"""Tests for pxeos.tls -- TLS certificate generation and CLI integration."""

from __future__ import annotations

import ssl
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from pxeos.tls import (
    DEFAULT_CERT_PATH,
    DEFAULT_KEY_PATH,
    ensure_tls_certs,
    generate_self_signed_cert,
)


# ---------------------------------------------------------------------------
# generate_self_signed_cert
# ---------------------------------------------------------------------------


class TestGenerateSelfSignedCert:
    """Tests for self-signed certificate generation."""

    def test_creates_cert_and_key_files(self, tmp_path):
        """Certificate and key PEM files are created on disk."""
        cert_path = tmp_path / "cert.pem"
        key_path = tmp_path / "key.pem"

        result_cert, result_key = generate_self_signed_cert(
            cert_path, key_path
        )

        assert result_cert == cert_path
        assert result_key == key_path
        assert cert_path.exists()
        assert key_path.exists()

    def test_cert_is_valid_pem(self, tmp_path):
        """Generated certificate is valid PEM that OpenSSL can parse."""
        cert_path = tmp_path / "cert.pem"
        key_path = tmp_path / "key.pem"

        generate_self_signed_cert(cert_path, key_path)

        cert_data = cert_path.read_text()
        assert "-----BEGIN CERTIFICATE-----" in cert_data
        assert "-----END CERTIFICATE-----" in cert_data

    def test_key_is_valid_pem(self, tmp_path):
        """Generated key is valid PEM format."""
        cert_path = tmp_path / "cert.pem"
        key_path = tmp_path / "key.pem"

        generate_self_signed_cert(cert_path, key_path)

        key_data = key_path.read_text()
        assert "-----BEGIN RSA PRIVATE KEY-----" in key_data
        assert "-----END RSA PRIVATE KEY-----" in key_data

    def test_key_file_permissions(self, tmp_path):
        """Private key file has restrictive permissions (0o600)."""
        cert_path = tmp_path / "cert.pem"
        key_path = tmp_path / "key.pem"

        generate_self_signed_cert(cert_path, key_path)

        mode = key_path.stat().st_mode & 0o777
        assert mode == 0o600

    def test_creates_parent_directories(self, tmp_path):
        """Parent directories are created if they do not exist."""
        cert_path = tmp_path / "subdir" / "nested" / "cert.pem"
        key_path = tmp_path / "subdir" / "nested" / "key.pem"

        generate_self_signed_cert(cert_path, key_path)

        assert cert_path.exists()
        assert key_path.exists()

    def test_custom_common_name(self, tmp_path):
        """Custom common name is accepted without error."""
        cert_path = tmp_path / "cert.pem"
        key_path = tmp_path / "key.pem"

        # Should not raise
        generate_self_signed_cert(
            cert_path, key_path, common_name="test.example.com"
        )

        assert cert_path.exists()

    def test_custom_validity_days(self, tmp_path):
        """Custom validity period is accepted."""
        cert_path = tmp_path / "cert.pem"
        key_path = tmp_path / "key.pem"

        generate_self_signed_cert(
            cert_path, key_path, validity_days=30
        )

        assert cert_path.exists()

    def test_cert_and_key_match(self, tmp_path):
        """Certificate and key form a valid pair (SSLContext accepts them)."""
        cert_path = tmp_path / "cert.pem"
        key_path = tmp_path / "key.pem"

        generate_self_signed_cert(cert_path, key_path)

        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        # This will raise if cert/key don't match
        ctx.load_cert_chain(str(cert_path), str(key_path))

    def test_cert_has_san_extension(self, tmp_path):
        """Certificate includes SAN with localhost and 127.0.0.1."""
        from cryptography import x509

        cert_path = tmp_path / "cert.pem"
        key_path = tmp_path / "key.pem"

        generate_self_signed_cert(cert_path, key_path)

        cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
        san = cert.extensions.get_extension_for_class(
            x509.SubjectAlternativeName
        )
        dns_names = san.value.get_values_for_type(x509.DNSName)
        assert "localhost" in dns_names

    def test_default_paths(self):
        """Default paths point to /etc/pxeos/tls/."""
        assert DEFAULT_CERT_PATH == Path("/etc/pxeos/tls/cert.pem")
        assert DEFAULT_KEY_PATH == Path("/etc/pxeos/tls/key.pem")


# ---------------------------------------------------------------------------
# ensure_tls_certs
# ---------------------------------------------------------------------------


