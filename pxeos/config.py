"""Configuration loading from TOML files."""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from pxeos.models import BootFirmware, HostRule, ProvisionProfile

if sys.version_info >= (3, 11):
    import tomllib
else:
    try:
        import tomllib
    except ModuleNotFoundError:
        import tomli as tomllib  # type: ignore[no-redef]


@dataclass
class PxeOSConfig:
    server_host: str = "0.0.0.0"
    server_port: int = 8443
    tls_cert: Optional[Path] = None
    tls_key: Optional[Path] = None
    tftp_root: Path = field(
        default_factory=lambda: Path("/srv/tftp")
    )
    distro_root: Path = field(
        default_factory=lambda: Path("/srv/pxeos/distros")
    )
    data_dir: Path = field(
        default_factory=lambda: Path("/etc/pxeos")
    )
    auth_enabled: bool = False


def load_config(path: Path) -> PxeOSConfig:
    try:
        with open(path, "rb") as fh:
            data = tomllib.load(fh)
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(
            f"malformed config file {path}: {exc}"
        ) from exc
    except OSError as exc:
        raise ValueError(
            f"cannot read config file {path}: {exc}"
        ) from exc

    server = data.get("server", {})
    paths = data.get("paths", {})
    auth = data.get("auth", {})

    tls_cert = server.get("tls_cert")
    tls_key = server.get("tls_key")

    return PxeOSConfig(
        server_host=server.get("host", "0.0.0.0"),
        server_port=server.get("port", 8443),
        tls_cert=Path(tls_cert) if tls_cert else None,
        tls_key=Path(tls_key) if tls_key else None,
        tftp_root=Path(paths.get("tftp_root", "/srv/tftp")),
        distro_root=Path(
            paths.get("distro_root", "/srv/pxeos/distros")
        ),
        data_dir=Path(paths.get("data_dir", "/etc/pxeos")),
        auth_enabled=auth.get("enabled", False),
    )


def load_hosts(path: Path) -> List[HostRule]:
    try:
        with open(path, "rb") as fh:
            data = tomllib.load(fh)
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(
            f"malformed hosts file {path}: {exc}"
        ) from exc

    rules: List[HostRule] = []
    for entry in data.get("host", []):
        rules.append(
            HostRule(
                profile=entry["profile"],
                os_family=entry["os_family"],
                os_version=entry["os_version"],
                vendor=entry.get("vendor", ""),
                priority=entry.get("priority", 100),
                mac=entry.get("mac"),
                mac_prefix=entry.get("mac_prefix"),
                hostname_pattern=entry.get("hostname_pattern"),
                subnet=entry.get("subnet"),
                serial=entry.get("serial"),
                group=entry.get("group"),
                arch=entry.get("arch"),
                bmc_host=entry.get("bmc_host"),
                bmc_user=entry.get("bmc_user"),
                bmc_password=entry.get("bmc_password"),
                bmc_driver=entry.get("bmc_driver"),
            )
        )
    return rules


def load_profile(path: Path) -> ProvisionProfile:
    try:
        with open(path, "rb") as fh:
            data = tomllib.load(fh)
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(
            f"malformed profile file {path}: {exc}"
        ) from exc

    profile = data.get("profile", data)
    firmware_str = profile.get("firmware", "bios").lower()
    firmware = (
        BootFirmware.UEFI
        if firmware_str == "uefi"
        else BootFirmware.BIOS
    )

    return ProvisionProfile(
        name=profile["name"],
        os_family=profile["os_family"],
        os_version=profile["os_version"],
        vendor=profile.get("vendor", ""),
        arch=profile.get("arch", "x86_64"),
        firmware=firmware,
        install_url=profile.get("install_url", ""),
        autoinstall_url=profile.get("autoinstall_url", ""),
        network=profile.get("network", {}),
        disk=profile.get("disk", {}),
        packages=profile.get("packages", []),
        post_scripts=profile.get("post_scripts", []),
        extra=profile.get("extra", {}),
    )
