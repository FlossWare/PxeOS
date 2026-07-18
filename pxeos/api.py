"""FastAPI REST API for PxeOS provisioning."""

from __future__ import annotations

import logging
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.middleware.base import (
    BaseHTTPMiddleware,
    RequestResponseEndpoint,
)

from pxeos.config import PxeOSConfig, load_hosts
from pxeos.engine import ProvisioningEngine
from pxeos.errors import (
    ConfigError,
    PxeOSError,
    PluginError,
    ProvisionError,
    ValidationError,
)
from pxeos.matcher import HostMatcher
from pxeos.models import BootFirmware, ProvisionProfile
from pxeos.registry import PluginRegistry
from pxeos.auth import ApiKeyStore, Role, get_key_store, init_auth, require_role
from pxeos.state import ProvisionState, ProvisionTracker
from pxeos.validation import normalize_mac, validate_mac, validate_os_family

logger = logging.getLogger("pxeos.api")

# Track app start time for health endpoint
_app_start_time: float = time.time()

app = FastAPI(
    title="PxeOS",
    version="1.0",
    description="Cross-OS PXE boot provisioning API",
)


class StructuredErrorResponse(BaseModel):
    """Structured error response returned by all error handlers."""

    detail: str
    suggestion: Optional[str] = None
    error_code: str = "PXEOS_ERROR"
    context: Dict[str, Any] = {}


@app.exception_handler(PxeOSError)
async def pxeos_error_handler(request: Any, exc: PxeOSError) -> Response:
    """Convert any PxeOSError into a structured JSON response."""
    from fastapi.responses import JSONResponse

    # Map exception types to HTTP status codes
    status_map: Dict[type, int] = {
        ValidationError: 422,
        ConfigError: 500,
        PluginError: 422,
        ProvisionError: 404,
    }
    status = status_map.get(type(exc), 400)

    body: Dict[str, Any] = {
        "detail": exc.message,
        "error_code": exc.error_code,
    }
    if exc.suggestion:
        body["suggestion"] = exc.suggestion
    if exc.context:
        body["context"] = exc.context

    return JSONResponse(status_code=status, content=body)


