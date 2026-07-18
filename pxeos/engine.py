"""Core provisioning engine."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Optional

from pxeos.cache import (
    TTLCacheWrapper,
    profile_cache_key,
    ttl_cache,
)
from pxeos.config import PxeOSConfig, load_profile
from pxeos.matcher import HostMatcher
from pxeos.models import BootAssets, HostRule, ProvisionProfile
from pxeos.registry import PluginRegistry
from pxeos.state import ProvisionState, ProvisionTracker

logger = logging.getLogger("pxeos.engine")

# Allowed variable names for #{variable} substitution in iPXE commands.
# Only these names are expanded; unknown names are left as-is.
_IPXE_ALLOWED_VARS = frozenset({
    "mac", "hostname", "profile", "os_family", "os_version",
    "arch", "vendor",
})

# Pattern that matches iPXE control flow and dangerous commands.
_IPXE_UNSAFE_RE = re.compile(
    r"^\s*(?:#!ipxe|chain\s|imgfetch\s|imgexec\s|exit\b|shell\b|sanboot\s)",
    re.IGNORECASE,
)


def _substitute_ipxe_vars(line: str, variables: dict[str, str]) -> str:
    """Replace ``#{name}`` placeholders with values from *variables*.

    Only names in ``_IPXE_ALLOWED_VARS`` are substituted.  Unknown
    placeholders are left verbatim so they cannot be used to inject
    arbitrary content.
    """
    def _replace(m: re.Match) -> str:
        name = m.group(1)
        if name in _IPXE_ALLOWED_VARS and name in variables:
            return variables[name]
        return m.group(0)  # leave unknown placeholders as-is

    return re.sub(r"#\{(\w+)\}", _replace, line)


def _validate_ipxe_command(cmd: str) -> bool:
    """Return True if *cmd* is safe to inject into an iPXE script.

    Rejects commands that could redirect boot flow (``chain``,
    ``imgfetch``, ``imgexec``, ``exit``, ``shell``, ``sanboot``)
    or that try to override the shebang line.
    """
    return not bool(_IPXE_UNSAFE_RE.match(cmd))


@ttl_cache(maxsize=64, ttl=300, name="profile_loader")
def _cached_load_profile(profile_path: str) -> ProvisionProfile:
    """Load a profile from disk with TTL caching."""
    return load_profile(Path(profile_path))

# iPXE script returned when netboot is disabled (boot-once complete).
# ``exit`` tells iPXE to fall through to the next boot device (local disk).
LOCAL_BOOT_SCRIPT = "#!ipxe\nexit\n"


class ProvisioningEngine:

    def __init__(
        self,
        registry: PluginRegistry,
        matcher: HostMatcher,
        config: PxeOSConfig,
        tracker: Optional[ProvisionTracker] = None,
    ) -> None:
        self._registry = registry
        self._matcher = matcher
        self._config = config
        self.tracker = tracker or ProvisionTracker()
        # Rendered-output caches keyed on (mac, profile_content_hash)
        self._ipxe_cache = TTLCacheWrapper(
            "ipxe_script", maxsize=256, ttl=300.0,
        )
        self._autoinstall_cache = TTLCacheWrapper(
            "autoinstall", maxsize=256, ttl=300.0,
        )

    def provision(
        self,
        mac: str,
        hostname: Optional[str] = None,
        subnet: Optional[str] = None,
        serial: Optional[str] = None,
        groups: Optional[list[str]] = None,
        arch: Optional[str] = None,
    ) -> BootAssets:
        from pxeos.metrics import provisions_total, active_provisions

        logger.info(
            "Provision request mac=%s hostname=%s",
            mac, hostname,
        )
        rule = self._resolve_rule(
            mac, hostname, subnet, serial, groups, arch
        )
        profile = self._load_profile_for_rule(rule)
        plugin = self._registry.get(rule.os_family)

        errors = plugin.validate_profile(profile)
        if errors:
            logger.warning(
                "Profile validation failed for %s: %s",
                profile.name, "; ".join(errors),
            )
            provisions_total.inc(
                os_family=rule.os_family, status="error",
            )
            raise ValueError(
                f"invalid profile {profile.name!r}: "
                + "; ".join(errors)
            )

        logger.info(
            "Provisioning mac=%s profile=%s os=%s/%s",
            mac, rule.profile, rule.os_family, rule.os_version,
        )
        provisions_total.inc(
            os_family=rule.os_family, status="success",
        )
        active_provisions.inc()
        return plugin.boot_assets(profile)

    def render_ipxe_script(self, mac: str) -> str:
        from pxeos.metrics import boot_requests_total

        boot_requests_total.inc()

        # Boot-once check: if netboot has been disabled for this MAC,
        # return a local-boot script so the machine boots from disk.
        if not self.tracker.is_netboot_enabled(mac):
            logger.info(
                "Netboot disabled for mac=%s, returning local boot",
                mac,
            )
            return LOCAL_BOOT_SCRIPT

        rule = self._resolve_rule(mac)
        profile_path = self._profile_path_for_rule(rule)
        phash = profile_cache_key(profile_path) if profile_path else "none"
        cache_key = (mac, rule.profile, phash)

        cached = self._ipxe_cache.get(cache_key)
        if cached is not None:
            # Still need to update state tracking even on cache hit
            self._ensure_tracked(mac, rule)
            self.tracker.transition(mac, ProvisionState.BOOTING)
            return cached

        profile = self._load_profile_for_rule(rule)
        plugin = self._registry.get(rule.os_family)
        is_live = profile.extra.get("live", False)

        if is_live and plugin.supports_live:
            assets = plugin.live_boot_assets(profile)
        else:
            assets = plugin.boot_assets(profile)

        # Register if not tracked, then transition to BOOTING
        self._ensure_tracked(mac, rule)
        self.tracker.transition(mac, ProvisionState.BOOTING)
        logger.info(
            "Boot script generated mac=%s profile=%s os=%s/%s",
            mac, rule.profile, rule.os_family, rule.os_version,
        )

        lines = [
            "#!ipxe",
            "",
        ]

        # Inject DHCP options as iPXE ``set`` commands
        for opt_name, opt_value in profile.dhcp_options.items():
            lines.append(f"set {opt_name} {opt_value}")
        if profile.dhcp_options:
            lines.append("")

        kernel_url = assets.kernel
        initrd_url = assets.initrd
        if profile.install_url:
            base = profile.install_url.rstrip("/")
            if not kernel_url.startswith(("http://", "https://")):
                kernel_url = f"{base}/{kernel_url.lstrip('/')}"
            if initrd_url and not initrd_url.startswith(("http://", "https://")):
                initrd_url = f"{base}/{initrd_url.lstrip('/')}"

        lines.append(f"kernel {kernel_url}")
        if initrd_url:
            lines.append(f"initrd {initrd_url}")

        # Inject custom iPXE commands before boot, with
        # variable substitution.
        if profile.ipxe_commands:
            hostname = profile.network.get(
                "hostname", profile.name
            )
            subst_vars = {
                "mac": mac,
                "hostname": hostname,
                "profile": profile.name,
                "os_family": profile.os_family,
                "os_version": profile.os_version,
                "arch": profile.arch,
                "vendor": profile.vendor,
            }
            for cmd in profile.ipxe_commands:
                if not _validate_ipxe_command(cmd):
                    logger.warning(
                        "Skipping unsafe iPXE command: %s",
                        cmd,
                    )
                    continue
                lines.append(
                    _substitute_ipxe_vars(cmd, subst_vars)
                )

        args = list(assets.boot_args)
        if not is_live:
            base_url = self._base_url()
            autoinstall_url = (
                f"{base_url}/api/v1/autoinstall/{mac}"
            )
            args.append(f"inst.ks={autoinstall_url}")
        lines.append(f"boot {' '.join(args)}")
        lines.append("")

        script = "\n".join(lines)
        self._ipxe_cache.put(cache_key, script)
        return script

    def get_autoinstall(self, mac: str) -> str:
        rule = self._resolve_rule(mac)
        profile_path = self._profile_path_for_rule(rule)
        phash = profile_cache_key(profile_path) if profile_path else "none"
        cache_key = (mac, rule.profile, phash)

        cached = self._autoinstall_cache.get(cache_key)
        if cached is not None:
            self._ensure_tracked(mac, rule)
            self.tracker.transition(mac, ProvisionState.INSTALLING)
            return cached

        profile = self._load_profile_for_rule(rule)
        plugin = self._registry.get(rule.os_family)

        # Register if not tracked, then transition to INSTALLING
        self._ensure_tracked(mac, rule)
        self.tracker.transition(mac, ProvisionState.INSTALLING)
        logger.info(
            "Autoinstall requested mac=%s state=installing",
            mac,
        )

        content = plugin.generate_autoinstall(profile)
        self._autoinstall_cache.put(cache_key, content)
        return content

    def invalidate_caches(self, mac: Optional[str] = None) -> int:
        """Invalidate rendered-output caches.

        If *mac* is provided only entries for that MAC are removed.
        Otherwise all entries in both rendered-output caches are cleared
        (the profile_loader TTL cache is also cleared).

        Returns the number of entries removed.
        """
        removed = 0
        if mac is None:
            removed += self._ipxe_cache.size
            removed += self._autoinstall_cache.size
            self._ipxe_cache.clear()
            self._autoinstall_cache.clear()
            _cached_load_profile.cache_clear()
        else:
            # Scan for keys that contain this MAC (atomic scan+remove)
            def _matches_mac(key):
                return isinstance(key, tuple) and len(key) >= 1 and key[0] == mac

            for cache in (self._ipxe_cache, self._autoinstall_cache):
                removed += cache.invalidate_matching(_matches_mac)
        return removed

    def get_rule(
        self,
        mac: str,
        hostname: Optional[str] = None,
        subnet: Optional[str] = None,
        serial: Optional[str] = None,
        groups: Optional[list[str]] = None,
        arch: Optional[str] = None,
    ) -> Optional[HostRule]:
        return self._matcher.match(
            mac=mac,
            hostname=hostname,
            subnet=subnet,
            serial=serial,
            groups=groups,
            arch=arch,
        )

    def _ensure_tracked(self, mac: str, rule: HostRule) -> None:
        """Register a provisioning record if one does not exist yet."""
        if self.tracker.get(mac) is None:
            self.tracker.register(
                mac=mac,
                profile=rule.profile,
                os_family=rule.os_family,
                os_version=rule.os_version,
            )

    def _resolve_rule(
        self,
        mac: str,
        hostname: Optional[str] = None,
        subnet: Optional[str] = None,
        serial: Optional[str] = None,
        groups: Optional[list[str]] = None,
        arch: Optional[str] = None,
    ) -> HostRule:
        rule = self._matcher.match(
            mac=mac,
            hostname=hostname,
            subnet=subnet,
            serial=serial,
            groups=groups,
            arch=arch,
        )
        if rule is None:
            raise ValueError(
                f"no matching host rule for MAC {mac!r}"
            )
        return rule

    def _profile_path_for_rule(
        self, rule: HostRule
    ) -> Optional[str]:
        """Return the on-disk path for the profile, or None."""
        if ".." in rule.profile or "/" in rule.profile:
            return None
        profiles_dir = self._config.data_dir / "profiles"
        profile_path = profiles_dir / f"{rule.profile}.toml"
        if profile_path.exists():
            return str(profile_path)
        return None

    def _load_profile_for_rule(
        self, rule: HostRule
    ) -> ProvisionProfile:
        if ".." in rule.profile or "/" in rule.profile:
            raise ValueError(
                f"invalid profile name: {rule.profile!r}"
            )
        profiles_dir = (
            self._config.data_dir / "profiles"
        )
        profile_path = profiles_dir / f"{rule.profile}.toml"
        if (
            profile_path.resolve().parent
            != profiles_dir.resolve()
        ):
            raise ValueError(
                f"invalid profile name: {rule.profile!r}"
            )
        if profile_path.exists():
            return _cached_load_profile(str(profile_path))

        return ProvisionProfile(
            name=rule.profile,
            os_family=rule.os_family,
            os_version=rule.os_version,
            vendor=rule.vendor,
        )

    def _base_url(self) -> str:
        scheme = (
            "https" if self._config.tls_cert else "http"
        )
        host = self._config.server_host
        if host == "0.0.0.0":
            host = "127.0.0.1"
        return f"{scheme}://{host}:{self._config.server_port}"
