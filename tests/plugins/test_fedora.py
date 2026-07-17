"""Tests for the Fedora/RHEL Kickstart plugin."""

from __future__ import annotations

import pytest

from pxeos.models import BootFirmware, ProvisionProfile
from pxeos.plugins.fedora import FedoraPlugin


@pytest.fixture
def plugin() -> FedoraPlugin:
    return FedoraPlugin()


@pytest.fixture
def valid_profile() -> ProvisionProfile:
    return ProvisionProfile(
        name="fedora-server",
        os_family="fedora",
        os_version="40",
        install_url="http://mirror.example.com/fedora/40/x86_64",
        autoinstall_url="http://pxe.example.com/ks/fedora-server",
        packages=["vim", "tmux"],
        post_scripts=["systemctl enable sshd"],
    )


class TestOsFamily:
    def test_returns_fedora(self, plugin: FedoraPlugin) -> None:
        assert plugin.os_family == "fedora"


class TestSupportedVersions:
    def test_includes_fedora_versions(self, plugin: FedoraPlugin) -> None:
        versions = plugin.supported_versions
        for v in ("38", "39", "40", "41", "42"):
            assert v in versions

    def test_includes_rhel_versions(self, plugin: FedoraPlugin) -> None:
        versions = plugin.supported_versions
        for v in ("8", "9"):
            assert v in versions


class TestAutoinstallFilename:
    def test_returns_ks_cfg(self, plugin: FedoraPlugin) -> None:
        assert plugin.autoinstall_filename() == "ks.cfg"


class TestGenerateAutoinstall:
    def test_contains_version_header(
        self, plugin: FedoraPlugin, valid_profile: ProvisionProfile
    ) -> None:
        output = plugin.generate_autoinstall(valid_profile)
        assert "#version=RHEL" in output

    def test_contains_install_url(
        self, plugin: FedoraPlugin, valid_profile: ProvisionProfile
    ) -> None:
        output = plugin.generate_autoinstall(valid_profile)
        assert (
            'url --url="http://mirror.example.com/fedora/40/x86_64"'
            in output
        )

    def test_contains_language(
        self, plugin: FedoraPlugin, valid_profile: ProvisionProfile
    ) -> None:
        output = plugin.generate_autoinstall(valid_profile)
        assert "lang en_US.UTF-8" in output

    def test_contains_packages_section(
        self, plugin: FedoraPlugin, valid_profile: ProvisionProfile
    ) -> None:
        output = plugin.generate_autoinstall(valid_profile)
        assert "%packages" in output
        assert "vim" in output
        assert "tmux" in output

    def test_contains_post_section(
        self, plugin: FedoraPlugin, valid_profile: ProvisionProfile
    ) -> None:
        output = plugin.generate_autoinstall(valid_profile)
        assert "%post" in output
        assert "systemctl enable sshd" in output

    def test_contains_profile_name_comment(
        self, plugin: FedoraPlugin, valid_profile: ProvisionProfile
    ) -> None:
        output = plugin.generate_autoinstall(valid_profile)
        assert "fedora-server" in output

    def test_contains_selinux_enforcing_by_default(
        self, plugin: FedoraPlugin, valid_profile: ProvisionProfile
    ) -> None:
        output = plugin.generate_autoinstall(valid_profile)
        assert "selinux --enforcing" in output

    def test_contains_firewall_enabled_by_default(
        self, plugin: FedoraPlugin, valid_profile: ProvisionProfile
    ) -> None:
        output = plugin.generate_autoinstall(valid_profile)
        assert "firewall --enabled --ssh" in output

    def test_contains_reboot_directive(
        self, plugin: FedoraPlugin, valid_profile: ProvisionProfile
    ) -> None:
        output = plugin.generate_autoinstall(valid_profile)
        assert "reboot --eject" in output


class TestValidateProfile:
    def test_valid_profile_has_no_errors(
        self, plugin: FedoraPlugin, valid_profile: ProvisionProfile
    ) -> None:
        errors = plugin.validate_profile(valid_profile)
        assert errors == []

    def test_missing_install_url(
        self, plugin: FedoraPlugin
    ) -> None:
        profile = ProvisionProfile(
            name="fedora-server",
            os_family="fedora",
            os_version="40",
            install_url="",
            autoinstall_url="http://pxe.example.com/ks/fedora-server",
        )
        errors = plugin.validate_profile(profile)
        assert any("install_url" in e for e in errors)

    def test_missing_autoinstall_url(
        self, plugin: FedoraPlugin
    ) -> None:
        profile = ProvisionProfile(
            name="fedora-server",
            os_family="fedora",
            os_version="40",
            install_url="http://mirror.example.com/fedora/40/x86_64",
            autoinstall_url="",
        )
        errors = plugin.validate_profile(profile)
        assert any("autoinstall_url" in e for e in errors)

    def test_unsupported_arch(
        self, plugin: FedoraPlugin
    ) -> None:
        profile = ProvisionProfile(
            name="fedora-server",
            os_family="fedora",
            os_version="40",
            arch="mips",
            install_url="http://mirror.example.com/fedora/40/x86_64",
            autoinstall_url="http://pxe.example.com/ks/fedora-server",
        )
        errors = plugin.validate_profile(profile)
        assert any("unsupported arch" in e for e in errors)

    def test_valid_arches_accepted(
        self, plugin: FedoraPlugin
    ) -> None:
        for arch in ("x86_64", "aarch64", "ppc64le"):
            profile = ProvisionProfile(
                name="fedora-server",
                os_family="fedora",
                os_version="40",
                arch=arch,
                install_url="http://mirror.example.com/fedora/40/x86_64",
                autoinstall_url="http://pxe.example.com/ks/fedora-server",
            )
            errors = plugin.validate_profile(profile)
            assert errors == [], f"arch {arch!r} should be valid"

    def test_os_family_mismatch(
        self, plugin: FedoraPlugin
    ) -> None:
        profile = ProvisionProfile(
            name="wrong-os",
            os_family="debian",
            os_version="40",
            install_url="http://mirror.example.com/fedora/40/x86_64",
            autoinstall_url="http://pxe.example.com/ks/fedora-server",
        )
        errors = plugin.validate_profile(profile)
        assert any("os_family mismatch" in e for e in errors)

    def test_unsupported_version(
        self, plugin: FedoraPlugin
    ) -> None:
        profile = ProvisionProfile(
            name="fedora-server",
            os_family="fedora",
            os_version="99",
            install_url="http://mirror.example.com/fedora/40/x86_64",
            autoinstall_url="http://pxe.example.com/ks/fedora-server",
        )
        errors = plugin.validate_profile(profile)
        assert any("unsupported version" in e for e in errors)


