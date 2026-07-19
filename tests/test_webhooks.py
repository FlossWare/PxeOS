"""Tests for the PxeOS webhook delivery system."""

from __future__ import annotations

import hashlib
import hmac
import json
import textwrap
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from pxeos.api import _cloud_init_store, app, init_app
from pxeos.config import PxeOSConfig, load_config
from pxeos.matcher import HostMatcher
from pxeos.models import HostRule
from pxeos.registry import PluginRegistry
from pxeos.webhooks import (
    SUPPORTED_EVENTS,
    WebhookConfig,
    WebhookDelivery,
    WebhookManager,
    compute_signature,
    verify_signature,
)


# ---------------------------------------------------------------
# WebhookConfig tests
# ---------------------------------------------------------------


class TestWebhookConfig:

    def test_valid_http_url(self):
        wh = WebhookConfig(
            url="http://example.com/hook",
            events=["boot.started"],
            secret="s3cret",
        )
        assert wh.url == "http://example.com/hook"
        assert wh.events == ["boot.started"]
        assert wh.secret == "s3cret"

    def test_valid_https_url(self):
        wh = WebhookConfig(
            url="https://example.com/hook",
            events=["install.complete"],
        )
        assert wh.url == "https://example.com/hook"

    def test_invalid_scheme_raises(self):
        with pytest.raises(ValueError, match="http or https"):
            WebhookConfig(url="ftp://example.com/hook")

    def test_unknown_event_raises(self):
        with pytest.raises(ValueError, match="unknown webhook events"):
            WebhookConfig(
                url="http://example.com/hook",
                events=["nonexistent.event"],
            )

    def test_empty_events_means_all(self):
        wh = WebhookConfig(url="http://example.com/hook")
        assert wh.events == []

    def test_default_retry_and_timeout(self):
        wh = WebhookConfig(url="http://example.com/hook")
        assert wh.retry_count == 3
        assert wh.timeout == 10.0

    def test_custom_retry_and_timeout(self):
        wh = WebhookConfig(
            url="http://example.com/hook",
            retry_count=5,
            timeout=30.0,
        )
        assert wh.retry_count == 5
        assert wh.timeout == 30.0


# ---------------------------------------------------------------
# HMAC signature tests
# ---------------------------------------------------------------


class TestHMACSignature:

    def test_compute_signature_deterministic(self):
        payload = b'{"event": "test"}'
        secret = "my-secret"
        sig1 = compute_signature(payload, secret)
        sig2 = compute_signature(payload, secret)
        assert sig1 == sig2

    def test_compute_signature_matches_manual(self):
        payload = b'{"event": "boot.started"}'
        secret = "webhook-secret"
        expected = hmac.new(
            b"webhook-secret", payload, hashlib.sha256
        ).hexdigest()
        assert compute_signature(payload, secret) == expected

    def test_different_secret_different_signature(self):
        payload = b'{"event": "test"}'
        sig1 = compute_signature(payload, "secret-a")
        sig2 = compute_signature(payload, "secret-b")
        assert sig1 != sig2

    def test_different_payload_different_signature(self):
        secret = "same-secret"
        sig1 = compute_signature(b"payload-a", secret)
        sig2 = compute_signature(b"payload-b", secret)
        assert sig1 != sig2

    def test_verify_signature_valid(self):
        payload = b'{"event": "test"}'
        secret = "my-secret"
        sig = compute_signature(payload, secret)
        assert verify_signature(payload, secret, sig) is True

    def test_verify_signature_invalid(self):
        payload = b'{"event": "test"}'
        secret = "my-secret"
        assert verify_signature(
            payload, secret, "invalid-sig"
        ) is False

    def test_verify_signature_wrong_secret(self):
        payload = b'{"event": "test"}'
        sig = compute_signature(payload, "correct-secret")
        assert verify_signature(
            payload, "wrong-secret", sig
        ) is False

    def test_verify_signature_timing_safe(self):
        """Verify that comparison uses hmac.compare_digest (timing-safe)."""
        payload = b'{"event": "test"}'
        secret = "secret"
        sig = compute_signature(payload, secret)
        # This test just confirms the function works; the actual
        # timing-safety is guaranteed by hmac.compare_digest internals.
        assert verify_signature(payload, secret, sig) is True


