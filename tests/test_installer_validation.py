"""Validate generated installer configs against real installer schemas.

Generates kickstart, preseed, cloud-init, autounattend.xml, and autoyast
configs using the existing plugins, then validates them statically:
  - Kickstart: required sections and directives per Anaconda spec
  - Preseed: d-i key-value pair format per debian-installer spec
  - Cloud-init: valid YAML with required autoinstall schema keys
  - Autounattend.xml: well-formed XML with required Windows Setup elements
  - AutoYaST: well-formed XML with required YaST2 profile elements

References GitHub issue #52.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import Any

import pytest
import yaml

from pxeos.models import BootFirmware, ProvisionProfile
from pxeos.plugins.debian import DebianPlugin
from pxeos.plugins.fedora import FedoraPlugin
from pxeos.plugins.suse import SUSEPlugin
from pxeos.plugins.ubuntu import UbuntuPlugin
from pxeos.plugins.windows import WindowsPlugin


# ── Profile helpers ────────────────────────────────────────────────


def _fedora(**overrides: Any) -> ProvisionProfile:
    defaults: dict[str, Any] = dict(
        name="ks-validation",
        os_family="fedora",
        os_version="40",
        arch="x86_64",
        install_url="http://mirror.example.com/fedora/40/x86_64",
        autoinstall_url="http://pxe.example.com/ks/ks-validation",
        packages=["vim", "tmux"],
        post_scripts=["systemctl enable sshd"],
    )
    defaults.update(overrides)
    return ProvisionProfile(**defaults)


def _debian(**overrides: Any) -> ProvisionProfile:
    defaults: dict[str, Any] = dict(
        name="preseed-validation",
        os_family="debian",
        os_version="12",
        arch="amd64",
        install_url="http://deb.debian.org/debian",
        autoinstall_url="http://pxe.example.com/preseed/preseed-validation",
        packages=["vim", "curl"],
        post_scripts=["echo done"],
    )
    defaults.update(overrides)
    return ProvisionProfile(**defaults)


def _ubuntu(**overrides: Any) -> ProvisionProfile:
    defaults: dict[str, Any] = dict(
        name="cloud-init-validation",
        os_family="ubuntu",
        os_version="24.04",
        arch="amd64",
        install_url="http://archive.ubuntu.com/ubuntu",
        autoinstall_url="http://pxe.example.com/autoinstall/cloud-init-validation",
        packages=["vim", "curl"],
        post_scripts=["echo done"],
    )
    defaults.update(overrides)
    return ProvisionProfile(**defaults)


def _windows(**overrides: Any) -> ProvisionProfile:
    defaults: dict[str, Any] = dict(
        name="unattend-validation",
        os_family="windows",
        os_version="2022",
        arch="x86_64",
        firmware=BootFirmware.UEFI,
        install_url="http://pxe.example.com/win/2022",
        autoinstall_url="http://pxe.example.com/unattend/win2022",
        extra={
            "product_key": "",
            "admin_password": "T3st!Pass",
        },
    )
    defaults.update(overrides)
    return ProvisionProfile(**defaults)


def _suse(**overrides: Any) -> ProvisionProfile:
    defaults: dict[str, Any] = dict(
        name="autoyast-validation",
        os_family="suse",
        os_version="15.6",
        arch="x86_64",
        install_url="http://mirror.example.com/suse/15.6",
        autoinstall_url="http://pxe.example.com/autoyast/autoyast-validation",
        packages=["vim", "tmux"],
        post_scripts=["echo done"],
    )
    defaults.update(overrides)
    return ProvisionProfile(**defaults)


# ═══════════════════════════════════════════════════════════════════
#  KICKSTART VALIDATION (Fedora / RHEL / CentOS)
# ═══════════════════════════════════════════════════════════════════


class TestKickstartRequiredSections:
    """Verify the generated kickstart contains all sections Anaconda requires."""

    @pytest.fixture
    def plugin(self) -> FedoraPlugin:
        return FedoraPlugin()

    @pytest.fixture
    def ks_output(self, plugin: FedoraPlugin) -> str:
        return plugin.generate_autoinstall(_fedora())

    def test_packages_section_present(self, ks_output: str) -> None:
        assert "%packages" in ks_output

    def test_packages_section_closed(self, ks_output: str) -> None:
        """Anaconda requires every %packages to be closed with %end."""
        packages_idx = ks_output.index("%packages")
        rest = ks_output[packages_idx:]
        assert "%end" in rest

    def test_post_section_present(self, ks_output: str) -> None:
        assert "%post" in ks_output

    def test_post_section_closed(self, ks_output: str) -> None:
        post_idx = ks_output.index("%post")
        rest = ks_output[post_idx:]
        assert "%end" in rest

    def test_all_sections_closed(self, ks_output: str) -> None:
        """Every %section must have a matching %end."""
        section_re = re.compile(r"^%(packages|pre|post|addon|anaconda)", re.MULTILINE)
        end_re = re.compile(r"^%end", re.MULTILINE)
        sections = section_re.findall(ks_output)
        ends = end_re.findall(ks_output)
        assert len(sections) == len(ends), (
            f"Found {len(sections)} section(s) but {len(ends)} %end(s)"
        )


class TestKickstartRequiredDirectives:
    """Verify mandatory Kickstart directives are present."""

    @pytest.fixture
    def plugin(self) -> FedoraPlugin:
        return FedoraPlugin()

    @pytest.fixture
    def ks_output(self, plugin: FedoraPlugin) -> str:
        return plugin.generate_autoinstall(_fedora())

    def test_url_directive(self, ks_output: str) -> None:
        """Anaconda needs 'url --url=...' to know where to fetch packages."""
        assert re.search(r'^url\s+--url=', ks_output, re.MULTILINE)

    def test_lang_directive(self, ks_output: str) -> None:
        assert re.search(r'^lang\s+\S+', ks_output, re.MULTILINE)

    def test_keyboard_directive(self, ks_output: str) -> None:
        assert re.search(r'^keyboard\s+', ks_output, re.MULTILINE)

    def test_timezone_directive(self, ks_output: str) -> None:
        assert re.search(r'^timezone\s+\S+', ks_output, re.MULTILINE)

    def test_rootpw_directive(self, ks_output: str) -> None:
        assert re.search(r'^rootpw\s+', ks_output, re.MULTILINE)

    def test_bootloader_directive(self, ks_output: str) -> None:
        assert re.search(r'^bootloader\s+', ks_output, re.MULTILINE)

    def test_network_directive(self, ks_output: str) -> None:
        assert re.search(r'^network\s+', ks_output, re.MULTILINE)

    def test_selinux_directive(self, ks_output: str) -> None:
        assert re.search(r'^selinux\s+--', ks_output, re.MULTILINE)

    def test_firewall_directive(self, ks_output: str) -> None:
        assert re.search(r'^firewall\s+--', ks_output, re.MULTILINE)

    def test_reboot_or_halt_directive(self, ks_output: str) -> None:
        assert re.search(r'^(reboot|halt|poweroff|shutdown)', ks_output, re.MULTILINE)

    def test_partitioning_directive(self, ks_output: str) -> None:
        """Either autopart or explicit part/logvol directives required."""
        assert re.search(r'^(autopart|part |clearpart)', ks_output, re.MULTILINE)


class TestKickstartSyntaxRules:
    """Verify Kickstart syntax constraints that Anaconda enforces."""

    @pytest.fixture
    def plugin(self) -> FedoraPlugin:
        return FedoraPlugin()

    def test_no_empty_url(self, plugin: FedoraPlugin) -> None:
        """url directive must contain an actual URL."""
        output = plugin.generate_autoinstall(_fedora())
        match = re.search(r'^url\s+--url="([^"]*)"', output, re.MULTILINE)
        assert match is not None
        assert match.group(1) != ""

    def test_packages_contains_at_least_one_group(self, plugin: FedoraPlugin) -> None:
        """Kickstart typically includes at least one package group (@...)."""
        output = plugin.generate_autoinstall(_fedora())
        packages_section = output[output.index("%packages"):output.index("%end", output.index("%packages"))]
        assert "@" in packages_section, "Expected at least one package group (@...)"

    def test_version_header(self, plugin: FedoraPlugin) -> None:
        """Kickstart files should start with #version=."""
        output = plugin.generate_autoinstall(_fedora())
        assert output.strip().startswith("#version=")

    def test_custom_partitioning_syntax(self, plugin: FedoraPlugin) -> None:
        """Custom partitioning with LVM should produce valid directives."""
        profile = _fedora(
            disk={
                "method": "custom",
                "device": "/dev/sda",
                "partitions": [
                    {"mount": "/boot", "fstype": "xfs", "size": 1024},
                    {"type": "pv", "disk": "sda", "size": 1, "grow": True},
                    {"type": "volgroup", "name": "vg_system", "pv": 1},
                    {"type": "logvol", "mount": "/", "vg": "vg_system",
                     "fstype": "xfs", "size": 8192, "name": "lv_root", "grow": True},
                ],
            },
        )
        output = plugin.generate_autoinstall(profile)
        assert "clearpart --all --initlabel" in output
        assert re.search(r'^part\s+', output, re.MULTILINE)
        assert "volgroup" in output
        assert "logvol" in output

    def test_uefi_bootloader_has_boot_drive(self, plugin: FedoraPlugin) -> None:
        """UEFI kickstart should specify --boot-drive in bootloader."""
        profile = _fedora(firmware=BootFirmware.UEFI)
        output = plugin.generate_autoinstall(profile)
        assert "--boot-drive=" in output


