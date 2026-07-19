"""Unit tests for the PxeOS Ansible collection modules.

These tests exercise the module logic without requiring a running
PxeOS server by mocking the HTTP layer (``pxeos_api.api_request``).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Bootstrap: make the ansible collection package importable without an
# actual Ansible installation.  We shim the minimal surface that the
# modules use (AnsibleModule, open_url) so the tests can exercise the
# module logic in isolation.
# ---------------------------------------------------------------------------

# Create a lightweight AnsibleModule stub that captures exit_json /
# fail_json calls and exposes ``params`` / ``check_mode``.


class _StubAnsibleModule:
    """Minimal stand-in for ``ansible.module_utils.basic.AnsibleModule``."""

    def __init__(self, argument_spec=None, required_if=None, supports_check_mode=False, **kwargs):
        self.argument_spec = argument_spec or {}
        self.params: Dict[str, Any] = {}
        self.check_mode = False
        self._exit_args: Optional[Dict[str, Any]] = None
        self._fail_args: Optional[Dict[str, Any]] = None

    def exit_json(self, **kwargs):
        self._exit_args = kwargs
        raise _ExitJson(kwargs)

    def fail_json(self, **kwargs):
        self._fail_args = kwargs
        raise _FailJson(kwargs)


class _ExitJson(Exception):
    def __init__(self, kwargs):
        self.kwargs = kwargs


class _FailJson(Exception):
    def __init__(self, kwargs):
        self.kwargs = kwargs


# ---------------------------------------------------------------------------
# Shim the ``ansible`` package tree so ``from ansible...`` imports work
# without Ansible installed.
# ---------------------------------------------------------------------------

_ansible_basic = MagicMock()
_ansible_basic.AnsibleModule = _StubAnsibleModule

_ansible_urls = MagicMock()
_ansible_urls.open_url = MagicMock()

sys.modules.setdefault("ansible", MagicMock())
sys.modules.setdefault("ansible.module_utils", MagicMock())
sys.modules.setdefault("ansible.module_utils.basic", _ansible_basic)
sys.modules.setdefault("ansible.module_utils.urls", _ansible_urls)

# Shim the collection namespace so the in-tree imports resolve.
_repo_root = Path(__file__).resolve().parent.parent
_ansible_dir = _repo_root / "ansible"

sys.modules.setdefault("ansible_collections", MagicMock())
sys.modules.setdefault("ansible_collections.flossware", MagicMock())
sys.modules.setdefault("ansible_collections.flossware.pxeos", MagicMock())
sys.modules.setdefault("ansible_collections.flossware.pxeos.plugins", MagicMock())
sys.modules.setdefault("ansible_collections.flossware.pxeos.plugins.module_utils", MagicMock())

# Now import the real module_utils code so it is available.
sys.path.insert(0, str(_ansible_dir / "plugins" / "module_utils"))
import pxeos_api as _real_pxeos_api  # noqa: E402

sys.modules["ansible_collections.flossware.pxeos.plugins.module_utils.pxeos_api"] = _real_pxeos_api

# Import the modules under test (they live in ansible/plugins/modules/).
sys.path.insert(0, str(_ansible_dir / "plugins" / "modules"))
import pxeos_profile as profile_mod  # noqa: E402
import pxeos_host as host_mod  # noqa: E402


# ---------------------------------------------------------------------------
# Helper to drive a module's ``run_module()`` with given params.
# ---------------------------------------------------------------------------


def _run_module(mod, params: Dict[str, Any], check_mode: bool = False):
    """Invoke *mod.run_module()* with a stubbed AnsibleModule.

    Returns ``(exit_kwargs, fail_kwargs)``; exactly one is non-None.
    """
    stub = _StubAnsibleModule()
    stub.params = params
    stub.check_mode = check_mode

    with patch.object(mod, "AnsibleModule", return_value=stub):
        try:
            mod.run_module()
        except _ExitJson as exc:
            return exc.kwargs, None
        except _FailJson as exc:
            return None, exc.kwargs

    # Should never reach here.
    return None, {"msg": "run_module returned without exit/fail"}


# ===================================================================
# pxeos_api unit tests
# ===================================================================


class TestPxeOSAPI:
    """Tests for the shared pxeos_api helper module."""

    def test_build_headers_no_key(self):
        headers = _real_pxeos_api.build_headers()
        assert headers == {"Content-Type": "application/json"}

    def test_build_headers_with_key(self):
        headers = _real_pxeos_api.build_headers("my_key")
        assert headers["Authorization"] == "Bearer my_key"
        assert headers["Content-Type"] == "application/json"

    def test_api_request_success(self):
        mock_resp = MagicMock()
        mock_resp.getcode.return_value = 200
        mock_resp.read.return_value = b'{"name": "test"}'

        with patch.object(_real_pxeos_api, "open_url", return_value=mock_resp):
            status, body = _real_pxeos_api.api_request(
                "http://localhost/api/v1/test", "GET"
            )

        assert status == 200
        assert body == {"name": "test"}

    def test_api_request_with_data(self):
        mock_resp = MagicMock()
        mock_resp.getcode.return_value = 201
        mock_resp.read.return_value = b'{"created": true}'

        with patch.object(_real_pxeos_api, "open_url", return_value=mock_resp) as mock_open:
            status, body = _real_pxeos_api.api_request(
                "http://localhost/api/v1/test",
                "POST",
                data={"key": "value"},
                api_key="secret",
            )

        assert status == 201
        assert body == {"created": True}

        # Verify data was serialised as JSON
        call_kwargs = mock_open.call_args
        assert call_kwargs[1]["data"] == '{"key": "value"}'
        assert "Bearer secret" in call_kwargs[1]["headers"]["Authorization"]

    def test_api_request_404_raises(self):
        exc = Exception("Not found")
        exc.code = 404
        exc.read = lambda: b'{"detail": "not found"}'

        with patch.object(_real_pxeos_api, "open_url", side_effect=exc):
            with pytest.raises(_real_pxeos_api.PxeOSAPIError) as exc_info:
                _real_pxeos_api.api_request("http://localhost/api/v1/missing", "GET")

        assert exc_info.value.status == 404

    def test_api_request_empty_response(self):
        mock_resp = MagicMock()
        mock_resp.getcode.return_value = 204
        mock_resp.read.return_value = b""

        with patch.object(_real_pxeos_api, "open_url", return_value=mock_resp):
            status, body = _real_pxeos_api.api_request(
                "http://localhost/api/v1/test", "DELETE"
            )

        assert status == 204
        assert body == {}


# ===================================================================
# pxeos_profile module tests
# ===================================================================


class TestPxeosProfile:
    """Tests for the pxeos_profile Ansible module."""

    BASE_PARAMS = {
        "name": "fedora42",
        "state": "present",
        "os_family": "fedora",
        "vendor": "Fedora Project",
        "version": "42",
        "arch": "x86_64",
        "kernel_path": "/distros/fedora/42/vmlinuz",
        "initrd_path": "/distros/fedora/42/initrd.img",
        "install_url": "http://mirror.example.com/fedora/42",
        "comment": "test profile",
        "server_url": "http://localhost:8443",
        "api_key": "test_key",
        "validate_certs": False,
        "timeout": 10,
    }

    def _mock_api(self, side_effect):
        return patch.object(profile_mod, "api_request", side_effect=side_effect)

    # -- Create --

    def test_create_profile(self):
        """Profile does not exist -> create it."""
        created_body = {
            "name": "fedora42",
            "os_family": "fedora",
            "vendor": "Fedora Project",
            "version": "42",
            "arch": "x86_64",
            "kernel_path": "/distros/fedora/42/vmlinuz",
            "initrd_path": "/distros/fedora/42/initrd.img",
            "install_url": "http://mirror.example.com/fedora/42",
            "comment": "test profile",
        }

        def _side_effect(url, method, **kw):
            if method == "GET":
                raise _real_pxeos_api.PxeOSAPIError(404, "not found")
            if method == "POST":
                return 201, created_body
            raise AssertionError(f"unexpected {method} {url}")

        with self._mock_api(_side_effect):
            result, fail = _run_module(profile_mod, self.BASE_PARAMS)

        assert fail is None
        assert result["changed"] is True
        assert result["profile"]["name"] == "fedora42"

    def test_profile_already_exists_no_change(self):
        """Profile exists with identical fields -> no change."""
        existing = {
            "name": "fedora42",
            "os_family": "fedora",
            "vendor": "Fedora Project",
            "version": "42",
            "arch": "x86_64",
            "kernel_path": "/distros/fedora/42/vmlinuz",
            "initrd_path": "/distros/fedora/42/initrd.img",
            "install_url": "http://mirror.example.com/fedora/42",
            "comment": "test profile",
        }

        def _side_effect(url, method, **kw):
            if method == "GET":
                return 200, existing
            raise AssertionError(f"unexpected {method} {url}")

        with self._mock_api(_side_effect):
            result, fail = _run_module(profile_mod, self.BASE_PARAMS)

        assert fail is None
        assert result["changed"] is False

    def test_profile_update(self):
        """Profile exists with different version -> update."""
        existing = {
            "name": "fedora42",
            "os_family": "fedora",
            "vendor": "Fedora Project",
            "version": "41",  # old version
            "arch": "x86_64",
            "kernel_path": "/distros/fedora/42/vmlinuz",
            "initrd_path": "/distros/fedora/42/initrd.img",
            "install_url": "http://mirror.example.com/fedora/42",
            "comment": "test profile",
        }
        updated = {**existing, "version": "42"}

        def _side_effect(url, method, **kw):
            if method == "GET":
                return 200, existing
            if method == "PUT":
                return 200, updated
            raise AssertionError(f"unexpected {method} {url}")

        with self._mock_api(_side_effect):
            result, fail = _run_module(profile_mod, self.BASE_PARAMS)

        assert fail is None
        assert result["changed"] is True
        assert result["profile"]["version"] == "42"

    # -- Delete --

    def test_delete_profile(self):
        """Delete an existing profile."""
        existing = {"name": "fedora42", "os_family": "fedora", "version": "42",
                     "vendor": "", "arch": "x86_64"}

        def _side_effect(url, method, **kw):
            if method == "GET":
                return 200, existing
            if method == "DELETE":
                return 200, {"status": "deleted"}
            raise AssertionError(f"unexpected {method} {url}")

        params = {**self.BASE_PARAMS, "state": "absent"}
        with self._mock_api(_side_effect):
            result, fail = _run_module(profile_mod, params)

        assert fail is None
        assert result["changed"] is True

    def test_delete_nonexistent_profile(self):
        """Delete a profile that does not exist -> no change."""
        def _side_effect(url, method, **kw):
            if method == "GET":
                raise _real_pxeos_api.PxeOSAPIError(404, "not found")
            raise AssertionError(f"unexpected {method} {url}")

        params = {**self.BASE_PARAMS, "state": "absent"}
        with self._mock_api(_side_effect):
            result, fail = _run_module(profile_mod, params)

        assert fail is None
        assert result["changed"] is False

    # -- Check mode --

    def test_check_mode_create(self):
        """Check mode: would create -> changed=True, no HTTP POST."""
        call_log = []

        def _side_effect(url, method, **kw):
            call_log.append(method)
            if method == "GET":
                raise _real_pxeos_api.PxeOSAPIError(404, "not found")
            raise AssertionError(f"unexpected {method}")

        with self._mock_api(_side_effect):
            result, fail = _run_module(profile_mod, self.BASE_PARAMS, check_mode=True)

        assert fail is None
        assert result["changed"] is True
        assert "POST" not in call_log

    def test_check_mode_delete(self):
        """Check mode: would delete -> changed=True, no HTTP DELETE."""
        existing = {"name": "fedora42", "os_family": "fedora", "version": "42",
                     "vendor": "", "arch": "x86_64"}
        call_log = []

        def _side_effect(url, method, **kw):
            call_log.append(method)
            if method == "GET":
                return 200, existing
            raise AssertionError(f"unexpected {method}")

        params = {**self.BASE_PARAMS, "state": "absent"}
        with self._mock_api(_side_effect):
            result, fail = _run_module(profile_mod, params, check_mode=True)

        assert fail is None
        assert result["changed"] is True
        assert "DELETE" not in call_log

    # -- Error handling --

    def test_create_api_error(self):
        """API error on create -> fail_json."""
        def _side_effect(url, method, **kw):
            if method == "GET":
                raise _real_pxeos_api.PxeOSAPIError(404, "not found")
            if method == "POST":
                raise _real_pxeos_api.PxeOSAPIError(500, "internal error")
            raise AssertionError(f"unexpected {method}")

        with self._mock_api(_side_effect):
            result, fail = _run_module(profile_mod, self.BASE_PARAMS)

        assert result is None
        assert "Failed to create profile" in fail["msg"]

    def test_query_api_error(self):
        """Non-404 error on initial GET -> fail_json."""
        def _side_effect(url, method, **kw):
            raise _real_pxeos_api.PxeOSAPIError(500, "server error")

        with self._mock_api(_side_effect):
            result, fail = _run_module(profile_mod, self.BASE_PARAMS)

        assert result is None
        assert "Failed to query profile" in fail["msg"]

    # -- URL construction --

    def test_distro_url_with_name(self):
        assert profile_mod._distro_url("http://localhost:8443", "test") == \
            "http://localhost:8443/api/v1/named/distros/test"

    def test_distro_url_without_name(self):
        assert profile_mod._distro_url("http://localhost:8443") == \
            "http://localhost:8443/api/v1/named/distros"

    def test_distro_url_strips_trailing_slash(self):
        assert profile_mod._distro_url("http://localhost:8443/", "x") == \
            "http://localhost:8443/api/v1/named/distros/x"

    # -- Payload building --

    def test_build_payload(self):
        payload = profile_mod._build_payload(self.BASE_PARAMS)
        assert payload["name"] == "fedora42"
        assert payload["os_family"] == "fedora"
        assert payload["version"] == "42"
        assert payload["arch"] == "x86_64"
        assert payload["kernel_path"] == "/distros/fedora/42/vmlinuz"

    # -- Diff detection --

    def test_needs_update_no_changes(self):
        obj = {"name": "a", "os_family": "fedora", "version": "42"}
        desired = {"name": "a", "os_family": "fedora", "version": "42"}
        assert profile_mod._needs_update(obj, desired) == {}

    def test_needs_update_with_changes(self):
        obj = {"name": "a", "os_family": "fedora", "version": "41"}
        desired = {"name": "a", "os_family": "fedora", "version": "42"}
        changes = profile_mod._needs_update(obj, desired)
        assert changes == {"version": "42"}


# ===================================================================
# pxeos_host module tests
# ===================================================================


class TestPxeosHost:
    """Tests for the pxeos_host Ansible module."""

    BASE_PARAMS = {
        "name": "web-01",
        "state": "present",
        "mac": "aa:bb:cc:dd:ee:01",
        "profile": "fedora42",
        "distro": "",
        "hostname": "web-01.example.com",
        "gateway": "192.168.1.1",
        "nameservers": ["8.8.8.8"],
        "ip_address": "192.168.1.101",
        "netmask": "255.255.255.0",
        "comment": "web server",
        "extra": {},
        "server_url": "http://localhost:8443",
        "api_key": "test_key",
        "validate_certs": False,
        "timeout": 10,
    }

    def _mock_api(self, side_effect):
        return patch.object(host_mod, "api_request", side_effect=side_effect)

    # -- Create --

    def test_create_host(self):
        """Host does not exist -> create it."""
        created_body = {
            "name": "web-01",
            "mac": "aa:bb:cc:dd:ee:01",
            "profile": "fedora42",
            "hostname": "web-01.example.com",
        }

        def _side_effect(url, method, **kw):
            if method == "GET":
                raise _real_pxeos_api.PxeOSAPIError(404, "not found")
            if method == "POST":
                return 201, created_body
            raise AssertionError(f"unexpected {method} {url}")

        with self._mock_api(_side_effect):
            result, fail = _run_module(host_mod, self.BASE_PARAMS)

        assert fail is None
        assert result["changed"] is True
        assert result["host"]["name"] == "web-01"

    def test_host_already_exists_no_change(self):
        """Host exists with identical fields -> no change."""
        existing = {
            "name": "web-01",
            "mac": "aa:bb:cc:dd:ee:01",
            "profile": "fedora42",
            "distro": "",
            "hostname": "web-01.example.com",
            "gateway": "192.168.1.1",
            "nameservers": ["8.8.8.8"],
            "ip_address": "192.168.1.101",
            "netmask": "255.255.255.0",
            "comment": "web server",
            "extra": {},
        }

        def _side_effect(url, method, **kw):
            if method == "GET":
                return 200, existing
            raise AssertionError(f"unexpected {method} {url}")

        with self._mock_api(_side_effect):
            result, fail = _run_module(host_mod, self.BASE_PARAMS)

        assert fail is None
        assert result["changed"] is False

    def test_host_update(self):
        """Host exists with different IP -> update."""
        existing = {
            "name": "web-01",
            "mac": "aa:bb:cc:dd:ee:01",
            "profile": "fedora42",
            "distro": "",
            "hostname": "web-01.example.com",
            "gateway": "192.168.1.1",
            "nameservers": ["8.8.8.8"],
            "ip_address": "192.168.1.99",  # different
            "netmask": "255.255.255.0",
            "comment": "web server",
            "extra": {},
        }
        updated = {**existing, "ip_address": "192.168.1.101"}

        def _side_effect(url, method, **kw):
            if method == "GET":
                return 200, existing
            if method == "PUT":
                return 200, updated
            raise AssertionError(f"unexpected {method} {url}")

        with self._mock_api(_side_effect):
            result, fail = _run_module(host_mod, self.BASE_PARAMS)

        assert fail is None
        assert result["changed"] is True
        assert result["host"]["ip_address"] == "192.168.1.101"

    # -- Delete --

    def test_delete_host(self):
        existing = {"name": "web-01", "mac": "aa:bb:cc:dd:ee:01"}

        def _side_effect(url, method, **kw):
            if method == "GET":
                return 200, existing
            if method == "DELETE":
                return 200, {"status": "deleted"}
            raise AssertionError(f"unexpected {method} {url}")

        params = {**self.BASE_PARAMS, "state": "absent"}
        with self._mock_api(_side_effect):
            result, fail = _run_module(host_mod, params)

        assert fail is None
        assert result["changed"] is True

    def test_delete_nonexistent_host(self):
        def _side_effect(url, method, **kw):
            if method == "GET":
                raise _real_pxeos_api.PxeOSAPIError(404, "not found")
            raise AssertionError(f"unexpected {method} {url}")

        params = {**self.BASE_PARAMS, "state": "absent"}
        with self._mock_api(_side_effect):
            result, fail = _run_module(host_mod, params)

        assert fail is None
        assert result["changed"] is False

    # -- Check mode --

    def test_check_mode_create(self):
        call_log = []

        def _side_effect(url, method, **kw):
            call_log.append(method)
            if method == "GET":
                raise _real_pxeos_api.PxeOSAPIError(404, "not found")
            raise AssertionError(f"unexpected {method}")

        with self._mock_api(_side_effect):
            result, fail = _run_module(host_mod, self.BASE_PARAMS, check_mode=True)

        assert fail is None
        assert result["changed"] is True
        assert "POST" not in call_log

    def test_check_mode_update(self):
        existing = {
            "name": "web-01",
            "mac": "aa:bb:cc:dd:ee:01",
            "profile": "fedora42",
            "distro": "",
            "hostname": "web-01.example.com",
            "gateway": "192.168.1.1",
            "nameservers": ["8.8.8.8"],
            "ip_address": "192.168.1.99",
            "netmask": "255.255.255.0",
            "comment": "web server",
            "extra": {},
        }
        call_log = []

        def _side_effect(url, method, **kw):
            call_log.append(method)
            if method == "GET":
                return 200, existing
            raise AssertionError(f"unexpected {method}")

        with self._mock_api(_side_effect):
            result, fail = _run_module(host_mod, self.BASE_PARAMS, check_mode=True)

        assert fail is None
        assert result["changed"] is True
        assert "PUT" not in call_log
        # Check mode should show the intended state
        assert result["host"]["ip_address"] == "192.168.1.101"

    # -- Error handling --

    def test_create_api_error(self):
        def _side_effect(url, method, **kw):
            if method == "GET":
                raise _real_pxeos_api.PxeOSAPIError(404, "not found")
            if method == "POST":
                raise _real_pxeos_api.PxeOSAPIError(400, "bad request")
            raise AssertionError(f"unexpected {method}")

        with self._mock_api(_side_effect):
            result, fail = _run_module(host_mod, self.BASE_PARAMS)

        assert result is None
        assert "Failed to create host" in fail["msg"]

    def test_delete_api_error(self):
        existing = {"name": "web-01", "mac": "aa:bb:cc:dd:ee:01"}

        def _side_effect(url, method, **kw):
            if method == "GET":
                return 200, existing
            if method == "DELETE":
                raise _real_pxeos_api.PxeOSAPIError(500, "server error")
            raise AssertionError(f"unexpected {method}")

        params = {**self.BASE_PARAMS, "state": "absent"}
        with self._mock_api(_side_effect):
            result, fail = _run_module(host_mod, params)

        assert result is None
        assert "Failed to delete host" in fail["msg"]

    # -- URL construction --

    def test_host_url_with_name(self):
        assert host_mod._host_url("http://localhost:8443", "web-01") == \
            "http://localhost:8443/api/v1/named/hosts/web-01"

    def test_host_url_without_name(self):
        assert host_mod._host_url("http://localhost:8443") == \
            "http://localhost:8443/api/v1/named/hosts"

    # -- Payload building --

    def test_build_payload(self):
        payload = host_mod._build_payload(self.BASE_PARAMS)
        assert payload["name"] == "web-01"
        assert payload["mac"] == "aa:bb:cc:dd:ee:01"
        assert payload["profile"] == "fedora42"
        assert payload["nameservers"] == ["8.8.8.8"]

    def test_build_payload_defaults(self):
        params = {
            "name": "test",
            "mac": "00:11:22:33:44:55",
        }
        payload = host_mod._build_payload(params)
        assert payload["profile"] == ""
        assert payload["nameservers"] == []
        assert payload["extra"] == {}

    # -- Diff detection --

    def test_needs_update_no_changes(self):
        obj = {"name": "a", "mac": "01:02:03:04:05:06", "profile": "p"}
        desired = {"name": "a", "mac": "01:02:03:04:05:06", "profile": "p"}
        assert host_mod._needs_update(obj, desired) == {}

    def test_needs_update_mac_change(self):
        obj = {"name": "a", "mac": "01:02:03:04:05:06"}
        desired = {"name": "a", "mac": "ff:ff:ff:ff:ff:ff"}
        changes = host_mod._needs_update(obj, desired)
        assert changes == {"mac": "ff:ff:ff:ff:ff:ff"}

    def test_needs_update_nameservers_change(self):
        obj = {"name": "a", "nameservers": ["8.8.8.8"]}
        desired = {"name": "a", "nameservers": ["8.8.8.8", "8.8.4.4"]}
        changes = host_mod._needs_update(obj, desired)
        assert changes == {"nameservers": ["8.8.8.8", "8.8.4.4"]}

    def test_needs_update_extra_change(self):
        obj = {"name": "a", "extra": {}}
        desired = {"name": "a", "extra": {"rack": "A1"}}
        changes = host_mod._needs_update(obj, desired)
        assert changes == {"extra": {"rack": "A1"}}


# ===================================================================
# Environment variable fallback
# ===================================================================


class TestEnvironmentFallback:
    """Test that api_key falls back to PXEOS_API_KEY env var."""

    def test_profile_env_key(self, monkeypatch):
        monkeypatch.setenv("PXEOS_API_KEY", "env_key_123")
        created = {"name": "t", "os_family": "fedora", "version": "42",
                    "vendor": "", "arch": "x86_64", "kernel_path": "",
                    "initrd_path": "", "install_url": "", "comment": ""}

        captured_key = []

        def _side_effect(url, method, **kw):
            captured_key.append(kw.get("api_key"))
            if method == "GET":
                raise _real_pxeos_api.PxeOSAPIError(404, "not found")
            if method == "POST":
                return 201, created
            raise AssertionError(f"unexpected {method}")

        params = {
            "name": "t", "state": "present", "os_family": "fedora",
            "vendor": "", "version": "42", "arch": "x86_64",
            "kernel_path": "", "initrd_path": "", "install_url": "",
            "comment": "", "server_url": "http://localhost:8443",
            "api_key": None, "validate_certs": False, "timeout": 10,
        }

        with patch.object(profile_mod, "api_request", side_effect=_side_effect):
            result, fail = _run_module(profile_mod, params)

        assert fail is None
        # The api_key passed to api_request should be the env var value
        assert "env_key_123" in captured_key

    def test_host_env_key(self, monkeypatch):
        monkeypatch.setenv("PXEOS_API_KEY", "env_host_key")
        created = {"name": "h", "mac": "00:11:22:33:44:55"}

        captured_key = []

        def _side_effect(url, method, **kw):
            captured_key.append(kw.get("api_key"))
            if method == "GET":
                raise _real_pxeos_api.PxeOSAPIError(404, "not found")
            if method == "POST":
                return 201, created
            raise AssertionError(f"unexpected {method}")

        params = {
            "name": "h", "state": "present", "mac": "00:11:22:33:44:55",
            "profile": "", "distro": "", "hostname": "", "gateway": "",
            "nameservers": [], "ip_address": "", "netmask": "",
            "comment": "", "extra": {},
            "server_url": "http://localhost:8443",
            "api_key": None, "validate_certs": False, "timeout": 10,
        }

        with patch.object(host_mod, "api_request", side_effect=_side_effect):
            result, fail = _run_module(host_mod, params)

        assert fail is None
        assert "env_host_key" in captured_key


# ===================================================================
# Edge cases
# ===================================================================


class TestEdgeCases:
    """Miscellaneous edge-case tests."""

    def test_profile_update_api_error(self):
        """API error on PUT -> fail_json."""
        existing = {"name": "p", "os_family": "fedora", "version": "41",
                     "vendor": "", "arch": "x86_64", "kernel_path": "",
                     "initrd_path": "", "install_url": "", "comment": ""}

        def _side_effect(url, method, **kw):
            if method == "GET":
                return 200, existing
            if method == "PUT":
                raise _real_pxeos_api.PxeOSAPIError(500, "db error")
            raise AssertionError(f"unexpected {method}")

        params = {
            "name": "p", "state": "present", "os_family": "fedora",
            "vendor": "", "version": "42", "arch": "x86_64",
            "kernel_path": "", "initrd_path": "", "install_url": "",
            "comment": "", "server_url": "http://localhost:8443",
            "api_key": "k", "validate_certs": False, "timeout": 10,
        }

        with patch.object(profile_mod, "api_request", side_effect=_side_effect):
            result, fail = _run_module(profile_mod, params)

        assert result is None
        assert "Failed to update profile" in fail["msg"]

    def test_host_update_api_error(self):
        """API error on PUT for host -> fail_json."""
        existing = {
            "name": "h", "mac": "00:11:22:33:44:55", "profile": "old",
            "distro": "", "hostname": "", "gateway": "",
            "nameservers": [], "ip_address": "", "netmask": "",
            "comment": "", "extra": {},
        }

        def _side_effect(url, method, **kw):
            if method == "GET":
                return 200, existing
            if method == "PUT":
                raise _real_pxeos_api.PxeOSAPIError(500, "db error")
            raise AssertionError(f"unexpected {method}")

        params = {
            "name": "h", "state": "present", "mac": "00:11:22:33:44:55",
            "profile": "new", "distro": "", "hostname": "", "gateway": "",
            "nameservers": [], "ip_address": "", "netmask": "",
            "comment": "", "extra": {},
            "server_url": "http://localhost:8443",
            "api_key": "k", "validate_certs": False, "timeout": 10,
        }

        with patch.object(host_mod, "api_request", side_effect=_side_effect):
            result, fail = _run_module(host_mod, params)

        assert result is None
        assert "Failed to update host" in fail["msg"]

    def test_profile_delete_api_error(self):
        """API error on DELETE for profile -> fail_json."""
        existing = {"name": "p", "os_family": "fedora", "version": "42",
                     "vendor": "", "arch": "x86_64"}

        def _side_effect(url, method, **kw):
            if method == "GET":
                return 200, existing
            if method == "DELETE":
                raise _real_pxeos_api.PxeOSAPIError(500, "server error")
            raise AssertionError(f"unexpected {method}")

        params = {
            "name": "p", "state": "absent",
            "os_family": None, "vendor": "", "version": None,
            "arch": "x86_64", "kernel_path": "", "initrd_path": "",
            "install_url": "", "comment": "",
            "server_url": "http://localhost:8443",
            "api_key": "k", "validate_certs": False, "timeout": 10,
        }

        with patch.object(profile_mod, "api_request", side_effect=_side_effect):
            result, fail = _run_module(profile_mod, params)

        assert result is None
        assert "Failed to delete profile" in fail["msg"]

    def test_api_request_non_json_response(self):
        """API returns non-JSON -> should not crash."""
        mock_resp = MagicMock()
        mock_resp.getcode.return_value = 200
        mock_resp.read.return_value = b"plain text response"

        with patch.object(_real_pxeos_api, "open_url", return_value=mock_resp):
            status, body = _real_pxeos_api.api_request(
                "http://localhost/api/v1/test", "GET"
            )

        assert status == 200
        assert body == {"raw": "plain text response"}

    def test_api_request_connection_error(self):
        """Connection refused -> PxeOSAPIError with status 0."""
        exc = ConnectionError("Connection refused")
        exc.code = 0

        with patch.object(_real_pxeos_api, "open_url", side_effect=exc):
            with pytest.raises(_real_pxeos_api.PxeOSAPIError) as exc_info:
                _real_pxeos_api.api_request("http://unreachable:8443/test", "GET")

        assert exc_info.value.status == 0