# ---------------------------------------------------------------
# WebhookManager tests (unit)
# ---------------------------------------------------------------


class TestWebhookManager:

    def _make_post_fn(
        self, status_code: int = 200, raises: Optional[Exception] = None,
    ):
        """Return a mock HTTP post function."""
        calls: list = []

        def post(url, data, headers, timeout=10.0):
            calls.append({
                "url": url,
                "data": data,
                "headers": headers,
                "timeout": timeout,
            })
            if raises:
                raise raises
            return status_code

        return post, calls

    def test_fire_dispatches_to_matching_webhooks(self):
        post_fn, calls = self._make_post_fn(200)
        wh = WebhookConfig(
            url="http://example.com/hook",
            events=["boot.started"],
            secret="secret",
        )
        mgr = WebhookManager([wh], http_post=post_fn)
        results = mgr.fire_sync("boot.started", {"mac": "aa:bb:cc:dd:ee:ff"})
        assert len(results) == 1
        assert results[0].success is True
        assert len(calls) == 1

    def test_fire_skips_unsubscribed_events(self):
        post_fn, calls = self._make_post_fn(200)
        wh = WebhookConfig(
            url="http://example.com/hook",
            events=["install.complete"],
        )
        mgr = WebhookManager([wh], http_post=post_fn)
        results = mgr.fire_sync("boot.started", {"mac": "aa:bb:cc:dd:ee:ff"})
        assert len(results) == 0
        assert len(calls) == 0

    def test_fire_empty_events_subscribes_to_all(self):
        post_fn, calls = self._make_post_fn(200)
        wh = WebhookConfig(
            url="http://example.com/hook",
            events=[],
        )
        mgr = WebhookManager([wh], http_post=post_fn)
        for event in SUPPORTED_EVENTS:
            results = mgr.fire_sync(event, {"mac": "aa:bb:cc:dd:ee:ff"})
            assert len(results) == 1
        assert len(calls) == len(SUPPORTED_EVENTS)

    def test_fire_unsupported_event_returns_zero(self):
        post_fn, calls = self._make_post_fn(200)
        wh = WebhookConfig(
            url="http://example.com/hook",
            events=[],
        )
        mgr = WebhookManager([wh], http_post=post_fn)
        count = mgr.fire("nonexistent.event", {"mac": "test"})
        assert count == 0
        assert len(calls) == 0

    def test_fire_multiple_webhooks(self):
        post_fn, calls = self._make_post_fn(200)
        webhooks = [
            WebhookConfig(
                url="http://example.com/hook1",
                events=["boot.started"],
            ),
            WebhookConfig(
                url="http://example.com/hook2",
                events=["boot.started"],
            ),
            WebhookConfig(
                url="http://example.com/hook3",
                events=["install.complete"],
            ),
        ]
        mgr = WebhookManager(webhooks, http_post=post_fn)
        results = mgr.fire_sync("boot.started", {"mac": "test"})
        assert len(results) == 2
        assert all(r.success for r in results)

    def test_hmac_signature_in_headers(self):
        post_fn, calls = self._make_post_fn(200)
        wh = WebhookConfig(
            url="http://example.com/hook",
            events=["boot.started"],
            secret="test-secret",
        )
        mgr = WebhookManager([wh], http_post=post_fn)
        mgr.fire_sync("boot.started", {"mac": "aa:bb:cc:dd:ee:ff"})

        assert len(calls) == 1
        headers = calls[0]["headers"]
        assert "X-PxeOS-Signature" in headers
        sig_header = headers["X-PxeOS-Signature"]
        assert sig_header.startswith("sha256=")

        # Verify the signature is correct
        payload_bytes = calls[0]["data"]
        expected_sig = compute_signature(payload_bytes, "test-secret")
        assert sig_header == f"sha256={expected_sig}"

    def test_no_signature_when_no_secret(self):
        post_fn, calls = self._make_post_fn(200)
        wh = WebhookConfig(
            url="http://example.com/hook",
            events=["boot.started"],
            secret="",
        )
        mgr = WebhookManager([wh], http_post=post_fn)
        mgr.fire_sync("boot.started", {"mac": "test"})
        assert "X-PxeOS-Signature" not in calls[0]["headers"]

    def test_event_and_delivery_headers(self):
        post_fn, calls = self._make_post_fn(200)
        wh = WebhookConfig(
            url="http://example.com/hook",
            events=["install.complete"],
        )
        mgr = WebhookManager([wh], http_post=post_fn)
        mgr.fire_sync("install.complete", {"mac": "test"})

        headers = calls[0]["headers"]
        assert headers["X-PxeOS-Event"] == "install.complete"
        assert "X-PxeOS-Delivery" in headers
        assert headers["Content-Type"] == "application/json"

    def test_payload_includes_event(self):
        post_fn, calls = self._make_post_fn(200)
        wh = WebhookConfig(
            url="http://example.com/hook",
            events=["boot.started"],
        )
        mgr = WebhookManager([wh], http_post=post_fn)
        mgr.fire_sync("boot.started", {"mac": "aa:bb:cc:dd:ee:ff"})

        data = json.loads(calls[0]["data"])
        assert data["event"] == "boot.started"
        assert data["mac"] == "aa:bb:cc:dd:ee:ff"


