"""Tests for the Windows unattend.xml plugin."""

from __future__ import annotations

import pytest

from pxeos.models import BootFirmware, ProvisionProfile
from pxeos.plugins.windows import WindowsPlugin


@pytest.fixture
def plugin() -> WindowsPlugin:
    return WindowsPlugin()


@pytest.fixture
def bios_profile() -> ProvisionProfile:
    return ProvisionProfile(
        name="win-bios",
        os_family="windows",
        os_version="11",
        firmware=BootFirmware.BIOS,
        install_url="http://pxe.example.com/win/11",
        autoinstall_url="http://pxe.example.com/unattend/win11",
    )


@pytest.fixture
def uefi_profile() -> ProvisionProfile:
    return ProvisionProfile(
        name="win-uefi",
        os_family="windows",
        os_version="2022",
        firmware=BootFirmware.UEFI,
        install_url="http://pxe.example.com/win/2022",
        autoinstall_url="http://pxe.example.com/unattend/win2022",
    )


class TestOsFamily:
    def test_returns_windows(self, plugin: WindowsPlugin) -> None:
        assert plugin.os_family == "windows"

    def test_supported_versions(self, plugin: WindowsPlugin) -> None:
        versions = plugin.supported_versions
        assert "10" in versions
        assert "11" in versions
        assert "2019" in versions
        assert "2022" in versions
        assert "2025" in versions

    def test_autoinstall_filename(self, plugin: WindowsPlugin) -> None:
        assert plugin.autoinstall_filename() == "unattend.xml"


class TestGenerateAutoinstall:
    def test_produces_xml(
        self, plugin: WindowsPlugin, bios_profile: ProvisionProfile
    ) -> None:
        output = plugin.generate_autoinstall(bios_profile)
        assert '<?xml version="1.0"' in output

    def test_has_microsoft_namespace(
        self, plugin: WindowsPlugin, bios_profile: ProvisionProfile
    ) -> None:
        output = plugin.generate_autoinstall(bios_profile)
        assert "urn:schemas-microsoft-com:unattend" in output

    def test_has_wcm_namespace(
        self, plugin: WindowsPlugin, bios_profile: ProvisionProfile
    ) -> None:
        output = plugin.generate_autoinstall(bios_profile)
        assert "http://schemas.microsoft.com/WMIConfig/2002/State" in output

    def test_contains_windows_pe_pass(
        self, plugin: WindowsPlugin, bios_profile: ProvisionProfile
    ) -> None:
        output = plugin.generate_autoinstall(bios_profile)
        assert 'pass="windowsPE"' in output

    def test_contains_specialize_pass(
        self, plugin: WindowsPlugin, bios_profile: ProvisionProfile
    ) -> None:
        output = plugin.generate_autoinstall(bios_profile)
        assert 'pass="specialize"' in output

    def test_contains_oobe_pass(
        self, plugin: WindowsPlugin, bios_profile: ProvisionProfile
    ) -> None:
        output = plugin.generate_autoinstall(bios_profile)
        assert 'pass="oobeSystem"' in output

    def test_contains_hostname(
        self, plugin: WindowsPlugin, bios_profile: ProvisionProfile
    ) -> None:
        output = plugin.generate_autoinstall(bios_profile)
        assert "<ComputerName>win-bios</ComputerName>" in output

    def test_contains_accept_eula(
        self, plugin: WindowsPlugin, bios_profile: ProvisionProfile
    ) -> None:
        output = plugin.generate_autoinstall(bios_profile)
        assert "<AcceptEula>true</AcceptEula>" in output


class TestBiosVsUefiPartitioning:
    def test_bios_has_mbr_layout(
        self, plugin: WindowsPlugin, bios_profile: ProvisionProfile
    ) -> None:
        output = plugin.generate_autoinstall(bios_profile)
        assert "MBR layout for BIOS" in output
        assert "<Active>true</Active>" in output

    def test_bios_has_two_create_partitions(
        self, plugin: WindowsPlugin, bios_profile: ProvisionProfile
    ) -> None:
        output = plugin.generate_autoinstall(bios_profile)
        # BIOS MBR has 2 partitions: System Reserved + Windows OS
        assert output.count("<CreatePartition") >= 2

    def test_uefi_has_gpt_layout(
        self, plugin: WindowsPlugin, uefi_profile: ProvisionProfile
    ) -> None:
        output = plugin.generate_autoinstall(uefi_profile)
        assert "GPT layout for UEFI" in output

    def test_uefi_has_efi_partition(
        self, plugin: WindowsPlugin, uefi_profile: ProvisionProfile
    ) -> None:
        output = plugin.generate_autoinstall(uefi_profile)
        assert "<Type>EFI</Type>" in output
        assert "<Type>MSR</Type>" in output

    def test_uefi_has_three_create_partitions(
        self, plugin: WindowsPlugin, uefi_profile: ProvisionProfile
    ) -> None:
        output = plugin.generate_autoinstall(uefi_profile)
        # UEFI GPT has 3 partitions: EFI + MSR + Windows OS
        assert output.count("<CreatePartition") >= 3

    def test_uefi_install_to_partition_3(
        self, plugin: WindowsPlugin, uefi_profile: ProvisionProfile
    ) -> None:
        output = plugin.generate_autoinstall(uefi_profile)
        # UEFI installs to partition 3
        assert "<PartitionID>3</PartitionID>" in output

    def test_bios_install_to_partition_2(
        self, plugin: WindowsPlugin, bios_profile: ProvisionProfile
    ) -> None:
        output = plugin.generate_autoinstall(bios_profile)
        # BIOS installs to partition 2
        assert "<PartitionID>2</PartitionID>" in output


