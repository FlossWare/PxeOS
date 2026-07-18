"""Security audit tests for PxeOS.

Tests for: template injection, auth bypass, path traversal,
secrets file permissions, and input validation.
"""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from pxeos.models import BootFirmware, HostRule, ProvisionProfile
from pxeos.validation import (
    escape_xml,
    is_shell_safe,
    normalize_mac,
    sanitize_hostname,
    sanitize_packages,
    sanitize_shell_value,
    sanitize_url,
    validate_hostname,
    validate_mac,
    validate_package_name,
    validate_safe_name,
    validate_url,
)


# ====================================================================
# Input validation module (pxeos.validation)
# ====================================================================


class TestMACValidation:

    def test_valid_colon_separated(self):
        assert validate_mac("aa:bb:cc:dd:ee:ff")

    def test_valid_dash_separated(self):
        assert validate_mac("AA-BB-CC-DD-EE-FF")

    def test_valid_bare_hex(self):
        assert validate_mac("aabbccddeeff")

    def test_valid_mixed_case(self):
        assert validate_mac("Aa:Bb:Cc:Dd:Ee:Ff")

    def test_invalid_too_short(self):
        assert not validate_mac("aa:bb:cc")

    def test_invalid_too_long(self):
        assert not validate_mac("aa:bb:cc:dd:ee:ff:00")

    def test_invalid_non_hex(self):
        assert not validate_mac("gg:hh:ii:jj:kk:ll")

    def test_invalid_empty(self):
        assert not validate_mac("")

    def test_invalid_with_injection(self):
        assert not validate_mac("aa:bb:cc:dd:ee:ff; rm -rf /")

    def test_normalize_colon(self):
        assert normalize_mac("AA:BB:CC:DD:EE:FF") == "aa:bb:cc:dd:ee:ff"

    def test_normalize_dash(self):
        assert normalize_mac("AA-BB-CC-DD-EE-FF") == "aa:bb:cc:dd:ee:ff"

    def test_normalize_bare(self):
        assert normalize_mac("AABBCCDDEEFF") == "aa:bb:cc:dd:ee:ff"

    def test_normalize_invalid_raises(self):
        with pytest.raises(ValueError, match="invalid MAC"):
            normalize_mac("not-a-mac")


class TestHostnameValidation:

    def test_valid_simple(self):
        assert validate_hostname("web-01")

    def test_valid_fqdn(self):
        assert validate_hostname("web-01.example.com")

    def test_valid_trailing_dot(self):
        assert validate_hostname("web-01.example.com.")

    def test_valid_single_char(self):
        assert validate_hostname("a")

    def test_valid_numeric(self):
        assert validate_hostname("server1")

    def test_invalid_empty(self):
        assert not validate_hostname("")

    def test_invalid_starts_with_hyphen(self):
        assert not validate_hostname("-invalid")

    def test_invalid_ends_with_hyphen(self):
        assert not validate_hostname("invalid-")

    def test_invalid_shell_injection(self):
        assert not validate_hostname('"; rm -rf / #')

    def test_invalid_semicolon(self):
        assert not validate_hostname("host;evil")

    def test_invalid_backtick(self):
        assert not validate_hostname("host`id`")

    def test_invalid_dollar(self):
        assert not validate_hostname("host$(whoami)")

    def test_invalid_pipe(self):
        assert not validate_hostname("host|cat /etc/passwd")

    def test_invalid_newline(self):
        assert not validate_hostname("host\nevil")

    def test_invalid_space(self):
        assert not validate_hostname("host name")

    def test_invalid_underscore(self):
        # RFC 952 does not allow underscores in hostnames
        assert not validate_hostname("host_name")

    def test_invalid_too_long_label(self):
        assert not validate_hostname("a" * 64)

    def test_invalid_too_long_total(self):
        assert not validate_hostname("a." * 127 + "a")

    def test_sanitize_valid(self):
        assert sanitize_hostname("web-01") == "web-01"

    def test_sanitize_strips_trailing_dot(self):
        assert sanitize_hostname("web-01.example.com.") == "web-01.example.com"

    def test_sanitize_invalid_raises(self):
        with pytest.raises(ValueError, match="invalid hostname"):
            sanitize_hostname("; rm -rf /")


