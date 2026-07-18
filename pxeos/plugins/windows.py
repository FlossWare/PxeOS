"""Windows provisioning plugin using unattend.xml."""

from __future__ import annotations

import shutil
from pathlib import Path

from pxeos.models import (
    BootAssets,
    BootFirmware,
    DistroAssets,
    ProvisionProfile,
)
from pxeos.plugins.base import OSPlugin

# Map of Windows version identifiers to friendly names.
_VERSION_NAMES = {
    "10": "Windows 10",
    "11": "Windows 11",
    "2019": "Windows Server 2019",
    "2022": "Windows Server 2022",
    "2025": "Windows Server 2025",
}

# Server versions use Server Core / Desktop Experience.
_SERVER_VERSIONS = {"2019", "2022", "2025"}


class WindowsPlugin(OSPlugin):

    @property
    def os_family(self) -> str:
        return "windows"

    @property
    def supported_versions(self) -> list[str]:
        return ["10", "11", "2019", "2022", "2025"]

    def autoinstall_filename(self) -> str:
        return "unattend.xml"

    def generate_autoinstall(
        self, profile: ProvisionProfile
    ) -> str:
        network_cfg = profile.network or {}
        disk_cfg = profile.disk or {}

        hostname = network_cfg.get(
            "hostname", profile.name
        )
        use_dhcp = network_cfg.get("dhcp", True)
        ipv4 = network_cfg.get("address", "")
        netmask = network_cfg.get(
            "prefix_length", "24"
        )
        gateway = network_cfg.get("gateway", "")
        nameservers = network_cfg.get(
            "nameservers", ["8.8.8.8"]
        )

        disk_id = disk_cfg.get("disk_id", "0")
        is_uefi = profile.firmware == BootFirmware.UEFI

        product_key = profile.extra.get("product_key", "")
        admin_password = profile.extra.get(
            "admin_password", ""
        )
        timezone_win = profile.extra.get(
            "timezone", "UTC"
        )
        locale = profile.extra.get("locale", "en-US")
        input_locale = profile.extra.get(
            "input_locale", locale
        )
        organization = profile.extra.get(
            "organization", ""
        )
        owner = profile.extra.get("owner", "User")
        auto_logon = profile.extra.get("auto_logon", True)
        auto_logon_count = profile.extra.get(
            "auto_logon_count", 1
        )

        is_server = (
            profile.os_version in _SERVER_VERSIONS
        )
        image_name = profile.extra.get("image_name", "")
        if not image_name:
            if is_server:
                image_name = (
                    "Windows Server "
                    f"{profile.os_version} SERVERSTANDARDCORE"
                )
            else:
                image_name = (
                    f"Windows {profile.os_version} Pro"
                )

        version_name = _VERSION_NAMES.get(
            profile.os_version,
            f"Windows {profile.os_version}",
        )

        context = {
            "profile": profile,
            "hostname": hostname,
            "use_dhcp": use_dhcp,
            "ipv4": ipv4,
            "netmask": netmask,
            "gateway": gateway,
            "nameservers": nameservers,
            "disk_id": disk_id,
            "is_uefi": is_uefi,
            "product_key": product_key,
            "admin_password": admin_password,
            "timezone": timezone_win,
            "locale": locale,
            "input_locale": input_locale,
            "organization": organization,
            "owner": owner,
            "auto_logon": auto_logon,
            "auto_logon_count": auto_logon_count,
            "is_server": is_server,
            "image_name": image_name,
            "version_name": version_name,
            "packages": profile.packages,
            "post_scripts": profile.post_scripts,
        }
        self._sanitize_context(context)
        return self._render_template(
            "unattend.xml.j2", context
        )

    def boot_assets(
        self, profile: ProvisionProfile
    ) -> BootAssets:
        base = profile.install_url.rstrip("/")

        if profile.firmware == BootFirmware.UEFI:
            kernel = f"{base}/boot/bootmgfw.efi"
            boot_args = ()
            config = (
                "# Windows UEFI PXE boot\n"
                "# bootmgfw.efi loads BCD and "
                "boot.wim from TFTP share\n"
                "# BCD must reference \\boot\\boot.wim "
                "for WinPE\n"
                f"# WinPE fetches unattend.xml from "
                f"{profile.autoinstall_url}\n"
            )
        else:
            kernel = f"{base}/boot/pxeboot.n12"
            boot_args = ()
            config = (
                "# Windows BIOS PXE boot\n"
                "# pxeboot.n12 loads bootmgr.exe and "
                "BCD via TFTP\n"
                "# BCD must reference \\boot\\boot.wim "
                "for WinPE\n"
                f"# WinPE fetches unattend.xml from "
                f"{profile.autoinstall_url}\n"
            )

        return BootAssets(
            kernel=kernel,
            initrd=f"{base}/boot/boot.wim",
            boot_args=boot_args,
            bootloader_config=config,
        )

    def validate_profile(
        self, profile: ProvisionProfile
    ) -> list[str]:
        errors = super().validate_profile(profile)

        if not profile.install_url:
            errors.append(
                "install_url is required for Windows "
                "(path to WIM/installation share)"
            )

        arch = profile.arch or "x86_64"
        if arch not in ("x86_64", "amd64", "x86"):
            errors.append(
                f"unsupported architecture {arch!r}; "
                f"Windows supports x86_64, amd64, x86"
            )

        if profile.extra.get("product_key"):
            key = profile.extra["product_key"]
            parts = key.split("-")
            if len(parts) != 5 or not all(
                len(p) == 5 for p in parts
            ):
                errors.append(
                    "product_key must be in "
                    "XXXXX-XXXXX-XXXXX-XXXXX-XXXXX format"
                )

        return errors

    def extract_from_iso(
        self, mount_path: Path, dest: Path
    ) -> DistroAssets:
        boot_dir = dest / "boot"
        sources_dir = dest / "sources"
        boot_dir.mkdir(parents=True, exist_ok=True)
        sources_dir.mkdir(parents=True, exist_ok=True)

        # Windows boot files (case-insensitive search)
        boot_wim_dst = boot_dir / "boot.wim"
        install_wim_dst = sources_dir / "install.wim"
        bootmgfw_dst = boot_dir / "bootmgfw.efi"
        pxeboot_dst = boot_dir / "pxeboot.n12"

        # boot.wim -- WinPE image
        for candidate in (
            mount_path / "boot" / "boot.wim",
            mount_path / "Boot" / "boot.wim",
            mount_path / "boot" / "Boot.wim",
        ):
            if candidate.exists():
                shutil.copy2(candidate, boot_wim_dst)
                break

        # install.wim -- Windows image
        for candidate in (
            mount_path / "sources" / "install.wim",
            mount_path / "Sources" / "install.wim",
            mount_path / "sources" / "install.esd",
            mount_path / "Sources" / "install.esd",
        ):
            if candidate.exists():
                shutil.copy2(
                    candidate, install_wim_dst
                )
                break

        # UEFI bootloader
        for candidate in (
            mount_path / "efi" / "boot" / "bootx64.efi",
            mount_path / "EFI" / "Boot" / "bootx64.efi",
            mount_path / "efi" / "boot" / "bootmgfw.efi",
        ):
            if candidate.exists():
                shutil.copy2(candidate, bootmgfw_dst)
                break

        # BIOS PXE bootstrap
        pxeboot_src = mount_path / "boot" / "pxeboot.n12"
        if pxeboot_src.exists():
            shutil.copy2(pxeboot_src, pxeboot_dst)

        # Copy BCD store
        for candidate in (
            mount_path / "boot" / "bcd",
            mount_path / "Boot" / "BCD",
            mount_path / "boot" / "BCD",
        ):
            if candidate.exists():
                shutil.copy2(
                    candidate, boot_dir / "BCD"
                )
                break

        boot_loader = (
            bootmgfw_dst
            if bootmgfw_dst.exists()
            else (
                pxeboot_dst
                if pxeboot_dst.exists()
                else None
            )
        )

        return DistroAssets(
            kernel_path=boot_wim_dst,
            initrd_path=None,
            repo_path=sources_dir,
            boot_loader_path=boot_loader,
        )
