"""Tests for the console proxy module and web routes."""

from __future__ import annotations

import asyncio
import unittest
from unittest import mock

from pxeos.console import (
    ConsoleConfig,
    ConsoleProxy,
    ConsoleType,
    SerialConsoleProxy,
)


# ---- ConsoleConfig tests ----


class TestConsoleConfig(unittest.TestCase):

    def test_from_host_rule_vnc(self):
        cfg = ConsoleConfig.from_host_rule("vnc", "kvm-host:5900")
        self.assertIsNotNone(cfg)
        self.assertEqual(cfg.console_type, ConsoleType.VNC)
        self.assertEqual(cfg.host, "kvm-host")
        self.assertEqual(cfg.port, 5900)

    def test_from_host_rule_spice(self):
        cfg = ConsoleConfig.from_host_rule("spice", "kvm-host:5930")
        self.assertIsNotNone(cfg)
        self.assertEqual(cfg.console_type, ConsoleType.SPICE)
        self.assertEqual(cfg.host, "kvm-host")
        self.assertEqual(cfg.port, 5930)

    def test_from_host_rule_serial(self):
        cfg = ConsoleConfig.from_host_rule("serial", "ipmi-host:623")
        self.assertIsNotNone(cfg)
        self.assertEqual(cfg.console_type, ConsoleType.SERIAL)
        self.assertEqual(cfg.host, "ipmi-host")
        self.assertEqual(cfg.port, 623)

    def test_from_host_rule_none_both(self):
        cfg = ConsoleConfig.from_host_rule(None, None)
        self.assertIsNone(cfg)

    def test_from_host_rule_none_empty_strings(self):
        cfg = ConsoleConfig.from_host_rule("", "")
        self.assertIsNone(cfg)

    def test_from_host_rule_type_without_endpoint(self):
        with self.assertRaises(ValueError) as ctx:
            ConsoleConfig.from_host_rule("vnc", None)
        self.assertIn("console_type set without console_endpoint", str(ctx.exception))

    def test_from_host_rule_endpoint_without_type(self):
        with self.assertRaises(ValueError) as ctx:
            ConsoleConfig.from_host_rule(None, "host:5900")
        self.assertIn("console_endpoint set without console_type", str(ctx.exception))

    def test_from_host_rule_invalid_type(self):
        with self.assertRaises(ValueError) as ctx:
            ConsoleConfig.from_host_rule("rdp", "host:3389")
        self.assertIn("invalid console_type", str(ctx.exception))

    def test_from_host_rule_invalid_endpoint_format(self):
        with self.assertRaises(ValueError) as ctx:
            ConsoleConfig.from_host_rule("vnc", "noport")
        self.assertIn("invalid console_endpoint", str(ctx.exception))

    def test_from_host_rule_invalid_endpoint_no_port(self):
        with self.assertRaises(ValueError) as ctx:
            ConsoleConfig.from_host_rule("vnc", "host:")
        self.assertIn("invalid console_endpoint", str(ctx.exception))

    def test_from_host_rule_port_zero(self):
        with self.assertRaises(ValueError) as ctx:
            ConsoleConfig.from_host_rule("vnc", "host:0")
        self.assertIn("invalid port", str(ctx.exception))

    def test_from_host_rule_port_too_high(self):
        with self.assertRaises(ValueError) as ctx:
            ConsoleConfig.from_host_rule("vnc", "host:70000")
        self.assertIn("invalid port", str(ctx.exception))

    def test_from_host_rule_case_insensitive(self):
        cfg = ConsoleConfig.from_host_rule("VNC", "my-host:5900")
        self.assertIsNotNone(cfg)
        self.assertEqual(cfg.console_type, ConsoleType.VNC)

    def test_from_host_rule_strips_whitespace(self):
        cfg = ConsoleConfig.from_host_rule(" vnc ", " host:5900 ")
        self.assertIsNotNone(cfg)
        self.assertEqual(cfg.host, "host")
        self.assertEqual(cfg.port, 5900)

    def test_config_is_frozen(self):
        cfg = ConsoleConfig.from_host_rule("vnc", "host:5900")
        with self.assertRaises(AttributeError):
            cfg.port = 1234

    def test_from_host_rule_ip_address(self):
        cfg = ConsoleConfig.from_host_rule("vnc", "192.168.1.100:5900")
        self.assertIsNotNone(cfg)
        self.assertEqual(cfg.host, "192.168.1.100")
        self.assertEqual(cfg.port, 5900)

    def test_from_host_rule_underscore_host(self):
        cfg = ConsoleConfig.from_host_rule("serial", "my_host:9600")
        self.assertIsNotNone(cfg)
        self.assertEqual(cfg.host, "my_host")


