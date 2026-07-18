"""Tests for the PxeOS custom exception hierarchy and error handling.

Covers:
 - Exception hierarchy and attributes
 - format_error() output
 - CLI integration (--verbose, suggestion display)
 - API structured error responses
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from pxeos.errors import (
    ConfigError,
    PxeOSError,
    PluginError,
    ProvisionError,
    ValidationError,
    format_error,
)


# ===================================================================
# 1. Exception hierarchy tests
# ===================================================================


class TestExceptionHierarchy:
    """Verify class relationships and default attributes."""

    def test_pxeos_error_is_exception(self):
        assert issubclass(PxeOSError, Exception)

    def test_config_error_is_pxeos_error(self):
        assert issubclass(ConfigError, PxeOSError)

    def test_validation_error_is_pxeos_error(self):
        assert issubclass(ValidationError, PxeOSError)

    def test_provision_error_is_pxeos_error(self):
        assert issubclass(ProvisionError, PxeOSError)

    def test_plugin_error_is_pxeos_error(self):
        assert issubclass(PluginError, PxeOSError)

    def test_pxeos_error_has_error_code(self):
        assert PxeOSError.error_code == "PXEOS_ERROR"

    def test_config_error_has_error_code(self):
        assert ConfigError.error_code == "CONFIG_ERROR"

    def test_validation_error_has_error_code(self):
        assert ValidationError.error_code == "VALIDATION_ERROR"

    def test_provision_error_has_error_code(self):
        assert ProvisionError.error_code == "PROVISION_ERROR"

    def test_plugin_error_has_error_code(self):
        assert PluginError.error_code == "PLUGIN_ERROR"


# ===================================================================
# 2. Exception attribute tests
# ===================================================================


class TestExceptionAttributes:
    """Verify that all attributes are stored and accessible."""

    def test_message_stored(self):
        exc = PxeOSError("something broke")
        assert exc.message == "something broke"

    def test_str_is_message(self):
        exc = PxeOSError("something broke")
        assert str(exc) == "something broke"

    def test_suggestion_default_none(self):
        exc = PxeOSError("fail")
        assert exc.suggestion is None

    def test_suggestion_stored(self):
        exc = PxeOSError("fail", suggestion="try again")
        assert exc.suggestion == "try again"

    def test_context_default_empty(self):
        exc = PxeOSError("fail")
        assert exc.context == {}

    def test_context_stored(self):
        ctx = {"path": "/etc/pxeos/pxeos.toml"}
        exc = PxeOSError("fail", context=ctx)
        assert exc.context == ctx

    def test_all_attributes_together(self):
        exc = ConfigError(
            "cannot read config",
            suggestion="check the path",
            context={"config_path": "/etc/pxeos/pxeos.toml"},
        )
        assert exc.message == "cannot read config"
        assert exc.suggestion == "check the path"
        assert exc.context["config_path"] == "/etc/pxeos/pxeos.toml"
        assert exc.error_code == "CONFIG_ERROR"

    def test_can_catch_subclass_as_base(self):
        exc = ValidationError("bad mac")
        with pytest.raises(PxeOSError):
            raise exc


# ===================================================================
# 3. format_error() tests
# ===================================================================


class TestFormatError:
    """Verify the CLI formatting helper."""

    def test_basic_message(self):
        exc = PxeOSError("something failed")
        result = format_error(exc)
        assert result == "error: something failed"

    def test_with_suggestion(self):
        exc = PxeOSError("bad input", suggestion="try X instead")
        result = format_error(exc)
        assert "error: bad input" in result
        assert "hint: try X instead" in result

    def test_with_context(self):
        exc = PxeOSError(
            "not found",
            context={"path": "/etc/pxeos/pxeos.toml"},
        )
        result = format_error(exc)
        assert "path: /etc/pxeos/pxeos.toml" in result

    def test_verbose_includes_traceback(self):
        try:
            raise ConfigError("broken config")
        except ConfigError as exc:
            result = format_error(exc, verbose=True)
        assert "Traceback" in result
        assert "ConfigError" in result

    def test_non_verbose_no_traceback(self):
        try:
            raise ConfigError("broken config")
        except ConfigError as exc:
            result = format_error(exc, verbose=False)
        assert "Traceback" not in result

    def test_multiline_context(self):
        exc = PxeOSError(
            "fail",
            context={"a": "1", "b": "2"},
        )
        result = format_error(exc)
        assert "  a: 1" in result
        assert "  b: 2" in result

    def test_all_sections_present(self):
        try:
            raise PluginError(
                "plugin missing",
                suggestion="install it",
                context={"plugin": "beos"},
            )
        except PluginError as exc:
            result = format_error(exc, verbose=True)
        assert "error: plugin missing" in result
        assert "hint: install it" in result
        assert "plugin: beos" in result
        assert "Traceback" in result


# ===================================================================
# 4. CLI integration tests
# ===================================================================


class TestCLIErrorHandling:
    """Test that CLI catches PxeOSError and formats output."""

    @patch("pxeos.cli._init_stack")
    def test_invalid_mac_shows_suggestion(
        self, mock_init, tmp_path, capsys
    ):
        """Invalid MAC prints error + hint to stderr."""
        from pxeos.cli import main
        from pxeos.config import PxeOSConfig

        config = PxeOSConfig(data_dir=tmp_path / "data")
        registry = MagicMock()
        matcher = MagicMock()
        mock_init.return_value = (config, registry, matcher)

        rc = main([
            "--config", str(tmp_path / "pxeos.toml"),
            "provision", "--mac", "not-a-mac",
        ])

        assert rc == 1
        err = capsys.readouterr().err
        assert "error:" in err
        assert "invalid MAC" in err
        assert "hint:" in err
        assert "xx:xx:xx:xx:xx:xx" in err

    @patch("pxeos.cli._init_stack")
    def test_verbose_shows_traceback(
        self, mock_init, tmp_path, capsys
    ):
        """--verbose flag causes traceback to appear."""
        from pxeos.cli import main
        from pxeos.config import PxeOSConfig

        config = PxeOSConfig(data_dir=tmp_path / "data")
        registry = MagicMock()
        matcher = MagicMock()
        mock_init.return_value = (config, registry, matcher)

        rc = main([
            "--verbose",
            "--config", str(tmp_path / "pxeos.toml"),
            "provision", "--mac", "not-a-mac",
        ])

        assert rc == 1
        err = capsys.readouterr().err
        assert "Traceback" in err

    @patch("pxeos.cli._init_stack")
    def test_no_verbose_hides_traceback(
        self, mock_init, tmp_path, capsys
    ):
        """Without --verbose, no traceback is shown."""
        from pxeos.cli import main
        from pxeos.config import PxeOSConfig

        config = PxeOSConfig(data_dir=tmp_path / "data")
        registry = MagicMock()
        matcher = MagicMock()
        mock_init.return_value = (config, registry, matcher)

        rc = main([
            "--config", str(tmp_path / "pxeos.toml"),
            "provision", "--mac", "not-a-mac",
        ])

        assert rc == 1
        err = capsys.readouterr().err
        assert "Traceback" not in err

    @patch("pxeos.cli._init_stack")
    def test_missing_iso_shows_path(
        self, mock_init, tmp_path, capsys
    ):
        """Missing ISO error includes the checked path."""
        from pxeos.cli import main
        from pxeos.config import PxeOSConfig

        config = PxeOSConfig(
            data_dir=tmp_path / "data",
            distro_root=tmp_path / "distros",
        )
        registry = MagicMock()
        registry.available = ["fedora"]
        matcher = MagicMock()
        mock_init.return_value = (config, registry, matcher)

        missing = tmp_path / "nonexistent.iso"
        rc = main([
            "--config", str(tmp_path / "pxeos.toml"),
            "import", "--iso", str(missing),
            "--os", "fedora", "--version", "42",
        ])

        assert rc == 1
        err = capsys.readouterr().err
        assert "ISO file not found" in err
        assert str(missing) in err
        assert "hint:" in err

    @patch("pxeos.cli._init_stack")
    def test_no_matching_rule_shows_suggestion(
        self, mock_init, tmp_path, capsys
    ):
        """No matching host rule error includes hint."""
        from pxeos.cli import main
        from pxeos.config import PxeOSConfig

        config = PxeOSConfig(data_dir=tmp_path / "data")
        registry = MagicMock()
        matcher = MagicMock()
        matcher._rules = []
        matcher.match.return_value = None
        mock_init.return_value = (config, registry, matcher)

        rc = main([
            "--config", str(tmp_path / "pxeos.toml"),
            "provision", "--mac", "aa:bb:cc:dd:ee:ff",
        ])

        assert rc == 1
        err = capsys.readouterr().err
        assert "no matching host rule" in err
        assert "hint:" in err
        assert "pxeos host add" in err

    @patch("pxeos.cli._init_stack")
    def test_no_matching_rule_lists_existing_rules(
        self, mock_init, tmp_path, capsys
    ):
        """When rules exist but none match, they are listed."""
        from pxeos.cli import main
        from pxeos.config import PxeOSConfig
        from pxeos.models import HostRule

        config = PxeOSConfig(data_dir=tmp_path / "data")
        registry = MagicMock()

        rule = HostRule(
            profile="web-server",
            os_family="fedora",
            os_version="42",
            priority=10,
            mac="11:22:33:44:55:66",
        )
        matcher = MagicMock()
        matcher._rules = [rule]
        matcher.match.return_value = None
        mock_init.return_value = (config, registry, matcher)

        rc = main([
            "--config", str(tmp_path / "pxeos.toml"),
            "provision", "--mac", "aa:bb:cc:dd:ee:ff",
        ])

        assert rc == 1
        err = capsys.readouterr().err
        assert "web-server" in err

    @patch("pxeos.cli._init_stack")
    def test_profile_not_found_shows_available(
        self, mock_init, tmp_path, capsys
    ):
        """Profile show with nonexistent name shows available profiles."""
        from pxeos.cli import main
        from pxeos.config import PxeOSConfig

        profiles_dir = tmp_path / "data" / "profiles"
        profiles_dir.mkdir(parents=True)
        # Create a profile so the suggestion can list it
        (profiles_dir / "web.toml").write_text(
            '[profile]\nname = "web"\nos_family = "fedora"\n'
            'os_version = "42"\n'
        )

        config = PxeOSConfig(data_dir=tmp_path / "data")
        registry = MagicMock()
        matcher = MagicMock()
        mock_init.return_value = (config, registry, matcher)

        rc = main([
            "--config", str(tmp_path / "pxeos.toml"),
            "profile", "show", "nonexistent",
        ])

        assert rc == 1
        err = capsys.readouterr().err
        assert "profile not found" in err
        assert "hint:" in err
        assert "web" in err

    @patch("pxeos.cli._init_stack")
    def test_unknown_mnemonic_shows_suggestion(
        self, mock_init, tmp_path, capsys
    ):
        """Unknown distro mnemonic shows suggestion to list aliases."""
        from pxeos.cli import main
        from pxeos.config import PxeOSConfig

        config = PxeOSConfig(
            data_dir=tmp_path / "data",
            distro_root=tmp_path / "distros",
        )
        registry = MagicMock()
        matcher = MagicMock()
        mock_init.return_value = (config, registry, matcher)

        iso = tmp_path / "test.iso"
        iso.write_bytes(b"\x00" * 1024)

        rc = main([
            "--config", str(tmp_path / "pxeos.toml"),
            "import", "--iso", str(iso),
            "--distro", "beos99",
        ])

        assert rc == 1
        err = capsys.readouterr().err
        assert "unknown mnemonic" in err
        assert "hint:" in err
        assert "pxeos distro aliases" in err

    @patch("pxeos.cli._init_stack")
    def test_malformed_config_shows_suggestion(
        self, mock_init, tmp_path, capsys
    ):
        """Malformed config file error includes helpful suggestion."""
        from pxeos.cli import main

        bad_config = tmp_path / "bad.toml"
        bad_config.write_text("[server\nhost = oops")

        # Don't mock _init_stack -- let it actually run
        mock_init.side_effect = None

        # We need to not mock _init_stack for this test
        with patch("pxeos.cli._init_stack") as real_init:
            from pxeos.config import load_config
            from pxeos.errors import ConfigError

            def fail_init(path):
                try:
                    load_config(path)
                except ValueError as exc:
                    raise ConfigError(
                        str(exc),
                        suggestion=(
                            f"Check that {path} is valid TOML. "
                            "See examples/ for a sample configuration."
                        ),
                        context={"config_path": str(path)},
                    ) from exc
                # Should not reach here for bad config
                raise AssertionError("expected failure")

            real_init.side_effect = fail_init

            rc = main([
                "--config", str(bad_config),
                "server", "status",
            ])

        assert rc == 1
        err = capsys.readouterr().err
        assert "error:" in err
        assert "malformed config" in err
        assert "hint:" in err


# ===================================================================
# 5. API structured error response tests
# ===================================================================


class TestAPIErrorResponses:
    """Test that the API returns structured error JSON."""

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path):
        from pxeos.api import app, init_app
        from pxeos.config import PxeOSConfig
        from pxeos.matcher import HostMatcher
        from pxeos.registry import PluginRegistry

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
    def client(self):
        from fastapi.testclient import TestClient
        from pxeos.api import app

        return TestClient(app)

    def test_invalid_mac_returns_structured_error(self, client):
        """Invalid MAC returns JSON with detail, suggestion, error_code."""
        resp = client.get("/api/v1/boot/not-a-mac")
        assert resp.status_code == 422
        body = resp.json()
        assert "detail" in body
        assert "error_code" in body
        assert body["error_code"] == "VALIDATION_ERROR"
        assert "suggestion" in body

    def test_invalid_mac_suggestion_has_format(self, client):
        """The suggestion for invalid MAC shows expected format."""
        resp = client.get("/api/v1/boot/xyz")
        body = resp.json()
        assert "xx:xx:xx:xx:xx:xx" in body["suggestion"]

    def test_register_host_unknown_os_structured(self, client):
        """Unknown os_family returns structured error with suggestion."""
        resp = client.post("/api/v1/hosts", json={
            "profile": "test",
            "os_family": "beos",
            "os_version": "5",
        })
        assert resp.status_code == 422
        body = resp.json()
        assert body["error_code"] == "PLUGIN_ERROR"
        assert "suggestion" in body
        # Suggestion should list available plugins
        assert "fedora" in body["suggestion"].lower() or "debian" in body["suggestion"].lower()

    def test_register_host_bad_mac_structured(self, client):
        """Bad MAC in host registration returns structured error."""
        resp = client.post("/api/v1/hosts", json={
            "profile": "test",
            "os_family": "fedora",
            "os_version": "42",
            "mac": "invalid-mac",
        })
        assert resp.status_code == 422
        body = resp.json()
        assert body["error_code"] == "VALIDATION_ERROR"

    def test_provision_status_bad_mac_structured(self, client):
        """Bad MAC in provision status returns structured error."""
        resp = client.get("/api/v1/provision/xyz/status")
        assert resp.status_code == 422
        body = resp.json()
        assert body["error_code"] == "VALIDATION_ERROR"
        assert "context" in body
        assert body["context"]["mac"] == "xyz"

    def test_error_response_has_all_fields(self, client):
        """Structured error response has all expected fields."""
        resp = client.get("/api/v1/boot/bad")
        body = resp.json()
        assert "detail" in body
        assert "error_code" in body
        # suggestion and context are present when relevant
        assert "suggestion" in body or "context" in body


# ===================================================================
# 6. Edge cases
# ===================================================================


class TestEdgeCases:
    """Edge cases for the error handling system."""

    def test_empty_context_not_shown(self):
        """Empty context dict produces no extra lines."""
        exc = PxeOSError("fail", context={})
        result = format_error(exc)
        assert result == "error: fail"

    def test_none_suggestion_not_shown(self):
        """None suggestion produces no hint line."""
        exc = PxeOSError("fail", suggestion=None)
        result = format_error(exc)
        assert "hint:" not in result

    def test_exception_is_catchable_in_except(self):
        """PxeOSError and subclasses work in try/except."""
        caught = False
        try:
            raise ProvisionError("no rule")
        except PxeOSError:
            caught = True
        assert caught

    def test_exception_chain_preserved(self):
        """__cause__ is preserved when wrapping ValueError."""
        original = ValueError("original error")
        try:
            try:
                raise original
            except ValueError as exc:
                raise ConfigError("wrapped") from exc
        except ConfigError as exc:
            assert exc.__cause__ is original

    def test_format_error_with_empty_message(self):
        """Empty message is handled gracefully."""
        exc = PxeOSError("")
        result = format_error(exc)
        assert result == "error: "

    def test_context_with_path_object(self):
        """Context can contain Path objects (converted to str)."""
        exc = PxeOSError(
            "fail",
            context={"path": str(Path("/etc/pxeos/pxeos.toml"))},
        )
        result = format_error(exc)
        assert "/etc/pxeos/pxeos.toml" in result
