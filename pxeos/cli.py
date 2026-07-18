"""Command-line interface for PxeOS."""

# PYTHON_ARGCOMPLETE_OK

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List, Optional, Sequence

try:
    import argcomplete
except ImportError:
    argcomplete = None  # type: ignore[assignment]

from pxeos import __version__
from pxeos.config import (
    PxeOSConfig,
    load_config,
    load_hosts,
    load_profile,
)
from pxeos.engine import ProvisioningEngine
from pxeos.matcher import HostMatcher
from pxeos.models import HostRule
from pxeos.registry import PluginRegistry


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pxeos",
        description="Cross-OS PXE boot provisioning system",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"pxeos {__version__}",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("/etc/pxeos/pxeos.toml"),
        help="path to config file",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="set logging level (default: INFO)",
    )
    parser.add_argument(
        "--log-json",
        action="store_true",
        default=False,
        help="emit JSON-formatted log lines",
    )

    sub = parser.add_subparsers(dest="command")

    _add_server_parser(sub)
    _add_import_parser(sub)
    _add_profile_parser(sub)
    _add_host_parser(sub)
    _add_client_parser(sub)
    _add_cloud_init_parser(sub)
    _add_provision_parser(sub)
    _add_distro_parser(sub)
    _add_secret_parser(sub)
    _add_named_host_parser(sub)
    _add_auth_parser(sub)
    _add_power_parser(sub)
    _add_migrate_parser(sub)
    _add_service_parser(sub)

    return parser


def _add_server_parser(
    sub: argparse._SubParsersAction,
) -> None:
    srv = sub.add_parser("server", help="manage server")
    srv_sub = srv.add_subparsers(dest="server_action")

    start = srv_sub.add_parser("start", help="start server")
    start.add_argument(
        "--host", default=None, help="bind address"
    )
    start.add_argument(
        "--port", type=int, default=None, help="bind port"
    )

    srv_sub.add_parser("status", help="show server status")


def _add_import_parser(
    sub: argparse._SubParsersAction,
) -> None:
    imp = sub.add_parser(
        "import", help="import distro assets"
    )
    source = imp.add_mutually_exclusive_group(required=True)
    source.add_argument("--iso", type=Path, help="ISO path")
    source.add_argument("--url", help="mirror URL")
    imp.add_argument(
        "--distro",
        help="distro mnemonic (e.g. fedora42, rhel9, deb12)",
    )
    imp.add_argument(
        "--os", dest="os_family",
        help="OS family (not needed with --distro)",
    )
    imp.add_argument(
        "--vendor", default="",
        help="OS vendor (e.g. fedora, rhel, rocky)",
    )
    imp.add_argument(
        "--version", dest="os_version",
        help="OS version (not needed with --distro)",
    )
    imp.add_argument(
        "--arch", default="x86_64", help="architecture"
    )
    imp.add_argument(
        "--live", action="store_true", default=False,
        help="import as live ISO (squashfs rootfs)",
    )
    imp.add_argument(
        "--dry-run", action="store_true", default=False,
        help="validate inputs and show what would be imported without extracting",
    )


def _add_profile_parser(
    sub: argparse._SubParsersAction,
) -> None:
    prof = sub.add_parser(
        "profile", help="manage profiles"
    )
    prof_sub = prof.add_subparsers(dest="profile_action")

    add = prof_sub.add_parser("add", help="add profile")
    add.add_argument("file", type=Path, help="TOML file")

    prof_sub.add_parser("list", help="list profiles")

    show = prof_sub.add_parser("show", help="show profile")
    show.add_argument("name", help="profile name")

    delete = prof_sub.add_parser(
        "delete", help="delete profile"
    )
    delete.add_argument("name", help="profile name")


def _add_host_parser(
    sub: argparse._SubParsersAction,
) -> None:
    host = sub.add_parser("host", help="manage host rules")
    host_sub = host.add_subparsers(dest="host_action")

    add = host_sub.add_parser("add", help="add host rule")
    add.add_argument(
        "--profile", required=True, help="profile name"
    )
    add.add_argument(
        "--os", dest="os_family", required=True,
        help="OS family",
    )
    add.add_argument(
        "--vendor", default="",
        help="OS vendor (e.g. fedora, rhel, rocky)",
    )
    add.add_argument(
        "--version", dest="os_version", required=True,
        help="OS version",
    )
    add.add_argument("--mac", help="MAC address")
    add.add_argument("--mac-prefix", help="MAC prefix")
    add.add_argument("--hostname", help="hostname glob")
    add.add_argument("--subnet", help="CIDR subnet")
    add.add_argument("--serial", help="serial number")
    add.add_argument("--group", help="group name")
    add.add_argument("--arch", help="architecture")
    add.add_argument(
        "--priority", type=int, default=100,
        help="priority (lower = higher)",
    )

    host_sub.add_parser("list", help="list host rules")

    show = host_sub.add_parser(
        "show", help="show host rule"
    )
    show.add_argument("mac", help="MAC address")

    delete = host_sub.add_parser(
        "delete", help="delete host rule"
    )
    delete.add_argument("mac", help="MAC address")

    # Boot-once netboot control (issue #19)
    disable_nb = host_sub.add_parser(
        "disable-netboot",
        help="disable PXE netboot for a MAC (boot-once)",
    )
    disable_nb.add_argument("mac", help="MAC address")

    enable_nb = host_sub.add_parser(
        "enable-netboot",
        help="re-enable PXE netboot for a MAC",
    )
    enable_nb.add_argument("mac", help="MAC address")


