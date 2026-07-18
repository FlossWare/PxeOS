"""DragonFlyBSD provisioning plugin using bsdinstall."""

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


class DragonFlyBSDPlugin(OSPlugin):

    @property
    def os_family(self) -> str:
        return "dragonflybsd"

    @property
    def supported_versions(self) -> list[str]:
        return ["6.4", "6.2", "6.0"]

    def autoinstall_filename(self) -> str:
        return "installerconfig"

    def generate_autoinstall(
        self, profile: ProvisionProfile
    ) -> str:
        disk_cfg = profile.disk or {}
        network_cfg = profile.network or {}

        use_hammer2 = (
            disk_cfg.get("filesystem", "hammer2") == "hammer2"
        )
        target_disk = disk_cfg.get("device", "da0")

        distributions = disk_cfg.get(
            "distributions", "base.txz"
        )

        iface = network_cfg.get("interface", "em0")
        use_dhcp = network_cfg.get("dhcp", True)
        ipv4 = network_cfg.get("address", "")
        netmask = network_cfg.get("netmask", "255.255.255.0")
        gateway = network_cfg.get("gateway", "")
        nameservers = network_cfg.get(
            "nameservers", ["8.8.8.8", "8.8.4.4"]
        )
        hostname = network_cfg.get(
            "hostname", profile.name
        )
        domain = network_cfg.get("domain", "local")

        root_password = profile.extra.get(
            "root_password", "$6$rounds=4096$salt$hash"
        )
        timezone = profile.extra.get("timezone", "UTC")
        keymap = profile.extra.get("keymap", "us")
        services = profile.extra.get(
            "services", ["sshd"]
        )

        context = {
            "profile": profile,
            "hostname": hostname,
            "domain": domain,
            "distributions": distributions,
            "use_hammer2": use_hammer2,
            "target_disk": target_disk,
            "iface": iface,
            "use_dhcp": use_dhcp,
            "ipv4": ipv4,
            "netmask": netmask,
            "gateway": gateway,
            "nameservers": nameservers,
            "root_password": root_password,
            "timezone": timezone,
            "keymap": keymap,
            "services": services,
            "packages": profile.packages,
            "post_scripts": profile.post_scripts,
            "install_url": profile.install_url,
        }
        self._sanitize_context(context)
        return self._render_template(
            "dragonflybsd-installerconfig.j2", context
        )

    def boot_assets(
        self, profile: ProvisionProfile
    ) -> BootAssets:
        base = profile.install_url.rstrip("/")
        version = profile.os_version
        arch = profile.arch or "x86_64"

        if profile.firmware == BootFirmware.UEFI:
            kernel = f"{base}/boot/loader.efi"
            boot_args = (
                f"vfs.root.mountfrom=ufs:/dev/md0",
                f"boot.nfsroot.server={base}",
                f"boot.nfsroot.path=/dragonflybsd/{version}/{arch}",
            )
            config = (
                f"# DragonFlyBSD {version} UEFI PXE boot\n"
                f"set boot_verbose\n"
                f'set kernel="kernel"\n'
                f'set autoboot_delay="3"\n'
            )
        else:
            kernel = f"{base}/boot/pxeboot"
            boot_args = (
                f"vfs.root.mountfrom=ufs:/dev/md0",
                f"boot.nfsroot.server={base}",
                f"boot.nfsroot.path=/dragonflybsd/{version}/{arch}",
            )
            config = (
                f"# DragonFlyBSD {version} BIOS PXE boot\n"
                f'set kernel="kernel"\n'
                f'set autoboot_delay="3"\n'
            )

        return BootAssets(
            kernel=kernel,
            initrd=f"{base}/boot/kernel/initrd.img.gz",
            boot_args=boot_args,
            bootloader_config=config,
        )

    def validate_profile(
        self, profile: ProvisionProfile
    ) -> list[str]:
        errors = super().validate_profile(profile)

        if not profile.install_url:
            errors.append(
                "install_url is required for DragonFlyBSD "
                "(HTTP/FTP path to distribution sets)"
            )
        elif urlparse(profile.install_url).scheme not in (
            "http", "https", "ftp", "nfs",
        ):
            errors.append(
                f"install_url must be http://, https://, "
                f"ftp://, or nfs:// (got {profile.install_url!r})"
            )

        disk = profile.disk or {}
        fs = disk.get("filesystem", "hammer2")
        if fs not in ("hammer2", "ufs"):
            errors.append(
                f"unsupported filesystem {fs!r}; "
                f"DragonFlyBSD supports 'hammer2' or 'ufs'"
            )

        arch = profile.arch or "x86_64"
        if arch not in ("x86_64", "amd64"):
            errors.append(
                f"unsupported architecture {arch!r}; "
                f"DragonFlyBSD supports x86_64, amd64"
            )

        return errors

    def extract_from_iso(
        self, mount_path: Path, dest: Path
    ) -> DistroAssets:
        boot_dir = dest / "boot"
        repo_dir = dest / "repo"
        boot_dir.mkdir(parents=True, exist_ok=True)
        repo_dir.mkdir(parents=True, exist_ok=True)

        # DragonFlyBSD kernel lives at boot/kernel/kernel
        kernel_src = mount_path / "boot" / "kernel" / "kernel"
        mfsroot_src = mount_path / "boot" / "mfsroot.gz"
        pxeboot_src = mount_path / "boot" / "pxeboot"
        loader_src = mount_path / "boot" / "loader.efi"

        kernel_dst = boot_dir / "kernel"
        mfsroot_dst = boot_dir / "mfsroot.gz"
        pxeboot_dst = boot_dir / "pxeboot"
        loader_dst = boot_dir / "loader.efi"

        if kernel_src.exists():
            shutil.copy2(kernel_src, kernel_dst)
        if mfsroot_src.exists():
            shutil.copy2(mfsroot_src, mfsroot_dst)
        if pxeboot_src.exists():
            shutil.copy2(pxeboot_src, pxeboot_dst)
        if loader_src.exists():
            shutil.copy2(loader_src, loader_dst)

        boot_loader_path = (
            loader_dst if loader_dst.exists() else None
        )

        # Copy distribution sets
        for dist_set in ("base.txz",):
            src = mount_path / "usr" / "release" / dist_set
            if src.exists():
                shutil.copy2(src, repo_dir / dist_set)

        return DistroAssets(
            kernel_path=kernel_dst,
            initrd_path=mfsroot_dst if mfsroot_dst.exists() else None,
            repo_path=repo_dir,
            boot_loader_path=boot_loader_path,
        )
