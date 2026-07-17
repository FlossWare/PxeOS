"""Tests for the ProvisioningEngine."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from pxeos.config import PxeOSConfig
from pxeos.engine import ProvisioningEngine
from pxeos.matcher import HostMatcher
from pxeos.models import BootAssets, BootFirmware, HostRule, ProvisionProfile
from pxeos.registry import PluginRegistry


# ---- helpers ----


def _rule(**kwargs) -> HostRule:
    kwargs.setdefault("profile", "fedora-server")
    kwargs.setdefault("os_family", "fedora")
    kwargs.setdefault("os_version", "41")
    return HostRule(**kwargs)


def _config(tmp_path: Path | None = None) -> PxeOSConfig:
    return PxeOSConfig(
        data_dir=tmp_path or Path("/tmp/pxeos-test"),
        server_host="0.0.0.0",
        server_port=8443,
    )


def _boot_assets(**kwargs) -> BootAssets:
    kwargs.setdefault("kernel", "/images/fedora/41/vmlinuz")
    kwargs.setdefault("initrd", "/images/fedora/41/initrd.img")
    kwargs.setdefault("boot_args", ("ip=dhcp", "rd.live.image"))
    return BootAssets(**kwargs)


def _build_engine(
    matcher_return=None,
    plugin=None,
    config=None,
):
    """Build an engine with fully mocked collaborators."""
    mock_matcher = MagicMock(spec=HostMatcher)
    mock_matcher.match.return_value = matcher_return

    mock_registry = MagicMock(spec=PluginRegistry)
    if plugin is not None:
        mock_registry.get.return_value = plugin

    cfg = config or _config()

    engine = ProvisioningEngine(mock_registry, mock_matcher, cfg)
    return engine, mock_matcher, mock_registry


# ---- provision ----


class TestProvision:

    def test_resolves_rule_and_returns_boot_assets(self):
        rule = _rule()
        assets = _boot_assets()

        plugin = MagicMock()
        plugin.validate_profile.return_value = []
        plugin.boot_assets.return_value = assets

        engine, matcher, registry = _build_engine(
            matcher_return=rule, plugin=plugin
        )

        result = engine.provision(mac="aa:bb:cc:dd:ee:ff")

        matcher.match.assert_called_once()
        registry.get.assert_called_once_with("fedora")
        plugin.validate_profile.assert_called_once()
        plugin.boot_assets.assert_called_once()
        assert result is assets

    def test_raises_when_no_rule_matches(self):
        engine, _, _ = _build_engine(matcher_return=None)

        with pytest.raises(ValueError, match="no matching host rule"):
            engine.provision(mac="aa:bb:cc:dd:ee:ff")

    def test_raises_when_validation_fails(self):
        rule = _rule()
        plugin = MagicMock()
        plugin.validate_profile.return_value = [
            "install_url is required"
        ]

        engine, _, _ = _build_engine(
            matcher_return=rule, plugin=plugin
        )

        with pytest.raises(ValueError, match="invalid profile"):
            engine.provision(mac="aa:bb:cc:dd:ee:ff")


# ---- render_ipxe_script ----


class TestRenderIpxeScript:

    def test_produces_valid_ipxe_script(self):
        rule = _rule(
            profile="fedora-server",
            os_family="fedora",
            os_version="41",
        )
        assets = _boot_assets(
            kernel="/images/fedora/41/vmlinuz",
            initrd="/images/fedora/41/initrd.img",
            boot_args=("ip=dhcp", "rd.live.image"),
        )

        plugin = MagicMock()
        plugin.validate_profile.return_value = []
        plugin.boot_assets.return_value = assets

        engine, _, _ = _build_engine(
            matcher_return=rule, plugin=plugin
        )

        script = engine.render_ipxe_script(mac="aa:bb:cc:dd:ee:ff")

        assert script.startswith("#!ipxe")
        assert "kernel /images/fedora/41/vmlinuz" in script
        assert "initrd /images/fedora/41/initrd.img" in script
        assert "boot " in script
        assert "inst.ks=" in script

    def test_omits_initrd_when_none(self):
        rule = _rule()
        assets = _boot_assets(initrd=None)

        plugin = MagicMock()
        plugin.validate_profile.return_value = []
        plugin.boot_assets.return_value = assets

        engine, _, _ = _build_engine(
            matcher_return=rule, plugin=plugin
        )

        script = engine.render_ipxe_script(mac="aa:bb:cc:dd:ee:ff")

        assert "initrd" not in script


# ---- get_autoinstall ----


class TestGetAutoinstall:

    def test_delegates_to_plugin(self):
        rule = _rule()
        plugin = MagicMock()
        plugin.generate_autoinstall.return_value = (
            "autoinstall content"
        )

        engine, _, _ = _build_engine(
            matcher_return=rule, plugin=plugin
        )

        result = engine.get_autoinstall(mac="aa:bb:cc:dd:ee:ff")

        assert result == "autoinstall content"
        plugin.generate_autoinstall.assert_called_once()
        profile_arg = plugin.generate_autoinstall.call_args[0][0]
        assert isinstance(profile_arg, ProvisionProfile)
        assert profile_arg.os_family == "fedora"


# ---- get_rule ----


class TestGetRule:

    def test_delegates_to_matcher(self):
        rule = _rule()
        engine, matcher, _ = _build_engine(matcher_return=rule)

        result = engine.get_rule(
            mac="aa:bb:cc:dd:ee:ff",
            hostname="web-01",
            subnet="10.0.0.5",
            serial="SN-1",
            groups=["servers"],
            arch="x86_64",
        )

        assert result is rule
        matcher.match.assert_called_once_with(
            mac="aa:bb:cc:dd:ee:ff",
            hostname="web-01",
            subnet="10.0.0.5",
            serial="SN-1",
            groups=["servers"],
            arch="x86_64",
        )

    def test_returns_none_when_no_match(self):
        engine, _, _ = _build_engine(matcher_return=None)
        result = engine.get_rule(mac="11:22:33:44:55:66")
        assert result is None


# ---- profile loading ----


class TestProfileLoading:

    def test_falls_back_to_rule_fields_when_no_toml(self):
        """When no profile TOML exists, engine constructs a
        ProvisionProfile from the rule fields."""
        rule = _rule(
            profile="missing-profile",
            os_family="fedora",
            os_version="41",
        )
        assets = _boot_assets()
        plugin = MagicMock()
        plugin.validate_profile.return_value = []
        plugin.boot_assets.return_value = assets

        engine, _, _ = _build_engine(
            matcher_return=rule, plugin=plugin
        )

        engine.provision(mac="aa:bb:cc:dd:ee:ff")

        profile_arg = plugin.boot_assets.call_args[0][0]
        assert profile_arg.name == "missing-profile"
        assert profile_arg.os_family == "fedora"
        assert profile_arg.os_version == "41"

    def test_rejects_path_traversal_in_profile_name(self):
        rule = _rule(profile="../../etc/passwd")
        assets = _boot_assets()
        plugin = MagicMock()
        plugin.validate_profile.return_value = []
        plugin.boot_assets.return_value = assets

        engine, _, _ = _build_engine(
            matcher_return=rule, plugin=plugin
        )

        with pytest.raises(ValueError, match="invalid profile name"):
            engine.provision(mac="aa:bb:cc:dd:ee:ff")

    def test_rejects_slash_in_profile_name(self):
        rule = _rule(profile="sub/dir")
        assets = _boot_assets()
        plugin = MagicMock()
        plugin.validate_profile.return_value = []
        plugin.boot_assets.return_value = assets

        engine, _, _ = _build_engine(
            matcher_return=rule, plugin=plugin
        )

        with pytest.raises(ValueError, match="invalid profile name"):
            engine.provision(mac="aa:bb:cc:dd:ee:ff")