def _add_client_parser(
    sub: argparse._SubParsersAction,
) -> None:
    client = sub.add_parser(
        "client", help="client operations"
    )
    client_sub = client.add_subparsers(
        dest="client_action"
    )

    reg = client_sub.add_parser(
        "register", help="register client"
    )
    reg.add_argument(
        "--mac", required=True, help="MAC address"
    )
    reg.add_argument(
        "--profile", required=True, help="profile name"
    )
    reg.add_argument(
        "--os", dest="os_family", required=True,
        help="OS family",
    )
    reg.add_argument(
        "--vendor", default="",
        help="OS vendor (e.g. fedora, rhel, rocky)",
    )
    reg.add_argument(
        "--version", dest="os_version", required=True,
        help="OS version",
    )

    replace = client_sub.add_parser(
        "replace", help="replace client config"
    )
    replace.add_argument(
        "--mac", required=True, help="MAC address"
    )
    replace.add_argument(
        "--profile", required=True, help="new profile"
    )
    replace.add_argument(
        "--os", dest="os_family", required=True,
        help="OS family",
    )
    replace.add_argument(
        "--vendor", default="",
        help="OS vendor (e.g. fedora, rhel, rocky)",
    )
    replace.add_argument(
        "--version", dest="os_version", required=True,
        help="OS version",
    )

    client_sub.add_parser(
        "list-profiles",
        help="list available profiles",
    )


def _add_cloud_init_parser(
    sub: argparse._SubParsersAction,
) -> None:
    ci = sub.add_parser(
        "cloud-init", help="cloud-init config generation"
    )
    ci_sub = ci.add_subparsers(dest="cloud_init_action")

    gen = ci_sub.add_parser(
        "generate", help="generate cloud-init configs"
    )
    gen.add_argument(
        "--name", required=True, help="instance name"
    )
    gen.add_argument(
        "--hostname", default=None, help="hostname"
    )
    gen.add_argument(
        "--user", default="admin", help="default user"
    )
    gen.add_argument(
        "--password", default=None, help="user password"
    )
    gen.add_argument(
        "--ssh-key", type=Path, default=None,
        help="SSH public key file",
    )
    gen.add_argument(
        "--packages", default="",
        help="comma-separated package list",
    )
    gen.add_argument(
        "--network", default="dhcp",
        choices=["dhcp", "static"],
        help="network method",
    )
    gen.add_argument("--ip", default=None, help="static IP")
    gen.add_argument(
        "--gateway", default=None, help="gateway"
    )
    gen.add_argument(
        "--dns", default="8.8.8.8",
        help="DNS servers (comma-separated)",
    )
    gen.add_argument(
        "--output-dir", type=Path, default=None,
        help="write configs to directory",
    )

    iso = ci_sub.add_parser(
        "iso", help="create config drive ISO"
    )
    iso.add_argument(
        "--name", required=True, help="instance name"
    )
    iso.add_argument(
        "--hostname", default=None, help="hostname"
    )
    iso.add_argument(
        "--user", default="admin", help="default user"
    )
    iso.add_argument(
        "--password", default=None, help="user password"
    )
    iso.add_argument(
        "--ssh-key", type=Path, default=None,
        help="SSH public key file",
    )
    iso.add_argument(
        "--packages", default="",
        help="comma-separated package list",
    )
    iso.add_argument(
        "--network", default="dhcp",
        choices=["dhcp", "static"],
        help="network method",
    )
    iso.add_argument("--ip", default=None, help="static IP")
    iso.add_argument(
        "--gateway", default=None, help="gateway"
    )
    iso.add_argument(
        "--dns", default="8.8.8.8",
        help="DNS servers (comma-separated)",
    )
    iso.add_argument(
        "--output", "-o", type=Path, required=True,
        help="output ISO path",
    )


def _init_stack(
    config_path: Path,
) -> tuple[PxeOSConfig, PluginRegistry, HostMatcher]:
    if config_path.exists():
        config = load_config(config_path)
    else:
        config = PxeOSConfig()

    registry = PluginRegistry()
    registry.load_builtins()
    registry.discover()

    hosts_path = config.data_dir / "hosts.toml"
    rules: List[HostRule] = []
    if hosts_path.exists():
        rules = load_hosts(hosts_path)
    matcher = HostMatcher(rules)

    return config, registry, matcher


def _cmd_server(
    args: argparse.Namespace,
    config: PxeOSConfig,
    registry: PluginRegistry,
    matcher: HostMatcher,
) -> int:
    if args.server_action == "start":
        host = args.host or config.server_host
        port = args.port or config.server_port

        try:
            import uvicorn

            from pxeos.api import init_app

            init_app(registry, config, matcher)
            uvicorn.run(
                "pxeos.api:app",
                host=host,
                port=port,
                ssl_certfile=(
                    str(config.tls_cert)
                    if config.tls_cert
                    else None
                ),
                ssl_keyfile=(
                    str(config.tls_key)
                    if config.tls_key
                    else None
                ),
            )
        except KeyboardInterrupt:
            pass
        return 0

    elif args.server_action == "status":
        print(f"host: {config.server_host}")
        print(f"port: {config.server_port}")
        print(f"tls:  {bool(config.tls_cert)}")
        print(
            f"plugins: {', '.join(registry.available)}"
        )
        return 0

    print("usage: pxeos server {start|status}")
    return 1


def _resolve_distro_args(args: argparse.Namespace) -> None:
    if getattr(args, "distro", None):
        from pxeos.mnemonics import resolve_mnemonic

        alias = resolve_mnemonic(args.distro)
        if alias is None:
            print(
                f"error: unknown mnemonic {args.distro!r}. "
                "Use 'pxeos distro aliases' to list available mnemonics.",
                file=sys.stderr,
            )
            sys.exit(1)
        if not args.os_family:
            args.os_family = alias.os_family
        if not args.vendor:
            args.vendor = alias.vendor
        if not args.os_version:
            args.os_version = alias.version

    # For ISO imports, auto-detection will fill missing values
    if getattr(args, "iso", None) and args.iso:
        return

    if not args.os_family or not args.os_version:
        print(
            "error: --distro or both --os and --version required",
            file=sys.stderr,
        )
        sys.exit(1)