class TestEnsureTlsCerts:
    """Tests for the ensure_tls_certs convenience function."""

    def test_returns_provided_paths_when_both_exist(self, tmp_path):
        """If user provides existing cert and key, they are returned."""
        cert_path = tmp_path / "user-cert.pem"
        key_path = tmp_path / "user-key.pem"

        # Create dummy files
        cert_path.write_text("cert")
        key_path.write_text("key")

        result_cert, result_key = ensure_tls_certs(
            cert_path=cert_path, key_path=key_path
        )

        assert result_cert == cert_path
        assert result_key == key_path

    def test_raises_when_cert_missing(self, tmp_path):
        """FileNotFoundError if user-provided cert does not exist."""
        cert_path = tmp_path / "missing-cert.pem"
        key_path = tmp_path / "key.pem"
        key_path.write_text("key")

        with pytest.raises(FileNotFoundError, match="certificate"):
            ensure_tls_certs(cert_path=cert_path, key_path=key_path)

    def test_raises_when_key_missing(self, tmp_path):
        """FileNotFoundError if user-provided key does not exist."""
        cert_path = tmp_path / "cert.pem"
        key_path = tmp_path / "missing-key.pem"
        cert_path.write_text("cert")

        with pytest.raises(FileNotFoundError, match="key"):
            ensure_tls_certs(cert_path=cert_path, key_path=key_path)

    def test_auto_generates_under_data_dir(self, tmp_path):
        """With no user paths, generates certs under data_dir/tls/."""
        cert, key = ensure_tls_certs(data_dir=tmp_path)

        assert cert == tmp_path / "tls" / "cert.pem"
        assert key == tmp_path / "tls" / "key.pem"
        assert cert.exists()
        assert key.exists()

    def test_reuses_existing_auto_generated(self, tmp_path):
        """If auto-generated certs already exist, they are reused."""
        tls_dir = tmp_path / "tls"
        tls_dir.mkdir()
        cert_path = tls_dir / "cert.pem"
        key_path = tls_dir / "key.pem"

        # Create dummy existing files
        cert_path.write_text("existing-cert")
        key_path.write_text("existing-key")

        result_cert, result_key = ensure_tls_certs(data_dir=tmp_path)

        assert result_cert == cert_path
        assert result_key == key_path
        # Should not have overwritten
        assert cert_path.read_text() == "existing-cert"

    def test_generates_when_no_args(self, tmp_path):
        """With only data_dir, new certs are generated."""
        cert, key = ensure_tls_certs(data_dir=tmp_path)

        assert cert.exists()
        assert key.exists()
        # Should be proper PEM
        assert "BEGIN CERTIFICATE" in cert.read_text()


# ---------------------------------------------------------------------------
# CLI parser: --tls-cert, --tls-key, --no-tls flags
# ---------------------------------------------------------------------------


class TestTlsCliFlags:
    """Tests for TLS-related CLI argument parsing."""

    def test_server_start_accepts_tls_cert(self):
        """'server start --tls-cert' is a valid argument."""
        from pxeos.cli import _build_parser

        parser = _build_parser()
        args = parser.parse_args([
            "server", "start", "--tls-cert", "/tmp/cert.pem"
        ])
        assert args.tls_cert == Path("/tmp/cert.pem")

    def test_server_start_accepts_tls_key(self):
        """'server start --tls-key' is a valid argument."""
        from pxeos.cli import _build_parser

        parser = _build_parser()
        args = parser.parse_args([
            "server", "start", "--tls-key", "/tmp/key.pem"
        ])
        assert args.tls_key == Path("/tmp/key.pem")

    def test_server_start_accepts_no_tls(self):
        """'server start --no-tls' is a valid argument."""
        from pxeos.cli import _build_parser

        parser = _build_parser()
        args = parser.parse_args(["server", "start", "--no-tls"])
        assert args.no_tls is True

    def test_server_start_no_tls_defaults_false(self):
        """--no-tls defaults to False."""
        from pxeos.cli import _build_parser

        parser = _build_parser()
        args = parser.parse_args(["server", "start"])
        assert args.no_tls is False

    def test_server_start_tls_cert_default_none(self):
        """--tls-cert defaults to None."""
        from pxeos.cli import _build_parser

        parser = _build_parser()
        args = parser.parse_args(["server", "start"])
        assert args.tls_cert is None

    def test_server_start_tls_key_default_none(self):
        """--tls-key defaults to None."""
        from pxeos.cli import _build_parser

        parser = _build_parser()
        args = parser.parse_args(["server", "start"])
        assert args.tls_key is None

    def test_both_tls_cert_and_key(self):
        """Both --tls-cert and --tls-key can be provided together."""
        from pxeos.cli import _build_parser

        parser = _build_parser()
        args = parser.parse_args([
            "server", "start",
            "--tls-cert", "/etc/pxeos/cert.pem",
            "--tls-key", "/etc/pxeos/key.pem",
        ])
        assert args.tls_cert == Path("/etc/pxeos/cert.pem")
        assert args.tls_key == Path("/etc/pxeos/key.pem")