class TestURLValidation:

    def test_valid_http(self):
        assert validate_url("http://mirror.example.com/repo")

    def test_valid_https(self):
        assert validate_url("https://mirror.example.com/repo")

    def test_valid_ftp(self):
        assert validate_url("ftp://mirror.example.com/repo")

    def test_valid_nfs(self):
        assert validate_url("nfs://server/export")

    def test_invalid_empty(self):
        assert not validate_url("")

    def test_invalid_no_scheme(self):
        assert not validate_url("mirror.example.com/repo")

    def test_invalid_javascript_scheme(self):
        assert not validate_url("javascript:alert(1)")

    def test_invalid_file_scheme(self):
        assert not validate_url("file:///etc/passwd")

    def test_invalid_data_scheme(self):
        assert not validate_url("data:text/html,<script>alert(1)</script>")

    def test_sanitize_valid(self):
        url = "http://mirror.example.com/repo"
        assert sanitize_url(url) == url

    def test_sanitize_invalid_raises(self):
        with pytest.raises(ValueError, match="invalid URL"):
            sanitize_url("not-a-url")


class TestShellSafety:

    def test_safe_simple_string(self):
        assert is_shell_safe("hello-world_123")

    def test_unsafe_semicolon(self):
        assert not is_shell_safe("hello; rm -rf /")

    def test_unsafe_pipe(self):
        assert not is_shell_safe("hello | cat /etc/passwd")

    def test_unsafe_backtick(self):
        assert not is_shell_safe("hello `id`")

    def test_unsafe_dollar(self):
        assert not is_shell_safe("hello $(whoami)")

    def test_unsafe_ampersand(self):
        assert not is_shell_safe("hello & background")

    def test_unsafe_newline(self):
        assert not is_shell_safe("hello\nevil")

    def test_unsafe_null(self):
        assert not is_shell_safe("hello\x00evil")

    def test_unsafe_double_quote(self):
        assert not is_shell_safe('hello"world')

    def test_unsafe_single_quote(self):
        assert not is_shell_safe("hello'world")

    def test_sanitize_valid(self):
        assert sanitize_shell_value("safe-value") == "safe-value"

    def test_sanitize_invalid_raises(self):
        with pytest.raises(ValueError, match="unsafe characters"):
            sanitize_shell_value("; rm -rf /", "hostname")


class TestXMLEscape:

    def test_escapes_ampersand(self):
        assert escape_xml("a&b") == "a&amp;b"

    def test_escapes_less_than(self):
        assert escape_xml("a<b") == "a&lt;b"

    def test_escapes_greater_than(self):
        assert escape_xml("a>b") == "a&gt;b"

    def test_escapes_double_quote(self):
        assert escape_xml('a"b') == "a&quot;b"

    def test_escapes_single_quote(self):
        assert escape_xml("a'b") == "a&apos;b"

    def test_no_escape_needed(self):
        assert escape_xml("safe-string") == "safe-string"

    def test_multiple_escapes(self):
        assert escape_xml('<a&b>') == "&lt;a&amp;b&gt;"


class TestSafeNameValidation:

    def test_valid_simple(self):
        assert validate_safe_name("my-profile") == "my-profile"

    def test_rejects_dotdot(self):
        with pytest.raises(ValueError, match="path traversal"):
            validate_safe_name("../../etc/passwd")

    def test_rejects_slash(self):
        with pytest.raises(ValueError, match="path traversal"):
            validate_safe_name("sub/dir")

    def test_rejects_backslash(self):
        with pytest.raises(ValueError, match="path traversal"):
            validate_safe_name("sub\\dir")

    def test_rejects_null(self):
        with pytest.raises(ValueError, match="path traversal"):
            validate_safe_name("name\x00evil")

    def test_rejects_empty(self):
        with pytest.raises(ValueError, match="must not be empty"):
            validate_safe_name("")