def _cmd_import(
    args: argparse.Namespace,
    config: PxeOSConfig,
    registry: PluginRegistry,
) -> int:
    from pxeos.importer import import_iso, import_url

    # Validate ISO file exists before attempting to mount
    if args.iso and not args.iso.exists():
        print(
            f"error: ISO file not found: {args.iso}\n"
            f"hint: check the path and ensure the file exists.",
            file=sys.stderr,
        )
        return 1

    _resolve_distro_args(args)

    dry_run = getattr(args, "dry_run", False)
    live = getattr(args, "live", False)

    if dry_run:
        print("[dry-run] Import preview:")
        if args.iso:
            size_mb = args.iso.stat().st_size / (1024 * 1024)
            print(f"  source:     {args.iso} ({size_mb:.1f} MB)")
        else:
            print(f"  source:     {args.url}")
        print(f"  os_family:  {args.os_family}")
        if args.vendor:
            print(f"  vendor:     {args.vendor}")
        print(f"  os_version: {args.os_version}")
        print(f"  arch:       {args.arch}")
        if live:
            print(f"  live:       yes")

        # Validate plugin exists
        try:
            plugin = registry.get(args.os_family)
            print(f"  plugin:     {plugin.os_family}")
            if live and not plugin.supports_live:
                print(
                    f"\n  warning: {args.os_family} plugin "
                    f"does not support live ISO import",
                    file=sys.stderr,
                )
        except ValueError as exc:
            print(f"\nerror: {exc}", file=sys.stderr)
            return 1

        dir_vendor = args.vendor or args.os_family
        if live:
            dir_vendor = f"{dir_vendor}-live"
        dest_name = f"{dir_vendor}-{args.os_version}-{args.arch}"
        dest = config.distro_root / dest_name
        print(f"  dest:       {dest}")
        print()
        print(
            "[dry-run] No files extracted. "
            "Remove --dry-run to import for real."
        )
        return 0

    if args.iso:
        assets = import_iso(
            args.iso,
            args.os_family,
            args.vendor,
            args.os_version,
            args.arch,
            registry,
            config.distro_root,
            live=live,
        )
    else:
        assets = import_url(
            args.url,
            args.os_family,
            args.vendor,
            args.os_version,
            args.arch,
            registry,
            config.distro_root,
        )

    print(f"kernel:  {assets.kernel_path}")
    if assets.initrd_path:
        print(f"initrd:  {assets.initrd_path}")
    print(f"repo:    {assets.repo_path}")
    if assets.squashfs_path:
        print(f"rootfs:  {assets.squashfs_path}")
    return 0


def _cmd_profile(
    args: argparse.Namespace,
    config: PxeOSConfig,
) -> int:
    profiles_dir = config.data_dir / "profiles"

    if args.profile_action == "add":
        profiles_dir.mkdir(parents=True, exist_ok=True)
        profile = load_profile(args.file)
        dest = profiles_dir / f"{profile.name}.toml"

        import shutil

        shutil.copy2(args.file, dest)
        print(f"added profile: {profile.name}")
        return 0

    elif args.profile_action == "list":
        if not profiles_dir.exists():
            print("no profiles configured")
            return 0
        for f in sorted(profiles_dir.glob("*.toml")):
            try:
                p = load_profile(f)
                vendor_str = f" [{p.vendor}]" if p.vendor else ""
                print(
                    f"  {p.name:<20s} "
                    f"{p.os_family}/{p.os_version}"
                    f"{vendor_str} "
                    f"({p.arch})"
                )
            except Exception as exc:
                print(f"  {f.stem:<20s} [error: {exc}]")
        return 0

    elif args.profile_action == "show":
        path = profiles_dir / f"{args.name}.toml"
        if not path.exists():
            print(f"profile not found: {args.name}")
            return 1
        p = load_profile(path)
        print(f"name:     {p.name}")
        print(f"os:       {p.os_family} {p.os_version}")
        if p.vendor:
            print(f"vendor:   {p.vendor}")
        print(f"arch:     {p.arch}")
        print(f"firmware: {p.firmware.value}")
        if p.packages:
            print(f"packages: {', '.join(p.packages)}")
        return 0

    elif args.profile_action == "delete":
        path = profiles_dir / f"{args.name}.toml"
        if path.exists():
            path.unlink()
            print(f"deleted profile: {args.name}")
        else:
            print(f"profile not found: {args.name}")
            return 1
        return 0

    print("usage: pxeos profile {add|list|show|delete}")
    return 1


def _cmd_host(
    args: argparse.Namespace,
    config: PxeOSConfig,
) -> int:
    hosts_path = config.data_dir / "hosts.toml"

    if args.host_action == "add":
        import sys as _sys

        if _sys.version_info >= (3, 11):
            import tomllib
        else:
            try:
                import tomllib
            except ModuleNotFoundError:
                import tomli as tomllib  # type: ignore[no-redef]

        existing: dict = {}
        if hosts_path.exists():
            with open(hosts_path, "rb") as fh:
                existing = tomllib.load(fh)

        hosts_list: list = existing.get("host", [])
        entry: dict = {
            "profile": args.profile,
            "os_family": args.os_family,
            "os_version": args.os_version,
            "vendor": args.vendor,
            "priority": args.priority,
        }
        for field_name, attr_name in [
            ("mac", "mac"),
            ("mac_prefix", "mac_prefix"),
            ("hostname_pattern", "hostname"),
            ("subnet", "subnet"),
            ("serial", "serial"),
            ("group", "group"),
            ("arch", "arch"),
        ]:
            val = getattr(args, attr_name, None)
            if val is not None:
                entry[field_name] = val

        hosts_list.append(entry)
        _write_hosts_file(hosts_path, hosts_list)
        print(f"added host rule for profile {args.profile}")
        return 0

    elif args.host_action == "list":
        if not hosts_path.exists():
            print("no host rules configured")
            return 0
        rules = load_hosts(hosts_path)
        for r in rules:
            criteria = []
            if r.mac:
                criteria.append(f"mac={r.mac}")
            if r.mac_prefix:
                criteria.append(f"prefix={r.mac_prefix}")
            if r.hostname_pattern:
                criteria.append(
                    f"host={r.hostname_pattern}"
                )
            if r.subnet:
                criteria.append(f"subnet={r.subnet}")
            if r.serial:
                criteria.append(f"serial={r.serial}")
            if r.group:
                criteria.append(f"group={r.group}")
            if r.arch:
                criteria.append(f"arch={r.arch}")
            match_str = (
                ", ".join(criteria) if criteria else "default"
            )
            print(
                f"  [{r.priority:3d}] "
                f"{r.profile:<20s} "
                f"{r.os_family}/{r.os_version} "
                f"({match_str})"
            )
        return 0

    elif args.host_action == "show":
        if not hosts_path.exists():
            print("no host rules configured")
            return 1
        rules = load_hosts(hosts_path)
        mac_norm = args.mac.lower().replace("-", ":")
        for r in rules:
            if r.mac and r.mac.lower().replace("-", ":") == mac_norm:
                print(f"profile:  {r.profile}")
                print(
                    f"os:       {r.os_family} {r.os_version}"
                )
                print(f"mac:      {r.mac}")
                print(f"priority: {r.priority}")
                return 0
        print(f"no rule found for MAC {args.mac}")
        return 1

    elif args.host_action == "delete":
        if not hosts_path.exists():
            print("no host rules configured")
            return 1

        import sys as _sys

        if _sys.version_info >= (3, 11):
            import tomllib
        else:
            try:
                import tomllib
            except ModuleNotFoundError:
                import tomli as tomllib  # type: ignore[no-redef]

        with open(hosts_path, "rb") as fh:
            existing = tomllib.load(fh)

        hosts_list = existing.get("host", [])
        mac_norm = args.mac.lower().replace("-", ":")
        new_list = [
            h
            for h in hosts_list
            if not (
                h.get("mac", "").lower().replace("-", ":")
                == mac_norm
            )
        ]
        if len(new_list) == len(hosts_list):
            print(f"no rule found for MAC {args.mac}")
            return 1

        _write_hosts_file(hosts_path, new_list)
        print(f"deleted host rule for MAC {args.mac}")
        return 0

    elif args.host_action == "disable-netboot":
        return _cmd_host_netboot(args.mac, enable=False, config=config)

    elif args.host_action == "enable-netboot":
        return _cmd_host_netboot(args.mac, enable=True, config=config)

    print(
        "usage: pxeos host "
        "{add|list|show|delete|disable-netboot|enable-netboot}"
    )
    return 1


