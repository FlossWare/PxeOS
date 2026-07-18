"""Shared fixtures for PxeOS tests."""

from __future__ import annotations

import json
import textwrap

import pytest

from pxeos.config import PxeOSConfig
from pxeos.models import BootFirmware, HostRule, ProvisionProfile
from pxeos.registry import PluginRegistry


@pytest.fixture
def sample_profile() -> ProvisionProfile:
    """A realistic Fedora provision profile with sensible defaults."""
    return ProvisionProfile(
        name="test-server",
        os_family="fedora",
        os_version="40",
        arch="x86_64",
        firmware=BootFirmware.BIOS,
        install_url="http://mirror.example.com/fedora/40/x86_64",
        autoinstall_url="http://pxe.example.com/ks/test-server",
        packages=["vim", "tmux", "htop"],
        post_scripts=["systemctl enable sshd"],
    )


@pytest.fixture
def fedora_profile() -> ProvisionProfile:
    """Fedora-specific profile for Kickstart testing."""
    return ProvisionProfile(
        name="test-server",
        os_family="fedora",
        os_version="40",
        arch="x86_64",
        firmware=BootFirmware.BIOS,
        install_url="http://mirror.example.com/fedora/40/x86_64",
        autoinstall_url="http://pxe.example.com/ks/test-server",
        packages=["vim", "tmux", "htop"],
        post_scripts=["systemctl enable sshd"],
    )


@pytest.fixture
def freebsd_profile() -> ProvisionProfile:
    """FreeBSD-specific profile for mfsBSD / bsdinstall testing."""
    return ProvisionProfile(
        name="bsd-node",
        os_family="freebsd",
        os_version="14.1",
        arch="amd64",
        firmware=BootFirmware.BIOS,
        install_url="http://mirror.example.com/freebsd/14.1",
        disk={"filesystem": "zfs", "device": "ada0"},
    )


@pytest.fixture
def windows_profile() -> ProvisionProfile:
    """Windows Server profile for unattended WinPE testing."""
    return ProvisionProfile(
        name="win-server",
        os_family="windows",
        os_version="2022",
        arch="x86_64",
        firmware=BootFirmware.UEFI,
        install_url="http://pxe.example.com/win/2022",
        autoinstall_url="http://pxe.example.com/unattend/win2022",
        extra={
            "product_key": "",
            "admin_password": "S3cur3P@ss!",
        },
    )


@pytest.fixture
def sample_host_rules() -> list[HostRule]:
    """A collection of HostRule objects covering different match criteria."""
    return [
        # Exact MAC match
        HostRule(
            profile="exact-mac-host",
            os_family="fedora",
            os_version="40",
            priority=10,
            mac="aa:bb:cc:dd:ee:ff",
        ),
        # MAC prefix match
        HostRule(
            profile="mac-prefix-hosts",
            os_family="debian",
            os_version="12",
            priority=20,
            mac_prefix="aa:bb:cc",
        ),
        # Hostname glob
        HostRule(
            profile="web-servers",
            os_family="ubuntu",
            os_version="24.04",
            priority=30,
            hostname_pattern="web-*",
        ),
        # Subnet CIDR
        HostRule(
            profile="lab-subnet",
            os_family="fedora",
            os_version="40",
            priority=40,
            subnet="192.168.10.0/24",
        ),
        # Group
        HostRule(
            profile="storage-cluster",
            os_family="freebsd",
            os_version="14.1",
            priority=50,
            group="storage",
        ),
        # Serial number
        HostRule(
            profile="specific-hw",
            os_family="windows",
            os_version="2022",
            priority=60,
            serial="SN-ABC123",
        ),
        # Default (no criteria) -- lowest priority
        HostRule(
            profile="default",
            os_family="debian",
            os_version="12",
            priority=1000,
        ),
    ]


@pytest.fixture
def tmp_config_dir(tmp_path):
    """Create a temporary directory populated with sample TOML configs."""
    # Main config
    pxeos_toml = tmp_path / "pxeos.toml"
    pxeos_toml.write_text(textwrap.dedent("""\
        [server]
        host = "0.0.0.0"
        port = 8443

        [paths]
        tftp_root = "/var/lib/tftpboot/pxeos"
        distro_root = "/var/lib/pxeos/distros"
        data_dir = "/var/lib/pxeos"

        [defaults]
        os = "fedora"
        version = "40"
        profile = "base"
    """))

    # Hosts config
    hosts_toml = tmp_path / "hosts.toml"
    hosts_toml.write_text(textwrap.dedent("""\
        [[host]]
        mac = "aa:bb:cc:dd:ee:ff"
        profile = "test-server"
        os_family = "fedora"
        os_version = "40"
    """))

    # Profiles directory with a sample profile
    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir()
    profile_toml = profiles_dir / "test-server.toml"
    profile_toml.write_text(textwrap.dedent("""\
        [profile]
        name = "test-server"
        os_family = "fedora"
        os_version = "40"
        arch = "x86_64"
        firmware = "bios"
        install_url = "http://mirror.example.com/fedora/40/x86_64"
        autoinstall_url = "http://pxe.example.com/ks/test-server"
        packages = ["vim", "tmux", "htop"]
        post_scripts = ["systemctl enable sshd"]
    """))

    return tmp_path


@pytest.fixture
def plugin_registry() -> PluginRegistry:
    """A PluginRegistry with all builtin plugins loaded."""
    registry = PluginRegistry()
    registry.load_builtins()
    return registry


@pytest.fixture
def pxeos_config(tmp_path) -> PxeOSConfig:
    """A PxeOSConfig pointing at temporary directories."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    distro_root = tmp_path / "distros"
    distro_root.mkdir()
    return PxeOSConfig(
        data_dir=data_dir,
        distro_root=distro_root,
    )


@pytest.fixture
def cobbler_export_dir(tmp_path):
    """A temporary Cobbler export directory with sample data."""
    export_dir = tmp_path / "cobbler_export"
    export_dir.mkdir()

    distros = [
        {
            "name": "fedora40-x86_64",
            "breed": "redhat",
            "os_version": "40",
            "arch": "x86_64",
            "kernel": "/var/lib/cobbler/distros/fedora40/vmlinuz",
            "initrd": "/var/lib/cobbler/distros/fedora40/initrd.img",
        }
    ]
    (export_dir / "distros.json").write_text(json.dumps(distros))

    profiles = [
        {
            "name": "webserver",
            "distro": "fedora40-x86_64",
            "kickstart": "/var/lib/cobbler/kickstarts/web.ks",
        }
    ]
    (export_dir / "profiles.json").write_text(json.dumps(profiles))

    systems = [
        {
            "name": "web-01",
            "profile": "webserver",
            "hostname": "web-01.example.com",
            "interfaces": {
                "eth0": {
                    "mac_address": "aa:bb:cc:dd:ee:ff",
                    "ip_address": "10.0.0.10",
                }
            },
        }
    ]
    (export_dir / "systems.json").write_text(json.dumps(systems))

    return export_dir


@pytest.fixture
def host_rule_with_bmc() -> HostRule:
    """A HostRule with BMC power management fields populated."""
    return HostRule(
        profile="bmc-test",
        os_family="fedora",
        os_version="40",
        mac="aa:bb:cc:dd:ee:ff",
        bmc_host="192.168.1.100",
        bmc_user="admin",
        bmc_password="secret",
        bmc_driver="ipmi",
    )