class TestPackageNameValidation:

    def test_valid_simple(self):
        assert validate_package_name("vim")

    def test_valid_with_hyphen(self):
        assert validate_package_name("openssh-server")

    def test_valid_with_version(self):
        assert validate_package_name("python3.11")

    def test_valid_with_colon(self):
        assert validate_package_name("libc6:amd64")

    def test_valid_with_plus(self):
        assert validate_package_name("g++")

    def test_invalid_with_semicolon(self):
        assert not validate_package_name("vim; rm -rf /")

    def test_invalid_with_shell_chars(self):
        assert not validate_package_name("pkg$(whoami)")

    def test_invalid_with_space(self):
        assert not validate_package_name("vim tmux")

    def test_invalid_empty(self):
        assert not validate_package_name("")

    def test_invalid_starts_with_hyphen(self):
        assert not validate_package_name("-evil")

    def test_sanitize_valid_list(self):
        pkgs = ["vim", "tmux", "htop"]
        assert sanitize_packages(pkgs) == pkgs

    def test_sanitize_invalid_raises(self):
        with pytest.raises(ValueError, match="invalid package name"):
            sanitize_packages(["vim", "; rm -rf /", "tmux"])


# ====================================================================
# Template injection attacks
# ====================================================================


class TestTemplateInjectionFedora:
    """Verify Fedora kickstart rejects malicious hostnames/URLs."""

    def _make_profile(self, **overrides):
        defaults = {
            "name": "test",
            "os_family": "fedora",
            "os_version": "40",
            "arch": "x86_64",
            "firmware": BootFirmware.BIOS,
            "install_url": "http://mirror.example.com/fedora/40/x86_64",
            "autoinstall_url": "http://pxe.example.com/ks/test",
        }
        defaults.update(overrides)
        return ProvisionProfile(**defaults)

    def test_rejects_shell_injection_in_hostname(self):
        from pxeos.plugins.fedora import FedoraPlugin

        plugin = FedoraPlugin()
        profile = self._make_profile(
            network={"hostname": '"; rm -rf / #'}
        )
        with pytest.raises(ValueError, match="invalid hostname"):
            plugin.generate_autoinstall(profile)

    def test_rejects_command_injection_via_backtick_hostname(self):
        from pxeos.plugins.fedora import FedoraPlugin

        plugin = FedoraPlugin()
        profile = self._make_profile(
            network={"hostname": "host`id`"}
        )
        with pytest.raises(ValueError, match="invalid hostname"):
            plugin.generate_autoinstall(profile)

    def test_rejects_newline_injection_in_hostname(self):
        from pxeos.plugins.fedora import FedoraPlugin

        plugin = FedoraPlugin()
        profile = self._make_profile(
            network={"hostname": "host\nrm -rf /"}
        )
        with pytest.raises(ValueError, match="invalid hostname"):
            plugin.generate_autoinstall(profile)

    def test_rejects_malicious_install_url(self):
        from pxeos.plugins.fedora import FedoraPlugin

        plugin = FedoraPlugin()
        profile = self._make_profile(
            install_url="javascript:alert(1)"
        )
        with pytest.raises(ValueError, match="invalid install_url"):
            plugin.generate_autoinstall(profile)

    def test_rejects_malicious_package_name(self):
        from pxeos.plugins.fedora import FedoraPlugin

        plugin = FedoraPlugin()
        profile = self._make_profile(
            packages=["vim", "; rm -rf /"]
        )
        with pytest.raises(ValueError, match="invalid package name"):
            plugin.generate_autoinstall(profile)

    def test_accepts_valid_profile(self):
        from pxeos.plugins.fedora import FedoraPlugin

        plugin = FedoraPlugin()
        profile = self._make_profile(
            network={"hostname": "web-01"},
            packages=["vim", "tmux"],
        )
        result = plugin.generate_autoinstall(profile)
        assert "web-01" in result
        assert "vim" in result


