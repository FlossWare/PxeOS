"""Web UI routes for PxeOS (server-rendered HTML + htmx)."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Form, File, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse

from jinja2 import Environment, PackageLoader

router = APIRouter(prefix="/web", tags=["web"])

_templates = Environment(
    loader=PackageLoader("pxeos.web", "templates"),
    autoescape=True,
)


def _render(
    template_name: str,
    page: str = "",
    **kwargs: Any,
) -> HTMLResponse:
    tmpl = _templates.get_template(template_name)
    html = tmpl.render(page=page, **kwargs)
    return HTMLResponse(html)


def _get_registry():
    from pxeos.api import _registry
    return _registry


def _get_config():
    from pxeos.api import _config
    return _config


def _get_engine():
    from pxeos.api import _engine
    return _engine


def _plugin_names() -> List[str]:
    reg = _get_registry()
    return reg.available if reg else []


def _list_distros() -> List[Dict[str, str]]:
    config = _get_config()
    if not config or not config.distro_root.exists():
        return []
    return [
        {"name": d.name, "path": str(d)}
        for d in sorted(config.distro_root.iterdir())
        if d.is_dir()
    ]


def _list_profiles() -> List[Dict[str, Any]]:
    config = _get_config()
    if not config:
        return []
    profiles_dir = config.data_dir / "profiles"
    if not profiles_dir.exists():
        return []

    from pxeos.config import load_profile

    results: List[Dict[str, Any]] = []
    for toml_file in sorted(profiles_dir.glob("*.toml")):
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


def _list_hosts() -> List[Dict[str, Any]]:
    config = _get_config()
    if not config:
        return []
    hosts_file = config.data_dir / "hosts.toml"
    if not hosts_file.exists():
        return []

    from pxeos.config import load_hosts

    rules = load_hosts(hosts_file)
    return [
        {
            "profile": r.profile,
            "os_family": r.os_family,
            "os_version": r.os_version,
            "vendor": r.vendor,
            "priority": r.priority,
            "mac": r.mac,
            "mac_prefix": r.mac_prefix,
            "hostname_pattern": r.hostname_pattern,
            "subnet": r.subnet,
            "serial": r.serial,
            "group": r.group,
            "arch": r.arch,
        }
        for r in rules
    ]


# ------- Dashboard -------


@router.get("/", response_class=HTMLResponse)
def dashboard():
    from pxeos import __version__

    config = _get_config()
    return _render(
        "dashboard.html",
        page="dashboard",
        distro_count=len(_list_distros()),
        profile_count=len(_list_profiles()),
        host_count=len(_list_hosts()),
        plugin_count=len(_plugin_names()),
        plugins=_plugin_names(),
        version=__version__,
        server_host=config.server_host if config else "N/A",
        server_port=config.server_port if config else "N/A",
        tls=bool(config and config.tls_cert),
    )


# ------- Distros -------


@router.get("/distros", response_class=HTMLResponse)
def distros_page():
    return _render(
        "distros.html",
        page="distros",
        distros=_list_distros(),
    )


@router.delete("/distros/{name}", response_class=HTMLResponse)
def delete_distro(name: str):
    import shutil

    if ".." in name or "/" in name:
        return HTMLResponse("invalid name", status_code=400)
    config = _get_config()
    if config:
        distro_path = config.distro_root / name
        if distro_path.resolve().parent == config.distro_root.resolve():
            if distro_path.exists() and distro_path.is_dir():
                shutil.rmtree(distro_path)
    return HTMLResponse("")


# ------- Profiles -------


@router.get("/profiles", response_class=HTMLResponse)
def profiles_page():
    return _render(
        "profiles.html",
        page="profiles",
        profiles=_list_profiles(),
        plugins=_plugin_names(),
    )


@router.post("/profiles", response_class=HTMLResponse)
def create_profile(
    name: str = Form(...),
    os_family: str = Form(...),
    os_version: str = Form(...),
    vendor: str = Form(""),
    arch: str = Form("x86_64"),
    firmware: str = Form("bios"),
    install_url: str = Form(""),
    packages: str = Form(""),
    post_scripts: str = Form(""),
):
    config = _get_config()
    if not config:
        return _render(
            "profiles.html",
            page="profiles",
            profiles=[],
            plugins=_plugin_names(),
            flash={"type": "error", "message": "Server not initialized"},
        )

    profiles_dir = config.data_dir / "profiles"
    profiles_dir.mkdir(parents=True, exist_ok=True)
    profile_path = profiles_dir / f"{name}.toml"

    pkg_list = [p.strip() for p in packages.split(",") if p.strip()]
    script_list = [s for s in post_scripts.splitlines() if s.strip()]

    lines = [
        "[profile]",
        f'name = "{name}"',
        f'os_family = "{os_family}"',
        f'os_version = "{os_version}"',
    ]
    if vendor:
        lines.append(f'vendor = "{vendor}"')
    lines.append(f'arch = "{arch}"')
    lines.append(f'firmware = "{firmware}"')
    if install_url:
        lines.append(f'install_url = "{install_url}"')
    if pkg_list:
        pkgs_str = ", ".join(f'"{p}"' for p in pkg_list)
        lines.append(f"packages = [{pkgs_str}]")
    if script_list:
        scripts_str = ", ".join(f'"{s}"' for s in script_list)
        lines.append(f"post_scripts = [{scripts_str}]")
    lines.append("")

    profile_path.write_text("\n".join(lines))

    return _render(
        "profiles.html",
        page="profiles",
        profiles=_list_profiles(),
        plugins=_plugin_names(),
        flash={"type": "success", "message": f"Profile '{name}' created"},
    )


@router.delete("/profiles/{name}", response_class=HTMLResponse)
def delete_profile(name: str):
    if ".." in name or "/" in name:
        return HTMLResponse("invalid name", status_code=400)
    config = _get_config()
    if config:
        profile_path = config.data_dir / "profiles" / f"{name}.toml"
        profiles_dir = (config.data_dir / "profiles").resolve()
        if profile_path.resolve().parent == profiles_dir:
            profile_path.unlink(missing_ok=True)
    return HTMLResponse("")


# ------- Host Rules -------


@router.get("/hosts", response_class=HTMLResponse)
def hosts_page():
    return _render(
        "hosts.html",
        page="hosts",
        hosts=_list_hosts(),
        plugins=_plugin_names(),
    )


@router.post("/hosts", response_class=HTMLResponse)
def create_host(
    profile: str = Form(...),
    os_family: str = Form(...),
    os_version: str = Form(...),
    vendor: str = Form(""),
    mac: str = Form(""),
    hostname_pattern: str = Form(""),
    subnet: str = Form(""),
    group: str = Form(""),
    priority: int = Form(100),
):
    config = _get_config()
    if not config:
        return _render(
            "hosts.html",
            page="hosts",
            hosts=[],
            plugins=_plugin_names(),
            flash={"type": "error", "message": "Server not initialized"},
        )

    from pxeos.api import _write_hosts_toml

    import sys
    if sys.version_info >= (3, 11):
        import tomllib
    else:
        try:
            import tomllib
        except ModuleNotFoundError:
            import tomli as tomllib  # type: ignore[no-redef]

    hosts_file = config.data_dir / "hosts.toml"
    existing: dict = {}
    if hosts_file.exists():
        with open(hosts_file, "rb") as fh:
            existing = tomllib.load(fh)

    hosts_list = existing.get("host", [])
    new_entry: Dict[str, Any] = {
        "profile": profile,
        "os_family": os_family,
        "os_version": os_version,
        "priority": priority,
    }
    if vendor:
        new_entry["vendor"] = vendor
    if mac:
        new_entry["mac"] = mac
    if hostname_pattern:
        new_entry["hostname_pattern"] = hostname_pattern
    if subnet:
        new_entry["subnet"] = subnet
    if group:
        new_entry["group"] = group
    hosts_list.append(new_entry)

    _write_hosts_toml(hosts_file, hosts_list)

    return _render(
        "hosts.html",
        page="hosts",
        hosts=_list_hosts(),
        plugins=_plugin_names(),
        flash={"type": "success", "message": "Host rule added"},
    )


# ------- Cloud-Init -------


@router.get("/cloud-init", response_class=HTMLResponse)
def cloud_init_page():
    return _render("cloud_init.html", page="cloud-init")


@router.post("/cloud-init/generate", response_class=HTMLResponse)
def web_cloud_init_generate(
    name: str = Form(...),
    hostname: str = Form(""),
    user: str = Form("admin"),
    password: str = Form(""),
    ssh_keys: str = Form(""),
    packages: str = Form(""),
    post_scripts: str = Form(""),
    network: str = Form("dhcp"),
    ip: str = Form(""),
    gateway: str = Form(""),
    dns: str = Form("8.8.8.8,8.8.4.4"),
    timezone: str = Form("UTC"),
    locale: str = Form("en_US.UTF-8"),
):
    from pxeos.cloud_init import generate
    from pxeos.models import ProvisionProfile

    net: Dict[str, Any] = {
        "method": network,
        "hostname": hostname or name,
        "device": "eth0",
    }
    if network == "static" and ip:
        net["address"] = ip
        if gateway:
            net["gateway"] = gateway
    dns_list = [d.strip() for d in dns.split(",") if d.strip()]
    if dns_list:
        net["nameservers"] = dns_list

    ssh_key_list = [k.strip() for k in ssh_keys.splitlines() if k.strip()]
    pkg_list = [p.strip() for p in packages.split(",") if p.strip()]
    script_list = [s for s in post_scripts.splitlines() if s.strip()]

    extra: Dict[str, Any] = {
        "user": user,
        "timezone": timezone,
        "locale": locale,
    }
    if password:
        extra["password"] = password
    if ssh_key_list:
        extra["ssh_authorized_keys"] = ssh_key_list

    profile = ProvisionProfile(
        name=name,
        os_family="",
        os_version="",
        network=net,
        packages=pkg_list,
        post_scripts=script_list,
        extra=extra,
    )
    config = generate(profile)

    tmpl = _templates.get_template("cloud_init.html")
    fragment = ""
    if config.user_data:
        fragment += f'<div class="card"><h3>user-data</h3><pre>{config.user_data}</pre></div>'
        fragment += f'<div class="card"><h3>meta-data</h3><pre>{config.meta_data}</pre></div>'
        if config.network_config:
            fragment += f'<div class="card"><h3>network-config</h3><pre>{config.network_config}</pre></div>'
    return HTMLResponse(fragment)


@router.post("/cloud-init/iso")
def web_cloud_init_iso(
    name: str = Form(...),
    hostname: str = Form(""),
    user: str = Form("admin"),
    password: str = Form(""),
    ssh_keys: str = Form(""),
    packages: str = Form(""),
    post_scripts: str = Form(""),
    network: str = Form("dhcp"),
    ip: str = Form(""),
    gateway: str = Form(""),
    dns: str = Form("8.8.8.8,8.8.4.4"),
    timezone: str = Form("UTC"),
    locale: str = Form("en_US.UTF-8"),
):
    from pxeos.cloud_init import create_config_drive
    from pxeos.models import ProvisionProfile

    net: Dict[str, Any] = {
        "method": network,
        "hostname": hostname or name,
        "device": "eth0",
    }
    if network == "static" and ip:
        net["address"] = ip
        if gateway:
            net["gateway"] = gateway
    dns_list = [d.strip() for d in dns.split(",") if d.strip()]
    if dns_list:
        net["nameservers"] = dns_list

    ssh_key_list = [k.strip() for k in ssh_keys.splitlines() if k.strip()]
    pkg_list = [p.strip() for p in packages.split(",") if p.strip()]
    script_list = [s for s in post_scripts.splitlines() if s.strip()]

    extra: Dict[str, Any] = {
        "user": user,
        "timezone": timezone,
        "locale": locale,
    }
    if password:
        extra["password"] = password
    if ssh_key_list:
        extra["ssh_authorized_keys"] = ssh_key_list

    profile = ProvisionProfile(
        name=name,
        os_family="",
        os_version="",
        network=net,
        packages=pkg_list,
        post_scripts=script_list,
        extra=extra,
    )

    with tempfile.NamedTemporaryFile(suffix=".iso", delete=False) as tmp:
        output_path = Path(tmp.name)

    create_config_drive(profile, output_path)
    return FileResponse(
        path=str(output_path),
        media_type="application/octet-stream",
        filename=f"{name}-cloud-init.iso",
    )


# ------- Import -------


@router.get("/import", response_class=HTMLResponse)
def import_page():
    return _render(
        "import.html",
        page="import",
        plugins=_plugin_names(),
    )


@router.post("/import/upload", response_class=HTMLResponse)
async def web_import_upload(
    os_family: str = Form(...),
    version: str = Form(...),
    vendor: str = Form(""),
    arch: str = Form("x86_64"),
    iso_file: UploadFile = File(...),
):
    config = _get_config()
    registry = _get_registry()
    if not config or not registry:
        return HTMLResponse(
            '<div class="card"><div class="flash flash-error">Server not initialized</div></div>'
        )

    from pxeos.importer import import_iso

    with tempfile.NamedTemporaryFile(suffix=".iso", delete=False) as tmp:
        iso_path = Path(tmp.name)
        content = await iso_file.read()
        tmp.write(content)

    try:
        assets = import_iso(
            iso_path, os_family, vendor, version, arch,
            registry, config.distro_root,
        )
        initrd_row = ""
        if assets.initrd_path:
            initrd_row = f"<tr><td>Initrd</td><td><code>{assets.initrd_path}</code></td></tr>"
        return HTMLResponse(
            f'<div class="card"><h3>Import Result</h3>'
            f'<div class="flash flash-success">Import successful</div>'
            f"<table><tbody>"
            f"<tr><td>Kernel</td><td><code>{assets.kernel_path}</code></td></tr>"
            f"{initrd_row}"
            f"<tr><td>Repo</td><td><code>{assets.repo_path}</code></td></tr>"
            f"</tbody></table></div>"
        )
    except Exception as exc:
        return HTMLResponse(
            f'<div class="card"><div class="flash flash-error">Import failed: {exc}</div></div>'
        )
    finally:
        iso_path.unlink(missing_ok=True)


@router.post("/import/fetch", response_class=HTMLResponse)
def web_import_fetch(
    os_family: str = Form(...),
    version: str = Form(...),
    vendor: str = Form(""),
    arch: str = Form("x86_64"),
    kernel_url: str = Form(...),
    initrd_url: str = Form(""),
):
    config = _get_config()
    registry = _get_registry()
    if not config or not registry:
        return HTMLResponse(
            '<div class="card"><div class="flash flash-error">Server not initialized</div></div>'
        )

    from pxeos.importer import import_url

    try:
        assets = import_url(
            kernel_url, os_family, vendor, version, arch,
            registry, config.distro_root,
        )
        initrd_row = ""
        if assets.initrd_path:
            initrd_row = f"<tr><td>Initrd</td><td><code>{assets.initrd_path}</code></td></tr>"
        return HTMLResponse(
            f'<div class="card"><h3>Import Result</h3>'
            f'<div class="flash flash-success">Fetch import successful</div>'
            f"<table><tbody>"
            f"<tr><td>Kernel</td><td><code>{assets.kernel_path}</code></td></tr>"
            f"{initrd_row}"
            f"<tr><td>Repo</td><td><code>{assets.repo_path}</code></td></tr>"
            f"</tbody></table></div>"
        )
    except Exception as exc:
        return HTMLResponse(
            f'<div class="card"><div class="flash flash-error">Fetch failed: {exc}</div></div>'
        )
