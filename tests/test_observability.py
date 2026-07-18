"""Tests for logging, metrics, and observability (issues #33 and #34)."""

from __future__ import annotations

import json
import logging
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from pxeos.api import app, init_app
from pxeos.config import PxeOSConfig
from pxeos.matcher import HostMatcher
from pxeos.registry import PluginRegistry


# ---- Fixtures ----


@pytest.fixture(autouse=True)
def _reset_metrics():
    """Reset metrics before each test to avoid cross-test contamination."""
    from pxeos.metrics import reset_all

    reset_all()
    yield
    reset_all()


@pytest.fixture
def _setup_app(tmp_path):
    """Initialize the FastAPI app for observability tests."""
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
def client(_setup_app):
    return TestClient(app)


# ---- Logging setup ----


class TestLoggingSetup:

    def test_setup_logging_sets_level(self):
        from pxeos.logging_config import setup_logging

        stream = StringIO()
        setup_logging(level="DEBUG", stream=stream)
        logger = logging.getLogger("pxeos")
        assert logger.level == logging.DEBUG

    def test_setup_logging_info_level(self):
        from pxeos.logging_config import setup_logging

        stream = StringIO()
        setup_logging(level="INFO", stream=stream)
        logger = logging.getLogger("pxeos")
        assert logger.level == logging.INFO

    def test_setup_logging_warning_level(self):
        from pxeos.logging_config import setup_logging

        stream = StringIO()
        setup_logging(level="WARNING", stream=stream)
        logger = logging.getLogger("pxeos")
        assert logger.level == logging.WARNING

    def test_setup_logging_error_level(self):
        from pxeos.logging_config import setup_logging

        stream = StringIO()
        setup_logging(level="ERROR", stream=stream)
        logger = logging.getLogger("pxeos")
        assert logger.level == logging.ERROR

    def test_setup_logging_invalid_level_defaults_to_info(self):
        from pxeos.logging_config import setup_logging

        stream = StringIO()
        setup_logging(level="INVALID", stream=stream)
        logger = logging.getLogger("pxeos")
        assert logger.level == logging.INFO

    def test_setup_logging_default_format(self):
        from pxeos.logging_config import setup_logging

        stream = StringIO()
        setup_logging(level="DEBUG", stream=stream)
        logger = logging.getLogger("pxeos.test_default")
        logger.debug("test message")

        output = stream.getvalue()
        assert "DEBUG" in output
        assert "pxeos.test_default" in output
        assert "test message" in output

    def test_setup_logging_json_format(self):
        from pxeos.logging_config import setup_logging

        stream = StringIO()
        setup_logging(level="DEBUG", json_format=True, stream=stream)
        logger = logging.getLogger("pxeos.test_json")
        logger.info("json test")

        output = stream.getvalue().strip()
        data = json.loads(output)
        assert data["level"] == "INFO"
        assert data["logger"] == "pxeos.test_json"
        assert data["message"] == "json test"

    def test_setup_logging_json_format_has_timestamp(self):
        from pxeos.logging_config import setup_logging

        stream = StringIO()
        setup_logging(level="DEBUG", json_format=True, stream=stream)
        logger = logging.getLogger("pxeos.test_ts")
        logger.info("timestamp test")

        output = stream.getvalue().strip()
        data = json.loads(output)
        assert "timestamp" in data

    def test_setup_logging_clears_previous_handlers(self):
        from pxeos.logging_config import setup_logging

        stream1 = StringIO()
        setup_logging(level="DEBUG", stream=stream1)
        stream2 = StringIO()
        setup_logging(level="INFO", stream=stream2)

        logger = logging.getLogger("pxeos")
        assert len(logger.handlers) == 1


# ---- Metrics endpoint ----


