"""TFTP root directory management for PXE boot files."""

from __future__ import annotations

from pathlib import Path

from pxeos.models import BootAssets, DistroAssets, HostRule


class TFTPManager:

    def __init__(self, tftp_root: Path) -> None:
        self._root = tftp_root

    def setup_boot_files(
        self, distro: DistroAssets, profile_name: str
    ) -> None:
        profile_dir = self._root / profile_name
        profile_dir.mkdir(parents=True, exist_ok=True)

        kernel_link = profile_dir / distro.kernel_path.name
        if kernel_link.exists() or kernel_link.is_symlink():
            kernel_link.unlink()
        kernel_link.symlink_to(distro.kernel_path.resolve())

        if distro.initrd_path:
            initrd_link = (
                profile_dir / distro.initrd_path.name
            )
            if initrd_link.exists() or initrd_link.is_symlink():
                initrd_link.unlink()
            initrd_link.symlink_to(
                distro.initrd_path.resolve()
            )

    def generate_pxe_config(
        self,
        host_rule: HostRule,
        boot_assets: BootAssets,
        mac: str,
    ) -> None:
        pxelinux_dir = self._root / "pxelinux.cfg"
        pxelinux_dir.mkdir(parents=True, exist_ok=True)

        mac_norm = mac.lower().replace(":", "-")
        config_file = pxelinux_dir / f"01-{mac_norm}"

        args = " ".join(boot_assets.boot_args)

        lines = [
            "DEFAULT install",
            "PROMPT 0",
            "TIMEOUT 1",
            "",
            "LABEL install",
            f"  KERNEL {boot_assets.kernel}",
        ]
        if boot_assets.initrd:
            lines.append(f"  INITRD {boot_assets.initrd}")
        if args:
            lines.append(f"  APPEND {args}")
        lines.append("")

        config_file.write_text("\n".join(lines))

    def cleanup(self, profile_name: str) -> None:
        profile_dir = self._root / profile_name
        if profile_dir.exists():
            for item in profile_dir.iterdir():
                if item.is_symlink() or item.is_file():
                    item.unlink()
            profile_dir.rmdir()

        pxelinux_dir = self._root / "pxelinux.cfg"
        if pxelinux_dir.exists():
            for cfg in pxelinux_dir.iterdir():
                if cfg.is_file():
                    try:
                        content = cfg.read_text()
                        if profile_name in content:
                            cfg.unlink()
                    except OSError:
                        pass