# ---------------------------------------------------------------------------
# Config: [tls] section loading
# ---------------------------------------------------------------------------


class TestTlsConfig:
    """Tests for [tls] section in TOML config."""

    def test_tls_section_cert_and_key(self, tmp_path):
        """[tls] section cert/key are loaded into PxeOSConfig."""
        from pxeos.config import load_config

        config_file = tmp_path / "pxeos.toml"
        config_file.write_text(
            '[server]\nhost = "0.0.0.0"\nport = 8443\n\n'
            '[tls]\ncert = "/etc/pxeos/tls/cert.pem"\n'
            'key = "/etc/pxeos/tls/key.pem"\n'
        )

        config = load_config(config_file)
        assert config.tls_cert == Path("/etc/pxeos/tls/cert.pem")
        assert config.tls_key == Path("/etc/pxeos/tls/key.pem")

    def test_tls_auto_generate_default_true(self, tmp_path):
        """tls_auto_generate defaults to True."""
        from pxeos.config import load_config

        config_file = tmp_path / "pxeos.toml"
        config_file.write_text(
            '[server]\nhost = "0.0.0.0"\nport = 8443\n'
        )

        config = load_config(config_file)
        assert config.tls_auto_generate is True

    def test_tls_auto_generate_false(self, tmp_path):
        """[tls] auto_generate = false is respected."""
        from pxeos.config import load_config

        config_file = tmp_path / "pxeos.toml"
        config_file.write_text(
            '[server]\nhost = "0.0.0.0"\nport = 8443\n\n'
            '[tls]\nauto_generate = false\n'
        )

        config = load_config(config_file)
        assert config.tls_auto_generate is False

    def test_tls_section_overrides_server_keys(self, tmp_path):
        """[tls] section takes precedence over server.tls_cert/tls_key."""
        from pxeos.config import load_config

        config_file = tmp_path / "pxeos.toml"
        config_file.write_text(
            '[server]\nhost = "0.0.0.0"\nport = 8443\n'
            'tls_cert = "/old/cert.pem"\n'
            'tls_key = "/old/key.pem"\n\n'
            '[tls]\ncert = "/new/cert.pem"\n'
            'key = "/new/key.pem"\n'
        )

        config = load_config(config_file)
        assert config.tls_cert == Path("/new/cert.pem")
        assert config.tls_key == Path("/new/key.pem")

    def test_backward_compat_server_tls_keys(self, tmp_path):
        """server.tls_cert/tls_key still work without [tls] section."""
        from pxeos.config import load_config

        config_file = tmp_path / "pxeos.toml"
        config_file.write_text(
            '[server]\nhost = "0.0.0.0"\nport = 8443\n'
            'tls_cert = "/etc/pxeos/cert.pem"\n'
            'tls_key = "/etc/pxeos/key.pem"\n'
        )

        config = load_config(config_file)
        assert config.tls_cert == Path("/etc/pxeos/cert.pem")
        assert config.tls_key == Path("/etc/pxeos/key.pem")

    def test_default_config_has_auto_generate_true(self):
        """PxeOSConfig() defaults tls_auto_generate to True."""
        from pxeos.config import PxeOSConfig

        config = PxeOSConfig()
        assert config.tls_auto_generate is True
        assert config.tls_cert is None
        assert config.tls_key is None


# ---------------------------------------------------------------------------
# Server start: TLS integration (mocked uvicorn)
# ---------------------------------------------------------------------------


