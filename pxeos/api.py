"""FastAPI REST API for PxeOS provisioning."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import Depends, FastAPI, File, Form, HTTPException, Response, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from pxeos.config import PxeOSConfig, load_hosts
from pxeos.engine import ProvisioningEngine
from pxeos.matcher import HostMatcher
from pxeos.models import BootFirmware, ProvisionProfile
from pxeos.registry import PluginRegistry
from pxeos.auth import ApiKeyStore, Role, get_key_store, init_auth, require_role
from pxeos.state import ProvisionState, ProvisionTracker

app = FastAPI(
    title="PxeOS",
    version="1.0",
    description="Cross-OS PXE boot provisioning API",
)

_engine: Optional[ProvisioningEngine] = None
_registry: Optional[PluginRegistry] = None
_config: Optional[PxeOSConfig] = None


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

    from pxeos.web.routes import router as web_router
    app.include_router(web_router)

    return app


@app.get("/api/v1/boot/{mac}")
def get_boot_script(mac: str) -> Response:
    if _engine is None:
        raise HTTPException(503, "engine not initialized")
    try:
        script = _engine.render_ipxe_script(mac)
        return Response(
            content=script, media_type="text/plain"
        )
    except ValueError as exc:
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
    return {
        "status": "ok",
        "plugins": plugins,
        "version": __version__,
    }


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
    if not entry:
        raise HTTPException(404, f"instance {instance_id!r} not found")
    return Response(content=entry["user_data"], media_type="text/yaml")


@app.get(
    "/api/v1/cloud-init/{instance_id}/meta-data",
    dependencies=[Depends(require_role(Role.OPERATOR))],
)
def get_cloud_init_meta_data(instance_id: str) -> Response:
    entry = _cloud_init_store.get(instance_id)
    if not entry:
        raise HTTPException(404, f"instance {instance_id!r} not found")
    return Response(content=entry["meta_data"], media_type="text/yaml")


@app.get(
    "/api/v1/cloud-init/{instance_id}/network-config",
    dependencies=[Depends(require_role(Role.OPERATOR))],
)
def get_cloud_init_network_config(instance_id: str) -> Response:
    entry = _cloud_init_store.get(instance_id)
    if not entry:
        raise HTTPException(404, f"instance {instance_id!r} not found")
    return Response(
        content=entry["network_config"], media_type="text/yaml"
    )


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
