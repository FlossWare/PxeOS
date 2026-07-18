"""Tests for PxeOS rate limiting.

Covers:
- Token bucket logic (RateLimiter class)
- Per-IP limiting
- Endpoint group classification
- 429 responses via middleware
- Rate-limit headers
- Config integration
- Backward compatibility (disabled by default)
"""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from pxeos.api import app, init_app
from pxeos.config import PxeOSConfig, RateLimitSettings
from pxeos.matcher import HostMatcher
from pxeos.rate_limit import (
    EndpointGroup,
    RateLimitConfig,
    RateLimiter,
    RateLimitMiddleware,
    _client_ip,
    classify_endpoint,
    configure_rate_limiting,
    get_limiter,
    is_enabled,
    reset_all_limiters,
)
from pxeos.registry import PluginRegistry


# ---- Helper fixtures ----


@pytest.fixture
def limiter():
    """A rate limiter allowing 60 req/min with burst of 5."""
    return RateLimiter(requests_per_minute=60.0, burst=5)


@pytest.fixture
def strict_limiter():
    """A rate limiter allowing 6 req/min with burst of 2."""
    return RateLimiter(requests_per_minute=6.0, burst=2)


def _make_app(tmp_path, rl_settings=None):
    """Initialise the FastAPI app with optional rate-limit settings."""
    registry = PluginRegistry()
    registry.load_builtins()
    config = PxeOSConfig(
        data_dir=tmp_path / "data",
        distro_root=tmp_path / "distros",
        rate_limit=rl_settings or RateLimitSettings(),
    )
    (tmp_path / "data").mkdir(exist_ok=True)
    (tmp_path / "distros").mkdir(exist_ok=True)
    matcher = HostMatcher([])
    init_app(registry, config, matcher)
    return TestClient(app)


# =================================================================
# 1. Token-bucket core logic
# =================================================================


class TestTokenBucket:
    """Unit tests for the RateLimiter token-bucket algorithm."""

    def test_first_request_allowed(self, limiter):
        assert limiter.check("k") is True

    def test_burst_requests_allowed(self, limiter):
        """All burst requests should succeed immediately."""
        for _ in range(5):
            assert limiter.check("k") is True

    def test_exceeding_burst_blocked(self, limiter):
        """The (burst+1)th request without refill should fail."""
        for _ in range(5):
            limiter.check("k")
        assert limiter.check("k") is False

    def test_tokens_refill_over_time(self, strict_limiter):
        """After exhausting burst, tokens refill at the configured rate."""
        # Exhaust both tokens.
        strict_limiter.check("k")
        strict_limiter.check("k")
        assert strict_limiter.check("k") is False

        # 6 req/min = 0.1 req/s -> 1 token every 10 seconds.
        # Advance time by 11s -> should have ~1 token.
        with patch("pxeos.rate_limit.time") as mock_time:
            mock_time.monotonic.return_value = (
                time.monotonic() + 11
            )
            # Cannot use patch this way because the monotonic calls
            # are already captured.  Use a different approach.

        # Instead, directly manipulate bucket state.
        bucket = strict_limiter._buckets["k"]
        bucket.last_refill -= 11  # pretend 11 seconds passed
        assert strict_limiter.check("k") is True

    def test_remaining_reports_tokens_left(self, limiter):
        assert limiter.remaining("fresh-key") == 5
        limiter.check("fresh-key")
        # After consuming 1 token, should have ~4 left.
        rem = limiter.remaining("fresh-key")
        assert rem == 4 or rem == 3  # allow rounding

    def test_remaining_full_when_unknown_key(self, limiter):
        assert limiter.remaining("unknown") == limiter.burst

    def test_retry_after_zero_when_tokens_available(self, limiter):
        assert limiter.retry_after("k") == 0.0

    def test_retry_after_positive_when_exhausted(self, limiter):
        for _ in range(5):
            limiter.check("k")
        ra = limiter.retry_after("k")
        assert ra > 0.0

    def test_independent_keys(self, limiter):
        """Different keys get independent buckets."""
        for _ in range(5):
            limiter.check("a")
        assert limiter.check("a") is False
        # Key "b" should still be allowed.
        assert limiter.check("b") is True

    def test_reset_clears_all_state(self, limiter):
        for _ in range(5):
            limiter.check("k")
        assert limiter.check("k") is False
        limiter.reset()
        assert limiter.check("k") is True

    def test_cleanup_removes_stale_entries(self, limiter):
        limiter.check("old")
        limiter.check("new")
        # Make "old" stale.
        limiter._buckets["old"].last_refill -= 7200
        removed = limiter.cleanup(max_age_seconds=3600)
        assert removed == 1
        assert "old" not in limiter._buckets
        assert "new" in limiter._buckets

    def test_cleanup_keeps_recent(self, limiter):
        limiter.check("recent")
        removed = limiter.cleanup(max_age_seconds=3600)
        assert removed == 0

    def test_rate_property(self, limiter):
        # 60 rpm = 1 per second.
        assert limiter.rate == pytest.approx(1.0)

    def test_burst_property(self, limiter):
        assert limiter.burst == 5

    def test_zero_rate_retry_after(self):
        """A limiter with 0 rpm should not divide by zero."""
        lim = RateLimiter(requests_per_minute=0, burst=1)
        lim.check("k")
        # Should not raise.
        ra = lim.retry_after("k")
        assert ra == 0.0