class TestImageName:
    def test_server_version_gets_serverstandardcore(
        self, plugin: WindowsPlugin, uefi_profile: ProvisionProfile
    ) -> None:
        output = plugin.generate_autoinstall(uefi_profile)
        assert "SERVERSTANDARDCORE" in output

    def test_desktop_version_gets_pro(
        self, plugin: WindowsPlugin, bios_profile: ProvisionProfile
    ) -> None:
        output = plugin.generate_autoinstall(bios_profile)
        assert "Windows 11 Pro" in output

    def test_custom_image_name_overrides(self, plugin: WindowsPlugin) -> None:
        profile = ProvisionProfile(
            name="win-custom",
            os_family="windows",
            os_version="2022",
            firmware=BootFirmware.UEFI,
            install_url="http://example.com/win",
            autoinstall_url="http://example.com/unattend",
            extra={"image_name": "Windows Server 2022 Datacenter"},
        )
        output = plugin.generate_autoinstall(profile)
        assert "Windows Server 2022 Datacenter" in output


class TestBootAssets:
    def test_bios_kernel_path(
        self, plugin: WindowsPlugin, bios_profile: ProvisionProfile
    ) -> None:
        assets = plugin.boot_assets(bios_profile)
        assert assets.kernel.endswith("/boot/pxeboot.n12")

    def test_uefi_kernel_path(
        self, plugin: WindowsPlugin, uefi_profile: ProvisionProfile
    ) -> None:
        assets = plugin.boot_assets(uefi_profile)
        assert assets.kernel.endswith("/boot/bootmgfw.efi")

    def test_both_have_boot_wim_initrd(
        self, plugin: WindowsPlugin, bios_profile: ProvisionProfile, uefi_profile: ProvisionProfile
    ) -> None:
        bios_assets = plugin.boot_assets(bios_profile)
        uefi_assets = plugin.boot_assets(uefi_profile)
        assert bios_assets.initrd is not None
        assert "boot.wim" in bios_assets.initrd
        assert uefi_assets.initrd is not None
        assert "boot.wim" in uefi_assets.initrd

    def test_bootloader_config_mentions_windows(
        self, plugin: WindowsPlugin, bios_profile: ProvisionProfile
    ) -> None:
        assets = plugin.boot_assets(bios_profile)
        assert "Windows" in assets.bootloader_config

    def test_bios_config_mentions_pxeboot(
        self, plugin: WindowsPlugin, bios_profile: ProvisionProfile
    ) -> None:
        assets = plugin.boot_assets(bios_profile)
        assert "pxeboot.n12" in assets.bootloader_config

    def test_uefi_config_mentions_bootmgfw(
        self, plugin: WindowsPlugin, uefi_profile: ProvisionProfile
    ) -> None:
        assets = plugin.boot_assets(uefi_profile)
        assert "bootmgfw.efi" in assets.bootloader_config or "UEFI" in assets.bootloader_config


class TestValidateProfile:
    def test_valid_bios_profile(
        self, plugin: WindowsPlugin, bios_profile: ProvisionProfile
    ) -> None:
        errors = plugin.validate_profile(bios_profile)
        assert errors == []

    def test_valid_uefi_profile(
        self, plugin: WindowsPlugin, uefi_profile: ProvisionProfile
    ) -> None:
        errors = plugin.validate_profile(uefi_profile)
        assert errors == []

    def test_missing_install_url(self, plugin: WindowsPlugin) -> None:
        profile = ProvisionProfile(
            name="win-test",
            os_family="windows",
            os_version="11",
            install_url="",
        )
        errors = plugin.validate_profile(profile)
        assert any("install_url" in e for e in errors)

    def test_unsupported_arch(self, plugin: WindowsPlugin) -> None:
        profile = ProvisionProfile(
            name="win-test",
            os_family="windows",
            os_version="11",
            arch="aarch64",
            install_url="http://example.com/win",
        )
        errors = plugin.validate_profile(profile)
        assert any("unsupported architecture" in e for e in errors)

    def test_invalid_product_key_format(self, plugin: WindowsPlugin) -> None:
        profile = ProvisionProfile(
            name="win-test",
            os_family="windows",
            os_version="11",
            install_url="http://example.com/win",
            extra={"product_key": "INVALID-KEY"},
        )
        errors = plugin.validate_profile(profile)
        assert any("product_key" in e for e in errors)

    def test_valid_product_key_accepted(self, plugin: WindowsPlugin) -> None:
        profile = ProvisionProfile(
            name="win-test",
            os_family="windows",
            os_version="11",
            install_url="http://example.com/win",
            extra={"product_key": "AAAAA-BBBBB-CCCCC-DDDDD-EEEEE"},
        )
        errors = plugin.validate_profile(profile)
        assert not any("product_key" in e for e in errors)
