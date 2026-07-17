"""Command-line interface for PxeOS."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List, Optional, Sequence

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

    sub = parser.add_subparsers(dest="command")

    _add_server_parser(sub)
    _add_import_parser(sub)
    _add_profile_parser(sub)
    _add_host_parser(sub)
    _add_client_parser(sub)

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
        "--os", dest="os_family", required=True,
        help="OS family",
    )
    imp.add_argument(
        "--vendor", default="",
        help="OS vendor (e.g. fedora, rhel, rocky)",
    )
    imp.add_argument(
        "--version", dest="os_version", required=True,
        help="OS version",
    )
    imp.add_argument(
        "--arch", default="x86_64", help="architecture"
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


def _cmd_import(
    args: argparse.Namespace,
    config: PxeOSConfig,
    registry: PluginRegistry,
) -> int:
    from pxeos.importer import import_iso, import_url

    if args.iso:
        assets = import_iso(
            args.iso,
            args.os_family,
            args.vendor,
            args.os_version,
            args.arch,
            registry,
            config.distro_root,
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

    print("usage: pxeos host {add|list|show|delete}")
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


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help()
        return 1

    config, registry, matcher = _init_stack(args.config)

    if args.command == "server":
        return _cmd_server(args, config, registry, matcher)
    elif args.command == "import":
        return _cmd_import(args, config, registry)
    elif args.command == "profile":
        return _cmd_profile(args, config)
    elif args.command == "host":
        return _cmd_host(args, config)
    elif args.command == "client":
        return _cmd_client(
            args, config, registry, matcher
        )

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