class TestKickstartVariations:
    """Validate kickstart under different profile configurations."""

    @pytest.fixture
    def plugin(self) -> FedoraPlugin:
        return FedoraPlugin()

    def test_selinux_disabled(self, plugin: FedoraPlugin) -> None:
        profile = _fedora(extra={"selinux": "disabled"})
        output = plugin.generate_autoinstall(profile)
        assert "selinux --disabled" in output

    def test_selinux_permissive(self, plugin: FedoraPlugin) -> None:
        profile = _fedora(extra={"selinux": "permissive"})
        output = plugin.generate_autoinstall(profile)
        assert "selinux --permissive" in output

    def test_firewall_disabled(self, plugin: FedoraPlugin) -> None:
        profile = _fedora(extra={"firewall": False})
        output = plugin.generate_autoinstall(profile)
        assert "firewall --disabled" in output

    def test_halt_instead_of_reboot(self, plugin: FedoraPlugin) -> None:
        profile = _fedora(extra={"reboot": False})
        output = plugin.generate_autoinstall(profile)
        assert "halt" in output
        assert "reboot" not in output.split("halt")[0].split("\n")[-1]

    def test_static_network(self, plugin: FedoraPlugin) -> None:
        profile = _fedora(
            network={
                "bootproto": "static",
                "device": "ens3",
                "ip": "10.0.0.5",
                "netmask": "255.255.255.0",
                "gateway": "10.0.0.1",
                "hostname": "static-host",
                "nameservers": ["8.8.8.8", "1.1.1.1"],
            },
        )
        output = plugin.generate_autoinstall(profile)
        assert "--bootproto=static" in output
        assert "--device=ens3" in output
        assert "--ip=10.0.0.5" in output
        assert "--hostname=static-host" in output

    def test_rhel_version_valid(self, plugin: FedoraPlugin) -> None:
        """RHEL versions use the same kickstart format."""
        for ver in ("8", "9", "10"):
            profile = _fedora(os_version=ver)
            output = plugin.generate_autoinstall(profile)
            assert "#version=RHEL" in output
            assert "%packages" in output