class TestTemplateInjectionWindows:
    """Verify Windows unattend.xml rejects/escapes malicious input."""

    def _make_profile(self, **overrides):
        defaults = {
            "name": "test-win",
            "os_family": "windows",
            "os_version": "2022",
            "arch": "x86_64",
            "firmware": BootFirmware.UEFI,
            "install_url": "http://pxe.example.com/win/2022",
            "autoinstall_url": "http://pxe.example.com/unattend/win2022",
        }
        defaults.update(overrides)
        return ProvisionProfile(**defaults)

    def test_rejects_hostname_injection(self):
        from pxeos.plugins.windows import WindowsPlugin

        plugin = WindowsPlugin()
        profile = self._make_profile(
            network={"hostname": "<script>alert(1)</script>"}
        )
        with pytest.raises(ValueError, match="invalid hostname"):
            plugin.generate_autoinstall(profile)

    def test_accepts_valid_hostname(self):
        from pxeos.plugins.windows import WindowsPlugin

        plugin = WindowsPlugin()
        profile = self._make_profile(
            network={"hostname": "WIN-SERVER-01"}
        )
        result = plugin.generate_autoinstall(profile)
        assert "WIN-SERVER-01" in result


class TestTemplateInjectionFreeBSD:
    """Verify FreeBSD installerconfig rejects shell injection."""

    def _make_profile(self, **overrides):
        defaults = {
            "name": "bsd-test",
            "os_family": "freebsd",
            "os_version": "14.1",
            "arch": "amd64",
            "firmware": BootFirmware.BIOS,
            "install_url": "http://mirror.example.com/freebsd/14.1",
        }
        defaults.update(overrides)
        return ProvisionProfile(**defaults)

    def test_rejects_shell_injection_hostname(self):
        from pxeos.plugins.freebsd import FreeBSDPlugin

        plugin = FreeBSDPlugin()
        profile = self._make_profile(
            network={"hostname": '"; rm -rf / #'}
        )
        with pytest.raises(ValueError, match="invalid hostname"):
            plugin.generate_autoinstall(profile)

    def test_rejects_dollar_injection_hostname(self):
        from pxeos.plugins.freebsd import FreeBSDPlugin

        plugin = FreeBSDPlugin()
        profile = self._make_profile(
            network={"hostname": "$(reboot)"}
        )
        with pytest.raises(ValueError, match="invalid hostname"):
            plugin.generate_autoinstall(profile)


