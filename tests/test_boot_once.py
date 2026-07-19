"""Tests for boot-once provisioning (issue #19).

Covers:
- ProvisionTracker netboot state management
- ProvisioningEngine local-boot script when netboot is disabled
- REST API endpoints for disable/enable/status
- CLI subcommand argument parsing
- Full boot-once workflow integration
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from pxeos.api import app, init_app
from pxeos.config import PxeOSConfig
from pxeos.engine import LOCAL_BOOT_SCRIPT, ProvisioningEngine
from pxeos.matcher import HostMatcher
from pxeos.models import BootAssets, HostRule
from pxeos.registry import PluginRegistry
from pxeos.state import ProvisionRecord, ProvisionState, ProvisionTracker


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _rule(**kwargs) -> HostRule:
    kwargs.setdefault("profile", "fedora-server")
    kwargs.setdefault("os_family", "fedora")
    kwargs.setdefault("os_version", "41")
    return HostRule(**kwargs)


def _config(tmp_path: Path | None = None) -> PxeOSConfig:
    return PxeOSConfig(
        data_dir=tmp_path or Path("/tmp/pxeos-boot-once-test"),
        server_host="0.0.0.0",
        server_port=8443,
    )


def _boot_assets(**kwargs) -> BootAssets:
    kwargs.setdefault("kernel", "/images/fedora/41/vmlinuz")
    kwargs.setdefault("initrd", "/images/fedora/41/initrd.img")
    kwargs.setdefault("boot_args", ("ip=dhcp",))
    return BootAssets(**kwargs)


def _build_engine(
    matcher_return=None,
    plugin=None,
    config=None,
    tracker=None,
):
    """Build a ProvisioningEngine with mocked collaborators."""
    mock_matcher = MagicMock(spec=HostMatcher)
    mock_matcher.match.return_value = matcher_return

    mock_registry = MagicMock(spec=PluginRegistry)
    if plugin is not None:
        mock_registry.get.return_value = plugin

    cfg = config or _config()
    engine = ProvisioningEngine(
        mock_registry, mock_matcher, cfg, tracker=tracker
    )
    return engine, mock_matcher, mock_registry


# ===========================================================================
# Unit tests: ProvisionTracker netboot methods
# ===========================================================================


class TestProvisionTrackerNetboot:

    def test_is_netboot_enabled_default_true_for_unknown_mac(self):
        """Unknown MACs default to netboot enabled."""
        tracker = ProvisionTracker()
        assert tracker.is_netboot_enabled("aa:bb:cc:dd:ee:ff") is True

    def test_is_netboot_enabled_true_after_register(self):
        """Newly registered hosts have netboot enabled."""
        tracker = ProvisionTracker()
        tracker.register(
            mac="aa:bb:cc:dd:ee:ff",
            profile="test",
            os_family="fedora",
            os_version="41",
        )
        assert tracker.is_netboot_enabled("aa:bb:cc:dd:ee:ff") is True

    def test_disable_netboot(self):
        tracker = ProvisionTracker()
        tracker.register(
            mac="aa:bb:cc:dd:ee:ff",
            profile="test",
            os_family="fedora",
            os_version="41",
        )
        record = tracker.disable_netboot("aa:bb:cc:dd:ee:ff")
        assert record.netboot_enabled is False
        assert tracker.is_netboot_enabled("aa:bb:cc:dd:ee:ff") is False

    def test_enable_netboot_after_disable(self):
        tracker = ProvisionTracker()
        tracker.register(
            mac="aa:bb:cc:dd:ee:ff",
            profile="test",
            os_family="fedora",
            os_version="41",
        )
        tracker.disable_netboot("aa:bb:cc:dd:ee:ff")
        record = tracker.enable_netboot("aa:bb:cc:dd:ee:ff")
        assert record.netboot_enabled is True
        assert tracker.is_netboot_enabled("aa:bb:cc:dd:ee:ff") is True

    def test_disable_netboot_unknown_mac_raises(self):
        """Cannot disable netboot for a MAC that was never registered."""
        tracker = ProvisionTracker()
        with pytest.raises(ValueError, match="No provisioning record"):
            tracker.disable_netboot("ff:ff:ff:ff:ff:ff")

    def test_enable_netboot_unknown_mac_raises(self):
        """Cannot enable netboot for a MAC that was never registered."""
        tracker = ProvisionTracker()
        with pytest.raises(ValueError, match="No provisioning record"):
            tracker.enable_netboot("ff:ff:ff:ff:ff:ff")

    def test_netboot_enabled_field_on_record(self):
        record = ProvisionRecord(
            mac="aa:bb:cc:dd:ee:ff",
            profile="test",
            os_family="fedora",
            os_version="41",
        )
        assert record.netboot_enabled is True

    def test_record_to_dict_includes_netboot(self):
        record = ProvisionRecord(
            mac="aa:bb:cc:dd:ee:ff",
            profile="test",
            os_family="fedora",
            os_version="41",
        )
        d = record.to_dict()
        assert "netboot_enabled" in d
        assert d["netboot_enabled"] is True

    def test_mac_normalisation_case_insensitive(self):
        """MAC lookups should be case-insensitive."""
        tracker = ProvisionTracker()
        tracker.register(
            mac="AA:BB:CC:DD:EE:FF",
            profile="test",
            os_family="fedora",
            os_version="41",
        )
        tracker.disable_netboot("aa:bb:cc:dd:ee:ff")
        assert tracker.is_netboot_enabled("AA:BB:CC:DD:EE:FF") is False


# ===========================================================================
# Unit tests: ProvisioningEngine boot-once in render_ipxe_script
# ===========================================================================


class TestEngineBootOnce:

    def test_returns_local_boot_when_netboot_disabled(self):
        """When netboot is disabled, render_ipxe_script returns the
        local-boot script without consulting the matcher/registry."""
        tracker = ProvisionTracker()
        tracker.register(
            mac="aa:bb:cc:dd:ee:ff",
            profile="test",
            os_family="fedora",
            os_version="41",
        )
        tracker.disable_netboot("aa:bb:cc:dd:ee:ff")

        engine, matcher, registry = _build_engine(tracker=tracker)

        script = engine.render_ipxe_script(mac="aa:bb:cc:dd:ee:ff")

        assert script == LOCAL_BOOT_SCRIPT
        assert script.startswith("#!ipxe")
        assert "exit" in script
        # Matcher and registry should NOT have been called
        matcher.match.assert_not_called()
        registry.get.assert_not_called()

    def test_returns_normal_script_when_netboot_enabled(self):
        """Default (netboot enabled) returns the full iPXE install script."""
        rule = _rule()
        assets = _boot_assets()
        plugin = MagicMock()
        plugin.validate_profile.return_value = []
        plugin.boot_assets.return_value = assets

        tracker = ProvisionTracker()

        engine, _, _ = _build_engine(
            matcher_return=rule, plugin=plugin, tracker=tracker
        )

        script = engine.render_ipxe_script(mac="aa:bb:cc:dd:ee:ff")

        assert script.startswith("#!ipxe")
        assert "kernel /images/fedora/41/vmlinuz" in script
        assert "initrd /images/fedora/41/initrd.img" in script
        assert "\nboot\n" in script
        assert "inst.ks=" in script

    def test_returns_normal_script_for_unknown_mac(self):
        """An unknown MAC (not in tracker) defaults to netboot enabled."""
        rule = _rule()
        assets = _boot_assets()
        plugin = MagicMock()
        plugin.validate_profile.return_value = []
        plugin.boot_assets.return_value = assets

        tracker = ProvisionTracker()

        engine, _, _ = _build_engine(
            matcher_return=rule, plugin=plugin, tracker=tracker
        )

        script = engine.render_ipxe_script(mac="11:22:33:44:55:66")

        assert script.startswith("#!ipxe")
        assert "kernel" in script

    def test_re_enable_netboot_restores_normal_script(self):
        """Disabling then re-enabling netboot gives the normal script."""
        rule = _rule()
        assets = _boot_assets()
        plugin = MagicMock()
        plugin.validate_profile.return_value = []
        plugin.boot_assets.return_value = assets

        tracker = ProvisionTracker()
        tracker.register(
            mac="aa:bb:cc:dd:ee:ff",
            profile="test",
            os_family="fedora",
            os_version="41",
        )
        tracker.disable_netboot("aa:bb:cc:dd:ee:ff")

        engine, _, _ = _build_engine(
            matcher_return=rule, plugin=plugin, tracker=tracker
        )

        # Disabled -> local boot
        script = engine.render_ipxe_script(mac="aa:bb:cc:dd:ee:ff")
        assert script == LOCAL_BOOT_SCRIPT

        # Re-enable -> normal script
        tracker.enable_netboot("aa:bb:cc:dd:ee:ff")
        script = engine.render_ipxe_script(mac="aa:bb:cc:dd:ee:ff")
        assert script != LOCAL_BOOT_SCRIPT
        assert "kernel" in script

    def test_local_boot_script_is_valid_ipxe(self):
        """LOCAL_BOOT_SCRIPT must start with the iPXE shebang."""
        assert LOCAL_BOOT_SCRIPT.startswith("#!ipxe\n")
        assert "exit" in LOCAL_BOOT_SCRIPT


# ===========================================================================
# API tests: netboot control endpoints
# ===========================================================================


@pytest.fixture
def api_setup(tmp_path):
    """Initialize the app with a real registry for API tests."""
    registry = PluginRegistry()
    registry.load_builtins()
    config = PxeOSConfig(
        data_dir=tmp_path / "data",
        distro_root=tmp_path / "distros",
    )
    (tmp_path / "data").mkdir(exist_ok=True)
    (tmp_path / "distros").mkdir(exist_ok=True)
    matcher = HostMatcher([])
    init_app(registry, config, matcher)
    yield


@pytest.fixture
def client(api_setup):
    return TestClient(app)


def _register_mac(client, mac="aa:bb:cc:dd:ee:ff"):
    """Register a MAC in the tracker via a boot request.

    We prime the tracker by calling the boot endpoint with a mocked engine,
    or we can access the engine's tracker directly.
    """
    from pxeos import api as api_mod

    engine = api_mod._engine
    engine.tracker.register(
        mac=mac,
        profile="test-profile",
        os_family="fedora",
        os_version="41",
    )


class TestDisableNetbootAPI:

    def test_disable_netboot_success(self, client):
        _register_mac(client)
        resp = client.post(
            "/api/v1/provision/aa:bb:cc:dd:ee:ff/disable-netboot"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["netboot_enabled"] is False
        assert data["status"] == "netboot disabled"

    def test_disable_netboot_unknown_mac_returns_404(self, client):
        resp = client.post(
            "/api/v1/provision/ff:ff:ff:ff:ff:ff/disable-netboot"
        )
        assert resp.status_code == 404

    def test_disable_netboot_idempotent(self, client):
        """Calling disable twice should not error."""
        _register_mac(client)
        resp1 = client.post(
            "/api/v1/provision/aa:bb:cc:dd:ee:ff/disable-netboot"
        )
        resp2 = client.post(
            "/api/v1/provision/aa:bb:cc:dd:ee:ff/disable-netboot"
        )
        assert resp1.status_code == 200
        assert resp2.status_code == 200
        assert resp2.json()["netboot_enabled"] is False


class TestEnableNetbootAPI:

    def test_enable_netboot_success(self, client):
        _register_mac(client)
        # Disable first
        client.post(
            "/api/v1/provision/aa:bb:cc:dd:ee:ff/disable-netboot"
        )
        # Re-enable
        resp = client.post(
            "/api/v1/provision/aa:bb:cc:dd:ee:ff/enable-netboot"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["netboot_enabled"] is True
        assert data["status"] == "netboot enabled"

    def test_enable_netboot_unknown_mac_returns_404(self, client):
        resp = client.post(
            "/api/v1/provision/ff:ff:ff:ff:ff:ff/enable-netboot"
        )
        assert resp.status_code == 404


class TestNetbootStatusAPI:

    def test_status_default_enabled_for_unknown_mac(self, client):
        resp = client.get(
            "/api/v1/provision/11:22:33:44:55:66/netboot-status"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["netboot_enabled"] is True
        assert data["mac"] == "11:22:33:44:55:66"

    def test_status_after_disable(self, client):
        _register_mac(client)
        client.post(
            "/api/v1/provision/aa:bb:cc:dd:ee:ff/disable-netboot"
        )
        resp = client.get(
            "/api/v1/provision/aa:bb:cc:dd:ee:ff/netboot-status"
        )
        assert resp.status_code == 200
        assert resp.json()["netboot_enabled"] is False

    def test_status_after_enable(self, client):
        _register_mac(client)
        client.post(
            "/api/v1/provision/aa:bb:cc:dd:ee:ff/disable-netboot"
        )
        client.post(
            "/api/v1/provision/aa:bb:cc:dd:ee:ff/enable-netboot"
        )
        resp = client.get(
            "/api/v1/provision/aa:bb:cc:dd:ee:ff/netboot-status"
        )
        assert resp.status_code == 200
        assert resp.json()["netboot_enabled"] is True


# ===========================================================================
# CLI tests: argument parsing for host disable-netboot / enable-netboot
# ===========================================================================


class TestCLINetbootParsing:

    def test_disable_netboot_parser(self):
        from pxeos.cli import _build_parser

        parser = _build_parser()
        args = parser.parse_args([
            "host", "disable-netboot", "aa:bb:cc:dd:ee:ff"
        ])
        assert args.command == "host"
        assert args.host_action == "disable-netboot"
        assert args.mac == "aa:bb:cc:dd:ee:ff"

    def test_enable_netboot_parser(self):
        from pxeos.cli import _build_parser

        parser = _build_parser()
        args = parser.parse_args([
            "host", "enable-netboot", "aa:bb:cc:dd:ee:ff"
        ])
        assert args.command == "host"
        assert args.host_action == "enable-netboot"
        assert args.mac == "aa:bb:cc:dd:ee:ff"


# ===========================================================================
# Integration: full boot-once workflow
# ===========================================================================


class TestBootOnceWorkflow:

    def test_full_workflow_register_boot_disable_reboot(self):
        """Simulate: register -> first boot (PXE) -> disable -> second boot
        (local disk)."""
        tracker = ProvisionTracker()
        rule = _rule(mac="aa:bb:cc:dd:ee:ff")
        assets = _boot_assets()

        plugin = MagicMock()
        plugin.validate_profile.return_value = []
        plugin.boot_assets.return_value = assets

        engine, _, _ = _build_engine(
            matcher_return=rule, plugin=plugin, tracker=tracker
        )

        # Step 1: First PXE boot -> normal install script
        script1 = engine.render_ipxe_script(mac="aa:bb:cc:dd:ee:ff")
        assert script1.startswith("#!ipxe")
        assert "kernel" in script1
        assert script1 != LOCAL_BOOT_SCRIPT

        # Step 2: Provisioning completes, disable netboot
        tracker.disable_netboot("aa:bb:cc:dd:ee:ff")

        # Step 3: Next reboot -> local boot (no PXE install)
        script2 = engine.render_ipxe_script(mac="aa:bb:cc:dd:ee:ff")
        assert script2 == LOCAL_BOOT_SCRIPT

        # Step 4: Re-provision scenario -> re-enable netboot
        tracker.enable_netboot("aa:bb:cc:dd:ee:ff")

        # Step 5: Boots PXE again
        script3 = engine.render_ipxe_script(mac="aa:bb:cc:dd:ee:ff")
        assert script3 != LOCAL_BOOT_SCRIPT
        assert "kernel" in script3

    def test_multiple_hosts_independent_netboot_state(self):
        """Each host's netboot state is independent."""
        tracker = ProvisionTracker()
        rule = _rule()
        assets = _boot_assets()

        plugin = MagicMock()
        plugin.validate_profile.return_value = []
        plugin.boot_assets.return_value = assets

        engine, _, _ = _build_engine(
            matcher_return=rule, plugin=plugin, tracker=tracker
        )

        mac_a = "aa:bb:cc:dd:ee:01"
        mac_b = "aa:bb:cc:dd:ee:02"

        # Boot both -> normal scripts
        script_a1 = engine.render_ipxe_script(mac=mac_a)
        script_b1 = engine.render_ipxe_script(mac=mac_b)
        assert "kernel" in script_a1
        assert "kernel" in script_b1

        # Disable only host A
        tracker.disable_netboot(mac_a)

        # Host A -> local boot, Host B -> still PXE
        script_a2 = engine.render_ipxe_script(mac=mac_a)
        script_b2 = engine.render_ipxe_script(mac=mac_b)
        assert script_a2 == LOCAL_BOOT_SCRIPT
        assert script_b2 != LOCAL_BOOT_SCRIPT
        assert "kernel" in script_b2


class TestProvisionStateTransitions:

    def test_transition_to_complete_sets_completed_at(self):
        tracker = ProvisionTracker()
        tracker.register(
            mac="aa:bb:cc:dd:ee:ff",
            profile="test",
            os_family="fedora",
            os_version="41",
        )
        record = tracker.transition(
            "aa:bb:cc:dd:ee:ff", ProvisionState.COMPLETE
        )
        assert record.state == ProvisionState.COMPLETE
        assert record.completed_at is not None

    def test_transition_unknown_mac_raises(self):
        tracker = ProvisionTracker()
        with pytest.raises(ValueError, match="No provisioning record"):
            tracker.transition("ff:ff:ff:ff:ff:ff", ProvisionState.BOOTING)

    def test_clear_removes_all_records(self):
        tracker = ProvisionTracker()
        tracker.register(
            mac="aa:bb:cc:dd:ee:ff",
            profile="test",
            os_family="fedora",
            os_version="41",
        )
        tracker.clear()
        assert tracker.get("aa:bb:cc:dd:ee:ff") is None
        assert tracker.is_netboot_enabled("aa:bb:cc:dd:ee:ff") is True
