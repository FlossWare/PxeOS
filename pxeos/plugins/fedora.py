"""Fedora/RHEL/CentOS/Rocky/Alma Kickstart plugin."""

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

_FEDORA_VERSIONS = ["38", "39", "40", "41", "42"]
_RHEL_VERSIONS = ["8", "9"]

_KERNEL_SUBPATH = Path("images/pxeboot/vmlinuz")
_INITRD_SUBPATH = Path("images/pxeboot/initrd.img")


class FedoraPlugin(OSPlugin):
    """Kickstart-based provisioning for the Fedora family.

    Covers Fedora, RHEL, CentOS Stream, Rocky Linux, and
    AlmaLinux.  All use the Anaconda installer with Kickstart
    configuration files.
    """

    @property
    def os_family(self) -> str:
        return "fedora"

    @property
    def supported_versions(self) -> list[str]:
        return _FEDORA_VERSIONS + _RHEL_VERSIONS

    def autoinstall_filename(self) -> str:
        return "ks.cfg"

    def generate_autoinstall(
        self, profile: ProvisionProfile
    ) -> str:
        context = {
            "profile": profile,
            "hostname": profile.network.get(
                "hostname", profile.name
            ),
            "bootproto": profile.network.get("bootproto", "dhcp"),
            "device": profile.network.get("device", "link"),
            "nameservers": profile.network.get("nameservers", []),
            "timezone": profile.extra.get(
                "timezone", "America/New_York"
            ),
            "lang": profile.extra.get("lang", "en_US.UTF-8"),
            "keyboard": profile.extra.get("keyboard", "us"),
            "disk_method": profile.disk.get("method", "auto"),
            "disk_device": profile.disk.get("device", ""),
            "disk_partitions": profile.disk.get("partitions", []),
            "packages": profile.packages,
            "post_scripts": profile.post_scripts,
            "install_url": profile.install_url,
            "rootpw_lock": profile.extra.get("rootpw_lock", True),
            "selinux": profile.extra.get("selinux", "enforcing"),
            "firewall": profile.extra.get("firewall", True),
            "reboot": profile.extra.get("reboot", True),
        }
        return self._render_template("kickstart.cfg.j2", context)

    def boot_assets(
        self, profile: ProvisionProfile
    ) -> BootAssets:
        boot_args = [
            f"inst.ks={profile.autoinstall_url}",
            f"inst.repo={profile.install_url}",
            "ip=dhcp",
        ]
        if profile.extra.get("serial_console"):
            boot_args.append(
                f"console={profile.extra['serial_console']}"
            )

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
                    f"{profile.name} - Fedora Family "
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
                "install_url is required for Kickstart installs"
            )
        if not profile.autoinstall_url:
            errors.append(
                "autoinstall_url is required "
                "(points to the Kickstart file)"
            )
        if profile.arch not in ("x86_64", "aarch64", "ppc64le"):
            errors.append(
                f"unsupported arch {profile.arch!r} "
                f"for {self.os_family}"
            )
        return errors

    def extract_from_iso(
        self, mount_path: Path, dest: Path
    ) -> DistroAssets:
        kernel_src = mount_path / _KERNEL_SUBPATH
        initrd_src = mount_path / _INITRD_SUBPATH
        repo_src = mount_path

        kernel_dst = dest / "vmlinuz"
        initrd_dst = dest / "initrd.img"
        repo_dst = dest / "repo"

        dest.mkdir(parents=True, exist_ok=True)
        repo_dst.mkdir(parents=True, exist_ok=True)

        shutil.copy2(kernel_src, kernel_dst)
        shutil.copy2(initrd_src, initrd_dst)

        # Copy the repository tree (Packages, repodata).
        for subdir in ("Packages", "repodata", "BaseOS", "AppStream"):
            src = repo_src / subdir
            if src.exists():
                shutil.copytree(
                    src,
                    repo_dst / subdir,
                    dirs_exist_ok=True,
                )

        # UEFI boot loader (if present).
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
