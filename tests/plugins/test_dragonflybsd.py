"""Tests for the DragonFlyBSD bsdinstall plugin."""

from __future__ import annotations

import pytest

from pxeos.models import BootFirmware, BootMethod, ProvisionProfile
from pxeos.plugins.dragonflybsd import DragonFlyBSDPlugin


@pytest.fixture
def plugin() -> DragonFlyBSDPlugin:
    return DragonFlyBSDPlugin()


@pytest.fixture
def valid_profile() -> ProvisionProfile:
    return ProvisionProfile(
        name="dragonfly-server",
        os_family="dragonflybsd",
        os_version="6.4",
        arch="x86_64",
        install_url="http://mirror.example.com/dragonflybsd/6.4",
        disk={"filesystem": "hammer2", "device": "da0"},
        packages=["vim", "bash"],
    )


class TestOsFamily:
    def test_returns_dragonflybsd(self, plugin: DragonFlyBSDPlugin) -> None:
        assert plugin.os_family == "dragonflybsd"

    def test_supported_versions(self, plugin: DragonFlyBSDPlugin) -> None:
        versions = plugin.supported_versions
        assert "6.4" in versions
        assert "6.2" in versions
        assert "6.0" in versions

    def test_autoinstall_filename(self, plugin: DragonFlyBSDPlugin) -> None:
        assert plugin.autoinstall_filename() == "installerconfig"


class TestGenerateAutoinstall:
    def test_starts_with_shebang(
        self, plugin: DragonFlyBSDPlugin, valid_profile: ProvisionProfile
    ) -> None:
        output = plugin.generate_autoinstall(valid_profile)
        assert output.startswith("#!/bin/sh")

    def test_contains_distributions(
        self, plugin: DragonFlyBSDPlugin, valid_profile: ProvisionProfile
    ) -> None:
        output = plugin.generate_autoinstall(valid_profile)
        assert "DISTRIBUTIONS=" in output

    def test_contains_hostname(
        self, plugin: DragonFlyBSDPlugin, valid_profile: ProvisionProfile
    ) -> None:
        output = plugin.generate_autoinstall(valid_profile)
        assert "dragonfly-server" in output

    def test_hammer2_config_present(
        self, plugin: DragonFlyBSDPlugin, valid_profile: ProvisionProfile
    ) -> None:
        output = plugin.generate_autoinstall(valid_profile)
        assert "hammer2" in output
        assert "da0" in output

    def test_ufs_config_when_specified(self, plugin: DragonFlyBSDPlugin) -> None:
        profile = ProvisionProfile(
            name="dragonfly-ufs",
            os_family="dragonflybsd",
            os_version="6.4",
            arch="x86_64",
            install_url="http://mirror.example.com/dragonflybsd/6.4",
            disk={"filesystem": "ufs", "device": "da0"},
        )
        output = plugin.generate_autoinstall(profile)
        assert "ufs" in output

    def test_contains_packages(
        self, plugin: DragonFlyBSDPlugin, valid_profile: ProvisionProfile
    ) -> None:
        output = plugin.generate_autoinstall(valid_profile)
        assert "pkg install -y" in output
        assert "vim" in output
        assert "bash" in output

    def test_contains_timezone_setup(
        self, plugin: DragonFlyBSDPlugin, valid_profile: ProvisionProfile
    ) -> None:
        output = plugin.generate_autoinstall(valid_profile)
        assert "zoneinfo" in output

    def test_contains_services(
        self, plugin: DragonFlyBSDPlugin, valid_profile: ProvisionProfile
    ) -> None:
        output = plugin.generate_autoinstall(valid_profile)
        assert "sshd" in output

    def test_install_url_in_output(
        self, plugin: DragonFlyBSDPlugin, valid_profile: ProvisionProfile
    ) -> None:
        output = plugin.generate_autoinstall(valid_profile)
        assert "BSDINSTALL_DISTSITE" in output
        assert "mirror.example.com" in output

    def test_noninteractive_set(
        self, plugin: DragonFlyBSDPlugin, valid_profile: ProvisionProfile
    ) -> None:
        output = plugin.generate_autoinstall(valid_profile)
        assert 'nonInteractive="YES"' in output

    def test_post_scripts_rendered(self, plugin: DragonFlyBSDPlugin) -> None:
        profile = ProvisionProfile(
            name="dragonfly-post",
            os_family="dragonflybsd",
            os_version="6.4",
            arch="x86_64",
            install_url="http://mirror.example.com/dragonflybsd/6.4",
            post_scripts=["echo hello", "touch /tmp/done"],
        )
        output = plugin.generate_autoinstall(profile)
        assert "echo hello" in output
        assert "touch /tmp/done" in output


