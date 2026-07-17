"""Tests for the OpenBSD autoinstall plugin."""

from __future__ import annotations

import pytest

from pxeos.models import BootFirmware, ProvisionProfile
from pxeos.plugins.openbsd import OpenBSDPlugin


@pytest.fixture
def plugin() -> OpenBSDPlugin:
    return OpenBSDPlugin()


@pytest.fixture
def valid_profile() -> ProvisionProfile:
    return ProvisionProfile(
        name="openbsd-fw",
        os_family="openbsd",
        os_version="7.6",
        arch="amd64",
        install_url="http://cdn.openbsd.org/pub/OpenBSD",
    )


class TestOsFamily:
    def test_returns_openbsd(self, plugin: OpenBSDPlugin) -> None:
        assert plugin.os_family == "openbsd"

    def test_supported_versions(self, plugin: OpenBSDPlugin) -> None:
        versions = plugin.supported_versions
        assert "7.4" in versions
        assert "7.5" in versions
        assert "7.6" in versions

    def test_autoinstall_filename(self, plugin: OpenBSDPlugin) -> None:
        assert plugin.autoinstall_filename() == "install.conf"


class TestGenerateAutoinstall:
    def test_key_value_format(
        self, plugin: OpenBSDPlugin, valid_profile: ProvisionProfile
    ) -> None:
        output = plugin.generate_autoinstall(valid_profile)
        assert "System hostname =" in output
        assert "Password for root account =" in output

    def test_contains_network_interfaces(
        self, plugin: OpenBSDPlugin, valid_profile: ProvisionProfile
    ) -> None:
        output = plugin.generate_autoinstall(valid_profile)
        assert "Network interfaces =" in output

    def test_contains_hostname(
        self, plugin: OpenBSDPlugin, valid_profile: ProvisionProfile
    ) -> None:
        output = plugin.generate_autoinstall(valid_profile)
        assert "openbsd-fw" in output

    def test_contains_disk_section(
        self, plugin: OpenBSDPlugin, valid_profile: ProvisionProfile
    ) -> None:
        output = plugin.generate_autoinstall(valid_profile)
        assert "Which disk is the root disk =" in output

    def test_contains_timezone(
        self, plugin: OpenBSDPlugin, valid_profile: ProvisionProfile
    ) -> None:
        output = plugin.generate_autoinstall(valid_profile)
        assert "What timezone are you in =" in output

    def test_contains_sets_section(
        self, plugin: OpenBSDPlugin, valid_profile: ProvisionProfile
    ) -> None:
        output = plugin.generate_autoinstall(valid_profile)
        assert "Set name(s) =" in output

    def test_contains_http_location_when_url_set(
        self, plugin: OpenBSDPlugin, valid_profile: ProvisionProfile
    ) -> None:
        output = plugin.generate_autoinstall(valid_profile)
        assert "Location of sets = http" in output
        assert "HTTP Server =" in output

    def test_contains_profile_comment(
        self, plugin: OpenBSDPlugin, valid_profile: ProvisionProfile
    ) -> None:
        output = plugin.generate_autoinstall(valid_profile)
        assert "OpenBSD autoinstall" in output


class TestBootAssets:
    def test_kernel_path_contains_bsd_rd(
        self, plugin: OpenBSDPlugin, valid_profile: ProvisionProfile
    ) -> None:
        assets = plugin.boot_assets(valid_profile)
        assert "bsd.rd" in assets.kernel

    def test_kernel_path_contains_version_and_arch(
        self, plugin: OpenBSDPlugin, valid_profile: ProvisionProfile
    ) -> None:
        assets = plugin.boot_assets(valid_profile)
        assert "7.6" in assets.kernel
        assert "amd64" in assets.kernel

    def test_no_initrd(
        self, plugin: OpenBSDPlugin, valid_profile: ProvisionProfile
    ) -> None:
        assets = plugin.boot_assets(valid_profile)
        assert assets.initrd is None

    def test_boot_args_contain_tftproot(
        self, plugin: OpenBSDPlugin, valid_profile: ProvisionProfile
    ) -> None:
        assets = plugin.boot_assets(valid_profile)
        assert any("tftproot=" in arg for arg in assets.boot_args)

    def test_bootloader_config_contains_comment(
        self, plugin: OpenBSDPlugin, valid_profile: ProvisionProfile
    ) -> None:
        assets = plugin.boot_assets(valid_profile)
        assert "OpenBSD" in assets.bootloader_config


class TestValidateProfile:
    def test_valid_profile_no_errors(
        self, plugin: OpenBSDPlugin, valid_profile: ProvisionProfile
    ) -> None:
        errors = plugin.validate_profile(valid_profile)
        assert errors == []

    def test_missing_install_url(self, plugin: OpenBSDPlugin) -> None:
        profile = ProvisionProfile(
            name="openbsd-fw",
            os_family="openbsd",
            os_version="7.6",
            arch="amd64",
            install_url="",
        )
        errors = plugin.validate_profile(profile)
        assert any("install_url" in e for e in errors)

    def test_unsupported_arch(self, plugin: OpenBSDPlugin) -> None:
        profile = ProvisionProfile(
            name="openbsd-fw",
            os_family="openbsd",
            os_version="7.6",
            arch="mips",
            install_url="http://example.com/openbsd",
        )
        errors = plugin.validate_profile(profile)
        assert any("unsupported architecture" in e for e in errors)