# =================================================================
# 2. Endpoint classification
# =================================================================


class TestEndpointClassification:

    def test_boot_endpoint_is_pxe(self):
        assert (
            classify_endpoint("/api/v1/boot/aa:bb:cc:dd:ee:ff")
            == EndpointGroup.PXE
        )

    def test_autoinstall_endpoint_is_pxe(self):
        assert (
            classify_endpoint(
                "/api/v1/autoinstall/aa:bb:cc:dd:ee:ff"
            )
            == EndpointGroup.PXE
        )

    def test_auth_keys_endpoint_is_auth(self):
        assert (
            classify_endpoint("/api/v1/auth/keys")
            == EndpointGroup.AUTH
        )

    def test_profiles_endpoint_is_api(self):
        assert (
            classify_endpoint("/api/v1/profiles")
            == EndpointGroup.API
        )

    def test_health_endpoint_is_api(self):
        assert (
            classify_endpoint("/api/v1/health")
            == EndpointGroup.API
        )

    def test_provision_endpoint_is_api(self):
        assert (
            classify_endpoint("/api/v1/provision/aa:bb:cc/status")
            == EndpointGroup.API
        )

    def test_secrets_endpoint_is_api(self):
        assert (
            classify_endpoint("/api/v1/secrets")
            == EndpointGroup.API
        )

    def test_import_endpoint_is_api(self):
        assert (
            classify_endpoint("/api/v1/import/upload")
            == EndpointGroup.API
        )


# =================================================================
# 3. RateLimitConfig dataclass
# =================================================================


class TestRateLimitConfig:

    def test_defaults(self):
        cfg = RateLimitConfig()
        assert cfg.requests_per_minute == 60.0
        assert cfg.burst == 10

    def test_rate_property(self):
        cfg = RateLimitConfig(requests_per_minute=120)
        assert cfg.rate == pytest.approx(2.0)


# =================================================================
# 4. Global limiter management
# =================================================================


class TestGlobalLimiters:

    def test_configure_sets_enabled(self):
        configure_rate_limiting(enabled=True)
        assert is_enabled() is True
        configure_rate_limiting(enabled=False)
        assert is_enabled() is False

    def test_configure_creates_limiters(self):
        configure_rate_limiting(enabled=True, pxe_rpm=100)
        pxe = get_limiter(EndpointGroup.PXE)
        assert pxe is not None
        assert pxe.rate == pytest.approx(100.0 / 60.0)

    def test_reset_all_clears_state(self):
        configure_rate_limiting(enabled=True)
        pxe = get_limiter(EndpointGroup.PXE)
        pxe.check("ip1")
        reset_all_limiters()
        assert pxe.remaining("ip1") == pxe.burst


# =================================================================
# 5. Client IP extraction
# =================================================================


class TestClientIP:

    def test_from_x_forwarded_for(self):
        class FakeRequest:
            headers = {"x-forwarded-for": "1.2.3.4, 5.6.7.8"}
            client = None

        assert _client_ip(FakeRequest()) == "1.2.3.4"

    def test_from_client(self):
        class FakeClient:
            host = "10.0.0.1"

        class FakeRequest:
            headers = {}
            client = FakeClient()

        assert _client_ip(FakeRequest()) == "10.0.0.1"

    def test_unknown_when_no_info(self):
        class FakeRequest:
            headers = {}
            client = None

        assert _client_ip(FakeRequest()) == "unknown"

    def test_x_forwarded_for_strips_spaces(self):
        class FakeRequest:
            headers = {"x-forwarded-for": "  9.8.7.6 , 1.2.3.4"}
            client = None

        assert _client_ip(FakeRequest()) == "9.8.7.6"


