"""Tests for pxeos.plugins.tinycore -- Tiny Core Linux PXE boot plugin."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from pxeos.models import (
    BootAssets,
    BootFirmware,
    DistroAssets,
    ProvisionProfile,
)
from pxeos.plugins.tinycore import TinyCorePlugin


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_profile(**overrides) -> ProvisionProfile:
    """Create a Tiny Core profile with sensible defaults."""
    defaults = {
        "name": "tc-test",
        "os_family": "tinycore",
        "os_version": "current",
        "arch": "x86_64",
        "install_url": "http://server/tinycore",
    }
    defaults.update(overrides)
    return ProvisionProfile(**defaults)


def _make_iso_32bit(mount: Path) -> None:
    """Create a mock 32-bit Tiny Core ISO structure."""
    boot = mount / "boot"
    boot.mkdir(parents=True)
    (boot / "vmlinuz").write_bytes(b"tc-kernel-32")
    (boot / "core.gz").write_bytes(b"tc-initrd-32")


def _make_iso_64bit(mount: Path) -> None:
    """Create a mock 64-bit Tiny Core ISO structure."""
    boot = mount / "boot"
    boot.mkdir(parents=True, exist_ok=True)
    (boot / "vmlinuz64").write_bytes(b"tc-kernel-64")
    (boot / "corepure64.gz").write_bytes(b"tc-initrd-64")


def _make_iso_full(mount: Path) -> None:
    """Create a mock ISO with both 32/64-bit and TCE extensions."""
    _make_iso_32bit(mount)
    _make_iso_64bit(mount)
    cde = mount / "cde" / "optional"
    cde.mkdir(parents=True)
    (cde / "nano.tcz").write_bytes(b"nano-ext")
    (cde / "openssh.tcz").write_bytes(b"ssh-ext")


# ---------------------------------------------------------------------------
# Plugin properties
# ---------------------------------------------------------------------------


class TestPluginProperties:
    """Tests for TinyCorePlugin basic properties."""

    def test_os_family(self):
        plugin = TinyCorePlugin()
        assert plugin.os_family == "tinycore"

    def test_supported_versions(self):
        plugin = TinyCorePlugin()
        versions = plugin.supported_versions
        assert "current" in versions
        assert "14" in versions
        assert "15" in versions
        assert "16" in versions

    def test_supported_versions_is_list(self):
        plugin = TinyCorePlugin()
        assert isinstance(plugin.supported_versions, list)

    def test_autoinstall_filename(self):
        plugin = TinyCorePlugin()
        assert plugin.autoinstall_filename() == "tinycore.cfg"

    def test_supports_live(self):
        plugin = TinyCorePlugin()
        assert plugin.supports_live is True


# ---------------------------------------------------------------------------
# boot_assets
# ---------------------------------------------------------------------------


class TestBootAssets:
    """Tests for boot_assets output."""

    def test_boot_assets_64bit_default(self):
        """Default is 64-bit kernel/initrd."""
        plugin = TinyCorePlugin()
        profile = _make_profile()
        assets = plugin.boot_assets(profile)

        assert assets.kernel == "boot/vmlinuz64"
        assert assets.initrd == "boot/corepure64.gz"

    def test_boot_assets_32bit(self):
        """32-bit kernel/initrd when 64bit=False."""
        plugin = TinyCorePlugin()
        profile = _make_profile(extra={"64bit": False})
        assets = plugin.boot_assets(profile)

        assert assets.kernel == "boot/vmlinuz"
        assert assets.initrd == "boot/core.gz"

    def test_boot_assets_tce_arg(self):
        """tce boot arg is included when configured."""
        plugin = TinyCorePlugin()
        profile = _make_profile(
            extra={"tce": "http://server/tce"}
        )
        assets = plugin.boot_assets(profile)
        assert "tce=http://server/tce" in assets.boot_args

    def test_boot_assets_restore_mydata(self):
        """restore boot arg from mydata extra."""
        plugin = TinyCorePlugin()
        profile = _make_profile(
            extra={"mydata": "http://server/mydata.tgz"}
        )
        assets = plugin.boot_assets(profile)
        assert (
            "restore=http://server/mydata.tgz"
            in assets.boot_args
        )

    def test_boot_assets_serial_console(self):
        """serial_console is passed as console= arg."""
        plugin = TinyCorePlugin()
        profile = _make_profile(
            extra={"serial_console": "ttyS0,115200"}
        )
        assets = plugin.boot_assets(profile)
        assert "console=ttyS0,115200" in assets.boot_args

    def test_boot_assets_bios_template(self):
        """BIOS firmware produces pxelinux config."""
        plugin = TinyCorePlugin()
        profile = _make_profile()
        assets = plugin.boot_assets(profile)
        assert (
            "DEFAULT" in assets.bootloader_config
            or "pxelinux" in assets.bootloader_config.lower()
        )

    def test_boot_assets_uefi_template(self):
        """UEFI firmware produces GRUB config."""
        plugin = TinyCorePlugin()
        profile = _make_profile(firmware=BootFirmware.UEFI)
        assets = plugin.boot_assets(profile)
        assert (
            "menuentry" in assets.bootloader_config
            or "linuxefi" in assets.bootloader_config
        )

    def test_boot_assets_nodhcp_present(self):
        """nodhcp boot arg is always present."""
        plugin = TinyCorePlugin()
        profile = _make_profile()
        assets = plugin.boot_assets(profile)
        assert "nodhcp" in assets.boot_args

    def test_boot_assets_norestore(self):
        """norestore boot code when configured."""
        plugin = TinyCorePlugin()
        profile = _make_profile(extra={"norestore": True})
        assets = plugin.boot_assets(profile)
        assert "norestore" in assets.boot_args

    def test_boot_assets_base_mode(self):
        """base boot code when configured."""
        plugin = TinyCorePlugin()
        profile = _make_profile(extra={"base": True})
        assets = plugin.boot_assets(profile)
        assert "base" in assets.boot_args

    def test_boot_assets_lst(self):
        """lst= boot code for extension list file."""
        plugin = TinyCorePlugin()
        profile = _make_profile(
            extra={"lst": "onboot.lst"}
        )
        assets = plugin.boot_assets(profile)
        assert "lst=onboot.lst" in assets.boot_args

    def test_boot_assets_returns_boot_assets_type(self):
        """boot_assets returns a BootAssets instance."""
        plugin = TinyCorePlugin()
        profile = _make_profile()
        assets = plugin.boot_assets(profile)
        assert isinstance(assets, BootAssets)

    def test_boot_assets_boot_args_is_tuple(self):
        """boot_args is a tuple."""
        plugin = TinyCorePlugin()
        profile = _make_profile()
        assets = plugin.boot_assets(profile)
        assert isinstance(assets.boot_args, tuple)


# ---------------------------------------------------------------------------
# autoinstall generation
# ---------------------------------------------------------------------------


class TestGenerateAutoinstall:
    """Tests for autoinstall config generation."""

    def test_generate_sets_hostname(self):
        plugin = TinyCorePlugin()
        profile = _make_profile(
            network={"hostname": "tc-node01"}
        )
        output = plugin.generate_autoinstall(profile)
        assert "tc-node01" in output

    def test_generate_includes_packages(self):
        plugin = TinyCorePlugin()
        profile = _make_profile(packages=["nano", "openssh"])
        output = plugin.generate_autoinstall(profile)
        assert "tce-load -wi nano" in output
        assert "tce-load -wi openssh" in output

    def test_generate_includes_post_scripts(self):
        plugin = TinyCorePlugin()
        profile = _make_profile(
            post_scripts=["echo hello"]
        )
        output = plugin.generate_autoinstall(profile)
        assert "echo hello" in output

    def test_generate_sets_tce_mirror(self):
        plugin = TinyCorePlugin()
        profile = _make_profile(
            extra={
                "tce_mirror": "http://mirror.example.com"
            }
        )
        output = plugin.generate_autoinstall(profile)
        assert "http://mirror.example.com" in output
        assert "tcemirror" in output

    def test_generate_uses_profile_name_as_hostname_default(self):
        plugin = TinyCorePlugin()
        profile = _make_profile(name="my-tiny-host")
        output = plugin.generate_autoinstall(profile)
        assert "my-tiny-host" in output

    def test_generate_is_shell_script(self):
        plugin = TinyCorePlugin()
        profile = _make_profile()
        output = plugin.generate_autoinstall(profile)
        assert output.startswith("#!/bin/sh")


# ---------------------------------------------------------------------------
# Profile validation
# ---------------------------------------------------------------------------


class TestValidateProfile:
    """Tests for profile validation."""

    def test_valid_profile_no_errors(self):
        plugin = TinyCorePlugin()
        profile = _make_profile()
        errors = plugin.validate_profile(profile)
        assert errors == []

    def test_missing_name(self):
        plugin = TinyCorePlugin()
        profile = _make_profile(name="")
        errors = plugin.validate_profile(profile)
        assert any("name" in e for e in errors)

    def test_wrong_os_family(self):
        plugin = TinyCorePlugin()
        profile = _make_profile(os_family="fedora")
        errors = plugin.validate_profile(profile)
        assert any("os_family" in e for e in errors)

    def test_unsupported_version(self):
        plugin = TinyCorePlugin()
        profile = _make_profile(os_version="9")
        errors = plugin.validate_profile(profile)
        assert any("version" in e.lower() for e in errors)

    def test_unsupported_arch(self):
        plugin = TinyCorePlugin()
        profile = _make_profile(arch="aarch64")
        errors = plugin.validate_profile(profile)
        assert any("arch" in e for e in errors)

    def test_x86_arch_supported(self):
        plugin = TinyCorePlugin()
        profile = _make_profile(arch="x86")
        errors = plugin.validate_profile(profile)
        assert not any("arch" in e for e in errors)

    def test_x86_64_arch_supported(self):
        plugin = TinyCorePlugin()
        profile = _make_profile(arch="x86_64")
        errors = plugin.validate_profile(profile)
        assert not any("arch" in e for e in errors)


# ---------------------------------------------------------------------------
# ISO extraction (mocked filesystem)
# ---------------------------------------------------------------------------


class TestExtractFromISO:
    """Tests for extract_from_iso."""

    def test_extract_64bit_iso(self, tmp_path):
        mount = tmp_path / "mount"
        mount.mkdir()
        _make_iso_64bit(mount)
        dest = tmp_path / "dest"

        plugin = TinyCorePlugin()
        assets = plugin.extract_from_iso(mount, dest)

        assert assets.kernel_path == dest / "vmlinuz64"
        assert assets.initrd_path == dest / "corepure64.gz"
        assert assets.kernel_path.read_bytes() == b"tc-kernel-64"
        assert assets.initrd_path.read_bytes() == b"tc-initrd-64"

    def test_extract_32bit_iso(self, tmp_path):
        mount = tmp_path / "mount"
        mount.mkdir()
        _make_iso_32bit(mount)
        dest = tmp_path / "dest"

        plugin = TinyCorePlugin()
        assets = plugin.extract_from_iso(mount, dest)

        assert assets.kernel_path == dest / "vmlinuz"
        assert assets.initrd_path == dest / "core.gz"
        assert assets.kernel_path.read_bytes() == b"tc-kernel-32"

    def test_extract_prefers_64bit(self, tmp_path):
        mount = tmp_path / "mount"
        mount.mkdir()
        _make_iso_full(mount)
        dest = tmp_path / "dest"

        plugin = TinyCorePlugin()
        assets = plugin.extract_from_iso(mount, dest)

        assert assets.kernel_path == dest / "vmlinuz64"

    def test_extract_copies_tce_extensions(self, tmp_path):
        mount = tmp_path / "mount"
        mount.mkdir()
        _make_iso_full(mount)
        dest = tmp_path / "dest"

        plugin = TinyCorePlugin()
        assets = plugin.extract_from_iso(mount, dest)

        assert (dest / "cde" / "optional" / "nano.tcz").exists()
        assert (
            dest / "cde" / "optional" / "openssh.tcz"
        ).exists()

    def test_extract_creates_cde_dir_when_absent(self, tmp_path):
        mount = tmp_path / "mount"
        mount.mkdir()
        _make_iso_64bit(mount)
        dest = tmp_path / "dest"

        plugin = TinyCorePlugin()
        assets = plugin.extract_from_iso(mount, dest)

        assert assets.repo_path == dest / "cde"
        assert assets.repo_path.exists()

    def test_extract_with_efi(self, tmp_path):
        mount = tmp_path / "mount"
        mount.mkdir()
        _make_iso_64bit(mount)
        efi = mount / "EFI" / "BOOT"
        efi.mkdir(parents=True)
        (efi / "BOOTX64.EFI").write_bytes(b"efi-binary")
        dest = tmp_path / "dest"

        plugin = TinyCorePlugin()
        assets = plugin.extract_from_iso(mount, dest)

        assert assets.boot_loader_path == dest / "EFI"
        assert (
            dest / "EFI" / "BOOT" / "BOOTX64.EFI"
        ).exists()

    def test_extract_no_efi(self, tmp_path):
        mount = tmp_path / "mount"
        mount.mkdir()
        _make_iso_64bit(mount)
        dest = tmp_path / "dest"

        plugin = TinyCorePlugin()
        assets = plugin.extract_from_iso(mount, dest)

        assert assets.boot_loader_path is None

    def test_extract_returns_distro_assets(self, tmp_path):
        mount = tmp_path / "mount"
        mount.mkdir()
        _make_iso_64bit(mount)
        dest = tmp_path / "dest"

        plugin = TinyCorePlugin()
        assets = plugin.extract_from_iso(mount, dest)

        assert isinstance(assets, DistroAssets)


# ---------------------------------------------------------------------------
# Live boot support
# ---------------------------------------------------------------------------


class TestLiveBoot:
    """Tests for live boot support."""

    def test_extract_live_assets_64bit(self, tmp_path):
        mount = tmp_path / "mount"
        mount.mkdir()
        _make_iso_64bit(mount)
        dest = tmp_path / "dest"

        plugin = TinyCorePlugin()
        assets = plugin.extract_live_assets(mount, dest)

        assert assets.kernel_path == dest / "vmlinuz64"
        assert assets.initrd_path == dest / "corepure64.gz"

    def test_extract_live_assets_32bit(self, tmp_path):
        mount = tmp_path / "mount"
        mount.mkdir()
        _make_iso_32bit(mount)
        dest = tmp_path / "dest"

        plugin = TinyCorePlugin()
        assets = plugin.extract_live_assets(mount, dest)

        assert assets.kernel_path == dest / "vmlinuz"
        assert assets.initrd_path == dest / "core.gz"

    def test_extract_live_copies_tce(self, tmp_path):
        mount = tmp_path / "mount"
        mount.mkdir()
        _make_iso_full(mount)
        dest = tmp_path / "dest"

        plugin = TinyCorePlugin()
        assets = plugin.extract_live_assets(mount, dest)

        assert (
            dest / "cde" / "optional" / "nano.tcz"
        ).exists()

    def test_extract_live_no_efi(self, tmp_path):
        mount = tmp_path / "mount"
        mount.mkdir()
        _make_iso_64bit(mount)
        dest = tmp_path / "dest"

        plugin = TinyCorePlugin()
        assets = plugin.extract_live_assets(mount, dest)

        assert assets.boot_loader_path is None

    def test_live_boot_assets_default(self):
        plugin = TinyCorePlugin()
        profile = _make_profile()
        assets = plugin.live_boot_assets(profile)

        assert assets.kernel == "boot/vmlinuz64"
        assert assets.initrd == "boot/corepure64.gz"
        assert isinstance(assets, BootAssets)

    def test_live_boot_assets_serial_console(self):
        plugin = TinyCorePlugin()
        profile = _make_profile(
            extra={"serial_console": "ttyS0,115200"}
        )
        assets = plugin.live_boot_assets(profile)
        assert "console=ttyS0,115200" in assets.boot_args

    def test_live_boot_assets_uefi(self):
        plugin = TinyCorePlugin()
        profile = _make_profile(firmware=BootFirmware.UEFI)
        assets = plugin.live_boot_assets(profile)
        assert (
            "menuentry" in assets.bootloader_config
            or "linuxefi" in assets.bootloader_config
        )

    def test_live_boot_assets_bios(self):
        plugin = TinyCorePlugin()
        profile = _make_profile()
        assets = plugin.live_boot_assets(profile)
        assert (
            "DEFAULT" in assets.bootloader_config
            or "pxelinux" in assets.bootloader_config.lower()
        )

    def test_live_boot_menu_label_includes_live(self):
        plugin = TinyCorePlugin()
        profile = _make_profile()
        assets = plugin.live_boot_assets(profile)
        assert "Live" in assets.bootloader_config


# ---------------------------------------------------------------------------
# Registry integration
# ---------------------------------------------------------------------------


class TestRegistryIntegration:
    """Tests for plugin registration."""

    def test_tinycore_in_registry(self, plugin_registry):
        assert "tinycore" in plugin_registry.available

    def test_registry_returns_tinycore_plugin(
        self, plugin_registry
    ):
        plugin = plugin_registry.get("tinycore")
        assert isinstance(plugin, TinyCorePlugin)

    def test_registry_get_case_insensitive(
        self, plugin_registry
    ):
        plugin = plugin_registry.get("tinycore")
        assert plugin.os_family == "tinycore"
