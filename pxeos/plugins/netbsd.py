"""NetBSD provisioning plugin using sysinst."""

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

# Standard NetBSD distribution sets.
_DIST_SETS = (
    "base.tgz",
    "comp.tgz",
    "etc.tgz",
    "games.tgz",
    "man.tgz",
    "misc.tgz",
    "modules.tgz",
    "rescue.tgz",
    "text.tgz",
)

# Kernel sets by architecture.
_KERNEL_SETS = {
    "amd64": "kern-GENERIC.tgz",
    "i386": "kern-GENERIC.tgz",
    "evbarm": "kern-GENERIC64.tgz",
}


class NetBSDPlugin(OSPlugin):

    @property
    def os_family(self) -> str:
        return "netbsd"

    @property
    def supported_versions(self) -> list[str]:
        return ["9.3", "9.4", "10.0", "10.1"]

    def autoinstall_filename(self) -> str:
        return "auto_install.cfg"

    def generate_autoinstall(
        self, profile: ProvisionProfile
    ) -> str:
        network_cfg = profile.network or {}
        disk_cfg = profile.disk or {}

        hostname = network_cfg.get(
            "hostname", profile.name
        )
        domain = network_cfg.get("domain", "local")
        iface = network_cfg.get("interface", "wm0")
        use_dhcp = network_cfg.get("dhcp", True)
        ipv4 = network_cfg.get("address", "")
        netmask = network_cfg.get("netmask", "255.255.255.0")
        gateway = network_cfg.get("gateway", "")
        nameservers = network_cfg.get(
            "nameservers", ["8.8.8.8", "8.8.4.4"]
        )

        disk_device = disk_cfg.get("device", "wd0")
        disk_layout = disk_cfg.get("layout", "default")
        filesystem = disk_cfg.get("filesystem", "ffs")

        root_password = profile.extra.get(
            "root_password", ""
        )
        timezone = profile.extra.get("timezone", "UTC")

        arch = profile.arch or "amd64"
        kernel_set = _KERNEL_SETS.get(
            arch, "kern-GENERIC.tgz"
        )
        selected_sets = profile.extra.get(
            "sets",
            ["base.tgz", "comp.tgz", "etc.tgz", kernel_set],
        )
        install_url = profile.install_url or ""

        context = {
            "profile": profile,
            "hostname": hostname,
            "domain": domain,
            "iface": iface,
            "use_dhcp": use_dhcp,
            "ipv4": ipv4,
            "netmask": netmask,
            "gateway": gateway,
            "nameservers": nameservers,
            "disk_device": disk_device,
            "disk_layout": disk_layout,
            "filesystem": filesystem,
            "root_password": root_password,
            "timezone": timezone,
            "selected_sets": selected_sets,
            "kernel_set": kernel_set,
            "install_url": install_url,
            "packages": profile.packages,
            "post_scripts": profile.post_scripts,
        }
        self._sanitize_context(context)
        return self._render_template(
            "netbsd-auto.j2", context
        )

    def boot_assets(
        self, profile: ProvisionProfile
    ) -> BootAssets:
        base = profile.install_url.rstrip("/")
        version = profile.os_version
        arch = profile.arch or "amd64"

        if profile.firmware == BootFirmware.UEFI:
            kernel = (
                f"{base}/NetBSD-{version}/{arch}/"
                f"installation/netboot/"
                f"netbsd-INSTALL_XEN3_DOMU.gz"
            )
            boot_args = (
                f"root=http={base}/NetBSD-{version}/"
                f"{arch}/binary/sets/",
                "console=com0",
            )
            config = (
                f"# NetBSD {version} UEFI PXE boot\n"
                f"# Serve netboot kernel via TFTP\n"
                f"# sysinst fetches sets from "
                f"install_url\n"
            )
        else:
            kernel = (
                f"{base}/NetBSD-{version}/{arch}/"
                f"installation/netboot/"
                f"pxeboot_ia32.bin"
            )
            boot_args = (
                f"root=http={base}/NetBSD-{version}/"
                f"{arch}/binary/sets/",
                "console=com0",
            )
            config = (
                f"# NetBSD {version} BIOS PXE boot\n"
                f"# pxeboot_ia32.bin loads the NetBSD "
                f"kernel\n"
                f"# sysinst uses auto_install.cfg for "
                f"unattended install\n"
            )

        # NetBSD does use an installer ramdisk
        initrd = (
            f"{base}/NetBSD-{version}/{arch}/"
            f"installation/netboot/"
            f"netbsd-INSTALL.gz"
        )

        return BootAssets(
            kernel=kernel,
            initrd=initrd,
            boot_args=boot_args,
            bootloader_config=config,
        )

    def validate_profile(
        self, profile: ProvisionProfile
    ) -> list[str]:
        errors = super().validate_profile(profile)

        if not profile.install_url:
            errors.append(
                "install_url is required for NetBSD "
                "(HTTP/FTP path to release directory)"
            )

        arch = profile.arch or "amd64"
        if arch not in ("amd64", "i386", "evbarm"):
            errors.append(
                f"unsupported architecture {arch!r}; "
                f"NetBSD supports amd64, i386, evbarm"
            )

        disk = profile.disk or {}
        fs = disk.get("filesystem", "ffs")
        if fs not in ("ffs", "lfs"):
            errors.append(
                f"unsupported filesystem {fs!r}; "
                f"NetBSD supports 'ffs' or 'lfs'"
            )

        return errors

    def extract_from_iso(
        self, mount_path: Path, dest: Path
    ) -> DistroAssets:
        boot_dir = dest / "boot"
        repo_dir = dest / "repo"
        boot_dir.mkdir(parents=True, exist_ok=True)
        repo_dir.mkdir(parents=True, exist_ok=True)

        # Look for netboot kernel
        kernel_dst = boot_dir / "pxeboot_ia32.bin"
        initrd_dst = boot_dir / "netbsd-INSTALL.gz"

        netboot_dir = (
            mount_path / "installation" / "netboot"
        )
        if netboot_dir.exists():
            pxeboot = netboot_dir / "pxeboot_ia32.bin"
            if pxeboot.exists():
                shutil.copy2(pxeboot, kernel_dst)

            install_kern = netboot_dir / "netbsd-INSTALL.gz"
            if install_kern.exists():
                shutil.copy2(install_kern, initrd_dst)

        # Copy binary sets
        sets_dir = mount_path / "binary" / "sets"
        if sets_dir.exists():
            for item in sets_dir.glob("*.tgz"):
                shutil.copy2(item, repo_dir / item.name)
        else:
            # Some ISOs have sets at the root
            for item in mount_path.rglob("*.tgz"):
                shutil.copy2(item, repo_dir / item.name)

        return DistroAssets(
            kernel_path=kernel_dst,
            initrd_path=(
                initrd_dst if initrd_dst.exists() else None
            ),
            repo_path=repo_dir,
            boot_loader_path=None,
        )
