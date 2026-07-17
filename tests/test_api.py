"""Tests for the PxeOS REST API endpoints."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from pxeos.api import _cloud_init_store, app, init_app
from pxeos.config import PxeOSConfig
from pxeos.matcher import HostMatcher
from pxeos.models import DistroAssets
from pxeos.registry import PluginRegistry


@pytest.fixture(autouse=True)
def _setup_app(tmp_path):
    """Initialize the FastAPI app with real registry and config."""
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
    # Clear the cloud-init store between tests
    _cloud_init_store.clear()
    yield


@pytest.fixture
def client():
    return TestClient(app)


# ---- health ----


class TestHealth:

    def test_returns_status_ok(self, client):
        resp = client.get("/api/v1/health")

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"

    def test_returns_version(self, client):
        resp = client.get("/api/v1/health")
        data = resp.json()

        assert "version" in data
        assert data["version"] == "1.0"

    def test_returns_plugins_list(self, client):
        resp = client.get("/api/v1/health")
        data = resp.json()

        assert "plugins" in data
        assert isinstance(data["plugins"], list)
        assert len(data["plugins"]) > 0


# ---- cloud-init generate ----


class TestCloudInitGenerate:

    def test_returns_all_three_sections(self, client):
        resp = client.post(
            "/api/v1/cloud-init/generate",
            json={
                "name": "my-vm",
                "os_family": "ubuntu",
                "os_version": "24.04",
            },
        )

        assert resp.status_code == 200
        data = resp.json()
        assert "user_data" in data
        assert "meta_data" in data
        assert "network_config" in data

    def test_user_data_has_cloud_config_header(self, client):
        resp = client.post(
            "/api/v1/cloud-init/generate",
            json={"name": "test-vm"},
        )
        data = resp.json()

        assert data["user_data"].startswith("#cloud-config")

    def test_user_data_contains_hostname(self, client):
        resp = client.post(
            "/api/v1/cloud-init/generate",
            json={"name": "web-server", "hostname": "web-01"},
        )
        data = resp.json()

        assert "hostname: web-01" in data["user_data"]

    def test_meta_data_contains_instance_id(self, client):
        resp = client.post(
            "/api/v1/cloud-init/generate",
            json={"name": "db-node", "os_version": "22.04"},
        )
        data = resp.json()

        assert "instance-id:" in data["meta_data"]

    def test_meta_data_contains_local_hostname(self, client):
        resp = client.post(
            "/api/v1/cloud-init/generate",
            json={"name": "db-node", "hostname": "db-01"},
        )
        data = resp.json()

        assert "local-hostname: db-01" in data["meta_data"]

    def test_network_config_dhcp_default(self, client):
        resp = client.post(
            "/api/v1/cloud-init/generate",
            json={"name": "test-vm"},
        )
        data = resp.json()

        assert "dhcp4: true" in data["network_config"]

    def test_network_config_static(self, client):
        resp = client.post(
            "/api/v1/cloud-init/generate",
            json={
                "name": "static-vm",
                "network_method": "static",
                "network_device": "ens3",
                "address": "10.0.0.50/24",
                "gateway": "10.0.0.1",
                "nameservers": ["8.8.8.8"],
            },
        )
        data = resp.json()

        assert "dhcp4: false" in data["network_config"]
        assert "10.0.0.50/24" in data["network_config"]
        assert "10.0.0.1" in data["network_config"]
        assert "ens3:" in data["network_config"]

    def test_packages_included(self, client):
        resp = client.post(
            "/api/v1/cloud-init/generate",
            json={
                "name": "pkg-vm",
                "packages": ["nginx", "git"],
            },
        )
        data = resp.json()

        assert "packages:" in data["user_data"]
        assert "nginx" in data["user_data"]
        assert "git" in data["user_data"]

    def test_post_scripts_become_runcmd(self, client):
        resp = client.post(
            "/api/v1/cloud-init/generate",
            json={
                "name": "cmd-vm",
                "post_scripts": ["systemctl start nginx"],
            },
        )
        data = resp.json()

        assert "runcmd:" in data["user_data"]
        assert "systemctl start nginx" in data["user_data"]

    def test_custom_user(self, client):
        resp = client.post(
            "/api/v1/cloud-init/generate",
            json={
                "name": "user-vm",
                "user": "deploy",
            },
        )
        data = resp.json()

        assert "name: deploy" in data["user_data"]

    def test_ssh_keys_included(self, client):
        resp = client.post(
            "/api/v1/cloud-init/generate",
            json={
                "name": "ssh-vm",
                "ssh_authorized_keys": ["ssh-ed25519 AAAA..."],
            },
        )
        data = resp.json()

        assert "ssh_authorized_keys:" in data["user_data"]
        assert "ssh-ed25519 AAAA..." in data["user_data"]

    def test_timezone(self, client):
        resp = client.post(
            "/api/v1/cloud-init/generate",
            json={
                "name": "tz-vm",
                "timezone": "Europe/Berlin",
            },
        )
        data = resp.json()

        assert "timezone: Europe/Berlin" in data["user_data"]


# ---- cloud-init register / retrieve ----


class TestCloudInitRegister:

    def test_register_returns_instance_id(self, client):
        resp = client.post(
            "/api/v1/cloud-init/register",
            json={
                "name": "reg-vm",
                "os_version": "24.04",
                "hostname": "reg-host",
            },
        )

        assert resp.status_code == 200
        data = resp.json()
        assert "instance_id" in data
        assert data["status"] == "registered"

    def test_register_then_get_user_data(self, client):
        client.post(
            "/api/v1/cloud-init/register",
            json={
                "name": "data-vm",
                "os_version": "24.04",
                "hostname": "data-host",
            },
        )

        resp = client.get(
            "/api/v1/cloud-init/data-host-24.04/user-data"
        )

        assert resp.status_code == 200
        assert resp.headers["content-type"] == "text/yaml; charset=utf-8"
        assert resp.text.startswith("#cloud-config")

    def test_register_then_get_meta_data(self, client):
        client.post(
            "/api/v1/cloud-init/register",
            json={
                "name": "meta-vm",
                "os_version": "22.04",
                "hostname": "meta-host",
            },
        )

        resp = client.get(
            "/api/v1/cloud-init/meta-host-22.04/meta-data"
        )

        assert resp.status_code == 200
        assert "instance-id:" in resp.text
        assert "local-hostname: meta-host" in resp.text

    def test_register_then_get_network_config(self, client):
        client.post(
            "/api/v1/cloud-init/register",
            json={
                "name": "net-vm",
                "os_version": "24.04",
                "hostname": "net-host",
            },
        )

        resp = client.get(
            "/api/v1/cloud-init/net-host-24.04/network-config"
        )

        assert resp.status_code == 200
        assert "version: 2" in resp.text

    def test_user_data_404_for_unknown_instance(self, client):
        resp = client.get(
            "/api/v1/cloud-init/nonexistent-vm/user-data"
        )

        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"]

    def test_meta_data_404_for_unknown_instance(self, client):
        resp = client.get(
            "/api/v1/cloud-init/nonexistent-vm/meta-data"
        )

        assert resp.status_code == 404

    def test_network_config_404_for_unknown_instance(self, client):
        resp = client.get(
            "/api/v1/cloud-init/nonexistent-vm/network-config"
        )

        assert resp.status_code == 404

    def test_register_with_custom_instance_id(self, client):
        resp = client.post(
            "/api/v1/cloud-init/register",
            json={
                "name": "custom-vm",
                "os_version": "24.04",
                "extra": {"instance_id": "my-custom-id"},
            },
        )

        data = resp.json()
        assert data["instance_id"] == "my-custom-id"

        resp = client.get(
            "/api/v1/cloud-init/my-custom-id/user-data"
        )
        assert resp.status_code == 200


# ---- import/fetch ----


class TestImportFetch:

    @patch("pxeos.importer.import_url")
    def test_calls_import_url(self, mock_import, client, tmp_path):
        mock_assets = DistroAssets(
            kernel_path=tmp_path / "vmlinuz",
            initrd_path=tmp_path / "initrd.img",
            repo_path=tmp_path / "repo",
        )
        mock_import.return_value = mock_assets

        resp = client.post(
            "/api/v1/import/fetch",
            json={
                "url": "http://mirror.example.com/fedora/41",
                "os_family": "fedora",
                "os_version": "41",
                "arch": "x86_64",
            },
        )

        assert resp.status_code == 200
        data = resp.json()
        assert "kernel_path" in data
        assert "repo_path" in data
        mock_import.assert_called_once()

    @patch("pxeos.importer.import_url")
    def test_import_fetch_returns_paths(self, mock_import, client, tmp_path):
        mock_assets = DistroAssets(
            kernel_path=tmp_path / "vmlinuz",
            initrd_path=tmp_path / "initrd.img",
            repo_path=tmp_path / "repo",
        )
        mock_import.return_value = mock_assets

        resp = client.post(
            "/api/v1/import/fetch",
            json={
                "url": "http://mirror.example.com/ubuntu/24.04",
                "os_family": "ubuntu",
                "os_version": "24.04",
            },
        )

        assert resp.status_code == 200
        data = resp.json()
        assert "vmlinuz" in data["kernel_path"]
        assert "initrd.img" in data["initrd_path"]
        assert "repo" in data["repo_path"]

    @patch("pxeos.importer.import_url")
    def test_import_fetch_with_no_initrd(
        self, mock_import, client, tmp_path,
    ):
        mock_assets = DistroAssets(
            kernel_path=tmp_path / "vmlinuz",
            initrd_path=None,
            repo_path=tmp_path / "repo",
        )
        mock_import.return_value = mock_assets

        resp = client.post(
            "/api/v1/import/fetch",
            json={
                "url": "http://mirror.example.com/custom/1.0",
                "os_family": "fedora",
                "os_version": "1.0",
            },
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["initrd_path"] is None

    @patch("pxeos.importer.import_url")
    def test_import_fetch_vendor_passed(
        self, mock_import, client, tmp_path,
    ):
        mock_assets = DistroAssets(
            kernel_path=tmp_path / "vmlinuz",
            repo_path=tmp_path / "repo",
        )
        mock_import.return_value = mock_assets

        resp = client.post(
            "/api/v1/import/fetch",
            json={
                "url": "http://mirror.example.com/rocky/9",
                "os_family": "fedora",
                "os_version": "9",
                "vendor": "rocky",
                "arch": "aarch64",
            },
        )

        assert resp.status_code == 200
        mock_import.assert_called_once()
        args = mock_import.call_args
        # Check vendor and arch were passed through
        assert args[0][2] == "rocky"  # vendor
        assert args[0][4] == "aarch64"  # arch
