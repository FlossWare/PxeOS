"""VM client backends for native hypervisor PXE boot provisioning."""

from pxeos.client.base import VirtBackend, detect_hypervisor

__all__ = ["VirtBackend", "detect_hypervisor"]