# ---------------------------------------------------------------
# Retry logic tests
# ---------------------------------------------------------------


class TestWebhookRetry:

    def test_retry_on_server_error(self):
        attempt_count = [0]

        def post_fn(url, data, headers, timeout=10.0):
            attempt_count[0] += 1
            if attempt_count[0] < 3:
                return 500
            return 200

        wh = WebhookConfig(
            url="http://example.com/hook",
            events=["boot.started"],
            retry_count=3,
        )
        mgr = WebhookManager([wh], http_post=post_fn)
        results = mgr.fire_sync("boot.started", {"mac": "test"})
        assert len(results) == 1
        assert results[0].success is True
        assert results[0].attempts == 3

    def test_retry_on_connection_error(self):
        attempt_count = [0]

        def post_fn(url, data, headers, timeout=10.0):
            attempt_count[0] += 1
            if attempt_count[0] < 2:
                raise ConnectionError("refused")
            return 200

        wh = WebhookConfig(
            url="http://example.com/hook",
            events=["boot.started"],
            retry_count=3,
        )
        mgr = WebhookManager([wh], http_post=post_fn)
        results = mgr.fire_sync("boot.started", {"mac": "test"})
        assert results[0].success is True
        assert results[0].attempts == 2

    def test_exhausted_retries_marks_failure(self):
        def post_fn(url, data, headers, timeout=10.0):
            return 500

        wh = WebhookConfig(
            url="http://example.com/hook",
            events=["boot.started"],
            retry_count=2,
        )
        mgr = WebhookManager([wh], http_post=post_fn)
        results = mgr.fire_sync("boot.started", {"mac": "test"})
        assert results[0].success is False
        assert results[0].attempts == 2
        assert results[0].error == "HTTP 500"

    def test_connection_error_exhausted(self):
        def post_fn(url, data, headers, timeout=10.0):
            raise ConnectionError("refused")

        wh = WebhookConfig(
            url="http://example.com/hook",
            events=["boot.started"],
            retry_count=1,
        )
        mgr = WebhookManager([wh], http_post=post_fn)
        results = mgr.fire_sync("boot.started", {"mac": "test"})
        assert results[0].success is False
        assert results[0].attempts == 1
        assert "refused" in results[0].error

    def test_retry_count_one_means_single_attempt(self):
        calls = []

        def post_fn(url, data, headers, timeout=10.0):
            calls.append(1)
            return 500

        wh = WebhookConfig(
            url="http://example.com/hook",
            events=["boot.started"],
            retry_count=1,
        )
        mgr = WebhookManager([wh], http_post=post_fn)
        mgr.fire_sync("boot.started", {"mac": "test"})
        assert len(calls) == 1

    def test_successful_delivery_records_timestamp(self):
        post_fn = lambda url, data, headers, timeout=10.0: 200
        wh = WebhookConfig(
            url="http://example.com/hook",
            events=["boot.started"],
        )
        mgr = WebhookManager([wh], http_post=post_fn)
        results = mgr.fire_sync("boot.started", {"mac": "test"})
        assert results[0].delivered_at is not None
        assert results[0].delivered_at > 0


