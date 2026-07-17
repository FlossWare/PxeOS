"""Tests for the SUSE AutoYaST plugin."""

from __future__ import annotations

import pytest

from pxeos.models import BootFirmware, ProvisionProfile
from pxeos.plugins.suse import SUSEPlugin


@pytest.fixture
def plugin() -> SUSEPlugin:
    return SUSEPlugin()


@pytest.fixture
def valid_profile() -> ProvisionProfile:
    return ProvisionProfile(
        name="suse-server",
        os_family="suse",
        os_version="15.6",
        install_url="http://mirror.example.com/suse/15.6",
        autoinstall_url="http://pxe.example.com/autoyast/suse-server",
        packages=["vim", "wget"],
    )


class TestOsFamily:
    def test_returns_suse(self, plugin: SUSEPlugin) -> None:
        assert plugin.os_family == "suse"

    def test_supported_versions(self, plugin: SUSEPlugin) -> None:
        versions = plugin.supported_versions
        assert "15.5" in versions
        assert "15.6" in versions
        assert "tumbleweed" in versions
        assert "leap-15.5" in versions
        assert "leap-15.6" in versions

    def test_autoinstall_filename(self, plugin: SUSEPlugin) -> None:
        assert plugin.autoinstall_filename() == "autoinst.xml"


class TestGenerateAutoinstall:
    def test_is_valid_xml(
        self, plugin: SUSEPlugin, valid_profile: ProvisionProfile
    ) -> None:
        output = plugin.generate_autoinstall(valid_profile)
        assert '<?xml version="1.0"?>' in output

    def test_has_suse_namespace(
        self, plugin: SUSEPlugin, valid_profile: ProvisionProfile
    ) -> None:
        output = plugin.generate_autoinstall(valid_profile)
        assert "http://www.suse.com/1.0/yast2ns" in output

    def test_has_config_namespace(
        self, plugin: SUSEPlugin, valid_profile: ProvisionProfile
    ) -> None:
        output = plugin.generate_autoinstall(valid_profile)
        assert "http://www.suse.com/1.0/configns" in output

    def test_contains_profile_element(
        self, plugin: SUSEPlugin, valid_profile: ProvisionProfile
    ) -> None:
        output = plugin.generate_autoinstall(valid_profile)
        assert "<profile" in output
        assert "</profile>" in output

    def test_contains_hostname(
        self, plugin: SUSEPlugin, valid_profile: ProvisionProfile
    ) -> None:
        output = plugin.generate_autoinstall(valid_profile)
        assert "<hostname>suse-server</hostname>" in output

    def test_contains_packages(
        self, plugin: SUSEPlugin, valid_profile: ProvisionProfile
    ) -> None:
        output = plugin.generate_autoinstall(valid_profile)
        assert "<package>vim</package>" in output
        assert "<package>wget</package>" in output

    def test_contains_software_section(
        self, plugin: SUSEPlugin, valid_profile: ProvisionProfile
    ) -> None:
        output = plugin.generate_autoinstall(valid_profile)
        assert "<software>" in output
        assert "<pattern>base</pattern>" in output

    def test_contains_partitioning(
        self, plugin: SUSEPlugin, valid_profile: ProvisionProfile
    ) -> None:
        output = plugin.generate_autoinstall(valid_profile)
        assert "<partitioning" in output

    def test_contains_firewall_enabled_by_default(
        self, plugin: SUSEPlugin, valid_profile: ProvisionProfile
    ) -> None:
        output = plugin.generate_autoinstall(valid_profile)
        assert "<enable_firewall" in output


class TestValidateProfile:
    def test_valid_profile_no_errors(
        self, plugin: SUSEPlugin, valid_profile: ProvisionProfile
    ) -> None:
        errors = plugin.validate_profile(valid_profile)
        assert errors == []

    def test_missing_install_url(self, plugin: SUSEPlugin) -> None:
        profile = ProvisionProfile(
            name="suse-server",
            os_family="suse",
            os_version="15.6",
            install_url="",
            autoinstall_url="http://example.com/autoyast",
        )
        errors = plugin.validate_profile(profile)
        assert any("install_url" in e for e in errors)

    def test_missing_autoinstall_url(self, plugin: SUSEPlugin) -> None:
        profile = ProvisionProfile(
            name="suse-server",
            os_family="suse",
            os_version="15.6",
            install_url="http://example.com/suse",
            autoinstall_url="",
        )
        errors = plugin.validate_profile(profile)
        assert any("autoinstall_url" in e for e in errors)

    def test_unsupported_arch(self, plugin: SUSEPlugin) -> None:
        profile = ProvisionProfile(
            name="suse-server",
            os_family="suse",
            os_version="15.6",
            arch="mips",
            install_url="http://example.com/suse",
            autoinstall_url="http://example.com/autoyast",
        )
        errors = plugin.validate_profile(profile)
        assert any("unsupported arch" in e for e in errors)


class TestBootAssets:
    def test_kernel_path(
        self, plugin: SUSEPlugin, valid_profile: ProvisionProfile
    ) -> None:
        assets = plugin.boot_assets(valid_profile)
        assert assets.kernel == "boot/x86_64/loader/linux"

    def test_initrd_path(
        self, plugin: SUSEPlugin, valid_profile: ProvisionProfile
    ) -> None:
        assets = plugin.boot_assets(valid_profile)
        assert assets.initrd == "boot/x86_64/loader/initrd"

    def test_boot_args_contain_autoyast(
        self, plugin: SUSEPlugin, valid_profile: ProvisionProfile
    ) -> None:
        assets = plugin.boot_assets(valid_profile)
        assert any("autoyast=" in arg for arg in assets.boot_args)

    def test_boot_args_contain_install(
        self, plugin: SUSEPlugin, valid_profile: ProvisionProfile
    ) -> None:
        assets = plugin.boot_assets(valid_profile)
        assert any("install=" in arg for arg in assets.boot_args)

    def test_bios_bootloader(self, plugin: SUSEPlugin) -> None:
        profile = ProvisionProfile(
            name="suse-bios",
            os_family="suse",
            os_version="15.6",
            firmware=BootFirmware.BIOS,
            install_url="http://example.com/suse",
            autoinstall_url="http://example.com/autoyast",
        )
        assets = plugin.boot_assets(profile)
        assert "PXELINUX" in assets.bootloader_config

    def test_uefi_bootloader(self, plugin: SUSEPlugin) -> None:
        profile = ProvisionProfile(
            name="suse-uefi",
            os_family="suse",
            os_version="15.6",
            firmware=BootFirmware.UEFI,
            install_url="http://example.com/suse",
            autoinstall_url="http://example.com/autoyast",
        )
        assets = plugin.boot_assets(profile)
        assert "linuxefi" in assets.bootloader_config
