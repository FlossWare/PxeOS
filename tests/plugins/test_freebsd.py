"""Tests for the FreeBSD bsdinstall plugin."""

from __future__ import annotations

import pytest

from pxeos.models import BootFirmware, ProvisionProfile
from pxeos.plugins.freebsd import FreeBSDPlugin


@pytest.fixture
def plugin() -> FreeBSDPlugin:
    return FreeBSDPlugin()


@pytest.fixture
def valid_profile() -> ProvisionProfile:
    return ProvisionProfile(
        name="freebsd-server",
        os_family="freebsd",
        os_version="14.1",
        arch="amd64",
        install_url="http://mirror.example.com/freebsd/14.1",
        disk={"filesystem": "zfs", "device": "ada0"},
        packages=["vim", "bash"],
    )


class TestOsFamily:
    def test_returns_freebsd(self, plugin: FreeBSDPlugin) -> None:
        assert plugin.os_family == "freebsd"

    def test_supported_versions(self, plugin: FreeBSDPlugin) -> None:
        versions = plugin.supported_versions
        assert "13.3" in versions
        assert "14.1" in versions
        assert "14.2" in versions

    def test_autoinstall_filename(self, plugin: FreeBSDPlugin) -> None:
        assert plugin.autoinstall_filename() == "installerconfig"


class TestGenerateAutoinstall:
    def test_starts_with_shebang(
        self, plugin: FreeBSDPlugin, valid_profile: ProvisionProfile
    ) -> None:
        output = plugin.generate_autoinstall(valid_profile)
        assert output.startswith("#!/bin/sh")

    def test_contains_distributions(
        self, plugin: FreeBSDPlugin, valid_profile: ProvisionProfile
    ) -> None:
        output = plugin.generate_autoinstall(valid_profile)
        assert "DISTRIBUTIONS=" in output

    def test_contains_hostname(
        self, plugin: FreeBSDPlugin, valid_profile: ProvisionProfile
    ) -> None:
        output = plugin.generate_autoinstall(valid_profile)
        assert "freebsd-server" in output

    def test_zfs_config_present(
        self, plugin: FreeBSDPlugin, valid_profile: ProvisionProfile
    ) -> None:
        output = plugin.generate_autoinstall(valid_profile)
        assert "ZFSBOOT_DISKS" in output
        assert "ada0" in output

    def test_ufs_config_when_specified(self, plugin: FreeBSDPlugin) -> None:
        profile = ProvisionProfile(
            name="freebsd-ufs",
            os_family="freebsd",
            os_version="14.1",
            arch="amd64",
            install_url="http://mirror.example.com/freebsd/14.1",
            disk={"filesystem": "ufs", "device": "da0"},
        )
        output = plugin.generate_autoinstall(profile)
        assert "PARTITIONS=" in output

    def test_contains_packages(
        self, plugin: FreeBSDPlugin, valid_profile: ProvisionProfile
    ) -> None:
        output = plugin.generate_autoinstall(valid_profile)
        assert "pkg install -y vim" in output
        assert "pkg install -y bash" in output

    def test_contains_timezone_setup(
        self, plugin: FreeBSDPlugin, valid_profile: ProvisionProfile
    ) -> None:
        output = plugin.generate_autoinstall(valid_profile)
        assert "tzsetup" in output

    def test_contains_services(
        self, plugin: FreeBSDPlugin, valid_profile: ProvisionProfile
    ) -> None:
        output = plugin.generate_autoinstall(valid_profile)
        assert "sshd" in output


class TestBootAssets:
    def test_no_initrd(
        self, plugin: FreeBSDPlugin, valid_profile: ProvisionProfile
    ) -> None:
        assets = plugin.boot_assets(valid_profile)
        assert assets.initrd is None

    def test_bios_kernel_path(
        self, plugin: FreeBSDPlugin, valid_profile: ProvisionProfile
    ) -> None:
        assets = plugin.boot_assets(valid_profile)
        assert assets.kernel.endswith("/boot/pxeboot")
        assert "mirror.example.com" in assets.kernel

    def test_uefi_kernel_path(self, plugin: FreeBSDPlugin) -> None:
        profile = ProvisionProfile(
            name="freebsd-uefi",
            os_family="freebsd",
            os_version="14.1",
            arch="amd64",
            firmware=BootFirmware.UEFI,
            install_url="http://mirror.example.com/freebsd/14.1",
        )
        assets = plugin.boot_assets(profile)
        assert assets.kernel.endswith("/boot/loader.efi")
        assert assets.initrd is None

    def test_boot_args_contain_nfsroot(
        self, plugin: FreeBSDPlugin, valid_profile: ProvisionProfile
    ) -> None:
        assets = plugin.boot_assets(valid_profile)
        assert any("boot.nfsroot.server=" in arg for arg in assets.boot_args)
        assert any("boot.nfsroot.path=" in arg for arg in assets.boot_args)

    def test_bootloader_config_contains_comment(
        self, plugin: FreeBSDPlugin, valid_profile: ProvisionProfile
    ) -> None:
        assets = plugin.boot_assets(valid_profile)
        assert "FreeBSD" in assets.bootloader_config
        assert "14.1" in assets.bootloader_config


class TestValidateProfile:
    def test_valid_profile_no_errors(
        self, plugin: FreeBSDPlugin, valid_profile: ProvisionProfile
    ) -> None:
        errors = plugin.validate_profile(valid_profile)
        assert errors == []

    def test_missing_install_url(self, plugin: FreeBSDPlugin) -> None:
        profile = ProvisionProfile(
            name="freebsd-server",
            os_family="freebsd",
            os_version="14.1",
            arch="amd64",
            install_url="",
        )
        errors = plugin.validate_profile(profile)
        assert any("install_url" in e for e in errors)

    def test_unsupported_filesystem(self, plugin: FreeBSDPlugin) -> None:
        profile = ProvisionProfile(
            name="freebsd-server",
            os_family="freebsd",
            os_version="14.1",
            arch="amd64",
            install_url="http://example.com/freebsd",
            disk={"filesystem": "ntfs"},
        )
        errors = plugin.validate_profile(profile)
        assert any("unsupported filesystem" in e for e in errors)

    def test_unsupported_arch(self, plugin: FreeBSDPlugin) -> None:
        profile = ProvisionProfile(
            name="freebsd-server",
            os_family="freebsd",
            os_version="14.1",
            arch="mips",
            install_url="http://example.com/freebsd",
        )
        errors = plugin.validate_profile(profile)
        assert any("unsupported architecture" in e for e in errors)

    def test_valid_filesystems_accepted(self, plugin: FreeBSDPlugin) -> None:
        for fs in ("zfs", "ufs"):
            profile = ProvisionProfile(
                name="freebsd-server",
                os_family="freebsd",
                os_version="14.1",
                arch="amd64",
                install_url="http://example.com/freebsd",
                disk={"filesystem": fs},
            )
            errors = plugin.validate_profile(profile)
            assert not any("filesystem" in e for e in errors), f"{fs} should be valid"
