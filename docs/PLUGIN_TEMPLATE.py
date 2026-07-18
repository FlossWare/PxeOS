"""Template for a new PxeOS OS plugin.

Copy this file to pxeos/plugins/<os_family>.py and replace all
TODO markers with your OS-specific implementation.

See docs/PLUGIN_GUIDE.md for detailed instructions.
See docs/PLUGIN_CHECKLIST.md for the review checklist.
"""

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

# TODO: List supported versions for your OS.
_SUPPORTED_VERSIONS = ["1.0"]

# TODO: Define paths to the kernel and initrd within the ISO
# or network boot tree.  These are relative to the TFTP root
# or the ISO mount point.
_KERNEL_SUBPATH = Path("boot/vmlinuz")
_INITRD_SUBPATH = Path("boot/initrd.img")

# TODO: If your OS supports live boot, define paths to the
# live kernel, initrd, and squashfs.  Delete these if live
# boot is not supported.
# _LIVE_KERNEL = Path("live/vmlinuz")
# _LIVE_INITRD = Path("live/initrd.img")
# _LIVE_SQUASHFS = Path("live/filesystem.squashfs")


class MyOSPlugin(OSPlugin):
    """TODO: Describe your plugin.

    Example: "Kickstart-based provisioning for the Fedora family."
    """

    # ------------------------------------------------------------------
    # Required properties
    # ------------------------------------------------------------------

    @property
    def os_family(self) -> str:
        """Return the OS family identifier (lowercase).

        This must match the os_family field in ProvisionProfile
        and is used as the registry key.
        """
        # TODO: Return your OS family name, e.g. "gentoo", "nixos".
        return "myos"

    @property
    def supported_versions(self) -> list[str]:
        """Return the list of OS versions this plugin supports.

        The base validate_profile() rejects profiles whose
        os_version is not in this list.  Return [] to skip
        version checking.
        """
        return list(_SUPPORTED_VERSIONS)

    # ------------------------------------------------------------------
    # Required methods
    # ------------------------------------------------------------------

    def autoinstall_filename(self) -> str:
        """Return the conventional filename for the autoinstall config.

        Examples:
            Fedora  -> "ks.cfg"
            Debian  -> "preseed.cfg"
            Ubuntu  -> "user-data"
            OpenBSD -> "install.conf"
            Windows -> "unattend.xml"
        """
        # TODO: Return the correct filename for your installer.
        return "install.cfg"

    def generate_autoinstall(
        self, profile: ProvisionProfile
    ) -> str:
        """Generate the unattended-install config for this OS.

        Steps:
        1. Build a context dict from profile fields.
        2. Call self._sanitize_context(context) to validate
           hostnames, URLs, and package names.
        3. Call self._render_template() with your Jinja2 template.

        Returns:
            The rendered config file content as a string.
        """
        context = {
            "profile": profile,
            # TODO: Extract fields from the profile.
            # Common fields to include:
            "hostname": profile.network.get(
                "hostname", profile.name
            ),
            "timezone": profile.extra.get(
                "timezone", "UTC"
            ),
            "packages": profile.packages,
            "post_scripts": profile.post_scripts,
            "install_url": profile.install_url,
        }

        # Sanitize user-supplied values before template rendering.
        # This checks hostnames, URLs, and package names for
        # injection risks and raises ValueError if invalid.
        self._sanitize_context(context)

        # TODO: Create your template file in pxeos/templates/
        # and update the name here.
        return self._render_template("myos-install.cfg.j2", context)

    def boot_assets(
        self, profile: ProvisionProfile
    ) -> BootAssets:
        """Return PXE boot assets for a standard install.

        Must handle both BIOS and UEFI firmware by choosing the
        appropriate bootloader template (pxelinux.cfg.j2 for BIOS,
        grub.cfg.j2 for UEFI).

        Returns:
            A BootAssets dataclass with kernel, initrd, boot_args,
            and bootloader_config.
        """
        # TODO: Build the kernel command-line arguments for your
        # OS installer.
        boot_args = [
            # TODO: Add installer-specific boot arguments.
            # Examples:
            #   Fedora:  "inst.ks=<url>", "inst.repo=<url>"
            #   Debian:  "auto=true", "url=<preseed_url>"
            #   Ubuntu:  "autoinstall", "ds=nocloud-net;s=<url>"
            #   OpenBSD: "tftproot=<path>"
            "ip=dhcp",
        ]

        if profile.extra.get("serial_console"):
            boot_args.append(
                f"console={profile.extra['serial_console']}"
            )

        # Select bootloader template based on firmware type.
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
                    f"{profile.name} - MyOS "
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
        """Extract boot files and repo tree from a mounted ISO.

        Copy the kernel, initrd, and distribution repository files
        from mount_path into dest.

        Args:
            mount_path: Path where the ISO is mounted (read-only).
            dest: Destination directory to copy files into.

        Returns:
            A DistroAssets dataclass describing the extracted files.
        """
        dest.mkdir(parents=True, exist_ok=True)

        # TODO: Copy kernel and initrd.
        kernel_src = mount_path / _KERNEL_SUBPATH
        initrd_src = mount_path / _INITRD_SUBPATH

        kernel_dst = dest / "vmlinuz"
        initrd_dst = dest / "initrd.img"

        shutil.copy2(kernel_src, kernel_dst)
        shutil.copy2(initrd_src, initrd_dst)

        # TODO: Copy the package repository tree.
        # Examples:
        #   Fedora: Packages/, repodata/, BaseOS/, AppStream/
        #   Debian: pool/, dists/
        #   OpenBSD: *.tgz distribution sets
        repo_dst = dest / "repo"
        repo_dst.mkdir(parents=True, exist_ok=True)

        # for subdir in ("packages", "metadata"):
        #     src = mount_path / subdir
        #     if src.exists():
        #         shutil.copytree(
        #             src, repo_dst / subdir, dirs_exist_ok=True
        #         )

        # TODO: Check for UEFI boot loader files.
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

    def validate_profile(
        self, profile: ProvisionProfile
    ) -> list[str]:
        """Validate a provision profile for this OS family.

        Always call super().validate_profile() first -- it checks:
        - profile.name is not empty
        - profile.os_family matches self.os_family
        - profile.os_version is in self.supported_versions

        Then add OS-specific checks (required URLs, valid
        architectures, etc.).

        Returns:
            A list of error message strings.  Empty means valid.
        """
        errors = super().validate_profile(profile)

        # TODO: Add OS-specific validation.
        if not profile.install_url:
            errors.append(
                "install_url is required for MyOS installs"
            )
        if not profile.autoinstall_url:
            errors.append(
                "autoinstall_url is required "
                "(points to the autoinstall config)"
            )

        # TODO: Update with architectures your OS supports.
        if profile.arch not in ("x86_64", "aarch64"):
            errors.append(
                f"unsupported arch {profile.arch!r} for MyOS"
            )

        return errors

    # ------------------------------------------------------------------
    # Optional: Live boot support
    # ------------------------------------------------------------------
    # Uncomment and implement the methods below if your OS
    # supports PXE live boot.  Delete this section if it does not.

    # @property
    # def supports_live(self) -> bool:
    #     return True
    #
    # def extract_live_assets(
    #     self, mount_path: Path, dest: Path
    # ) -> DistroAssets:
    #     """Extract live boot files from a mounted live ISO."""
    #     dest.mkdir(parents=True, exist_ok=True)
    #
    #     kernel_dst = dest / "vmlinuz"
    #     initrd_dst = dest / "initrd.img"
    #     shutil.copy2(mount_path / _LIVE_KERNEL, kernel_dst)
    #     shutil.copy2(mount_path / _LIVE_INITRD, initrd_dst)
    #
    #     rootfs_dst = dest / "live"
    #     rootfs_dst.mkdir(parents=True, exist_ok=True)
    #     squashfs_dst = rootfs_dst / "filesystem.squashfs"
    #     shutil.copy2(
    #         mount_path / _LIVE_SQUASHFS, squashfs_dst
    #     )
    #
    #     return DistroAssets(
    #         kernel_path=kernel_dst,
    #         initrd_path=initrd_dst,
    #         repo_path=rootfs_dst,
    #         squashfs_path=squashfs_dst,
    #     )
    #
    # def live_boot_assets(
    #     self, profile: ProvisionProfile
    # ) -> BootAssets:
    #     """Return boot assets for a live (non-install) PXE boot."""
    #     rootfs_url = (
    #         f"{profile.install_url.rstrip('/')}"
    #         f"/live/filesystem.squashfs"
    #     )
    #     boot_args = [
    #         "boot=live",
    #         f"fetch={rootfs_url}",
    #         "ip=dhcp",
    #     ]
    #
    #     if profile.firmware == BootFirmware.UEFI:
    #         template = "grub.cfg.j2"
    #     else:
    #         template = "pxelinux.cfg.j2"
    #
    #     bootloader_cfg = self._render_template(
    #         template,
    #         {
    #             "profile": profile,
    #             "kernel": str(_LIVE_KERNEL),
    #             "initrd": str(_LIVE_INITRD),
    #             "boot_args": " ".join(boot_args),
    #             "menu_label": (
    #                 f"{profile.name} - MyOS Live "
    #                 f"{profile.os_version}"
    #             ),
    #         },
    #     )
    #
    #     return BootAssets(
    #         kernel=str(_LIVE_KERNEL),
    #         initrd=str(_LIVE_INITRD),
    #         boot_args=tuple(boot_args),
    #         bootloader_config=bootloader_cfg,
    #     )
