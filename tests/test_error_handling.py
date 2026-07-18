"""Tests for --dry-run support, input validation, and improved error messages."""

from __future__ import annotations

import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from pxeos.cli import _build_parser, main
from pxeos.config import PxeOSConfig, load_config
from pxeos.models import HostRule
from pxeos.validation import normalize_mac, validate_mac, validate_os_family


# ---------------------------------------------------------------------------
# MAC address validation
# ---------------------------------------------------------------------------


class TestMacValidation:
    """Tests for MAC address validation helper."""

    def test_valid_colon_separated(self):
        valid, err = validate_mac("aa:bb:cc:dd:ee:ff")
        assert valid is True
        assert err == ""

    def test_valid_dash_separated(self):
        valid, err = validate_mac("AA-BB-CC-DD-EE-FF")
        assert valid is True
        assert err == ""

    def test_valid_mixed_case(self):
        valid, err = validate_mac("aA:bB:cC:dD:eE:fF")
        assert valid is True
        assert err == ""

    def test_invalid_too_short(self):
        valid, err = validate_mac("aa:bb:cc")
        assert valid is False
        assert "invalid MAC address format" in err

    def test_invalid_bad_chars(self):
        valid, err = validate_mac("gg:hh:ii:jj:kk:ll")
        assert valid is False
        assert "invalid MAC address format" in err

    def test_invalid_no_separators(self):
        valid, err = validate_mac("aabbccddeeff")
        assert valid is False
        assert "invalid MAC address format" in err

    def test_invalid_empty(self):
        valid, err = validate_mac("")
        assert valid is False

    def test_normalize_lowercase_colon(self):
        assert normalize_mac("AA-BB-CC-DD-EE-FF") == "aa:bb:cc:dd:ee:ff"

    def test_normalize_preserves_valid(self):
        assert normalize_mac("aa:bb:cc:dd:ee:ff") == "aa:bb:cc:dd:ee:ff"

    def test_normalize_strips_whitespace(self):
        assert normalize_mac("  aa:bb:cc:dd:ee:ff  ") == "aa:bb:cc:dd:ee:ff"


# ---------------------------------------------------------------------------
# os_family validation
# ---------------------------------------------------------------------------


class TestOsFamilyValidation:
    """Tests for os_family validation helper."""

    def test_valid_family(self):
        valid, err = validate_os_family("fedora", ["fedora", "debian", "ubuntu"])
        assert valid is True
        assert err == ""

    def test_valid_case_insensitive(self):
        valid, err = validate_os_family("Fedora", ["fedora", "debian"])
        assert valid is True

    def test_invalid_family(self):
        valid, err = validate_os_family("gentoo", ["fedora", "debian", "ubuntu"])
        assert valid is False
        assert "unknown os_family" in err
        assert "fedora" in err
        assert "debian" in err

    def test_empty_available_list(self):
        valid, err = validate_os_family("fedora", [])
        assert valid is False


# ---------------------------------------------------------------------------
# --dry-run for import
# ---------------------------------------------------------------------------


