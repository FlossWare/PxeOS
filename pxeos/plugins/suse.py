"""SUSE (SLES / openSUSE) AutoYaST plugin."""

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

_SUPPORTED = [
    "15.5",
    "15.6",
    "leap-15.5",
    "leap-15.6",
    "tumbleweed",
]

_KERNEL_SUBPATH = Path("boot/x86_64/loader/linux")
_INITRD_SUBPATH = Path("boot/x86_64/loader/initrd")


class SUSEPlugin(OSPlugin):
    """AutoYaST-based provisioning for SUSE Linux.

    Covers SUSE Linux Enterprise Server (SLES), openSUSE Leap,
    and openSUSE Tumbleweed.  All use the YaST installer with
    AutoYaST XML profiles.
    """

    @property
    def os_family(self) -> str:
        return "suse"

    @property
    def supported_versions(self) -> list[str]:
        return list(_SUPPORTED)

    def autoinstall_filename(self) -> str:
        return "autoinst.xml"

    def generate_autoinstall(
        self, profile: ProvisionProfile
    ) -> str:
        context = {
            "profile": profile,
            "hostname": profile.network.get(
                "hostname", profile.name
            ),
            "domain": profile.network.get("domain", "local"),
            "bootproto": profile.network.get("bootproto", "dhcp"),
            "device": profile.network.get("device", "eth0"),
            "nameservers": profile.network.get("nameservers", []),
            "timezone": profile.extra.get(
                "timezone", "America/New_York"
            ),
            "lang": profile.extra.get("lang", "en_US.UTF-8"),
            "keyboard": profile.extra.get("keyboard", "english-us"),
            "disk_device": profile.disk.get(
                "device", "/dev/sda"
            ),
            "disk_partitions": profile.disk.get("partitions", []),
            "use_lvm": profile.disk.get("use_lvm", False),
            "packages": profile.packages,
            "post_scripts": profile.post_scripts,
            "install_url": profile.install_url,
            "registration_key": profile.extra.get(
                "registration_key", ""
            ),
            "registration_email": profile.extra.get(
                "registration_email", ""
            ),
            "firewall_enable": profile.extra.get(
                "firewall", True
            ),
        }
        self._sanitize_context(context)
        return self._render_template("autoyast.xml.j2", context)

    def boot_assets(
        self, profile: ProvisionProfile
    ) -> BootAssets:
        boot_args = [
            f"autoyast={profile.autoinstall_url}",
            f"install={profile.install_url}",
            "ip=dhcp",
            "splash=silent",
            "showopts",
        ]
        if profile.extra.get("serial_console"):
            boot_args.append(
                f"console={profile.extra['serial_console']}"
            )
        if profile.extra.get("self_update") is False:
            boot_args.append("self_update=0")

        if profile.firmware == BootFirmware.UEFI:
            template = "grub.cfg.j2"
        else:
            template = "pxelinux.cfg.j2"

        bootloader_cfg = self._render_template(
            template,
            {
                "profile": profile,
                "kernel": str(_KERNEL_SUBPATH),
                "initrd": str(_INITRD_SUBPATH),
                "boot_args": " ".join(boot_args),
                "menu_label": (
                    f"{profile.name} - SUSE "
                    f"{profile.os_version}"
                ),
            },
        )

        return BootAssets(
            kernel=str(_KERNEL_SUBPATH),
            initrd=str(_INITRD_SUBPATH),
            boot_args=tuple(boot_args),
            bootloader_config=bootloader_cfg,
        )

    def validate_profile(
        self, profile: ProvisionProfile
    ) -> list[str]:
        errors = super().validate_profile(profile)
        if not profile.install_url:
            errors.append(
                "install_url is required for AutoYaST installs"
            )
        if not profile.autoinstall_url:
            errors.append(
                "autoinstall_url is required "
                "(points to the AutoYaST XML profile)"
            )
        if profile.arch not in ("x86_64", "aarch64"):
            errors.append(
                f"unsupported arch {profile.arch!r} for SUSE"
            )
        return errors

    def extract_from_iso(
        self, mount_path: Path, dest: Path
    ) -> DistroAssets:
        dest.mkdir(parents=True, exist_ok=True)

        kernel_src = mount_path / _KERNEL_SUBPATH
        initrd_src = mount_path / _INITRD_SUBPATH

        kernel_dst = dest / "linux"
        initrd_dst = dest / "initrd"

        shutil.copy2(kernel_src, kernel_dst)
        shutil.copy2(initrd_src, initrd_dst)

        # Copy the repo content (suse/ or product/ trees).
        repo_dst = dest / "repo"
        repo_dst.mkdir(parents=True, exist_ok=True)
        for subdir in ("suse", "product", "repodata", "noarch"):
            src = mount_path / subdir
            if src.exists():
                shutil.copytree(
                    src,
                    repo_dst / subdir,
                    dirs_exist_ok=True,
                )

        boot_loader_dst = None
        efi_src = mount_path / "EFI" / "BOOT"
        if efi_src.exists():
            boot_loader_dst = dest / "EFI" / "BOOT"
            shutil.copytree(
                efi_src, boot_loader_dst, dirs_exist_ok=True
            )

        return DistroAssets(
            kernel_path=kernel_dst,
            initrd_path=initrd_dst,
            repo_path=repo_dst,
            boot_loader_path=boot_loader_dst,
        )
