"""Tests for pxeos.cli -- argument parsing, subcommands, and main dispatch."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from pxeos.cli import _build_parser, main


# ---------------------------------------------------------------------------
# _build_parser
# ---------------------------------------------------------------------------

class TestBuildParser:
    """Tests for the argument parser structure."""

    def test_parser_prog_name(self):
        """Parser prog is 'pxeos'."""
        parser = _build_parser()
        assert parser.prog == "pxeos"

    def test_has_expected_subcommands(self):
        """Parser has server, import, profile, host, client subcommands."""
        parser = _build_parser()

        # Extract the subparser actions to get registered subcommand names
        subparser_action = None
        for action in parser._subparsers._actions:
            if hasattr(action, "_parser_class"):
                subparser_action = action
                break

        assert subparser_action is not None
        registered = set(subparser_action.choices.keys())
        expected = {"server", "import", "profile", "host", "client"}
        assert expected == registered

    def test_config_default_path(self):
        """--config defaults to /etc/pxeos/pxeos.toml."""
        parser = _build_parser()
        args = parser.parse_args(["server", "status"])
        assert args.config == Path("/etc/pxeos/pxeos.toml")

    def test_config_custom_path(self):
        """--config accepts a custom path."""
        parser = _build_parser()
        args = parser.parse_args(["--config", "/tmp/custom.toml", "server", "status"])
        assert args.config == Path("/tmp/custom.toml")

    def test_import_requires_os_and_version(self):
        """'import' subcommand requires --os and --version."""
        parser = _build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["import", "--iso", "/tmp/test.iso"])

    def test_import_iso_and_url_mutually_exclusive(self):
        """'import' subcommand does not allow both --iso and --url."""
        parser = _build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args([
                "import",
                "--iso", "/tmp/test.iso",
                "--url", "http://example.com",
                "--os", "fedora",
                "--version", "40",
            ])

    def test_import_parses_iso_args(self):
        """'import --iso' correctly parses all arguments."""
        parser = _build_parser()
        args = parser.parse_args([
            "import",
            "--iso", "/images/fedora-40.iso",
            "--os", "fedora",
            "--version", "40",
            "--arch", "aarch64",
        ])
        assert args.command == "import"
        assert args.iso == Path("/images/fedora-40.iso")
        assert args.os_family == "fedora"
        assert args.os_version == "40"
        assert args.arch == "aarch64"

    def test_import_default_arch(self):
        """'import' defaults arch to x86_64."""
        parser = _build_parser()
        args = parser.parse_args([
            "import",
            "--url", "http://example.com",
            "--os", "debian",
            "--version", "12",
        ])
        assert args.arch == "x86_64"


# ---------------------------------------------------------------------------
# main() -- help, version, no args
# ---------------------------------------------------------------------------

class TestMainBasics:
    """Tests for main() with --help, --version, and no arguments."""

    def test_help_exits_zero(self, capsys):
        """main(['--help']) prints usage and exits with code 0."""
        with pytest.raises(SystemExit) as exc_info:
            main(["--help"])

        assert exc_info.value.code == 0
        captured = capsys.readouterr()
        assert "pxeos" in captured.out
        assert "usage" in captured.out.lower() or "positional" in captured.out.lower()

    def test_version_output(self, capsys):
        """main(['--version']) prints 'pxeos 1.0' and exits with code 0."""
        with pytest.raises(SystemExit) as exc_info:
            main(["--version"])

        assert exc_info.value.code == 0
        captured = capsys.readouterr()
        assert "pxeos 1.0" in captured.out

    @patch("pxeos.cli._init_stack")
    def test_no_args_returns_one(self, mock_init_stack, capsys):
        """main([]) with no subcommand returns exit code 1."""
        result = main([])
        assert result == 1

        captured = capsys.readouterr()
        assert "pxeos" in captured.out.lower() or "usage" in captured.out.lower()


# ---------------------------------------------------------------------------
# "server status" subcommand
# ---------------------------------------------------------------------------

class TestServerStatus:
    """Tests for 'pxeos server status' subcommand."""

    @patch("pxeos.cli._init_stack")
    def test_prints_host_port_plugins(self, mock_init_stack, capsys):
        """'server status' prints host, port, tls, and plugins info."""
        from pxeos.config import PxeOSConfig
        from pxeos.matcher import HostMatcher
        from pxeos.registry import PluginRegistry

        config = PxeOSConfig(
            server_host="0.0.0.0",
            server_port=8443,
        )

        mock_registry = MagicMock(spec=PluginRegistry)
        mock_registry.available = ["debian", "fedora", "ubuntu"]

        matcher = HostMatcher([])

        mock_init_stack.return_value = (config, mock_registry, matcher)

        result = main(["server", "status"])

        assert result == 0

        captured = capsys.readouterr()
        assert "host: 0.0.0.0" in captured.out
        assert "port: 8443" in captured.out
        assert "tls:  False" in captured.out
        assert "plugins: debian, fedora, ubuntu" in captured.out

    @patch("pxeos.cli._init_stack")
    def test_returns_zero(self, mock_init_stack):
        """'server status' returns exit code 0."""
        from pxeos.config import PxeOSConfig
        from pxeos.matcher import HostMatcher

        config = PxeOSConfig()
        mock_registry = MagicMock()
        mock_registry.available = []
        matcher = HostMatcher([])

        mock_init_stack.return_value = (config, mock_registry, matcher)

        result = main(["server", "status"])
        assert result == 0

    @patch("pxeos.cli._init_stack")
    def test_tls_true_when_cert_configured(self, mock_init_stack, capsys):
        """'server status' shows tls: True when tls_cert is set."""
        from pxeos.config import PxeOSConfig
        from pxeos.matcher import HostMatcher

        config = PxeOSConfig(
            tls_cert=Path("/etc/pxeos/cert.pem"),
            tls_key=Path("/etc/pxeos/key.pem"),
        )
        mock_registry = MagicMock()
        mock_registry.available = ["fedora"]
        matcher = HostMatcher([])

        mock_init_stack.return_value = (config, mock_registry, matcher)

        result = main(["server", "status"])
        assert result == 0

        captured = capsys.readouterr()
        assert "tls:  True" in captured.out


# ---------------------------------------------------------------------------
# "server" with no sub-action
# ---------------------------------------------------------------------------

class TestServerNoAction:
    """Tests for 'pxeos server' with no sub-action."""

    @patch("pxeos.cli._init_stack")
    def test_no_action_returns_one(self, mock_init_stack, capsys):
        """'server' with no action prints usage hint and returns 1."""
        from pxeos.config import PxeOSConfig
        from pxeos.matcher import HostMatcher

        config = PxeOSConfig()
        mock_registry = MagicMock()
        mock_registry.available = []
        matcher = HostMatcher([])

        mock_init_stack.return_value = (config, mock_registry, matcher)

        result = main(["server"])
        assert result == 1

        captured = capsys.readouterr()
        assert "usage" in captured.out.lower()


# ---------------------------------------------------------------------------
# init_stack integration path
# ---------------------------------------------------------------------------

class TestInitStackIntegration:
    """Tests for _init_stack with a non-existent config (uses defaults)."""

    @patch("pxeos.cli._init_stack")
    def test_config_path_passed_to_init_stack(self, mock_init_stack):
        """main() passes --config value to _init_stack."""
        from pxeos.config import PxeOSConfig
        from pxeos.matcher import HostMatcher

        config = PxeOSConfig()
        mock_registry = MagicMock()
        mock_registry.available = []
        matcher = HostMatcher([])

        mock_init_stack.return_value = (config, mock_registry, matcher)

        main(["--config", "/tmp/my-config.toml", "server", "status"])

        mock_init_stack.assert_called_once()
        call_arg = mock_init_stack.call_args[0][0]
        assert call_arg == Path("/tmp/my-config.toml")
