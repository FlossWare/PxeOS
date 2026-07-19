"""End-to-end PXE boot tests using libvirt/QEMU VMs.

These tests create real VMs that PXE boot from PxeOS, verifying the
complete boot chain: DHCP → iPXE → boot script → kernel/initrd →
installer → kickstart/preseed fetch.

Requires:
  - libvirt/QEMU/virt-install on the host
  - The pxeos-test libvirt network defined (scripts/e2e-test/pxeos-test-network.xml)
  - Distro files extracted in e2e-data/distros/
  - Run with: pytest -m e2e tests/test_e2e_pxe_boot.py

Skip by default in normal test runs (no -m e2e flag).
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import time
from pathlib import Path

import pytest
import requests

pytestmark = pytest.mark.e2e

PROJECT_ROOT = Path(__file__).resolve().parent.parent
E2E_DATA = PROJECT_ROOT / "e2e-data"
SERVER_URL = "http://192.168.200.1:8880"

LINUX_VMS = [
    pytest.param(
        "fedora43",
        {
            "mac": "52:54:00:e2:e0:01",
            "profile": "fedora43-server",
            "ram": 2048,
            "os_variant": "fedora-unknown",
            "expect_autoinstall": True,
        },
        id="fedora43",
    ),
    pytest.param(
        "debian13",
        {
            "mac": "52:54:00:e2:e0:04",
            "profile": "debian13",
            "ram": 2048,
            "os_variant": "debian12",
            "expect_autoinstall": False,
        },
        id="debian13",
    ),
    pytest.param(
        "rhel10",
        {
            "mac": "52:54:00:e2:e0:03",
            "profile": "rhel10-server",
            "ram": 2048,
            "os_variant": "rhel-unknown",
            "expect_autoinstall": True,
        },
        id="rhel10",
    ),
    pytest.param(
        "rocky101",
        {
            "mac": "52:54:00:e2:e0:02",
            "profile": "rocky101-server",
            "ram": 2048,
            "os_variant": "rocky-unknown",
            "expect_autoinstall": True,
        },
        id="rocky101",
    ),
    pytest.param(
        "tinycore",
        {
            "mac": "52:54:00:e2:e0:0b",
            "profile": "tinycore",
            "ram": 512,
            "os_variant": "linux2022",
            "expect_autoinstall": False,
        },
        id="tinycore",
    ),
]


def _run(cmd: list[str], check: bool = True, **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, check=check, **kwargs)


def _vm_exists(name: str) -> bool:
    r = _run(["sudo", "virsh", "dominfo", name], check=False)
    return r.returncode == 0


def _vm_running(name: str) -> bool:
    r = _run(["sudo", "virsh", "domstate", name], check=False)
    return r.returncode == 0 and "running" in r.stdout


def _destroy_vm(name: str) -> None:
    if _vm_running(name):
        _run(["sudo", "virsh", "destroy", name], check=False)
    if _vm_exists(name):
        _run(["sudo", "virsh", "undefine", name, "--remove-all-storage"], check=False)


def _network_active(name: str) -> bool:
    r = _run(["sudo", "virsh", "net-info", name], check=False)
    return r.returncode == 0 and "Active:         yes" in r.stdout


@pytest.fixture(scope="session")
def pxe_network():
    """Ensure the pxeos-test libvirt network is active."""
    if not _network_active("pxeos-test"):
        net_xml = PROJECT_ROOT / "scripts" / "e2e-test" / "pxeos-test-network.xml"
        if not net_xml.exists():
            pytest.skip("pxeos-test-network.xml not found")
        r = _run(["sudo", "virsh", "net-info", "pxeos-test"], check=False)
        if r.returncode != 0:
            _run(["sudo", "virsh", "net-define", str(net_xml)])
        _run(["sudo", "virsh", "net-start", "pxeos-test"])
    yield
    # Don't tear down the network — it may be shared


@pytest.fixture(scope="session")
def pxeos_server(pxe_network):
    """Start PxeOS server for e2e testing."""
    config_path = E2E_DATA / "pxeos.toml"
    if not config_path.exists():
        pytest.skip("e2e-data/pxeos.toml not found")

    try:
        r = requests.get(f"{SERVER_URL}/api/v1/health", timeout=2)
        if r.status_code == 200:
            yield SERVER_URL
            return
    except Exception:
        pass

    proc = subprocess.Popen(
        [
            "python3", "-m", "pxeos.cli",
            "--config", str(config_path),
            "server", "start",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        cwd=str(PROJECT_ROOT),
    )

    for _ in range(30):
        time.sleep(1)
        try:
            r = requests.get(f"{SERVER_URL}/api/v1/health", timeout=2)
            if r.status_code == 200:
                break
        except Exception:
            if proc.poll() is not None:
                pytest.fail(f"PxeOS server died: {proc.stdout.read().decode()}")

    yield SERVER_URL

    proc.send_signal(signal.SIGTERM)
    proc.wait(timeout=10)


@pytest.fixture()
def vm_lifecycle():
    """Factory fixture that creates a PXE VM and cleans it up after the test."""
    created_vms: list[str] = []

    def _create(name: str, mac: str, ram: int, os_variant: str) -> str:
        _destroy_vm(name)
        disk_path = f"/var/lib/libvirt/images/{name}.qcow2"
        _run([
            "sudo", "virt-install",
            "--name", name,
            "--ram", str(ram),
            "--vcpus", "1",
            "--disk", f"path={disk_path},size=10,format=qcow2",
            "--network", f"network=pxeos-test,mac={mac}",
            "--pxe", "--boot", "network",
            "--os-variant", os_variant,
            "--graphics", "vnc,listen=0.0.0.0",
            "--noautoconsole",
        ])
        created_vms.append(name)
        return name

    yield _create

    for name in created_vms:
        _destroy_vm(name)


def _wait_for_boot_request(mac: str, timeout: int = 30) -> dict:
    """Wait for PxeOS to register a boot request for this MAC."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = requests.get(
                f"{SERVER_URL}/api/v1/provision/{mac}/status",
                timeout=2,
            )
            if r.status_code == 200:
                data = r.json()
                if data.get("state") in ("booting", "installing", "complete"):
                    return data
        except Exception:
            pass
        time.sleep(2)
    pytest.fail(f"No boot request received for MAC {mac} within {timeout}s")


