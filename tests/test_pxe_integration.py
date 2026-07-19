"""Comprehensive QEMU/libvirt PXE integration tests (issue #35).

Simulates full PXE boot lifecycle through the FastAPI REST API
for Fedora, Debian, and Ubuntu. Tests cover:
- iPXE script delivery and format validation
- Autoinstall config serving per OS family
- State transitions: REGISTERED -> BOOTING -> INSTALLING -> COMPLETE/FAILED
- Boot-once behavior (netboot disable after provisioning)
- Concurrent multi-host boot simulation
- Multi-OS provisioning in the same environment
- Failure and re-provisioning flows
"""

from __future__ import annotations

import textwrap
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict

import pytest
from fastapi.testclient import TestClient

from pxeos.api import app, init_app
from pxeos.config import PxeOSConfig
from pxeos.engine import LOCAL_BOOT_SCRIPT
from pxeos.matcher import HostMatcher
from pxeos.models import HostRule, ProvisionProfile
from pxeos.registry import PluginRegistry
from pxeos.state import ProvisionState, ProvisionTracker


# ---------------------------------------------------------------------------
# OS configuration table
# ---------------------------------------------------------------------------

OS_CONFIGS: Dict[str, Dict[str, Any]] = {
    "fedora": {
        "os_version": "40",
        "profile_name": "fedora-server",
        "install_url": "http://mirror.example.com/fedora/40/x86_64",
        "autoinstall_url": "http://pxe.example.com/ks/fedora-server",
        "expected_kernel": "http://mirror.example.com/fedora/40/x86_64/images/pxeboot/vmlinuz",
        "expected_initrd": "http://mirror.example.com/fedora/40/x86_64/images/pxeboot/initrd.img",
        "autoinstall_markers": ["install", "rootpw", "network"],
    },
    "debian": {
        "os_version": "12",
        "profile_name": "debian-server",
        "install_url": "http://mirror.example.com/debian/12",
        "autoinstall_url": "http://pxe.example.com/preseed/debian-server",
        "expected_kernel": "http://mirror.example.com/debian/12/install.amd/vmlinuz",
        "expected_initrd": "http://mirror.example.com/debian/12/install.amd/initrd.gz",
        "autoinstall_markers": ["d-i", "preseed"],
    },
    "ubuntu": {
        "os_version": "24.04",
        "profile_name": "ubuntu-server",
        "install_url": "http://mirror.example.com/ubuntu/24.04",
        "autoinstall_url": "http://pxe.example.com/autoinstall/ubuntu-server",
        "expected_kernel": "http://mirror.example.com/ubuntu/24.04/casper/vmlinuz",
        "expected_initrd": "http://mirror.example.com/ubuntu/24.04/casper/initrd",
        "autoinstall_markers": ["autoinstall"],
    },
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mac(index: int) -> str:
    """Generate a unique, valid MAC address from an integer index."""
    b = index.to_bytes(5, "big")
    return f"02:{b[0]:02x}:{b[1]:02x}:{b[2]:02x}:{b[3]:02x}:{b[4]:02x}"


def _create_host_rule(
    mac: str,
    os_family: str,
) -> HostRule:
    """Create a HostRule from OS_CONFIGS for the given os_family."""
    cfg = OS_CONFIGS[os_family]
    return HostRule(
        profile=cfg["profile_name"],
        os_family=os_family,
        os_version=cfg["os_version"],
        mac=mac,
        priority=10,
    )


def _create_profile_toml(
    profiles_dir: Path,
    os_family: str,
) -> None:
    """Write a profile TOML file for the given OS family."""
    cfg = OS_CONFIGS[os_family]
    profile_path = profiles_dir / f"{cfg['profile_name']}.toml"
    profile_path.write_text(textwrap.dedent(f"""\
        [profile]
        name = "{cfg['profile_name']}"
        os_family = "{os_family}"
        os_version = "{cfg['os_version']}"
        arch = "x86_64"
        firmware = "bios"
        install_url = "{cfg['install_url']}"
        autoinstall_url = "{cfg['autoinstall_url']}"
        packages = ["vim", "curl"]
        post_scripts = ["echo done"]
    """))


def _write_hosts_toml(
    data_dir: Path,
    rules: list[HostRule],
) -> None:
    """Write a hosts.toml file from a list of HostRule objects."""
    lines: list[str] = []
    for rule in rules:
        lines.append("[[host]]")
        if rule.mac:
            lines.append(f'mac = "{rule.mac}"')
        lines.append(f'profile = "{rule.profile}"')
        lines.append(f'os_family = "{rule.os_family}"')
        lines.append(f'os_version = "{rule.os_version}"')
        lines.append(f"priority = {rule.priority}")
        lines.append("")
    (data_dir / "hosts.toml").write_text("\n".join(lines))


def _setup_environment(
    tmp_path: Path,
    os_families: list[str],
    mac_map: Dict[str, str],
) -> TestClient:
    """Create config, profiles, host rules, and initialize the FastAPI app.

    Args:
        tmp_path: pytest temporary directory.
        os_families: OS families to configure (e.g. ["fedora", "debian"]).
        mac_map: Mapping of MAC address -> os_family.

    Returns:
        A FastAPI TestClient ready for requests.
    """
    data_dir = tmp_path / "data"
    data_dir.mkdir(exist_ok=True)
    distro_dir = tmp_path / "distros"
    distro_dir.mkdir(exist_ok=True)
    profiles_dir = data_dir / "profiles"
    profiles_dir.mkdir(exist_ok=True)

    # Write profile TOML files
    for os_family in os_families:
        _create_profile_toml(profiles_dir, os_family)

    # Build host rules from mac_map
    rules = []
    for mac, os_family in mac_map.items():
        rules.append(_create_host_rule(mac, os_family))
    _write_hosts_toml(data_dir, rules)

    # Load hosts and initialize the app
    from pxeos.config import load_hosts

    loaded_rules = load_hosts(data_dir / "hosts.toml")
    registry = PluginRegistry()
    registry.load_builtins()
    config = PxeOSConfig(
        data_dir=data_dir,
        distro_root=distro_dir,
    )
    matcher = HostMatcher(loaded_rules)
    init_app(registry, config, matcher)

    return TestClient(app)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(params=["fedora", "debian", "ubuntu"], ids=lambda x: x)
def os_family(request):
    """Parametrize tests across all three OS families."""
    return request.param


# ===========================================================================
# TestPxeBootLifecycle - Full lifecycle per OS
# ===========================================================================


class TestPxeBootLifecycle:
    """Full PXE boot lifecycle: register -> boot -> autoinstall -> complete."""

    def test_boot_script_starts_with_ipxe_shebang(self, tmp_path, os_family):
        mac = _make_mac(1)
        client = _setup_environment(tmp_path, [os_family], {mac: os_family})

        resp = client.get(f"/api/v1/boot/{mac}")
        assert resp.status_code == 200
        assert resp.text.startswith("#!ipxe")

    def test_boot_script_has_kernel_line(self, tmp_path, os_family):
        mac = _make_mac(2)
        client = _setup_environment(tmp_path, [os_family], {mac: os_family})
        cfg = OS_CONFIGS[os_family]

        resp = client.get(f"/api/v1/boot/{mac}")
        assert resp.status_code == 200
        assert f"kernel {cfg['expected_kernel']}" in resp.text

    def test_boot_script_has_initrd_line(self, tmp_path, os_family):
        mac = _make_mac(3)
        client = _setup_environment(tmp_path, [os_family], {mac: os_family})
        cfg = OS_CONFIGS[os_family]

        resp = client.get(f"/api/v1/boot/{mac}")
        assert resp.status_code == 200
        assert f"initrd {cfg['expected_initrd']}" in resp.text

    def test_boot_script_has_boot_line(self, tmp_path, os_family):
        mac = _make_mac(4)
        client = _setup_environment(tmp_path, [os_family], {mac: os_family})

        resp = client.get(f"/api/v1/boot/{mac}")
        assert resp.status_code == 200
        assert "\nboot\n" in resp.text

    def test_boot_script_has_autoinstall_reference(self, tmp_path, os_family):
        mac = _make_mac(5)
        client = _setup_environment(tmp_path, [os_family], {mac: os_family})
        cfg = OS_CONFIGS[os_family]

        resp = client.get(f"/api/v1/boot/{mac}")
        assert resp.status_code == 200
        assert cfg["autoinstall_url"] in resp.text

    def test_autoinstall_returns_os_specific_content(self, tmp_path, os_family):
        mac = _make_mac(6)
        client = _setup_environment(tmp_path, [os_family], {mac: os_family})
        cfg = OS_CONFIGS[os_family]

        resp = client.get(f"/api/v1/autoinstall/{mac}")
        assert resp.status_code == 200
        content = resp.text
        # Check that at least one OS-specific marker is present
        assert any(
            marker in content for marker in cfg["autoinstall_markers"]
        ), (
            f"Expected one of {cfg['autoinstall_markers']} in "
            f"{os_family} autoinstall output"
        )

    def test_autoinstall_content_type_is_text(self, tmp_path, os_family):
        mac = _make_mac(7)
        client = _setup_environment(tmp_path, [os_family], {mac: os_family})

        resp = client.get(f"/api/v1/autoinstall/{mac}")
        assert resp.status_code == 200
        assert "text/plain" in resp.headers["content-type"]

    def test_state_transitions_registered_to_booting(self, tmp_path, os_family):
        """GET /boot/{mac} transitions state to BOOTING."""
        mac = _make_mac(8)
        client = _setup_environment(tmp_path, [os_family], {mac: os_family})

        # Trigger boot script (registers + transitions to BOOTING)
        resp = client.get(f"/api/v1/boot/{mac}")
        assert resp.status_code == 200

        # Check state
        from pxeos import api as api_mod
        record = api_mod._engine.tracker.get(mac)
        assert record is not None
        assert record.state == ProvisionState.BOOTING

    def test_state_transitions_booting_to_installing(self, tmp_path, os_family):
        """GET /autoinstall/{mac} transitions state to INSTALLING."""
        mac = _make_mac(9)
        client = _setup_environment(tmp_path, [os_family], {mac: os_family})

        # Boot first (-> BOOTING)
        client.get(f"/api/v1/boot/{mac}")
        # Fetch autoinstall (-> INSTALLING)
        resp = client.get(f"/api/v1/autoinstall/{mac}")
        assert resp.status_code == 200

        from pxeos import api as api_mod
        record = api_mod._engine.tracker.get(mac)
        assert record is not None
        assert record.state == ProvisionState.INSTALLING

    def test_state_transitions_installing_to_complete(self, tmp_path, os_family):
        """POST /provision/{mac}/complete transitions state to COMPLETE."""
        mac = _make_mac(10)
        client = _setup_environment(tmp_path, [os_family], {mac: os_family})

        # Full flow: boot -> autoinstall -> complete
        client.get(f"/api/v1/boot/{mac}")
        client.get(f"/api/v1/autoinstall/{mac}")

        resp = client.post(f"/api/v1/provision/{mac}/complete")
        assert resp.status_code == 200
        data = resp.json()
        assert data["state"] == "complete"

    def test_complete_sets_completed_at(self, tmp_path, os_family):
        mac = _make_mac(11)
        client = _setup_environment(tmp_path, [os_family], {mac: os_family})

        client.get(f"/api/v1/boot/{mac}")
        client.get(f"/api/v1/autoinstall/{mac}")
        resp = client.post(f"/api/v1/provision/{mac}/complete")

        data = resp.json()
        assert data["completed_at"] is not None

    def test_state_history_tracks_all_transitions(self, tmp_path, os_family):
        """History should contain REGISTERED, BOOTING, INSTALLING, COMPLETE."""
        mac = _make_mac(12)
        client = _setup_environment(tmp_path, [os_family], {mac: os_family})

        client.get(f"/api/v1/boot/{mac}")
        client.get(f"/api/v1/autoinstall/{mac}")
        client.post(f"/api/v1/provision/{mac}/complete")

        from pxeos import api as api_mod
        record = api_mod._engine.tracker.get(mac)
        states = [s.value for s, _ in record.history]
        assert "registered" in states
        assert "booting" in states
        assert "installing" in states
        assert "complete" in states

    def test_boot_once_returns_local_boot_after_complete(
        self, tmp_path, os_family,
    ):
        """After completing provisioning and disabling netboot, the next
        boot request returns a local-boot script (exit)."""
        mac = _make_mac(13)
        client = _setup_environment(tmp_path, [os_family], {mac: os_family})

        # Full lifecycle
        client.get(f"/api/v1/boot/{mac}")
        client.get(f"/api/v1/autoinstall/{mac}")
        client.post(f"/api/v1/provision/{mac}/complete")

        # Disable netboot (boot-once)
        resp = client.post(f"/api/v1/provision/{mac}/disable-netboot")
        assert resp.status_code == 200

        # Next boot request should return local-boot script
        resp = client.get(f"/api/v1/boot/{mac}")
        assert resp.status_code == 200
        assert resp.text == LOCAL_BOOT_SCRIPT
        assert "exit" in resp.text

    def test_full_lifecycle_end_to_end(self, tmp_path, os_family):
        """Complete end-to-end lifecycle in a single test."""
        mac = _make_mac(14)
        client = _setup_environment(tmp_path, [os_family], {mac: os_family})
        cfg = OS_CONFIGS[os_family]

        # Step 1: Boot request
        boot_resp = client.get(f"/api/v1/boot/{mac}")
        assert boot_resp.status_code == 200
        assert boot_resp.text.startswith("#!ipxe")
        assert f"kernel {cfg['expected_kernel']}" in boot_resp.text
        assert f"initrd {cfg['expected_initrd']}" in boot_resp.text
        assert "\nboot\n" in boot_resp.text

        # Step 2: Autoinstall request
        autoinstall_resp = client.get(f"/api/v1/autoinstall/{mac}")
        assert autoinstall_resp.status_code == 200
        assert any(
            m in autoinstall_resp.text for m in cfg["autoinstall_markers"]
        )

        # Step 3: Mark complete
        complete_resp = client.post(f"/api/v1/provision/{mac}/complete")
        assert complete_resp.status_code == 200
        assert complete_resp.json()["state"] == "complete"

        # Step 4: Disable netboot
        disable_resp = client.post(
            f"/api/v1/provision/{mac}/disable-netboot"
        )
        assert disable_resp.status_code == 200
        assert disable_resp.json()["netboot_enabled"] is False

        # Step 5: Next boot returns local boot
        reboot_resp = client.get(f"/api/v1/boot/{mac}")
        assert reboot_resp.status_code == 200
        assert reboot_resp.text == LOCAL_BOOT_SCRIPT


# ===========================================================================
# TestPxeBootFailure - Failure and re-provisioning flows
# ===========================================================================


class TestPxeBootFailure:
    """Test failure handling and re-provisioning."""

    def test_mark_failed_transitions_state(self, tmp_path):
        mac = _make_mac(20)
        client = _setup_environment(tmp_path, ["fedora"], {mac: "fedora"})

        client.get(f"/api/v1/boot/{mac}")
        client.get(f"/api/v1/autoinstall/{mac}")

        resp = client.post(
            f"/api/v1/provision/{mac}/failed",
            json={"error": "disk error during install"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["state"] == "failed"
        assert data["error_message"] == "disk error during install"

    def test_failed_host_can_be_re_provisioned(self, tmp_path):
        """A failed host can boot again and go through the lifecycle."""
        mac = _make_mac(21)
        client = _setup_environment(tmp_path, ["fedora"], {mac: "fedora"})

        # First attempt: boot -> install -> fail
        client.get(f"/api/v1/boot/{mac}")
        client.get(f"/api/v1/autoinstall/{mac}")
        client.post(
            f"/api/v1/provision/{mac}/failed",
            json={"error": "timeout"},
        )

        # Verify state is FAILED
        from pxeos import api as api_mod
        record = api_mod._engine.tracker.get(mac)
        assert record.state == ProvisionState.FAILED

        # Second attempt: boot again (transitions back to BOOTING)
        resp = client.get(f"/api/v1/boot/{mac}")
        assert resp.status_code == 200
        assert resp.text.startswith("#!ipxe")

        record = api_mod._engine.tracker.get(mac)
        assert record.state == ProvisionState.BOOTING

    def test_failed_preserves_error_message(self, tmp_path):
        mac = _make_mac(22)
        client = _setup_environment(tmp_path, ["debian"], {mac: "debian"})

        client.get(f"/api/v1/boot/{mac}")
        resp = client.post(
            f"/api/v1/provision/{mac}/failed",
            json={"error": "kernel panic during install"},
        )
        assert resp.json()["error_message"] == "kernel panic during install"

    def test_failed_without_prior_registration_returns_404(self, tmp_path):
        mac = _make_mac(23)
        client = _setup_environment(tmp_path, ["fedora"], {mac: "fedora"})

        # Never booted, so no record exists
        resp = client.post(
            f"/api/v1/provision/{mac}/failed",
            json={"error": "never booted"},
        )
        assert resp.status_code == 404

    def test_complete_without_prior_registration_returns_404(self, tmp_path):
        mac = _make_mac(24)
        client = _setup_environment(tmp_path, ["fedora"], {mac: "fedora"})

        resp = client.post(f"/api/v1/provision/{mac}/complete")
        assert resp.status_code == 404

    def test_failed_history_includes_failure(self, tmp_path):
        mac = _make_mac(25)
        client = _setup_environment(tmp_path, ["ubuntu"], {mac: "ubuntu"})

        client.get(f"/api/v1/boot/{mac}")
        client.get(f"/api/v1/autoinstall/{mac}")
        client.post(
            f"/api/v1/provision/{mac}/failed",
            json={"error": "oom"},
        )

        from pxeos import api as api_mod
        record = api_mod._engine.tracker.get(mac)
        states = [s.value for s, _ in record.history]
        assert "failed" in states


# ===========================================================================
# TestConcurrentBoots - Thread-safe concurrent boot simulation
# ===========================================================================


class TestConcurrentBoots:
    """Simulate many hosts booting concurrently."""

    def test_concurrent_boot_scripts_correct(self, tmp_path):
        """10 hosts boot simultaneously; each gets a valid iPXE script."""
        num_hosts = 10
        macs = [_make_mac(100 + i) for i in range(num_hosts)]
        mac_map = {mac: "fedora" for mac in macs}
        client = _setup_environment(tmp_path, ["fedora"], mac_map)

        results = {}
        with ThreadPoolExecutor(max_workers=num_hosts) as executor:
            futures = {
                executor.submit(
                    client.get, f"/api/v1/boot/{mac}"
                ): mac
                for mac in macs
            }
            for future in as_completed(futures):
                mac = futures[future]
                results[mac] = future.result()

        for mac, resp in results.items():
            assert resp.status_code == 200, f"Boot failed for {mac}"
            assert resp.text.startswith("#!ipxe"), f"Bad iPXE for {mac}"
            assert "kernel" in resp.text, f"No kernel for {mac}"
            assert "\nboot\n" in resp.text, f"No boot cmd for {mac}"

    def test_concurrent_autoinstalls_correct(self, tmp_path):
        """10 hosts fetch autoinstall concurrently."""
        num_hosts = 10
        macs = [_make_mac(200 + i) for i in range(num_hosts)]
        mac_map = {mac: "fedora" for mac in macs}
        client = _setup_environment(tmp_path, ["fedora"], mac_map)

        # Boot all first
        for mac in macs:
            client.get(f"/api/v1/boot/{mac}")

        # Concurrent autoinstall requests
        results = {}
        with ThreadPoolExecutor(max_workers=num_hosts) as executor:
            futures = {
                executor.submit(
                    client.get, f"/api/v1/autoinstall/{mac}"
                ): mac
                for mac in macs
            }
            for future in as_completed(futures):
                mac = futures[future]
                results[mac] = future.result()

        for mac, resp in results.items():
            assert resp.status_code == 200, f"Autoinstall failed for {mac}"

    def test_no_state_cross_contamination(self, tmp_path):
        """Each host's state is independent under concurrency."""
        num_hosts = 12
        macs = [_make_mac(300 + i) for i in range(num_hosts)]
        mac_map = {mac: "fedora" for mac in macs}
        client = _setup_environment(tmp_path, ["fedora"], mac_map)

        # Boot all concurrently
        with ThreadPoolExecutor(max_workers=num_hosts) as executor:
            list(executor.map(
                lambda mac: client.get(f"/api/v1/boot/{mac}"), macs
            ))

        # Complete only the first half
        first_half = macs[:num_hosts // 2]
        second_half = macs[num_hosts // 2:]

        for mac in first_half:
            client.get(f"/api/v1/autoinstall/{mac}")
            client.post(f"/api/v1/provision/{mac}/complete")

        from pxeos import api as api_mod

        # First half should be COMPLETE
        for mac in first_half:
            record = api_mod._engine.tracker.get(mac)
            assert record.state == ProvisionState.COMPLETE, (
                f"Expected COMPLETE for {mac}, got {record.state}"
            )

        # Second half should still be BOOTING
        for mac in second_half:
            record = api_mod._engine.tracker.get(mac)
            assert record.state == ProvisionState.BOOTING, (
                f"Expected BOOTING for {mac}, got {record.state}"
            )

    def test_concurrent_full_lifecycle(self, tmp_path):
        """Run full lifecycle concurrently for 10 hosts."""
        num_hosts = 10
        macs = [_make_mac(400 + i) for i in range(num_hosts)]
        mac_map = {mac: "fedora" for mac in macs}
        client = _setup_environment(tmp_path, ["fedora"], mac_map)

        def full_lifecycle(mac):
            r1 = client.get(f"/api/v1/boot/{mac}")
            assert r1.status_code == 200
            r2 = client.get(f"/api/v1/autoinstall/{mac}")
            assert r2.status_code == 200
            r3 = client.post(f"/api/v1/provision/{mac}/complete")
            assert r3.status_code == 200
            return r3.json()["state"]

        with ThreadPoolExecutor(max_workers=num_hosts) as executor:
            futures = {
                executor.submit(full_lifecycle, mac): mac
                for mac in macs
            }
            for future in as_completed(futures):
                mac = futures[future]
                state = future.result()
                assert state == "complete", (
                    f"Expected complete for {mac}, got {state}"
                )


# ===========================================================================
# TestBootOnce - Boot-once behavior with netboot disable/enable
# ===========================================================================


class TestBootOnce:
    """Boot-once (netboot disable) integration tests via API."""

    def test_local_boot_after_disable(self, tmp_path):
        mac = _make_mac(30)
        client = _setup_environment(tmp_path, ["fedora"], {mac: "fedora"})

        # Boot and complete
        client.get(f"/api/v1/boot/{mac}")
        client.get(f"/api/v1/autoinstall/{mac}")
        client.post(f"/api/v1/provision/{mac}/complete")

        # Disable netboot
        client.post(f"/api/v1/provision/{mac}/disable-netboot")

        # Verify local boot
        resp = client.get(f"/api/v1/boot/{mac}")
        assert resp.status_code == 200
        assert resp.text == LOCAL_BOOT_SCRIPT

    def test_local_boot_script_starts_with_ipxe(self, tmp_path):
        mac = _make_mac(31)
        client = _setup_environment(tmp_path, ["debian"], {mac: "debian"})

        client.get(f"/api/v1/boot/{mac}")
        client.post(f"/api/v1/provision/{mac}/disable-netboot")

        resp = client.get(f"/api/v1/boot/{mac}")
        assert resp.text.startswith("#!ipxe")

    def test_local_boot_script_contains_exit(self, tmp_path):
        mac = _make_mac(32)
        client = _setup_environment(tmp_path, ["debian"], {mac: "debian"})

        client.get(f"/api/v1/boot/{mac}")
        client.post(f"/api/v1/provision/{mac}/disable-netboot")

        resp = client.get(f"/api/v1/boot/{mac}")
        assert "exit" in resp.text

    def test_re_enable_netboot_restores_pxe_boot(self, tmp_path):
        mac = _make_mac(33)
        client = _setup_environment(tmp_path, ["ubuntu"], {mac: "ubuntu"})

        # Full cycle + disable
        client.get(f"/api/v1/boot/{mac}")
        client.get(f"/api/v1/autoinstall/{mac}")
        client.post(f"/api/v1/provision/{mac}/complete")
        client.post(f"/api/v1/provision/{mac}/disable-netboot")

        # Verify local boot
        resp = client.get(f"/api/v1/boot/{mac}")
        assert resp.text == LOCAL_BOOT_SCRIPT

        # Re-enable netboot
        client.post(f"/api/v1/provision/{mac}/enable-netboot")

        # Should get PXE boot script again
        resp = client.get(f"/api/v1/boot/{mac}")
        assert resp.status_code == 200
        assert resp.text.startswith("#!ipxe")
        assert "kernel" in resp.text
        assert resp.text != LOCAL_BOOT_SCRIPT

    def test_netboot_status_reflects_disable(self, tmp_path):
        mac = _make_mac(34)
        client = _setup_environment(tmp_path, ["fedora"], {mac: "fedora"})

        client.get(f"/api/v1/boot/{mac}")
        client.post(f"/api/v1/provision/{mac}/disable-netboot")

        resp = client.get(f"/api/v1/provision/{mac}/netboot-status")
        assert resp.status_code == 200
        assert resp.json()["netboot_enabled"] is False

    def test_netboot_status_reflects_enable(self, tmp_path):
        mac = _make_mac(35)
        client = _setup_environment(tmp_path, ["fedora"], {mac: "fedora"})

        client.get(f"/api/v1/boot/{mac}")
        client.post(f"/api/v1/provision/{mac}/disable-netboot")
        client.post(f"/api/v1/provision/{mac}/enable-netboot")

        resp = client.get(f"/api/v1/provision/{mac}/netboot-status")
        assert resp.status_code == 200
        assert resp.json()["netboot_enabled"] is True

    def test_disable_netboot_idempotent(self, tmp_path):
        mac = _make_mac(36)
        client = _setup_environment(tmp_path, ["fedora"], {mac: "fedora"})

        client.get(f"/api/v1/boot/{mac}")

        resp1 = client.post(f"/api/v1/provision/{mac}/disable-netboot")
        resp2 = client.post(f"/api/v1/provision/{mac}/disable-netboot")
        assert resp1.status_code == 200
        assert resp2.status_code == 200
        assert resp2.json()["netboot_enabled"] is False

    def test_boot_once_does_not_affect_other_hosts(self, tmp_path):
        mac_a = _make_mac(37)
        mac_b = _make_mac(38)
        client = _setup_environment(
            tmp_path, ["fedora"], {mac_a: "fedora", mac_b: "fedora"}
        )

        # Boot both
        client.get(f"/api/v1/boot/{mac_a}")
        client.get(f"/api/v1/boot/{mac_b}")

        # Disable only mac_a
        client.post(f"/api/v1/provision/{mac_a}/disable-netboot")

        # mac_a -> local boot, mac_b -> PXE boot
        resp_a = client.get(f"/api/v1/boot/{mac_a}")
        resp_b = client.get(f"/api/v1/boot/{mac_b}")
        assert resp_a.text == LOCAL_BOOT_SCRIPT
        assert resp_b.text != LOCAL_BOOT_SCRIPT
        assert "kernel" in resp_b.text


# ===========================================================================
# TestMultiOS - Different OS families in the same environment
# ===========================================================================


class TestMultiOS:
    """Multiple OS families provisioned simultaneously."""

    def test_different_macs_get_different_os_boot_scripts(self, tmp_path):
        mac_fedora = _make_mac(50)
        mac_debian = _make_mac(51)
        mac_ubuntu = _make_mac(52)

        client = _setup_environment(
            tmp_path,
            ["fedora", "debian", "ubuntu"],
            {
                mac_fedora: "fedora",
                mac_debian: "debian",
                mac_ubuntu: "ubuntu",
            },
        )

        resp_f = client.get(f"/api/v1/boot/{mac_fedora}")
        resp_d = client.get(f"/api/v1/boot/{mac_debian}")
        resp_u = client.get(f"/api/v1/boot/{mac_ubuntu}")

        # All should be valid iPXE scripts
        for resp in [resp_f, resp_d, resp_u]:
            assert resp.status_code == 200
            assert resp.text.startswith("#!ipxe")

        # Each should have its OS-specific kernel path
        assert "images/pxeboot/vmlinuz" in resp_f.text
        assert "install.amd/vmlinuz" in resp_d.text
        assert "casper/vmlinuz" in resp_u.text

    def test_different_macs_get_correct_autoinstall_format(self, tmp_path):
        mac_fedora = _make_mac(53)
        mac_debian = _make_mac(54)
        mac_ubuntu = _make_mac(55)

        client = _setup_environment(
            tmp_path,
            ["fedora", "debian", "ubuntu"],
            {
                mac_fedora: "fedora",
                mac_debian: "debian",
                mac_ubuntu: "ubuntu",
            },
        )

        fedora_ai = client.get(f"/api/v1/autoinstall/{mac_fedora}")
        debian_ai = client.get(f"/api/v1/autoinstall/{mac_debian}")
        ubuntu_ai = client.get(f"/api/v1/autoinstall/{mac_ubuntu}")

        # Fedora uses Kickstart
        assert any(
            m in fedora_ai.text
            for m in OS_CONFIGS["fedora"]["autoinstall_markers"]
        )
        # Debian uses preseed
        assert any(
            m in debian_ai.text
            for m in OS_CONFIGS["debian"]["autoinstall_markers"]
        )
        # Ubuntu uses cloud-init autoinstall
        assert any(
            m in ubuntu_ai.text
            for m in OS_CONFIGS["ubuntu"]["autoinstall_markers"]
        )

    def test_multi_os_concurrent_lifecycle(self, tmp_path):
        """All three OS families can complete their lifecycle concurrently."""
        mac_fedora = _make_mac(56)
        mac_debian = _make_mac(57)
        mac_ubuntu = _make_mac(58)

        client = _setup_environment(
            tmp_path,
            ["fedora", "debian", "ubuntu"],
            {
                mac_fedora: "fedora",
                mac_debian: "debian",
                mac_ubuntu: "ubuntu",
            },
        )

        def lifecycle(mac):
            r1 = client.get(f"/api/v1/boot/{mac}")
            assert r1.status_code == 200
            r2 = client.get(f"/api/v1/autoinstall/{mac}")
            assert r2.status_code == 200
            r3 = client.post(f"/api/v1/provision/{mac}/complete")
            assert r3.status_code == 200
            return mac, r3.json()["state"]

        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = [
                executor.submit(lifecycle, mac)
                for mac in [mac_fedora, mac_debian, mac_ubuntu]
            ]
            for future in as_completed(futures):
                mac, state = future.result()
                assert state == "complete", (
                    f"Expected complete for {mac}, got {state}"
                )

    def test_multi_os_state_isolation(self, tmp_path):
        """State of one OS host does not affect another."""
        mac_fedora = _make_mac(59)
        mac_debian = _make_mac(60)

        client = _setup_environment(
            tmp_path,
            ["fedora", "debian"],
            {mac_fedora: "fedora", mac_debian: "debian"},
        )

        # Boot both
        client.get(f"/api/v1/boot/{mac_fedora}")
        client.get(f"/api/v1/boot/{mac_debian}")

        # Complete only Fedora
        client.get(f"/api/v1/autoinstall/{mac_fedora}")
        client.post(f"/api/v1/provision/{mac_fedora}/complete")

        from pxeos import api as api_mod
        assert api_mod._engine.tracker.get(mac_fedora).state == (
            ProvisionState.COMPLETE
        )
        assert api_mod._engine.tracker.get(mac_debian).state == (
            ProvisionState.BOOTING
        )

    def test_multi_os_initrd_correct_per_family(self, tmp_path):
        mac_fedora = _make_mac(61)
        mac_debian = _make_mac(62)
        mac_ubuntu = _make_mac(63)

        client = _setup_environment(
            tmp_path,
            ["fedora", "debian", "ubuntu"],
            {
                mac_fedora: "fedora",
                mac_debian: "debian",
                mac_ubuntu: "ubuntu",
            },
        )

        resp_f = client.get(f"/api/v1/boot/{mac_fedora}")
        resp_d = client.get(f"/api/v1/boot/{mac_debian}")
        resp_u = client.get(f"/api/v1/boot/{mac_ubuntu}")

        assert "initrd http://mirror.example.com/fedora/40/x86_64/images/pxeboot/initrd.img" in resp_f.text
        assert "initrd http://mirror.example.com/debian/12/install.amd/initrd.gz" in resp_d.text
        assert "initrd http://mirror.example.com/ubuntu/24.04/casper/initrd" in resp_u.text


# ===========================================================================
# TestEdgeCases - Error handling and edge cases
# ===========================================================================


class TestEdgeCases:
    """Edge cases and error handling in the PXE integration flow."""

    def test_boot_unknown_mac_returns_404(self, tmp_path):
        """A MAC with no matching host rule returns 404."""
        known_mac = _make_mac(70)
        unknown_mac = _make_mac(99)
        client = _setup_environment(
            tmp_path, ["fedora"], {known_mac: "fedora"}
        )

        resp = client.get(f"/api/v1/boot/{unknown_mac}")
        assert resp.status_code == 404

    def test_autoinstall_unknown_mac_returns_404(self, tmp_path):
        known_mac = _make_mac(71)
        unknown_mac = _make_mac(98)
        client = _setup_environment(
            tmp_path, ["fedora"], {known_mac: "fedora"}
        )

        resp = client.get(f"/api/v1/autoinstall/{unknown_mac}")
        assert resp.status_code == 404

    def test_invalid_mac_format_returns_422(self, tmp_path):
        mac = _make_mac(72)
        client = _setup_environment(tmp_path, ["fedora"], {mac: "fedora"})

        resp = client.get("/api/v1/boot/not-a-mac")
        assert resp.status_code == 422

    def test_boot_script_response_is_text_plain(self, tmp_path):
        mac = _make_mac(73)
        client = _setup_environment(tmp_path, ["fedora"], {mac: "fedora"})

        resp = client.get(f"/api/v1/boot/{mac}")
        assert "text/plain" in resp.headers["content-type"]

    def test_multiple_boot_requests_same_mac(self, tmp_path):
        """Requesting boot script multiple times for the same MAC works."""
        mac = _make_mac(74)
        client = _setup_environment(tmp_path, ["fedora"], {mac: "fedora"})

        resp1 = client.get(f"/api/v1/boot/{mac}")
        resp2 = client.get(f"/api/v1/boot/{mac}")

        assert resp1.status_code == 200
        assert resp2.status_code == 200
        assert resp1.text == resp2.text

    def test_autoinstall_before_boot_still_works(self, tmp_path):
        """Calling autoinstall before boot registers and serves content."""
        mac = _make_mac(75)
        client = _setup_environment(tmp_path, ["debian"], {mac: "debian"})

        resp = client.get(f"/api/v1/autoinstall/{mac}")
        assert resp.status_code == 200

        from pxeos import api as api_mod
        record = api_mod._engine.tracker.get(mac)
        assert record is not None
        assert record.state == ProvisionState.INSTALLING

    def test_provision_status_endpoint(self, tmp_path):
        """GET /provision/{mac}/status returns the current state."""
        mac = _make_mac(76)
        client = _setup_environment(tmp_path, ["fedora"], {mac: "fedora"})

        client.get(f"/api/v1/boot/{mac}")

        resp = client.get(f"/api/v1/provision/{mac}/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["mac"] == mac
        assert data["state"] == "booting"
        assert data["os_family"] == "fedora"

    def test_list_provisions_returns_all_hosts(self, tmp_path):
        """GET /provision returns all provisioning records."""
        mac_a = _make_mac(77)
        mac_b = _make_mac(78)
        client = _setup_environment(
            tmp_path, ["fedora"], {mac_a: "fedora", mac_b: "fedora"}
        )

        client.get(f"/api/v1/boot/{mac_a}")
        client.get(f"/api/v1/boot/{mac_b}")

        resp = client.get("/api/v1/provision")
        assert resp.status_code == 200
        data = resp.json()
        macs_returned = {r["mac"] for r in data}
        assert mac_a in macs_returned
        assert mac_b in macs_returned


# ===========================================================================
# TestFedoraSpecific - Fedora Kickstart specifics
# ===========================================================================


class TestFedoraSpecific:
    """Fedora-specific autoinstall content validation."""

    def test_kickstart_has_install_directive(self, tmp_path):
        mac = _make_mac(80)
        client = _setup_environment(tmp_path, ["fedora"], {mac: "fedora"})

        resp = client.get(f"/api/v1/autoinstall/{mac}")
        assert resp.status_code == 200
        assert "install" in resp.text.lower() or "url" in resp.text.lower()

    def test_kickstart_has_network_config(self, tmp_path):
        mac = _make_mac(81)
        client = _setup_environment(tmp_path, ["fedora"], {mac: "fedora"})

        resp = client.get(f"/api/v1/autoinstall/{mac}")
        assert "network" in resp.text.lower()

    def test_kickstart_has_packages_section(self, tmp_path):
        mac = _make_mac(82)
        client = _setup_environment(tmp_path, ["fedora"], {mac: "fedora"})

        resp = client.get(f"/api/v1/autoinstall/{mac}")
        assert "%packages" in resp.text

    def test_boot_script_has_inst_ks_url(self, tmp_path):
        mac = _make_mac(83)
        client = _setup_environment(tmp_path, ["fedora"], {mac: "fedora"})

        resp = client.get(f"/api/v1/boot/{mac}")
        assert "inst.ks=" in resp.text


# ===========================================================================
# TestDebianSpecific - Debian preseed specifics
# ===========================================================================


class TestDebianSpecific:
    """Debian-specific preseed content validation."""

    def test_preseed_has_di_directives(self, tmp_path):
        mac = _make_mac(84)
        client = _setup_environment(tmp_path, ["debian"], {mac: "debian"})

        resp = client.get(f"/api/v1/autoinstall/{mac}")
        assert resp.status_code == 200
        assert "d-i" in resp.text

    def test_preseed_has_locale_config(self, tmp_path):
        mac = _make_mac(85)
        client = _setup_environment(tmp_path, ["debian"], {mac: "debian"})

        resp = client.get(f"/api/v1/autoinstall/{mac}")
        assert "locale" in resp.text.lower()

    def test_debian_kernel_path(self, tmp_path):
        mac = _make_mac(86)
        client = _setup_environment(tmp_path, ["debian"], {mac: "debian"})

        resp = client.get(f"/api/v1/boot/{mac}")
        assert "install.amd/vmlinuz" in resp.text


# ===========================================================================
# TestUbuntuSpecific - Ubuntu cloud-init autoinstall specifics
# ===========================================================================


class TestUbuntuSpecific:
    """Ubuntu-specific cloud-init autoinstall content validation."""

    def test_autoinstall_has_autoinstall_key(self, tmp_path):
        mac = _make_mac(87)
        client = _setup_environment(tmp_path, ["ubuntu"], {mac: "ubuntu"})

        resp = client.get(f"/api/v1/autoinstall/{mac}")
        assert resp.status_code == 200
        assert "autoinstall" in resp.text

    def test_autoinstall_has_identity_section(self, tmp_path):
        mac = _make_mac(88)
        client = _setup_environment(tmp_path, ["ubuntu"], {mac: "ubuntu"})

        resp = client.get(f"/api/v1/autoinstall/{mac}")
        assert "identity" in resp.text or "hostname" in resp.text.lower()

    def test_ubuntu_kernel_path(self, tmp_path):
        mac = _make_mac(89)
        client = _setup_environment(tmp_path, ["ubuntu"], {mac: "ubuntu"})

        resp = client.get(f"/api/v1/boot/{mac}")
        assert "casper/vmlinuz" in resp.text

    def test_ubuntu_initrd_path(self, tmp_path):
        mac = _make_mac(90)
        client = _setup_environment(tmp_path, ["ubuntu"], {mac: "ubuntu"})

        resp = client.get(f"/api/v1/boot/{mac}")
        assert "casper/initrd" in resp.text


# ===========================================================================
# TestReProvisioningFlow - Re-provisioning after completion
# ===========================================================================


class TestReProvisioningFlow:
    """Test that a host can be re-provisioned after completion."""

    def test_re_enable_netboot_allows_new_boot(self, tmp_path):
        mac = _make_mac(40)
        client = _setup_environment(tmp_path, ["fedora"], {mac: "fedora"})

        # First lifecycle
        client.get(f"/api/v1/boot/{mac}")
        client.get(f"/api/v1/autoinstall/{mac}")
        client.post(f"/api/v1/provision/{mac}/complete")
        client.post(f"/api/v1/provision/{mac}/disable-netboot")

        # Verify local boot
        resp = client.get(f"/api/v1/boot/{mac}")
        assert resp.text == LOCAL_BOOT_SCRIPT

        # Re-enable for re-provisioning
        client.post(f"/api/v1/provision/{mac}/enable-netboot")

        # New boot should return PXE script
        resp = client.get(f"/api/v1/boot/{mac}")
        assert resp.status_code == 200
        assert "kernel" in resp.text
        assert resp.text != LOCAL_BOOT_SCRIPT

    def test_re_provision_after_failure(self, tmp_path):
        mac = _make_mac(41)
        client = _setup_environment(tmp_path, ["debian"], {mac: "debian"})

        # First attempt fails
        client.get(f"/api/v1/boot/{mac}")
        client.get(f"/api/v1/autoinstall/{mac}")
        client.post(
            f"/api/v1/provision/{mac}/failed",
            json={"error": "disk full"},
        )

        # Second attempt succeeds
        client.get(f"/api/v1/boot/{mac}")
        client.get(f"/api/v1/autoinstall/{mac}")
        resp = client.post(f"/api/v1/provision/{mac}/complete")
        assert resp.json()["state"] == "complete"

    def test_full_double_provision_cycle(self, tmp_path):
        """Complete two full provision cycles for the same host."""
        mac = _make_mac(42)
        client = _setup_environment(tmp_path, ["ubuntu"], {mac: "ubuntu"})

        # Cycle 1
        client.get(f"/api/v1/boot/{mac}")
        client.get(f"/api/v1/autoinstall/{mac}")
        client.post(f"/api/v1/provision/{mac}/complete")
        client.post(f"/api/v1/provision/{mac}/disable-netboot")
        resp = client.get(f"/api/v1/boot/{mac}")
        assert resp.text == LOCAL_BOOT_SCRIPT

        # Re-enable for cycle 2
        client.post(f"/api/v1/provision/{mac}/enable-netboot")

        # Cycle 2
        resp = client.get(f"/api/v1/boot/{mac}")
        assert "kernel" in resp.text
        resp = client.get(f"/api/v1/autoinstall/{mac}")
        assert resp.status_code == 200
        resp = client.post(f"/api/v1/provision/{mac}/complete")
        assert resp.json()["state"] == "complete"