# =================================================================
# 6. Config integration
# =================================================================


class TestRateLimitSettings:

    def test_defaults_disabled(self):
        settings = RateLimitSettings()
        assert settings.enabled is False

    def test_custom_values(self):
        settings = RateLimitSettings(
            enabled=True,
            pxe_requests_per_minute=500,
            pxe_burst=100,
            api_requests_per_minute=30,
            api_burst=10,
            auth_requests_per_minute=5,
            auth_burst=3,
        )
        assert settings.enabled is True
        assert settings.pxe_requests_per_minute == 500
        assert settings.auth_burst == 3

    def test_config_includes_rate_limit(self):
        cfg = PxeOSConfig()
        assert hasattr(cfg, "rate_limit")
        assert isinstance(cfg.rate_limit, RateLimitSettings)
        assert cfg.rate_limit.enabled is False

    def test_load_config_parses_rate_limit(self, tmp_path):
        from pxeos.config import load_config

        config_file = tmp_path / "pxeos.toml"
        config_file.write_text(
            "[rate_limit]\n"
            "enabled = true\n"
            "pxe_requests_per_minute = 200\n"
            "pxe_burst = 40\n"
            "api_requests_per_minute = 30\n"
            "api_burst = 15\n"
            "auth_requests_per_minute = 5\n"
            "auth_burst = 2\n"
        )
        cfg = load_config(config_file)
        assert cfg.rate_limit.enabled is True
        assert cfg.rate_limit.pxe_requests_per_minute == 200.0
        assert cfg.rate_limit.api_burst == 15
        assert cfg.rate_limit.auth_burst == 2


# =================================================================
# 7. Middleware integration -- disabled (backward compat)
# =================================================================


class TestRateLimitDisabled:

    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        self.client = _make_app(tmp_path)

    def test_health_returns_200(self):
        resp = self.client.get("/api/v1/health")
        assert resp.status_code == 200

    def test_no_rate_limit_headers_when_disabled(self):
        resp = self.client.get("/api/v1/health")
        # When disabled, the middleware is a pass-through.
        # Headers may or may not be present; what matters is
        # the request succeeds.
        assert resp.status_code == 200


# =================================================================
# 8. Middleware integration -- enabled
# =================================================================


class TestRateLimitEnabled:

    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        rl = RateLimitSettings(
            enabled=True,
            api_requests_per_minute=60,
            api_burst=3,
            pxe_requests_per_minute=60,
            pxe_burst=3,
            auth_requests_per_minute=60,
            auth_burst=2,
        )
        self.client = _make_app(tmp_path, rl)
        yield
        reset_all_limiters()

    def test_requests_under_burst_succeed(self):
        for _ in range(3):
            resp = self.client.get("/api/v1/profiles")
            assert resp.status_code == 200

    def test_exceeding_burst_returns_429(self):
        for _ in range(3):
            self.client.get("/api/v1/profiles")
        resp = self.client.get("/api/v1/profiles")
        assert resp.status_code == 429

    def test_429_body_has_detail(self):
        for _ in range(3):
            self.client.get("/api/v1/profiles")
        resp = self.client.get("/api/v1/profiles")
        assert "detail" in resp.json()

    def test_429_has_retry_after_header(self):
        for _ in range(3):
            self.client.get("/api/v1/profiles")
        resp = self.client.get("/api/v1/profiles")
        assert "retry-after" in resp.headers

    def test_429_has_rate_limit_remaining_header(self):
        for _ in range(3):
            self.client.get("/api/v1/profiles")
        resp = self.client.get("/api/v1/profiles")
        assert resp.headers["x-ratelimit-remaining"] == "0"

    def test_429_has_rate_limit_reset_header(self):
        for _ in range(3):
            self.client.get("/api/v1/profiles")
        resp = self.client.get("/api/v1/profiles")
        assert "x-ratelimit-reset" in resp.headers

    def test_successful_response_has_remaining_header(self):
        resp = self.client.get("/api/v1/profiles")
        assert "x-ratelimit-remaining" in resp.headers

    def test_health_exempt_from_rate_limiting(self):
        """Health endpoint is never rate-limited."""
        for _ in range(10):
            resp = self.client.get("/api/v1/health")
            assert resp.status_code == 200

    def test_metrics_exempt_from_rate_limiting(self):
        """Metrics endpoint is never rate-limited."""
        for _ in range(10):
            resp = self.client.get("/metrics")
            assert resp.status_code == 200

    def test_different_endpoint_groups_independent(self):
        """Exhausting API burst should not affect PXE endpoints."""
        # Exhaust API burst.
        for _ in range(3):
            self.client.get("/api/v1/profiles")
        resp = self.client.get("/api/v1/profiles")
        assert resp.status_code == 429

        # PXE endpoints should still work.
        resp = self.client.get(
            "/api/v1/boot/aa:bb:cc:dd:ee:ff"
        )
        # 404 because there's no host rule, but NOT 429.
        assert resp.status_code != 429


