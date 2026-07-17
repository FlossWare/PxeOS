"""Tests for the Arch Linux archinstall plugin."""

from __future__ import annotations

import json

import pytest

from pxeos.models import BootFirmware, ProvisionProfile
from pxeos.plugins.arch import ArchPlugin


@pytest.fixture
def plugin() -> ArchPlugin:
    return ArchPlugin()


@pytest.fixture
def valid_profile() -> ProvisionProfile:
    return ProvisionProfile(
        name="arch-workstation",
        os_family="arch",
        os_version="latest",
        autoinstall_url="http://pxe.example.com/archinstall/config.json",
        install_url="http://mirror.example.com/archlinux",
        packages=["vim", "git"],
    )


class TestOsFamily:
    def test_returns_arch(self, plugin: ArchPlugin) -> None:
        assert plugin.os_family == "arch"

    def test_supported_versions(self, plugin: ArchPlugin) -> None:
        versions = plugin.supported_versions
        assert "latest" in versions
        assert "rolling" in versions

    def test_autoinstall_filename(self, plugin: ArchPlugin) -> None:
        assert plugin.autoinstall_filename() == "user_configuration.json"


class TestGenerateAutoinstall:
    def test_produces_valid_json(
        self, plugin: ArchPlugin, valid_profile: ProvisionProfile
    ) -> None:
        output = plugin.generate_autoinstall(valid_profile)
        parsed = json.loads(output)
        assert isinstance(parsed, dict)

    def test_json_contains_config_version(
        self, plugin: ArchPlugin, valid_profile: ProvisionProfile
    ) -> None:
        output = plugin.generate_autoinstall(valid_profile)
        parsed = json.loads(output)
        assert "config_version" in parsed

    def test_json_contains_hostname(
        self, plugin: ArchPlugin, valid_profile: ProvisionProfile
    ) -> None:
        output = plugin.generate_autoinstall(valid_profile)
        parsed = json.loads(output)
        assert parsed["hostname"] == "arch-workstation"

    def test_json_contains_bootloader(
        self, plugin: ArchPlugin, valid_profile: ProvisionProfile
    ) -> None:
        output = plugin.generate_autoinstall(valid_profile)
        parsed = json.loads(output)
        assert "bootloader" in parsed
        assert parsed["bootloader"] == "systemd-bootctl"

    def test_json_contains_disk_config(
        self, plugin: ArchPlugin, valid_profile: ProvisionProfile
    ) -> None:
        output = plugin.generate_autoinstall(valid_profile)
        parsed = json.loads(output)
        assert "disk_config" in parsed

    def test_json_contains_packages(
        self, plugin: ArchPlugin, valid_profile: ProvisionProfile
    ) -> None:
        output = plugin.generate_autoinstall(valid_profile)
        parsed = json.loads(output)
        assert "packages" in parsed
        assert "vim" in parsed["packages"]
        assert "git" in parsed["packages"]

    def test_json_contains_locale(
        self, plugin: ArchPlugin, valid_profile: ProvisionProfile
    ) -> None:
        output = plugin.generate_autoinstall(valid_profile)
        parsed = json.loads(output)
        assert "locale_config" in parsed

    def test_json_contains_mirror_config(
        self, plugin: ArchPlugin, valid_profile: ProvisionProfile
    ) -> None:
        output = plugin.generate_autoinstall(valid_profile)
        parsed = json.loads(output)
        assert "mirror_config" in parsed


class TestBootAssets:
    def test_kernel_path(
        self, plugin: ArchPlugin, valid_profile: ProvisionProfile
    ) -> None:
        assets = plugin.boot_assets(valid_profile)
        assert assets.kernel == "arch/boot/x86_64/vmlinuz-linux"

    def test_initrd_path(
        self, plugin: ArchPlugin, valid_profile: ProvisionProfile
    ) -> None:
        assets = plugin.boot_assets(valid_profile)
        assert assets.initrd == "arch/boot/x86_64/initramfs-linux.img"

    def test_boot_args_contain_archisobasedir(
        self, plugin: ArchPlugin, valid_profile: ProvisionProfile
    ) -> None:
        assets = plugin.boot_assets(valid_profile)
        assert "archisobasedir=arch" in assets.boot_args

    def test_boot_args_contain_archiso_http(
        self, plugin: ArchPlugin, valid_profile: ProvisionProfile
    ) -> None:
        assets = plugin.boot_assets(valid_profile)
        assert any("archiso_http_srv=" in arg for arg in assets.boot_args)

    def test_boot_args_contain_archinstall_config(
        self, plugin: ArchPlugin, valid_profile: ProvisionProfile
    ) -> None:
        assets = plugin.boot_assets(valid_profile)
        assert any("archinstall_config=" in arg for arg in assets.boot_args)

    def test_bios_bootloader_config(self, plugin: ArchPlugin) -> None:
        profile = ProvisionProfile(
            name="arch-bios",
            os_family="arch",
            os_version="latest",
            firmware=BootFirmware.BIOS,
            autoinstall_url="http://example.com/archinstall",
            install_url="http://example.com/archlinux",
        )
        assets = plugin.boot_assets(profile)
        assert "PXELINUX" in assets.bootloader_config

    def test_uefi_bootloader_config(self, plugin: ArchPlugin) -> None:
        profile = ProvisionProfile(
            name="arch-uefi",
            os_family="arch",
            os_version="latest",
            firmware=BootFirmware.UEFI,
            autoinstall_url="http://example.com/archinstall",
            install_url="http://example.com/archlinux",
        )
        assets = plugin.boot_assets(profile)
        assert "linuxefi" in assets.bootloader_config


class TestValidateProfile:
    def test_valid_profile_no_errors(
        self, plugin: ArchPlugin, valid_profile: ProvisionProfile
    ) -> None:
        errors = plugin.validate_profile(valid_profile)
        assert errors == []

    def test_missing_autoinstall_url(self, plugin: ArchPlugin) -> None:
        profile = ProvisionProfile(
            name="arch-workstation",
            os_family="arch",
            os_version="latest",
            autoinstall_url="",
        )
        errors = plugin.validate_profile(profile)
        assert any("autoinstall_url" in e for e in errors)

    def test_unsupported_arch(self, plugin: ArchPlugin) -> None:
        profile = ProvisionProfile(
            name="arch-workstation",
            os_family="arch",
            os_version="latest",
            arch="aarch64",
            autoinstall_url="http://example.com/archinstall",
        )
        errors = plugin.validate_profile(profile)
        assert any("unsupported arch" in e for e in errors)

    def test_x86_64_accepted(self, plugin: ArchPlugin) -> None:
        profile = ProvisionProfile(
            name="arch-workstation",
            os_family="arch",
            os_version="latest",
            arch="x86_64",
            autoinstall_url="http://example.com/archinstall",
        )
        errors = plugin.validate_profile(profile)
        assert not any("arch" in e.lower() and "unsupported" in e.lower() for e in errors)