# ═══════════════════════════════════════════════════════════════════
#  PRESEED VALIDATION (Debian)
# ═══════════════════════════════════════════════════════════════════


class TestPreseedKeyValueFormat:
    """Verify preseed lines follow 'd-i component/question type value' format."""

    @pytest.fixture
    def plugin(self) -> DebianPlugin:
        return DebianPlugin()

    @pytest.fixture
    def preseed_output(self, plugin: DebianPlugin) -> str:
        return plugin.generate_autoinstall(_debian())

    def test_all_di_lines_have_correct_format(self, preseed_output: str) -> None:
        """Every d-i line must match: d-i <owner/key> <type> <value>."""
        di_pattern = re.compile(
            r'^d-i\s+[\w\-]+(/[\w\-]+)+\s+'
            r'(string|boolean|select|multiselect|note|password|text)\b',
        )
        for line in preseed_output.splitlines():
            stripped = line.strip()
            if stripped.startswith("d-i "):
                assert di_pattern.match(stripped), (
                    f"Malformed preseed line: {stripped!r}"
                )

    def test_tasksel_lines_have_correct_format(self, preseed_output: str) -> None:
        """tasksel lines must match: tasksel <owner/key> <type> <value>."""
        tasksel_pattern = re.compile(
            r'^tasksel\s+[\w\-]+/[\w\-]+\s+(multiselect|select)\s+',
        )
        for line in preseed_output.splitlines():
            stripped = line.strip()
            if stripped.startswith("tasksel "):
                assert tasksel_pattern.match(stripped), (
                    f"Malformed tasksel line: {stripped!r}"
                )

    def test_popularity_contest_lines_format(self, preseed_output: str) -> None:
        """popularity-contest lines follow same pattern as d-i."""
        for line in preseed_output.splitlines():
            stripped = line.strip()
            if stripped.startswith("popularity-contest "):
                assert re.match(
                    r'^popularity-contest\s+[\w\-]+/[\w\-]+\s+(boolean|string)\s+',
                    stripped,
                ), f"Malformed popularity-contest line: {stripped!r}"


class TestPreseedRequiredDirectives:
    """Verify essential preseed directives are present."""

    @pytest.fixture
    def plugin(self) -> DebianPlugin:
        return DebianPlugin()

    @pytest.fixture
    def preseed_output(self, plugin: DebianPlugin) -> str:
        return plugin.generate_autoinstall(_debian())

    def test_locale(self, preseed_output: str) -> None:
        assert "debian-installer/locale" in preseed_output

    def test_keyboard(self, preseed_output: str) -> None:
        assert "keyboard-configuration/xkb-keymap" in preseed_output

    def test_network_interface(self, preseed_output: str) -> None:
        assert "netcfg/choose_interface" in preseed_output

    def test_hostname(self, preseed_output: str) -> None:
        assert "netcfg/get_hostname" in preseed_output

    def test_domain(self, preseed_output: str) -> None:
        assert "netcfg/get_domain" in preseed_output

    def test_mirror_hostname(self, preseed_output: str) -> None:
        assert "mirror/http/hostname" in preseed_output

    def test_mirror_directory(self, preseed_output: str) -> None:
        assert "mirror/http/directory" in preseed_output

    def test_user_account(self, preseed_output: str) -> None:
        assert "passwd/username" in preseed_output

    def test_timezone(self, preseed_output: str) -> None:
        assert "time/zone" in preseed_output

    def test_partitioning_method(self, preseed_output: str) -> None:
        assert "partman-auto/method" in preseed_output

    def test_partitioning_disk(self, preseed_output: str) -> None:
        assert "partman-auto/disk" in preseed_output

    def test_grub_installer(self, preseed_output: str) -> None:
        assert "grub-installer/bootdev" in preseed_output

    def test_finish_install(self, preseed_output: str) -> None:
        assert "finish-install/reboot_in_progress" in preseed_output

    def test_package_selection(self, preseed_output: str) -> None:
        assert "pkgsel/include" in preseed_output

    def test_apt_setup(self, preseed_output: str) -> None:
        assert "apt-setup/services-select" in preseed_output


class TestPreseedBooleanValues:
    """Verify boolean preseed values use 'true' or 'false' (not yes/no)."""

    @pytest.fixture
    def plugin(self) -> DebianPlugin:
        return DebianPlugin()

    @pytest.fixture
    def preseed_output(self, plugin: DebianPlugin) -> str:
        return plugin.generate_autoinstall(_debian())

    def test_boolean_values_correct(self, preseed_output: str) -> None:
        """d-i boolean values must be 'true' or 'false'."""
        bool_pattern = re.compile(
            r'^d-i\s+\S+\s+boolean\s+(.+)$', re.MULTILINE,
        )
        for match in bool_pattern.finditer(preseed_output):
            value = match.group(1).strip()
            assert value in ("true", "false"), (
                f"Expected 'true' or 'false', got {value!r}"
            )


