"""Windows provisioning plugin using unattend.xml."""

from __future__ import annotations

import shutil
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional

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

# Microsoft unattend namespace
_UNATTEND_NS = "urn:schemas-microsoft-com:unattend"
_WCM_NS = (
    "http://schemas.microsoft.com/WMIConfig/2002/State"
)

# Valid configuration pass names per Microsoft docs
_VALID_PASSES = frozenset({
    "windowsPE",
    "offlineServicing",
    "generalize",
    "specialize",
    "auditSystem",
    "auditUser",
    "oobeSystem",
})

# Known Windows Setup component names (subset used by PxeOS)
_KNOWN_COMPONENTS = frozenset({
    "Microsoft-Windows-International-Core-WinPE",
    "Microsoft-Windows-International-Core",
    "Microsoft-Windows-Setup",
    "Microsoft-Windows-Shell-Setup",
    "Microsoft-Windows-TCPIP",
    "Microsoft-Windows-DNS-Client",
    "Microsoft-Windows-UnattendedJoin",
    "Microsoft-Windows-PnpCustomizationsWinPE",
    "Microsoft-Windows-PnpCustomizationsNonWinPE",
    "Microsoft-Windows-Deployment",
})

# Required elements in a valid unattend.xml
_REQUIRED_PASSES = {"windowsPE", "oobeSystem"}


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

        # Driver injection paths
        driver_paths: list[str] = profile.extra.get(
            "driver_paths", []
        )

        # SetupComplete.cmd script content
        setup_complete: str = profile.extra.get(
            "setup_complete", ""
        )

        # WinPE extra commands (startnet.cmd additions)
        winpe_commands: list[str] = profile.extra.get(
            "winpe_commands", []
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
            "driver_paths": driver_paths,
            "setup_complete": setup_complete,
            "winpe_commands": winpe_commands,
        }
        self._sanitize_context(context)
        return self._render_template(
            "unattend.xml.j2", context
        )

    def boot_assets(
        self, profile: ProvisionProfile
    ) -> BootAssets:
        base = profile.install_url.rstrip("/")

        # Build WinPE boot arguments
        boot_args_list: list[str] = []

        # Add custom WinPE boot arguments from profile
        winpe_boot_args: list[str] = profile.extra.get(
            "winpe_boot_args", []
        )
        boot_args_list.extend(winpe_boot_args)

        boot_args = tuple(boot_args_list)

        if profile.firmware == BootFirmware.UEFI:
            kernel = f"{base}/boot/bootmgfw.efi"
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

        # Validate driver paths
        driver_paths = profile.extra.get(
            "driver_paths", []
        )
        if not isinstance(driver_paths, list):
            errors.append(
                "driver_paths must be a list of "
                "path strings"
            )
        else:
            for i, dp in enumerate(driver_paths):
                if not isinstance(dp, str) or not dp.strip():
                    errors.append(
                        f"driver_paths[{i}] must be a "
                        f"non-empty string"
                    )

        # Validate winpe_boot_args
        winpe_boot_args = profile.extra.get(
            "winpe_boot_args", []
        )
        if not isinstance(winpe_boot_args, list):
            errors.append(
                "winpe_boot_args must be a list of "
                "strings"
            )

        # Validate setup_complete (must be a string
        # if provided)
        setup_complete = profile.extra.get(
            "setup_complete", ""
        )
        if not isinstance(setup_complete, str):
            errors.append(
                "setup_complete must be a string "
                "(path to SetupComplete script)"
            )

        return errors

    def validate_unattend_schema(
        self, xml_content: str
    ) -> list[str]:
        """Validate unattend.xml structure against
        the Microsoft schema conventions.

        Checks:
        - Well-formed XML
        - Correct root element and namespace
        - Valid configuration pass names
        - Known component names
        - Required passes present (windowsPE, oobeSystem)
        - Component structure (processorArchitecture attr)

        Returns a list of validation error strings.
        An empty list means the XML is valid.
        """
        errors: list[str] = []

        # 1. Parse XML (disable external entities
        # to prevent XXE attacks if fed untrusted input)
        try:
            parser = ET.XMLParser()
            # Attempt to disable entity resolution
            # for defense-in-depth (Python 3.8+)
            try:
                parser.parser.UseForeignDTD(False)
            except AttributeError:
                pass
            root = ET.fromstring(xml_content, parser)
        except ET.ParseError as exc:
            errors.append(f"XML parse error: {exc}")
            return errors

        # 2. Check root element
        expected_tag = f"{{{_UNATTEND_NS}}}unattend"
        if root.tag != expected_tag:
            errors.append(
                f"root element must be "
                f"'{{{_UNATTEND_NS}}}unattend', "
                f"got '{root.tag}'"
            )
            return errors

        # 3. Check settings passes
        ns = {"u": _UNATTEND_NS}
        settings_elements = root.findall(
            "u:settings", ns
        )

        if not settings_elements:
            errors.append(
                "no <settings> elements found"
            )
            return errors

        found_passes: set[str] = set()
        for settings in settings_elements:
            pass_name = settings.get("pass", "")
            if not pass_name:
                errors.append(
                    "<settings> element missing "
                    "'pass' attribute"
                )
                continue

            if pass_name not in _VALID_PASSES:
                errors.append(
                    f"invalid pass name "
                    f"'{pass_name}'; valid passes: "
                    f"{sorted(_VALID_PASSES)}"
                )
            else:
                found_passes.add(pass_name)

            # 4. Check components within each pass
            components = settings.findall(
                "u:component", ns
            )
            for comp in components:
                comp_name = comp.get("name", "")
                if not comp_name:
                    errors.append(
                        f"<component> in pass "
                        f"'{pass_name}' missing "
                        f"'name' attribute"
                    )
                    continue

                if comp_name not in _KNOWN_COMPONENTS:
                    errors.append(
                        f"unknown component "
                        f"'{comp_name}' in pass "
                        f"'{pass_name}'"
                    )

                # Check processorArchitecture attribute
                proc_arch = comp.get(
                    "processorArchitecture", ""
                )
                if not proc_arch:
                    errors.append(
                        f"component '{comp_name}' in "
                        f"pass '{pass_name}' missing "
                        f"'processorArchitecture' "
                        f"attribute"
                    )

        # 5. Check required passes
        for req_pass in _REQUIRED_PASSES:
            if req_pass not in found_passes:
                errors.append(
                    f"required pass '{req_pass}' "
                    f"not found"
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
