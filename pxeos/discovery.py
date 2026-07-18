"""Service discovery for PxeOS using mDNS/DNS-SD (zeroconf)."""

from __future__ import annotations

import logging
import socket
from typing import Any, Dict, List, Optional

from pxeos import __version__

logger = logging.getLogger("pxeos.discovery")

# mDNS service type for PxeOS
SERVICE_TYPE = "_pxeos._tcp.local."
DEFAULT_SERVICE_NAME = "pxeos"


def _get_zeroconf():
    """Import and return zeroconf classes, or None if unavailable."""
    try:
        from zeroconf import ServiceBrowser, ServiceInfo, Zeroconf

        return Zeroconf, ServiceInfo, ServiceBrowser
    except ImportError:
        return None, None, None


def register_mdns(
    host: str,
    port: int,
    service_name: str = DEFAULT_SERVICE_NAME,
    auth_enabled: bool = False,
) -> Optional[Any]:
    """Register PxeOS as an mDNS/DNS-SD service.

    Returns the Zeroconf instance (for later unregistration) or None
    if zeroconf is not installed.
    """
    Zeroconf, ServiceInfo, _ = _get_zeroconf()
    if Zeroconf is None:
        logger.warning(
            "zeroconf not installed; mDNS registration skipped"
        )
        return None

    bind_host = host
    if bind_host in ("0.0.0.0", "::"):
        bind_host = socket.gethostname()

    try:
        addresses = [socket.inet_aton(socket.gethostbyname(bind_host))]
    except (socket.gaierror, OSError):
        logger.warning(
            "cannot resolve %s for mDNS; using 127.0.0.1", bind_host
        )
        addresses = [socket.inet_aton("127.0.0.1")]

    properties = {
        b"version": __version__.encode(),
        b"auth": b"true" if auth_enabled else b"false",
        b"path": b"/api/v1",
    }

    info = ServiceInfo(
        SERVICE_TYPE,
        f"{service_name}.{SERVICE_TYPE}",
        addresses=addresses,
        port=port,
        properties=properties,
        server=f"{bind_host}.local.",
    )

    zc = Zeroconf()
    try:
        zc.register_service(info)
        logger.info(
            "registered mDNS service %s on port %d", service_name, port
        )
    except Exception as exc:
        logger.error("mDNS registration failed: %s", exc)
        zc.close()
        return None

    return zc


def discover_pxeos(timeout: float = 5.0) -> List[Dict[str, Any]]:
    """Discover PxeOS instances on the network via mDNS.

    Returns a list of dicts with keys: name, host, port, version, auth, path.
    """
    Zeroconf, ServiceInfo, ServiceBrowser = _get_zeroconf()
    if Zeroconf is None:
        logger.warning(
            "zeroconf not installed; mDNS discovery unavailable"
        )
        return []

    import threading

    found: List[Dict[str, Any]] = []
    event = threading.Event()

    class Listener:
        def add_service(self, zc, service_type, name):
            info = zc.get_service_info(service_type, name)
            if info is None:
                return
            addresses = info.parsed_addresses()
            host = addresses[0] if addresses else "unknown"
            props = info.properties or {}
            found.append({
                "name": name.replace(f".{SERVICE_TYPE}", ""),
                "host": host,
                "port": info.port,
                "version": props.get(b"version", b"").decode(),
                "auth": props.get(b"auth", b"false").decode() == "true",
                "path": props.get(b"path", b"/api/v1").decode(),
            })

        def remove_service(self, zc, service_type, name):
            pass

        def update_service(self, zc, service_type, name):
            pass

    zc = Zeroconf()
    try:
        listener = Listener()
        browser = ServiceBrowser(zc, SERVICE_TYPE, listener)
        event.wait(timeout)
    finally:
        zc.close()

    return found


def get_service_info(
    host: str = "0.0.0.0",
    port: int = 8443,
    auth_enabled: bool = False,
    tls_enabled: bool = False,
) -> Dict[str, Any]:
    """Return service metadata for this PxeOS instance.

    This is used by the /api/v1/service-info endpoint and the
    CLI `pxeos service info` command.
    """
    scheme = "https" if tls_enabled else "http"
    display_host = host
    if display_host in ("0.0.0.0", "::"):
        try:
            display_host = socket.gethostname()
        except (socket.error, OSError):
            display_host = "localhost"

    return {
        "service": "pxeos",
        "version": __version__,
        "host": display_host,
        "port": port,
        "base_url": f"{scheme}://{display_host}:{port}",
        "api_base": f"{scheme}://{display_host}:{port}/api/v1",
        "auth_enabled": auth_enabled,
        "tls_enabled": tls_enabled,
        "endpoints": [
            "/api/v1/health",
            "/api/v1/boot/{mac}",
            "/api/v1/autoinstall/{mac}",
            "/api/v1/profiles",
            "/api/v1/distros",
            "/api/v1/hosts",
            "/api/v1/provision",
            "/api/v1/cloud-init/generate",
            "/api/v1/import/upload",
            "/api/v1/import/fetch",
            "/api/v1/service-info",
        ],
    }