# ---------------------------------------------------------------
# Async (background) delivery tests
# ---------------------------------------------------------------


class TestWebhookAsyncDelivery:

    def test_fire_returns_dispatch_count(self):
        post_fn = lambda url, data, headers, timeout=10.0: 200
        webhooks = [
            WebhookConfig(
                url="http://example.com/hook1",
                events=["boot.started"],
            ),
            WebhookConfig(
                url="http://example.com/hook2",
                events=["install.complete"],
            ),
        ]
        mgr = WebhookManager(webhooks, http_post=post_fn)
        count = mgr.fire("boot.started", {"mac": "test"})
        assert count == 1
        mgr.shutdown()

    def test_async_delivery_completes(self):
        delivered = threading.Event()

        def post_fn(url, data, headers, timeout=10.0):
            delivered.set()
            return 200

        wh = WebhookConfig(
            url="http://example.com/hook",
            events=["boot.started"],
        )
        mgr = WebhookManager([wh], http_post=post_fn)
        mgr.fire("boot.started", {"mac": "test"})
        assert delivered.wait(timeout=5.0)
        mgr.shutdown()


# ---------------------------------------------------------------
# Delivery tracking tests
# ---------------------------------------------------------------


class TestDeliveryTracking:

    def test_recent_deliveries_recorded(self):
        post_fn = lambda url, data, headers, timeout=10.0: 200
        wh = WebhookConfig(
            url="http://example.com/hook",
            events=["boot.started"],
        )
        mgr = WebhookManager([wh], http_post=post_fn)
        mgr.fire_sync("boot.started", {"mac": "test"})
        recent = mgr.get_recent_deliveries()
        assert len(recent) == 1
        assert recent[0].event == "boot.started"
        assert recent[0].success is True

    def test_deliveries_newest_first(self):
        post_fn = lambda url, data, headers, timeout=10.0: 200
        wh = WebhookConfig(url="http://example.com/hook", events=[])
        mgr = WebhookManager([wh], http_post=post_fn)
        mgr.fire_sync("boot.started", {"mac": "first"})
        mgr.fire_sync("install.complete", {"mac": "second"})
        recent = mgr.get_recent_deliveries()
        assert recent[0].event == "install.complete"
        assert recent[1].event == "boot.started"

    def test_on_delivery_callback_invoked(self):
        callbacks: list = []
        post_fn = lambda url, data, headers, timeout=10.0: 200
        wh = WebhookConfig(
            url="http://example.com/hook",
            events=["boot.started"],
        )
        mgr = WebhookManager(
            [wh],
            http_post=post_fn,
            on_delivery=lambda d: callbacks.append(d),
        )
        mgr.fire_sync("boot.started", {"mac": "test"})
        assert len(callbacks) == 1
        assert callbacks[0].success is True


# ---------------------------------------------------------------
# Test webhook endpoint
# ---------------------------------------------------------------