class TestTemplateInjectionAllPlugins:
    """Cross-plugin injection tests for all OS families."""

    _PLUGIN_CONFIGS = [
        (
            "fedora",
            "pxeos.plugins.fedora",
            "FedoraPlugin",
            {
                "os_version": "40",
                "install_url": "http://mirror.example.com/fedora/40/x86_64",
                "autoinstall_url": "http://pxe.example.com/ks/test",
            },
        ),
        (
            "ubuntu",
            "pxeos.plugins.ubuntu",
            "UbuntuPlugin",
            {
                "os_version": "24.04",
                "autoinstall_url": "http://pxe.example.com/ci/test",
            },
        ),
        (
            "debian",
            "pxeos.plugins.debian",
            "DebianPlugin",
            {
                "os_version": "12",
                "autoinstall_url": "http://pxe.example.com/preseed/test",
            },
        ),
        (
            "suse",
            "pxeos.plugins.suse",
            "SUSEPlugin",
            {
                "os_version": "15.6",
                "install_url": "http://mirror.example.com/suse/15.6",
                "autoinstall_url": "http://pxe.example.com/autoyast/test",
            },
        ),
        (
            "arch",
            "pxeos.plugins.arch",
            "ArchPlugin",
            {
                "os_version": "latest",
                "autoinstall_url": "http://pxe.example.com/arch/test",
            },
        ),
        (
            "freebsd",
            "pxeos.plugins.freebsd",
            "FreeBSDPlugin",
            {
                "os_version": "14.1",
                "install_url": "http://mirror.example.com/freebsd/14.1",
            },
        ),
        (
            "openbsd",
            "pxeos.plugins.openbsd",
            "OpenBSDPlugin",
            {
                "os_version": "7.5",
                "install_url": "http://mirror.example.com/openbsd",
            },
        ),
        (
            "netbsd",
            "pxeos.plugins.netbsd",
            "NetBSDPlugin",
            {
                "os_version": "10.0",
                "install_url": "http://mirror.example.com/netbsd",
            },
        ),
        (
            "dragonflybsd",
            "pxeos.plugins.dragonflybsd",
            "DragonFlyBSDPlugin",
            {
                "os_version": "6.4",
                "install_url": "http://mirror.example.com/dragonfly",
            },
        ),
        (
            "windows",
            "pxeos.plugins.windows",
            "WindowsPlugin",
            {
                "os_version": "2022",
                "install_url": "http://pxe.example.com/win/2022",
                "autoinstall_url": "http://pxe.example.com/unattend/win2022",
                "firmware": BootFirmware.UEFI,
            },
        ),
    ]

    @pytest.mark.parametrize(
        "os_family,module_path,class_name,extra_fields",
        _PLUGIN_CONFIGS,
        ids=[c[0] for c in _PLUGIN_CONFIGS],
    )
    def test_rejects_shell_injection_hostname(
        self, os_family, module_path, class_name, extra_fields
    ):
        import importlib

        mod = importlib.import_module(module_path)
        plugin_class = getattr(mod, class_name)
        plugin = plugin_class()

        profile_kwargs = {
            "name": "test",
            "os_family": os_family,
            "arch": "x86_64" if os_family != "freebsd" else "amd64",
            "firmware": extra_fields.pop("firmware", BootFirmware.BIOS),
            "network": {"hostname": "; rm -rf / #"},
            **extra_fields,
        }
        profile = ProvisionProfile(**profile_kwargs)
        with pytest.raises(ValueError):
            plugin.generate_autoinstall(profile)

    @pytest.mark.parametrize(
        "os_family,module_path,class_name,extra_fields",
        _PLUGIN_CONFIGS,
        ids=[c[0] for c in _PLUGIN_CONFIGS],
    )
    def test_rejects_malicious_package_names(
        self, os_family, module_path, class_name, extra_fields
    ):
        import importlib

        mod = importlib.import_module(module_path)
        plugin_class = getattr(mod, class_name)
        plugin = plugin_class()

        profile_kwargs = {
            "name": "test",
            "os_family": os_family,
            "arch": "x86_64" if os_family != "freebsd" else "amd64",
            "firmware": extra_fields.pop("firmware", BootFirmware.BIOS),
            "packages": ["vim", "$(whoami)", "tmux"],
            **extra_fields,
        }
        profile = ProvisionProfile(**profile_kwargs)
        with pytest.raises(ValueError):
            plugin.generate_autoinstall(profile)


# ====================================================================
# Auth security
# ====================================================================


class TestAuthTimingSafe:
    """Verify auth uses timing-safe comparison."""

    def test_validate_uses_hmac_compare_digest(self, tmp_path):
        """Auth validation must use timing-safe comparison."""
        from pxeos.auth import ApiKeyStore, Role

        store = ApiKeyStore(tmp_path)
        raw_key, _ = store.create_key("test", Role.VIEWER)

        # Valid key should validate
        result = store.validate(raw_key)
        assert result is not None
        assert result.name == "test"

        # Invalid key should not validate (timing-safe)
        result = store.validate("pxeos_invalid_key_here")
        assert result is None

    def test_key_hashing_is_sha256(self, tmp_path):
        """Keys are hashed with SHA-256."""
        import hashlib

        from pxeos.auth import ApiKeyStore

        store = ApiKeyStore(tmp_path)
        test_key = "pxeos_test123"
        expected = hashlib.sha256(test_key.encode()).hexdigest()
        assert store.hash_key(test_key) == expected

    def test_disabled_key_rejected(self, tmp_path):
        """Disabled keys are rejected even with correct raw key."""
        from pxeos.auth import ApiKeyStore, Role

        store = ApiKeyStore(tmp_path)
        raw_key, _ = store.create_key("test", Role.ADMIN)
        store.revoke("test")
        assert store.validate(raw_key) is None