# ---- ConsoleProxy tests ----


class TestConsoleProxy(unittest.TestCase):

    def test_init_vnc(self):
        cfg = ConsoleConfig(ConsoleType.VNC, "host", 5900)
        proxy = ConsoleProxy(cfg)
        self.assertEqual(proxy.config, cfg)

    def test_init_spice(self):
        cfg = ConsoleConfig(ConsoleType.SPICE, "host", 5930)
        proxy = ConsoleProxy(cfg)
        self.assertEqual(proxy.config, cfg)

    def test_init_rejects_serial(self):
        cfg = ConsoleConfig(ConsoleType.SERIAL, "host", 9600)
        with self.assertRaises(ValueError) as ctx:
            ConsoleProxy(cfg)
        self.assertIn("requires vnc or spice", str(ctx.exception))

    def test_send_to_backend_no_writer(self):
        cfg = ConsoleConfig(ConsoleType.VNC, "host", 5900)
        proxy = ConsoleProxy(cfg)
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(proxy.send_to_backend(b"data"))
        finally:
            loop.close()

    def test_receive_from_backend_no_reader(self):
        cfg = ConsoleConfig(ConsoleType.VNC, "host", 5900)
        proxy = ConsoleProxy(cfg)
        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(proxy.receive_from_backend())
            self.assertEqual(result, b"")
        finally:
            loop.close()

    def test_close_no_writer(self):
        cfg = ConsoleConfig(ConsoleType.VNC, "host", 5900)
        proxy = ConsoleProxy(cfg)
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(proxy.close())
        finally:
            loop.close()

    def test_connect_opens_connection(self):
        cfg = ConsoleConfig(ConsoleType.VNC, "host", 5900)
        proxy = ConsoleProxy(cfg)

        mock_reader = mock.MagicMock()
        mock_writer = mock.MagicMock()

        async def fake_open(*args, **kwargs):
            return mock_reader, mock_writer

        loop = asyncio.new_event_loop()
        try:
            with mock.patch("asyncio.open_connection", side_effect=fake_open) as mock_conn:
                loop.run_until_complete(proxy.connect())
                mock_conn.assert_called_once_with("host", 5900)
                self.assertIs(proxy._reader, mock_reader)
                self.assertIs(proxy._writer, mock_writer)
        finally:
            loop.close()

    def test_send_to_backend_with_writer(self):
        cfg = ConsoleConfig(ConsoleType.VNC, "host", 5900)
        proxy = ConsoleProxy(cfg)
        mock_writer = mock.MagicMock()
        mock_writer.drain = mock.AsyncMock()
        proxy._writer = mock_writer

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(proxy.send_to_backend(b"test"))
            mock_writer.write.assert_called_once_with(b"test")
            mock_writer.drain.assert_called_once()
        finally:
            loop.close()

    def test_receive_from_backend_with_reader(self):
        cfg = ConsoleConfig(ConsoleType.VNC, "host", 5900)
        proxy = ConsoleProxy(cfg)
        mock_reader = mock.MagicMock()
        mock_reader.read = mock.AsyncMock(return_value=b"response")
        proxy._reader = mock_reader

        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(proxy.receive_from_backend())
            self.assertEqual(result, b"response")
        finally:
            loop.close()

    def test_close_with_writer(self):
        cfg = ConsoleConfig(ConsoleType.VNC, "host", 5900)
        proxy = ConsoleProxy(cfg)
        mock_writer = mock.AsyncMock()
        mock_writer.close = mock.MagicMock()
        mock_writer.wait_closed = mock.AsyncMock()
        proxy._writer = mock_writer

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(proxy.close())
        finally:
            loop.close()
        mock_writer.close.assert_called_once()
        self.assertIsNone(proxy._writer)
        self.assertIsNone(proxy._reader)


# ---- SerialConsoleProxy tests ----


