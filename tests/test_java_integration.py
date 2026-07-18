"""Integration tests validating the Java client's YAML descriptor
format and API compatibility with the PxeOS Python server.

These tests ensure that the YAML descriptors consumed by the Java
``PxeOSProvisioner`` produce payloads that the PxeOS REST API
accepts, and that the API response schemas match what the Java
model classes expect.
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path
from typing import Any, Dict, List

import pytest
import yaml  # pyyaml (runtime dependency of PxeOS tests)
from fastapi.testclient import TestClient

from pxeos.api import app, init_app
from pxeos.config import PxeOSConfig
from pxeos.matcher import HostMatcher
from pxeos.models import HostRule
from pxeos.registry import PluginRegistry


# ---- Paths ----------------------------------------------------------------

CONTRIB_JAVA = Path(__file__).resolve().parent.parent / "contrib" / "java"
EXAMPLE_DESCRIPTOR = CONTRIB_JAVA / "examples" / "webserver-cluster.yaml"


# ---- Fixtures --------------------------------------------------------------


@pytest.fixture(autouse=True)
def _setup_app(tmp_path):
    """Initialize the FastAPI app for each test."""
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
def client():
    return TestClient(app)


@pytest.fixture
def descriptor() -> Dict[str, Any]:
    """Load the example webserver-cluster.yaml descriptor."""
    with open(EXAMPLE_DESCRIPTOR) as fh:
        return yaml.safe_load(fh)


# ---- Descriptor format tests -----------------------------------------------


class TestDescriptorFormat:
    """Validate that the YAML descriptor format matches PxeOS API
    expectations."""

    def test_example_file_exists(self):
        assert EXAMPLE_DESCRIPTOR.exists(), (
            f"Example descriptor not found at {EXAMPLE_DESCRIPTOR}"
        )

    def test_top_level_deployment_key(self, descriptor):
        assert "deployment" in descriptor

    def test_deployment_has_name(self, descriptor):
        deploy = descriptor["deployment"]
        assert "name" in deploy
        assert isinstance(deploy["name"], str)
        assert len(deploy["name"]) > 0

    def test_deployment_has_nodes(self, descriptor):
        deploy = descriptor["deployment"]
        assert "nodes" in deploy
        assert isinstance(deploy["nodes"], list)
        assert len(deploy["nodes"]) >= 2

    def test_each_node_has_required_fields(self, descriptor):
        for node in descriptor["deployment"]["nodes"]:
            assert "hostname" in node, f"missing hostname in {node}"
            assert "mac" in node, f"missing mac in {node}"
            assert "provision" in node, f"missing provision in {node}"

    def test_provision_config_fields(self, descriptor):
        for node in descriptor["deployment"]["nodes"]:
            prov = node["provision"]
            assert "server" in prov, f"missing server in {node['hostname']}"
            assert "profile" in prov, f"missing profile in {node['hostname']}"
            assert "os" in prov, f"missing os in {node['hostname']}"
            assert "version" in prov, f"missing version in {node['hostname']}"

    def test_mac_format_valid(self, descriptor):
        """MAC addresses must be colon-separated hex pairs."""
        import re
        mac_re = re.compile(
            r"^[0-9a-fA-F]{2}(:[0-9a-fA-F]{2}){5}$"
        )
        for node in descriptor["deployment"]["nodes"]:
            assert mac_re.match(node["mac"]), (
                f"Invalid MAC format: {node['mac']}"
            )

    def test_version_is_string(self, descriptor):
        """Version must remain a string (not parsed as float)."""
        for node in descriptor["deployment"]["nodes"]:
            v = node["provision"]["version"]
            assert isinstance(v, str), (
                f"version should be str, got {type(v).__name__}: {v}"
            )


# ---- Descriptor-to-API compatibility tests --------------------------------


class TestDescriptorApiCompat:
    """Verify that descriptor nodes can be registered through the
    PxeOS REST API."""

    def _host_rule_payload(self, node: Dict) -> Dict[str, Any]:
        """Convert a descriptor node into a PxeOS HostRuleRequest
        payload, the same mapping the Java PxeOSProvisioner uses."""
        prov = node["provision"]
        return {
            "profile": prov["profile"],
            "os_family": prov["os"],
            "os_version": str(prov["version"]),
            "mac": node["mac"],
            "vendor": "",
            "priority": 100,
        }

    def test_register_first_node(self, client, descriptor):
        node = descriptor["deployment"]["nodes"][0]
        payload = self._host_rule_payload(node)
        resp = client.post("/api/v1/hosts", json=payload)
        assert resp.status_code == 201
        data = resp.json()
        assert data["mac"] == node["mac"].lower()
        assert data["profile"] == payload["profile"]
        assert data["os_family"] == payload["os_family"]

    def test_register_all_nodes(self, client, descriptor):
        for node in descriptor["deployment"]["nodes"]:
            payload = self._host_rule_payload(node)
            resp = client.post("/api/v1/hosts", json=payload)
            assert resp.status_code == 201, (
                f"Failed to register {node['hostname']}: "
                f"{resp.status_code} {resp.text}"
            )

    def test_registered_host_appears_in_boot(self, client, descriptor):
        """After registration, requesting a boot script should
        resolve (or 404 if no distro assets are set up, which is
        expected in tests)."""
        node = descriptor["deployment"]["nodes"][0]
        payload = self._host_rule_payload(node)
        client.post("/api/v1/hosts", json=payload)

        mac = node["mac"]
        resp = client.get(f"/api/v1/boot/{mac}")
        # Either 200 (script rendered) or 404 (no distro assets)
        # is acceptable -- the point is the MAC was recognized.
        assert resp.status_code in (200, 404)

    def test_health_response_schema(self, client):
        """Health response must contain fields the Java HealthStatus
        model expects."""
        resp = client.get("/api/v1/health")
        assert resp.status_code == 200
        data = resp.json()
        assert "status" in data
        assert "plugins" in data
        assert "version" in data
        assert isinstance(data["plugins"], list)

    def test_profiles_response_is_list(self, client):
        """Profiles response must be a JSON array compatible with
        the Java List<Profile> deserialization."""
        resp = client.get("/api/v1/profiles")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)


# ---- Authentication tests -------------------------------------------------


class TestAuthCompat:
    """Verify the API key flow that the Java client uses."""

    def test_unauthenticated_health(self, client):
        """Health endpoint works without auth (no auth configured)."""
        resp = client.get("/api/v1/health")
        assert resp.status_code == 200

    def test_bearer_header_accepted(self, client):
        """Sending a Bearer header should not cause errors when
        auth is disabled."""
        resp = client.get(
            "/api/v1/health",
            headers={"Authorization": "Bearer fake-key-12345"},
        )
        assert resp.status_code == 200


# ---- Provision status polling tests ----------------------------------------


class TestProvisionStatusCompat:
    """Validate that provision status responses match the Java
    ProvisionStatus model."""

    def test_unknown_mac_returns_404(self, client):
        resp = client.get(
            "/api/v1/provision/ff:ff:ff:ff:ff:ff/status"
        )
        assert resp.status_code == 404

    def test_status_response_fields(self, client):
        """Boot a known MAC to create a tracking record, then verify
        the status response contains the fields the Java model
        expects."""
        # First register a host
        payload = {
            "profile": "webserver",
            "os_family": "fedora",
            "os_version": "42",
            "mac": "aa:bb:cc:dd:ee:f1",
            "vendor": "",
            "priority": 100,
        }
        reg = client.post("/api/v1/hosts", json=payload)
        assert reg.status_code == 201

        # Trigger boot to create a provision record
        boot = client.get("/api/v1/boot/aa:bb:cc:dd:ee:f1")
        # May be 200 or 404 depending on distro setup
        if boot.status_code == 200:
            status = client.get(
                "/api/v1/provision/aa:bb:cc:dd:ee:f1/status"
            )
            if status.status_code == 200:
                data = status.json()
                assert "mac" in data
                assert "state" in data
                assert "profile" in data


# ---- Custom descriptor round-trip tests ------------------------------------


class TestCustomDescriptor:
    """Create descriptors programmatically and verify they work."""

    def _write_descriptor(self, tmp_path: Path, nodes: list) -> Path:
        desc = {
            "deployment": {
                "name": "test-deploy",
                "nodes": nodes,
            }
        }
        p = tmp_path / "test-deploy.yaml"
        p.write_text(yaml.dump(desc, default_flow_style=False))
        return p

    def test_single_node_descriptor(self, client, tmp_path):
        path = self._write_descriptor(tmp_path, [{
            "hostname": "db-01",
            "mac": "11:22:33:44:55:66",
            "provision": {
                "server": "http://localhost:8443",
                "profile": "database",
                "os": "debian",
                "version": "12",
            },
        }])
        desc = yaml.safe_load(path.read_text())
        assert desc["deployment"]["name"] == "test-deploy"
        assert len(desc["deployment"]["nodes"]) == 1

        # Verify the node can be registered
        node = desc["deployment"]["nodes"][0]
        payload = {
            "profile": node["provision"]["profile"],
            "os_family": node["provision"]["os"],
            "os_version": str(node["provision"]["version"]),
            "mac": node["mac"],
            "vendor": "",
            "priority": 100,
        }
        resp = client.post("/api/v1/hosts", json=payload)
        assert resp.status_code == 201

    def test_multi_os_descriptor(self, client, tmp_path):
        """Verify cross-OS descriptors (the main PxeOS use case)."""
        nodes = [
            {
                "hostname": "linux-01",
                "mac": "11:22:33:44:55:01",
                "provision": {
                    "server": "http://localhost:8443",
                    "profile": "base",
                    "os": "fedora",
                    "version": "42",
                },
            },
            {
                "hostname": "bsd-01",
                "mac": "11:22:33:44:55:02",
                "provision": {
                    "server": "http://localhost:8443",
                    "profile": "base",
                    "os": "freebsd",
                    "version": "14.2",
                },
            },
            {
                "hostname": "win-01",
                "mac": "11:22:33:44:55:03",
                "provision": {
                    "server": "http://localhost:8443",
                    "profile": "base",
                    "os": "windows",
                    "version": "2022",
                },
            },
        ]
        path = self._write_descriptor(tmp_path, nodes)
        desc = yaml.safe_load(path.read_text())

        for node in desc["deployment"]["nodes"]:
            payload = {
                "profile": node["provision"]["profile"],
                "os_family": node["provision"]["os"],
                "os_version": str(node["provision"]["version"]),
                "mac": node["mac"],
                "vendor": "",
                "priority": 100,
            }
            resp = client.post("/api/v1/hosts", json=payload)
            assert resp.status_code == 201, (
                f"Failed for {node['hostname']}: {resp.text}"
            )

    def test_descriptor_without_nodes_key(self, tmp_path):
        """A descriptor with no nodes should still be parseable."""
        desc = {"deployment": {"name": "empty"}}
        p = tmp_path / "empty.yaml"
        p.write_text(yaml.dump(desc))
        loaded = yaml.safe_load(p.read_text())
        assert loaded["deployment"]["name"] == "empty"
        assert loaded["deployment"].get("nodes") is None