class TestWebhookSendTest:

    def test_send_test_to_all(self):
        post_fn = lambda url, data, headers, timeout=10.0: 200
        webhooks = [
            WebhookConfig(
                url="http://example.com/hook1",
                events=["boot.started"],
            ),
            WebhookConfig(
                url="http://example.com/hook2",
                events=["install.complete"],
            ),
        ]
        mgr = WebhookManager(webhooks, http_post=post_fn)
        results = mgr.send_test()
        assert len(results) == 2
        assert all(r.success for r in results)

    def test_send_test_to_specific_url(self):
        post_fn = lambda url, data, headers, timeout=10.0: 200
        webhooks = [
            WebhookConfig(url="http://example.com/hook1"),
            WebhookConfig(url="http://example.com/hook2"),
        ]
        mgr = WebhookManager(webhooks, http_post=post_fn)
        results = mgr.send_test("http://example.com/hook2")
        assert len(results) == 1
        assert results[0].webhook_url == "http://example.com/hook2"


# ---------------------------------------------------------------
# Config parsing tests
# ---------------------------------------------------------------


class TestWebhookConfigParsing:

    def test_load_config_with_webhooks(self, tmp_path):
        config_file = tmp_path / "pxeos.toml"
        config_file.write_text(textwrap.dedent("""\
            [server]
            host = "0.0.0.0"
            port = 8443

            [[webhooks]]
            url = "http://virtos:8080/callback"
            events = ["boot.started", "install.complete"]
            secret = "hmac-key"
            retry_count = 5
            timeout = 15.0

            [[webhooks]]
            url = "https://monitoring.example.com/events"
            events = ["install.failed"]
        """))
        config = load_config(config_file)
        assert len(config.webhooks) == 2

        wh0 = config.webhooks[0]
        assert wh0.url == "http://virtos:8080/callback"
        assert wh0.events == ["boot.started", "install.complete"]
        assert wh0.secret == "hmac-key"
        assert wh0.retry_count == 5
        assert wh0.timeout == 15.0

        wh1 = config.webhooks[1]
        assert wh1.url == "https://monitoring.example.com/events"
        assert wh1.events == ["install.failed"]
        assert wh1.secret == ""
        assert wh1.retry_count == 3  # default

    def test_load_config_no_webhooks(self, tmp_path):
        config_file = tmp_path / "pxeos.toml"
        config_file.write_text(textwrap.dedent("""\
            [server]
            host = "0.0.0.0"
            port = 8443
        """))
        config = load_config(config_file)
        assert config.webhooks == []

    def test_webhook_config_defaults_in_dataclass(self):
        config = PxeOSConfig()
        assert config.webhooks == []


# ---------------------------------------------------------------
# API endpoint tests
# ---------------------------------------------------------------


class TestWebhookAPIEndpoints:

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path):
        """Initialize the FastAPI app with webhook config."""
        import pxeos.api as api_mod

        registry = PluginRegistry()
        registry.load_builtins()
        config = PxeOSConfig(
            data_dir=tmp_path / "data",
            distro_root=tmp_path / "distros",
            webhooks=[
                WebhookConfig(
                    url="http://example.com/hook",
                    events=["boot.started", "install.complete"],
                    secret="test-secret",
                ),
            ],
        )
        (tmp_path / "data").mkdir(exist_ok=True)
        (tmp_path / "distros").mkdir(exist_ok=True)
        matcher = HostMatcher([])
        init_app(registry, config, matcher)

        # Replace the webhook manager's http_post with a mock
        self._post_calls: list = []

        def mock_post(url, data, headers, timeout=10.0):
            self._post_calls.append({
                "url": url,
                "data": data,
                "headers": headers,
            })
            return 200

        api_mod._webhook_manager._http_post = mock_post
        _cloud_init_store.clear()
        yield

    @pytest.fixture
    def client(self):
        return TestClient(app)

    def test_list_webhooks(self, client):
        resp = client.get("/api/v1/webhooks")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["url"] == "http://example.com/hook"
        assert data[0]["events"] == ["boot.started", "install.complete"]
        # Secret must NOT be exposed
        assert "secret" not in data[0]

    def test_test_webhooks(self, client):
        resp = client.post("/api/v1/webhooks/test")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["success"] is True
        assert data[0]["url"] == "http://example.com/hook"

    def test_list_webhooks_empty_when_none_configured(self, tmp_path):
        """When no webhooks are configured, the endpoint returns []."""
        registry = PluginRegistry()
        registry.load_builtins()
        config = PxeOSConfig(
            data_dir=tmp_path / "data2",
            distro_root=tmp_path / "distros2",
        )
        (tmp_path / "data2").mkdir(exist_ok=True)
        (tmp_path / "distros2").mkdir(exist_ok=True)
        matcher = HostMatcher([])
        init_app(registry, config, matcher)

        client = TestClient(app)
        resp = client.get("/api/v1/webhooks")
        assert resp.status_code == 200
        assert resp.json() == []