class TestServerStartTls:
    """Tests for TLS behavior during 'server start'."""

    @patch("pxeos.cli._init_stack")
    @patch("pxeos.cli.PluginRegistry", autospec=True)
    def test_no_tls_flag_logs_warning(
        self, mock_reg_cls, mock_init_stack, capsys
    ):
        """--no-tls logs a warning about plain HTTP."""
        from pxeos.cli import main
        from pxeos.config import PxeOSConfig
        from pxeos.matcher import HostMatcher

        config = PxeOSConfig(tls_auto_generate=False)
        mock_registry = MagicMock()
        mock_registry.available = []
        matcher = HostMatcher([])
        mock_init_stack.return_value = (config, mock_registry, matcher)

        with patch("pxeos.cli.PluginRegistry"):
            with patch("uvicorn.run") as mock_uvicorn:
                result = main([
                    "server", "start", "--no-tls"
                ])

        assert result == 0
        # uvicorn called without SSL
        mock_uvicorn.assert_called_once()
        call_kwargs = mock_uvicorn.call_args
        assert call_kwargs[1]["ssl_certfile"] is None
        assert call_kwargs[1]["ssl_keyfile"] is None

    @patch("pxeos.cli._init_stack")
    def test_cli_cert_key_passed_to_uvicorn(
        self, mock_init_stack, tmp_path
    ):
        """--tls-cert and --tls-key are forwarded to uvicorn."""
        from pxeos.cli import main
        from pxeos.config import PxeOSConfig
        from pxeos.matcher import HostMatcher

        cert = tmp_path / "cert.pem"
        key = tmp_path / "key.pem"
        cert.write_text("cert")
        key.write_text("key")

        config = PxeOSConfig(tls_auto_generate=False)
        mock_registry = MagicMock()
        mock_registry.available = []
        matcher = HostMatcher([])
        mock_init_stack.return_value = (config, mock_registry, matcher)

        with patch("uvicorn.run") as mock_uvicorn:
            result = main([
                "server", "start",
                "--tls-cert", str(cert),
                "--tls-key", str(key),
            ])

        assert result == 0
        mock_uvicorn.assert_called_once()
        call_kwargs = mock_uvicorn.call_args
        assert call_kwargs[1]["ssl_certfile"] == str(cert)
        assert call_kwargs[1]["ssl_keyfile"] == str(key)

    @patch("pxeos.cli._init_stack")
    def test_auto_generate_when_no_cert(
        self, mock_init_stack, tmp_path
    ):
        """Auto-generates cert when tls_auto_generate is True."""
        from pxeos.cli import main
        from pxeos.config import PxeOSConfig
        from pxeos.matcher import HostMatcher

        config = PxeOSConfig(
            tls_auto_generate=True,
            data_dir=tmp_path,
        )
        mock_registry = MagicMock()
        mock_registry.available = []
        matcher = HostMatcher([])
        mock_init_stack.return_value = (config, mock_registry, matcher)

        with patch("uvicorn.run") as mock_uvicorn:
            result = main(["server", "start"])

        assert result == 0
        mock_uvicorn.assert_called_once()
        call_kwargs = mock_uvicorn.call_args
        assert call_kwargs[1]["ssl_certfile"] is not None
        assert call_kwargs[1]["ssl_keyfile"] is not None
        # Verify the auto-generated files exist
        assert Path(call_kwargs[1]["ssl_certfile"]).exists()
        assert Path(call_kwargs[1]["ssl_keyfile"]).exists()

    @patch("pxeos.cli._init_stack")
    def test_auto_generate_disabled_no_cert(
        self, mock_init_stack
    ):
        """No auto-generate when tls_auto_generate is False and no cert."""
        from pxeos.cli import main
        from pxeos.config import PxeOSConfig
        from pxeos.matcher import HostMatcher

        config = PxeOSConfig(tls_auto_generate=False)
        mock_registry = MagicMock()
        mock_registry.available = []
        matcher = HostMatcher([])
        mock_init_stack.return_value = (config, mock_registry, matcher)

        with patch("uvicorn.run") as mock_uvicorn:
            result = main(["server", "start"])

        assert result == 0
        mock_uvicorn.assert_called_once()
        call_kwargs = mock_uvicorn.call_args
        assert call_kwargs[1]["ssl_certfile"] is None
        assert call_kwargs[1]["ssl_keyfile"] is None

    @patch("pxeos.cli._init_stack")
    def test_config_cert_key_used_when_no_cli_flags(
        self, mock_init_stack, tmp_path
    ):
        """Config tls_cert/tls_key used when no CLI flags provided."""
        from pxeos.cli import main
        from pxeos.config import PxeOSConfig
        from pxeos.matcher import HostMatcher

        cert = tmp_path / "config-cert.pem"
        key = tmp_path / "config-key.pem"
        cert.write_text("cert")
        key.write_text("key")

        config = PxeOSConfig(
            tls_cert=cert,
            tls_key=key,
            tls_auto_generate=False,
        )
        mock_registry = MagicMock()
        mock_registry.available = []
        matcher = HostMatcher([])
        mock_init_stack.return_value = (config, mock_registry, matcher)

        with patch("uvicorn.run") as mock_uvicorn:
            result = main(["server", "start"])

        assert result == 0
        call_kwargs = mock_uvicorn.call_args
        assert call_kwargs[1]["ssl_certfile"] == str(cert)
        assert call_kwargs[1]["ssl_keyfile"] == str(key)
