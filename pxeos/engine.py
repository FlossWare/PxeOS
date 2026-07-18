"""Core provisioning engine."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from pxeos.cache import ttl_cache
from pxeos.config import PxeOSConfig, load_profile
from pxeos.matcher import HostMatcher
from pxeos.models import BootAssets, HostRule, ProvisionProfile
from pxeos.registry import PluginRegistry
from pxeos.state import ProvisionState, ProvisionTracker


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

    def provision(
        self,
        mac: str,
        hostname: Optional[str] = None,
        subnet: Optional[str] = None,
        serial: Optional[str] = None,
        groups: Optional[list[str]] = None,
        arch: Optional[str] = None,
    ) -> BootAssets:
        rule = self._resolve_rule(
            mac, hostname, subnet, serial, groups, arch
        )
        profile = self._load_profile_for_rule(rule)
        plugin = self._registry.get(rule.os_family)

        errors = plugin.validate_profile(profile)
        if errors:
            raise ValueError(
                f"invalid profile {profile.name!r}: "
                + "; ".join(errors)
            )

        return plugin.boot_assets(profile)

    def render_ipxe_script(self, mac: str) -> str:
        # Boot-once check: if netboot has been disabled for this MAC,
        # return a local-boot script so the machine boots from disk.
        if not self.tracker.is_netboot_enabled(mac):
            return LOCAL_BOOT_SCRIPT

        rule = self._resolve_rule(mac)
        profile = self._load_profile_for_rule(rule)
        plugin = self._registry.get(rule.os_family)
        is_live = profile.extra.get("live", False)

        if is_live and plugin.supports_live:
            assets = plugin.live_boot_assets(profile)
        else:
            assets = plugin.boot_assets(profile)

        # Register if not tracked, then transition to BOOTING
        if self.tracker.get(mac) is None:
            self.tracker.register(
                mac=mac,
                profile=rule.profile,
                os_family=rule.os_family,
                os_version=rule.os_version,
            )
        self.tracker.transition(mac, ProvisionState.BOOTING)

        lines = [
            "#!ipxe",
            "",
            f"kernel {assets.kernel}",
        ]
        if assets.initrd:
            lines.append(f"initrd {assets.initrd}")

        args = list(assets.boot_args)
        if not is_live:
            base_url = self._base_url()
            autoinstall_url = (
                f"{base_url}/api/v1/autoinstall/{mac}"
            )
            args.append(f"inst.ks={autoinstall_url}")
        lines.append(f"boot {' '.join(args)}")
        lines.append("")

        return "\n".join(lines)

    def get_autoinstall(self, mac: str) -> str:
        rule = self._resolve_rule(mac)
        profile = self._load_profile_for_rule(rule)
        plugin = self._registry.get(rule.os_family)

        # Register if not tracked, then transition to INSTALLING
        if self.tracker.get(mac) is None:
            self.tracker.register(
                mac=mac,
                profile=rule.profile,
                os_family=rule.os_family,
                os_version=rule.os_version,
            )
        self.tracker.transition(mac, ProvisionState.INSTALLING)

        return plugin.generate_autoinstall(profile)

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
