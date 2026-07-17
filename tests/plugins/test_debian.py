"""Tests for the Debian preseed plugin."""

from __future__ import annotations

import pytest

from pxeos.models import BootFirmware, ProvisionProfile
from pxeos.plugins.debian import DebianPlugin


@pytest.fixture
def plugin() -> DebianPlugin:
    return DebianPlugin()


@pytest.fixture
def valid_profile() -> ProvisionProfile:
    return ProvisionProfile(
        name="debian-server",
        os_family="debian",
        os_version="12",
        autoinstall_url="http://pxe.example.com/preseed/debian-server",
        packages=["vim", "curl"],
        post_scripts=["systemctl enable sshd"],
    )


class TestOsFamily:
    def test_returns_debian(self, plugin: DebianPlugin) -> None:
        assert plugin.os_family == "debian"

    def test_supported_versions(self, plugin: DebianPlugin) -> None:
        versions = plugin.supported_versions
        assert "11" in versions
        assert "12" in versions
        assert "13" in versions

    def test_autoinstall_filename(self, plugin: DebianPlugin) -> None:
        assert plugin.autoinstall_filename() == "preseed.cfg"


class TestGenerateAutoinstall:
    def test_contains_di_directives(
        self, plugin: DebianPlugin, valid_profile: ProvisionProfile
    ) -> None:
        output = plugin.generate_autoinstall(valid_profile)
        assert "d-i debian-installer/locale" in output
        assert "d-i netcfg/" in output

    def test_contains_mirror_settings(
        self, plugin: DebianPlugin, valid_profile: ProvisionProfile
    ) -> None:
        output = plugin.generate_autoinstall(valid_profile)
        assert "d-i mirror/http/hostname" in output
        assert "deb.debian.org" in output

    def test_contains_partitioning(
        self, plugin: DebianPlugin, valid_profile: ProvisionProfile
    ) -> None:
        output = plugin.generate_autoinstall(valid_profile)
        assert "d-i partman-auto/method" in output

    def test_contains_packages(
        self, plugin: DebianPlugin, valid_profile: ProvisionProfile
    ) -> None:
        output = plugin.generate_autoinstall(valid_profile)
        assert "vim" in output
        assert "curl" in output

    def test_contains_hostname(
        self, plugin: DebianPlugin, valid_profile: ProvisionProfile
    ) -> None:
        output = plugin.generate_autoinstall(valid_profile)
        assert "debian-server" in output

    def test_contains_preseed_header(
        self, plugin: DebianPlugin, valid_profile: ProvisionProfile
    ) -> None:
        output = plugin.generate_autoinstall(valid_profile)
        assert "PxeOS generated Preseed" in output

    def test_contains_post_scripts(
        self, plugin: DebianPlugin, valid_profile: ProvisionProfile
    ) -> None:
        output = plugin.generate_autoinstall(valid_profile)
        assert "preseed/late_command" in output
        assert "systemctl enable sshd" in output


class TestValidateProfile:
    def test_valid_profile_no_errors(
        self, plugin: DebianPlugin, valid_profile: ProvisionProfile
    ) -> None:
        errors = plugin.validate_profile(valid_profile)
        assert errors == []

    def test_missing_autoinstall_url(self, plugin: DebianPlugin) -> None:
        profile = ProvisionProfile(
            name="debian-server",
            os_family="debian",
            os_version="12",
            autoinstall_url="",
        )
        errors = plugin.validate_profile(profile)
        assert any("autoinstall_url" in e for e in errors)

    def test_unsupported_arch(self, plugin: DebianPlugin) -> None:
        profile = ProvisionProfile(
            name="debian-server",
            os_family="debian",
            os_version="12",
            arch="mips",
            autoinstall_url="http://example.com/preseed",
        )
        errors = plugin.validate_profile(profile)
        assert any("unsupported arch" in e for e in errors)


class TestBootAssets:
    def test_kernel_path(
        self, plugin: DebianPlugin, valid_profile: ProvisionProfile
    ) -> None:
        assets = plugin.boot_assets(valid_profile)
        assert assets.kernel == "install.amd/vmlinuz"

    def test_initrd_path(
        self, plugin: DebianPlugin, valid_profile: ProvisionProfile
    ) -> None:
        assets = plugin.boot_assets(valid_profile)
        assert assets.initrd == "install.amd/initrd.gz"

    def test_boot_args_contain_auto_true(
        self, plugin: DebianPlugin, valid_profile: ProvisionProfile
    ) -> None:
        assets = plugin.boot_assets(valid_profile)
        assert "auto=true" in assets.boot_args

    def test_boot_args_contain_url(
        self, plugin: DebianPlugin, valid_profile: ProvisionProfile
    ) -> None:
        assets = plugin.boot_assets(valid_profile)
        assert any("url=" in arg for arg in assets.boot_args)

    def test_bios_bootloader_config(self, plugin: DebianPlugin) -> None:
        profile = ProvisionProfile(
            name="debian-bios",
            os_family="debian",
            os_version="12",
            firmware=BootFirmware.BIOS,
            autoinstall_url="http://example.com/preseed",
        )
        assets = plugin.boot_assets(profile)
        assert "PXELINUX" in assets.bootloader_config

    def test_uefi_bootloader_config(self, plugin: DebianPlugin) -> None:
        profile = ProvisionProfile(
            name="debian-uefi",
            os_family="debian",
            os_version="12",
            firmware=BootFirmware.UEFI,
            autoinstall_url="http://example.com/preseed",
        )
        assets = plugin.boot_assets(profile)
        assert "linuxefi" in assets.bootloader_config
