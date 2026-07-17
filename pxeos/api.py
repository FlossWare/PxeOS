"""FastAPI REST API for PxeOS provisioning."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Response
from pydantic import BaseModel

from pxeos.config import PxeOSConfig, load_hosts
from pxeos.engine import ProvisioningEngine
from pxeos.matcher import HostMatcher
from pxeos.registry import PluginRegistry

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


def init_app(
    registry: PluginRegistry,
    config: PxeOSConfig,
    matcher: HostMatcher,
) -> FastAPI:
    global _engine, _registry, _config
    _registry = registry
    _config = config
    _engine = ProvisioningEngine(registry, matcher, config)
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
