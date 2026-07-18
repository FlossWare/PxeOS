"""Debian preseed plugin."""

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

_SUPPORTED = ["11", "12", "13"]

_KERNEL_CANDIDATES = ("install.amd/vmlinuz", "install.amd/linux")
_INITRD_SUBPATH = Path("install.amd/initrd.gz")
_LIVE_KERNEL = Path("live/vmlinuz")
_LIVE_INITRD = Path("live/initrd.img")
_LIVE_SQUASHFS = Path("live/filesystem.squashfs")


class DebianPlugin(OSPlugin):
    """Preseed-based provisioning for Debian GNU/Linux.

    Generates ``preseed.cfg`` files consumed by the Debian
    Installer (d-i) during network boot.
    """

    @property
    def os_family(self) -> str:
        return "debian"

    @property
    def supported_versions(self) -> list[str]:
        return list(_SUPPORTED)

    def autoinstall_filename(self) -> str:
        return "preseed.cfg"

    def generate_autoinstall(
        self, profile: ProvisionProfile
    ) -> str:
        context = {
            "profile": profile,
            "locale": profile.extra.get("locale", "en_US.UTF-8"),
            "keyboard_layout": profile.extra.get(
                "keyboard", "us"
            ),
            "timezone": profile.extra.get(
                "timezone", "America/New_York"
            ),
            "hostname": profile.network.get(
                "hostname", profile.name
            ),
            "domain": profile.network.get("domain", "local"),
            "bootproto": profile.network.get("bootproto", "dhcp"),
            "interface": profile.network.get("device", "auto"),
            "nameservers": profile.network.get("nameservers", []),
            "mirror_host": profile.extra.get(
                "mirror_host", "deb.debian.org"
            ),
            "mirror_dir": profile.extra.get(
                "mirror_dir", "/debian"
            ),
            "mirror_proxy": profile.extra.get("mirror_proxy", ""),
            "disk_method": profile.disk.get("method", "lvm"),
            "disk_device": profile.disk.get("device", "/dev/sda"),
            "disk_recipe": profile.disk.get("recipe", "atomic"),
            "packages": profile.packages,
            "post_scripts": profile.post_scripts,
            "install_url": profile.install_url,
            "rootpw_lock": profile.extra.get("rootpw_lock", True),
            "user_fullname": profile.extra.get(
                "user_fullname", "Admin"
            ),
            "username": profile.extra.get("username", "admin"),
        }
        return self._render_template("preseed.cfg.j2", context)

    def boot_assets(
        self, profile: ProvisionProfile
    ) -> BootAssets:
        kernel = "install.amd/vmlinuz"
        initrd = str(_INITRD_SUBPATH)

        boot_args = [
            "auto=true",
            "priority=critical",
            f"url={profile.autoinstall_url}",
            f"mirror/http/hostname={profile.extra.get('mirror_host', 'deb.debian.org')}",
            "interface=auto",
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
                "kernel": kernel,
                "initrd": initrd,
                "boot_args": " ".join(boot_args),
                "menu_label": (
                    f"{profile.name} - Debian "
                    f"{profile.os_version}"
                ),
            },
        )

        return BootAssets(
            kernel=kernel,
            initrd=initrd,
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
                "(points to the preseed file)"
            )
        if profile.arch not in ("amd64", "x86_64", "arm64"):
            errors.append(
                f"unsupported arch {profile.arch!r} for Debian"
            )
        return errors

    @property
    def supports_live(self) -> bool:
        return True

    def extract_live_assets(
        self, mount_path: Path, dest: Path
    ) -> DistroAssets:
        dest.mkdir(parents=True, exist_ok=True)

        kernel_src = mount_path / _LIVE_KERNEL
        initrd_src = mount_path / _LIVE_INITRD

        kernel_dst = dest / "vmlinuz"
        initrd_dst = dest / "initrd.img"

        shutil.copy2(kernel_src, kernel_dst)
        shutil.copy2(initrd_src, initrd_dst)

        rootfs_dst = dest / "live"
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
            f"/live/filesystem.squashfs"
        )
        boot_args = [
            "boot=live",
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
                "kernel": str(_LIVE_KERNEL),
                "initrd": str(_LIVE_INITRD),
                "boot_args": " ".join(boot_args),
                "menu_label": (
                    f"{profile.name} - Debian Live "
                    f"{profile.os_version}"
                ),
            },
        )

        return BootAssets(
            kernel=str(_LIVE_KERNEL),
            initrd=str(_LIVE_INITRD),
            boot_args=tuple(boot_args),
            bootloader_config=bootloader_cfg,
        )

    def extract_from_iso(
        self, mount_path: Path, dest: Path
    ) -> DistroAssets:
        dest.mkdir(parents=True, exist_ok=True)

        # Locate kernel -- prefer vmlinuz, fall back to linux.
        kernel_src = None
        for candidate in _KERNEL_CANDIDATES:
            path = mount_path / candidate
            if path.exists():
                kernel_src = path
                break
        if kernel_src is None:
            raise FileNotFoundError(
                "Could not find kernel under "
                f"{mount_path / 'install.amd'}"
            )

        initrd_src = mount_path / _INITRD_SUBPATH
        kernel_dst = dest / "vmlinuz"
        initrd_dst = dest / "initrd.gz"

        shutil.copy2(kernel_src, kernel_dst)
        shutil.copy2(initrd_src, initrd_dst)

        # Copy the pool/dists tree for the local mirror.
        repo_dst = dest / "repo"
        repo_dst.mkdir(parents=True, exist_ok=True)
        for subdir in ("pool", "dists"):
            src = mount_path / subdir
            if src.exists():
                shutil.copytree(
                    src,
                    repo_dst / subdir,
                    dirs_exist_ok=True,
                )

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