class TestBootAssets:
    def test_bios_fallback_kernel_path(
        self, plugin: DragonFlyBSDPlugin, valid_profile: ProvisionProfile
    ) -> None:
        assets = plugin.boot_assets(valid_profile)
        assert assets.kernel == "boot/pxeboot"
        assert assets.boot_method == BootMethod.KERNEL

    def test_uefi_fallback_kernel_path(
        self, plugin: DragonFlyBSDPlugin
    ) -> None:
        profile = ProvisionProfile(
            name="dragonfly-uefi",
            os_family="dragonflybsd",
            os_version="6.4",
            arch="x86_64",
            firmware=BootFirmware.UEFI,
            install_url="http://mirror.example.com/dragonflybsd/6.4",
        )
        assets = plugin.boot_assets(profile)
        assert assets.kernel == "boot/loader.efi"

    def test_memdisk_with_iso(self, plugin: DragonFlyBSDPlugin) -> None:
        profile = ProvisionProfile(
            name="dragonfly-server",
            os_family="dragonflybsd",
            os_version="6.4",
            arch="x86_64",
            install_url="http://mirror.example.com/dragonflybsd/6.4",
            extra={"boot_iso": "dfly-x86_64-6.4.2_REL.iso"},
        )
        assets = plugin.boot_assets(profile)
        assert assets.boot_method == BootMethod.MEMDISK
        assert assets.kernel == "memdisk"
        assert assets.initrd == "dfly-x86_64-6.4.2_REL.iso"

    def test_no_initrd_in_fallback(
        self, plugin: DragonFlyBSDPlugin, valid_profile: ProvisionProfile
    ) -> None:
        assets = plugin.boot_assets(valid_profile)
        assert assets.initrd is None


class TestValidateProfile:
    def test_valid_profile_no_errors(
        self, plugin: DragonFlyBSDPlugin, valid_profile: ProvisionProfile
    ) -> None:
        errors = plugin.validate_profile(valid_profile)
        assert errors == []

    def test_missing_install_url(self, plugin: DragonFlyBSDPlugin) -> None:
        profile = ProvisionProfile(
            name="dragonfly-server",
            os_family="dragonflybsd",
            os_version="6.4",
            arch="x86_64",
            install_url="",
        )
        errors = plugin.validate_profile(profile)
        assert any("install_url" in e for e in errors)

    def test_unsupported_filesystem(self, plugin: DragonFlyBSDPlugin) -> None:
        profile = ProvisionProfile(
            name="dragonfly-server",
            os_family="dragonflybsd",
            os_version="6.4",
            arch="x86_64",
            install_url="http://example.com/dragonflybsd",
            disk={"filesystem": "ntfs"},
        )
        errors = plugin.validate_profile(profile)
        assert any("unsupported filesystem" in e for e in errors)

    def test_unsupported_arch(self, plugin: DragonFlyBSDPlugin) -> None:
        profile = ProvisionProfile(
            name="dragonfly-server",
            os_family="dragonflybsd",
            os_version="6.4",
            arch="mips",
            install_url="http://example.com/dragonflybsd",
        )
        errors = plugin.validate_profile(profile)
        assert any("unsupported architecture" in e for e in errors)

    def test_valid_filesystems_accepted(self, plugin: DragonFlyBSDPlugin) -> None:
        for fs in ("hammer2", "ufs"):
            profile = ProvisionProfile(
                name="dragonfly-server",
                os_family="dragonflybsd",
                os_version="6.4",
                arch="x86_64",
                install_url="http://example.com/dragonflybsd",
                disk={"filesystem": fs},
            )
            errors = plugin.validate_profile(profile)
            assert not any(
                "filesystem" in e for e in errors
            ), f"{fs} should be valid"

    def test_os_family_mismatch(self, plugin: DragonFlyBSDPlugin) -> None:
        profile = ProvisionProfile(
            name="dragonfly-server",
            os_family="freebsd",
            os_version="6.4",
            arch="x86_64",
            install_url="http://example.com/dragonflybsd",
        )
        errors = plugin.validate_profile(profile)
        assert any("os_family mismatch" in e for e in errors)

    def test_unsupported_version(self, plugin: DragonFlyBSDPlugin) -> None:
        profile = ProvisionProfile(
            name="dragonfly-server",
            os_family="dragonflybsd",
            os_version="5.0",
            arch="x86_64",
            install_url="http://example.com/dragonflybsd",
        )
        errors = plugin.validate_profile(profile)
        assert any("unsupported version" in e for e in errors)

    def test_missing_name(self, plugin: DragonFlyBSDPlugin) -> None:
        profile = ProvisionProfile(
            name="",
            os_family="dragonflybsd",
            os_version="6.4",
            arch="x86_64",
            install_url="http://example.com/dragonflybsd",
        )
        errors = plugin.validate_profile(profile)
        assert any("profile name" in e for e in errors)

    def test_amd64_arch_accepted(self, plugin: DragonFlyBSDPlugin) -> None:
        profile = ProvisionProfile(
            name="dragonfly-server",
            os_family="dragonflybsd",
            os_version="6.4",
            arch="amd64",
            install_url="http://example.com/dragonflybsd",
        )
        errors = plugin.validate_profile(profile)
        assert not any("architecture" in e for e in errors)