_engine: Optional[ProvisioningEngine] = None
_registry: Optional[PluginRegistry] = None
_config: Optional[PxeOSConfig] = None


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Log every request: method, path, status code, and duration."""

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        start = time.monotonic()
        response = await call_next(request)
        duration_ms = (time.monotonic() - start) * 1000

        client_ip = "unknown"
        if request.client is not None:
            client_ip = request.client.host

        logger.info(
            "%s %s %d %.1fms ip=%s",
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
            client_ip,
        )
        return response


# Register middleware at module level so it is in place before
# any TestClient or uvicorn starts the ASGI app.  Both are
# no-ops until init_app() calls configure_rate_limiting().
from pxeos.rate_limit import RateLimitMiddleware  # noqa: E402

app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(RateLimitMiddleware)


class HostRuleRequest(BaseModel):
    profile: str
    os_family: str
    os_version: str
    vendor: str = ""
    priority: int = 100
    mac: Optional[str] = None
    mac_prefix: Optional[str] = None
    hostname_pattern: Optional[str] = None
    subnet: Optional[str] = None
    serial: Optional[str] = None
    group: Optional[str] = None
    arch: Optional[str] = None


class HostRuleResponse(BaseModel):
    profile: str
    os_family: str
    os_version: str
    vendor: str = ""
    priority: int
    mac: Optional[str] = None
    mac_prefix: Optional[str] = None
    hostname_pattern: Optional[str] = None
    subnet: Optional[str] = None
    serial: Optional[str] = None
    group: Optional[str] = None
    arch: Optional[str] = None


class ProfileResponse(BaseModel):
    name: str
    os_family: str
    os_version: str
    vendor: str = ""
    arch: str
    firmware: str


class DistroResponse(BaseModel):
    name: str
    path: str


class HealthResponse(BaseModel):
    status: str
    plugins: List[str]
    version: str
    uptime_seconds: Optional[float] = None
    provision_count: Optional[int] = None
    data_dir_free_bytes: Optional[int] = None


class ProvisionStatusResponse(BaseModel):
    mac: str
    profile: str
    os_family: str
    os_version: str
    state: str
    started_at: Optional[float] = None
    updated_at: Optional[float] = None
    completed_at: Optional[float] = None
    error_message: Optional[str] = None
    history: List[Dict[str, Any]] = []
    netboot_enabled: bool = True


class ProvisionFailRequest(BaseModel):
    error: str


def init_app(
    registry: PluginRegistry,
    config: PxeOSConfig,
    matcher: HostMatcher,
) -> FastAPI:
    global _engine, _registry, _config
    _registry = registry
    _config = config
    _engine = ProvisioningEngine(registry, matcher, config)

    key_store = ApiKeyStore(config.data_dir)
    init_auth(config.auth_enabled, key_store)

    if config.auth_enabled and key_store.is_empty():
        import sys

        raw_key, _ = key_store.create_key(
            "bootstrap-admin", Role.ADMIN
        )
        print(
            f"\n*** BOOTSTRAP: Auth enabled but no keys "
            f"found. Created admin key: {raw_key}\n"
            f"*** Save this key and create proper keys "
            f"via the API or CLI.\n",
            file=sys.stderr,
        )

    # Configure rate limiting (middleware is already registered
    # at module level; this call sets limits and enables/disables).
    from pxeos.rate_limit import configure_rate_limiting

    rl = config.rate_limit
    configure_rate_limiting(
        enabled=rl.enabled,
        pxe_rpm=rl.pxe_requests_per_minute,
        pxe_burst=rl.pxe_burst,
        api_rpm=rl.api_requests_per_minute,
        api_burst=rl.api_burst,
        auth_rpm=rl.auth_requests_per_minute,
        auth_burst=rl.auth_burst,
    )

    from pxeos.web.routes import router as web_router
    app.include_router(web_router)

    if config.distro_root.exists():
        app.mount(
            "/distros",
            StaticFiles(directory=str(config.distro_root)),
            name="distros",
        )

    return app


def _validate_mac_param(mac: str) -> str:
    """Validate and normalize a MAC address path parameter.

    Raises ValidationError on invalid format.  Returns the
    normalized (lowercase, colon-separated) MAC string.
    """
    if not validate_mac(mac):
        raise ValidationError(
            f"invalid MAC address format: {mac!r}",
            suggestion=(
                "Expected format: xx:xx:xx:xx:xx:xx (colon-separated), "
                "xx-xx-xx-xx-xx-xx (dash-separated), or xxxxxxxxxxxx "
                "(bare hex). Example: aa:bb:cc:dd:ee:ff"
            ),
            context={"mac": mac},
        )
    return normalize_mac(mac)


@app.get("/api/v1/boot/{mac}")
def get_boot_script(mac: str) -> Response:
    if _engine is None:
        raise HTTPException(503, "engine not initialized")
    mac = _validate_mac_param(mac)
    logger.info("Boot script requested mac=%s", mac)
    try:
        script = _engine.render_ipxe_script(mac)
        return Response(
            content=script, media_type="text/plain"
        )
    except ValueError as exc:
        logger.warning("Boot script failed mac=%s: %s", mac, exc)
        raise HTTPException(404, str(exc))


# ---------------------------------------------------------------
# Boot-once / netboot control endpoints (issue #19)
# ---------------------------------------------------------------


class NetbootStatusResponse(BaseModel):
    mac: str
    netboot_enabled: bool


@app.post(
    "/api/v1/provision/{mac}/disable-netboot",
    dependencies=[Depends(require_role(Role.OPERATOR))],
)
def disable_netboot(mac: str) -> Dict[str, Any]:
    """Disable PXE netboot for a MAC (boot-once: after successful provisioning)."""
    if _engine is None:
        raise HTTPException(503, "engine not initialized")
    try:
        record = _engine.tracker.disable_netboot(mac)
        return {
            "mac": record.mac,
            "netboot_enabled": record.netboot_enabled,
            "status": "netboot disabled",
        }
    except ValueError as exc:
        raise HTTPException(404, str(exc))


@app.post(
    "/api/v1/provision/{mac}/enable-netboot",
    dependencies=[Depends(require_role(Role.OPERATOR))],
)
def enable_netboot(mac: str) -> Dict[str, Any]:
    """Re-enable PXE netboot for a MAC (for re-provisioning)."""
    if _engine is None:
        raise HTTPException(503, "engine not initialized")
    try:
        record = _engine.tracker.enable_netboot(mac)
        return {
            "mac": record.mac,
            "netboot_enabled": record.netboot_enabled,
            "status": "netboot enabled",
        }
    except ValueError as exc:
        raise HTTPException(404, str(exc))


@app.get(
    "/api/v1/provision/{mac}/netboot-status",
    response_model=NetbootStatusResponse,
    dependencies=[Depends(require_role(Role.VIEWER))],
)
def get_netboot_status(mac: str) -> Dict[str, Any]:
    """Return the current netboot status for a MAC."""
    if _engine is None:
        raise HTTPException(503, "engine not initialized")
    enabled = _engine.tracker.is_netboot_enabled(mac)
    return {"mac": mac, "netboot_enabled": enabled}


@app.get("/api/v1/autoinstall/{mac}")
def get_autoinstall(mac: str) -> Response:
    if _engine is None:
        raise HTTPException(503, "engine not initialized")
    try:
        content = _engine.get_autoinstall(mac)
        return Response(
            content=content, media_type="text/plain"
        )
    except ValueError as exc:
        raise HTTPException(404, str(exc))


@app.get(
    "/api/v1/profiles",
    response_model=List[ProfileResponse],
    dependencies=[Depends(require_role(Role.VIEWER))],
)
def list_profiles() -> List[Dict[str, Any]]:
    if _config is None:
        raise HTTPException(503, "config not initialized")

    profiles_dir = _config.data_dir / "profiles"
    if not profiles_dir.exists():
        return []

    results: List[Dict[str, Any]] = []
    for toml_file in sorted(profiles_dir.glob("*.toml")):
        from pxeos.config import load_profile

        try:
            p = load_profile(toml_file)
            results.append({
                "name": p.name,
                "os_family": p.os_family,
                "os_version": p.os_version,
                "vendor": p.vendor,
                "arch": p.arch,
                "firmware": p.firmware.value,
            })
        except Exception:
            pass
    return results


@app.get(
    "/api/v1/distros",
    response_model=List[DistroResponse],
    dependencies=[Depends(require_role(Role.VIEWER))],
)
def list_distros() -> List[Dict[str, str]]:
    if _config is None:
        raise HTTPException(503, "config not initialized")

    distro_root = _config.distro_root
    if not distro_root.exists():
        return []

    return [
        {"name": d.name, "path": str(d)}
        for d in sorted(distro_root.iterdir())
        if d.is_dir()
    ]


@app.post(
    "/api/v1/hosts",
    response_model=HostRuleResponse,
    status_code=201,
    dependencies=[Depends(require_role(Role.ADMIN))],
)
def register_host(rule: HostRuleRequest) -> Dict[str, Any]:
    if _config is None:
        raise HTTPException(503, "config not initialized")

    # Validate os_family against registered plugins
    if _registry is not None:
        valid, err = validate_os_family(
            rule.os_family, _registry.available
        )
        if not valid:
            raise PluginError(
                f"unknown os_family {rule.os_family!r}",
                suggestion=(
                    f"Available plugins: "
                    f"{', '.join(sorted(_registry.available))}"
                ),
                context={"os_family": rule.os_family},
            )

    # Validate MAC format if provided
    if rule.mac:
        if not validate_mac(rule.mac):
            raise ValidationError(
                f"invalid MAC address format: {rule.mac!r}",
                suggestion=(
                    "Expected format: xx:xx:xx:xx:xx:xx. "
                    "Example: aa:bb:cc:dd:ee:ff"
                ),
                context={"mac": rule.mac},
            )
        rule.mac = normalize_mac(rule.mac)

    hosts_file = _config.data_dir / "hosts.toml"

    import sys

    if sys.version_info >= (3, 11):
        import tomllib
    else:
        try:
            import tomllib
        except ModuleNotFoundError:
            import tomli as tomllib  # type: ignore[no-redef]

    existing: dict = {}
    if hosts_file.exists():
        with open(hosts_file, "rb") as fh:
            existing = tomllib.load(fh)

    hosts_list = existing.get("host", [])
    new_entry: Dict[str, Any] = {
        "profile": rule.profile,
        "os_family": rule.os_family,
        "os_version": rule.os_version,
        "vendor": rule.vendor,
        "priority": rule.priority,
    }
    for field_name in (
        "mac", "mac_prefix", "hostname_pattern",
        "subnet", "serial", "group", "arch",
    ):
        val = getattr(rule, field_name)
        if val is not None:
            new_entry[field_name] = val

    hosts_list.append(new_entry)

    _write_hosts_toml(hosts_file, hosts_list)

    return rule.model_dump()


def _write_hosts_toml(
    path: Path, hosts: List[Dict[str, Any]]
) -> None:
    lines: list[str] = []
    for entry in hosts:
        lines.append("[[host]]")
        for key, val in entry.items():
            if isinstance(val, str):
                lines.append(f'{key} = "{val}"')
            elif isinstance(val, int):
                lines.append(f"{key} = {val}")
        lines.append("")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines))


@app.get(
    "/api/v1/health",
    response_model=HealthResponse,
)
def health_check() -> Dict[str, Any]:
    from pxeos import __version__

    plugins = _registry.available if _registry else []
    uptime = time.time() - _app_start_time

    provision_count = 0
    if _engine is not None:
        provision_count = len(_engine.tracker.list_all())

    free_bytes = None
    if _config is not None and _config.data_dir.exists():
        try:
            usage = shutil.disk_usage(str(_config.data_dir))
            free_bytes = usage.free
        except OSError:
            pass

    return {
        "status": "ok",
        "plugins": plugins,
        "version": __version__,
        "uptime_seconds": round(uptime, 1),
        "provision_count": provision_count,
        "data_dir_free_bytes": free_bytes,
    }


@app.get("/api/v1/service-info")
def service_info() -> Dict[str, Any]:
    """Return service metadata for VirtOS integration and discovery."""
    from pxeos.discovery import get_service_info

    if _config is None:
        raise HTTPException(503, "config not initialized")

    return get_service_info(
        host=_config.server_host,
        port=_config.server_port,
        auth_enabled=_config.auth_enabled,
        tls_enabled=_config.tls_cert is not None,
    )


@app.get("/metrics")
def prometheus_metrics() -> Response:
    """Prometheus-compatible metrics endpoint."""
    from pxeos.metrics import render_metrics

    return Response(
        content=render_metrics(),
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )


# ---------------------------------------------------------------
# Provisioning state tracking endpoints
# ---------------------------------------------------------------


@app.get(
    "/api/v1/provision/{mac}/status",
    response_model=ProvisionStatusResponse,
    dependencies=[Depends(require_role(Role.VIEWER))],
)
def get_provision_status(mac: str) -> Dict[str, Any]:
    if _engine is None:
        raise HTTPException(503, "engine not initialized")
    mac = _validate_mac_param(mac)
    record = _engine.tracker.get(mac)
    if record is None:
        raise HTTPException(
            404, f"no provisioning record for {mac!r}"
        )
    return record.to_dict()


@app.post(
    "/api/v1/provision/{mac}/complete",
    response_model=ProvisionStatusResponse,
)
def mark_provision_complete(mac: str) -> Dict[str, Any]:
    if _engine is None:
        raise HTTPException(503, "engine not initialized")
    record = _engine.tracker.get(mac)
    if record is None:
        raise HTTPException(
            404, f"no provisioning record for {mac!r}"
        )
    _engine.tracker.transition(mac, ProvisionState.COMPLETE)
    return record.to_dict()


@app.post(
    "/api/v1/provision/{mac}/failed",
    response_model=ProvisionStatusResponse,
)
def mark_provision_failed(
    mac: str, body: ProvisionFailRequest
) -> Dict[str, Any]:
    if _engine is None:
        raise HTTPException(503, "engine not initialized")
    record = _engine.tracker.get(mac)
    if record is None:
        raise HTTPException(
            404, f"no provisioning record for {mac!r}"
        )
    _engine.tracker.transition(
        mac, ProvisionState.FAILED, error_message=body.error
    )
    return record.to_dict()


@app.get(
    "/api/v1/provision",
    response_model=List[ProvisionStatusResponse],
    dependencies=[Depends(require_role(Role.VIEWER))],
)
def list_provisions() -> List[Dict[str, Any]]:
    if _engine is None:
        raise HTTPException(503, "engine not initialized")
    return [r.to_dict() for r in _engine.tracker.list_all()]


# ---------------------------------------------------------------
# Cloud-init endpoints (absorbed from VirtOS virtos-cloud-init)
# ---------------------------------------------------------------


class CloudInitRequest(BaseModel):
    name: str
    os_family: str = ""
    os_version: str = ""
    vendor: str = ""
    hostname: str = ""
    user: str = "admin"
    password: Optional[str] = None
    ssh_authorized_keys: List[str] = []
    packages: List[str] = []
    post_scripts: List[str] = []
    network_method: str = "dhcp"
    network_device: str = "eth0"
    address: Optional[str] = None
    gateway: Optional[str] = None
    nameservers: List[str] = []
    timezone: str = "UTC"
    locale: str = "en_US.UTF-8"
    write_files: List[Dict[str, Any]] = []
    extra: Dict[str, Any] = {}


class CloudInitResponse(BaseModel):
    user_data: str
    meta_data: str
    network_config: str


def _profile_from_cloud_init_request(
    req: CloudInitRequest,
) -> ProvisionProfile:
    network: Dict[str, Any] = {
        "method": req.network_method,
        "hostname": req.hostname or req.name,
        "device": req.network_device,
    }
    if req.address:
        network["address"] = req.address
    if req.gateway:
        network["gateway"] = req.gateway
    if req.nameservers:
        network["nameservers"] = req.nameservers

    extra: Dict[str, Any] = {
        "user": req.user,
        "timezone": req.timezone,
        "locale": req.locale,
        **req.extra,
    }
    if req.password:
        extra["password"] = req.password
    if req.ssh_authorized_keys:
        extra["ssh_authorized_keys"] = req.ssh_authorized_keys
    if req.write_files:
        extra["write_files"] = req.write_files

    return ProvisionProfile(
        name=req.name,
        os_family=req.os_family,
        os_version=req.os_version,
        vendor=req.vendor,
        network=network,
        packages=req.packages,
        post_scripts=req.post_scripts,
        extra=extra,
    )


@app.post(
    "/api/v1/cloud-init/generate",
    response_model=CloudInitResponse,
    dependencies=[Depends(require_role(Role.OPERATOR))],
)
def generate_cloud_init(
    req: CloudInitRequest,
) -> Dict[str, str]:
    from pxeos.cloud_init import generate

    profile = _profile_from_cloud_init_request(req)
    config = generate(profile)
    return {
        "user_data": config.user_data,
        "meta_data": config.meta_data,
        "network_config": config.network_config,
    }


@app.post(
    "/api/v1/cloud-init/iso",
    dependencies=[Depends(require_role(Role.OPERATOR))],
)
def generate_cloud_init_iso(req: CloudInitRequest) -> Response:
    from pxeos.cloud_init import create_config_drive

    profile = _profile_from_cloud_init_request(req)

    with tempfile.NamedTemporaryFile(
        suffix=".iso", delete=False
    ) as tmp:
        output_path = Path(tmp.name)

    try:
        create_config_drive(profile, output_path)
        return FileResponse(
            path=str(output_path),
            media_type="application/octet-stream",
            filename=f"{req.name}-cloud-init.iso",
        )
    except RuntimeError as exc:
        raise HTTPException(500, str(exc))


_cloud_init_store: Dict[str, Dict[str, str]] = {}


@app.post(
    "/api/v1/cloud-init/register",
    dependencies=[Depends(require_role(Role.OPERATOR))],
)
def register_cloud_init(
    req: CloudInitRequest,
) -> Dict[str, str]:
    from pxeos.cloud_init import generate

    profile = _profile_from_cloud_init_request(req)
    config = generate(profile)
    instance_id = profile.extra.get(
        "instance_id",
        f"{req.hostname or req.name}-{req.os_version}",
    )
    _cloud_init_store[instance_id] = {
        "user_data": config.user_data,
        "meta_data": config.meta_data,
        "network_config": config.network_config,
    }
    return {"instance_id": instance_id, "status": "registered"}


@app.get(
    "/api/v1/cloud-init/{instance_id}/user-data",
    dependencies=[Depends(require_role(Role.OPERATOR))],
)
def get_cloud_init_user_data(instance_id: str) -> Response:
    entry = _cloud_init_store.get(instance_id)
    if entry:
        return Response(content=entry["user_data"], media_type="text/yaml")
    # Fall back to MAC-based resolution
    if _engine is not None and validate_mac(instance_id):
        mac = normalize_mac(instance_id)
        try:
            rule = _engine._resolve_rule(mac)
            profile = _engine._load_profile_for_rule(rule)
            from pxeos.cloud_init import generate_user_data
            content = generate_user_data(profile)
            return Response(content=content, media_type="text/yaml")
        except ValueError:
            pass
    raise HTTPException(404, f"instance {instance_id!r} not found")


@app.get(
    "/api/v1/cloud-init/{instance_id}/meta-data",
    dependencies=[Depends(require_role(Role.OPERATOR))],
)
def get_cloud_init_meta_data(instance_id: str) -> Response:
    entry = _cloud_init_store.get(instance_id)
    if entry:
        return Response(content=entry["meta_data"], media_type="text/yaml")
    # Fall back to MAC-based resolution
    if _engine is not None and validate_mac(instance_id):
        mac = normalize_mac(instance_id)
        try:
            rule = _engine._resolve_rule(mac)
            profile = _engine._load_profile_for_rule(rule)
            hostname = profile.network.get("hostname", profile.name)
            from pxeos.cloud_init import generate_meta_data
            content = generate_meta_data(hostname)
            return Response(content=content, media_type="text/yaml")
        except ValueError:
            pass
    raise HTTPException(404, f"instance {instance_id!r} not found")


@app.get(
    "/api/v1/cloud-init/{instance_id}/network-config",
    dependencies=[Depends(require_role(Role.OPERATOR))],
)
def get_cloud_init_network_config(instance_id: str) -> Response:
    entry = _cloud_init_store.get(instance_id)
    if entry:
        return Response(content=entry["network_config"], media_type="text/yaml")
    # Fall back to MAC-based resolution
    if _engine is not None and validate_mac(instance_id):
        mac = normalize_mac(instance_id)
        try:
            rule = _engine._resolve_rule(mac)
            profile = _engine._load_profile_for_rule(rule)
            from pxeos.cloud_init import generate_network_config
            content = generate_network_config(profile)
            return Response(content=content, media_type="text/yaml")
        except ValueError:
            pass
    raise HTTPException(404, f"instance {instance_id!r} not found")


# ---------------------------------------------------------------
# Remote ISO import endpoints
# ---------------------------------------------------------------


class ImportFetchRequest(BaseModel):
    url: str
    os_family: str = ""
    vendor: str = ""
    os_version: str = ""
    arch: str = "x86_64"
    mnemonic: Optional[str] = None
    live: bool = False


class ImportResponse(BaseModel):
    kernel_path: str
    initrd_path: Optional[str] = None
    repo_path: str
    squashfs_path: Optional[str] = None


@app.post(
    "/api/v1/import/upload",
    response_model=ImportResponse,
    dependencies=[Depends(require_role(Role.OPERATOR))],
)
async def import_upload(
    file: UploadFile = File(...),
    os_family: str = Form(""),
    os_version: str = Form(""),
    vendor: str = Form(""),
    arch: str = Form("x86_64"),
    mnemonic: str = Form(""),
    live: bool = Form(False),
) -> Dict[str, Any]:
    if _config is None or _registry is None:
        raise HTTPException(503, "not initialized")

    if mnemonic:
        from pxeos.mnemonics import resolve_mnemonic

        alias = resolve_mnemonic(mnemonic)
        if alias is None:
            raise HTTPException(
                400, f"unknown mnemonic {mnemonic!r}"
            )
        if not os_family:
            os_family = alias.os_family
        if not vendor:
            vendor = alias.vendor
        if not os_version:
            os_version = alias.version

    if not os_family or not os_version:
        raise HTTPException(
            400, "mnemonic or os_family+os_version required"
        )

    from pxeos.importer import import_iso

    with tempfile.NamedTemporaryFile(
        suffix=".iso", delete=False
    ) as tmp:
        iso_path = Path(tmp.name)
        content = await file.read()
        tmp.write(content)

    try:
        assets = import_iso(
            iso_path, os_family, vendor, os_version, arch,
            _registry, _config.distro_root, live=live,
        )
        return {
            "kernel_path": str(assets.kernel_path),
            "initrd_path": (
                str(assets.initrd_path) if assets.initrd_path else None
            ),
            "repo_path": str(assets.repo_path),
            "squashfs_path": (
                str(assets.squashfs_path) if assets.squashfs_path else None
            ),
        }
    finally:
        iso_path.unlink(missing_ok=True)


@app.post(
    "/api/v1/import/fetch",
    response_model=ImportResponse,
    dependencies=[Depends(require_role(Role.OPERATOR))],
)
def import_fetch(req: ImportFetchRequest) -> Dict[str, Any]:
    if _config is None or _registry is None:
        raise HTTPException(503, "not initialized")

    os_family = req.os_family
    vendor = req.vendor
    os_version = req.os_version

    if req.mnemonic:
        from pxeos.mnemonics import resolve_mnemonic

        alias = resolve_mnemonic(req.mnemonic)
        if alias is None:
            raise HTTPException(
                400, f"unknown mnemonic {req.mnemonic!r}"
            )
        if not os_family:
            os_family = alias.os_family
        if not vendor:
            vendor = alias.vendor
        if not os_version:
            os_version = alias.version

    if not os_family or not os_version:
        raise HTTPException(
            400, "mnemonic or os_family+os_version required"
        )

    from pxeos.importer import import_url

    assets = import_url(
        req.url, os_family, vendor,
        os_version, req.arch,
        _registry, _config.distro_root,
    )
    return {
        "kernel_path": str(assets.kernel_path),
        "initrd_path": (
            str(assets.initrd_path) if assets.initrd_path else None
        ),
        "repo_path": str(assets.repo_path),
        "squashfs_path": (
            str(assets.squashfs_path) if assets.squashfs_path else None
        ),
    }


# ---------------------------------------------------------------
# Secrets management endpoints
# ---------------------------------------------------------------


class SecretSetRequest(BaseModel):
    key: str
    value: str


class SecretKeyResponse(BaseModel):
    keys: List[str]


class SecretValueResponse(BaseModel):
    key: str
    value: str


def _get_secrets_provider():
    """Return a FileSecretsProvider using the configured data_dir."""
    from pxeos.secrets import FileSecretsProvider

    if _config is None:
        raise HTTPException(503, "config not initialized")
    return FileSecretsProvider(_config.data_dir)


@app.post(
    "/api/v1/secrets",
    status_code=201,
    dependencies=[Depends(require_role(Role.ADMIN))],
)
def set_secret(req: SecretSetRequest) -> Dict[str, str]:
    provider = _get_secrets_provider()
    provider.set(req.key, req.value)
    return {"key": req.key, "status": "stored"}


@app.get(
    "/api/v1/secrets/{key}",
    response_model=SecretValueResponse,
    dependencies=[Depends(require_role(Role.ADMIN))],
)
def get_secret(key: str) -> Dict[str, str]:
    provider = _get_secrets_provider()
    value = provider.get(key)
    if value is None:
        raise HTTPException(404, f"secret {key!r} not found")
    return {"key": key, "value": value}


@app.delete(
    "/api/v1/secrets/{key}",
    dependencies=[Depends(require_role(Role.ADMIN))],
)
def delete_secret(key: str) -> Dict[str, str]:
    provider = _get_secrets_provider()
    provider.delete(key)
    return {"key": key, "status": "deleted"}


@app.get(
    "/api/v1/secrets",
    response_model=SecretKeyResponse,
    dependencies=[Depends(require_role(Role.VIEWER))],
)
def list_secrets() -> Dict[str, List[str]]:
    provider = _get_secrets_provider()
    return {"keys": provider.list_keys()}


# ---------------------------------------------------------------
# Named objects (cobbler-style distros & hosts)
# ---------------------------------------------------------------


class NamedDistroRequest(BaseModel):
    name: str
    os_family: str
    vendor: str
    version: str
    arch: str = "x86_64"
    kernel_path: str = ""
    initrd_path: str = ""
    install_url: str = ""
    comment: str = ""


class NamedDistroResponse(BaseModel):
    name: str
    os_family: str
    vendor: str
    version: str
    arch: str = "x86_64"
    kernel_path: str = ""
    initrd_path: str = ""
    install_url: str = ""
    comment: str = ""


class NamedHostRequest(BaseModel):
    name: str
    mac: str
    profile: str = ""
    distro: str = ""
    hostname: str = ""
    gateway: str = ""
    nameservers: List[str] = []
    ip_address: str = ""
    netmask: str = ""
    comment: str = ""
    extra: Dict[str, Any] = {}


class NamedHostResponse(BaseModel):
    name: str
    mac: str
    profile: str = ""
    distro: str = ""
    hostname: str = ""
    gateway: str = ""
    nameservers: List[str] = []
    ip_address: str = ""
    netmask: str = ""
    comment: str = ""
    extra: Dict[str, Any] = {}


def _get_named_store():
    """Return a NamedObjectStore using the configured data_dir."""
    from pxeos.named_objects import NamedObjectStore

    if _config is None:
        raise HTTPException(503, "config not initialized")
    return NamedObjectStore(_config.data_dir / "named")


# -- Named distro endpoints --


@app.get(
    "/api/v1/named/distros",
    response_model=List[NamedDistroResponse],
    dependencies=[Depends(require_role(Role.VIEWER))],
)
def list_named_distros() -> List[Dict[str, Any]]:
    from dataclasses import asdict

    store = _get_named_store()
    return [asdict(d) for d in store.list_distros()]


@app.post(
    "/api/v1/named/distros",
    response_model=NamedDistroResponse,
    status_code=201,
    dependencies=[Depends(require_role(Role.ADMIN))],
)
def create_named_distro(
    req: NamedDistroRequest,
) -> Dict[str, Any]:
    from dataclasses import asdict

    from pxeos.named_objects import NamedDistro

    store = _get_named_store()
    if store.get_distro(req.name) is not None:
        raise HTTPException(
            409, f"distro {req.name!r} already exists"
        )
    distro = NamedDistro(**req.model_dump())
    try:
        store.add_distro(distro)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return asdict(distro)


@app.get(
    "/api/v1/named/distros/{name}",
    response_model=NamedDistroResponse,
    dependencies=[Depends(require_role(Role.VIEWER))],
)
def get_named_distro(name: str) -> Dict[str, Any]:
    from dataclasses import asdict

    store = _get_named_store()
    try:
        distro = store.get_distro(name)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    if distro is None:
        raise HTTPException(404, f"distro {name!r} not found")
    return asdict(distro)


@app.put(
    "/api/v1/named/distros/{name}",
    response_model=NamedDistroResponse,
    dependencies=[Depends(require_role(Role.ADMIN))],
)
def update_named_distro(
    name: str, updates: Dict[str, Any]
) -> Dict[str, Any]:
    from dataclasses import asdict

    store = _get_named_store()
    try:
        distro = store.update_distro(name, updates)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    if distro is None:
        raise HTTPException(404, f"distro {name!r} not found")
    return asdict(distro)


@app.delete(
    "/api/v1/named/distros/{name}",
    dependencies=[Depends(require_role(Role.ADMIN))],
)
def delete_named_distro(name: str) -> Dict[str, str]:
    store = _get_named_store()
    try:
        deleted = store.delete_distro(name)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    if not deleted:
        raise HTTPException(404, f"distro {name!r} not found")
    return {"name": name, "status": "deleted"}


# -- Named host endpoints --


@app.get(
    "/api/v1/named/hosts",
    response_model=List[NamedHostResponse],
    dependencies=[Depends(require_role(Role.VIEWER))],
)
def list_named_hosts() -> List[Dict[str, Any]]:
    from dataclasses import asdict

    store = _get_named_store()
    return [asdict(h) for h in store.list_hosts()]


@app.post(
    "/api/v1/named/hosts",
    response_model=NamedHostResponse,
    status_code=201,
    dependencies=[Depends(require_role(Role.ADMIN))],
)
def create_named_host(
    req: NamedHostRequest,
) -> Dict[str, Any]:
    from dataclasses import asdict

    from pxeos.named_objects import NamedHost

    store = _get_named_store()
    if store.get_host(req.name) is not None:
        raise HTTPException(
            409, f"host {req.name!r} already exists"
        )
    host = NamedHost(**req.model_dump())
    try:
        store.add_host(host)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return asdict(host)


@app.get(
    "/api/v1/named/hosts/{name}",
    response_model=NamedHostResponse,
    dependencies=[Depends(require_role(Role.VIEWER))],
)
def get_named_host(name: str) -> Dict[str, Any]:
    from dataclasses import asdict

    store = _get_named_store()
    try:
        host = store.get_host(name)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    if host is None:
        raise HTTPException(404, f"host {name!r} not found")
    return asdict(host)


@app.put(
    "/api/v1/named/hosts/{name}",
    response_model=NamedHostResponse,
    dependencies=[Depends(require_role(Role.ADMIN))],
)
def update_named_host(
    name: str, updates: Dict[str, Any]
) -> Dict[str, Any]:
    from dataclasses import asdict

    store = _get_named_store()
    try:
        host = store.update_host(name, updates)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    if host is None:
        raise HTTPException(404, f"host {name!r} not found")
    return asdict(host)


@app.delete(
    "/api/v1/named/hosts/{name}",
    dependencies=[Depends(require_role(Role.ADMIN))],
)
def delete_named_host(name: str) -> Dict[str, str]:
    store = _get_named_store()
    try:
        deleted = store.delete_host(name)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    if not deleted:
        raise HTTPException(404, f"host {name!r} not found")
    return {"name": name, "status": "deleted"}


# ---------------------------------------------------------------
# API key management endpoints (admin only)
# ---------------------------------------------------------------


# ---------------------------------------------------------------
# Power management endpoints (issue #29)
# ---------------------------------------------------------------


class PowerActionResponse(BaseModel):
    mac: str
    action: str
    result: str


class PowerStatusResponse(BaseModel):
    mac: str
    status: str


_power_manager: Optional[Any] = None


def _get_power_manager():
    """Lazily build a PowerManager from host rules."""
    global _power_manager
    if _power_manager is not None:
        return _power_manager

    from pxeos.power import PowerManager

    if _config is None:
        raise HTTPException(503, "config not initialized")

    manager = PowerManager()
    hosts_path = _config.data_dir / "hosts.toml"
    if hosts_path.exists():
        rules = load_hosts(hosts_path)
        for rule in rules:
            if rule.mac and rule.bmc_host and rule.bmc_driver:
                driver = PowerManager.create_driver(
                    rule.bmc_driver,
                    rule.bmc_host,
                    rule.bmc_user or "",
                    rule.bmc_password or "",
                )
                manager.register(rule.mac, driver)

    _power_manager = manager
    return manager


@app.post(
    "/api/v1/power/{mac}/on",
    response_model=PowerActionResponse,
    dependencies=[Depends(require_role(Role.OPERATOR))],
)
def power_on(mac: str) -> Dict[str, Any]:
    """Power on a host via its BMC."""
    from pxeos.power import PowerError

    manager = _get_power_manager()
    try:
        result = manager.power_on(mac)
        return {"mac": mac, "action": "power_on", "result": result}
    except PowerError as exc:
        raise HTTPException(400, str(exc))


@app.post(
    "/api/v1/power/{mac}/off",
    response_model=PowerActionResponse,
    dependencies=[Depends(require_role(Role.OPERATOR))],
)
def power_off(mac: str) -> Dict[str, Any]:
    """Power off a host via its BMC."""
    from pxeos.power import PowerError

    manager = _get_power_manager()
    try:
        result = manager.power_off(mac)
        return {"mac": mac, "action": "power_off", "result": result}
    except PowerError as exc:
        raise HTTPException(400, str(exc))


@app.get(
    "/api/v1/power/{mac}/status",
    response_model=PowerStatusResponse,
    dependencies=[Depends(require_role(Role.VIEWER))],
)
def get_power_status(mac: str) -> Dict[str, Any]:
    """Get the power status of a host via its BMC."""
    from pxeos.power import PowerError

    manager = _get_power_manager()
    try:
        status = manager.power_status(mac)
        return {"mac": mac, "status": status}
    except PowerError as exc:
        raise HTTPException(400, str(exc))


# ---------------------------------------------------------------
# Cache management endpoints (issue #31)
# ---------------------------------------------------------------


@app.get(
    "/api/v1/cache/stats",
    dependencies=[Depends(require_role(Role.VIEWER))],
)
def cache_stats() -> Dict[str, Any]:
    """Return hit/miss statistics for all TTL caches."""
    from pxeos.cache import get_all_cache_stats
    return get_all_cache_stats()


@app.post(
    "/api/v1/cache/clear",
    dependencies=[Depends(require_role(Role.ADMIN))],
)
def cache_clear() -> Dict[str, Any]:
    """Flush all caches."""
    from pxeos.cache import clear_all_caches
    count = clear_all_caches()
    return {"cleared": count, "status": "ok"}


# ---------------------------------------------------------------
# API key management endpoints (admin only)
# ---------------------------------------------------------------


class ApiKeyCreateRequest(BaseModel):
    name: str
    role: str = "viewer"


class ApiKeyCreateResponse(BaseModel):
    name: str
    role: str
    raw_key: str


class ApiKeyListItem(BaseModel):
    name: str
    role: str
    enabled: bool
    created_at: float
    last_used_at: Optional[float] = None


# ---------------------------------------------------------------
# Cloud image management endpoints (issue #7)
# ---------------------------------------------------------------


class CloudImageResponse(BaseModel):
    name: str
    os_family: str
    vendor: str
    version: str
    arch: str = "x86_64"
    format: str = "qcow2"
    path: str = ""
    size_bytes: int = 0
    cloud_init: bool = True


class CloudImageImportRequest(BaseModel):
    url: str
    os_family: str
    vendor: str
    version: str
    arch: str = "x86_64"
    format: str = "qcow2"


@app.get(
    "/api/v1/images",
    response_model=List[CloudImageResponse],
    dependencies=[Depends(require_role(Role.VIEWER))],
)
def list_cloud_images() -> List[Dict[str, Any]]:
    """List all imported cloud images."""
    if _config is None:
        raise HTTPException(503, "config not initialized")
    from pxeos.cloud_image import list_images

    images = list_images(data_dir=_config.data_dir)
    return [
        {
            "name": img.name,
            "os_family": img.os_family,
            "vendor": img.vendor,
            "version": img.version,
            "arch": img.arch,
            "format": img.format,
            "path": str(img.path),
            "size_bytes": img.size_bytes,
            "cloud_init": img.cloud_init,
        }
        for img in images
    ]


@app.post(
    "/api/v1/images/import",
    response_model=CloudImageResponse,
    status_code=201,
    dependencies=[Depends(require_role(Role.OPERATOR))],
)
def import_cloud_image(req: CloudImageImportRequest) -> Dict[str, Any]:
    """Import a cloud image from a URL."""
    if _config is None:
        raise HTTPException(503, "config not initialized")
    from pxeos.cloud_image import import_cloud_image as do_import

    try:
        image = do_import(
            source=req.url,
            os_family=req.os_family,
            vendor=req.vendor,
            version=req.version,
            arch=req.arch,
            fmt=req.format,
            data_dir=_config.data_dir,
        )
        return {
            "name": image.name,
            "os_family": image.os_family,
            "vendor": image.vendor,
            "version": image.version,
            "arch": image.arch,
            "format": image.format,
            "path": str(image.path),
            "size_bytes": image.size_bytes,
            "cloud_init": image.cloud_init,
        }
    except (ValueError, FileNotFoundError, OSError) as exc:
        raise HTTPException(400, str(exc))


@app.delete(
    "/api/v1/images/{name}",
    dependencies=[Depends(require_role(Role.ADMIN))],
)
def delete_cloud_image(name: str) -> Dict[str, str]:
    """Delete a cloud image by name."""
    if _config is None:
        raise HTTPException(503, "config not initialized")
    from pxeos.cloud_image import delete_image

    if not delete_image(name, data_dir=_config.data_dir):
        raise HTTPException(404, f"image {name!r} not found")
    return {"name": name, "status": "deleted"}


@app.post(
    "/api/v1/auth/keys",
    response_model=ApiKeyCreateResponse,
    status_code=201,
    dependencies=[Depends(require_role(Role.ADMIN))],
)
def create_api_key(
    req: ApiKeyCreateRequest,
) -> Dict[str, Any]:
    store = get_key_store()
    if store is None:
        raise HTTPException(503, "auth not initialized")
    try:
        role = Role(req.role)
    except ValueError:
        raise HTTPException(
            400, f"invalid role: {req.role!r}"
        )
    raw_key, api_key = store.create_key(req.name, role)
    return {
        "name": api_key.name,
        "role": api_key.role.value,
        "raw_key": raw_key,
    }


@app.get(
    "/api/v1/auth/keys",
    response_model=List[ApiKeyListItem],
    dependencies=[Depends(require_role(Role.ADMIN))],
)
def list_api_keys() -> List[Dict[str, Any]]:
    store = get_key_store()
    if store is None:
        raise HTTPException(503, "auth not initialized")
    return [
        {
            "name": k.name,
            "role": k.role.value,
            "enabled": k.enabled,
            "created_at": k.created_at,
            "last_used_at": k.last_used_at,
        }
        for k in store.list_keys()
    ]


@app.delete(
    "/api/v1/auth/keys/{name}",
    dependencies=[Depends(require_role(Role.ADMIN))],
)
def delete_api_key(name: str) -> Dict[str, str]:
    store = get_key_store()
    if store is None:
        raise HTTPException(503, "auth not initialized")
    if not store.delete(name):
        raise HTTPException(
            404, f"API key {name!r} not found"
        )
    return {"name": name, "status": "deleted"}


# ---------------------------------------------------------------
# Repository mirror endpoints (issue #42)
# ---------------------------------------------------------------


class MirrorRequest(BaseModel):
    name: str
    source_url: str
    local_path: str = ""
    sync_interval: int = 86400


class MirrorResponse(BaseModel):
    name: str
    source_url: str
    local_path: str
    sync_interval: int = 86400
    last_sync: Optional[float] = None


class MirrorSyncResponse(BaseModel):
    mirror_name: str
    success: bool
    started_at: float
    finished_at: float
    error: str = ""


def _get_repo_manager():
    """Return a RepoManager using the configured data_dir."""
    from pxeos.repo_mirror import RepoManager

    if _config is None:
        raise HTTPException(503, "config not initialized")
    return RepoManager(_config.data_dir)


@app.get(
    "/api/v1/mirrors",
    response_model=List[MirrorResponse],
    dependencies=[Depends(require_role(Role.VIEWER))],
)
def list_mirrors() -> List[Dict[str, Any]]:
    """List all configured repository mirrors."""
    from dataclasses import asdict

    manager = _get_repo_manager()
    return [asdict(m) for m in manager.list_mirrors()]


@app.post(
    "/api/v1/mirrors",
    response_model=MirrorResponse,
    status_code=201,
    dependencies=[Depends(require_role(Role.ADMIN))],
)
def add_mirror(req: MirrorRequest) -> Dict[str, Any]:
    """Add a new repository mirror."""
    from dataclasses import asdict

    from pxeos.repo_mirror import RepoMirror

    manager = _get_repo_manager()
    mirror = RepoMirror(
        name=req.name,
        source_url=req.source_url,
        local_path=req.local_path,
        sync_interval=req.sync_interval,
    )
    try:
        result = manager.add_mirror(mirror)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return asdict(result)


@app.post(
    "/api/v1/mirrors/{name}/sync",
    response_model=MirrorSyncResponse,
    dependencies=[Depends(require_role(Role.OPERATOR))],
)
def sync_mirror(name: str) -> Dict[str, Any]:
    """Trigger a sync for a mirror."""
    from dataclasses import asdict

    manager = _get_repo_manager()
    try:
        result = manager.sync_mirror(name)
    except ValueError as exc:
        raise HTTPException(404, str(exc))
    return asdict(result)


@app.delete(
    "/api/v1/mirrors/{name}",
    dependencies=[Depends(require_role(Role.ADMIN))],
)
def delete_mirror(name: str) -> Dict[str, str]:
    """Remove a repository mirror."""
    manager = _get_repo_manager()
    try:
        if not manager.remove_mirror(name):
            raise HTTPException(
                404, f"mirror {name!r} not found"
            )
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {"name": name, "status": "deleted"}
