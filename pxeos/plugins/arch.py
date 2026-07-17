"""Arch Linux archinstall plugin."""

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

_SUPPORTED = ["latest", "rolling"]

_KERNEL_SUBPATH = Path(
    "arch/boot/x86_64/vmlinuz-linux"
)
_INITRD_SUBPATH = Path(
    "arch/boot/x86_64/initramfs-linux.img"
)


class ArchPlugin(OSPlugin):
    """archinstall JSON provisioning for Arch Linux.

    Generates ``user_configuration.json`` files consumed by the
    ``archinstall`` guided installer.  The PXE boot environment
    passes the configuration URL to archinstall via kernel
    command-line arguments.
    """

    @property
    def os_family(self) -> str:
        return "arch"

    @property
    def supported_versions(self) -> list[str]:
        return list(_SUPPORTED)

    def autoinstall_filename(self) -> str:
        return "user_configuration.json"

    def generate_autoinstall(
        self, profile: ProvisionProfile
    ) -> str:
        context = {
            "profile": profile,
            "hostname": profile.network.get(
                "hostname", profile.name
            ),
            "timezone": profile.extra.get(
                "timezone", "America/New_York"
            ),
            "locale": profile.extra.get("locale", "en_US.UTF-8"),
            "keyboard": profile.extra.get("keyboard", "us"),
            "bootloader": profile.extra.get(
                "bootloader", "systemd-bootctl"
            ),
            "disk_device": profile.disk.get(
                "device", "/dev/sda"
            ),
            "disk_layout": profile.disk.get("layout", {}),
            "filesystem": profile.disk.get("filesystem", "ext4"),
            "packages": profile.packages,
            "post_scripts": profile.post_scripts,
            "install_url": profile.install_url,
            "mirror_region": profile.extra.get(
                "mirror_region", "United States"
            ),
            "audio": profile.extra.get("audio", "pipewire"),
            "kernels": profile.extra.get(
                "kernels", ["linux"]
            ),
            "services": profile.extra.get("services", []),
            "users": profile.extra.get("users", []),
        }
        return self._render_template(
            "archinstall.json.j2", context
        )

    def boot_assets(
        self, profile: ProvisionProfile
    ) -> BootAssets:
        boot_args = [
            "archisobasedir=arch",
            "archiso_http_srv="
            f"{profile.install_url.rstrip('/')}/",
            f"archinstall_config={profile.autoinstall_url}",
            "ip=dhcp",
        ]
        if profile.extra.get("serial_console"):
            boot_args.append(
                f"console={profile.extra['serial_console']}"
            )
        if profile.extra.get("cow_spacesize"):
            boot_args.append(
                f"cow_spacesize={profile.extra['cow_spacesize']}"
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
                    f"{profile.name} - Arch Linux"
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
                "(URL to user_configuration.json)"
            )
        if profile.arch not in ("x86_64",):
            errors.append(
                f"unsupported arch {profile.arch!r} "
                f"for Arch Linux"
            )
        return errors

    def extract_from_iso(
        self, mount_path: Path, dest: Path
    ) -> DistroAssets:
        dest.mkdir(parents=True, exist_ok=True)

        kernel_src = mount_path / _KERNEL_SUBPATH
        initrd_src = mount_path / _INITRD_SUBPATH

        kernel_dst = dest / "vmlinuz-linux"
        initrd_dst = dest / "initramfs-linux.img"

        shutil.copy2(kernel_src, kernel_dst)
        shutil.copy2(initrd_src, initrd_dst)

        # Copy the airootfs squashfs image.
        repo_dst = dest / "arch"
        repo_dst.mkdir(parents=True, exist_ok=True)
        airootfs_src = mount_path / "arch" / "x86_64"
        if airootfs_src.exists():
            shutil.copytree(
                airootfs_src,
                repo_dst / "x86_64",
                dirs_exist_ok=True,
            )

        # Arch ISOs include syslinux rather than EFI shim,
        # but check for EFI anyway.
        boot_loader_dst = None
        efi_src = mount_path / "EFI"
        if efi_src.exists():
            boot_loader_dst = dest / "EFI"
            shutil.copytree(
                efi_src, boot_loader_dst, dirs_exist_ok=True
            )

        return DistroAssets(
            kernel_path=kernel_dst,
            initrd_path=initrd_dst,
            repo_path=repo_dst,
            boot_loader_path=boot_loader_dst,
        )