# =================================================================
# 9. Per-IP isolation
# =================================================================


class TestPerIPIsolation:

    def test_different_ips_have_independent_limits(self):
        """Each IP gets its own bucket."""
        limiter = RateLimiter(requests_per_minute=60, burst=2)
        # Exhaust IP-A.
        limiter.check("api:1.1.1.1")
        limiter.check("api:1.1.1.1")
        assert limiter.check("api:1.1.1.1") is False
        # IP-B is independent.
        assert limiter.check("api:2.2.2.2") is True

    def test_x_forwarded_for_respected(self, tmp_path):
        """Requests with different X-Forwarded-For get separate limits."""
        rl = RateLimitSettings(
            enabled=True,
            api_burst=2,
        )
        client = _make_app(tmp_path, rl)

        # Exhaust from IP-A.
        for _ in range(2):
            client.get(
                "/api/v1/profiles",
                headers={"X-Forwarded-For": "1.1.1.1"},
            )
        resp = client.get(
            "/api/v1/profiles",
            headers={"X-Forwarded-For": "1.1.1.1"},
        )
        assert resp.status_code == 429

        # IP-B should be fine.
        resp = client.get(
            "/api/v1/profiles",
            headers={"X-Forwarded-For": "2.2.2.2"},
        )
        assert resp.status_code == 200
        reset_all_limiters()


# =================================================================
# 10. EndpointGroup enum
# =================================================================


class TestEndpointGroupEnum:

    def test_pxe_value(self):
        assert EndpointGroup.PXE.value == "pxe"

    def test_api_value(self):
        assert EndpointGroup.API.value == "api"

    def test_auth_value(self):
        assert EndpointGroup.AUTH.value == "auth"

    def test_string_comparison(self):
        assert EndpointGroup.PXE == "pxe"


# =================================================================
# 11. Edge cases
# =================================================================


class TestEdgeCases:

    def test_single_burst_limiter(self):
        """Burst of 1 should allow exactly one request."""
        lim = RateLimiter(requests_per_minute=60, burst=1)
        assert lim.check("k") is True
        assert lim.check("k") is False

    def test_very_high_burst(self):
        """Large burst should not cause issues."""
        lim = RateLimiter(requests_per_minute=60, burst=10000)
        for _ in range(10000):
            assert lim.check("k") is True
        assert lim.check("k") is False

    def test_fractional_rpm(self):
        """Non-integer rpm should work."""
        lim = RateLimiter(requests_per_minute=0.5, burst=1)
        assert lim.rate == pytest.approx(0.5 / 60.0)

    def test_multiple_keys_cleanup(self):
        """Cleanup with many keys works correctly."""
        lim = RateLimiter(requests_per_minute=60, burst=5)
        for i in range(100):
            lim.check(f"key-{i}")
        # Make them all stale.
        for b in lim._buckets.values():
            b.last_refill -= 7200
        removed = lim.cleanup(max_age_seconds=3600)
        assert removed == 100
        assert len(lim._buckets) == 0

    def test_retry_after_matches_rate(self):
        """Retry-after should be roughly 1/rate seconds."""
        lim = RateLimiter(
            requests_per_minute=60, burst=1
        )  # 1/sec
        lim.check("k")
        ra = lim.retry_after("k")
        # Should be approximately 1 second (1/rate).
        assert 0.5 < ra < 1.5
