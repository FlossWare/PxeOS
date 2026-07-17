"""Tests for pxeos.models dataclasses and enums."""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from pxeos.models import (
    BootAssets,
    BootFirmware,
    DistroAssets,
    HostRule,
    ProvisionProfile,
)


# ---------------------------------------------------------------------------
# BootFirmware enum
# ---------------------------------------------------------------------------

class TestBootFirmware:

    def test_bios_value(self):
        assert BootFirmware.BIOS.value == "bios"

    def test_uefi_value(self):
        assert BootFirmware.UEFI.value == "uefi"

    def test_members_are_exactly_two(self):
        members = list(BootFirmware)
        assert len(members) == 2
        assert set(members) == {BootFirmware.BIOS, BootFirmware.UEFI}


# ---------------------------------------------------------------------------
# ProvisionProfile
# ---------------------------------------------------------------------------

class TestProvisionProfile:

    def test_defaults(self):
        """Required fields only -- verify every default."""
        p = ProvisionProfile(
            name="minimal",
            os_family="debian",
            os_version="12",
        )
        assert p.name == "minimal"
        assert p.os_family == "debian"
        assert p.os_version == "12"
        assert p.arch == "x86_64"
        assert p.firmware is BootFirmware.BIOS
        assert p.install_url == ""
        assert p.autoinstall_url == ""
        assert p.network == {}
        assert p.disk == {}
        assert p.packages == []
        assert p.post_scripts == []
        assert p.extra == {}

    def test_all_fields_populated(self, sample_profile):
        """Verify a fully-populated profile stores all values."""
        p = sample_profile
        assert p.name == "test-server"
        assert p.os_family == "fedora"
        assert p.os_version == "40"
        assert p.arch == "x86_64"
        assert p.firmware is BootFirmware.BIOS
        assert p.install_url == "http://mirror.example.com/fedora/40/x86_64"
        assert p.autoinstall_url == "http://pxe.example.com/ks/test-server"
        assert p.packages == ["vim", "tmux", "htop"]
        assert p.post_scripts == ["systemctl enable sshd"]

    def test_mutable_defaults_are_independent(self):
        """Ensure each instance gets its own mutable containers."""
        a = ProvisionProfile(name="a", os_family="fedora", os_version="40")
        b = ProvisionProfile(name="b", os_family="fedora", os_version="40")
        a.packages.append("gcc")
        assert b.packages == []
        assert "gcc" not in b.packages

    def test_extra_dict(self, windows_profile):
        """Verify extra dict stores arbitrary keys."""
        assert windows_profile.extra["product_key"] == ""
        assert windows_profile.extra["admin_password"] == "S3cur3P@ss!"


# ---------------------------------------------------------------------------
# BootAssets (frozen dataclass)
# ---------------------------------------------------------------------------

class TestBootAssets:

    def test_defaults(self):
        ba = BootAssets(kernel="/path/to/vmlinuz")
        assert ba.kernel == "/path/to/vmlinuz"
        assert ba.initrd is None
        assert ba.boot_args == ()
        assert ba.bootloader_config == ""

    def test_all_fields_populated(self):
        ba = BootAssets(
            kernel="images/pxeboot/vmlinuz",
            initrd="images/pxeboot/initrd.img",
            boot_args=("inst.ks=http://ks", "ip=dhcp"),
            bootloader_config="DEFAULT linux\n",
        )
        assert ba.kernel == "images/pxeboot/vmlinuz"
        assert ba.initrd == "images/pxeboot/initrd.img"
        assert ba.boot_args == ("inst.ks=http://ks", "ip=dhcp")
        assert ba.bootloader_config == "DEFAULT linux\n"

    def test_frozen_immutability(self):
        ba = BootAssets(kernel="vmlinuz")
        with pytest.raises(dataclasses.FrozenInstanceError):
            ba.kernel = "other"

    def test_boot_args_is_tuple(self):
        ba = BootAssets(kernel="k", boot_args=("a", "b"))
        assert isinstance(ba.boot_args, tuple)


# ---------------------------------------------------------------------------
# DistroAssets
# ---------------------------------------------------------------------------