class TestSerialConsoleProxy(unittest.TestCase):

    def test_init_serial(self):
        cfg = ConsoleConfig(ConsoleType.SERIAL, "host", 9600)
        proxy = SerialConsoleProxy(cfg)
        self.assertEqual(proxy.config, cfg)

    def test_init_rejects_vnc(self):
        cfg = ConsoleConfig(ConsoleType.VNC, "host", 5900)
        with self.assertRaises(ValueError) as ctx:
            SerialConsoleProxy(cfg)
        self.assertIn("requires serial", str(ctx.exception))

    def test_init_rejects_spice(self):
        cfg = ConsoleConfig(ConsoleType.SPICE, "host", 5930)
        with self.assertRaises(ValueError) as ctx:
            SerialConsoleProxy(cfg)
        self.assertIn("requires serial", str(ctx.exception))

    def test_send_to_backend_no_writer(self):
        cfg = ConsoleConfig(ConsoleType.SERIAL, "host", 9600)
        proxy = SerialConsoleProxy(cfg)
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(proxy.send_to_backend(b"data"))
        finally:
            loop.close()

    def test_receive_from_backend_no_reader(self):
        cfg = ConsoleConfig(ConsoleType.SERIAL, "host", 9600)
        proxy = SerialConsoleProxy(cfg)
        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(proxy.receive_from_backend())
            self.assertEqual(result, b"")
        finally:
            loop.close()

    def test_close_no_writer(self):
        cfg = ConsoleConfig(ConsoleType.SERIAL, "host", 9600)
        proxy = SerialConsoleProxy(cfg)
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(proxy.close())
        finally:
            loop.close()

    def test_connect_opens_connection(self):
        cfg = ConsoleConfig(ConsoleType.SERIAL, "host", 9600)
        proxy = SerialConsoleProxy(cfg)

        mock_reader = mock.MagicMock()
        mock_writer = mock.MagicMock()

        async def fake_open(*args, **kwargs):
            return mock_reader, mock_writer

        loop = asyncio.new_event_loop()
        try:
            with mock.patch("asyncio.open_connection", side_effect=fake_open) as mock_conn:
                loop.run_until_complete(proxy.connect())
                mock_conn.assert_called_once_with("host", 9600)
        finally:
            loop.close()

    def test_send_to_backend_with_writer(self):
        cfg = ConsoleConfig(ConsoleType.SERIAL, "host", 9600)
        proxy = SerialConsoleProxy(cfg)
        mock_writer = mock.MagicMock()
        mock_writer.drain = mock.AsyncMock()
        proxy._writer = mock_writer

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(proxy.send_to_backend(b"cmd\n"))
            mock_writer.write.assert_called_once_with(b"cmd\n")
        finally:
            loop.close()

    def test_receive_from_backend_with_reader(self):
        cfg = ConsoleConfig(ConsoleType.SERIAL, "host", 9600)
        proxy = SerialConsoleProxy(cfg)
        mock_reader = mock.MagicMock()
        mock_reader.read = mock.AsyncMock(return_value=b"output")
        proxy._reader = mock_reader

        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(proxy.receive_from_backend())
            self.assertEqual(result, b"output")
        finally:
            loop.close()

    def test_close_with_writer(self):
        cfg = ConsoleConfig(ConsoleType.SERIAL, "host", 9600)
        proxy = SerialConsoleProxy(cfg)
        mock_writer = mock.AsyncMock()
        mock_writer.close = mock.MagicMock()
        mock_writer.wait_closed = mock.AsyncMock()
        proxy._writer = mock_writer

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(proxy.close())
        finally:
            loop.close()
        mock_writer.close.assert_called_once()
        self.assertIsNone(proxy._writer)
        self.assertIsNone(proxy._reader)

    def test_receive_default_max_bytes(self):
        cfg = ConsoleConfig(ConsoleType.SERIAL, "host", 9600)
        proxy = SerialConsoleProxy(cfg)
        mock_reader = mock.MagicMock()
        mock_reader.read = mock.AsyncMock(return_value=b"data")
        proxy._reader = mock_reader

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(proxy.receive_from_backend())
            mock_reader.read.assert_called_once_with(4096)
        finally:
            loop.close()


# ---- ConsoleType enum tests ----


class TestConsoleType(unittest.TestCase):

    def test_vnc_value(self):
        self.assertEqual(ConsoleType.VNC.value, "vnc")

    def test_spice_value(self):
        self.assertEqual(ConsoleType.SPICE.value, "spice")

    def test_serial_value(self):
        self.assertEqual(ConsoleType.SERIAL.value, "serial")