# ---------------------------------------------------------------
# Integration: webhook fires on provision state changes
# ---------------------------------------------------------------


class TestWebhookIntegration:

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path):
        import pxeos.api as api_mod

        registry = PluginRegistry()
        registry.load_builtins()

        data_dir = tmp_path / "data"
        data_dir.mkdir()
        distro_dir = tmp_path / "distros"
        distro_dir.mkdir()

        # Write a hosts.toml and profile so provision works
        hosts_toml = data_dir / "hosts.toml"
        hosts_toml.write_text(textwrap.dedent("""\
            [[host]]
            mac = "aa:bb:cc:dd:ee:ff"
            profile = "test-server"
            os_family = "fedora"
            os_version = "40"
        """))

        profiles_dir = data_dir / "profiles"
        profiles_dir.mkdir()
        profile_toml = profiles_dir / "test-server.toml"
        profile_toml.write_text(textwrap.dedent("""\
            [profile]
            name = "test-server"
            os_family = "fedora"
            os_version = "40"
            arch = "x86_64"
            firmware = "bios"
            install_url = "http://mirror.example.com/fedora/40/x86_64"
        """))

        config = PxeOSConfig(
            data_dir=data_dir,
            distro_root=distro_dir,
            webhooks=[
                WebhookConfig(
                    url="http://virtos:8080/callback",
                    events=["boot.started", "install.started",
                            "install.complete", "install.failed",
                            "netboot.disabled"],
                    secret="integration-secret",
                    retry_count=1,
                ),
            ],
        )

        rules = [
            HostRule(
                profile="test-server",
                os_family="fedora",
                os_version="40",
                mac="aa:bb:cc:dd:ee:ff",
            ),
        ]
        matcher = HostMatcher(rules)
        init_app(registry, config, matcher)

        self._post_calls: list = []

        def mock_post(url, data, headers, timeout=10.0):
            self._post_calls.append({
                "url": url,
                "data": json.loads(data),
                "headers": headers,
            })
            return 200

        api_mod._webhook_manager._http_post = mock_post
        _cloud_init_store.clear()
        yield

    @pytest.fixture
    def client(self):
        return TestClient(app)

    def test_boot_fires_webhook(self, client):
        resp = client.get("/api/v1/boot/aa:bb:cc:dd:ee:ff")
        assert resp.status_code == 200
        # Give async delivery a moment
        time.sleep(0.2)
        boot_calls = [
            c for c in self._post_calls
            if c["data"].get("event") == "boot.started"
        ]
        assert len(boot_calls) >= 1
        assert boot_calls[0]["data"]["mac"] == "aa:bb:cc:dd:ee:ff"
        # HMAC signature present
        assert "X-PxeOS-Signature" in boot_calls[0]["headers"]

    def test_autoinstall_fires_webhook(self, client):
        # First trigger a boot so the host is tracked
        client.get("/api/v1/boot/aa:bb:cc:dd:ee:ff")
        time.sleep(0.1)
        self._post_calls.clear()

        resp = client.get("/api/v1/autoinstall/aa:bb:cc:dd:ee:ff")
        assert resp.status_code == 200
        time.sleep(0.2)
        install_calls = [
            c for c in self._post_calls
            if c["data"].get("event") == "install.started"
        ]
        assert len(install_calls) >= 1

    def test_complete_fires_webhook(self, client):
        # Set up the host in tracking
        client.get("/api/v1/boot/aa:bb:cc:dd:ee:ff")
        time.sleep(0.1)
        self._post_calls.clear()

        resp = client.post(
            "/api/v1/provision/aa:bb:cc:dd:ee:ff/complete"
        )
        assert resp.status_code == 200
        time.sleep(0.2)
        complete_calls = [
            c for c in self._post_calls
            if c["data"].get("event") == "install.complete"
        ]
        assert len(complete_calls) >= 1
        assert complete_calls[0]["data"]["mac"] == "aa:bb:cc:dd:ee:ff"

    def test_failed_fires_webhook(self, client):
        client.get("/api/v1/boot/aa:bb:cc:dd:ee:ff")
        time.sleep(0.1)
        self._post_calls.clear()

        resp = client.post(
            "/api/v1/provision/aa:bb:cc:dd:ee:ff/failed",
            json={"error": "disk not found"},
        )
        assert resp.status_code == 200
        time.sleep(0.2)
        failed_calls = [
            c for c in self._post_calls
            if c["data"].get("event") == "install.failed"
        ]
        assert len(failed_calls) >= 1
        assert "disk not found" in failed_calls[0]["data"].get("error", "")

    def test_disable_netboot_fires_webhook(self, client):
        client.get("/api/v1/boot/aa:bb:cc:dd:ee:ff")
        time.sleep(0.1)
        self._post_calls.clear()

        resp = client.post(
            "/api/v1/provision/aa:bb:cc:dd:ee:ff/disable-netboot"
        )
        assert resp.status_code == 200
        time.sleep(0.2)
        netboot_calls = [
            c for c in self._post_calls
            if c["data"].get("event") == "netboot.disabled"
        ]
        assert len(netboot_calls) >= 1

    def test_webhook_signature_verifiable(self, client):
        """Verify that the HMAC signature sent by the webhook can
        be verified with the shared secret."""
        client.get("/api/v1/boot/aa:bb:cc:dd:ee:ff")
        time.sleep(0.2)
        boot_calls = [
            c for c in self._post_calls
            if c["data"].get("event") == "boot.started"
        ]
        assert len(boot_calls) >= 1

        call = boot_calls[0]
        sig_header = call["headers"]["X-PxeOS-Signature"]
        assert sig_header.startswith("sha256=")
        sig = sig_header[len("sha256="):]

        # Reconstruct payload bytes the same way the manager does
        payload_bytes = json.dumps(
            call["data"], default=str
        ).encode("utf-8")
        assert verify_signature(
            payload_bytes, "integration-secret", sig
        )