class TestPreseedVariations:
    """Validate preseed under different configurations."""

    @pytest.fixture
    def plugin(self) -> DebianPlugin:
        return DebianPlugin()

    def test_static_network(self, plugin: DebianPlugin) -> None:
        profile = _debian(
            network={
                "bootproto": "static",
                "device": "eth0",
                "ip": "192.168.1.10",
                "netmask": "255.255.255.0",
                "gateway": "192.168.1.1",
                "hostname": "deb-static",
                "domain": "example.com",
                "nameservers": ["8.8.8.8"],
            },
        )
        output = plugin.generate_autoinstall(profile)
        assert "netcfg/disable_autoconfig boolean true" in output
        assert "netcfg/get_ipaddress" in output
        assert "netcfg/confirm_static boolean true" in output

    def test_lvm_partitioning(self, plugin: DebianPlugin) -> None:
        output = plugin.generate_autoinstall(_debian())
        assert "partman-auto/method string lvm" in output
        assert "partman-lvm/confirm boolean true" in output

    def test_regular_partitioning(self, plugin: DebianPlugin) -> None:
        profile = _debian(disk={"method": "regular", "device": "/dev/sda"})
        output = plugin.generate_autoinstall(profile)
        assert "partman-auto/method string regular" in output

    def test_uefi_efi_partition(self, plugin: DebianPlugin) -> None:
        profile = _debian(firmware=BootFirmware.UEFI)
        output = plugin.generate_autoinstall(profile)
        assert "partman-efi/non_efi_system" in output

    def test_late_command_with_post_scripts(self, plugin: DebianPlugin) -> None:
        profile = _debian(post_scripts=["apt-get update", "apt-get upgrade -y"])
        output = plugin.generate_autoinstall(profile)
        assert "preseed/late_command" in output
        assert "apt-get update" in output


# ═══════════════════════════════════════════════════════════════════
#  CLOUD-INIT VALIDATION (Ubuntu autoinstall)
# ═══════════════════════════════════════════════════════════════════


class TestCloudInitYAMLValidity:
    """Verify cloud-init output is valid YAML."""

    @pytest.fixture
    def plugin(self) -> UbuntuPlugin:
        return UbuntuPlugin()

    @pytest.fixture
    def ci_output(self, plugin: UbuntuPlugin) -> str:
        return plugin.generate_autoinstall(_ubuntu())

    def test_parses_as_valid_yaml(self, ci_output: str) -> None:
        """The output must parse without YAML errors."""
        parsed = yaml.safe_load(ci_output)
        assert parsed is not None

    def test_not_empty_document(self, ci_output: str) -> None:
        parsed = yaml.safe_load(ci_output)
        assert isinstance(parsed, dict)
        assert len(parsed) > 0


class TestCloudInitSchema:
    """Verify cloud-init autoinstall has the required schema keys."""

    @pytest.fixture
    def plugin(self) -> UbuntuPlugin:
        return UbuntuPlugin()

    @pytest.fixture
    def parsed(self, plugin: UbuntuPlugin) -> dict:
        output = plugin.generate_autoinstall(_ubuntu())
        return yaml.safe_load(output)

    def test_has_autoinstall_key(self, parsed: dict) -> None:
        assert "autoinstall" in parsed

    def test_autoinstall_has_version(self, parsed: dict) -> None:
        ai = parsed["autoinstall"]
        assert "version" in ai
        assert isinstance(ai["version"], int)
        assert ai["version"] >= 1

    def test_autoinstall_has_identity(self, parsed: dict) -> None:
        ai = parsed["autoinstall"]
        assert "identity" in ai

    def test_identity_has_hostname(self, parsed: dict) -> None:
        identity = parsed["autoinstall"]["identity"]
        assert "hostname" in identity
        assert isinstance(identity["hostname"], str)
        assert len(identity["hostname"]) > 0

    def test_identity_has_username(self, parsed: dict) -> None:
        identity = parsed["autoinstall"]["identity"]
        assert "username" in identity

    def test_identity_has_password(self, parsed: dict) -> None:
        identity = parsed["autoinstall"]["identity"]
        assert "password" in identity

    def test_autoinstall_has_locale(self, parsed: dict) -> None:
        ai = parsed["autoinstall"]
        assert "locale" in ai

    def test_autoinstall_has_keyboard(self, parsed: dict) -> None:
        ai = parsed["autoinstall"]
        assert "keyboard" in ai
        assert "layout" in ai["keyboard"]

    def test_autoinstall_has_ssh(self, parsed: dict) -> None:
        ai = parsed["autoinstall"]
        assert "ssh" in ai
        assert "install-server" in ai["ssh"]

    def test_autoinstall_has_storage(self, parsed: dict) -> None:
        ai = parsed["autoinstall"]
        assert "storage" in ai

    def test_autoinstall_has_shutdown(self, parsed: dict) -> None:
        ai = parsed["autoinstall"]
        assert "shutdown" in ai
        assert ai["shutdown"] in ("reboot", "poweroff")

    def test_autoinstall_has_updates(self, parsed: dict) -> None:
        ai = parsed["autoinstall"]
        assert "updates" in ai


class TestCloudInitPackages:
    """Verify cloud-init packages section."""

    @pytest.fixture
    def plugin(self) -> UbuntuPlugin:
        return UbuntuPlugin()

    def test_packages_listed(self, plugin: UbuntuPlugin) -> None:
        output = plugin.generate_autoinstall(_ubuntu(packages=["nginx", "git"]))
        parsed = yaml.safe_load(output)
        ai = parsed["autoinstall"]
        assert "packages" in ai
        assert "nginx" in ai["packages"]
        assert "git" in ai["packages"]

    def test_no_packages_key_when_empty(self, plugin: UbuntuPlugin) -> None:
        output = plugin.generate_autoinstall(_ubuntu(packages=[]))
        parsed = yaml.safe_load(output)
        ai = parsed["autoinstall"]
        # When no packages, the key should be absent or empty
        if "packages" in ai:
            assert ai["packages"] is None or ai["packages"] == []