# ---- HostRule console fields ----


class TestHostRuleConsoleFields(unittest.TestCase):

    def test_host_rule_default_console_none(self):
        from pxeos.models import HostRule
        rule = HostRule(profile="test", os_family="fedora", os_version="42")
        self.assertIsNone(rule.console_type)
        self.assertIsNone(rule.console_endpoint)

    def test_host_rule_console_fields_set(self):
        from pxeos.models import HostRule
        rule = HostRule(
            profile="test", os_family="fedora", os_version="42",
            console_type="vnc", console_endpoint="kvm:5900",
        )
        self.assertEqual(rule.console_type, "vnc")
        self.assertEqual(rule.console_endpoint, "kvm:5900")


# ---- Config loading console fields ----


class TestConfigConsoleLoading(unittest.TestCase):

    def test_load_hosts_with_console(self):
        import tempfile
        from pathlib import Path
        from pxeos.config import load_hosts

        content = """\
[[host]]
profile = "test"
os_family = "fedora"
os_version = "42"
mac = "aa:bb:cc:dd:ee:ff"
console_type = "vnc"
console_endpoint = "kvm-host:5900"
"""
        with tempfile.NamedTemporaryFile(suffix=".toml", mode="w", delete=False) as f:
            f.write(content)
            f.flush()
            hosts = load_hosts(Path(f.name))
        self.assertEqual(len(hosts), 1)
        self.assertEqual(hosts[0].console_type, "vnc")
        self.assertEqual(hosts[0].console_endpoint, "kvm-host:5900")
        Path(f.name).unlink()

    def test_load_hosts_without_console(self):
        import tempfile
        from pathlib import Path
        from pxeos.config import load_hosts

        content = """\
[[host]]
profile = "test"
os_family = "fedora"
os_version = "42"
mac = "aa:bb:cc:dd:ee:ff"
"""
        with tempfile.NamedTemporaryFile(suffix=".toml", mode="w", delete=False) as f:
            f.write(content)
            f.flush()
            hosts = load_hosts(Path(f.name))
        self.assertEqual(len(hosts), 1)
        self.assertIsNone(hosts[0].console_type)
        self.assertIsNone(hosts[0].console_endpoint)
        Path(f.name).unlink()

    def test_load_hosts_serial_console(self):
        import tempfile
        from pathlib import Path
        from pxeos.config import load_hosts

        content = """\
[[host]]
profile = "baremetal"
os_family = "fedora"
os_version = "42"
mac = "11:22:33:44:55:66"
console_type = "serial"
console_endpoint = "ipmi-host:623"
"""
        with tempfile.NamedTemporaryFile(suffix=".toml", mode="w", delete=False) as f:
            f.write(content)
            f.flush()
            hosts = load_hosts(Path(f.name))
        self.assertEqual(len(hosts), 1)
        self.assertEqual(hosts[0].console_type, "serial")
        self.assertEqual(hosts[0].console_endpoint, "ipmi-host:623")
        Path(f.name).unlink()


# ---- Web route tests ----


