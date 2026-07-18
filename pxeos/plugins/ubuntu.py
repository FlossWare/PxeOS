"""Ubuntu Cloud-Init autoinstall plugin."""

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

_SUPPORTED = ["22.04", "24.04", "24.10"]

_KERNEL_SUBPATH = Path("casper/vmlinuz")
_INITRD_SUBPATH = Path("casper/initrd")
_LIVE_SQUASHFS = Path("casper/filesystem.squashfs")


class UbuntuPlugin(OSPlugin):
    """Cloud-Init autoinstall provisioning for Ubuntu.

    Generates ``user-data`` YAML files consumed by the Subiquity
    installer via the ``autoinstall`` directive during PXE boot.
    """

    @property
    def os_family(self) -> str:
        return "ubuntu"

    @property
    def supported_versions(self) -> list[str]:
        return list(_SUPPORTED)

    def autoinstall_filename(self) -> str:
        return "user-data"

    def generate_autoinstall(
        self, profile: ProvisionProfile
    ) -> str:
        context = {
            "profile": profile,
            "hostname": profile.network.get(
                "hostname", profile.name
            ),
            "username": profile.extra.get("username", "ubuntu"),
            "timezone": profile.extra.get(
                "timezone", "America/New_York"
            ),
            "locale": profile.extra.get("locale", "en_US.UTF-8"),
            "keyboard_layout": profile.extra.get(
                "keyboard", "us"
            ),
            "disk_method": profile.disk.get("method", "lvm"),
            "disk_device": profile.disk.get("device", ""),
            "disk_layout": profile.disk.get("layout", {}),
            "network_config": profile.network,
            "packages": profile.packages,
            "post_scripts": profile.post_scripts,
            "install_url": profile.install_url,
            "ssh_import_id": profile.extra.get(
                "ssh_import_id", []
            ),
            "ssh_authorized_keys": profile.extra.get(
                "ssh_authorized_keys", []
            ),
            "autoinstall_version": profile.extra.get(
                "autoinstall_version", 1
            ),
        }
        return self._render_template(
            "cloud-init.yaml.j2", context
        )

    def boot_assets(
        self, profile: ProvisionProfile
    ) -> BootAssets:
        # The semicolon in ds= must not be shell-escaped;
        # it is part of the kernel cmdline syntax.
        autoinstall_base = profile.autoinstall_url.rstrip("/")
        boot_args = [
            "autoinstall",
            f"ds=nocloud-net;s={autoinstall_base}/",
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
                    f"{profile.name} - Ubuntu "
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
        if not profile.autoinstall_url:
            errors.append(
                "autoinstall_url is required "
                "(base URL serving user-data and meta-data)"
            )
        if profile.arch not in ("amd64", "x86_64", "arm64"):
            errors.append(
                f"unsupported arch {profile.arch!r} for Ubuntu"
            )
        return errors

    @property
    def supports_live(self) -> bool:
        return True

    def extract_live_assets(
        self, mount_path: Path, dest: Path
    ) -> DistroAssets:
        dest.mkdir(parents=True, exist_ok=True)

        kernel_src = mount_path / _KERNEL_SUBPATH
        initrd_src = mount_path / _INITRD_SUBPATH

        kernel_dst = dest / "vmlinuz"
        initrd_dst = dest / "initrd"

        shutil.copy2(kernel_src, kernel_dst)
        shutil.copy2(initrd_src, initrd_dst)

        rootfs_dst = dest / "casper"
        rootfs_dst.mkdir(parents=True, exist_ok=True)
        squashfs_src = mount_path / _LIVE_SQUASHFS
        squashfs_dst = rootfs_dst / "filesystem.squashfs"
        shutil.copy2(squashfs_src, squashfs_dst)

        boot_loader_dst = None
        efi_src = mount_path / "EFI" / "boot"
        if efi_src.exists():
            boot_loader_dst = dest / "EFI" / "boot"
            shutil.copytree(
                efi_src, boot_loader_dst, dirs_exist_ok=True
            )

        return DistroAssets(
            kernel_path=kernel_dst,
            initrd_path=initrd_dst,
            repo_path=rootfs_dst,
            boot_loader_path=boot_loader_dst,
            squashfs_path=squashfs_dst,
        )

    def live_boot_assets(
        self, profile: ProvisionProfile
    ) -> BootAssets:
        rootfs_url = (
            f"{profile.install_url.rstrip('/')}"
            f"/casper/filesystem.squashfs"
        )
        boot_args = [
            "boot=casper",
            f"fetch={rootfs_url}",
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
                    f"{profile.name} - Ubuntu Live "
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

    def extract_from_iso(
        self, mount_path: Path, dest: Path
    ) -> DistroAssets:
        dest.mkdir(parents=True, exist_ok=True)

        kernel_src = mount_path / _KERNEL_SUBPATH
        initrd_src = mount_path / _INITRD_SUBPATH

        kernel_dst = dest / "vmlinuz"
        initrd_dst = dest / "initrd"

        shutil.copy2(kernel_src, kernel_dst)
        shutil.copy2(initrd_src, initrd_dst)

        # The squashfs filesystem and casper directory.
        repo_dst = dest / "casper"
        repo_dst.mkdir(parents=True, exist_ok=True)
        casper_src = mount_path / "casper"
        if casper_src.exists():
            for item in casper_src.iterdir():
                dst = repo_dst / item.name
                if item.is_file():
                    shutil.copy2(item, dst)

        boot_loader_dst = None
        efi_src = mount_path / "EFI" / "boot"
        if efi_src.exists():
            boot_loader_dst = dest / "EFI" / "boot"
            shutil.copytree(
                efi_src, boot_loader_dst, dirs_exist_ok=True
            )

        return DistroAssets(
            kernel_path=kernel_dst,
            initrd_path=initrd_dst,
            repo_path=repo_dst,
            boot_loader_path=boot_loader_dst,
        )