class TestCloudInitVariations:
    """Validate cloud-init under different configurations."""

    @pytest.fixture
    def plugin(self) -> UbuntuPlugin:
        return UbuntuPlugin()

    def test_static_network(self, plugin: UbuntuPlugin) -> None:
        profile = _ubuntu(
            network={
                "bootproto": "static",
                "device": "ens3",
                "ip": "10.0.0.5",
                "prefix": "24",
                "gateway": "10.0.0.1",
                "nameservers": ["8.8.8.8"],
            },
        )
        output = plugin.generate_autoinstall(profile)
        parsed = yaml.safe_load(output)
        ai = parsed["autoinstall"]
        assert "network" in ai
        network = ai["network"]
        assert network["version"] == 2

    def test_lvm_storage(self, plugin: UbuntuPlugin) -> None:
        output = plugin.generate_autoinstall(_ubuntu(disk={"method": "lvm"}))
        parsed = yaml.safe_load(output)
        storage = parsed["autoinstall"]["storage"]
        assert "layout" in storage
        assert storage["layout"]["name"] == "lvm"

    def test_direct_storage(self, plugin: UbuntuPlugin) -> None:
        output = plugin.generate_autoinstall(_ubuntu(disk={"method": "direct"}))
        parsed = yaml.safe_load(output)
        storage = parsed["autoinstall"]["storage"]
        assert storage["layout"]["name"] == "direct"

    def test_ssh_authorized_keys(self, plugin: UbuntuPlugin) -> None:
        profile = _ubuntu(
            extra={"ssh_authorized_keys": ["ssh-ed25519 AAAA... user@host"]},
        )
        output = plugin.generate_autoinstall(profile)
        parsed = yaml.safe_load(output)
        ssh = parsed["autoinstall"]["ssh"]
        assert "authorized-keys" in ssh
        assert len(ssh["authorized-keys"]) == 1

    def test_late_commands(self, plugin: UbuntuPlugin) -> None:
        profile = _ubuntu(post_scripts=["apt-get update"])
        output = plugin.generate_autoinstall(profile)
        parsed = yaml.safe_load(output)
        ai = parsed["autoinstall"]
        assert "late-commands" in ai
        assert len(ai["late-commands"]) > 0

    def test_cloud_config_header(self, plugin: UbuntuPlugin) -> None:
        """Cloud-init files should start with #cloud-config."""
        output = plugin.generate_autoinstall(_ubuntu())
        assert output.strip().startswith("#cloud-config")


# ═══════════════════════════════════════════════════════════════════
#  AUTOUNATTEND.XML VALIDATION (Windows)
# ═══════════════════════════════════════════════════════════════════


class TestUnattendXMLWellFormedness:
    """Verify unattend.xml is well-formed XML."""

    @pytest.fixture
    def plugin(self) -> WindowsPlugin:
        return WindowsPlugin()

    @pytest.fixture
    def xml_output(self, plugin: WindowsPlugin) -> str:
        return plugin.generate_autoinstall(_windows())

    def test_parses_as_xml(self, xml_output: str) -> None:
        """Must parse without XML errors."""
        root = ET.fromstring(xml_output)
        assert root is not None

    def test_xml_declaration(self, xml_output: str) -> None:
        """Should start with <?xml ...?>."""
        assert xml_output.strip().startswith("<?xml")

    def test_root_element_is_unattend(self, xml_output: str) -> None:
        root = ET.fromstring(xml_output)
        # Namespace-aware: tag is {namespace}unattend
        local_name = root.tag.split("}")[-1] if "}" in root.tag else root.tag
        assert local_name == "unattend"


class TestUnattendRequiredPasses:
    """Verify required Windows Setup passes are present."""

    NS = {"u": "urn:schemas-microsoft-com:unattend"}

    @pytest.fixture
    def plugin(self) -> WindowsPlugin:
        return WindowsPlugin()

    @pytest.fixture
    def root(self, plugin: WindowsPlugin) -> ET.Element:
        output = plugin.generate_autoinstall(_windows())
        return ET.fromstring(output)

    def test_has_windowspe_pass(self, root: ET.Element) -> None:
        passes = [s.get("pass") for s in root.findall("u:settings", self.NS)]
        assert "windowsPE" in passes

    def test_has_specialize_pass(self, root: ET.Element) -> None:
        passes = [s.get("pass") for s in root.findall("u:settings", self.NS)]
        assert "specialize" in passes

    def test_has_oobe_pass(self, root: ET.Element) -> None:
        passes = [s.get("pass") for s in root.findall("u:settings", self.NS)]
        assert "oobeSystem" in passes


class TestUnattendRequiredComponents:
    """Verify required components within each pass."""

    NS = {"u": "urn:schemas-microsoft-com:unattend"}

    @pytest.fixture
    def plugin(self) -> WindowsPlugin:
        return WindowsPlugin()

    @pytest.fixture
    def root(self, plugin: WindowsPlugin) -> ET.Element:
        output = plugin.generate_autoinstall(_windows())
        return ET.fromstring(output)

    def _get_pass(self, root: ET.Element, pass_name: str) -> ET.Element:
        for s in root.findall("u:settings", self.NS):
            if s.get("pass") == pass_name:
                return s
        pytest.fail(f"Pass {pass_name!r} not found")

    def _component_names(self, pass_elem: ET.Element) -> list[str]:
        return [
            c.get("name", "")
            for c in pass_elem.findall("u:component", self.NS)
        ]

    def test_windowspe_has_setup(self, root: ET.Element) -> None:
        pe = self._get_pass(root, "windowsPE")
        names = self._component_names(pe)
        assert "Microsoft-Windows-Setup" in names

    def test_windowspe_has_intl(self, root: ET.Element) -> None:
        pe = self._get_pass(root, "windowsPE")
        names = self._component_names(pe)
        assert "Microsoft-Windows-International-Core-WinPE" in names

    def test_specialize_has_shell_setup(self, root: ET.Element) -> None:
        spec = self._get_pass(root, "specialize")
        names = self._component_names(spec)
        assert "Microsoft-Windows-Shell-Setup" in names

    def test_oobe_has_shell_setup(self, root: ET.Element) -> None:
        oobe = self._get_pass(root, "oobeSystem")
        names = self._component_names(oobe)
        assert "Microsoft-Windows-Shell-Setup" in names

    def test_oobe_has_intl(self, root: ET.Element) -> None:
        oobe = self._get_pass(root, "oobeSystem")
        names = self._component_names(oobe)
        assert "Microsoft-Windows-International-Core" in names


