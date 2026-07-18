"""Comprehensive validation tests for the Windows unattend.xml plugin.

Covers: edition variants, product key handling, driver injection,
WinPE customization, network config, domain join, locale/timezone,
partition layouts, auto-logon, post-install scripts, architecture
validation, and ISO extraction edge cases.

References GitHub issue #22.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from pxeos.models import BootFirmware, ProvisionProfile
from pxeos.plugins.windows import WindowsPlugin, _SERVER_VERSIONS, _VERSION_NAMES


# ── helpers ──────────────────────────────────────────────────────────

def _make_profile(**overrides) -> ProvisionProfile:
    """Build a Windows profile with sensible defaults, applying *overrides*."""
    defaults = dict(
        name="win-test",
        os_family="windows",
        os_version="11",
        arch="x86_64",
        firmware=BootFirmware.BIOS,
        install_url="http://pxe.local/win/11",
        autoinstall_url="http://pxe.local/unattend/win11",
    )
    defaults.update(overrides)
    return ProvisionProfile(**defaults)


def _parse_xml(xml_text: str) -> ET.Element:
    """Parse unattend.xml into an ElementTree root, handling the MS namespace."""
    return ET.fromstring(xml_text)


NS = {"u": "urn:schemas-microsoft-com:unattend"}


@pytest.fixture
def plugin() -> WindowsPlugin:
    return WindowsPlugin()


# ═══════════════════════════════════════════════════════════════════
# 1.  Edition / image name selection
# ═══════════════════════════════════════════════════════════════════

class TestEditionSelection:
    """Verify the correct Windows image name is set for each edition."""

    def test_win10_pro_default(self, plugin: WindowsPlugin) -> None:
        profile = _make_profile(os_version="10")
        output = plugin.generate_autoinstall(profile)
        assert "Windows 10 Pro" in output

    def test_win11_pro_default(self, plugin: WindowsPlugin) -> None:
        profile = _make_profile(os_version="11")
        output = plugin.generate_autoinstall(profile)
        assert "Windows 11 Pro" in output

    def test_server_2019_core_default(self, plugin: WindowsPlugin) -> None:
        profile = _make_profile(os_version="2019", firmware=BootFirmware.UEFI)
        output = plugin.generate_autoinstall(profile)
        assert "SERVERSTANDARDCORE" in output

    def test_server_2022_core_default(self, plugin: WindowsPlugin) -> None:
        profile = _make_profile(os_version="2022", firmware=BootFirmware.UEFI)
        output = plugin.generate_autoinstall(profile)
        assert "Windows Server 2022 SERVERSTANDARDCORE" in output

    def test_server_2025_core_default(self, plugin: WindowsPlugin) -> None:
        profile = _make_profile(os_version="2025", firmware=BootFirmware.UEFI)
        output = plugin.generate_autoinstall(profile)
        assert "Windows Server 2025 SERVERSTANDARDCORE" in output

    def test_custom_image_name_datacenter(self, plugin: WindowsPlugin) -> None:
        profile = _make_profile(
            os_version="2022",
            firmware=BootFirmware.UEFI,
            extra={"image_name": "Windows Server 2022 SERVERDATACENTER"},
        )
        output = plugin.generate_autoinstall(profile)
        assert "SERVERDATACENTER" in output
        assert "SERVERSTANDARDCORE" not in output

    def test_custom_image_desktop_experience(self, plugin: WindowsPlugin) -> None:
        profile = _make_profile(
            os_version="2022",
            firmware=BootFirmware.UEFI,
            extra={"image_name": "Windows Server 2022 SERVERSTANDARD"},
        )
        output = plugin.generate_autoinstall(profile)
        assert "SERVERSTANDARD" in output
        # Should not have the CORE suffix
        assert "SERVERSTANDARDCORE" not in output

    def test_custom_image_win11_enterprise(self, plugin: WindowsPlugin) -> None:
        profile = _make_profile(
            os_version="11",
            extra={"image_name": "Windows 11 Enterprise"},
        )
        output = plugin.generate_autoinstall(profile)
        assert "Windows 11 Enterprise" in output
        assert "Windows 11 Pro" not in output

    def test_server_versions_constant(self) -> None:
        """Ensure the _SERVER_VERSIONS set is consistent."""
        assert _SERVER_VERSIONS == {"2019", "2022", "2025"}

    def test_version_names_mapping(self) -> None:
        """Ensure all supported versions have friendly names."""
        for v in ("10", "11", "2019", "2022", "2025"):
            assert v in _VERSION_NAMES


# ═══════════════════════════════════════════════════════════════════
# 2.  Product key handling
# ═══════════════════════════════════════════════════════════════════

class TestProductKeyHandling:
    """Verify product key injection and validation."""

    def test_no_product_key_omits_product_key_element(self, plugin: WindowsPlugin) -> None:
        profile = _make_profile(extra={})
        output = plugin.generate_autoinstall(profile)
        assert "<ProductKey>" not in output
        # AcceptEula should still be present
        assert "<AcceptEula>true</AcceptEula>" in output

    def test_empty_string_key_omits_product_key_element(self, plugin: WindowsPlugin) -> None:
        profile = _make_profile(extra={"product_key": ""})
        output = plugin.generate_autoinstall(profile)
        assert "<ProductKey>" not in output

    def test_valid_key_included_in_xml(self, plugin: WindowsPlugin) -> None:
        key = "AAAAA-BBBBB-CCCCC-DDDDD-EEEEE"
        profile = _make_profile(extra={"product_key": key})
        output = plugin.generate_autoinstall(profile)
        assert f"<Key>{key}</Key>" in output

    def test_volume_license_key_format(self, plugin: WindowsPlugin) -> None:
        """KMS client keys follow the same XXXXX-XXXXX-XXXXX-XXXXX-XXXXX format."""
        key = "W269N-WFGWX-YVC9B-4J6C9-T83GX"  # Win 10 Pro GVLK
        profile = _make_profile(
            extra={"product_key": key},
            install_url="http://pxe.local/win/10",
        )
        errors = plugin.validate_profile(profile)
        assert not any("product_key" in e for e in errors)

    def test_invalid_key_too_few_groups(self, plugin: WindowsPlugin) -> None:
        profile = _make_profile(
            extra={"product_key": "AAAAA-BBBBB-CCCCC"},
            install_url="http://pxe.local/win/11",
        )
        errors = plugin.validate_profile(profile)
        assert any("product_key" in e for e in errors)

    def test_invalid_key_wrong_group_length(self, plugin: WindowsPlugin) -> None:
        profile = _make_profile(
            extra={"product_key": "AAA-BBBBB-CCCCC-DDDDD-EEEEE"},
            install_url="http://pxe.local/win/11",
        )
        errors = plugin.validate_profile(profile)
        assert any("product_key" in e for e in errors)

    def test_invalid_key_no_dashes(self, plugin: WindowsPlugin) -> None:
        profile = _make_profile(
            extra={"product_key": "AAAAABBBBBCCCCCDDDDDEEEE"},
            install_url="http://pxe.local/win/11",
        )
        errors = plugin.validate_profile(profile)
        assert any("product_key" in e for e in errors)

    def test_key_with_product_key_element_wrapping(self, plugin: WindowsPlugin) -> None:
        """When a key is present, it must be inside <ProductKey> in the XML."""
        key = "NPPR9-FWDCX-D2C8J-H872K-2YT43"
        profile = _make_profile(extra={"product_key": key})
        output = plugin.generate_autoinstall(profile)
        assert "<ProductKey>" in output


# ═══════════════════════════════════════════════════════════════════
# 3.  Network configuration
# ═══════════════════════════════════════════════════════════════════

class TestNetworkConfiguration:
    """Verify DHCP and static IP configuration in unattend.xml."""

    def test_dhcp_default_no_tcpip_component(self, plugin: WindowsPlugin) -> None:
        """By default dhcp=True, so the static IP component should be absent."""
        profile = _make_profile()
        output = plugin.generate_autoinstall(profile)
        assert "Microsoft-Windows-TCPIP" not in output

    def test_static_ip_includes_tcpip(self, plugin: WindowsPlugin) -> None:
        profile = _make_profile(
            network={
                "dhcp": False,
                "address": "10.0.0.50",
                "prefix_length": "24",
                "gateway": "10.0.0.1",
                "nameservers": ["10.0.0.2", "10.0.0.3"],
            },
        )
        output = plugin.generate_autoinstall(profile)
        assert "Microsoft-Windows-TCPIP" in output
        assert "10.0.0.50" in output
        assert "10.0.0.1" in output
        assert "<DhcpEnabled>false</DhcpEnabled>" in output

    def test_static_ip_dns_servers(self, plugin: WindowsPlugin) -> None:
        profile = _make_profile(
            network={
                "dhcp": False,
                "address": "192.168.1.10",
                "gateway": "192.168.1.1",
                "nameservers": ["1.1.1.1", "8.8.8.8"],
            },
        )
        output = plugin.generate_autoinstall(profile)
        assert "Microsoft-Windows-DNS-Client" in output
        assert "1.1.1.1" in output
        assert "8.8.8.8" in output

    def test_custom_hostname_in_network(self, plugin: WindowsPlugin) -> None:
        profile = _make_profile(network={"hostname": "web-srv-01"})
        output = plugin.generate_autoinstall(profile)
        assert "<ComputerName>web-srv-01</ComputerName>" in output

    def test_hostname_falls_back_to_profile_name(self, plugin: WindowsPlugin) -> None:
        profile = _make_profile(name="fallback-host", network={})
        output = plugin.generate_autoinstall(profile)
        assert "<ComputerName>fallback-host</ComputerName>" in output

    def test_single_nameserver(self, plugin: WindowsPlugin) -> None:
        profile = _make_profile(
            network={
                "dhcp": False,
                "address": "10.0.0.5",
                "gateway": "10.0.0.1",
                "nameservers": ["10.0.0.2"],
            },
        )
        output = plugin.generate_autoinstall(profile)
        assert "10.0.0.2" in output


# ═══════════════════════════════════════════════════════════════════
# 4.  Domain join scenarios
# ═══════════════════════════════════════════════════════════════════

class TestDomainJoin:
    """Verify domain join configuration in the specialize pass."""

    def test_no_domain_join_by_default(self, plugin: WindowsPlugin) -> None:
        profile = _make_profile()
        output = plugin.generate_autoinstall(profile)
        assert "Microsoft-Windows-UnattendedJoin" not in output

    def test_domain_join_present(self, plugin: WindowsPlugin) -> None:
        profile = _make_profile(
            extra={
                "join_domain": "corp.example.com",
                "domain_user": "svc-join",
                "domain_password": "JoinP@ss!",
            },
        )
        output = plugin.generate_autoinstall(profile)
        assert "<JoinDomain>corp.example.com</JoinDomain>" in output
        assert "<Username>svc-join</Username>" in output
        assert "<Password>JoinP@ss!</Password>" in output

    def test_domain_join_with_ou(self, plugin: WindowsPlugin) -> None:
        profile = _make_profile(
            extra={
                "join_domain": "corp.example.com",
                "domain_ou": "OU=Servers,DC=corp,DC=example,DC=com",
            },
        )
        output = plugin.generate_autoinstall(profile)
        assert "<MachineObjectOU>" in output
        assert "OU=Servers" in output

    def test_domain_join_default_user(self, plugin: WindowsPlugin) -> None:
        """When domain_user is not specified, it defaults to Administrator."""
        profile = _make_profile(
            extra={"join_domain": "test.local"},
        )
        output = plugin.generate_autoinstall(profile)
        assert "<Username>Administrator</Username>" in output


# ═══════════════════════════════════════════════════════════════════
# 5.  Locale and timezone settings
# ═══════════════════════════════════════════════════════════════════

class TestLocaleTimezone:
    """Verify locale and timezone rendering."""

    def test_default_locale(self, plugin: WindowsPlugin) -> None:
        profile = _make_profile()
        output = plugin.generate_autoinstall(profile)
        assert "<UILanguage>en-US</UILanguage>" in output
        assert "<InputLocale>en-US</InputLocale>" in output

    def test_custom_locale(self, plugin: WindowsPlugin) -> None:
        profile = _make_profile(extra={"locale": "de-DE", "input_locale": "de-DE"})
        output = plugin.generate_autoinstall(profile)
        assert "<UILanguage>de-DE</UILanguage>" in output
        assert "<InputLocale>de-DE</InputLocale>" in output

    def test_different_input_locale(self, plugin: WindowsPlugin) -> None:
        profile = _make_profile(extra={"locale": "en-US", "input_locale": "fr-FR"})
        output = plugin.generate_autoinstall(profile)
        assert "<InputLocale>fr-FR</InputLocale>" in output
        assert "<UILanguage>en-US</UILanguage>" in output

    def test_default_timezone(self, plugin: WindowsPlugin) -> None:
        profile = _make_profile()
        output = plugin.generate_autoinstall(profile)
        assert "<TimeZone>UTC</TimeZone>" in output

    def test_custom_timezone(self, plugin: WindowsPlugin) -> None:
        profile = _make_profile(extra={"timezone": "Pacific Standard Time"})
        output = plugin.generate_autoinstall(profile)
        assert "<TimeZone>Pacific Standard Time</TimeZone>" in output

    def test_locale_in_oobe_pass(self, plugin: WindowsPlugin) -> None:
        """Locale should appear in both windowsPE and oobeSystem passes."""
        profile = _make_profile(extra={"locale": "ja-JP"})
        output = plugin.generate_autoinstall(profile)
        # The locale should appear multiple times (windowsPE + oobeSystem)
        assert output.count("<UILanguage>ja-JP</UILanguage>") >= 2


# ═══════════════════════════════════════════════════════════════════
# 6.  Partition layout (BIOS vs UEFI)
# ═══════════════════════════════════════════════════════════════════

class TestPartitionLayout:
    """Verify partition creation for BIOS (MBR) and UEFI (GPT)."""

    def test_bios_mbr_layout(self, plugin: WindowsPlugin) -> None:
        profile = _make_profile(firmware=BootFirmware.BIOS)
        output = plugin.generate_autoinstall(profile)
        assert "MBR layout for BIOS" in output
        assert "<Active>true</Active>" in output

    def test_bios_two_partitions(self, plugin: WindowsPlugin) -> None:
        profile = _make_profile(firmware=BootFirmware.BIOS)
        output = plugin.generate_autoinstall(profile)
        # Count individual partition elements (with space), not <CreatePartitions> container
        assert output.count("<CreatePartition ") == 2

    def test_bios_partition_2_is_install_target(self, plugin: WindowsPlugin) -> None:
        profile = _make_profile(firmware=BootFirmware.BIOS)
        output = plugin.generate_autoinstall(profile)
        assert "<PartitionID>2</PartitionID>" in output

    def test_uefi_gpt_layout(self, plugin: WindowsPlugin) -> None:
        profile = _make_profile(firmware=BootFirmware.UEFI)
        output = plugin.generate_autoinstall(profile)
        assert "GPT layout for UEFI" in output

    def test_uefi_three_partitions(self, plugin: WindowsPlugin) -> None:
        profile = _make_profile(firmware=BootFirmware.UEFI)
        output = plugin.generate_autoinstall(profile)
        # Count individual partition elements (with space), not <CreatePartitions> container
        assert output.count("<CreatePartition ") == 3

    def test_uefi_efi_and_msr_types(self, plugin: WindowsPlugin) -> None:
        profile = _make_profile(firmware=BootFirmware.UEFI)
        output = plugin.generate_autoinstall(profile)
        assert "<Type>EFI</Type>" in output
        assert "<Type>MSR</Type>" in output

    def test_uefi_partition_3_is_install_target(self, plugin: WindowsPlugin) -> None:
        profile = _make_profile(firmware=BootFirmware.UEFI)
        output = plugin.generate_autoinstall(profile)
        assert "<PartitionID>3</PartitionID>" in output

    def test_uefi_efi_formatted_fat32(self, plugin: WindowsPlugin) -> None:
        profile = _make_profile(firmware=BootFirmware.UEFI)
        output = plugin.generate_autoinstall(profile)
        assert "<Format>FAT32</Format>" in output

    def test_custom_disk_id(self, plugin: WindowsPlugin) -> None:
        profile = _make_profile(disk={"disk_id": "1"})
        output = plugin.generate_autoinstall(profile)
        assert "<DiskID>1</DiskID>" in output

    def test_default_disk_id_zero(self, plugin: WindowsPlugin) -> None:
        profile = _make_profile()
        output = plugin.generate_autoinstall(profile)
        assert "<DiskID>0</DiskID>" in output

    def test_will_wipe_disk_true(self, plugin: WindowsPlugin) -> None:
        profile = _make_profile()
        output = plugin.generate_autoinstall(profile)
        assert "<WillWipeDisk>true</WillWipeDisk>" in output


# ═══════════════════════════════════════════════════════════════════
# 7.  Auto-logon configuration
# ═══════════════════════════════════════════════════════════════════

class TestAutoLogon:
    """Verify auto-logon settings in oobeSystem pass."""

    def test_auto_logon_enabled_by_default(self, plugin: WindowsPlugin) -> None:
        profile = _make_profile()
        output = plugin.generate_autoinstall(profile)
        assert "<AutoLogon>" in output
        assert "<Enabled>true</Enabled>" in output

    def test_auto_logon_count_default_1(self, plugin: WindowsPlugin) -> None:
        profile = _make_profile()
        output = plugin.generate_autoinstall(profile)
        assert "<LogonCount>1</LogonCount>" in output

    def test_auto_logon_custom_count(self, plugin: WindowsPlugin) -> None:
        profile = _make_profile(extra={"auto_logon_count": 5})
        output = plugin.generate_autoinstall(profile)
        assert "<LogonCount>5</LogonCount>" in output

    def test_auto_logon_disabled(self, plugin: WindowsPlugin) -> None:
        profile = _make_profile(extra={"auto_logon": False})
        output = plugin.generate_autoinstall(profile)
        assert "<AutoLogon>" not in output

    def test_admin_password_in_auto_logon(self, plugin: WindowsPlugin) -> None:
        profile = _make_profile(extra={"admin_password": "Test!Pass123"})
        output = plugin.generate_autoinstall(profile)
        assert "Test!Pass123" in output

    def test_default_admin_password(self, plugin: WindowsPlugin) -> None:
        profile = _make_profile()
        output = plugin.generate_autoinstall(profile)
        assert "P@ssw0rd!" in output


# ═══════════════════════════════════════════════════════════════════
# 8.  Organization / owner fields
# ═══════════════════════════════════════════════════════════════════

class TestOrganizationOwner:
    """Verify organization and owner rendering."""

    def test_default_owner(self, plugin: WindowsPlugin) -> None:
        profile = _make_profile()
        output = plugin.generate_autoinstall(profile)
        assert "<FullName>User</FullName>" in output
        assert "<RegisteredOwner>User</RegisteredOwner>" in output

    def test_custom_owner(self, plugin: WindowsPlugin) -> None:
        profile = _make_profile(extra={"owner": "IT Admin"})
        output = plugin.generate_autoinstall(profile)
        assert "<FullName>IT Admin</FullName>" in output

    def test_organization_when_set(self, plugin: WindowsPlugin) -> None:
        profile = _make_profile(extra={"organization": "Acme Corp"})
        output = plugin.generate_autoinstall(profile)
        assert "<Organization>Acme Corp</Organization>" in output
        assert "<RegisteredOrganization>Acme Corp</RegisteredOrganization>" in output

    def test_no_organization_by_default(self, plugin: WindowsPlugin) -> None:
        profile = _make_profile()
        output = plugin.generate_autoinstall(profile)
        assert "<Organization>" not in output
        assert "<RegisteredOrganization>" not in output


# ═══════════════════════════════════════════════════════════════════
# 9.  Post-install scripts
# ═══════════════════════════════════════════════════════════════════

class TestPostInstallScripts:
    """Verify FirstLogonCommands rendering."""

    def test_no_scripts_no_commands_section(self, plugin: WindowsPlugin) -> None:
        profile = _make_profile(post_scripts=[])
        output = plugin.generate_autoinstall(profile)
        assert "<FirstLogonCommands>" not in output

    def test_single_script(self, plugin: WindowsPlugin) -> None:
        profile = _make_profile(post_scripts=["powershell -File C:\\setup.ps1"])
        output = plugin.generate_autoinstall(profile)
        assert "<FirstLogonCommands>" in output
        assert "<CommandLine>powershell -File C:\\setup.ps1</CommandLine>" in output
        assert "<Order>1</Order>" in output

    def test_multiple_scripts_ordered(self, plugin: WindowsPlugin) -> None:
        scripts = [
            "cmd /c echo first",
            "cmd /c echo second",
            "cmd /c echo third",
        ]
        profile = _make_profile(post_scripts=scripts)
        output = plugin.generate_autoinstall(profile)
        assert "<Order>1</Order>" in output
        assert "<Order>2</Order>" in output
        assert "<Order>3</Order>" in output
        assert "echo first" in output
        assert "echo third" in output

    def test_script_requires_no_user_input(self, plugin: WindowsPlugin) -> None:
        profile = _make_profile(post_scripts=["notepad.exe"])
        output = plugin.generate_autoinstall(profile)
        assert "<RequiresUserInput>false</RequiresUserInput>" in output


# ═══════════════════════════════════════════════════════════════════
# 10.  OOBE settings
# ═══════════════════════════════════════════════════════════════════

class TestOOBE:
    """Verify OOBE (Out Of Box Experience) pass settings."""

    def test_eula_hidden(self, plugin: WindowsPlugin) -> None:
        profile = _make_profile()
        output = plugin.generate_autoinstall(profile)
        assert "<HideEULAPage>true</HideEULAPage>" in output

    def test_wireless_setup_hidden(self, plugin: WindowsPlugin) -> None:
        profile = _make_profile()
        output = plugin.generate_autoinstall(profile)
        assert "<HideWirelessSetupInOOBE>true</HideWirelessSetupInOOBE>" in output

    def test_network_location_work(self, plugin: WindowsPlugin) -> None:
        profile = _make_profile()
        output = plugin.generate_autoinstall(profile)
        assert "<NetworkLocation>Work</NetworkLocation>" in output

    def test_skip_oobe_flags(self, plugin: WindowsPlugin) -> None:
        profile = _make_profile()
        output = plugin.generate_autoinstall(profile)
        assert "<SkipMachineOOBE>true</SkipMachineOOBE>" in output
        assert "<SkipUserOOBE>true</SkipUserOOBE>" in output


# ═══════════════════════════════════════════════════════════════════
# 11.  Boot assets (BIOS vs UEFI)
# ═══════════════════════════════════════════════════════════════════

class TestBootAssetsValidation:
    """Extended boot asset tests beyond the basic plugin tests."""

    def test_bios_pxeboot_n12(self, plugin: WindowsPlugin) -> None:
        profile = _make_profile(firmware=BootFirmware.BIOS)
        assets = plugin.boot_assets(profile)
        assert assets.kernel == "http://pxe.local/win/11/boot/pxeboot.n12"

    def test_uefi_bootmgfw_efi(self, plugin: WindowsPlugin) -> None:
        profile = _make_profile(firmware=BootFirmware.UEFI)
        assets = plugin.boot_assets(profile)
        assert assets.kernel == "http://pxe.local/win/11/boot/bootmgfw.efi"

    def test_initrd_always_boot_wim(self, plugin: WindowsPlugin) -> None:
        for fw in (BootFirmware.BIOS, BootFirmware.UEFI):
            profile = _make_profile(firmware=fw)
            assets = plugin.boot_assets(profile)
            assert assets.initrd == "http://pxe.local/win/11/boot/boot.wim"

    def test_boot_args_empty(self, plugin: WindowsPlugin) -> None:
        """Windows PXE boot does not use kernel boot args."""
        profile = _make_profile()
        assets = plugin.boot_assets(profile)
        assert assets.boot_args == ()

    def test_bootloader_config_mentions_autoinstall_url(
        self, plugin: WindowsPlugin
    ) -> None:
        profile = _make_profile(
            autoinstall_url="http://pxe.local/unattend/custom",
        )
        assets = plugin.boot_assets(profile)
        assert "http://pxe.local/unattend/custom" in assets.bootloader_config

    def test_trailing_slash_stripped(self, plugin: WindowsPlugin) -> None:
        profile = _make_profile(install_url="http://pxe.local/win/11/")
        assets = plugin.boot_assets(profile)
        assert "//" not in assets.kernel.split("://", 1)[1]

    def test_server_version_boot_assets(self, plugin: WindowsPlugin) -> None:
        profile = _make_profile(
            os_version="2022",
            firmware=BootFirmware.UEFI,
            install_url="http://pxe.local/win/2022",
        )
        assets = plugin.boot_assets(profile)
        assert "2022" in assets.kernel
        assert assets.kernel.endswith("bootmgfw.efi")


# ═══════════════════════════════════════════════════════════════════
# 12.  Profile validation
# ═══════════════════════════════════════════════════════════════════

class TestProfileValidation:
    """Extended validation tests beyond the basic plugin tests."""

    def test_valid_profile_bios(self, plugin: WindowsPlugin) -> None:
        profile = _make_profile()
        assert plugin.validate_profile(profile) == []

    def test_valid_profile_uefi(self, plugin: WindowsPlugin) -> None:
        profile = _make_profile(firmware=BootFirmware.UEFI)
        assert plugin.validate_profile(profile) == []

    def test_missing_name(self, plugin: WindowsPlugin) -> None:
        profile = _make_profile(name="")
        errors = plugin.validate_profile(profile)
        assert any("profile name" in e for e in errors)

    def test_wrong_os_family(self, plugin: WindowsPlugin) -> None:
        profile = _make_profile(os_family="linux")
        errors = plugin.validate_profile(profile)
        assert any("os_family mismatch" in e for e in errors)

    def test_unsupported_version(self, plugin: WindowsPlugin) -> None:
        profile = _make_profile(os_version="7")
        errors = plugin.validate_profile(profile)
        assert any("unsupported version" in e for e in errors)

    def test_missing_install_url(self, plugin: WindowsPlugin) -> None:
        profile = _make_profile(install_url="")
        errors = plugin.validate_profile(profile)
        assert any("install_url" in e for e in errors)

    def test_arch_x86_64_valid(self, plugin: WindowsPlugin) -> None:
        profile = _make_profile(arch="x86_64")
        errors = plugin.validate_profile(profile)
        assert not any("architecture" in e for e in errors)

    def test_arch_amd64_valid(self, plugin: WindowsPlugin) -> None:
        profile = _make_profile(arch="amd64")
        errors = plugin.validate_profile(profile)
        assert not any("architecture" in e for e in errors)

    def test_arch_x86_valid(self, plugin: WindowsPlugin) -> None:
        profile = _make_profile(arch="x86")
        errors = plugin.validate_profile(profile)
        assert not any("architecture" in e for e in errors)

    def test_arch_arm64_invalid(self, plugin: WindowsPlugin) -> None:
        profile = _make_profile(arch="arm64")
        errors = plugin.validate_profile(profile)
        assert any("unsupported architecture" in e for e in errors)

    def test_arch_aarch64_invalid(self, plugin: WindowsPlugin) -> None:
        profile = _make_profile(arch="aarch64")
        errors = plugin.validate_profile(profile)
        assert any("unsupported architecture" in e for e in errors)

    def test_multiple_validation_errors(self, plugin: WindowsPlugin) -> None:
        """A profile with several problems should report all errors."""
        profile = _make_profile(
            name="",
            os_family="linux",
            os_version="7",
            install_url="",
            arch="sparc",
        )
        errors = plugin.validate_profile(profile)
        assert len(errors) >= 3


# ═══════════════════════════════════════════════════════════════════
# 13.  XML well-formedness
# ═══════════════════════════════════════════════════════════════════

class TestXmlWellFormedness:
    """Ensure generated XML is parseable."""

    def test_bios_xml_parses(self, plugin: WindowsPlugin) -> None:
        profile = _make_profile(firmware=BootFirmware.BIOS)
        output = plugin.generate_autoinstall(profile)
        root = _parse_xml(output)
        assert root.tag.endswith("unattend")

    def test_uefi_xml_parses(self, plugin: WindowsPlugin) -> None:
        profile = _make_profile(firmware=BootFirmware.UEFI)
        output = plugin.generate_autoinstall(profile)
        root = _parse_xml(output)
        assert root.tag.endswith("unattend")

    def test_xml_with_all_options_parses(self, plugin: WindowsPlugin) -> None:
        """Generate XML with every option populated and verify it parses."""
        profile = _make_profile(
            firmware=BootFirmware.UEFI,
            os_version="2022",
            network={
                "dhcp": False,
                "hostname": "full-test",
                "address": "10.0.0.5",
                "prefix_length": "24",
                "gateway": "10.0.0.1",
                "nameservers": ["10.0.0.2"],
            },
            disk={"disk_id": "0"},
            packages=["IIS-WebServer"],
            post_scripts=["powershell Enable-WindowsOptionalFeature -Online -FeatureName IIS-WebServerRole"],
            extra={
                "product_key": "AAAAA-BBBBB-CCCCC-DDDDD-EEEEE",
                "admin_password": "Str0ngP@ss!",
                "timezone": "Eastern Standard Time",
                "locale": "en-US",
                "input_locale": "en-US",
                "organization": "Test Corp",
                "owner": "Admin",
                "auto_logon": True,
                "auto_logon_count": 3,
                "image_name": "Windows Server 2022 SERVERDATACENTER",
                "join_domain": "corp.test.com",
                "domain_ou": "OU=Servers,DC=corp,DC=test,DC=com",
                "domain_user": "svc-join",
                "domain_password": "D0m@inP@ss!",
            },
        )
        output = plugin.generate_autoinstall(profile)
        root = _parse_xml(output)
        # Should have 3 settings passes
        settings = root.findall("u:settings", NS)
        assert len(settings) == 3


# ═══════════════════════════════════════════════════════════════════
# 14.  ISO extraction
# ═══════════════════════════════════════════════════════════════════

class TestExtractFromIso:
    """Test Windows ISO extraction with various directory layouts."""

    def test_extracts_boot_wim_lowercase(
        self, plugin: WindowsPlugin, tmp_path: Path
    ) -> None:
        mount = tmp_path / "mount"
        dest = tmp_path / "dest"
        boot_dir = mount / "boot"
        boot_dir.mkdir(parents=True)
        (boot_dir / "boot.wim").write_bytes(b"BOOT_WIM_DATA")

        assets = plugin.extract_from_iso(mount, dest)
        assert assets.kernel_path == dest / "boot" / "boot.wim"
        assert assets.kernel_path.read_bytes() == b"BOOT_WIM_DATA"

    def test_extracts_boot_wim_capital_boot(
        self, plugin: WindowsPlugin, tmp_path: Path
    ) -> None:
        mount = tmp_path / "mount"
        dest = tmp_path / "dest"
        boot_dir = mount / "Boot"
        boot_dir.mkdir(parents=True)
        (boot_dir / "boot.wim").write_bytes(b"BOOT_WIM")

        assets = plugin.extract_from_iso(mount, dest)
        assert assets.kernel_path.exists()

    def test_extracts_install_wim(
        self, plugin: WindowsPlugin, tmp_path: Path
    ) -> None:
        mount = tmp_path / "mount"
        dest = tmp_path / "dest"
        (mount / "boot").mkdir(parents=True)
        sources = mount / "sources"
        sources.mkdir(parents=True)
        (sources / "install.wim").write_bytes(b"INSTALL_WIM")

        assets = plugin.extract_from_iso(mount, dest)
        assert (dest / "sources" / "install.wim").exists()

    def test_extracts_install_esd_fallback(
        self, plugin: WindowsPlugin, tmp_path: Path
    ) -> None:
        mount = tmp_path / "mount"
        dest = tmp_path / "dest"
        (mount / "boot").mkdir(parents=True)
        sources = mount / "sources"
        sources.mkdir(parents=True)
        (sources / "install.esd").write_bytes(b"INSTALL_ESD")

        plugin.extract_from_iso(mount, dest)
        assert (dest / "sources" / "install.wim").exists()

    def test_extracts_uefi_bootloader(
        self, plugin: WindowsPlugin, tmp_path: Path
    ) -> None:
        mount = tmp_path / "mount"
        dest = tmp_path / "dest"
        (mount / "boot").mkdir(parents=True)
        efi_dir = mount / "efi" / "boot"
        efi_dir.mkdir(parents=True)
        (efi_dir / "bootx64.efi").write_bytes(b"EFI_BOOT")

        assets = plugin.extract_from_iso(mount, dest)
        assert assets.boot_loader_path is not None
        assert assets.boot_loader_path.name == "bootmgfw.efi"

    def test_extracts_bios_pxeboot(
        self, plugin: WindowsPlugin, tmp_path: Path
    ) -> None:
        mount = tmp_path / "mount"
        dest = tmp_path / "dest"
        boot_dir = mount / "boot"
        boot_dir.mkdir(parents=True)
        (boot_dir / "pxeboot.n12").write_bytes(b"PXEBOOT")

        assets = plugin.extract_from_iso(mount, dest)
        assert (dest / "boot" / "pxeboot.n12").exists()

    def test_extracts_bcd_store(
        self, plugin: WindowsPlugin, tmp_path: Path
    ) -> None:
        mount = tmp_path / "mount"
        dest = tmp_path / "dest"
        boot_dir = mount / "boot"
        boot_dir.mkdir(parents=True)
        (boot_dir / "bcd").write_bytes(b"BCD_STORE")

        plugin.extract_from_iso(mount, dest)
        assert (dest / "boot" / "BCD").exists()

    def test_boot_loader_prefers_efi_over_pxeboot(
        self, plugin: WindowsPlugin, tmp_path: Path
    ) -> None:
        mount = tmp_path / "mount"
        dest = tmp_path / "dest"
        boot_dir = mount / "boot"
        boot_dir.mkdir(parents=True)
        (boot_dir / "pxeboot.n12").write_bytes(b"PXEBOOT")
        efi_dir = mount / "efi" / "boot"
        efi_dir.mkdir(parents=True)
        (efi_dir / "bootx64.efi").write_bytes(b"EFI")

        assets = plugin.extract_from_iso(mount, dest)
        assert assets.boot_loader_path.name == "bootmgfw.efi"

    def test_missing_all_files_returns_none_loader(
        self, plugin: WindowsPlugin, tmp_path: Path
    ) -> None:
        mount = tmp_path / "mount"
        dest = tmp_path / "dest"
        mount.mkdir(parents=True)

        assets = plugin.extract_from_iso(mount, dest)
        assert assets.boot_loader_path is None
        assert assets.initrd_path is None

    def test_repo_path_is_sources_dir(
        self, plugin: WindowsPlugin, tmp_path: Path
    ) -> None:
        mount = tmp_path / "mount"
        dest = tmp_path / "dest"
        mount.mkdir(parents=True)

        assets = plugin.extract_from_iso(mount, dest)
        assert assets.repo_path == dest / "sources"


# ═══════════════════════════════════════════════════════════════════
# 15.  WinPE pass structure
# ═══════════════════════════════════════════════════════════════════

class TestWinPEPass:
    """Verify windowsPE pass structure and components."""

    def test_winpe_has_international_core(self, plugin: WindowsPlugin) -> None:
        profile = _make_profile()
        output = plugin.generate_autoinstall(profile)
        assert "Microsoft-Windows-International-Core-WinPE" in output

    def test_winpe_has_setup_component(self, plugin: WindowsPlugin) -> None:
        profile = _make_profile()
        output = plugin.generate_autoinstall(profile)
        assert "Microsoft-Windows-Setup" in output

    def test_processor_arch_attribute(self, plugin: WindowsPlugin) -> None:
        profile = _make_profile(arch="amd64")
        output = plugin.generate_autoinstall(profile)
        assert 'processorArchitecture="amd64"' in output

    def test_disk_configuration_in_setup(self, plugin: WindowsPlugin) -> None:
        profile = _make_profile()
        output = plugin.generate_autoinstall(profile)
        assert "<DiskConfiguration>" in output
        assert "<WillShowUI>OnError</WillShowUI>" in output

    def test_image_install_section(self, plugin: WindowsPlugin) -> None:
        profile = _make_profile()
        output = plugin.generate_autoinstall(profile)
        assert "<ImageInstall>" in output
        assert "<OSImage>" in output
        assert "<InstallTo>" in output

    def test_image_name_metadata(self, plugin: WindowsPlugin) -> None:
        profile = _make_profile()
        output = plugin.generate_autoinstall(profile)
        assert "<Key>/IMAGE/NAME</Key>" in output