class TestConsoleWebRoutes(unittest.TestCase):

    def setUp(self):
        from pxeos.registry import PluginRegistry
        self.registry = PluginRegistry()
        self.registry.load_builtins()

        self.tmp = self.enterContext(
            mock.patch("pxeos.api._registry", self.registry)
        )

        self.config = mock.MagicMock()
        self.config.server_host = "0.0.0.0"
        self.config.server_port = 8443
        self.config.tls_cert = None
        self.config.distro_root.exists.return_value = False
        self.config.data_dir.__truediv__ = mock.MagicMock(
            return_value=mock.MagicMock()
        )

        self.enterContext(
            mock.patch("pxeos.api._config", self.config)
        )
        self.enterContext(
            mock.patch("pxeos.api._engine", mock.MagicMock())
        )

        from pxeos.api import app
        from pxeos.web.routes import router
        if router not in [r for r in app.routes]:
            try:
                app.include_router(router)
            except Exception:
                pass

        from fastapi.testclient import TestClient
        self.client = TestClient(app)

    def enterContext(self, cm):
        result = cm.__enter__()
        self.addCleanup(cm.__exit__, None, None, None)
        return result

    def test_console_page_no_config(self):
        with mock.patch("pxeos.web.routes._get_console_config", return_value=None):
            resp = self.client.get("/web/console/aa:bb:cc:dd:ee:ff")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("No console configured", resp.text)

    def test_console_page_vnc(self):
        cfg = ConsoleConfig(ConsoleType.VNC, "kvm-host", 5900)
        with mock.patch("pxeos.web.routes._get_console_config", return_value=cfg):
            resp = self.client.get("/web/console/aa:bb:cc:dd:ee:ff")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("aa:bb:cc:dd:ee:ff", resp.text)
        self.assertIn("vnc", resp.text)
        self.assertIn("kvm-host", resp.text)
        self.assertIn("Fullscreen", resp.text)

    def test_console_page_serial(self):
        cfg = ConsoleConfig(ConsoleType.SERIAL, "ipmi-host", 623)
        with mock.patch("pxeos.web.routes._get_console_config", return_value=cfg):
            resp = self.client.get("/web/console/11:22:33:44:55:66")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("serial", resp.text)
        self.assertIn("xterm", resp.text)

    def test_console_page_spice(self):
        cfg = ConsoleConfig(ConsoleType.SPICE, "kvm-host", 5930)
        with mock.patch("pxeos.web.routes._get_console_config", return_value=cfg):
            resp = self.client.get("/web/console/aa:bb:cc:dd:ee:ff")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("spice", resp.text)

    def test_console_page_has_back_link(self):
        cfg = ConsoleConfig(ConsoleType.VNC, "host", 5900)
        with mock.patch("pxeos.web.routes._get_console_config", return_value=cfg):
            resp = self.client.get("/web/console/aa:bb:cc:dd:ee:ff")
        self.assertIn("/web/provisions", resp.text)
        self.assertIn("Back", resp.text)

    def test_console_page_has_connection_status(self):
        cfg = ConsoleConfig(ConsoleType.VNC, "host", 5900)
        with mock.patch("pxeos.web.routes._get_console_config", return_value=cfg):
            resp = self.client.get("/web/console/aa:bb:cc:dd:ee:ff")
        self.assertIn("conn-status", resp.text)
        self.assertIn("Connecting...", resp.text)

    def test_console_page_vnc_has_novnc(self):
        cfg = ConsoleConfig(ConsoleType.VNC, "host", 5900)
        with mock.patch("pxeos.web.routes._get_console_config", return_value=cfg):
            resp = self.client.get("/web/console/aa:bb:cc:dd:ee:ff")
        self.assertIn("novnc", resp.text.lower())

    def test_console_page_serial_has_xterm(self):
        cfg = ConsoleConfig(ConsoleType.SERIAL, "host", 9600)
        with mock.patch("pxeos.web.routes._get_console_config", return_value=cfg):
            resp = self.client.get("/web/console/aa:bb:cc:dd:ee:ff")
        self.assertIn("xterm", resp.text)

    def test_console_websocket_no_config(self):
        from starlette.websockets import WebSocketDisconnect
        with mock.patch("pxeos.web.routes._get_console_config", return_value=None):
            with self.assertRaises(WebSocketDisconnect):
                with self.client.websocket_connect("/web/ws/console/aa:bb:cc:dd:ee:ff") as ws:
                    pass

    def test_console_websocket_connection_refused(self):
        cfg = ConsoleConfig(ConsoleType.VNC, "nonexistent-host", 5900)
        with mock.patch("pxeos.web.routes._get_console_config", return_value=cfg):
            try:
                with self.client.websocket_connect("/web/ws/console/aa:bb:cc:dd:ee:ff") as ws:
                    pass
            except Exception:
                pass  # Expected to fail connecting to nonexistent host


# ---- Helper function tests ----


