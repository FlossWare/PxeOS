"""Comprehensive tests for Windows plugin rebuild (issue #53).

Covers: autounattend.xml schema validation, driver injection via
profile.extra driver_paths, WinPE boot arguments, SetupComplete.cmd
support, and autoinstall template improvements.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest

from pxeos.models import BootFirmware, ProvisionProfile
from pxeos.plugins.windows import (
    WindowsPlugin,
    _KNOWN_COMPONENTS,
    _REQUIRED_PASSES,
    _SERVER_VERSIONS,
    _VALID_PASSES,
    _VERSION_NAMES,
)


# -- helpers ---------------------------------------------------------

def _make_profile(**overrides) -> ProvisionProfile:
    """Build a Windows profile with sensible defaults."""
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


NS = {"u": "urn:schemas-microsoft-com:unattend"}


@pytest.fixture
def plugin() -> WindowsPlugin:
    return WindowsPlugin()


# ================================================================
# 1. Schema validation - validate_unattend_schema()
# ================================================================

class TestSchemaValidation:
    """Tests for the new validate_unattend_schema method."""

    def test_valid_bios_xml_passes(
        self, plugin: WindowsPlugin
    ) -> None:
        profile = _make_profile(firmware=BootFirmware.BIOS)
        xml = plugin.generate_autoinstall(profile)
        errors = plugin.validate_unattend_schema(xml)
        assert errors == []

    def test_valid_uefi_xml_passes(
        self, plugin: WindowsPlugin
    ) -> None:
        profile = _make_profile(firmware=BootFirmware.UEFI)
        xml = plugin.generate_autoinstall(profile)
        errors = plugin.validate_unattend_schema(xml)
        assert errors == []

    def test_malformed_xml_returns_parse_error(
        self, plugin: WindowsPlugin
    ) -> None:
        errors = plugin.validate_unattend_schema(
            "<not valid xml><"
        )
        assert len(errors) == 1
        assert "XML parse error" in errors[0]

    def test_wrong_root_element(
        self, plugin: WindowsPlugin
    ) -> None:
        xml = (
            '<?xml version="1.0"?>'
            '<configuration xmlns='
            '"urn:schemas-microsoft-com:unattend">'
            "</configuration>"
        )
        errors = plugin.validate_unattend_schema(xml)
        assert any("root element" in e for e in errors)

    def test_wrong_namespace(
        self, plugin: WindowsPlugin
    ) -> None:
        xml = (
            '<?xml version="1.0"?>'
            '<unattend xmlns="urn:wrong:namespace">'
            "</unattend>"
        )
        errors = plugin.validate_unattend_schema(xml)
        assert any("root element" in e for e in errors)

    def test_missing_settings_elements(
        self, plugin: WindowsPlugin
    ) -> None:
        xml = (
            '<?xml version="1.0"?>'
            '<unattend xmlns='
            '"urn:schemas-microsoft-com:unattend">'
            "</unattend>"
        )
        errors = plugin.validate_unattend_schema(xml)
        assert any(
            "no <settings> elements" in e
            for e in errors
        )

    def test_invalid_pass_name(
        self, plugin: WindowsPlugin
    ) -> None:
        xml = (
            '<?xml version="1.0"?>'
            '<unattend xmlns='
            '"urn:schemas-microsoft-com:unattend">'
            '<settings pass="invalidPass">'
            "</settings>"
            '<settings pass="windowsPE">'
            "</settings>"
            '<settings pass="oobeSystem">'
            "</settings>"
            "</unattend>"
        )
        errors = plugin.validate_unattend_schema(xml)
        assert any("invalid pass name" in e for e in errors)
        assert any("invalidPass" in e for e in errors)

    def test_missing_required_passes(
        self, plugin: WindowsPlugin
    ) -> None:
        xml = (
            '<?xml version="1.0"?>'
            '<unattend xmlns='
            '"urn:schemas-microsoft-com:unattend">'
            '<settings pass="specialize">'
            "</settings>"
            "</unattend>"
        )
        errors = plugin.validate_unattend_schema(xml)
        assert any("windowsPE" in e for e in errors)
        assert any("oobeSystem" in e for e in errors)

    def test_unknown_component_name(
        self, plugin: WindowsPlugin
    ) -> None:
        xml = (
            '<?xml version="1.0"?>'
            '<unattend xmlns='
            '"urn:schemas-microsoft-com:unattend">'
            '<settings pass="windowsPE">'
            '<component name="Unknown-Component"'
            ' processorArchitecture="amd64"'
            ' publicKeyToken="31bf3856ad364e35"'
            ' language="neutral"'
            ' versionScope="nonSxS"/>'
            "</settings>"
            '<settings pass="oobeSystem">'
            "</settings>"
            "</unattend>"
        )
        errors = plugin.validate_unattend_schema(xml)
        assert any(
            "unknown component" in e for e in errors
        )

    def test_missing_processor_architecture(
        self, plugin: WindowsPlugin
    ) -> None:
        xml = (
            '<?xml version="1.0"?>'
            '<unattend xmlns='
            '"urn:schemas-microsoft-com:unattend">'
            '<settings pass="windowsPE">'
            '<component name="Microsoft-Windows-Setup"'
            ' publicKeyToken="31bf3856ad364e35"'
            ' language="neutral"'
            ' versionScope="nonSxS"/>'
            "</settings>"
            '<settings pass="oobeSystem">'
            "</settings>"
            "</unattend>"
        )
        errors = plugin.validate_unattend_schema(xml)
        assert any(
            "processorArchitecture" in e
            for e in errors
        )

    def test_full_profile_xml_validates(
        self, plugin: WindowsPlugin
    ) -> None:
        """Generate XML with all features and validate."""
        profile = _make_profile(
            firmware=BootFirmware.UEFI,
            os_version="2022",
            network={
                "dhcp": False,
                "hostname": "schema-test",
                "address": "10.0.0.5",
                "prefix_length": "24",
                "gateway": "10.0.0.1",
                "nameservers": ["10.0.0.2"],
            },
            extra={
                "product_key": "AAAAA-BBBBB-CCCCC-DDDDD-EEEEE",
                "admin_password": "Test!",
                "organization": "Test",
                "driver_paths": [
                    "\\\\server\\drivers\\virtio",
                ],
                "join_domain": "test.local",
                "setup_complete": "C:\\scripts\\setup.cmd",
            },
            post_scripts=["cmd /c echo done"],
        )
        xml = plugin.generate_autoinstall(profile)
        errors = plugin.validate_unattend_schema(xml)
        assert errors == []

    def test_valid_passes_constant(self) -> None:
        """Verify _VALID_PASSES includes all 7 MS passes."""
        assert len(_VALID_PASSES) == 7
        assert "windowsPE" in _VALID_PASSES
        assert "specialize" in _VALID_PASSES
        assert "oobeSystem" in _VALID_PASSES
        assert "offlineServicing" in _VALID_PASSES
        assert "generalize" in _VALID_PASSES
        assert "auditSystem" in _VALID_PASSES
        assert "auditUser" in _VALID_PASSES

    def test_required_passes_constant(self) -> None:
        assert "windowsPE" in _REQUIRED_PASSES
        assert "oobeSystem" in _REQUIRED_PASSES

    def test_known_components_includes_pnp(self) -> None:
        assert (
            "Microsoft-Windows-PnpCustomizationsWinPE"
            in _KNOWN_COMPONENTS
        )

    def test_missing_pass_attribute(
        self, plugin: WindowsPlugin
    ) -> None:
        xml = (
            '<?xml version="1.0"?>'
            '<unattend xmlns='
            '"urn:schemas-microsoft-com:unattend">'
            "<settings>"
            "</settings>"
            "</unattend>"
        )
        errors = plugin.validate_unattend_schema(xml)
        assert any(
            "missing" in e and "pass" in e
            for e in errors
        )


# ================================================================
# 2. Driver injection via profile.extra["driver_paths"]
# ================================================================

class TestDriverInjection:
    """Tests for driver path injection into unattend.xml."""

    def test_no_drivers_omits_pnp_component(
        self, plugin: WindowsPlugin
    ) -> None:
        profile = _make_profile()
        output = plugin.generate_autoinstall(profile)
        assert (
            "Microsoft-Windows-PnpCustomizationsWinPE"
            not in output
        )

    def test_single_driver_path(
        self, plugin: WindowsPlugin
    ) -> None:
        profile = _make_profile(
            extra={
                "driver_paths": [
                    "\\\\server\\share\\drivers\\virtio"
                ]
            }
        )
        output = plugin.generate_autoinstall(profile)
        assert (
            "Microsoft-Windows-PnpCustomizationsWinPE"
            in output
        )
        assert "<DriverPaths>" in output
        assert "<PathAndCredentials" in output
        assert (
            "\\\\server\\share\\drivers\\virtio"
            in output
        )

    def test_multiple_driver_paths(
        self, plugin: WindowsPlugin
    ) -> None:
        paths = [
            "\\\\server\\drivers\\virtio",
            "\\\\server\\drivers\\nic",
            "\\\\server\\drivers\\storage",
        ]
        profile = _make_profile(
            extra={"driver_paths": paths}
        )
        output = plugin.generate_autoinstall(profile)
        for p in paths:
            assert p in output
        # Verify ordering via keyValue attributes
        assert 'wcm:keyValue="1"' in output
        assert 'wcm:keyValue="2"' in output
        assert 'wcm:keyValue="3"' in output

    def test_driver_paths_in_winpe_pass(
        self, plugin: WindowsPlugin
    ) -> None:
        """Driver paths must be inside the windowsPE pass."""
        profile = _make_profile(
            extra={
                "driver_paths": [
                    "D:\\drivers\\virtio"
                ]
            }
        )
        output = plugin.generate_autoinstall(profile)
        root = ET.fromstring(output)
        winpe_settings = None
        for s in root.findall("u:settings", NS):
            if s.get("pass") == "windowsPE":
                winpe_settings = s
                break
        assert winpe_settings is not None
        pnp = winpe_settings.find(
            ".//u:component["
            "@name='Microsoft-Windows-"
            "PnpCustomizationsWinPE']",
            NS,
        )
        assert pnp is not None
        driver_paths_el = pnp.find(
            "u:DriverPaths", NS
        )
        assert driver_paths_el is not None

    def test_driver_xml_well_formed_with_drivers(
        self, plugin: WindowsPlugin
    ) -> None:
        profile = _make_profile(
            firmware=BootFirmware.UEFI,
            extra={
                "driver_paths": [
                    "E:\\drivers\\net",
                    "E:\\drivers\\storage",
                ]
            },
        )
        output = plugin.generate_autoinstall(profile)
        root = ET.fromstring(output)
        assert root.tag.endswith("unattend")

    def test_driver_schema_validates(
        self, plugin: WindowsPlugin
    ) -> None:
        """Generated XML with drivers passes schema validation."""
        profile = _make_profile(
            extra={
                "driver_paths": [
                    "\\\\pxe\\drivers\\virtio\\w11"
                ]
            }
        )
        xml = plugin.generate_autoinstall(profile)
        errors = plugin.validate_unattend_schema(xml)
        assert errors == []

    def test_empty_driver_paths_omits_section(
        self, plugin: WindowsPlugin
    ) -> None:
        profile = _make_profile(
            extra={"driver_paths": []}
        )
        output = plugin.generate_autoinstall(profile)
        assert (
            "Microsoft-Windows-PnpCustomizationsWinPE"
            not in output
        )


# ================================================================
# 3. Driver path validation in validate_profile
# ================================================================

class TestDriverPathValidation:
    """Tests for driver_paths validation in validate_profile."""

    def test_valid_driver_paths(
        self, plugin: WindowsPlugin
    ) -> None:
        profile = _make_profile(
            extra={
                "driver_paths": [
                    "\\\\server\\drivers\\virtio",
                    "D:\\drivers\\nic",
                ]
            }
        )
        errors = plugin.validate_profile(profile)
        assert not any(
            "driver_paths" in e for e in errors
        )

    def test_driver_paths_not_a_list(
        self, plugin: WindowsPlugin
    ) -> None:
        profile = _make_profile(
            extra={
                "driver_paths": "\\\\server\\drivers"
            }
        )
        errors = plugin.validate_profile(profile)
        assert any(
            "driver_paths must be a list" in e
            for e in errors
        )

    def test_driver_path_empty_string(
        self, plugin: WindowsPlugin
    ) -> None:
        profile = _make_profile(
            extra={"driver_paths": [""]}
        )
        errors = plugin.validate_profile(profile)
        assert any(
            "driver_paths[0]" in e for e in errors
        )

    def test_driver_path_not_string(
        self, plugin: WindowsPlugin
    ) -> None:
        profile = _make_profile(
            extra={"driver_paths": [123]}
        )
        errors = plugin.validate_profile(profile)
        assert any(
            "driver_paths[0]" in e for e in errors
        )

    def test_driver_path_whitespace_only(
        self, plugin: WindowsPlugin
    ) -> None:
        profile = _make_profile(
            extra={"driver_paths": ["   "]}
        )
        errors = plugin.validate_profile(profile)
        assert any(
            "driver_paths[0]" in e for e in errors
        )

    def test_no_driver_paths_key_is_valid(
        self, plugin: WindowsPlugin
    ) -> None:
        profile = _make_profile(extra={})
        errors = plugin.validate_profile(profile)
        assert not any(
            "driver_paths" in e for e in errors
        )

    def test_multiple_invalid_paths_reported(
        self, plugin: WindowsPlugin
    ) -> None:
        profile = _make_profile(
            extra={
                "driver_paths": ["valid\\path", "", 42]
            }
        )
        errors = plugin.validate_profile(profile)
        driver_errors = [
            e for e in errors if "driver_paths" in e
        ]
        assert len(driver_errors) == 2


# ================================================================
# 4. WinPE boot arguments
# ================================================================

class TestWinPEBootArgs:
    """Tests for WinPE boot arguments in boot_assets."""

    def test_default_boot_args_empty(
        self, plugin: WindowsPlugin
    ) -> None:
        profile = _make_profile()
        assets = plugin.boot_assets(profile)
        assert assets.boot_args == ()

    def test_custom_winpe_boot_args(
        self, plugin: WindowsPlugin
    ) -> None:
        profile = _make_profile(
            extra={
                "winpe_boot_args": [
                    "/WinPE",
                    "/minint",
                ]
            }
        )
        assets = plugin.boot_assets(profile)
        assert "/WinPE" in assets.boot_args
        assert "/minint" in assets.boot_args

    def test_single_winpe_boot_arg(
        self, plugin: WindowsPlugin
    ) -> None:
        profile = _make_profile(
            extra={
                "winpe_boot_args": [
                    "BCD=/boot/BCD"
                ]
            }
        )
        assets = plugin.boot_assets(profile)
        assert len(assets.boot_args) == 1
        assert assets.boot_args[0] == "BCD=/boot/BCD"

    def test_winpe_args_with_bios(
        self, plugin: WindowsPlugin
    ) -> None:
        profile = _make_profile(
            firmware=BootFirmware.BIOS,
            extra={
                "winpe_boot_args": [
                    "/WinPE",
                    "wpeinit",
                ]
            },
        )
        assets = plugin.boot_assets(profile)
        assert assets.kernel.endswith("pxeboot.n12")
        assert "/WinPE" in assets.boot_args
        assert "wpeinit" in assets.boot_args

    def test_winpe_args_with_uefi(
        self, plugin: WindowsPlugin
    ) -> None:
        profile = _make_profile(
            firmware=BootFirmware.UEFI,
            extra={
                "winpe_boot_args": [
                    "/WinPE",
                ]
            },
        )
        assets = plugin.boot_assets(profile)
        assert assets.kernel.endswith("bootmgfw.efi")
        assert "/WinPE" in assets.boot_args

    def test_winpe_boot_args_validation_valid(
        self, plugin: WindowsPlugin
    ) -> None:
        profile = _make_profile(
            extra={
                "winpe_boot_args": ["/WinPE"]
            }
        )
        errors = plugin.validate_profile(profile)
        assert not any(
            "winpe_boot_args" in e for e in errors
        )

    def test_winpe_boot_args_validation_not_list(
        self, plugin: WindowsPlugin
    ) -> None:
        profile = _make_profile(
            extra={"winpe_boot_args": "/WinPE"}
        )
        errors = plugin.validate_profile(profile)
        assert any(
            "winpe_boot_args must be a list" in e
            for e in errors
        )

    def test_no_winpe_boot_args_is_valid(
        self, plugin: WindowsPlugin
    ) -> None:
        profile = _make_profile(extra={})
        errors = plugin.validate_profile(profile)
        assert not any(
            "winpe_boot_args" in e for e in errors
        )


# ================================================================
# 4b. SetupComplete validation
# ================================================================

class TestSetupCompleteValidation:
    """Tests for setup_complete validation in validate_profile."""

    def test_valid_setup_complete_string(
        self, plugin: WindowsPlugin
    ) -> None:
        profile = _make_profile(
            extra={"setup_complete": "C:\\setup.cmd"}
        )
        errors = plugin.validate_profile(profile)
        assert not any(
            "setup_complete" in e for e in errors
        )

    def test_setup_complete_not_string(
        self, plugin: WindowsPlugin
    ) -> None:
        profile = _make_profile(
            extra={"setup_complete": 123}
        )
        errors = plugin.validate_profile(profile)
        assert any(
            "setup_complete must be a string" in e
            for e in errors
        )

    def test_no_setup_complete_is_valid(
        self, plugin: WindowsPlugin
    ) -> None:
        profile = _make_profile(extra={})
        errors = plugin.validate_profile(profile)
        assert not any(
            "setup_complete" in e for e in errors
        )

    def test_empty_setup_complete_is_valid(
        self, plugin: WindowsPlugin
    ) -> None:
        profile = _make_profile(
            extra={"setup_complete": ""}
        )
        errors = plugin.validate_profile(profile)
        assert not any(
            "setup_complete" in e for e in errors
        )


# ================================================================
# 5. SetupComplete.cmd support
# ================================================================

class TestSetupComplete:
    """Tests for SetupComplete.cmd script support."""

    def test_no_setup_complete_omits_section(
        self, plugin: WindowsPlugin
    ) -> None:
        profile = _make_profile(
            post_scripts=[], extra={}
        )
        output = plugin.generate_autoinstall(profile)
        assert "<FirstLogonCommands>" not in output
        assert "SetupComplete" not in output

    def test_setup_complete_adds_command(
        self, plugin: WindowsPlugin
    ) -> None:
        profile = _make_profile(
            extra={
                "setup_complete": (
                    "C:\\Windows\\Setup\\Scripts\\"
                    "SetupComplete.cmd"
                )
            }
        )
        output = plugin.generate_autoinstall(profile)
        assert "<FirstLogonCommands>" in output
        assert "SetupComplete" in output
        assert "cmd /c" in output

    def test_setup_complete_after_post_scripts(
        self, plugin: WindowsPlugin
    ) -> None:
        """SetupComplete runs after all post_scripts."""
        profile = _make_profile(
            post_scripts=["cmd /c echo first"],
            extra={
                "setup_complete": (
                    "C:\\scripts\\setup.cmd"
                )
            },
        )
        output = plugin.generate_autoinstall(profile)
        # post_script gets Order 1
        assert "<Order>1</Order>" in output
        # setup_complete gets Order 2
        assert "<Order>2</Order>" in output
        # Verify setup_complete is present
        assert "C:\\scripts\\setup.cmd" in output

    def test_setup_complete_ordering_with_multiple(
        self, plugin: WindowsPlugin
    ) -> None:
        """SetupComplete runs after all N post_scripts."""
        profile = _make_profile(
            post_scripts=[
                "cmd /c echo one",
                "cmd /c echo two",
                "cmd /c echo three",
            ],
            extra={
                "setup_complete": (
                    "C:\\final\\setup.cmd"
                )
            },
        )
        output = plugin.generate_autoinstall(profile)
        assert "<Order>1</Order>" in output
        assert "<Order>2</Order>" in output
        assert "<Order>3</Order>" in output
        assert "<Order>4</Order>" in output

    def test_setup_complete_xml_well_formed(
        self, plugin: WindowsPlugin
    ) -> None:
        profile = _make_profile(
            extra={
                "setup_complete": (
                    "C:\\setup.cmd"
                )
            }
        )
        output = plugin.generate_autoinstall(profile)
        root = ET.fromstring(output)
        assert root.tag.endswith("unattend")

    def test_setup_complete_alone_creates_commands(
        self, plugin: WindowsPlugin
    ) -> None:
        """SetupComplete without post_scripts still works."""
        profile = _make_profile(
            post_scripts=[],
            extra={
                "setup_complete": (
                    "C:\\scripts\\final.cmd"
                )
            },
        )
        output = plugin.generate_autoinstall(profile)
        assert "<FirstLogonCommands>" in output
        assert "<Order>1</Order>" in output
        assert "C:\\scripts\\final.cmd" in output


# ================================================================
# 6. WinPE commands (startnet.cmd) in template
# ================================================================

class TestWinPECommands:
    """Tests for WinPE commands in the template context."""

    def test_winpe_commands_passed_to_context(
        self, plugin: WindowsPlugin
    ) -> None:
        """winpe_commands are available in the template."""
        profile = _make_profile(
            extra={
                "winpe_commands": [
                    "wpeinit",
                    "net use Z: \\\\server\\share",
                ]
            }
        )
        # Verifies that it does not crash
        output = plugin.generate_autoinstall(profile)
        assert output  # Non-empty XML

    def test_empty_winpe_commands_ok(
        self, plugin: WindowsPlugin
    ) -> None:
        profile = _make_profile(
            extra={"winpe_commands": []}
        )
        output = plugin.generate_autoinstall(profile)
        assert output


# ================================================================
# 7. Combined features
# ================================================================

class TestCombinedFeatures:
    """Tests with multiple new features together."""

    def test_drivers_and_setup_complete(
        self, plugin: WindowsPlugin
    ) -> None:
        profile = _make_profile(
            firmware=BootFirmware.UEFI,
            extra={
                "driver_paths": [
                    "\\\\pxe\\drivers\\virtio"
                ],
                "setup_complete": (
                    "C:\\scripts\\final.cmd"
                ),
            },
            post_scripts=["powershell Set-Thing"],
        )
        output = plugin.generate_autoinstall(profile)
        assert (
            "Microsoft-Windows-PnpCustomizationsWinPE"
            in output
        )
        assert "SetupComplete" in output
        root = ET.fromstring(output)
        assert root.tag.endswith("unattend")

    def test_all_new_features_with_schema_validation(
        self, plugin: WindowsPlugin
    ) -> None:
        """All new features produce valid XML."""
        profile = _make_profile(
            firmware=BootFirmware.UEFI,
            os_version="2022",
            extra={
                "driver_paths": [
                    "\\\\server\\drivers\\virtio",
                    "\\\\server\\drivers\\nic",
                ],
                "setup_complete": (
                    "C:\\scripts\\setup.cmd"
                ),
                "winpe_boot_args": ["/WinPE"],
                "product_key": (
                    "AAAAA-BBBBB-CCCCC-DDDDD-EEEEE"
                ),
                "admin_password": "Str0ng!",
                "organization": "Test Corp",
            },
            post_scripts=[
                "cmd /c echo test",
                "powershell Enable-Feature",
            ],
        )
        xml = plugin.generate_autoinstall(profile)
        errors = plugin.validate_unattend_schema(xml)
        assert errors == []

        # Also check boot assets
        assets = plugin.boot_assets(profile)
        assert "/WinPE" in assets.boot_args
        assert assets.kernel.endswith("bootmgfw.efi")

    def test_validate_all_features_profile(
        self, plugin: WindowsPlugin
    ) -> None:
        """Profile validation passes with all features."""
        profile = _make_profile(
            extra={
                "driver_paths": [
                    "\\\\srv\\drv\\virtio"
                ],
                "winpe_boot_args": ["/WinPE"],
                "product_key": (
                    "AAAAA-BBBBB-CCCCC-DDDDD-EEEEE"
                ),
                "setup_complete": "C:\\setup.cmd",
            }
        )
        errors = plugin.validate_profile(profile)
        assert errors == []

    def test_drivers_plus_domain_join(
        self, plugin: WindowsPlugin
    ) -> None:
        """Drivers and domain join together."""
        profile = _make_profile(
            firmware=BootFirmware.UEFI,
            extra={
                "driver_paths": [
                    "E:\\drivers\\net"
                ],
                "join_domain": "corp.example.com",
                "domain_user": "svc-join",
                "domain_password": "P@ss!",
            },
        )
        output = plugin.generate_autoinstall(profile)
        assert (
            "Microsoft-Windows-PnpCustomizationsWinPE"
            in output
        )
        assert (
            "Microsoft-Windows-UnattendedJoin"
            in output
        )
        assert (
            "<JoinDomain>corp.example.com</JoinDomain>"
            in output
        )
        root = ET.fromstring(output)
        assert root.tag.endswith("unattend")


# ================================================================
# 8. Backward compatibility
# ================================================================

class TestBackwardCompatibility:
    """Verify existing functionality still works."""

    def test_basic_bios_profile_unchanged(
        self, plugin: WindowsPlugin
    ) -> None:
        profile = _make_profile(firmware=BootFirmware.BIOS)
        output = plugin.generate_autoinstall(profile)
        assert "MBR layout for BIOS" in output
        assert "<Active>true</Active>" in output

    def test_basic_uefi_profile_unchanged(
        self, plugin: WindowsPlugin
    ) -> None:
        profile = _make_profile(
            firmware=BootFirmware.UEFI
        )
        output = plugin.generate_autoinstall(profile)
        assert "GPT layout for UEFI" in output
        assert "<Type>EFI</Type>" in output

    def test_os_family(
        self, plugin: WindowsPlugin
    ) -> None:
        assert plugin.os_family == "windows"

    def test_supported_versions(
        self, plugin: WindowsPlugin
    ) -> None:
        assert "10" in plugin.supported_versions
        assert "11" in plugin.supported_versions
        assert "2022" in plugin.supported_versions

    def test_autoinstall_filename(
        self, plugin: WindowsPlugin
    ) -> None:
        assert (
            plugin.autoinstall_filename()
            == "unattend.xml"
        )

    def test_no_extra_features_xml_parses(
        self, plugin: WindowsPlugin
    ) -> None:
        profile = _make_profile()
        output = plugin.generate_autoinstall(profile)
        root = ET.fromstring(output)
        assert root.tag.endswith("unattend")
        settings = root.findall("u:settings", NS)
        assert len(settings) == 3

    def test_boot_assets_bios_no_args(
        self, plugin: WindowsPlugin
    ) -> None:
        profile = _make_profile(
            firmware=BootFirmware.BIOS
        )
        assets = plugin.boot_assets(profile)
        assert assets.boot_args == ()
        assert "pxeboot.n12" in assets.kernel
        assert "boot.wim" in assets.initrd

    def test_boot_assets_uefi_no_args(
        self, plugin: WindowsPlugin
    ) -> None:
        profile = _make_profile(
            firmware=BootFirmware.UEFI
        )
        assets = plugin.boot_assets(profile)
        assert assets.boot_args == ()
        assert "bootmgfw.efi" in assets.kernel

    def test_post_scripts_still_work(
        self, plugin: WindowsPlugin
    ) -> None:
        profile = _make_profile(
            post_scripts=[
                "cmd /c echo hello",
                "powershell Set-Something",
            ]
        )
        output = plugin.generate_autoinstall(profile)
        assert "<FirstLogonCommands>" in output
        assert "<Order>1</Order>" in output
        assert "<Order>2</Order>" in output
        assert "echo hello" in output
