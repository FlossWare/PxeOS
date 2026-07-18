"""End-to-end VM provisioning workflow: create VM, register with PxeOS, PXE boot."""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from typing import Optional

from pxeos.client.base import VirtBackend

logger = logging.getLogger("pxeos.client.workflow")

# Terminal states that end the polling loop
_TERMINAL_STATES = {"complete", "failed"}


def provision_vm(
    server_url: str,
    profile: str,
    backend: VirtBackend,
    name: str,
    os_family: str = "fedora",
    os_version: str = "40",
    memory_mb: int = 2048,
    vcpus: int = 2,
    disk_gb: int = 20,
    bridge: Optional[str] = None,
    poll_interval: float = 10.0,
    poll_timeout: float = 3600.0,
) -> dict:
    """Create a VM, register it with PxeOS, PXE boot, and poll until done.

    Steps:
      1. Create VM with PXE-enabled NIC
      2. Get VM's MAC address
      3. Register MAC with PxeOS server (POST /api/v1/hosts)
      4. Start VM (PXE boot triggers install)
      5. Poll status (GET /api/v1/provision/{mac}/status) until complete
      6. Return result

    Args:
        server_url: Base URL of PxeOS server (e.g. "http://pxe.local:8443")
        profile: Provision profile name to use
        backend: VirtBackend instance for the target hypervisor
        name: VM name
        os_family: OS family for host registration
        os_version: OS version for host registration
        memory_mb: VM memory in megabytes
        vcpus: Number of virtual CPUs
        disk_gb: Disk size in gigabytes
        bridge: Network bridge name (backend-specific default if None)
        poll_interval: Seconds between status polls
        poll_timeout: Maximum seconds to wait for provisioning

    Returns:
        dict with keys: name, mac, status, and provision details

    Raises:
        RuntimeError: if VM creation, registration, or polling fails
    """
    server_url = server_url.rstrip("/")

    # Step 1: Create VM with PXE-enabled NIC
    logger.info("Creating VM %s on %s", name, backend.hypervisor_name)
    try:
        vm_info = backend.create_vm(
            name=name,
            mac=_generate_mac(name),
            memory_mb=memory_mb,
            vcpus=vcpus,
            disk_gb=disk_gb,
            bridge=bridge,
        )
    except Exception as exc:
        raise RuntimeError(f"failed to create VM {name!r}: {exc}") from exc

    # Step 2: Get VM's MAC address
    mac = vm_info["mac"]
    logger.info("VM %s created with MAC %s", name, mac)

    # Step 3: Register MAC with PxeOS server
    logger.info("Registering MAC %s with PxeOS at %s", mac, server_url)
    try:
        _register_host(server_url, mac, profile, os_family, os_version)
    except Exception as exc:
        raise RuntimeError(
            f"failed to register MAC {mac} with PxeOS: {exc}"
        ) from exc

    # Step 4: Start VM (PXE boot triggers install)
    logger.info("Starting VM %s for PXE boot", name)
    try:
        backend.start_vm(name)
    except Exception as exc:
        raise RuntimeError(f"failed to start VM {name!r}: {exc}") from exc

    # Step 5: Poll status until complete or timeout
    logger.info("Polling provisioning status for MAC %s", mac)
    result = _poll_provision_status(
        server_url, mac, poll_interval, poll_timeout,
    )

    # Step 6: Return result
    return {
        "name": name,
        "mac": mac,
        "hypervisor": backend.hypervisor_name,
        "status": result.get("state", "unknown"),
        "provision": result,
    }


def _generate_mac(name: str) -> str:
    """Generate a deterministic MAC address from a VM name.

    Uses the locally-administered unicast range (02:xx:xx:xx:xx:xx).
    """
    import hashlib

    digest = hashlib.sha256(name.encode()).hexdigest()
    octets = [
        "02",
        digest[0:2],
        digest[2:4],
        digest[4:6],
        digest[6:8],
        digest[8:10],
    ]
    return ":".join(octets)


def _register_host(
    server_url: str,
    mac: str,
    profile: str,
    os_family: str,
    os_version: str,
) -> dict:
    """Register a host with the PxeOS server via POST /api/v1/hosts."""
    url = f"{server_url}/api/v1/hosts"
    payload = json.dumps({
        "profile": profile,
        "os_family": os_family,
        "os_version": os_version,
        "mac": mac,
    }).encode()

    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode()
        raise RuntimeError(
            f"HTTP {exc.code} from PxeOS: {body}"
        ) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(
            f"cannot reach PxeOS server at {url}: {exc.reason}"
        ) from exc


def _poll_provision_status(
    server_url: str,
    mac: str,
    poll_interval: float,
    poll_timeout: float,
) -> dict:
    """Poll GET /api/v1/provision/{mac}/status until a terminal state.

    Returns the final status dict.
    Raises RuntimeError on timeout or connection errors.
    """
    url = f"{server_url}/api/v1/provision/{mac}/status"
    deadline = time.monotonic() + poll_timeout

    while time.monotonic() < deadline:
        try:
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req) as resp:
                data = json.loads(resp.read().decode())

            state = data.get("state", "")
            logger.info("Provision status for %s: %s", mac, state)

            if state in _TERMINAL_STATES:
                return data

        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                # Provisioning record may not exist yet
                logger.debug("No provision record yet for %s", mac)
            else:
                logger.warning(
                    "HTTP %d polling status for %s", exc.code, mac
                )
        except urllib.error.URLError as exc:
            logger.warning(
                "Cannot reach PxeOS server: %s", exc.reason
            )

        time.sleep(poll_interval)

    raise RuntimeError(
        f"provisioning timed out after {poll_timeout}s for MAC {mac}"
    )
