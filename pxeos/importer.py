"""ISO and mirror import for distro PXE assets."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import urllib.request
from pathlib import Path

from pxeos.models import DistroAssets
from pxeos.registry import PluginRegistry


def _distro_dir(
    distro_root: Path,
    vendor: str,
    version: str,
    arch: str,
) -> Path:
    name = f"{vendor}-{version}-{arch}"
    dest = distro_root / name
    dest.mkdir(parents=True, exist_ok=True)
    return dest


def import_iso(
    iso_path: Path,
    os_family: str,
    vendor: str,
    version: str,
    arch: str,
    registry: PluginRegistry,
    distro_root: Path,
) -> DistroAssets:
    plugin = registry.get(os_family)
    dest = _distro_dir(distro_root, vendor or os_family, version, arch)

    mount_point = Path(tempfile.mkdtemp(prefix="pxeos_mount_"))
    try:
        subprocess.run(
            ["mount", "-o", "loop,ro", str(iso_path),
             str(mount_point)],
            check=True,
            capture_output=True,
        )
        try:
            assets = plugin.extract_from_iso(mount_point, dest)
        finally:
            subprocess.run(
                ["umount", str(mount_point)],
                check=True,
                capture_output=True,
            )
    finally:
        mount_point.rmdir()

    return assets


def import_url(
    mirror_url: str,
    os_family: str,
    vendor: str,
    version: str,
    arch: str,
    registry: PluginRegistry,
    distro_root: Path,
) -> DistroAssets:
    plugin = registry.get(os_family)
    dest = _distro_dir(distro_root, vendor or os_family, version, arch)

    boot_assets = plugin.boot_assets(
        _stub_profile(os_family, vendor, version, arch, mirror_url)
    )

    kernel_dest = dest / "kernel"
    kernel_dest.mkdir(parents=True, exist_ok=True)

    kernel_file = kernel_dest / Path(boot_assets.kernel).name
    _download(boot_assets.kernel, kernel_file)

    initrd_file = None
    if boot_assets.initrd:
        initrd_file = kernel_dest / Path(boot_assets.initrd).name
        _download(boot_assets.initrd, initrd_file)

    repo_dir = dest / "repo"
    repo_dir.mkdir(parents=True, exist_ok=True)

    return DistroAssets(
        kernel_path=kernel_file,
        initrd_path=initrd_file,
        repo_path=repo_dir,
    )


def _download(url: str, dest: Path) -> None:
    with urllib.request.urlopen(url) as response:
        with open(dest, "wb") as out:
            shutil.copyfileobj(response, out)


def _stub_profile(
    os_family: str,
    vendor: str,
    version: str,
    arch: str,
    install_url: str,
) -> "ProvisionProfile":
    from pxeos.models import ProvisionProfile

    return ProvisionProfile(
        name=f"{vendor or os_family}-{version}-{arch}",
        os_family=os_family,
        os_version=version,
        vendor=vendor,
        arch=arch,
        install_url=install_url,
    )