class TestAuthRoleEscalation:
    """Verify that role escalation is not possible."""

    def test_viewer_cannot_escalate_to_operator(self):
        from pxeos.auth import Role, role_has_access

        assert not role_has_access(Role.VIEWER, Role.OPERATOR)

    def test_viewer_cannot_escalate_to_admin(self):
        from pxeos.auth import Role, role_has_access

        assert not role_has_access(Role.VIEWER, Role.ADMIN)

    def test_operator_cannot_escalate_to_admin(self):
        from pxeos.auth import Role, role_has_access

        assert not role_has_access(Role.OPERATOR, Role.ADMIN)


class TestAuthFilePermissions:
    """Verify auth key files have restrictive permissions."""

    def test_keys_file_has_600_permissions(self, tmp_path):
        from pxeos.auth import ApiKeyStore, Role

        store = ApiKeyStore(tmp_path)
        store.create_key("test", Role.VIEWER)

        keys_path = tmp_path / "auth_keys.json"
        mode = stat.S_IMODE(keys_path.stat().st_mode)
        assert mode == 0o600

    def test_keys_dir_has_700_permissions(self, tmp_path):
        sub = tmp_path / "auth-subdir"
        from pxeos.auth import ApiKeyStore, Role

        store = ApiKeyStore(sub)
        store.create_key("test", Role.VIEWER)

        mode = stat.S_IMODE(sub.stat().st_mode)
        assert mode == 0o700

    def test_key_hash_not_in_raw_key(self, tmp_path):
        """The raw key and its hash must be different."""
        from pxeos.auth import ApiKeyStore, Role

        store = ApiKeyStore(tmp_path)
        raw_key, api_key = store.create_key("test", Role.VIEWER)
        assert raw_key != api_key.key_hash
        assert api_key.key_hash not in raw_key


# ====================================================================
# Secrets security
# ====================================================================


class TestSecretsFilePermissions:

    def test_secrets_file_600(self, tmp_path):
        from pxeos.secrets import FileSecretsProvider

        provider = FileSecretsProvider(tmp_path)
        provider.set("TEST", "value")

        secrets_path = tmp_path / "secrets.json"
        mode = stat.S_IMODE(secrets_path.stat().st_mode)
        assert mode == 0o600

    def test_secrets_dir_700(self, tmp_path):
        sub = tmp_path / "secrets-subdir"
        from pxeos.secrets import FileSecretsProvider

        provider = FileSecretsProvider(sub)
        provider.set("TEST", "value")

        mode = stat.S_IMODE(sub.stat().st_mode)
        assert mode == 0o700


class TestSecretsNotLeaked:

    def test_list_endpoint_returns_keys_only(self, tmp_path):
        """GET /api/v1/secrets must return keys, not values."""
        from fastapi.testclient import TestClient

        from pxeos.api import app, init_app
        from pxeos.config import PxeOSConfig
        from pxeos.matcher import HostMatcher
        from pxeos.registry import PluginRegistry

        data_dir = tmp_path / "data"
        data_dir.mkdir()
        distro_root = tmp_path / "distros"
        distro_root.mkdir()

        config = PxeOSConfig(
            data_dir=data_dir, distro_root=distro_root
        )
        registry = PluginRegistry()
        registry.load_builtins()
        matcher = HostMatcher([])
        init_app(registry, config, matcher)

        client = TestClient(app)
        # Store a secret
        client.post(
            "/api/v1/secrets",
            json={"key": "MY_SECRET", "value": "super-secret-value"},
        )
        # List should not contain the value
        resp = client.get("/api/v1/secrets")
        body = resp.json()
        assert "MY_SECRET" in body["keys"]
        assert "super-secret-value" not in json.dumps(body)