class TestUnattendDiskConfiguration:
    """Verify disk configuration structure in unattend.xml."""

    @pytest.fixture
    def plugin(self) -> WindowsPlugin:
        return WindowsPlugin()

    def _raw(self, plugin: WindowsPlugin, **overrides: Any) -> str:
        return plugin.generate_autoinstall(_windows(**overrides))

    def test_uefi_has_efi_partition(self, plugin: WindowsPlugin) -> None:
        xml_str = self._raw(plugin, firmware=BootFirmware.UEFI)
        assert "<Type>EFI</Type>" in xml_str

    def test_uefi_has_msr_partition(self, plugin: WindowsPlugin) -> None:
        xml_str = self._raw(plugin, firmware=BootFirmware.UEFI)
        assert "<Type>MSR</Type>" in xml_str

    def test_bios_has_active_partition(self, plugin: WindowsPlugin) -> None:
        xml_str = self._raw(plugin, firmware=BootFirmware.BIOS)
        assert "<Active>true</Active>" in xml_str

    def test_disk_wipe_enabled(self, plugin: WindowsPlugin) -> None:
        xml_str = self._raw(plugin)
        assert "<WillWipeDisk>true</WillWipeDisk>" in xml_str

    def test_ntfs_windows_partition(self, plugin: WindowsPlugin) -> None:
        xml_str = self._raw(plugin)
        assert "<Format>NTFS</Format>" in xml_str


class TestUnattendOOBE:
    """Verify OOBE settings for unattended Windows install."""

    NS = {"u": "urn:schemas-microsoft-com:unattend"}

    @pytest.fixture
    def plugin(self) -> WindowsPlugin:
        return WindowsPlugin()

    @pytest.fixture
    def xml_str(self, plugin: WindowsPlugin) -> str:
        return plugin.generate_autoinstall(_windows())

    def test_eula_accepted(self, xml_str: str) -> None:
        assert "<AcceptEula>true</AcceptEula>" in xml_str

    def test_hide_eula_page(self, xml_str: str) -> None:
        assert "<HideEULAPage>true</HideEULAPage>" in xml_str

    def test_skip_oobe(self, xml_str: str) -> None:
        assert "<SkipMachineOOBE>true</SkipMachineOOBE>" in xml_str

    def test_admin_password_present(self, xml_str: str) -> None:
        assert "<AdministratorPassword>" in xml_str


class TestUnattendVariations:
    """Validate unattend.xml under different configurations."""

    @pytest.fixture
    def plugin(self) -> WindowsPlugin:
        return WindowsPlugin()

    def test_windows_10_client(self, plugin: WindowsPlugin) -> None:
        profile = _windows(os_version="10")
        output = plugin.generate_autoinstall(profile)
        root = ET.fromstring(output)
        assert root is not None

    def test_windows_11_client(self, plugin: WindowsPlugin) -> None:
        profile = _windows(os_version="11")
        output = plugin.generate_autoinstall(profile)
        root = ET.fromstring(output)
        assert root is not None

    def test_windows_server_2019(self, plugin: WindowsPlugin) -> None:
        profile = _windows(os_version="2019")
        output = plugin.generate_autoinstall(profile)
        root = ET.fromstring(output)
        assert root is not None
        assert "SERVERSTANDARDCORE" in output

    def test_windows_server_2025(self, plugin: WindowsPlugin) -> None:
        profile = _windows(os_version="2025")
        output = plugin.generate_autoinstall(profile)
        root = ET.fromstring(output)
        assert root is not None

    def test_bios_mode(self, plugin: WindowsPlugin) -> None:
        profile = _windows(firmware=BootFirmware.BIOS)
        output = plugin.generate_autoinstall(profile)
        root = ET.fromstring(output)
        assert root is not None

    def test_with_product_key(self, plugin: WindowsPlugin) -> None:
        profile = _windows(
            extra={
                "product_key": "AAAAA-BBBBB-CCCCC-DDDDD-EEEEE",
                "admin_password": "Pass!",
            },
        )
        output = plugin.generate_autoinstall(profile)
        root = ET.fromstring(output)
        assert root is not None
        assert "AAAAA-BBBBB-CCCCC-DDDDD-EEEEE" in output

    def test_with_post_scripts(self, plugin: WindowsPlugin) -> None:
        profile = _windows(post_scripts=["powershell.exe -File setup.ps1"])
        output = plugin.generate_autoinstall(profile)
        root = ET.fromstring(output)
        assert root is not None
        assert "FirstLogonCommands" in output
        assert "SynchronousCommand" in output

    def test_static_network(self, plugin: WindowsPlugin) -> None:
        profile = _windows(
            network={
                "dhcp": False,
                "address": "10.0.0.5",
                "prefix_length": "24",
                "gateway": "10.0.0.1",
                "nameservers": ["8.8.8.8", "1.1.1.1"],
                "hostname": "win-static",
            },
        )
        output = plugin.generate_autoinstall(profile)
        root = ET.fromstring(output)
        assert root is not None
        assert "Microsoft-Windows-TCPIP" in output
        assert "Microsoft-Windows-DNS-Client" in output


# ═══════════════════════════════════════════════════════════════════
#  AUTOYAST VALIDATION (SUSE)
# ═══════════════════════════════════════════════════════════════════