def _wait_for_state(mac: str, target_state: str, timeout: int = 120) -> dict:
    """Wait for provision state to reach at least the target state."""
    state_order = ["registered", "booting", "installing", "complete"]
    target_idx = state_order.index(target_state)
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = requests.get(
                f"{SERVER_URL}/api/v1/provision/{mac}/status",
                timeout=2,
            )
            if r.status_code == 200:
                data = r.json()
                current_state = data.get("state", "")
                if current_state in state_order:
                    if state_order.index(current_state) >= target_idx:
                        return data
        except Exception:
            pass
        time.sleep(3)
    pytest.fail(f"MAC {mac} did not reach state '{target_state}' within {timeout}s")


class TestPxeBootChain:
    """Verify the PXE boot chain works for each OS."""

    @pytest.mark.parametrize("os_name,vm_config", LINUX_VMS)
    def test_boot_script_served(self, pxeos_server, os_name, vm_config):
        """PxeOS returns a valid iPXE boot script for each MAC."""
        mac = vm_config["mac"]
        r = requests.get(f"{pxeos_server}/api/v1/boot/{mac}", timeout=5)
        assert r.status_code == 200
        assert r.text.startswith("#!ipxe")
        assert "kernel " in r.text
        assert "\nboot\n" in r.text

    @pytest.mark.parametrize("os_name,vm_config", LINUX_VMS)
    def test_autoinstall_served(self, pxeos_server, os_name, vm_config):
        """PxeOS returns autoinstall config for non-live OSes."""
        if not vm_config["expect_autoinstall"]:
            pytest.skip(f"{os_name} is live/no-autoinstall")
        mac = vm_config["mac"]
        r = requests.get(f"{pxeos_server}/api/v1/autoinstall/{mac}", timeout=5)
        assert r.status_code == 200
        assert len(r.text) > 50

    @pytest.mark.parametrize("os_name,vm_config", LINUX_VMS)
    @pytest.mark.timeout(180)
    def test_vm_pxe_boots(self, pxeos_server, vm_lifecycle, os_name, vm_config):
        """A real VM PXE boots: receives boot script and downloads kernel."""
        mac = vm_config["mac"]
        vm_name = f"pxeos-e2e-{os_name}"

        vm_lifecycle(vm_name, mac, vm_config["ram"], vm_config["os_variant"])

        status = _wait_for_boot_request(mac, timeout=60)
        assert status["state"] in ("booting", "installing", "complete")
        assert status["profile"] == vm_config["profile"]

    @pytest.mark.parametrize(
        "os_name,vm_config",
        [p for p in LINUX_VMS if p.values[1]["expect_autoinstall"]],
    )
    @pytest.mark.timeout(300)
    def test_installer_fetches_kickstart(
        self, pxeos_server, vm_lifecycle, os_name, vm_config,
    ):
        """For installer OSes, Anaconda/d-i fetches the kickstart/preseed."""
        mac = vm_config["mac"]
        vm_name = f"pxeos-e2e-ks-{os_name}"

        vm_lifecycle(vm_name, mac, vm_config["ram"], vm_config["os_variant"])

        status = _wait_for_state(mac, "installing", timeout=120)
        assert status["state"] == "installing"


class TestProvisionTracking:
    """Verify that PxeOS tracks provision state correctly."""

    def test_health_shows_provisions(self, pxeos_server):
        """Health endpoint reports provision count."""
        r = requests.get(f"{pxeos_server}/api/v1/health", timeout=5)
        assert r.status_code == 200
        data = r.json()
        assert "provision_count" in data
        assert isinstance(data["provision_count"], int)

    @pytest.mark.parametrize("os_name,vm_config", LINUX_VMS[:1])
    @pytest.mark.timeout(120)
    def test_state_transitions(self, pxeos_server, vm_lifecycle, os_name, vm_config):
        """Provision state goes through registered → booting."""
        mac = vm_config["mac"]
        vm_name = f"pxeos-e2e-state-{os_name}"

        vm_lifecycle(vm_name, mac, vm_config["ram"], vm_config["os_variant"])

        status = _wait_for_boot_request(mac, timeout=60)
        history_states = [h["state"] for h in status.get("history", [])]
        assert "registered" in history_states
        assert "booting" in history_states
