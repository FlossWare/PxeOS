"""Core data models for PxeOS provisioning."""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


class BootFirmware(enum.Enum):
    BIOS = "bios"
    UEFI = "uefi"


@dataclass
class ProvisionProfile:
    name: str
    os_family: str
    os_version: str
    vendor: str = ""
    arch: str = "x86_64"
    firmware: BootFirmware = BootFirmware.BIOS
    install_url: str = ""
    autoinstall_url: str = ""
    network: dict = field(default_factory=dict)
    disk: dict = field(default_factory=dict)
    packages: list[str] = field(default_factory=list)
    post_scripts: list[str] = field(default_factory=list)
    extra: dict = field(default_factory=dict)


@dataclass(frozen=True)
class BootAssets:
    kernel: str
    initrd: Optional[str] = None
    boot_args: tuple[str, ...] = ()
    bootloader_config: str = ""


@dataclass
class DistroAssets:
    kernel_path: Path
    initrd_path: Optional[Path] = None
    repo_path: Path = field(default_factory=lambda: Path("."))
    boot_loader_path: Optional[Path] = None
    squashfs_path: Optional[Path] = None


@dataclass
class HostRule:
    profile: str
    os_family: str
    os_version: str
    vendor: str = ""
    priority: int = 100
    mac: Optional[str] = None
    mac_prefix: Optional[str] = None
    hostname_pattern: Optional[str] = None
    subnet: Optional[str] = None
    serial: Optional[str] = None
    group: Optional[str] = None
    arch: Optional[str] = None
    bmc_host: Optional[str] = None
    bmc_user: Optional[str] = None
    bmc_password: Optional[str] = None
    bmc_driver: Optional[str] = None  # "ipmi" or "redfish"