def _cmd_host_netboot(
    mac: str,
    enable: bool,
    config: PxeOSConfig,
) -> int:
    """Toggle netboot for a MAC via the running PxeOS server."""
    import urllib.error
    import urllib.request

    action = "enable-netboot" if enable else "disable-netboot"
    scheme = "https" if config.tls_cert else "http"
    host = config.server_host
    if host == "0.0.0.0":
        host = "127.0.0.1"
    url = (
        f"{scheme}://{host}:{config.server_port}"
        f"/api/v1/provision/{mac}/{action}"
    )

    try:
        req = urllib.request.Request(url, method="POST", data=b"")
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode())
            verb = "enabled" if enable else "disabled"
            print(f"netboot {verb} for {data['mac']}")
            return 0
    except urllib.error.HTTPError as exc:
        body = exc.read().decode()
        try:
            detail = json.loads(body).get("detail", body)
        except (json.JSONDecodeError, AttributeError):
            detail = body
        print(f"error: {detail}", file=sys.stderr)
        return 1
    except urllib.error.URLError as exc:
        print(
            f"error: cannot reach PxeOS server at {url}: {exc.reason}",
            file=sys.stderr,
        )
        return 1


def _cmd_client(
    args: argparse.Namespace,
    config: PxeOSConfig,
    registry: PluginRegistry,
    matcher: HostMatcher,
) -> int:
    if args.client_action == "register":
        engine = ProvisioningEngine(
            registry, matcher, config
        )
        rule = HostRule(
            profile=args.profile,
            os_family=args.os_family,
            os_version=args.os_version,
            vendor=args.vendor,
            mac=args.mac,
            priority=10,
        )
        print(f"registered {args.mac} -> {args.profile}")
        return 0

    elif args.client_action == "replace":
        print(
            f"replaced {args.mac} -> {args.profile} "
            f"({args.os_family}/{args.os_version})"
        )
        return 0

    elif args.client_action == "list-profiles":
        profiles_dir = config.data_dir / "profiles"
        if not profiles_dir.exists():
            print("no profiles available")
            return 0
        for f in sorted(profiles_dir.glob("*.toml")):
            try:
                p = load_profile(f)
                print(
                    f"  {p.name} "
                    f"({p.os_family}/{p.os_version})"
                )
            except Exception:
                pass
        return 0

    print(
        "usage: pxeos client "
        "{register|replace|list-profiles}"
    )
    return 1


def _build_cloud_init_profile(
    args: argparse.Namespace,
) -> "ProvisionProfile":
    from pxeos.models import ProvisionProfile

    hostname = args.hostname or args.name
    ssh_keys: list[str] = []
    if args.ssh_key and args.ssh_key.exists():
        ssh_keys = [args.ssh_key.read_text().strip()]

    packages = [
        p.strip() for p in args.packages.split(",") if p.strip()
    ]
    nameservers = [
        n.strip() for n in args.dns.split(",") if n.strip()
    ]

    network = {
        "method": args.network,
        "hostname": hostname,
        "device": "eth0",
    }
    if args.network == "static":
        if args.ip:
            network["address"] = args.ip
        if args.gateway:
            network["gateway"] = args.gateway
        network["nameservers"] = nameservers

    extra: dict = {
        "user": args.user,
    }
    if args.password:
        extra["password"] = args.password
    if ssh_keys:
        extra["ssh_authorized_keys"] = ssh_keys

    return ProvisionProfile(
        name=args.name,
        os_family="",
        os_version="",
        network=network,
        packages=packages,
        extra=extra,
    )


def _cmd_cloud_init(
    args: argparse.Namespace,
) -> int:
    from pxeos.cloud_init import create_config_drive, generate

    if args.cloud_init_action == "generate":
        profile = _build_cloud_init_profile(args)
        config = generate(profile)

        if args.output_dir:
            out = args.output_dir
            out.mkdir(parents=True, exist_ok=True)
            (out / "user-data").write_text(config.user_data)
            (out / "meta-data").write_text(config.meta_data)
            if config.network_config:
                (out / "network-config").write_text(
                    config.network_config
                )
            print(f"cloud-init configs written to {out}")
        else:
            print("=== user-data ===")
            print(config.user_data)
            print("=== meta-data ===")
            print(config.meta_data)
            if config.network_config:
                print("=== network-config ===")
                print(config.network_config)
        return 0

    elif args.cloud_init_action == "iso":
        profile = _build_cloud_init_profile(args)
        try:
            create_config_drive(profile, args.output)
            print(f"config drive ISO: {args.output}")
            return 0
        except RuntimeError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1

    print(
        "usage: pxeos cloud-init {generate|iso}"
    )
    return 1


