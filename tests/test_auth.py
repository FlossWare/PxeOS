"""Tests for API key authentication and RBAC."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from pxeos.auth import (
    ApiKey,
    ApiKeyStore,
    Role,
    init_auth,
    require_role,
    role_has_access,
)
from pxeos.config import PxeOSConfig


# ---------------------------------------------------------------
# Role ordering
# ---------------------------------------------------------------


class TestRoleOrdering:

    def test_viewer_has_viewer_access(self):
        assert role_has_access(Role.VIEWER, Role.VIEWER)

    def test_operator_has_viewer_access(self):
        assert role_has_access(Role.OPERATOR, Role.VIEWER)

    def test_operator_has_operator_access(self):
        assert role_has_access(Role.OPERATOR, Role.OPERATOR)

    def test_admin_has_viewer_access(self):
        assert role_has_access(Role.ADMIN, Role.VIEWER)

    def test_admin_has_operator_access(self):
        assert role_has_access(Role.ADMIN, Role.OPERATOR)

    def test_admin_has_admin_access(self):
        assert role_has_access(Role.ADMIN, Role.ADMIN)

    def test_viewer_lacks_operator_access(self):
        assert not role_has_access(Role.VIEWER, Role.OPERATOR)

    def test_viewer_lacks_admin_access(self):
        assert not role_has_access(Role.VIEWER, Role.ADMIN)

    def test_operator_lacks_admin_access(self):
        assert not role_has_access(Role.OPERATOR, Role.ADMIN)


# ---------------------------------------------------------------
# ApiKeyStore
# ---------------------------------------------------------------


class TestApiKeyStoreCreate:

    def test_returns_raw_key_and_api_key(self, tmp_path):
        store = ApiKeyStore(tmp_path)
        raw_key, api_key = store.create_key("test", Role.VIEWER)
        assert isinstance(raw_key, str)
        assert isinstance(api_key, ApiKey)

    def test_raw_key_starts_with_prefix(self, tmp_path):
        store = ApiKeyStore(tmp_path)
        raw_key, _ = store.create_key("test", Role.VIEWER)
        assert raw_key.startswith("pxeos_")

    def test_raw_key_is_unique(self, tmp_path):
        store = ApiKeyStore(tmp_path)
        raw1, _ = store.create_key("key1", Role.VIEWER)
        raw2, _ = store.create_key("key2", Role.VIEWER)
        assert raw1 != raw2

    def test_created_key_has_correct_role(self, tmp_path):
        store = ApiKeyStore(tmp_path)
        _, api_key = store.create_key("test", Role.ADMIN)
        assert api_key.role == Role.ADMIN

    def test_created_key_is_enabled(self, tmp_path):
        store = ApiKeyStore(tmp_path)
        _, api_key = store.create_key("test", Role.VIEWER)
        assert api_key.enabled is True

    def test_created_key_has_name(self, tmp_path):
        store = ApiKeyStore(tmp_path)
        _, api_key = store.create_key("my-key", Role.OPERATOR)
        assert api_key.name == "my-key"

    def test_created_key_has_timestamp(self, tmp_path):
        store = ApiKeyStore(tmp_path)
        _, api_key = store.create_key("test", Role.VIEWER)
        assert api_key.created_at > 0


class TestApiKeyStoreValidate:

    def test_validate_correct_key(self, tmp_path):
        store = ApiKeyStore(tmp_path)
        raw_key, _ = store.create_key("test", Role.VIEWER)
        result = store.validate(raw_key)
        assert result is not None
        assert result.name == "test"

    def test_validate_wrong_key(self, tmp_path):
        store = ApiKeyStore(tmp_path)
        store.create_key("test", Role.VIEWER)
        assert store.validate("pxeos_bogus") is None

    def test_validate_disabled_key(self, tmp_path):
        store = ApiKeyStore(tmp_path)
        raw_key, _ = store.create_key("test", Role.VIEWER)
        store.revoke("test")
        assert store.validate(raw_key) is None

    def test_validate_updates_last_used(self, tmp_path):
        store = ApiKeyStore(tmp_path)
        raw_key, api_key = store.create_key("test", Role.VIEWER)
        assert api_key.last_used_at is None
        result = store.validate(raw_key)
        assert result.last_used_at is not None
        assert result.last_used_at > 0


class TestApiKeyStoreList:

    def test_list_empty(self, tmp_path):
        store = ApiKeyStore(tmp_path)
        assert store.list_keys() == []

    def test_list_returns_all(self, tmp_path):
        store = ApiKeyStore(tmp_path)
        store.create_key("key1", Role.VIEWER)
        store.create_key("key2", Role.ADMIN)
        keys = store.list_keys()
        assert len(keys) == 2
        names = {k.name for k in keys}
        assert names == {"key1", "key2"}


class TestApiKeyStoreRevoke:

    def test_revoke_disables_key(self, tmp_path):
        store = ApiKeyStore(tmp_path)
        raw_key, _ = store.create_key("test", Role.VIEWER)
        assert store.revoke("test") is True
        assert store.validate(raw_key) is None

    def test_revoke_nonexistent(self, tmp_path):
        store = ApiKeyStore(tmp_path)
        assert store.revoke("nope") is False


class TestApiKeyStoreDelete:

    def test_delete_removes_key(self, tmp_path):
        store = ApiKeyStore(tmp_path)
        store.create_key("test", Role.VIEWER)
        assert store.delete("test") is True
        assert store.list_keys() == []

    def test_delete_nonexistent(self, tmp_path):
        store = ApiKeyStore(tmp_path)
        assert store.delete("nope") is False


class TestApiKeyStoreEmpty:

    def test_is_empty_initially(self, tmp_path):
        store = ApiKeyStore(tmp_path)
        assert store.is_empty() is True

    def test_is_not_empty_after_create(self, tmp_path):
        store = ApiKeyStore(tmp_path)
        store.create_key("test", Role.VIEWER)
        assert store.is_empty() is False


class TestApiKeyStorePermissions:

    def test_file_permissions(self, tmp_path):
        store = ApiKeyStore(tmp_path)
        store.create_key("test", Role.VIEWER)
        keys_path = tmp_path / "auth_keys.json"
        mode = stat.S_IMODE(keys_path.stat().st_mode)
        assert mode == 0o600

    def test_dir_permissions(self, tmp_path):
        sub = tmp_path / "subdir"
        store = ApiKeyStore(sub)
        store.create_key("test", Role.VIEWER)
        mode = stat.S_IMODE(sub.stat().st_mode)
        assert mode == 0o700

    def test_file_is_valid_json(self, tmp_path):
        store = ApiKeyStore(tmp_path)
        store.create_key("test", Role.VIEWER)
        keys_path = tmp_path / "auth_keys.json"
        data = json.loads(keys_path.read_text())
        assert isinstance(data, dict)
        assert len(data) == 1


# ---------------------------------------------------------------
# API integration tests (auth disabled)
# ---------------------------------------------------------------


@pytest.fixture
def _app_no_auth(tmp_path):
    """Initialize app with auth disabled."""
    from pxeos.api import _cloud_init_store, app, init_app
    from pxeos.matcher import HostMatcher
    from pxeos.registry import PluginRegistry

    _cloud_init_store.clear()

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    distro_root = tmp_path / "distros"
    distro_root.mkdir()

    config = PxeOSConfig(
        data_dir=data_dir,
        distro_root=distro_root,
        auth_enabled=False,
    )
    registry = PluginRegistry()
    registry.load_builtins()
    matcher = HostMatcher([])
    init_app(registry, config, matcher)

    yield TestClient(app)

    init_auth(False, None)


class TestAuthDisabled:

    def test_health_no_auth(self, _app_no_auth):
        resp = _app_no_auth.get("/api/v1/health")
        assert resp.status_code == 200

    def test_profiles_no_auth(self, _app_no_auth):
        resp = _app_no_auth.get("/api/v1/profiles")
        assert resp.status_code == 200

    def test_distros_no_auth(self, _app_no_auth):
        resp = _app_no_auth.get("/api/v1/distros")
        assert resp.status_code == 200

    def test_secrets_list_no_auth(self, _app_no_auth):
        resp = _app_no_auth.get("/api/v1/secrets")
        assert resp.status_code == 200

    def test_provision_list_no_auth(self, _app_no_auth):
        resp = _app_no_auth.get("/api/v1/provision")
        assert resp.status_code == 200


# ---------------------------------------------------------------
# API integration tests (auth enabled)
# ---------------------------------------------------------------


@pytest.fixture
def auth_app(tmp_path):
    """Initialize app with auth enabled and create test keys."""
    from pxeos.api import _cloud_init_store, app, init_app
    from pxeos.matcher import HostMatcher
    from pxeos.registry import PluginRegistry

    _cloud_init_store.clear()

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    distro_root = tmp_path / "distros"
    distro_root.mkdir()

    config = PxeOSConfig(
        data_dir=data_dir,
        distro_root=distro_root,
        auth_enabled=True,
    )
    registry = PluginRegistry()
    registry.load_builtins()
    matcher = HostMatcher([])

    key_store = ApiKeyStore(data_dir)
    admin_raw, _ = key_store.create_key(
        "test-admin", Role.ADMIN
    )
    oper_raw, _ = key_store.create_key(
        "test-operator", Role.OPERATOR
    )
    viewer_raw, _ = key_store.create_key(
        "test-viewer", Role.VIEWER
    )

    init_app(registry, config, matcher)

    client = TestClient(app)
    yield client, admin_raw, oper_raw, viewer_raw

    init_auth(False, None)


def _bearer(key: str) -> dict:
    return {"Authorization": f"Bearer {key}"}


class TestAuthPublicRoutes:

    def test_health_no_key(self, auth_app):
        client, *_ = auth_app
        resp = client.get("/api/v1/health")
        assert resp.status_code == 200

    def test_boot_no_key_not_401(self, auth_app):
        client, *_ = auth_app
        resp = client.get("/api/v1/boot/aa:bb:cc:dd:ee:ff")
        assert resp.status_code != 401

    def test_autoinstall_no_key_not_401(self, auth_app):
        client, *_ = auth_app
        resp = client.get(
            "/api/v1/autoinstall/aa:bb:cc:dd:ee:ff"
        )
        assert resp.status_code != 401

    def test_provision_complete_no_key_not_401(
        self, auth_app
    ):
        client, *_ = auth_app
        resp = client.post(
            "/api/v1/provision/aa:bb:cc:dd:ee:ff/complete"
        )
        assert resp.status_code != 401

    def test_provision_failed_no_key_not_401(self, auth_app):
        client, *_ = auth_app
        resp = client.post(
            "/api/v1/provision/aa:bb:cc:dd:ee:ff/failed",
            json={"error": "test"},
        )
        assert resp.status_code != 401


class TestAuthProtectedRoutes:

    # --- Missing key -> 401 ---

    def test_profiles_no_key_401(self, auth_app):
        client, *_ = auth_app
        resp = client.get("/api/v1/profiles")
        assert resp.status_code == 401

    def test_distros_no_key_401(self, auth_app):
        client, *_ = auth_app
        resp = client.get("/api/v1/distros")
        assert resp.status_code == 401

    def test_secrets_list_no_key_401(self, auth_app):
        client, *_ = auth_app
        resp = client.get("/api/v1/secrets")
        assert resp.status_code == 401

    def test_provision_list_no_key_401(self, auth_app):
        client, *_ = auth_app
        resp = client.get("/api/v1/provision")
        assert resp.status_code == 401

    # --- Invalid key -> 401 ---

    def test_profiles_invalid_key_401(self, auth_app):
        client, *_ = auth_app
        resp = client.get(
            "/api/v1/profiles",
            headers=_bearer("pxeos_invalid"),
        )
        assert resp.status_code == 401

    # --- Viewer key -> viewer OK, operator/admin 403 ---

    def test_profiles_viewer_200(self, auth_app):
        client, _, _, viewer = auth_app
        resp = client.get(
            "/api/v1/profiles", headers=_bearer(viewer)
        )
        assert resp.status_code == 200

    def test_distros_viewer_200(self, auth_app):
        client, _, _, viewer = auth_app
        resp = client.get(
            "/api/v1/distros", headers=_bearer(viewer)
        )
        assert resp.status_code == 200

    def test_disable_netboot_viewer_403(self, auth_app):
        client, _, _, viewer = auth_app
        resp = client.post(
            "/api/v1/provision/aa:bb:cc:dd:ee:ff"
            "/disable-netboot",
            headers=_bearer(viewer),
        )
        assert resp.status_code == 403

    def test_create_host_viewer_403(self, auth_app):
        client, _, _, viewer = auth_app
        resp = client.post(
            "/api/v1/hosts",
            json={
                "profile": "test",
                "os_family": "fedora",
                "os_version": "41",
            },
            headers=_bearer(viewer),
        )
        assert resp.status_code == 403

    def test_set_secret_viewer_403(self, auth_app):
        client, _, _, viewer = auth_app
        resp = client.post(
            "/api/v1/secrets",
            json={"key": "test", "value": "val"},
            headers=_bearer(viewer),
        )
        assert resp.status_code == 403

    # --- Operator key -> viewer+operator OK, admin 403 ---

    def test_profiles_operator_200(self, auth_app):
        client, _, oper, _ = auth_app
        resp = client.get(
            "/api/v1/profiles", headers=_bearer(oper)
        )
        assert resp.status_code == 200

    def test_cloud_init_generate_operator_200(
        self, auth_app
    ):
        client, _, oper, _ = auth_app
        resp = client.post(
            "/api/v1/cloud-init/generate",
            json={"name": "test"},
            headers=_bearer(oper),
        )
        assert resp.status_code == 200

    def test_create_host_operator_403(self, auth_app):
        client, _, oper, _ = auth_app
        resp = client.post(
            "/api/v1/hosts",
            json={
                "profile": "test",
                "os_family": "fedora",
                "os_version": "41",
            },
            headers=_bearer(oper),
        )
        assert resp.status_code == 403

    def test_set_secret_operator_403(self, auth_app):
        client, _, oper, _ = auth_app
        resp = client.post(
            "/api/v1/secrets",
            json={"key": "test", "value": "val"},
            headers=_bearer(oper),
        )
        assert resp.status_code == 403

    # --- Admin key -> everything works ---

    def test_profiles_admin_200(self, auth_app):
        client, admin, _, _ = auth_app
        resp = client.get(
            "/api/v1/profiles", headers=_bearer(admin)
        )
        assert resp.status_code == 200

    def test_set_secret_admin_201(self, auth_app):
        client, admin, _, _ = auth_app
        resp = client.post(
            "/api/v1/secrets",
            json={"key": "test", "value": "val"},
            headers=_bearer(admin),
        )
        assert resp.status_code == 201

    def test_create_host_admin_201(self, auth_app):
        client, admin, _, _ = auth_app
        resp = client.post(
            "/api/v1/hosts",
            json={
                "profile": "test",
                "os_family": "fedora",
                "os_version": "41",
                "mac": "aa:bb:cc:dd:ee:ff",
            },
            headers=_bearer(admin),
        )
        assert resp.status_code == 201

    def test_named_distros_list_viewer_200(self, auth_app):
        client, _, _, viewer = auth_app
        resp = client.get(
            "/api/v1/named/distros",
            headers=_bearer(viewer),
        )
        assert resp.status_code == 200

    def test_named_distros_create_viewer_403(
        self, auth_app
    ):
        client, _, _, viewer = auth_app
        resp = client.post(
            "/api/v1/named/distros",
            json={
                "name": "test",
                "os_family": "fedora",
                "vendor": "",
                "version": "41",
            },
            headers=_bearer(viewer),
        )
        assert resp.status_code == 403

    def test_named_distros_create_admin_201(self, auth_app):
        client, admin, _, _ = auth_app
        resp = client.post(
            "/api/v1/named/distros",
            json={
                "name": "test",
                "os_family": "fedora",
                "vendor": "",
                "version": "41",
            },
            headers=_bearer(admin),
        )
        assert resp.status_code == 201


# ---------------------------------------------------------------
# API key management endpoints
# ---------------------------------------------------------------


class TestApiKeyManagement:

    def test_create_key_returns_raw_key(self, auth_app):
        client, admin, _, _ = auth_app
        resp = client.post(
            "/api/v1/auth/keys",
            json={"name": "new-key", "role": "viewer"},
            headers=_bearer(admin),
        )
        assert resp.status_code == 201
        data = resp.json()
        assert "raw_key" in data
        assert data["raw_key"].startswith("pxeos_")
        assert data["name"] == "new-key"
        assert data["role"] == "viewer"

    def test_create_key_requires_admin(self, auth_app):
        client, _, oper, _ = auth_app
        resp = client.post(
            "/api/v1/auth/keys",
            json={"name": "new-key"},
            headers=_bearer(oper),
        )
        assert resp.status_code == 403

    def test_create_key_invalid_role_400(self, auth_app):
        client, admin, _, _ = auth_app
        resp = client.post(
            "/api/v1/auth/keys",
            json={"name": "bad", "role": "superadmin"},
            headers=_bearer(admin),
        )
        assert resp.status_code == 400

    def test_list_keys(self, auth_app):
        client, admin, _, _ = auth_app
        resp = client.get(
            "/api/v1/auth/keys", headers=_bearer(admin)
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 3
        names = {k["name"] for k in data}
        assert "test-admin" in names
        assert "test-operator" in names
        assert "test-viewer" in names

    def test_list_keys_requires_admin(self, auth_app):
        client, _, _, viewer = auth_app
        resp = client.get(
            "/api/v1/auth/keys", headers=_bearer(viewer)
        )
        assert resp.status_code == 403

    def test_delete_key(self, auth_app):
        client, admin, _, _ = auth_app
        client.post(
            "/api/v1/auth/keys",
            json={"name": "to-delete", "role": "viewer"},
            headers=_bearer(admin),
        )
        resp = client.delete(
            "/api/v1/auth/keys/to-delete",
            headers=_bearer(admin),
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "deleted"

    def test_delete_key_not_found(self, auth_app):
        client, admin, _, _ = auth_app
        resp = client.delete(
            "/api/v1/auth/keys/nonexistent",
            headers=_bearer(admin),
        )
        assert resp.status_code == 404

    def test_delete_key_requires_admin(self, auth_app):
        client, _, oper, _ = auth_app
        resp = client.delete(
            "/api/v1/auth/keys/test-viewer",
            headers=_bearer(oper),
        )
        assert resp.status_code == 403


# ---------------------------------------------------------------
# Web routes with auth enabled
# ---------------------------------------------------------------


class TestWebRoutesWithAuth:

    def test_dashboard_no_key(self, auth_app):
        client, *_ = auth_app
        resp = client.get("/web/")
        assert resp.status_code == 200

    def test_distros_page_no_key(self, auth_app):
        client, *_ = auth_app
        resp = client.get("/web/distros")
        assert resp.status_code == 200

    def test_profiles_page_no_key(self, auth_app):
        client, *_ = auth_app
        resp = client.get("/web/profiles")
        assert resp.status_code == 200


# ---------------------------------------------------------------
# CLI auth subcommand
# ---------------------------------------------------------------


class TestCLIAuth:

    def test_parser_has_auth_subcommand(self):
        from pxeos.cli import _build_parser

        parser = _build_parser()
        subparser_action = None
        for action in parser._subparsers._actions:
            if hasattr(action, "_parser_class"):
                subparser_action = action
                break
        assert "auth" in subparser_action.choices

    @patch("pxeos.cli._init_stack")
    def test_create_key_prints_raw_key(
        self, mock_init_stack, tmp_path, capsys
    ):
        from pxeos.cli import main
        from pxeos.matcher import HostMatcher

        config = PxeOSConfig(data_dir=tmp_path)
        mock_registry = MagicMock()
        mock_registry.available = []
        matcher = HostMatcher([])
        mock_init_stack.return_value = (
            config,
            mock_registry,
            matcher,
        )

        result = main([
            "auth", "create-key",
            "--name", "my-key", "--role", "admin",
        ])
        assert result == 0
        captured = capsys.readouterr()
        assert "pxeos_" in captured.out
        assert "my-key" in captured.out
        assert "admin" in captured.out

    @patch("pxeos.cli._init_stack")
    def test_list_keys_empty(
        self, mock_init_stack, tmp_path, capsys
    ):
        from pxeos.cli import main
        from pxeos.matcher import HostMatcher

        config = PxeOSConfig(data_dir=tmp_path)
        mock_registry = MagicMock()
        mock_registry.available = []
        matcher = HostMatcher([])
        mock_init_stack.return_value = (
            config,
            mock_registry,
            matcher,
        )

        result = main(["auth", "list-keys"])
        assert result == 0
        captured = capsys.readouterr()
        assert "no API keys" in captured.out

    @patch("pxeos.cli._init_stack")
    def test_list_keys_shows_entries(
        self, mock_init_stack, tmp_path, capsys
    ):
        from pxeos.cli import main
        from pxeos.matcher import HostMatcher

        config = PxeOSConfig(data_dir=tmp_path)
        mock_registry = MagicMock()
        mock_registry.available = []
        matcher = HostMatcher([])
        mock_init_stack.return_value = (
            config,
            mock_registry,
            matcher,
        )

        main([
            "auth", "create-key",
            "--name", "test-key", "--role", "viewer",
        ])
        result = main(["auth", "list-keys"])
        assert result == 0
        captured = capsys.readouterr()
        assert "test-key" in captured.out
        assert "viewer" in captured.out

    @patch("pxeos.cli._init_stack")
    def test_revoke_key(
        self, mock_init_stack, tmp_path, capsys
    ):
        from pxeos.cli import main
        from pxeos.matcher import HostMatcher

        config = PxeOSConfig(data_dir=tmp_path)
        mock_registry = MagicMock()
        mock_registry.available = []
        matcher = HostMatcher([])
        mock_init_stack.return_value = (
            config,
            mock_registry,
            matcher,
        )

        main([
            "auth", "create-key",
            "--name", "rev-key", "--role", "viewer",
        ])
        result = main(["auth", "revoke-key", "rev-key"])
        assert result == 0
        captured = capsys.readouterr()
        assert "revoked" in captured.out

    @patch("pxeos.cli._init_stack")
    def test_revoke_nonexistent_returns_1(
        self, mock_init_stack, tmp_path, capsys
    ):
        from pxeos.cli import main
        from pxeos.matcher import HostMatcher

        config = PxeOSConfig(data_dir=tmp_path)
        mock_registry = MagicMock()
        mock_registry.available = []
        matcher = HostMatcher([])
        mock_init_stack.return_value = (
            config,
            mock_registry,
            matcher,
        )

        result = main(["auth", "revoke-key", "nope"])
        assert result == 1

    @patch("pxeos.cli._init_stack")
    def test_delete_key(
        self, mock_init_stack, tmp_path, capsys
    ):
        from pxeos.cli import main
        from pxeos.matcher import HostMatcher

        config = PxeOSConfig(data_dir=tmp_path)
        mock_registry = MagicMock()
        mock_registry.available = []
        matcher = HostMatcher([])
        mock_init_stack.return_value = (
            config,
            mock_registry,
            matcher,
        )

        main([
            "auth", "create-key",
            "--name", "del-key", "--role", "viewer",
        ])
        result = main(["auth", "delete-key", "del-key"])
        assert result == 0
        captured = capsys.readouterr()
        assert "deleted" in captured.out


# ---------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------


class TestConfigAuth:

    def test_default_auth_disabled(self):
        config = PxeOSConfig()
        assert config.auth_enabled is False

    def test_config_load_auth_section(self, tmp_path):
        from pxeos.config import load_config

        config_path = tmp_path / "pxeos.toml"
        config_path.write_text(
            "[server]\n"
            'host = "0.0.0.0"\n'
            "port = 8443\n"
            "\n"
            "[auth]\n"
            "enabled = true\n"
        )
        config = load_config(config_path)
        assert config.auth_enabled is True

    def test_config_load_auth_missing(self, tmp_path):
        from pxeos.config import load_config

        config_path = tmp_path / "pxeos.toml"
        config_path.write_text(
            "[server]\n"
            'host = "0.0.0.0"\n'
            "port = 8443\n"
        )
        config = load_config(config_path)
        assert config.auth_enabled is False


# ---------------------------------------------------------------
# Bootstrap (auto-create key when auth enabled + no keys)
# ---------------------------------------------------------------


class TestBootstrap:

    def test_bootstrap_creates_key_when_empty(
        self, tmp_path, capsys
    ):
        from pxeos.api import app, init_app
        from pxeos.matcher import HostMatcher
        from pxeos.registry import PluginRegistry

        data_dir = tmp_path / "data"
        data_dir.mkdir()
        distro_root = tmp_path / "distros"
        distro_root.mkdir()

        config = PxeOSConfig(
            data_dir=data_dir,
            distro_root=distro_root,
            auth_enabled=True,
        )
        registry = PluginRegistry()
        registry.load_builtins()
        matcher = HostMatcher([])

        init_app(registry, config, matcher)

        captured = capsys.readouterr()
        assert "BOOTSTRAP" in captured.err
        assert "pxeos_" in captured.err

        store = ApiKeyStore(data_dir)
        assert not store.is_empty()
        keys = store.list_keys()
        assert any(
            k.name == "bootstrap-admin" for k in keys
        )

        init_auth(False, None)