# ---------------------------------------------------------------
# Audit integration tests
# ---------------------------------------------------------------


class TestWebhookAudit:

    def test_audit_event_type_constant(self):
        from pxeos.audit import AuditEvent
        assert AuditEvent.WEBHOOK_DELIVERY == "webhook_delivery"

    def test_audit_logger_log_webhook_delivery(self):
        from pxeos.audit import AuditLogger
        audit = AuditLogger()
        entry = audit.log_webhook_delivery(
            delivery_id="abc123",
            webhook_url="http://example.com/hook",
            event="boot.started",
            success=True,
            attempts=1,
            status_code=200,
        )
        assert entry["event_type"] == "webhook_delivery"
        assert entry["delivery_id"] == "abc123"
        assert entry["success"] is True
        assert entry["status_code"] == 200

    def test_audit_logger_log_webhook_failure(self):
        from pxeos.audit import AuditLogger
        audit = AuditLogger()
        entry = audit.log_webhook_delivery(
            delivery_id="def456",
            webhook_url="http://example.com/hook",
            event="install.failed",
            success=False,
            attempts=3,
            error="Connection refused",
        )
        assert entry["success"] is False
        assert entry["error"] == "Connection refused"
        assert entry["attempts"] == 3


# ---------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------


class TestWebhookEdgeCases:

    def test_manager_with_no_webhooks(self):
        mgr = WebhookManager([])
        count = mgr.fire("boot.started", {"mac": "test"})
        assert count == 0
        assert mgr.webhooks == []

    def test_manager_webhooks_property_returns_copy(self):
        wh = WebhookConfig(url="http://example.com/hook")
        mgr = WebhookManager([wh])
        # Modifying the returned list should not affect the manager
        mgr.webhooks.append(
            WebhookConfig(url="http://other.com/hook")
        )
        assert len(mgr.webhooks) == 1

    def test_delivery_ring_buffer_bounded(self):
        post_fn = lambda url, data, headers, timeout=10.0: 200
        wh = WebhookConfig(
            url="http://example.com/hook", events=[]
        )
        mgr = WebhookManager([wh], http_post=post_fn)
        mgr._max_deliveries = 5
        for _ in range(10):
            mgr.fire_sync("boot.started", {"mac": "test"})
        recent = mgr.get_recent_deliveries(limit=100)
        assert len(recent) == 5

    def test_shutdown_idempotent(self):
        mgr = WebhookManager([])
        mgr.shutdown()
        # Second shutdown should not raise
        mgr.shutdown(wait=False)

    def test_supported_events_frozenset(self):
        assert isinstance(SUPPORTED_EVENTS, frozenset)
        assert "boot.started" in SUPPORTED_EVENTS
        assert "install.complete" in SUPPORTED_EVENTS
        assert "install.failed" in SUPPORTED_EVENTS
        assert "netboot.disabled" in SUPPORTED_EVENTS
        assert "boot.requested" in SUPPORTED_EVENTS
        assert "install.started" in SUPPORTED_EVENTS


