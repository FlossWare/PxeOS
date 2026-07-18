"""Tiny Core Linux PXE boot plugin."""

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

_SUPPORTED_VERSIONS = ["current", "14", "15", "16"]

# Standard Tiny Core ISO layout (32-bit)
_KERNEL_SUBPATH = Path("boot/vmlinuz")
_INITRD_SUBPATH = Path("boot/core.gz")

# 64-bit variants (corepure64)
_KERNEL64_SUBPATH = Path("boot/vmlinuz64")
_INITRD64_SUBPATH = Path("boot/corepure64.gz")


class TinyCorePlugin(OSPlugin):
    """PXE boot provisioning for Tiny Core Linux.

    Tiny Core Linux is a minimal (~16MB) Linux distribution that
    boots entirely into RAM.  It does not use a traditional
    autoinstall mechanism (kickstart/preseed/autoinstall).  Instead,
    configuration is passed via kernel boot arguments and TCE
    (Tiny Core Extension) packages are loaded from a network or
    local path.

    The ``generate_autoinstall`` method produces a shell script
    that can be served to configure the booted system (install
    extensions, set up persistence, etc.).
    """

    @property
    def os_family(self) -> str:
        return "tinycore"

    @property
    def supported_versions(self) -> list[str]:
        return list(_SUPPORTED_VERSIONS)

    def autoinstall_filename(self) -> str:
        return "tinycore.cfg"

    def generate_autoinstall(
        self, profile: ProvisionProfile
    ) -> str:
        context = {
            "profile": profile,
            "hostname": profile.network.get(
                "hostname", profile.name
            ),
            "packages": profile.packages,
            "post_scripts": profile.post_scripts,
            "install_url": profile.install_url,
            "tce_mirror": profile.extra.get(
                "tce_mirror", ""
            ),
            "persistence": profile.extra.get(
                "persistence", "none"
            ),
            "mydata_url": profile.extra.get(
                "mydata_url", ""
            ),
        }
        self._sanitize_context(context)
        return self._render_template(
            "tinycore.cfg.j2", context
        )

    def boot_assets(
        self, profile: ProvisionProfile
    ) -> BootAssets:
        is_64bit = profile.extra.get("64bit", True)

        if is_64bit:
            kernel = str(_KERNEL64_SUBPATH)
            initrd = str(_INITRD64_SUBPATH)
        else:
            kernel = str(_KERNEL_SUBPATH)
            initrd = str(_INITRD_SUBPATH)

        boot_args = self._build_boot_args(profile)

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
                    f"{profile.name} - Tiny Core Linux "
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
        if profile.arch not in ("x86_64", "x86"):
            errors.append(
                f"unsupported arch {profile.arch!r} "
                f"for Tiny Core Linux"
            )
        return errors

    @property
    def supports_live(self) -> bool:
        return True

    def extract_live_assets(
        self, mount_path: Path, dest: Path
    ) -> DistroAssets:
        dest.mkdir(parents=True, exist_ok=True)
        kernel_src, initrd_src = self._find_kernel_initrd(
            mount_path
        )

        kernel_dst = dest / kernel_src.name
        initrd_dst = dest / initrd_src.name

        shutil.copy2(kernel_src, kernel_dst)
        shutil.copy2(initrd_src, initrd_dst)

        # Copy TCE extensions directory if present
        tce_src = mount_path / "cde" / "optional"
        tce_dst = None
        if tce_src.exists():
            tce_dst = dest / "cde" / "optional"
            shutil.copytree(
                tce_src, tce_dst, dirs_exist_ok=True
            )

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
            repo_path=dest,
            boot_loader_path=boot_loader_dst,
        )

    def live_boot_assets(
        self, profile: ProvisionProfile
    ) -> BootAssets:
        is_64bit = profile.extra.get("64bit", True)

        if is_64bit:
            kernel = str(_KERNEL64_SUBPATH)
            initrd = str(_INITRD64_SUBPATH)
        else:
            kernel = str(_KERNEL_SUBPATH)
            initrd = str(_INITRD_SUBPATH)

        boot_args = self._build_boot_args(profile)

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
                    f"{profile.name} - Tiny Core Linux "
                    f"Live {profile.os_version}"
                ),
            },
        )

        return BootAssets(
            kernel=kernel,
            initrd=initrd,
            boot_args=tuple(boot_args),
            bootloader_config=bootloader_cfg,
        )

    def extract_from_iso(
        self, mount_path: Path, dest: Path
    ) -> DistroAssets:
        dest.mkdir(parents=True, exist_ok=True)

        kernel_src, initrd_src = self._find_kernel_initrd(
            mount_path
        )

        kernel_dst = dest / kernel_src.name
        initrd_dst = dest / initrd_src.name

        shutil.copy2(kernel_src, kernel_dst)
        shutil.copy2(initrd_src, initrd_dst)

        # Copy TCE extensions directory if present
        repo_dst = dest / "cde"
        cde_src = mount_path / "cde"
        if cde_src.exists():
            shutil.copytree(
                cde_src, repo_dst, dirs_exist_ok=True
            )
        else:
            repo_dst.mkdir(parents=True, exist_ok=True)

        # Check for EFI boot loader files
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

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _find_kernel_initrd(
        self, mount_path: Path
    ) -> tuple[Path, Path]:
        """Locate kernel and initrd in the ISO mount.

        Prefers 64-bit variants if available, falls back to
        32-bit.
        """
        kernel64 = mount_path / _KERNEL64_SUBPATH
        initrd64 = mount_path / _INITRD64_SUBPATH

        if kernel64.exists() and initrd64.exists():
            return kernel64, initrd64

        kernel32 = mount_path / _KERNEL_SUBPATH
        initrd32 = mount_path / _INITRD_SUBPATH

        if kernel32.exists() and initrd32.exists():
            return kernel32, initrd32

        # Fall back to whichever kernel exists
        if kernel64.exists():
            return kernel64, initrd64
        return kernel32, initrd32

    def _build_boot_args(
        self, profile: ProvisionProfile
    ) -> list[str]:
        """Build kernel command-line arguments for Tiny Core."""
        boot_args: list[str] = []

        # TCE directory for extensions
        tce_path = profile.extra.get("tce", "")
        if tce_path:
            boot_args.append(f"tce={tce_path}")

        # mydata.tgz backup/restore URL or path
        mydata = profile.extra.get("mydata", "")
        if mydata:
            boot_args.append(f"restore={mydata}")

        # Network configuration
        boot_args.append("nodhcp")
        waittime = profile.extra.get("waitusb", "")
        if waittime:
            boot_args.append(f"waitusb={waittime}")

        # Additional Tiny Core boot codes
        if profile.extra.get("norestore"):
            boot_args.append("norestore")
        if profile.extra.get("base"):
            boot_args.append("base")
        if profile.extra.get("showapps"):
            boot_args.append("showapps")
        if profile.extra.get("lst"):
            boot_args.append(
                f"lst={profile.extra['lst']}"
            )

        # Serial console
        if profile.extra.get("serial_console"):
            boot_args.append(
                f"console={profile.extra['serial_console']}"
            )

        return boot_args