class TestExtractFromIso:
    def test_copies_kernel(self, plugin: DragonFlyBSDPlugin, tmp_path) -> None:
        mount = tmp_path / "mount"
        dest = tmp_path / "dest"
        kernel_dir = mount / "boot" / "kernel"
        kernel_dir.mkdir(parents=True)
        (kernel_dir / "kernel").write_bytes(b"KERNEL")

        assets = plugin.extract_from_iso(mount, dest)
        assert assets.kernel_path == dest / "boot" / "kernel"
        assert assets.kernel_path.exists()

    def test_copies_mfsroot(self, plugin: DragonFlyBSDPlugin, tmp_path) -> None:
        mount = tmp_path / "mount"
        dest = tmp_path / "dest"
        boot_dir = mount / "boot"
        boot_dir.mkdir(parents=True)
        (boot_dir / "mfsroot.gz").write_bytes(b"MFSROOT")

        assets = plugin.extract_from_iso(mount, dest)
        assert assets.initrd_path == dest / "boot" / "mfsroot.gz"
        assert assets.initrd_path.exists()

    def test_copies_pxeboot(self, plugin: DragonFlyBSDPlugin, tmp_path) -> None:
        mount = tmp_path / "mount"
        dest = tmp_path / "dest"
        boot_dir = mount / "boot"
        boot_dir.mkdir(parents=True)
        (boot_dir / "pxeboot").write_bytes(b"PXEBOOT")

        plugin.extract_from_iso(mount, dest)
        assert (dest / "boot" / "pxeboot").exists()

    def test_copies_loader_efi(self, plugin: DragonFlyBSDPlugin, tmp_path) -> None:
        mount = tmp_path / "mount"
        dest = tmp_path / "dest"
        boot_dir = mount / "boot"
        boot_dir.mkdir(parents=True)
        (boot_dir / "loader.efi").write_bytes(b"LOADEREFI")

        assets = plugin.extract_from_iso(mount, dest)
        assert assets.boot_loader_path == dest / "boot" / "loader.efi"
        assert assets.boot_loader_path.exists()

    def test_copies_dist_sets(self, plugin: DragonFlyBSDPlugin, tmp_path) -> None:
        mount = tmp_path / "mount"
        dest = tmp_path / "dest"
        (mount / "boot").mkdir(parents=True)
        release_dir = mount / "usr" / "release"
        release_dir.mkdir(parents=True)
        (release_dir / "base.txz").write_bytes(b"BASE")

        assets = plugin.extract_from_iso(mount, dest)
        assert assets.repo_path == dest / "repo"
        assert (dest / "repo" / "base.txz").exists()

    def test_missing_files_handled_gracefully(
        self, plugin: DragonFlyBSDPlugin, tmp_path
    ) -> None:
        mount = tmp_path / "mount"
        dest = tmp_path / "dest"
        mount.mkdir(parents=True)

        assets = plugin.extract_from_iso(mount, dest)
        assert assets.kernel_path == dest / "boot" / "kernel"
        assert assets.initrd_path is None
        assert assets.boot_loader_path is None

    def test_no_loader_efi_returns_none(
        self, plugin: DragonFlyBSDPlugin, tmp_path
    ) -> None:
        mount = tmp_path / "mount"
        dest = tmp_path / "dest"
        kernel_dir = mount / "boot" / "kernel"
        kernel_dir.mkdir(parents=True)
        (kernel_dir / "kernel").write_bytes(b"KERNEL")

        assets = plugin.extract_from_iso(mount, dest)
        assert assets.boot_loader_path is None