class TestImportDryRun:
    """Tests for pxeos import --dry-run."""

    @patch("pxeos.cli._init_stack")
    def test_dry_run_iso_shows_preview(self, mock_init, tmp_path, capsys):
        """--dry-run shows what would be imported without extracting."""
        iso = tmp_path / "test.iso"
        iso.write_bytes(b"\x00" * 1024)

        registry = MagicMock()
        plugin = MagicMock()
        plugin.os_family = "fedora"
        plugin.supports_live = False
        registry.get.return_value = plugin
        registry.available = ["fedora", "debian"]

        config = PxeOSConfig(
            data_dir=tmp_path / "data",
            distro_root=tmp_path / "distros",
        )
        matcher = MagicMock()
        mock_init.return_value = (config, registry, matcher)

        rc = main([
            "--config", str(tmp_path / "pxeos.toml"),
            "import", "--iso", str(iso),
            "--os", "fedora", "--version", "42",
            "--dry-run",
        ])

        assert rc == 0
        out = capsys.readouterr().out
        assert "[dry-run]" in out
        assert "fedora" in out
        assert "42" in out
        assert "No files extracted" in out

    @patch("pxeos.cli._init_stack")
    @patch("pxeos.importer.subprocess.run")
    def test_dry_run_does_not_mount(self, mock_run, mock_init, tmp_path, capsys):
        """--dry-run must not call mount or extract."""
        iso = tmp_path / "test.iso"
        iso.write_bytes(b"\x00" * 1024)

        registry = MagicMock()
        plugin = MagicMock()
        plugin.os_family = "fedora"
        plugin.supports_live = False
        registry.get.return_value = plugin
        registry.available = ["fedora"]

        config = PxeOSConfig(
            data_dir=tmp_path / "data",
            distro_root=tmp_path / "distros",
        )
        matcher = MagicMock()
        mock_init.return_value = (config, registry, matcher)

        main([
            "--config", str(tmp_path / "pxeos.toml"),
            "import", "--iso", str(iso),
            "--os", "fedora", "--version", "42",
            "--dry-run",
        ])

        # subprocess.run should NOT have been called (no mount/umount)
        mock_run.assert_not_called()


# ---------------------------------------------------------------------------
# --dry-run for provision
# ---------------------------------------------------------------------------


class TestProvisionDryRun:
    """Tests for pxeos provision --dry-run."""

    @patch("pxeos.cli._init_stack")
    def test_dry_run_shows_preview(self, mock_init, tmp_path, capsys):
        """--dry-run shows matching rule info without tracking state."""
        registry = MagicMock()
        plugin = MagicMock()
        plugin.os_family = "fedora"
        registry.get.return_value = plugin
        registry.available = ["fedora"]

        config = PxeOSConfig(data_dir=tmp_path / "data")

        rule = HostRule(
            profile="test-server",
            os_family="fedora",
            os_version="42",
            priority=10,
            mac="aa:bb:cc:dd:ee:ff",
        )
        matcher = MagicMock()
        matcher._rules = [rule]
        matcher.match.return_value = rule

        mock_init.return_value = (config, registry, matcher)

        rc = main([
            "--config", str(tmp_path / "pxeos.toml"),
            "provision", "--mac", "aa:bb:cc:dd:ee:ff", "--dry-run",
        ])

        assert rc == 0
        out = capsys.readouterr().out
        assert "[dry-run]" in out
        assert "test-server" in out
        assert "fedora" in out
        assert "No state tracked" in out

    @patch("pxeos.cli._init_stack")
    def test_dry_run_no_matching_rule(self, mock_init, tmp_path, capsys):
        """--dry-run reports error when no rule matches."""
        registry = MagicMock()
        registry.available = ["fedora"]

        config = PxeOSConfig(data_dir=tmp_path / "data")
        matcher = MagicMock()
        matcher._rules = []
        matcher.match.return_value = None

        mock_init.return_value = (config, registry, matcher)

        rc = main([
            "--config", str(tmp_path / "pxeos.toml"),
            "provision", "--mac", "aa:bb:cc:dd:ee:ff", "--dry-run",
        ])

        assert rc == 1
        err = capsys.readouterr().err
        assert "no matching host rule" in err

    @patch("pxeos.cli._init_stack")
    def test_provision_invalid_mac(self, mock_init, tmp_path, capsys):
        """Invalid MAC format is rejected."""
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
        assert "invalid MAC address format" in err


# ---------------------------------------------------------------------------
# Error messages for missing ISO
# ---------------------------------------------------------------------------


class TestMissingIso:
    """Tests for clear error when ISO file does not exist."""

    @patch("pxeos.cli._init_stack")
    def test_missing_iso_error_message(self, mock_init, tmp_path, capsys):
        """Reports clear error with path when ISO is missing."""
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


# ---------------------------------------------------------------------------
# Error messages for unknown OS family
# ---------------------------------------------------------------------------


class TestUnknownOsFamily:
    """Tests for error when plugin is not found for os_family."""

    def test_registry_get_unknown_lists_available(self):
        """registry.get() error shows available plugins."""
        from pxeos.registry import PluginRegistry

        reg = PluginRegistry()
        reg.load_builtins()

        with pytest.raises(ValueError, match="available"):
            reg.get("beos")


