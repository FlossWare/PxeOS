"""OpenBSD provisioning plugin using autoinstall(8)."""

from __future__ import annotations

import shutil
from pathlib import Path
from urllib.parse import urlparse

from pxeos.models import (
    BootAssets,
    BootFirmware,
    DistroAssets,
    ProvisionProfile,
)
from pxeos.plugins.base import OSPlugin

# OpenBSD distribution sets vary by version; the version
# number is embedded in filenames (e.g. base75.tgz for 7.5).
_DIST_SETS = (
    "base",
    "comp",
    "man",
    "game",
    "xbase",
    "xshare",
    "xfont",
    "xserv",
)


def _version_tag(version: str) -> str:
    """Convert '7.5' to '75' for set filenames."""
    return version.replace(".", "")


class OpenBSDPlugin(OSPlugin):

    @property
    def os_family(self) -> str:
        return "openbsd"

    @property
    def supported_versions(self) -> list[str]:
        return ["7.4", "7.5", "7.6"]

    def autoinstall_filename(self) -> str:
        return "install.conf"

    def generate_autoinstall(
        self, profile: ProvisionProfile
    ) -> str:
        network_cfg = profile.network or {}
        disk_cfg = profile.disk or {}

        hostname = network_cfg.get(
            "hostname", profile.name
        )
        domain = network_cfg.get("domain", "local")
        iface = network_cfg.get("interface", "em0")
        use_dhcp = network_cfg.get("dhcp", True)
        ipv4 = network_cfg.get("address", "")
        netmask = network_cfg.get("netmask", "255.255.255.0")
        gateway = network_cfg.get("gateway", "none")
        nameservers = network_cfg.get(
            "nameservers", ["8.8.8.8"]
        )

        disk_device = disk_cfg.get("device", "sd0")
        disk_layout = disk_cfg.get("layout", "whole")

        root_password = profile.extra.get(
            "root_password",
            "$2b$10$xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
        )
        timezone = profile.extra.get("timezone", "UTC")
        username = profile.extra.get("user", "")
        user_password = profile.extra.get("user_password", "")
        x11 = profile.extra.get("x11", False)

        vtag = _version_tag(profile.os_version)
        selected_sets = profile.extra.get(
            "sets",
            [f"base{vtag}.tgz", f"comp{vtag}.tgz"],
        )
        install_url = profile.install_url or ""

        # Parse URL into server + path for install.conf
        http_server = ""
        server_directory = (
            f"pub/OpenBSD/{profile.os_version}/"
            f"{profile.arch or 'amd64'}"
        )
        if install_url:
            parsed = urlparse(install_url)
            http_server = parsed.hostname or ""
            if parsed.path and parsed.path != "/":
                server_directory = parsed.path.strip("/")

        context = {
            "profile": profile,
            "hostname": hostname,
            "domain": domain,
            "iface": iface,
            "use_dhcp": use_dhcp,
            "ipv4": ipv4,
            "netmask": netmask,
            "gateway": gateway,
            "nameservers": nameservers,
            "disk_device": disk_device,
            "disk_layout": disk_layout,
            "root_password": root_password,
            "timezone": timezone,
            "username": username,
            "user_password": user_password,
            "x11": x11,
            "selected_sets": selected_sets,
            "install_url": install_url,
            "http_server": http_server,
            "server_directory": server_directory,
            "vtag": vtag,
            "post_scripts": profile.post_scripts,
            "packages": profile.packages,
        }
        return self._render_template(
            "install.conf.j2", context
        )

    def boot_assets(
        self, profile: ProvisionProfile
    ) -> BootAssets:
        base = profile.install_url.rstrip("/")
        version = profile.os_version
        arch = profile.arch or "amd64"

        # OpenBSD PXE boots bsd.rd which is both kernel
        # and installer ramdisk combined.
        kernel = f"{base}/{version}/{arch}/bsd.rd"

        if profile.firmware == BootFirmware.UEFI:
            boot_args = (
                f"tftproot={base}/{version}/{arch}/",
            )
            config = (
                f"# OpenBSD {version} UEFI PXE boot\n"
                f"# DHCP must serve bsd.rd as boot file\n"
                f"# autoinstall fetches install.conf "
                f"via HTTP from next-server\n"
            )
        else:
            boot_args = (
                f"tftproot={base}/{version}/{arch}/",
            )
            config = (
                f"# OpenBSD {version} BIOS PXE boot\n"
                f"# DHCP option next-server points to "
                f"TFTP with bsd.rd\n"
                f"# autoinstall(8) fetches "
                f"http://SERVER_IP/install.conf\n"
            )

        return BootAssets(
            kernel=kernel,
            initrd=None,
            boot_args=boot_args,
            bootloader_config=config,
        )

    def validate_profile(
        self, profile: ProvisionProfile
    ) -> list[str]:
        errors = super().validate_profile(profile)

        if not profile.install_url:
            errors.append(
                "install_url is required for OpenBSD "
                "(HTTP path to sets directory)"
            )

        arch = profile.arch or "amd64"
        if arch not in ("amd64", "arm64", "i386"):
            errors.append(
                f"unsupported architecture {arch!r}; "
                f"OpenBSD supports amd64, arm64, i386"
            )

        return errors

    def extract_from_iso(
        self, mount_path: Path, dest: Path
    ) -> DistroAssets:
        boot_dir = dest / "boot"
        repo_dir = dest / "repo"
        boot_dir.mkdir(parents=True, exist_ok=True)
        repo_dir.mkdir(parents=True, exist_ok=True)

        # bsd.rd is the combined kernel + ramdisk installer
        bsd_rd_dst = boot_dir / "bsd.rd"
        for candidate in (
            mount_path / "bsd.rd",
            mount_path / "7.6" / "amd64" / "bsd.rd",
            mount_path / "7.5" / "amd64" / "bsd.rd",
            mount_path / "7.4" / "amd64" / "bsd.rd",
        ):
            if candidate.exists():
                shutil.copy2(candidate, bsd_rd_dst)
                break

        # Copy distribution sets (baseXX.tgz, compXX.tgz, ...)
        for item in mount_path.rglob("*.tgz"):
            shutil.copy2(item, repo_dir / item.name)

        return DistroAssets(
            kernel_path=bsd_rd_dst,
            initrd_path=None,
            repo_path=repo_dir,
            boot_loader_path=None,
        )
