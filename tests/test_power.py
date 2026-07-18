"""Tests for pxeos.power -- PowerDriver ABC, IPMI, Redfish, PowerManager."""

from __future__ import annotations

import json
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from pxeos.power import (
    IPMIDriver,
    PowerDriver,
    PowerError,
    PowerManager,
    RedfishDriver,
)


# ---------------------------------------------------------------------------
# PowerDriver ABC
# ---------------------------------------------------------------------------


class TestPowerDriverABC:

    def test_cannot_instantiate_directly(self):
        with pytest.raises(TypeError):
            PowerDriver()

    def test_concrete_subclass_must_implement_all_methods(self):
        class PartialDriver(PowerDriver):
            def power_on(self):
                return "on"

        with pytest.raises(TypeError):
            PartialDriver()

    def test_complete_subclass_instantiates(self):
        class FullDriver(PowerDriver):
            def power_on(self):
                return "on"
            def power_off(self):
                return "off"
            def power_status(self):
                return "on"
            def set_boot_device(self, device="pxe"):
                return f"set to {device}"

        driver = FullDriver()
        assert driver.power_on() == "on"
        assert driver.power_off() == "off"
        assert driver.power_status() == "on"
        assert driver.set_boot_device("disk") == "set to disk"


# ---------------------------------------------------------------------------
# IPMIDriver
# ---------------------------------------------------------------------------


class TestIPMIDriver:

    def _make_driver(self):
        return IPMIDriver(
            host="192.168.1.100",
            username="admin",
            password="secret",
        )

    @patch("subprocess.run")
    def test_power_on(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="Chassis Power Control: Up/On\n", stderr=""
        )
        driver = self._make_driver()
        result = driver.power_on()
        assert "Up/On" in result
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert "ipmitool" in cmd
        assert "power" in cmd
        assert "on" in cmd

    @patch("subprocess.run")
    def test_power_off(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="Chassis Power Control: Down/Off\n", stderr=""
        )
        driver = self._make_driver()
        result = driver.power_off()
        assert "Down/Off" in result

    @patch("subprocess.run")
    def test_power_status_on(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="Chassis Power is on\n", stderr=""
        )
        driver = self._make_driver()
        assert driver.power_status() == "on"

    @patch("subprocess.run")
    def test_power_status_off(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="Chassis Power is off\n", stderr=""
        )
        driver = self._make_driver()
        assert driver.power_status() == "off"

    @patch("subprocess.run")
    def test_power_status_unknown(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="Chassis Power is ???\n", stderr=""
        )
        driver = self._make_driver()
        assert driver.power_status() == "unknown"

    @patch("subprocess.run")
    def test_set_boot_device_pxe(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="Set Boot Device to pxe\n", stderr=""
        )
        driver = self._make_driver()
        result = driver.set_boot_device("pxe")
        assert "pxe" in result.lower()
        cmd = mock_run.call_args[0][0]
        assert "bootdev" in cmd
        assert "pxe" in cmd

    @patch("subprocess.run")
    def test_set_boot_device_disk(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="Set Boot Device to disk\n", stderr=""
        )
        driver = self._make_driver()
        result = driver.set_boot_device("disk")
        assert "disk" in result.lower()

    def test_set_boot_device_invalid(self):
        driver = self._make_driver()
        with pytest.raises(PowerError, match="unsupported boot device"):
            driver.set_boot_device("cdrom")

    @patch("subprocess.run")
    def test_ipmitool_failure(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="Unable to establish session"
        )
        driver = self._make_driver()
        with pytest.raises(PowerError, match="ipmitool failed"):
            driver.power_on()

    @patch("subprocess.run", side_effect=FileNotFoundError)
    def test_ipmitool_not_found(self, mock_run):
        driver = self._make_driver()
        with pytest.raises(PowerError, match="ipmitool not found"):
            driver.power_on()

    @patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="", timeout=30))
    def test_ipmitool_timeout(self, mock_run):
        driver = self._make_driver()
        with pytest.raises(PowerError, match="timed out"):
            driver.power_on()

    @patch("subprocess.run")
    def test_uses_lanplus_interface(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="ok", stderr=""
        )
        driver = self._make_driver()
        driver.power_status()
        cmd = mock_run.call_args[0][0]
        assert "-I" in cmd
        idx = cmd.index("-I")
        assert cmd[idx + 1] == "lanplus"

    @patch("subprocess.run")
    def test_passes_host_credentials(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="ok", stderr=""
        )
        driver = self._make_driver()
        driver.power_status()
        cmd = mock_run.call_args[0][0]
        assert "-H" in cmd
        assert "192.168.1.100" in cmd
        assert "-U" in cmd
        assert "admin" in cmd
        assert "-P" in cmd
        assert "secret" in cmd