class TestAutoyastXMLWellFormedness:
    """Verify AutoYaST profile is well-formed XML."""

    @pytest.fixture
    def plugin(self) -> SUSEPlugin:
        return SUSEPlugin()

    @pytest.fixture
    def xml_output(self, plugin: SUSEPlugin) -> str:
        return plugin.generate_autoinstall(_suse())

    def test_parses_as_xml(self, xml_output: str) -> None:
        root = ET.fromstring(xml_output)
        assert root is not None

    def test_xml_declaration(self, xml_output: str) -> None:
        assert xml_output.strip().startswith("<?xml")

    def test_has_doctype(self, xml_output: str) -> None:
        assert "<!DOCTYPE profile>" in xml_output

    def test_root_element_is_profile(self, xml_output: str) -> None:
        root = ET.fromstring(xml_output)
        local_name = root.tag.split("}")[-1] if "}" in root.tag else root.tag
        assert local_name == "profile"


class TestAutoyastRequiredSections:
    """Verify AutoYaST profile contains required YaST2 sections."""

    NS = {
        "y": "http://www.suse.com/1.0/yast2ns",
        "config": "http://www.suse.com/1.0/configns",
    }

    @pytest.fixture
    def plugin(self) -> SUSEPlugin:
        return SUSEPlugin()

    @pytest.fixture
    def root(self, plugin: SUSEPlugin) -> ET.Element:
        output = plugin.generate_autoinstall(_suse())
        return ET.fromstring(output)

    def test_has_general_section(self, root: ET.Element) -> None:
        assert root.find("y:general", self.NS) is not None

    def test_has_language_section(self, root: ET.Element) -> None:
        assert root.find("y:language", self.NS) is not None

    def test_has_keyboard_section(self, root: ET.Element) -> None:
        assert root.find("y:keyboard", self.NS) is not None

    def test_has_timezone_section(self, root: ET.Element) -> None:
        assert root.find("y:timezone", self.NS) is not None

    def test_has_networking_section(self, root: ET.Element) -> None:
        assert root.find("y:networking", self.NS) is not None

    def test_has_users_section(self, root: ET.Element) -> None:
        assert root.find("y:users", self.NS) is not None

    def test_has_partitioning_section(self, root: ET.Element) -> None:
        assert root.find("y:partitioning", self.NS) is not None

    def test_has_software_section(self, root: ET.Element) -> None:
        assert root.find("y:software", self.NS) is not None

    def test_has_services_manager(self, root: ET.Element) -> None:
        assert root.find("y:services-manager", self.NS) is not None

    def test_has_firewall_section(self, root: ET.Element) -> None:
        assert root.find("y:firewall", self.NS) is not None


class TestAutoyastGeneralSection:
    """Verify AutoYaST general/mode settings."""

    @pytest.fixture
    def plugin(self) -> SUSEPlugin:
        return SUSEPlugin()

    @pytest.fixture
    def xml_str(self, plugin: SUSEPlugin) -> str:
        return plugin.generate_autoinstall(_suse())

    def test_confirm_false(self, xml_str: str) -> None:
        """Unattended install must not prompt for confirmation."""
        assert "<confirm" in xml_str
        assert "false" in xml_str

    def test_final_reboot(self, xml_str: str) -> None:
        assert "<final_reboot" in xml_str


class TestAutoyastNetworking:
    """Verify AutoYaST networking section structure."""

    @pytest.fixture
    def plugin(self) -> SUSEPlugin:
        return SUSEPlugin()

    def test_hostname_present(self, plugin: SUSEPlugin) -> None:
        output = plugin.generate_autoinstall(_suse())
        assert "<hostname>" in output

    def test_interface_present(self, plugin: SUSEPlugin) -> None:
        output = plugin.generate_autoinstall(_suse())
        assert "<device>" in output
        assert "<bootproto>" in output

    def test_dhcp_default(self, plugin: SUSEPlugin) -> None:
        output = plugin.generate_autoinstall(_suse())
        assert "<bootproto>dhcp</bootproto>" in output

    def test_static_network(self, plugin: SUSEPlugin) -> None:
        profile = _suse(
            network={
                "bootproto": "static",
                "device": "eth0",
                "ip": "10.0.0.5",
                "netmask": "255.255.255.0",
                "gateway": "10.0.0.1",
                "hostname": "suse-static",
                "nameservers": ["8.8.8.8"],
            },
        )
        output = plugin.generate_autoinstall(profile)
        assert "<bootproto>static</bootproto>" in output
        assert "<ipaddr>" in output


class TestAutoyastSoftware:
    """Verify AutoYaST software/packages section."""

    @pytest.fixture
    def plugin(self) -> SUSEPlugin:
        return SUSEPlugin()

    def test_base_patterns_present(self, plugin: SUSEPlugin) -> None:
        output = plugin.generate_autoinstall(_suse())
        assert "<pattern>base</pattern>" in output

    def test_packages_listed(self, plugin: SUSEPlugin) -> None:
        profile = _suse(packages=["nginx", "git"])
        output = plugin.generate_autoinstall(profile)
        assert "<package>nginx</package>" in output
        assert "<package>git</package>" in output