def _write_hosts_file(
    path: Path, hosts: list[dict],
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


def _add_provision_parser(
    sub: argparse._SubParsersAction,
) -> None:
    prov = sub.add_parser(
        "provision",
        help="provision a host (or preview with --dry-run)",
    )
    prov.add_argument(
        "--mac", required=True, help="MAC address of the host",
    )
    prov.add_argument(
        "--hostname", default=None, help="hostname for matching",
    )
    prov.add_argument(
        "--subnet", default=None, help="client subnet for matching",
    )
    prov.add_argument(
        "--serial", default=None, help="serial number for matching",
    )
    prov.add_argument(
        "--group", action="append", default=None,
        help="group name for matching (repeatable)",
    )
    prov.add_argument(
        "--arch", default=None, help="architecture for matching",
    )
    prov.add_argument(
        "--dry-run", action="store_true", default=False,
        help="show what would be provisioned without tracking state",
    )


def _cmd_provision(
    args: argparse.Namespace,
    config: PxeOSConfig,
    registry: PluginRegistry,
    matcher: HostMatcher,
) -> int:
    from pxeos.validation import normalize_mac, validate_mac

    if not validate_mac(args.mac):
        print(
            f"error: invalid MAC address format: {args.mac!r}",
            file=sys.stderr,
        )
        return 1

    mac = normalize_mac(args.mac)
    engine = ProvisioningEngine(registry, matcher, config)

    # Resolve the matching host rule
    rule = engine.get_rule(
        mac,
        hostname=args.hostname,
        subnet=args.subnet,
        serial=args.serial,
        groups=args.group,
        arch=args.arch,
    )
    if rule is None:
        print(
            f"error: no matching host rule for MAC {mac!r}",
            file=sys.stderr,
        )
        # Show what rules exist so the user can debug
        rules = matcher._rules
        if rules:
            print("\nConfigured host rules:", file=sys.stderr)
            for r in rules:
                criteria = []
                if r.mac:
                    criteria.append(f"mac={r.mac}")
                if r.mac_prefix:
                    criteria.append(f"prefix={r.mac_prefix}")
                if r.hostname_pattern:
                    criteria.append(f"host={r.hostname_pattern}")
                if r.subnet:
                    criteria.append(f"subnet={r.subnet}")
                if r.serial:
                    criteria.append(f"serial={r.serial}")
                if r.group:
                    criteria.append(f"group={r.group}")
                if r.arch:
                    criteria.append(f"arch={r.arch}")
                match_str = ", ".join(criteria) if criteria else "default"
                print(
                    f"  [{r.priority:3d}] {r.profile:<20s} ({match_str})",
                    file=sys.stderr,
                )
        else:
            print(
                "hint: no host rules configured. "
                "Use 'pxeos host add' to create one.",
                file=sys.stderr,
            )
        return 1

    if args.dry_run:
        print("[dry-run] Provisioning preview:")
        print(f"  MAC:       {mac}")
        print(f"  profile:   {rule.profile}")
        print(f"  os_family: {rule.os_family}")
        print(f"  os_version:{rule.os_version}")
        if rule.vendor:
            print(f"  vendor:    {rule.vendor}")
        print(f"  priority:  {rule.priority}")

        try:
            plugin = registry.get(rule.os_family)
        except ValueError as exc:
            print(f"\nerror: {exc}", file=sys.stderr)
            return 1

        print(f"  plugin:    {plugin.os_family}")
        print()
        print("[dry-run] No state tracked. "
              "Remove --dry-run to provision for real.")
        return 0

    # Real provisioning
    try:
        assets = engine.provision(
            mac,
            hostname=args.hostname,
            subnet=args.subnet,
            serial=args.serial,
            groups=args.group,
            arch=args.arch,
        )
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(f"kernel: {assets.kernel}")
    if assets.initrd:
        print(f"initrd: {assets.initrd}")
    if assets.boot_args:
        print(f"args:   {' '.join(assets.boot_args)}")
    return 0


def _add_distro_parser(
    sub: argparse._SubParsersAction,
) -> None:
    distro = sub.add_parser(
        "distro", help="manage named distros and mnemonic tools"
    )
    distro_sub = distro.add_subparsers(
        dest="distro_action"
    )
    distro_sub.add_parser(
        "aliases", help="list available mnemonics"
    )
    resolve = distro_sub.add_parser(
        "resolve", help="resolve a mnemonic"
    )
    resolve.add_argument("mnemonic", help="mnemonic to resolve")

    # Named distro CRUD subcommands
    d_add = distro_sub.add_parser(
        "add", help="add a named distro"
    )
    d_add.add_argument(
        "--name", required=True, help="distro name"
    )
    d_add.add_argument(
        "--os", dest="os_family", required=True,
        help="OS family (e.g. fedora, debian)",
    )
    d_add.add_argument(
        "--vendor", required=True,
        help="vendor (e.g. rhel, rocky)",
    )
    d_add.add_argument(
        "--version", dest="os_version", required=True,
        help="OS version",
    )
    d_add.add_argument(
        "--arch", default="x86_64", help="architecture"
    )
    d_add.add_argument(
        "--kernel", dest="kernel_path", default="",
        help="kernel path",
    )
    d_add.add_argument(
        "--initrd", dest="initrd_path", default="",
        help="initrd path",
    )
    d_add.add_argument(
        "--install-url", default="",
        help="install URL",
    )
    d_add.add_argument(
        "--comment", default="", help="comment"
    )

    distro_sub.add_parser(
        "list", help="list named distros"
    )

    d_show = distro_sub.add_parser(
        "show", help="show a named distro"
    )
    d_show.add_argument("name", help="distro name")

    d_delete = distro_sub.add_parser(
        "delete", help="delete a named distro"
    )
    d_delete.add_argument("name", help="distro name")


def _add_named_host_parser(
    sub: argparse._SubParsersAction,
) -> None:
    nhost = sub.add_parser(
        "named-host", help="manage named hosts (cobbler-style)"
    )
    nhost_sub = nhost.add_subparsers(
        dest="named_host_action"
    )

    nh_add = nhost_sub.add_parser(
        "add", help="add a named host"
    )
    nh_add.add_argument(
        "--name", required=True, help="host name"
    )
    nh_add.add_argument(
        "--mac", required=True, help="MAC address"
    )
    nh_add.add_argument(
        "--profile", default="",
        help="profile name",
    )
    nh_add.add_argument(
        "--distro", default="",
        help="named distro to use",
    )
    nh_add.add_argument(
        "--hostname", default="",
        help="FQDN hostname",
    )
    nh_add.add_argument(
        "--gateway", default="", help="gateway IP"
    )
    nh_add.add_argument(
        "--nameservers", default="",
        help="comma-separated nameservers",
    )
    nh_add.add_argument(
        "--ip", dest="ip_address", default="",
        help="IP address",
    )
    nh_add.add_argument(
        "--netmask", default="",
        help="netmask (e.g. 255.255.255.0)",
    )
    nh_add.add_argument(
        "--comment", default="", help="comment"
    )

    nhost_sub.add_parser(
        "list", help="list named hosts"
    )

    nh_show = nhost_sub.add_parser(
        "show", help="show a named host"
    )
    nh_show.add_argument("name", help="host name")

    nh_delete = nhost_sub.add_parser(
        "delete", help="delete a named host"
    )
    nh_delete.add_argument("name", help="host name")


def _cmd_distro(
    args: argparse.Namespace,
    config: Optional[PxeOSConfig] = None,
) -> int:
    # Mnemonic subcommands (no config needed)
    if args.distro_action == "aliases":
        from pxeos.mnemonics import list_mnemonics

        aliases = list_mnemonics()
        fmt = "{:<20s} {:<12s} {:<12s} {}"
        print(fmt.format("MNEMONIC", "OS_FAMILY", "VENDOR", "VERSION"))
        print("-" * 60)
        for name, alias in aliases:
            print(fmt.format(
                name, alias.os_family, alias.vendor, alias.version,
            ))
        return 0

    elif args.distro_action == "resolve":
        from pxeos.mnemonics import resolve_mnemonic

        alias = resolve_mnemonic(args.mnemonic)
        if alias is None:
            print(
                f"error: unknown mnemonic {args.mnemonic!r}",
                file=sys.stderr,
            )
            return 1
        print(f"os_family: {alias.os_family}")
        print(f"vendor:    {alias.vendor}")
        print(f"version:   {alias.version}")
        return 0

    # Named distro CRUD subcommands (config needed)
    elif args.distro_action in ("add", "list", "show", "delete"):
        from pxeos.named_objects import NamedDistro, NamedObjectStore

        if config is None:
            config = PxeOSConfig()
        store = NamedObjectStore(config.data_dir / "named")

        if args.distro_action == "add":
            distro = NamedDistro(
                name=args.name,
                os_family=args.os_family,
                vendor=args.vendor,
                version=args.os_version,
                arch=args.arch,
                kernel_path=args.kernel_path,
                initrd_path=args.initrd_path,
                install_url=args.install_url,
                comment=args.comment,
            )
            try:
                store.add_distro(distro)
            except ValueError as exc:
                print(f"error: {exc}", file=sys.stderr)
                return 1
            print(f"added named distro: {distro.name}")
            return 0

        elif args.distro_action == "list":
            distros = store.list_distros()
            if not distros:
                print("no named distros")
                return 0
            fmt = "{:<20s} {:<12s} {:<12s} {:<8s} {}"
            print(fmt.format(
                "NAME", "OS_FAMILY", "VENDOR", "VERSION", "ARCH",
            ))
            print("-" * 70)
            for d in distros:
                print(fmt.format(
                    d.name, d.os_family, d.vendor,
                    d.version, d.arch,
                ))
            return 0

        elif args.distro_action == "show":
            distro = store.get_distro(args.name)
            if distro is None:
                print(f"named distro not found: {args.name}")
                return 1
            print(f"name:        {distro.name}")
            print(f"os_family:   {distro.os_family}")
            print(f"vendor:      {distro.vendor}")
            print(f"version:     {distro.version}")
            print(f"arch:        {distro.arch}")
            if distro.kernel_path:
                print(f"kernel:      {distro.kernel_path}")
            if distro.initrd_path:
                print(f"initrd:      {distro.initrd_path}")
            if distro.install_url:
                print(f"install_url: {distro.install_url}")
            if distro.comment:
                print(f"comment:     {distro.comment}")
            return 0

        elif args.distro_action == "delete":
            if store.delete_distro(args.name):
                print(f"deleted named distro: {args.name}")
                return 0
            print(f"named distro not found: {args.name}")
            return 1

    print(
        "usage: pxeos distro "
        "{aliases|resolve|add|list|show|delete}"
    )
    return 1


def _cmd_named_host(
    args: argparse.Namespace,
    config: PxeOSConfig,
) -> int:
    from pxeos.named_objects import NamedHost, NamedObjectStore

    store = NamedObjectStore(config.data_dir / "named")

    if args.named_host_action == "add":
        nameservers = [
            n.strip()
            for n in args.nameservers.split(",")
            if n.strip()
        ]
        host = NamedHost(
            name=args.name,
            mac=args.mac,
            profile=args.profile,
            distro=args.distro,
            hostname=args.hostname,
            gateway=args.gateway,
            nameservers=nameservers,
            ip_address=args.ip_address,
            netmask=args.netmask,
            comment=args.comment,
        )
        try:
            store.add_host(host)
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        print(f"added named host: {host.name}")
        return 0

    elif args.named_host_action == "list":
        hosts = store.list_hosts()
        if not hosts:
            print("no named hosts")
            return 0
        fmt = "{:<20s} {:<20s} {:<20s} {}"
        print(fmt.format("NAME", "MAC", "PROFILE", "HOSTNAME"))
        print("-" * 70)
        for h in hosts:
            print(fmt.format(
                h.name, h.mac,
                h.profile or "-",
                h.hostname or "-",
            ))
        return 0

    elif args.named_host_action == "show":
        host = store.get_host(args.name)
        if host is None:
            print(f"named host not found: {args.name}")
            return 1
        print(f"name:        {host.name}")
        print(f"mac:         {host.mac}")
        if host.profile:
            print(f"profile:     {host.profile}")
        if host.distro:
            print(f"distro:      {host.distro}")
        if host.hostname:
            print(f"hostname:    {host.hostname}")
        if host.ip_address:
            print(f"ip_address:  {host.ip_address}")
        if host.netmask:
            print(f"netmask:     {host.netmask}")
        if host.gateway:
            print(f"gateway:     {host.gateway}")
        if host.nameservers:
            print(
                f"nameservers: {', '.join(host.nameservers)}"
            )
        if host.comment:
            print(f"comment:     {host.comment}")
        return 0

    elif args.named_host_action == "delete":
        if store.delete_host(args.name):
            print(f"deleted named host: {args.name}")
            return 0
        print(f"named host not found: {args.name}")
        return 1

    print(
        "usage: pxeos named-host {add|list|show|delete}"
    )
    return 1


def _add_secret_parser(
    sub: argparse._SubParsersAction,
) -> None:
    secret = sub.add_parser(
        "secret", help="manage secrets"
    )
    secret_sub = secret.add_subparsers(
        dest="secret_action"
    )

    s_set = secret_sub.add_parser(
        "set", help="store a secret"
    )
    s_set.add_argument("key", help="secret key name")
    s_set.add_argument("value", help="secret value")

    s_get = secret_sub.add_parser(
        "get", help="retrieve a secret"
    )
    s_get.add_argument("key", help="secret key name")

    s_del = secret_sub.add_parser(
        "delete", help="remove a secret"
    )
    s_del.add_argument("key", help="secret key name")

    secret_sub.add_parser(
        "list", help="list all secret keys"
    )


def _cmd_secret(
    args: argparse.Namespace,
    config: PxeOSConfig,
) -> int:
    from pxeos.secrets import FileSecretsProvider

    provider = FileSecretsProvider(config.data_dir)

    if args.secret_action == "set":
        provider.set(args.key, args.value)
        print(f"secret stored: {args.key}")
        return 0

    elif args.secret_action == "get":
        value = provider.get(args.key)
        if value is None:
            print(
                f"secret not found: {args.key}",
                file=sys.stderr,
            )
            return 1
        print(value)
        return 0

    elif args.secret_action == "delete":
        provider.delete(args.key)
        print(f"secret deleted: {args.key}")
        return 0

    elif args.secret_action == "list":
        keys = provider.list_keys()
        if not keys:
            print("no secrets stored")
        else:
            for key in keys:
                print(f"  {key}")
        return 0

    print("usage: pxeos secret {set|get|delete|list}")
    return 1


def _add_power_parser(
    sub: argparse._SubParsersAction,
) -> None:
    power = sub.add_parser(
        "power", help="BMC power management (IPMI/Redfish)"
    )
    power_sub = power.add_subparsers(dest="power_action")

    p_on = power_sub.add_parser("on", help="power on host")
    p_on.add_argument("mac", help="MAC address")

    p_off = power_sub.add_parser("off", help="power off host")
    p_off.add_argument("mac", help="MAC address")

    p_status = power_sub.add_parser(
        "status", help="query power status"
    )
    p_status.add_argument("mac", help="MAC address")

    p_boot = power_sub.add_parser(
        "set-boot-device", help="set next boot device"
    )
    p_boot.add_argument("mac", help="MAC address")
    p_boot.add_argument(
        "device", choices=["pxe", "disk"],
        help="boot device (pxe or disk)",
    )


def _add_migrate_parser(
    sub: argparse._SubParsersAction,
) -> None:
    migrate = sub.add_parser(
        "migrate", help="migrate from other provisioning systems"
    )
    migrate_sub = migrate.add_subparsers(dest="migrate_action")

    cobbler = migrate_sub.add_parser(
        "from-cobbler", help="import Cobbler export data"
    )
    cobbler.add_argument(
        "export_dir", type=Path,
        help="path to Cobbler export directory",
    )


def _cmd_power(
    args: argparse.Namespace,
    config: PxeOSConfig,
    matcher: HostMatcher,
) -> int:
    from pxeos.power import PowerError, PowerManager

    # Build PowerManager from host rules
    hosts_path = config.data_dir / "hosts.toml"
    rules: List[HostRule] = []
    if hosts_path.exists():
        rules = load_hosts(hosts_path)

    if not args.power_action:
        print(
            "usage: pxeos power {on|off|status|set-boot-device}"
        )
        return 1

    manager = PowerManager()
    for rule in rules:
        if rule.mac and rule.bmc_host and rule.bmc_driver:
            driver = PowerManager.create_driver(
                rule.bmc_driver,
                rule.bmc_host,
                rule.bmc_user or "",
                rule.bmc_password or "",
            )
            manager.register(rule.mac, driver)

    mac = args.mac

    try:
        if args.power_action == "on":
            result = manager.power_on(mac)
            print(f"power on: {result}")
            return 0
        elif args.power_action == "off":
            result = manager.power_off(mac)
            print(f"power off: {result}")
            return 0
        elif args.power_action == "status":
            status = manager.power_status(mac)
            print(f"power status: {status}")
            return 0
        elif args.power_action == "set-boot-device":
            result = manager.set_boot_device(mac, args.device)
            print(f"boot device: {result}")
            return 0
    except PowerError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    return 0


def _cmd_migrate(
    args: argparse.Namespace,
    config: PxeOSConfig,
    registry: PluginRegistry,
) -> int:
    if args.migrate_action == "from-cobbler":
        from pxeos.cobbler_import import import_cobbler_data

        report = import_cobbler_data(
            args.export_dir, registry, config.data_dir,
        )

        print(f"distros imported:  {report.distros_imported}")
        print(f"profiles imported: {report.profiles_imported}")
        print(f"systems imported:  {report.systems_imported}")

        if report.warnings:
            print("\nwarnings:")
            for w in report.warnings:
                print(f"  - {w}")

        if report.errors:
            print("\nerrors:")
            for e in report.errors:
                print(f"  - {e}")
            return 1

        return 0

    print("usage: pxeos migrate {from-cobbler}")
    return 1


def _add_service_parser(
    sub: argparse._SubParsersAction,
) -> None:
    svc = sub.add_parser(
        "service", help="service discovery and info"
    )
    svc_sub = svc.add_subparsers(dest="service_action")

    svc_sub.add_parser(
        "info",
        help="show service info (URL, version, auth, endpoints)",
    )

    svc_sub.add_parser(
        "register",
        help="register with mDNS (requires zeroconf)",
    )


def _cmd_service(
    args: argparse.Namespace,
    config: PxeOSConfig,
) -> int:
    from pxeos.discovery import get_service_info, register_mdns

    if args.service_action == "info":
        info = get_service_info(
            host=config.server_host,
            port=config.server_port,
            auth_enabled=config.auth_enabled,
            tls_enabled=config.tls_cert is not None,
        )
        print(f"service:  {info['service']}")
        print(f"version:  {info['version']}")
        print(f"host:     {info['host']}")
        print(f"port:     {info['port']}")
        print(f"base_url: {info['base_url']}")
        print(f"api_base: {info['api_base']}")
        print(f"auth:     {info['auth_enabled']}")
        print(f"tls:      {info['tls_enabled']}")
        print("endpoints:")
        for ep in info["endpoints"]:
            print(f"  {ep}")
        return 0

    elif args.service_action == "register":
        zc = register_mdns(
            host=config.server_host,
            port=config.server_port,
            service_name=config.service_name,
            auth_enabled=config.auth_enabled,
        )
        if zc is None:
            print(
                "error: mDNS registration failed "
                "(is zeroconf installed?)",
                file=sys.stderr,
            )
            return 1
        print(
            f"registered mDNS service "
            f"'{config.service_name}' on port {config.server_port}"
        )
        return 0

    print("usage: pxeos service {info|register}")
    return 1


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = _build_parser()

    if argcomplete is not None:
        argcomplete.autocomplete(parser)

    args = parser.parse_args(argv)

    # Initialize logging before anything else
    from pxeos.logging_config import setup_logging

    setup_logging(
        level=getattr(args, "log_level", "INFO"),
        json_format=getattr(args, "log_json", False),
    )

    if not args.command:
        parser.print_help()
        return 1

    # Distro mnemonic subcommands don't need config;
    # named-distro CRUD subcommands do.  Let _cmd_distro
    # handle both -- pass config when available.
    if args.command == "distro":
        action = getattr(args, "distro_action", None)
        if action in ("add", "list", "show", "delete"):
            config, registry, matcher = _init_stack(
                args.config
            )
            return _cmd_distro(args, config)
        return _cmd_distro(args)

    config, registry, matcher = _init_stack(args.config)

    if args.command == "server":
        return _cmd_server(args, config, registry, matcher)
    elif args.command == "import":
        return _cmd_import(args, config, registry)
    elif args.command == "provision":
        return _cmd_provision(
            args, config, registry, matcher
        )
    elif args.command == "profile":
        return _cmd_profile(args, config)
    elif args.command == "host":
        return _cmd_host(args, config)
    elif args.command == "client":
        return _cmd_client(
            args, config, registry, matcher
        )
    elif args.command == "cloud-init":
        return _cmd_cloud_init(args)
    elif args.command == "secret":
        return _cmd_secret(args, config)
    elif args.command == "named-host":
        return _cmd_named_host(args, config)
    elif args.command == "auth":
        return _cmd_auth(args, config)
    elif args.command == "power":
        return _cmd_power(args, config, matcher)
    elif args.command == "migrate":
        return _cmd_migrate(args, config, registry)
    elif args.command == "service":
        return _cmd_service(args, config)

    parser.print_help()
    return 1


def _add_auth_parser(
    sub: argparse._SubParsersAction,
) -> None:
    auth = sub.add_parser(
        "auth", help="manage API key authentication"
    )
    auth_sub = auth.add_subparsers(dest="auth_action")

    create = auth_sub.add_parser(
        "create-key", help="create a new API key"
    )
    create.add_argument(
        "--name", required=True, help="key name/label"
    )
    create.add_argument(
        "--role",
        default="viewer",
        choices=["viewer", "operator", "admin"],
        help="role to assign (default: viewer)",
    )

    auth_sub.add_parser(
        "list-keys", help="list API keys"
    )

    revoke = auth_sub.add_parser(
        "revoke-key", help="disable an API key"
    )
    revoke.add_argument("name", help="key name to revoke")

    delete = auth_sub.add_parser(
        "delete-key", help="delete an API key"
    )
    delete.add_argument("name", help="key name to delete")


def _cmd_auth(
    args: argparse.Namespace, config: PxeOSConfig
) -> int:
    from pxeos.auth import ApiKeyStore, Role

    key_store = ApiKeyStore(config.data_dir)

    if args.auth_action == "create-key":
        role = Role(args.role)
        raw_key, api_key = key_store.create_key(
            args.name, role
        )
        print(f"API key created:")
        print(f"  Name: {api_key.name}")
        print(f"  Role: {api_key.role.value}")
        print(f"  Key:  {raw_key}")
        print()
        print(
            "Save this key -- it cannot be "
            "retrieved later."
        )
        return 0

    elif args.auth_action == "list-keys":
        keys = key_store.list_keys()
        if not keys:
            print("no API keys configured")
            return 0
        fmt = "{:<20s} {:<10s} {:<8s}"
        print(fmt.format("NAME", "ROLE", "ENABLED"))
        print("-" * 40)
        for k in keys:
            print(
                fmt.format(
                    k.name, k.role.value, str(k.enabled)
                )
            )
        return 0

    elif args.auth_action == "revoke-key":
        if key_store.revoke(args.name):
            print(f"revoked API key: {args.name}")
            return 0
        print(f"API key not found: {args.name}")
        return 1

    elif args.auth_action == "delete-key":
        if key_store.delete(args.name):
            print(f"deleted API key: {args.name}")
            return 0
        print(f"API key not found: {args.name}")
        return 1

    print(
        "usage: pxeos auth "
        "{create-key|list-keys|revoke-key|delete-key}"
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
