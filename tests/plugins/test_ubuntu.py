"""Tests for the Ubuntu Cloud-Init autoinstall plugin."""

from __future__ import annotations

import pytest

from pxeos.models import BootFirmware, ProvisionProfile
from pxeos.plugins.ubuntu import UbuntuPlugin


@pytest.fixture
def plugin() -> UbuntuPlugin:
    return UbuntuPlugin()


@pytest.fixture
def valid_profile() -> ProvisionProfile:
    return ProvisionProfile(
        name="ubuntu-server",
        os_family="ubuntu",
        os_version="24.04",
        autoinstall_url="http://pxe.example.com/cloud-init/ubuntu",
        packages=["vim", "git"],
    )


class TestOsFamily:
    def test_returns_ubuntu(self, plugin: UbuntuPlugin) -> None:
        assert plugin.os_family == "ubuntu"

    def test_supported_versions(self, plugin: UbuntuPlugin) -> None:
        versions = plugin.supported_versions
        assert "22.04" in versions
        assert "24.04" in versions
        assert "24.10" in versions

    def test_autoinstall_filename(self, plugin: UbuntuPlugin) -> None:
        assert plugin.autoinstall_filename() == "user-data"


class TestGenerateAutoinstall:
    def test_starts_with_cloud_config(
        self, plugin: UbuntuPlugin, valid_profile: ProvisionProfile
    ) -> None:
        output = plugin.generate_autoinstall(valid_profile)
        assert output.startswith("#cloud-config")

    def test_contains_autoinstall_key(
        self, plugin: UbuntuPlugin, valid_profile: ProvisionProfile
    ) -> None:
        output = plugin.generate_autoinstall(valid_profile)
        assert "autoinstall:" in output

    def test_contains_version(
        self, plugin: UbuntuPlugin, valid_profile: ProvisionProfile
    ) -> None:
        output = plugin.generate_autoinstall(valid_profile)
        assert "version:" in output

    def test_contains_identity_hostname(
        self, plugin: UbuntuPlugin, valid_profile: ProvisionProfile
    ) -> None:
        output = plugin.generate_autoinstall(valid_profile)
        assert "hostname:" in output
        assert "ubuntu-server" in output

    def test_contains_packages(
        self, plugin: UbuntuPlugin, valid_profile: ProvisionProfile
    ) -> None:
        output = plugin.generate_autoinstall(valid_profile)
        assert "packages:" in output
        assert "vim" in output
        assert "git" in output

    def test_contains_ssh_config(
        self, plugin: UbuntuPlugin, valid_profile: ProvisionProfile
    ) -> None:
        output = plugin.generate_autoinstall(valid_profile)
        assert "ssh:" in output
        assert "install-server: true" in output

    def test_contains_storage_section(
        self, plugin: UbuntuPlugin, valid_profile: ProvisionProfile
    ) -> None:
        output = plugin.generate_autoinstall(valid_profile)
        assert "storage:" in output


class TestValidateProfile:
    def test_valid_profile_no_errors(
        self, plugin: UbuntuPlugin, valid_profile: ProvisionProfile
    ) -> None:
        errors = plugin.validate_profile(valid_profile)
        assert errors == []

    def test_missing_autoinstall_url(self, plugin: UbuntuPlugin) -> None:
        profile = ProvisionProfile(
            name="ubuntu-server",
            os_family="ubuntu",
            os_version="24.04",
            autoinstall_url="",
        )
        errors = plugin.validate_profile(profile)
        assert any("autoinstall_url" in e for e in errors)

    def test_unsupported_arch(self, plugin: UbuntuPlugin) -> None:
        profile = ProvisionProfile(
            name="ubuntu-server",
            os_family="ubuntu",
            os_version="24.04",
            arch="mips",
            autoinstall_url="http://example.com/cloud-init",
        )
        errors = plugin.validate_profile(profile)
        assert any("unsupported arch" in e for e in errors)


class TestBootAssets:
    def test_kernel_path(
        self, plugin: UbuntuPlugin, valid_profile: ProvisionProfile
    ) -> None:
        assets = plugin.boot_assets(valid_profile)
        assert assets.kernel == "casper/vmlinuz"

    def test_initrd_path(
        self, plugin: UbuntuPlugin, valid_profile: ProvisionProfile
    ) -> None:
        assets = plugin.boot_assets(valid_profile)
        assert assets.initrd == "casper/initrd"

    def test_boot_args_contain_autoinstall(
        self, plugin: UbuntuPlugin, valid_profile: ProvisionProfile
    ) -> None:
        assets = plugin.boot_assets(valid_profile)
        assert "autoinstall" in assets.boot_args

    def test_boot_args_contain_nocloud(
        self, plugin: UbuntuPlugin, valid_profile: ProvisionProfile
    ) -> None:
        assets = plugin.boot_assets(valid_profile)
        assert any("ds=nocloud-net" in arg for arg in assets.boot_args)

    def test_boot_args_contain_ip_dhcp(
        self, plugin: UbuntuPlugin, valid_profile: ProvisionProfile
    ) -> None:
        assets = plugin.boot_assets(valid_profile)
        assert "ip=dhcp" in assets.boot_args

    def test_bios_bootloader_config(self, plugin: UbuntuPlugin) -> None:
        profile = ProvisionProfile(
            name="ubuntu-bios",
            os_family="ubuntu",
            os_version="24.04",
            firmware=BootFirmware.BIOS,
            autoinstall_url="http://example.com/cloud-init",
        )
        assets = plugin.boot_assets(profile)
        assert "PXELINUX" in assets.bootloader_config

    def test_uefi_bootloader_config(self, plugin: UbuntuPlugin) -> None:
        profile = ProvisionProfile(
            name="ubuntu-uefi",
            os_family="ubuntu",
            os_version="24.04",
            firmware=BootFirmware.UEFI,
            autoinstall_url="http://example.com/cloud-init",
        )
        assets = plugin.boot_assets(profile)
        assert "linuxefi" in assets.bootloader_config