class TestMetricsEndpoint:

    def test_metrics_returns_200(self, client):
        resp = client.get("/metrics")
        assert resp.status_code == 200

    def test_metrics_content_type(self, client):
        resp = client.get("/metrics")
        assert "text/plain" in resp.headers["content-type"]

    def test_metrics_contains_provisions_total(self, client):
        resp = client.get("/metrics")
        assert "pxeos_provisions_total" in resp.text

    def test_metrics_contains_active_provisions(self, client):
        resp = client.get("/metrics")
        assert "pxeos_active_provisions" in resp.text

    def test_metrics_contains_boot_requests(self, client):
        resp = client.get("/metrics")
        assert "pxeos_boot_requests_total" in resp.text

    def test_metrics_contains_import_operations(self, client):
        resp = client.get("/metrics")
        assert "pxeos_import_operations_total" in resp.text

    def test_metrics_contains_auth_attempts(self, client):
        resp = client.get("/metrics")
        assert "pxeos_auth_attempts_total" in resp.text

    def test_metrics_contains_uptime(self, client):
        resp = client.get("/metrics")
        assert "pxeos_uptime_seconds" in resp.text

    def test_metrics_has_help_lines(self, client):
        resp = client.get("/metrics")
        assert "# HELP" in resp.text

    def test_metrics_has_type_lines(self, client):
        resp = client.get("/metrics")
        assert "# TYPE" in resp.text

    def test_metrics_valid_prometheus_format(self, client):
        """Each non-comment line must be 'metric_name{labels} value' or 'metric_name value'."""
        resp = client.get("/metrics")
        for line in resp.text.strip().split("\n"):
            if line.startswith("#") or not line.strip():
                continue
            parts = line.split()
            assert len(parts) == 2, f"bad metrics line: {line!r}"
            # The second part should be a number
            float(parts[1])


# ---- Enhanced health endpoint ----


class TestHealthEndpointEnhanced:

    def test_health_includes_uptime(self, client):
        resp = client.get("/api/v1/health")
        data = resp.json()
        assert "uptime_seconds" in data
        assert isinstance(data["uptime_seconds"], (int, float))
        assert data["uptime_seconds"] >= 0

    def test_health_includes_provision_count(self, client):
        resp = client.get("/api/v1/health")
        data = resp.json()
        assert "provision_count" in data
        assert data["provision_count"] == 0

    def test_health_includes_data_dir_free_bytes(self, client):
        resp = client.get("/api/v1/health")
        data = resp.json()
        assert "data_dir_free_bytes" in data
        # Should be a positive integer (disk has free space)
        assert data["data_dir_free_bytes"] > 0

    def test_health_still_returns_plugins(self, client):
        resp = client.get("/api/v1/health")
        data = resp.json()
        assert "plugins" in data
        assert isinstance(data["plugins"], list)

    def test_health_still_returns_version(self, client):
        resp = client.get("/api/v1/health")
        data = resp.json()
        assert data["version"] == "1.0"


# ---- CLI --log-level flag ----


class TestCliLogLevel:

    def test_parser_accepts_log_level(self):
        from pxeos.cli import _build_parser

        parser = _build_parser()
        args = parser.parse_args(
            ["--log-level", "DEBUG", "server", "status"]
        )
        assert args.log_level == "DEBUG"

    def test_parser_default_log_level(self):
        from pxeos.cli import _build_parser

        parser = _build_parser()
        args = parser.parse_args(["server", "status"])
        assert args.log_level == "INFO"

    def test_parser_accepts_warning_level(self):
        from pxeos.cli import _build_parser

        parser = _build_parser()
        args = parser.parse_args(
            ["--log-level", "WARNING", "server", "status"]
        )
        assert args.log_level == "WARNING"

    def test_parser_accepts_error_level(self):
        from pxeos.cli import _build_parser

        parser = _build_parser()
        args = parser.parse_args(
            ["--log-level", "ERROR", "server", "status"]
        )
        assert args.log_level == "ERROR"

    def test_parser_rejects_invalid_level(self):
        from pxeos.cli import _build_parser

        parser = _build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(
                ["--log-level", "INVALID", "server", "status"]
            )

    def test_parser_accepts_log_json_flag(self):
        from pxeos.cli import _build_parser

        parser = _build_parser()
        args = parser.parse_args(
            ["--log-json", "server", "status"]
        )
        assert args.log_json is True

    @patch("pxeos.cli._init_stack")
    def test_main_initializes_logging(self, mock_init_stack):
        from pxeos.cli import main
        from pxeos.config import PxeOSConfig

        config = PxeOSConfig()
        mock_registry = MagicMock()
        mock_registry.available = []
        matcher = HostMatcher([])
        mock_init_stack.return_value = (config, mock_registry, matcher)

        with patch("pxeos.logging_config.setup_logging") as mock_setup:
            main(["--log-level", "DEBUG", "server", "status"])
            mock_setup.assert_called_once_with(
                level="DEBUG", json_format=False,
            )