# ---------------------------------------------------------------------------
# Malformed config handling
# ---------------------------------------------------------------------------


class TestMalformedConfig:
    """Tests for error messages on malformed config files."""

    def test_malformed_toml_config(self, tmp_path):
        """load_config raises ValueError with file path on malformed TOML."""
        bad = tmp_path / "bad.toml"
        bad.write_text("[server\nhost = oops")

        with pytest.raises(ValueError, match="malformed config file"):
            load_config(bad)

    def test_malformed_hosts_file(self, tmp_path):
        """load_hosts raises ValueError with file path on malformed TOML."""
        from pxeos.config import load_hosts

        bad = tmp_path / "hosts.toml"
        bad.write_text("[[host]\nprofile = oops")

        with pytest.raises(ValueError, match="malformed hosts file"):
            load_hosts(bad)

    def test_malformed_profile_file(self, tmp_path):
        """load_profile raises ValueError with file path on malformed TOML."""
        from pxeos.config import load_profile

        bad = tmp_path / "profile.toml"
        bad.write_text("[profile\nname = oops")

        with pytest.raises(ValueError, match="malformed profile file"):
            load_profile(bad)


# ---------------------------------------------------------------------------
# API MAC validation (via TestClient)
# ---------------------------------------------------------------------------


class TestApiMacValidation:
    """Tests for MAC validation in API endpoints."""

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path):
        from pxeos.api import app, init_app
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

    def test_boot_invalid_mac_returns_422(self, client):
        """GET /api/v1/boot/<bad-mac> returns 422."""
        resp = client.get("/api/v1/boot/not-a-mac-address")
        assert resp.status_code == 422

    def test_boot_valid_mac_does_not_422(self, client):
        """GET /api/v1/boot/<good-mac> should not return 422."""
        resp = client.get("/api/v1/boot/aa:bb:cc:dd:ee:ff")
        # Will be 404 (no rule) but NOT 422
        assert resp.status_code != 422

    def test_register_host_invalid_os_family(self, client):
        """POST /api/v1/hosts with unknown os_family returns 422."""
        resp = client.post("/api/v1/hosts", json={
            "profile": "test",
            "os_family": "beos",
            "os_version": "5",
        })
        assert resp.status_code == 422
        assert "unknown os_family" in resp.json()["detail"]

    def test_register_host_invalid_mac_format(self, client):
        """POST /api/v1/hosts with bad MAC format returns 422."""
        resp = client.post("/api/v1/hosts", json={
            "profile": "test",
            "os_family": "fedora",
            "os_version": "42",
            "mac": "not-a-mac",
        })
        assert resp.status_code == 422

    def test_provision_status_invalid_mac(self, client):
        """GET /api/v1/provision/<bad-mac>/status returns 422."""
        resp = client.get("/api/v1/provision/xyz/status")
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Parser structure for provision subcommand
# ---------------------------------------------------------------------------


class TestProvisionParser:
    """Tests for the provision argument parser."""

    def test_provision_subcommand_exists(self):
        """Parser includes the provision subcommand."""
        parser = _build_parser()
        args = parser.parse_args([
            "provision", "--mac", "aa:bb:cc:dd:ee:ff",
        ])
        assert args.command == "provision"
        assert args.mac == "aa:bb:cc:dd:ee:ff"

    def test_provision_dry_run_flag(self):
        """provision --dry-run flag is parsed."""
        parser = _build_parser()
        args = parser.parse_args([
            "provision", "--mac", "aa:bb:cc:dd:ee:ff", "--dry-run",
        ])
        assert args.dry_run is True

    def test_import_dry_run_flag(self):
        """import --dry-run flag is parsed."""
        parser = _build_parser()
        args = parser.parse_args([
            "import", "--iso", "/tmp/test.iso",
            "--os", "fedora", "--version", "42",
            "--dry-run",
        ])
        assert args.dry_run is True