# ---------------------------------------------------------------------------
# RedfishDriver
# ---------------------------------------------------------------------------


class TestRedfishDriver:

    def _make_driver(self):
        return RedfishDriver(
            host="192.168.1.100",
            username="admin",
            password="secret",
        )

    @patch("pxeos.power.urlopen")
    def test_power_on(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.status = 204
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        driver = self._make_driver()
        result = driver.power_on()
        assert "power on" in result.lower()

        # Check the request
        call_args = mock_urlopen.call_args
        req = call_args[0][0]
        assert "ComputerSystem.Reset" in req.full_url
        body = json.loads(req.data)
        assert body["ResetType"] == "On"

    @patch("pxeos.power.urlopen")
    def test_power_off(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.status = 204
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        driver = self._make_driver()
        result = driver.power_off()
        assert "power off" in result.lower()

        req = mock_urlopen.call_args[0][0]
        body = json.loads(req.data)
        assert body["ResetType"] == "ForceOff"

    @patch("pxeos.power.urlopen")
    def test_power_status_on(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.read.return_value = json.dumps(
            {"PowerState": "On"}
        ).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        driver = self._make_driver()
        assert driver.power_status() == "on"

    @patch("pxeos.power.urlopen")
    def test_power_status_off(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.read.return_value = json.dumps(
            {"PowerState": "Off"}
        ).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        driver = self._make_driver()
        assert driver.power_status() == "off"

    @patch("pxeos.power.urlopen")
    def test_set_boot_device_pxe(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.read.return_value = b"{}"
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        driver = self._make_driver()
        result = driver.set_boot_device("pxe")
        assert "pxe" in result

        req = mock_urlopen.call_args[0][0]
        body = json.loads(req.data)
        assert body["Boot"]["BootSourceOverrideTarget"] == "Pxe"

    @patch("pxeos.power.urlopen")
    def test_set_boot_device_disk(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.read.return_value = b"{}"
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        driver = self._make_driver()
        result = driver.set_boot_device("disk")
        assert "disk" in result

        req = mock_urlopen.call_args[0][0]
        body = json.loads(req.data)
        assert body["Boot"]["BootSourceOverrideTarget"] == "Hdd"

    def test_set_boot_device_invalid(self):
        driver = self._make_driver()
        with pytest.raises(PowerError, match="unsupported boot device"):
            driver.set_boot_device("cdrom")

    @patch("pxeos.power.urlopen")
    def test_uses_basic_auth(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.read.return_value = json.dumps(
            {"PowerState": "On"}
        ).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        driver = self._make_driver()
        driver.power_status()

        req = mock_urlopen.call_args[0][0]
        auth_header = req.get_header("Authorization")
        assert auth_header is not None
        assert auth_header.startswith("Basic ")


# ---------------------------------------------------------------------------
# PowerManager
# ---------------------------------------------------------------------------


class TestPowerManager:

    def test_register_and_get_driver(self):
        manager = PowerManager()
        mock_driver = MagicMock(spec=PowerDriver)
        manager.register("aa:bb:cc:dd:ee:ff", mock_driver)
        assert manager.get_driver("aa:bb:cc:dd:ee:ff") is mock_driver

    def test_mac_normalization(self):
        manager = PowerManager()
        mock_driver = MagicMock(spec=PowerDriver)
        manager.register("AA-BB-CC-DD-EE-FF", mock_driver)
        assert manager.get_driver("aa:bb:cc:dd:ee:ff") is mock_driver

    def test_get_driver_not_found(self):
        manager = PowerManager()
        with pytest.raises(PowerError, match="no power driver"):
            manager.get_driver("00:00:00:00:00:00")

    def test_has_driver(self):
        manager = PowerManager()
        mock_driver = MagicMock(spec=PowerDriver)
        manager.register("aa:bb:cc:dd:ee:ff", mock_driver)
        assert manager.has_driver("aa:bb:cc:dd:ee:ff")
        assert not manager.has_driver("00:00:00:00:00:00")

    def test_delegates_power_on(self):
        manager = PowerManager()
        mock_driver = MagicMock(spec=PowerDriver)
        mock_driver.power_on.return_value = "powered on"
        manager.register("aa:bb:cc:dd:ee:ff", mock_driver)
        result = manager.power_on("aa:bb:cc:dd:ee:ff")
        assert result == "powered on"
        mock_driver.power_on.assert_called_once()

    def test_delegates_power_off(self):
        manager = PowerManager()
        mock_driver = MagicMock(spec=PowerDriver)
        mock_driver.power_off.return_value = "powered off"
        manager.register("aa:bb:cc:dd:ee:ff", mock_driver)
        result = manager.power_off("aa:bb:cc:dd:ee:ff")
        assert result == "powered off"

    def test_delegates_power_status(self):
        manager = PowerManager()
        mock_driver = MagicMock(spec=PowerDriver)
        mock_driver.power_status.return_value = "on"
        manager.register("aa:bb:cc:dd:ee:ff", mock_driver)
        assert manager.power_status("aa:bb:cc:dd:ee:ff") == "on"

    def test_delegates_set_boot_device(self):
        manager = PowerManager()
        mock_driver = MagicMock(spec=PowerDriver)
        mock_driver.set_boot_device.return_value = "set to pxe"
        manager.register("aa:bb:cc:dd:ee:ff", mock_driver)
        result = manager.set_boot_device("aa:bb:cc:dd:ee:ff", "pxe")
        assert result == "set to pxe"
        mock_driver.set_boot_device.assert_called_once_with("pxe")

    def test_create_driver_ipmi(self):
        driver = PowerManager.create_driver(
            "ipmi", "192.168.1.100", "admin", "pass"
        )
        assert isinstance(driver, IPMIDriver)

    def test_create_driver_redfish(self):
        driver = PowerManager.create_driver(
            "redfish", "192.168.1.100", "admin", "pass"
        )
        assert isinstance(driver, RedfishDriver)

    def test_create_driver_unknown(self):
        with pytest.raises(PowerError, match="unknown BMC driver"):
            PowerManager.create_driver("wol", "host", "user", "pass")


# ---------------------------------------------------------------------------
# Power CLI commands
# ---------------------------------------------------------------------------


class TestPowerCLI:

    @patch("pxeos.cli._init_stack")
    @patch("pxeos.power.PowerManager.power_on", return_value="powered on")
    def test_power_on_command(self, mock_power_on, mock_init, tmp_path, capsys):
        from pxeos.cli import main
        from pxeos.config import PxeOSConfig
        from pxeos.matcher import HostMatcher
        from pxeos.models import HostRule
        from pxeos.registry import PluginRegistry

        # Create hosts file with BMC config
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        hosts_file = data_dir / "hosts.toml"
        hosts_file.write_text(
            '[[host]]\n'
            'mac = "aa:bb:cc:dd:ee:ff"\n'
            'profile = "test"\n'
            'os_family = "fedora"\n'
            'os_version = "40"\n'
            'bmc_host = "192.168.1.100"\n'
            'bmc_user = "admin"\n'
            'bmc_password = "secret"\n'
            'bmc_driver = "ipmi"\n'
        )

        config = PxeOSConfig(data_dir=data_dir)
        registry = PluginRegistry()
        registry.load_builtins()
        matcher = HostMatcher([])
        mock_init.return_value = (config, registry, matcher)

        result = main(["power", "on", "aa:bb:cc:dd:ee:ff"])
        assert result == 0
        captured = capsys.readouterr()
        assert "power on" in captured.out.lower()

    @patch("pxeos.cli._init_stack")
    def test_power_no_action(self, mock_init, capsys):
        from pxeos.cli import main
        from pxeos.config import PxeOSConfig
        from pxeos.matcher import HostMatcher
        from pxeos.registry import PluginRegistry

        config = PxeOSConfig()
        registry = PluginRegistry()
        matcher = HostMatcher([])
        mock_init.return_value = (config, registry, matcher)

        result = main(["power"])
        assert result == 1


# ---------------------------------------------------------------------------
# Power API endpoints
# ---------------------------------------------------------------------------


class TestPowerAPI:

    @pytest.fixture(autouse=True)
    def _setup_app(self, tmp_path):
        import pxeos.api as api_module

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
        # Reset global power manager
        api_module._power_manager = None
        yield

    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient
        return TestClient(app)

    @patch("pxeos.power.PowerManager.power_on", return_value="powered on")
    @patch("pxeos.power.PowerManager.has_driver", return_value=True)
    @patch("pxeos.power.PowerManager.get_driver")
    def test_power_on_endpoint(self, mock_get, mock_has, mock_on, client):
        mock_driver = MagicMock()
        mock_driver.power_on.return_value = "powered on"
        mock_get.return_value = mock_driver

        resp = client.post("/api/v1/power/aa:bb:cc:dd:ee:ff/on")
        assert resp.status_code == 200
        data = resp.json()
        assert data["mac"] == "aa:bb:cc:dd:ee:ff"
        assert data["action"] == "power_on"

    @patch("pxeos.power.PowerManager.power_status", return_value="on")
    def test_power_status_endpoint(self, mock_status, client):
        resp = client.get("/api/v1/power/aa:bb:cc:dd:ee:ff/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["mac"] == "aa:bb:cc:dd:ee:ff"


# Required imports at module level for fixtures
from pxeos.api import app, init_app
from pxeos.config import PxeOSConfig
from pxeos.matcher import HostMatcher
from pxeos.registry import PluginRegistry