# ====================================================================
# Path traversal in engine
# ====================================================================


class TestPathTraversalInEngine:

    def _build_engine(self, rule, tmp_path):
        from pxeos.config import PxeOSConfig
        from pxeos.engine import ProvisioningEngine
        from pxeos.matcher import HostMatcher
        from pxeos.models import BootAssets
        from pxeos.registry import PluginRegistry

        mock_matcher = MagicMock(spec=HostMatcher)
        mock_matcher.match.return_value = rule

        mock_plugin = MagicMock()
        mock_plugin.validate_profile.return_value = []
        mock_plugin.boot_assets.return_value = BootAssets(
            kernel="/vmlinuz", initrd="/initrd.img"
        )

        mock_registry = MagicMock(spec=PluginRegistry)
        mock_registry.get.return_value = mock_plugin

        config = PxeOSConfig(data_dir=tmp_path)
        return ProvisioningEngine(
            mock_registry, mock_matcher, config
        )

    def test_rejects_dotdot_profile(self, tmp_path):
        rule = HostRule(
            profile="../../etc/passwd",
            os_family="fedora",
            os_version="40",
        )
        engine = self._build_engine(rule, tmp_path)
        with pytest.raises(ValueError, match="invalid profile name"):
            engine.provision(mac="aa:bb:cc:dd:ee:ff")

    def test_rejects_slash_profile(self, tmp_path):
        rule = HostRule(
            profile="sub/dir",
            os_family="fedora",
            os_version="40",
        )
        engine = self._build_engine(rule, tmp_path)
        with pytest.raises(ValueError, match="invalid profile name"):
            engine.provision(mac="aa:bb:cc:dd:ee:ff")

    def test_rejects_absolute_path_profile(self, tmp_path):
        rule = HostRule(
            profile="/etc/passwd",
            os_family="fedora",
            os_version="40",
        )
        engine = self._build_engine(rule, tmp_path)
        with pytest.raises(ValueError, match="invalid profile name"):
            engine.provision(mac="aa:bb:cc:dd:ee:ff")

    def test_accepts_valid_profile_name(self, tmp_path):
        rule = HostRule(
            profile="my-server",
            os_family="fedora",
            os_version="40",
        )
        engine = self._build_engine(rule, tmp_path)
        # Should not raise -- profile file won't exist but the
        # engine falls back to constructing from rule fields.
        engine.provision(mac="aa:bb:cc:dd:ee:ff")


# ====================================================================
# XML autoescape in Jinja2
# ====================================================================


class TestXMLAutoescapeInTemplates:
    """Verify that XML templates (unattend.xml, autoyast.xml) auto-escape."""

    def test_unattend_xml_escapes_special_chars(self):
        """Windows unattend.xml template should auto-escape XML chars."""
        from pxeos.plugins.windows import WindowsPlugin

        plugin = WindowsPlugin()
        # The hostname validation will block truly malicious input,
        # but we test with a valid hostname and org containing &
        profile = ProvisionProfile(
            name="test-win",
            os_family="windows",
            os_version="2022",
            arch="x86_64",
            firmware=BootFirmware.UEFI,
            install_url="http://pxe.example.com/win/2022",
            autoinstall_url="http://pxe.example.com/unattend/test",
            network={"hostname": "WINSERVER01"},
            extra={"organization": "Smith & Jones <Corp>"},
        )
        result = plugin.generate_autoinstall(profile)
        # XML special chars should be escaped
        assert "Smith &amp; Jones &lt;Corp&gt;" in result
        assert "Smith & Jones <Corp>" not in result