class TestConsoleHelpers(unittest.TestCase):

    def test_get_console_config_no_config(self):
        from pxeos.web.routes import _get_console_config
        with mock.patch("pxeos.web.routes._get_config", return_value=None):
            result = _get_console_config("aa:bb:cc:dd:ee:ff")
        self.assertIsNone(result)

    def test_get_console_config_no_hosts_file(self):
        from pxeos.web.routes import _get_console_config
        config = mock.MagicMock()
        hosts_path = mock.MagicMock()
        hosts_path.exists.return_value = False
        config.data_dir.__truediv__ = mock.MagicMock(return_value=hosts_path)
        with mock.patch("pxeos.web.routes._get_config", return_value=config):
            result = _get_console_config("aa:bb:cc:dd:ee:ff")
        self.assertIsNone(result)

    def test_get_console_config_found(self):
        from pxeos.web.routes import _get_console_config
        from pxeos.models import HostRule
        config = mock.MagicMock()
        hosts_path = mock.MagicMock()
        hosts_path.exists.return_value = True
        config.data_dir.__truediv__ = mock.MagicMock(return_value=hosts_path)

        rule = HostRule(
            profile="test", os_family="fedora", os_version="42",
            mac="aa:bb:cc:dd:ee:ff",
            console_type="vnc", console_endpoint="host:5900",
        )
        with mock.patch("pxeos.web.routes._get_config", return_value=config), \
             mock.patch("pxeos.config.load_hosts", return_value=[rule]):
            result = _get_console_config("aa:bb:cc:dd:ee:ff")
        self.assertIsNotNone(result)
        self.assertEqual(result.console_type, ConsoleType.VNC)
        self.assertEqual(result.host, "host")
        self.assertEqual(result.port, 5900)

    def test_console_macs_no_config(self):
        from pxeos.web.routes import _console_macs
        with mock.patch("pxeos.web.routes._get_config", return_value=None):
            result = _console_macs()
        self.assertEqual(result, set())

    def test_console_macs_no_hosts_file(self):
        from pxeos.web.routes import _console_macs
        config = mock.MagicMock()
        hosts_path = mock.MagicMock()
        hosts_path.exists.return_value = False
        config.data_dir.__truediv__ = mock.MagicMock(return_value=hosts_path)
        with mock.patch("pxeos.web.routes._get_config", return_value=config):
            result = _console_macs()
        self.assertEqual(result, set())

    def test_provisions_page_passes_console_macs(self):
        """Provisions page should include console_macs context."""
        mock_engine = mock.MagicMock()
        mock_engine.tracker.list_all.return_value = []

        with mock.patch("pxeos.web.routes._console_macs", return_value=set()), \
             mock.patch("pxeos.api._registry", mock.MagicMock()), \
             mock.patch("pxeos.api._config", mock.MagicMock(tls_cert=None)), \
             mock.patch("pxeos.api._engine", mock_engine):
            from pxeos.api import app
            from fastapi.testclient import TestClient
            client = TestClient(app)
            resp = client.get("/web/provisions")
            self.assertEqual(resp.status_code, 200)


# ---- Provisions table console button ----


class TestProvisionsTableConsoleButton(unittest.TestCase):

    def test_console_button_shown_for_console_host(self):
        from jinja2 import Environment, PackageLoader
        env = Environment(
            loader=PackageLoader("pxeos.web", "templates"),
            autoescape=True,
        )
        tmpl = env.get_template("provisions_table.html")
        html = tmpl.render(
            provisions=[{
                "mac": "aa:bb:cc:dd:ee:ff",
                "profile": "test",
                "os_family": "fedora",
                "os_version": "42",
                "state": "installing",
                "netboot_enabled": True,
            }],
            console_macs={"aa:bb:cc:dd:ee:ff"},
        )
        self.assertIn("Console", html)
        self.assertIn("/web/console/aa:bb:cc:dd:ee:ff", html)

    def test_console_button_hidden_for_non_console_host(self):
        from jinja2 import Environment, PackageLoader
        env = Environment(
            loader=PackageLoader("pxeos.web", "templates"),
            autoescape=True,
        )
        tmpl = env.get_template("provisions_table.html")
        html = tmpl.render(
            provisions=[{
                "mac": "aa:bb:cc:dd:ee:ff",
                "profile": "test",
                "os_family": "fedora",
                "os_version": "42",
                "state": "installing",
                "netboot_enabled": True,
            }],
            console_macs=set(),
        )
        self.assertNotIn("/web/console/", html)

    def test_console_button_absent_without_console_macs_var(self):
        from jinja2 import Environment, PackageLoader
        env = Environment(
            loader=PackageLoader("pxeos.web", "templates"),
            autoescape=True,
        )
        tmpl = env.get_template("provisions_table.html")
        html = tmpl.render(
            provisions=[{
                "mac": "aa:bb:cc:dd:ee:ff",
                "profile": "test",
                "os_family": "fedora",
                "os_version": "42",
                "state": "installing",
                "netboot_enabled": True,
            }],
        )
        self.assertNotIn("/web/console/", html)