class TestBootAssets:
    def test_kernel_path(
        self, plugin: FedoraPlugin, valid_profile: ProvisionProfile
    ) -> None:
        assets = plugin.boot_assets(valid_profile)
        assert assets.kernel == "images/pxeboot/vmlinuz"

    def test_initrd_path(
        self, plugin: FedoraPlugin, valid_profile: ProvisionProfile
    ) -> None:
        assets = plugin.boot_assets(valid_profile)
        assert assets.initrd == "images/pxeboot/initrd.img"

    def test_boot_args_contain_inst_ks(
        self, plugin: FedoraPlugin, valid_profile: ProvisionProfile
    ) -> None:
        assets = plugin.boot_assets(valid_profile)
        assert any(
            arg.startswith("inst.ks=") for arg in assets.boot_args
        )

    def test_boot_args_contain_inst_repo(
        self, plugin: FedoraPlugin, valid_profile: ProvisionProfile
    ) -> None:
        assets = plugin.boot_assets(valid_profile)
        assert any(
            arg.startswith("inst.repo=") for arg in assets.boot_args
        )

    def test_boot_args_contain_ip_dhcp(
        self, plugin: FedoraPlugin, valid_profile: ProvisionProfile
    ) -> None:
        assets = plugin.boot_assets(valid_profile)
        assert "ip=dhcp" in assets.boot_args

    def test_boot_args_have_correct_ks_url(
        self, plugin: FedoraPlugin, valid_profile: ProvisionProfile
    ) -> None:
        assets = plugin.boot_assets(valid_profile)
        expected = f"inst.ks={valid_profile.autoinstall_url}"
        assert expected in assets.boot_args

    def test_boot_args_have_correct_repo_url(
        self, plugin: FedoraPlugin, valid_profile: ProvisionProfile
    ) -> None:
        assets = plugin.boot_assets(valid_profile)
        expected = f"inst.repo={valid_profile.install_url}"
        assert expected in assets.boot_args


class TestBootloaderConfig:
    def test_bios_contains_pxelinux_markers(
        self, plugin: FedoraPlugin
    ) -> None:
        profile = ProvisionProfile(
            name="fedora-server",
            os_family="fedora",
            os_version="40",
            firmware=BootFirmware.BIOS,
            install_url="http://mirror.example.com/fedora/40/x86_64",
            autoinstall_url="http://pxe.example.com/ks/fedora-server",
        )
        assets = plugin.boot_assets(profile)
        config = assets.bootloader_config
        assert "PXELINUX" in config
        assert "KERNEL" in config
        assert "images/pxeboot/vmlinuz" in config

    def test_uefi_contains_grub_markers(
        self, plugin: FedoraPlugin
    ) -> None:
        profile = ProvisionProfile(
            name="fedora-server",
            os_family="fedora",
            os_version="40",
            firmware=BootFirmware.UEFI,
            install_url="http://mirror.example.com/fedora/40/x86_64",
            autoinstall_url="http://pxe.example.com/ks/fedora-server",
        )
        assets = plugin.boot_assets(profile)
        config = assets.bootloader_config
        assert "linuxefi" in config
        assert "initrdefi" in config
        assert "menuentry" in config

    def test_bios_config_contains_menu_label(
        self, plugin: FedoraPlugin
    ) -> None:
        profile = ProvisionProfile(
            name="fedora-server",
            os_family="fedora",
            os_version="40",
            firmware=BootFirmware.BIOS,
            install_url="http://mirror.example.com/fedora/40/x86_64",
            autoinstall_url="http://pxe.example.com/ks/fedora-server",
        )
        assets = plugin.boot_assets(profile)
        assert "fedora-server" in assets.bootloader_config

    def test_uefi_config_contains_boot_args(
        self, plugin: FedoraPlugin
    ) -> None:
        profile = ProvisionProfile(
            name="fedora-server",
            os_family="fedora",
            os_version="40",
            firmware=BootFirmware.UEFI,
            install_url="http://mirror.example.com/fedora/40/x86_64",
            autoinstall_url="http://pxe.example.com/ks/fedora-server",
        )
        assets = plugin.boot_assets(profile)
        config = assets.bootloader_config
        assert "inst.ks=" in config
        assert "inst.repo=" in config