class TestDistroAssets:

    def test_defaults(self):
        da = DistroAssets(kernel_path=Path("/boot/vmlinuz"))
        assert da.kernel_path == Path("/boot/vmlinuz")
        assert da.initrd_path is None
        assert da.repo_path == Path(".")
        assert da.boot_loader_path is None

    def test_all_fields_populated(self):
        da = DistroAssets(
            kernel_path=Path("/tftpboot/fedora/vmlinuz"),
            initrd_path=Path("/tftpboot/fedora/initrd.img"),
            repo_path=Path("/srv/repo/fedora/40"),
            boot_loader_path=Path("/tftpboot/fedora/EFI/BOOT"),
        )
        assert da.kernel_path == Path("/tftpboot/fedora/vmlinuz")
        assert da.initrd_path == Path("/tftpboot/fedora/initrd.img")
        assert da.repo_path == Path("/srv/repo/fedora/40")
        assert da.boot_loader_path == Path("/tftpboot/fedora/EFI/BOOT")

    def test_mutable_default_repo_path_independent(self):
        """Each instance should get its own default repo_path."""
        a = DistroAssets(kernel_path=Path("/a"))
        b = DistroAssets(kernel_path=Path("/b"))
        assert a.repo_path == b.repo_path == Path(".")


# ---------------------------------------------------------------------------
# HostRule
# ---------------------------------------------------------------------------

class TestHostRule:

    def test_priority_default(self):
        rule = HostRule(
            profile="default",
            os_family="debian",
            os_version="12",
        )
        assert rule.priority == 100

    def test_optional_fields_default_none(self):
        rule = HostRule(
            profile="test",
            os_family="fedora",
            os_version="40",
        )
        assert rule.mac is None
        assert rule.mac_prefix is None
        assert rule.hostname_pattern is None
        assert rule.subnet is None
        assert rule.serial is None
        assert rule.group is None
        assert rule.arch is None

    def test_all_fields_populated(self):
        rule = HostRule(
            profile="full",
            os_family="fedora",
            os_version="40",
            priority=5,
            mac="aa:bb:cc:dd:ee:ff",
            mac_prefix="aa:bb:cc",
            hostname_pattern="web-*",
            subnet="10.0.0.0/8",
            serial="SN-999",
            group="compute",
            arch="aarch64",
        )
        assert rule.profile == "full"
        assert rule.os_family == "fedora"
        assert rule.os_version == "40"
        assert rule.priority == 5
        assert rule.mac == "aa:bb:cc:dd:ee:ff"
        assert rule.mac_prefix == "aa:bb:cc"
        assert rule.hostname_pattern == "web-*"
        assert rule.subnet == "10.0.0.0/8"
        assert rule.serial == "SN-999"
        assert rule.group == "compute"
        assert rule.arch == "aarch64"

    def test_rules_fixture_coverage(self, sample_host_rules):
        """Verify the fixture contains rules for all match criteria types."""
        assert len(sample_host_rules) == 7
        # Exact MAC rule
        mac_rules = [r for r in sample_host_rules if r.mac is not None]
        assert len(mac_rules) >= 1
        # MAC prefix rule
        prefix_rules = [r for r in sample_host_rules if r.mac_prefix is not None]
        assert len(prefix_rules) >= 1
        # Hostname glob rule
        hostname_rules = [r for r in sample_host_rules if r.hostname_pattern is not None]
        assert len(hostname_rules) >= 1
        # Subnet CIDR rule
        subnet_rules = [r for r in sample_host_rules if r.subnet is not None]
        assert len(subnet_rules) >= 1
        # Group rule
        group_rules = [r for r in sample_host_rules if r.group is not None]
        assert len(group_rules) >= 1
        # Serial rule
        serial_rules = [r for r in sample_host_rules if r.serial is not None]
        assert len(serial_rules) >= 1

    def test_rules_sorted_by_priority(self, sample_host_rules):
        """Rules should be sortable by priority (lower = higher precedence)."""
        sorted_rules = sorted(sample_host_rules, key=lambda r: r.priority)
        assert sorted_rules[0].priority == 10
        assert sorted_rules[-1].priority == 1000