class TestAutoyastVariations:
    """Validate AutoYaST under different configurations."""

    @pytest.fixture
    def plugin(self) -> SUSEPlugin:
        return SUSEPlugin()

    def test_with_registration(self, plugin: SUSEPlugin) -> None:
        profile = _suse(
            extra={
                "registration_key": "ABCDE-12345",
                "registration_email": "admin@example.com",
            },
        )
        output = plugin.generate_autoinstall(profile)
        root = ET.fromstring(output)
        assert root is not None
        assert "suse_register" in output
        assert "ABCDE-12345" in output

    def test_firewall_disabled(self, plugin: SUSEPlugin) -> None:
        profile = _suse(extra={"firewall": False})
        output = plugin.generate_autoinstall(profile)
        root = ET.fromstring(output)
        assert root is not None
        assert "<enable_firewall" in output

    def test_custom_partitions(self, plugin: SUSEPlugin) -> None:
        profile = _suse(
            disk={
                "device": "/dev/sda",
                "partitions": [
                    {"mount": "/boot", "fstype": "ext4", "size": "1G"},
                    {"mount": "/", "fstype": "btrfs"},
                ],
            },
        )
        output = plugin.generate_autoinstall(profile)
        root = ET.fromstring(output)
        assert root is not None
        assert "<mount>/boot</mount>" in output
        assert "<mount>/</mount>" in output

    def test_uefi_partitioning(self, plugin: SUSEPlugin) -> None:
        profile = _suse(firmware=BootFirmware.UEFI)
        output = plugin.generate_autoinstall(profile)
        root = ET.fromstring(output)
        assert root is not None
        assert "/boot/efi" in output

    def test_post_scripts_in_cdata(self, plugin: SUSEPlugin) -> None:
        profile = _suse(post_scripts=["echo hello"])
        output = plugin.generate_autoinstall(profile)
        root = ET.fromstring(output)
        assert root is not None
        assert "CDATA" in output
        assert "echo hello" in output

    def test_all_supported_versions(self, plugin: SUSEPlugin) -> None:
        """Every supported version produces valid XML."""
        for ver in plugin.supported_versions:
            profile = _suse(os_version=ver)
            output = plugin.generate_autoinstall(profile)
            root = ET.fromstring(output)
            assert root is not None, f"Version {ver} produced invalid XML"


# ═══════════════════════════════════════════════════════════════════
#  CROSS-INSTALLER VALIDATION
# ═══════════════════════════════════════════════════════════════════


class TestCrossInstallerComparison:
    """Cross-cutting tests that compare properties across all installer types."""

    def test_all_autoinstall_filenames_unique_per_family(self) -> None:
        """Each OS family must produce a distinct autoinstall filename."""
        plugins = [
            FedoraPlugin(),
            DebianPlugin(),
            UbuntuPlugin(),
            WindowsPlugin(),
            SUSEPlugin(),
        ]
        filenames = {p.os_family: p.autoinstall_filename() for p in plugins}
        # The values should be unique (different OS families, different files)
        unique_filenames = set(filenames.values())
        assert len(unique_filenames) == len(filenames), (
            f"Filename collision: {filenames}"
        )

    def test_all_generated_configs_are_nonempty(self) -> None:
        """Every plugin must produce a non-empty config."""
        configs = {
            "fedora": FedoraPlugin().generate_autoinstall(_fedora()),
            "debian": DebianPlugin().generate_autoinstall(_debian()),
            "ubuntu": UbuntuPlugin().generate_autoinstall(_ubuntu()),
            "windows": WindowsPlugin().generate_autoinstall(_windows()),
            "suse": SUSEPlugin().generate_autoinstall(_suse()),
        }
        for family, config in configs.items():
            assert len(config.strip()) > 100, (
                f"{family} config is suspiciously short: {len(config)} chars"
            )

    def test_xml_configs_are_well_formed(self) -> None:
        """All XML-based configs (Windows, SUSE) must parse without errors."""
        xml_configs = {
            "windows": WindowsPlugin().generate_autoinstall(_windows()),
            "suse": SUSEPlugin().generate_autoinstall(_suse()),
        }
        for family, config in xml_configs.items():
            try:
                ET.fromstring(config)
            except ET.ParseError as exc:
                pytest.fail(f"{family} XML is malformed: {exc}")

    def test_yaml_configs_are_valid(self) -> None:
        """All YAML-based configs (Ubuntu cloud-init) must parse."""
        yaml_configs = {
            "ubuntu": UbuntuPlugin().generate_autoinstall(_ubuntu()),
        }
        for family, config in yaml_configs.items():
            try:
                parsed = yaml.safe_load(config)
                assert parsed is not None
            except yaml.YAMLError as exc:
                pytest.fail(f"{family} YAML is malformed: {exc}")

    def test_no_config_contains_jinja_artifacts(self) -> None:
        """No rendered config should contain unresolved Jinja2 syntax."""
        configs = {
            "fedora": FedoraPlugin().generate_autoinstall(_fedora()),
            "debian": DebianPlugin().generate_autoinstall(_debian()),
            "ubuntu": UbuntuPlugin().generate_autoinstall(_ubuntu()),
            "windows": WindowsPlugin().generate_autoinstall(_windows()),
            "suse": SUSEPlugin().generate_autoinstall(_suse()),
        }
        jinja_patterns = [
            re.compile(r'\{\{(?!\s*$)'),   # {{ ... }}
            re.compile(r'\{%'),             # {% ... %}
            re.compile(r'undefined'),       # Jinja2 undefined errors
        ]
        for family, config in configs.items():
            for pattern in jinja_patterns:
                matches = pattern.findall(config)
                assert not matches, (
                    f"{family} config contains Jinja2 artifact: "
                    f"{pattern.pattern!r} matched {matches}"
                )

    def test_hostname_appears_in_all_configs(self) -> None:
        """The configured hostname should appear in every generated config."""
        test_cases = [
            ("fedora", FedoraPlugin(), _fedora(network={"hostname": "test-ks"})),
            ("debian", DebianPlugin(), _debian(network={"hostname": "test-preseed"})),
            ("ubuntu", UbuntuPlugin(), _ubuntu(network={"hostname": "test-ci"})),
            ("windows", WindowsPlugin(), _windows(network={"hostname": "test-win"})),
            ("suse", SUSEPlugin(), _suse(network={"hostname": "test-yast"})),
        ]
        for family, plugin, profile in test_cases:
            output = plugin.generate_autoinstall(profile)
            hostname = profile.network["hostname"]
            assert hostname in output, (
                f"{family} config does not contain hostname {hostname!r}"
            )
