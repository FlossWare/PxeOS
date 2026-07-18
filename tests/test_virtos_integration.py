"""Tests for VirtOS integration: bridge script, discovery, proxy configs."""

from __future__ import annotations

import json
import textwrap
from pathlib import Path
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from pxeos.api import app, init_app
from pxeos.config import PxeOSConfig, load_config
from pxeos.discovery import (
    DEFAULT_SERVICE_NAME,
    SERVICE_TYPE,
    get_service_info,
)
from pxeos.matcher import HostMatcher
from pxeos.registry import PluginRegistry

# Import bridge script functions
import importlib
import importlib.machinery
import importlib.util
import sys


def _import_bridge():
    """Import the bridge script as a module.

    The bridge file has no .py extension, so we use
    SourceFileLoader directly.
    """
    bridge_path = str(
        Path(__file__).parent.parent / "contrib" / "virtos" / "virtos-pxeos"
    )
    loader = importlib.machinery.SourceFileLoader("virtos_pxeos", bridge_path)
    spec = importlib.util.spec_from_loader("virtos_pxeos", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


bridge = _import_bridge()


# ---------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------


@pytest.fixture(autouse=True)
def _setup_app(tmp_path):
    """Initialize the FastAPI app with real registry and config."""
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
def client():
    return TestClient(app)


@pytest.fixture
def pxeos_config_file(tmp_path) -> Path:
    """Create a sample PxeOS TOML config file."""
    config_path = tmp_path / "pxeos.toml"
    config_path.write_text(textwrap.dedent("""\
        [server]
        host = "10.0.0.5"
        port = 9443
        tls_cert = "/etc/pxeos/cert.pem"

        [paths]
        data_dir = "/var/lib/pxeos"

        [discovery]
        enabled = true
        service_name = "my-pxeos"
    """))
    return config_path


# ---------------------------------------------------------------
# Bridge script: discover_pxeos
# ---------------------------------------------------------------


class TestBridgeDiscoverExplicitArgs:
    """Test bridge discovery with explicit host/port arguments."""

    def test_explicit_host_port(self):
        result = bridge.discover_pxeos(host="10.0.0.5", port=9443)

        assert result["host"] == "10.0.0.5"
        assert result["port"] == 9443
        assert result["base_url"] == "http://10.0.0.5:9443"

    def test_explicit_args_override_config(self, pxeos_config_file):
        result = bridge.discover_pxeos(
            config_path=str(pxeos_config_file),
            host="192.168.1.1",
            port=5555,
        )

        assert result["host"] == "192.168.1.1"
        assert result["port"] == 5555


class TestBridgeDiscoverConfigFile:
    """Test bridge discovery from a config file."""

    def test_config_file_discovery(self, pxeos_config_file):
        result = bridge.discover_pxeos(
            config_path=str(pxeos_config_file)
        )

        assert result["host"] == "10.0.0.5"
        assert result["port"] == 9443
        assert result["scheme"] == "https"

    def test_config_file_not_found_falls_back(self, tmp_path):
        result = bridge.discover_pxeos(
            config_path=str(tmp_path / "nonexistent.toml")
        )

        assert result["host"] == bridge.DEFAULT_HOST
        assert result["port"] == bridge.DEFAULT_PORT

    def test_defaults_when_no_args(self):
        result = bridge.discover_pxeos()

        assert result["host"] == bridge.DEFAULT_HOST
        assert result["port"] == bridge.DEFAULT_PORT
        assert "base_url" in result


class TestBridgeDiscoverDefaults:
    """Test bridge discovery falls back to defaults."""

    def test_default_values(self):
        result = bridge.discover_pxeos()

        assert result["host"] == "127.0.0.1"
        assert result["port"] == 8443
        assert result["scheme"] == "http"
        assert result["base_url"] == "http://127.0.0.1:8443"

    def test_partial_host_only(self):
        result = bridge.discover_pxeos(host="10.0.0.1")

        # host set but no port, falls through to defaults
        assert result["host"] == "10.0.0.1"
        assert result["port"] == bridge.DEFAULT_PORT

    def test_partial_port_only(self):
        result = bridge.discover_pxeos(port=9999)

        assert result["host"] == bridge.DEFAULT_HOST
        assert result["port"] == 9999


# ---------------------------------------------------------------
# Bridge script: check_health
# ---------------------------------------------------------------


class TestBridgeHealthCheck:
    """Test health check with mock HTTP responses."""

    def test_health_check_success(self):
        mock_response = json.dumps({
            "status": "ok",
            "version": "1.0",
            "plugins": ["fedora"],
        }).encode()

        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.read.return_value = mock_response
            mock_resp.__enter__ = lambda s: s
            mock_resp.__exit__ = MagicMock(return_value=False)
            mock_urlopen.return_value = mock_resp

            data = bridge.check_health("http://10.0.0.5:8443")

            assert data["status"] == "ok"
            assert data["version"] == "1.0"

    def test_health_check_bad_status(self):
        mock_response = json.dumps({
            "status": "degraded",
        }).encode()

        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.read.return_value = mock_response
            mock_resp.__enter__ = lambda s: s
            mock_resp.__exit__ = MagicMock(return_value=False)
            mock_urlopen.return_value = mock_resp

            with pytest.raises(RuntimeError, match="status"):
                bridge.check_health("http://10.0.0.5:8443")

    def test_health_check_connection_error(self):
        import urllib.error

        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.side_effect = urllib.error.URLError("refused")

            with pytest.raises(RuntimeError, match="cannot reach"):
                bridge.check_health("http://10.0.0.5:8443")


# ---------------------------------------------------------------
# Bridge script: nginx config generation
# ---------------------------------------------------------------


class TestBridgeNginxConfig:
    """Test nginx config generation."""

    def test_generates_valid_config(self):
        config = bridge.generate_nginx_config(
            "http://10.0.0.5:8443"
        )

        assert "proxy_pass http://10.0.0.5:8443/api/v1/;" in config
        assert "location /api/v1/pxe/" in config
        assert "proxy_set_header Authorization" in config
        assert "upstream pxeos-upstream" in config

    def test_writes_to_file(self, tmp_path):
        output = tmp_path / "nginx.conf"

        bridge.generate_nginx_config(
            "http://localhost:8443",
            output_path=str(output),
        )

        assert output.exists()
        content = output.read_text()
        assert "proxy_pass" in content

    def test_returns_config_string(self):
        config = bridge.generate_nginx_config(
            "http://127.0.0.1:8443"
        )

        assert isinstance(config, str)
        assert len(config) > 100

    def test_includes_host_port_in_upstream(self):
        config = bridge.generate_nginx_config(
            "http://192.168.1.50:9443"
        )

        assert "192.168.1.50:9443" in config


# ---------------------------------------------------------------
# Bridge script: haproxy config generation
# ---------------------------------------------------------------


class TestBridgeHAProxyConfig:
    """Test HAProxy config generation."""

    def test_generates_valid_config(self):
        config = bridge.generate_haproxy_config(
            "http://10.0.0.5:8443"
        )

        assert "backend pxeos" in config
        assert "server pxeos1 10.0.0.5:8443 check" in config
        assert "http-request set-path" in config
        assert "/api/v1/pxe/" in config

    def test_writes_to_file(self, tmp_path):
        output = tmp_path / "haproxy.cfg"

        bridge.generate_haproxy_config(
            "http://localhost:8443",
            output_path=str(output),
        )

        assert output.exists()
        content = output.read_text()
        assert "backend pxeos" in content

    def test_health_check_in_config(self):
        config = bridge.generate_haproxy_config(
            "http://10.0.0.5:8443"
        )

        assert "option httpchk GET /api/v1/health" in config
        assert "http-check expect status 200" in config

    def test_returns_config_string(self):
        config = bridge.generate_haproxy_config(
            "http://127.0.0.1:8443"
        )

        assert isinstance(config, str)
        assert len(config) > 50


# ---------------------------------------------------------------
# Service-info API endpoint
# ---------------------------------------------------------------


class TestServiceInfoEndpoint:
    """Test GET /api/v1/service-info."""

    def test_returns_200(self, client):
        resp = client.get("/api/v1/service-info")

        assert resp.status_code == 200

    def test_contains_service_name(self, client):
        resp = client.get("/api/v1/service-info")
        data = resp.json()

        assert data["service"] == "pxeos"

    def test_contains_version(self, client):
        resp = client.get("/api/v1/service-info")
        data = resp.json()

        assert data["version"] == "1.0"

    def test_contains_endpoints_list(self, client):
        resp = client.get("/api/v1/service-info")
        data = resp.json()

        assert isinstance(data["endpoints"], list)
        assert "/api/v1/health" in data["endpoints"]
        assert "/api/v1/service-info" in data["endpoints"]

    def test_contains_auth_and_tls_status(self, client):
        resp = client.get("/api/v1/service-info")
        data = resp.json()

        assert "auth_enabled" in data
        assert "tls_enabled" in data
        assert isinstance(data["auth_enabled"], bool)
        assert isinstance(data["tls_enabled"], bool)

    def test_contains_base_url(self, client):
        resp = client.get("/api/v1/service-info")
        data = resp.json()

        assert "base_url" in data
        assert "api_base" in data


# ---------------------------------------------------------------
# Discovery module: get_service_info
# ---------------------------------------------------------------


class TestGetServiceInfo:
    """Test pxeos.discovery.get_service_info()."""

    def test_returns_service_name(self):
        info = get_service_info()

        assert info["service"] == "pxeos"

    def test_returns_version(self):
        info = get_service_info()

        assert info["version"] == "1.0"

    def test_http_scheme_no_tls(self):
        info = get_service_info(tls_enabled=False)

        assert "http://" in info["base_url"]

    def test_https_scheme_with_tls(self):
        info = get_service_info(tls_enabled=True)

        assert "https://" in info["base_url"]

    def test_auth_status_passed_through(self):
        info = get_service_info(auth_enabled=True)

        assert info["auth_enabled"] is True

    def test_wildcard_host_resolved(self):
        info = get_service_info(host="0.0.0.0")

        # Should not contain 0.0.0.0 in the display
        assert info["host"] != "0.0.0.0"

    def test_explicit_host_preserved(self):
        info = get_service_info(host="10.0.0.5", port=9443)

        assert info["host"] == "10.0.0.5"
        assert info["port"] == 9443


# ---------------------------------------------------------------
# Config additions
# ---------------------------------------------------------------


class TestConfigAdditions:
    """Test PxeOSConfig new fields for discovery."""

    def test_default_service_name(self):
        config = PxeOSConfig()

        assert config.service_name == "pxeos"

    def test_default_enable_discovery(self):
        config = PxeOSConfig()

        assert config.enable_discovery is False

    def test_custom_service_name(self):
        config = PxeOSConfig(service_name="my-pxeos")

        assert config.service_name == "my-pxeos"

    def test_load_config_with_discovery(self, tmp_path):
        config_path = tmp_path / "pxeos.toml"
        config_path.write_text(textwrap.dedent("""\
            [server]
            host = "0.0.0.0"
            port = 8443

            [discovery]
            enabled = true
            service_name = "test-pxe"
        """))

        config = load_config(config_path)

        assert config.enable_discovery is True
        assert config.service_name == "test-pxe"

    def test_load_config_without_discovery_section(self, tmp_path):
        config_path = tmp_path / "pxeos.toml"
        config_path.write_text(textwrap.dedent("""\
            [server]
            host = "0.0.0.0"
            port = 8443
        """))

        config = load_config(config_path)

        assert config.enable_discovery is False
        assert config.service_name == "pxeos"


# ---------------------------------------------------------------
# Discovery module constants
# ---------------------------------------------------------------


class TestDiscoveryConstants:
    """Test discovery module constants and types."""

    def test_service_type_format(self):
        assert SERVICE_TYPE == "_pxeos._tcp.local."

    def test_default_service_name(self):
        assert DEFAULT_SERVICE_NAME == "pxeos"


# ---------------------------------------------------------------
# Bridge script: _extract_host_port utility
# ---------------------------------------------------------------


class TestExtractHostPort:
    """Test the bridge script's URL parsing utility."""

    def test_http_url(self):
        result = bridge._extract_host_port("http://10.0.0.5:8443")

        assert result == "10.0.0.5:8443"

    def test_https_url(self):
        result = bridge._extract_host_port("https://example.com:443")

        assert result == "example.com:443"

    def test_url_with_path(self):
        result = bridge._extract_host_port(
            "http://10.0.0.5:8443/api/v1"
        )

        assert result == "10.0.0.5:8443"

    def test_bare_host_port(self):
        result = bridge._extract_host_port("10.0.0.5:8443")

        assert result == "10.0.0.5:8443"


# ---------------------------------------------------------------
# Bridge script: main() CLI
# ---------------------------------------------------------------


class TestBridgeCLI:
    """Test the bridge script CLI entry point."""

    def test_no_command_returns_1(self):
        assert bridge.main([]) == 1

    def test_discover_returns_0(self, capsys):
        ret = bridge.main(["discover", "--host", "10.0.0.1", "--port", "8443"])

        assert ret == 0
        output = capsys.readouterr().out
        data = json.loads(output)
        assert data["host"] == "10.0.0.1"

    def test_nginx_returns_0(self, capsys):
        ret = bridge.main(["nginx", "--url", "http://10.0.0.1:8443"])

        assert ret == 0
        output = capsys.readouterr().out
        assert "proxy_pass" in output

    def test_haproxy_returns_0(self, capsys):
        ret = bridge.main(["haproxy", "--url", "http://10.0.0.1:8443"])

        assert ret == 0
        output = capsys.readouterr().out
        assert "backend pxeos" in output