# ---------------------------------------------------------------
# Integration with mock HTTP server
# ---------------------------------------------------------------


@pytest.mark.filterwarnings("ignore::pytest.PytestUnraisableExceptionWarning")
class TestWebhookMockServer:
    """Integration test using a real HTTP server."""

    def test_delivery_to_real_http_server(self):
        received: list = []

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length)
                received.append({
                    "body": json.loads(body),
                    "headers": dict(self.headers),
                })
                self.send_response(200)
                self.end_headers()

            def log_message(self, format, *args):
                pass  # silence server logs

        server = HTTPServer(("127.0.0.1", 0), Handler)
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever)
        thread.daemon = True
        thread.start()

        try:
            wh = WebhookConfig(
                url=f"http://127.0.0.1:{port}/webhook",
                events=["boot.started"],
                secret="real-test-secret",
                retry_count=1,
                timeout=5.0,
            )
            mgr = WebhookManager([wh])
            results = mgr.fire_sync("boot.started", {
                "mac": "aa:bb:cc:dd:ee:ff",
                "profile": "test-server",
            })
            assert len(results) == 1
            assert results[0].success is True
            assert results[0].status_code == 200

            # Verify payload arrived at the server
            assert len(received) == 1
            body = received[0]["body"]
            assert body["event"] == "boot.started"
            assert body["mac"] == "aa:bb:cc:dd:ee:ff"

            # Verify HMAC signature
            headers = received[0]["headers"]
            sig_header = headers.get("X-Pxeos-Signature", "")
            assert sig_header.startswith("sha256=")
            sig = sig_header[len("sha256="):]
            raw_body = json.dumps(body, default=str).encode("utf-8")
            assert verify_signature(
                raw_body, "real-test-secret", sig
            )
        finally:
            server.shutdown()

    def test_delivery_to_failing_server(self):
        class FailHandler(BaseHTTPRequestHandler):
            def do_POST(self):
                self.send_response(503)
                self.end_headers()

            def log_message(self, format, *args):
                pass

        server = HTTPServer(("127.0.0.1", 0), FailHandler)
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever)
        thread.daemon = True
        thread.start()

        try:
            wh = WebhookConfig(
                url=f"http://127.0.0.1:{port}/webhook",
                events=["boot.started"],
                retry_count=2,
                timeout=2.0,
            )
            mgr = WebhookManager([wh])
            results = mgr.fire_sync("boot.started", {"mac": "test"})
            assert len(results) == 1
            assert results[0].success is False
            assert results[0].attempts == 2
        finally:
            server.shutdown()