# ---- Auth logging ----


class TestAuthLogging:

    def test_auth_failure_does_not_leak_key(self, _setup_app, caplog):
        """Ensure auth failure logs do not contain the raw API key."""
        from pxeos.auth import init_auth, ApiKeyStore

        # Enable auth
        client = TestClient(app)
        config = PxeOSConfig(data_dir=Path("/tmp/pxeos-auth-test"))
        store = ApiKeyStore(config.data_dir)
        init_auth(True, store)

        fake_key = "pxeos_secret_test_key_12345"

        with caplog.at_level(logging.DEBUG, logger="pxeos.auth"):
            resp = client.get(
                "/api/v1/profiles",
                headers={"Authorization": f"Bearer {fake_key}"},
            )

        # Auth should have failed
        assert resp.status_code == 401

        # The raw key must NOT appear in logs
        for record in caplog.records:
            assert fake_key not in record.getMessage()

        # Re-disable auth for other tests
        init_auth(False, store)


# ---- Metrics increment on events ----


class TestMetricsIncrements:

    def test_boot_request_increments_counter(self):
        from pxeos.metrics import boot_requests_total

        assert boot_requests_total.get() == 0.0
        boot_requests_total.inc()
        assert boot_requests_total.get() == 1.0

    def test_provision_counter_with_labels(self):
        from pxeos.metrics import provisions_total

        provisions_total.inc(os_family="fedora", status="success")
        provisions_total.inc(os_family="fedora", status="success")
        provisions_total.inc(os_family="debian", status="success")

        assert provisions_total.get(
            os_family="fedora", status="success"
        ) == 2.0
        assert provisions_total.get(
            os_family="debian", status="success"
        ) == 1.0

    def test_active_provisions_gauge(self):
        from pxeos.metrics import active_provisions

        assert active_provisions.get() == 0.0
        active_provisions.inc()
        active_provisions.inc()
        assert active_provisions.get() == 2.0
        active_provisions.dec()
        assert active_provisions.get() == 1.0

    def test_import_counter_with_labels(self):
        from pxeos.metrics import import_operations_total

        import_operations_total.inc(os_family="fedora", type="iso")
        import_operations_total.inc(os_family="ubuntu", type="url")

        assert import_operations_total.get(
            os_family="fedora", type="iso"
        ) == 1.0
        assert import_operations_total.get(
            os_family="ubuntu", type="url"
        ) == 1.0

    def test_auth_counter_with_labels(self):
        from pxeos.metrics import auth_attempts_total

        auth_attempts_total.inc(result="success")
        auth_attempts_total.inc(result="failure")
        auth_attempts_total.inc(result="failure")

        assert auth_attempts_total.get(result="success") == 1.0
        assert auth_attempts_total.get(result="failure") == 2.0

    def test_render_metrics_includes_all_counters(self):
        from pxeos.metrics import (
            provisions_total,
            render_metrics,
        )

        provisions_total.inc(os_family="arch", status="success")

        output = render_metrics()
        assert 'pxeos_provisions_total{os_family="arch",status="success"} 1' in output

    def test_gauge_set(self):
        from pxeos.metrics import active_provisions

        active_provisions.set(42)
        assert active_provisions.get() == 42.0

    def test_counter_render_no_values(self):
        from pxeos.metrics import _Counter

        c = _Counter("test_empty", "test help")
        rendered = c.render()
        assert "test_empty 0" in rendered

    def test_uptime_positive(self):
        from pxeos.metrics import get_uptime_seconds

        assert get_uptime_seconds() >= 0
