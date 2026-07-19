"""Tests for the NetBSD sysinst plugin."""

from __future__ import annotations

import pytest

from pxeos.models import BootFirmware, BootMethod, ProvisionProfile
from pxeos.plugins.netbsd import NetBSDPlugin


@pytest.fixture
def plugin() -> NetBSDPlugin:
    return NetBSDPlugin()


@pytest.fixture
def valid_profile() -> ProvisionProfile:
    return ProvisionProfile(
        name="netbsd-box",
        os_family="netbsd",
        os_version="10.0",
        arch="amd64",
        install_url="http://cdn.netbsd.org/pub/NetBSD",
    )


class TestOsFamily:
    def test_returns_netbsd(self, plugin: NetBSDPlugin) -> None:
        assert plugin.os_family == "netbsd"

    def test_supported_versions(self, plugin: NetBSDPlugin) -> None:
        versions = plugin.supported_versions
        assert "9.3" in versions
        assert "9.4" in versions
        assert "10.0" in versions
        assert "10.1" in versions

    def test_autoinstall_filename(self, plugin: NetBSDPlugin) -> None:
        assert plugin.autoinstall_filename() == "auto_install.cfg"


class TestGenerateAutoinstall:
    def test_contains_hostname(
        self, plugin: NetBSDPlugin, valid_profile: ProvisionProfile
    ) -> None:
        output = plugin.generate_autoinstall(valid_profile)
        assert "hostname=" in output
        assert "netbsd-box" in output

    def test_contains_network_yes(
        self, plugin: NetBSDPlugin, valid_profile: ProvisionProfile
    ) -> None:
        output = plugin.generate_autoinstall(valid_profile)
        assert "network=yes" in output

    def test_contains_disk_setting(
        self, plugin: NetBSDPlugin, valid_profile: ProvisionProfile
    ) -> None:
        output = plugin.generate_autoinstall(valid_profile)
        assert "disk=" in output

    def test_contains_filesystem(
        self, plugin: NetBSDPlugin, valid_profile: ProvisionProfile
    ) -> None:
        output = plugin.generate_autoinstall(valid_profile)
        assert "filesystem=" in output

    def test_contains_sets(
        self, plugin: NetBSDPlugin, valid_profile: ProvisionProfile
    ) -> None:
        output = plugin.generate_autoinstall(valid_profile)
        assert "sets=" in output
        assert "base.tgz" in output

    def test_contains_timezone(
        self, plugin: NetBSDPlugin, valid_profile: ProvisionProfile
    ) -> None:
        output = plugin.generate_autoinstall(valid_profile)
        assert "timezone=" in output

    def test_contains_fetch_url_when_install_url_set(
        self, plugin: NetBSDPlugin, valid_profile: ProvisionProfile
    ) -> None:
        output = plugin.generate_autoinstall(valid_profile)
        assert "fetch_url=" in output

    def test_contains_reboot(
        self, plugin: NetBSDPlugin, valid_profile: ProvisionProfile
    ) -> None:
        output = plugin.generate_autoinstall(valid_profile)
        assert "reboot=yes" in output


class TestBootAssets:
    def test_kernel_is_install_gz(
        self, plugin: NetBSDPlugin, valid_profile: ProvisionProfile
    ) -> None:
        assets = plugin.boot_assets(valid_profile)
        assert "netbsd-INSTALL.gz" in assets.kernel
        assert "amd64" in assets.kernel
        assert assets.boot_method == BootMethod.KERNEL

    def test_no_initrd(
        self, plugin: NetBSDPlugin, valid_profile: ProvisionProfile
    ) -> None:
        assets = plugin.boot_assets(valid_profile)
        assert assets.initrd is None

    def test_memdisk_with_iso(self, plugin: NetBSDPlugin) -> None:
        profile = ProvisionProfile(
            name="netbsd-box",
            os_family="netbsd",
            os_version="10.0",
            arch="amd64",
            install_url="http://cdn.netbsd.org/pub/NetBSD",
            extra={"boot_iso": "NetBSD-10.0-amd64.iso"},
        )
        assets = plugin.boot_assets(profile)
        assert assets.boot_method == BootMethod.MEMDISK
        assert assets.kernel == "memdisk"
        assert assets.initrd == "NetBSD-10.0-amd64.iso"


class TestValidateProfile:
    def test_valid_profile_no_errors(
        self, plugin: NetBSDPlugin, valid_profile: ProvisionProfile
    ) -> None:
        errors = plugin.validate_profile(valid_profile)
        assert errors == []

    def test_missing_install_url(self, plugin: NetBSDPlugin) -> None:
        profile = ProvisionProfile(
            name="netbsd-box",
            os_family="netbsd",
            os_version="10.0",
            arch="amd64",
            install_url="",
        )
        errors = plugin.validate_profile(profile)
        assert any("install_url" in e for e in errors)

    def test_unsupported_arch(self, plugin: NetBSDPlugin) -> None:
        profile = ProvisionProfile(
            name="netbsd-box",
            os_family="netbsd",
            os_version="10.0",
            arch="mips",
            install_url="http://example.com/netbsd",
        )
        errors = plugin.validate_profile(profile)
        assert any("unsupported architecture" in e for e in errors)

    def test_unsupported_filesystem(self, plugin: NetBSDPlugin) -> None:
        profile = ProvisionProfile(
            name="netbsd-box",
            os_family="netbsd",
            os_version="10.0",
            arch="amd64",
            install_url="http://example.com/netbsd",
            disk={"filesystem": "zfs"},
        )
        errors = plugin.validate_profile(profile)
        assert any("unsupported filesystem" in e for e in errors)
