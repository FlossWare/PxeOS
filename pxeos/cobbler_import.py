"""Import Cobbler JSON/YAML exports into PxeOS configuration."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from pxeos.models import HostRule, ProvisionProfile
from pxeos.registry import PluginRegistry

try:
    import yaml
except ImportError:
    yaml = None  # type: ignore[assignment]


@dataclass
class ImportedDistro:
    """A distro imported from Cobbler."""
    name: str
    os_family: str
    os_version: str
    arch: str = "x86_64"
    kernel: str = ""
    initrd: str = ""
    breed: str = ""
    comment: str = ""


@dataclass
class ImportedProfile:
    """A profile imported from Cobbler."""
    name: str
    distro: str
    kickstart: str = ""
    kernel_options: str = ""
    comment: str = ""


@dataclass
class ImportedSystem:
    """A system imported from Cobbler."""
    name: str
    profile: str
    mac: str = ""
    hostname: str = ""
    ip_address: str = ""
    gateway: str = ""
    netmask: str = ""
    comment: str = ""


@dataclass
class ImportReport:
    """Summary of a Cobbler import operation."""
    distros_imported: int = 0
    profiles_imported: int = 0
    systems_imported: int = 0
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    distros: List[ImportedDistro] = field(default_factory=list)
    profiles: List[ImportedProfile] = field(default_factory=list)
    systems: List[ImportedSystem] = field(default_factory=list)


def _load_json_or_yaml(path: Path) -> Any:
    """Load a JSON or YAML file."""
    content = path.read_text()

    # Try JSON first
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass

    # Try YAML
    if yaml is not None:
        try:
            return yaml.safe_load(content)
        except Exception:
            pass

    raise ValueError(f"Cannot parse {path} as JSON or YAML")


def _find_data_file(
    export_dir: Path, name: str
) -> Optional[Path]:
    """Find a data file with .json or .yaml/.yml extension."""
    for ext in (".json", ".yaml", ".yml"):
        candidate = export_dir / f"{name}{ext}"
        if candidate.exists():
            return candidate
    return None


def _guess_os_family(breed: str, name: str) -> str:
    """Map Cobbler breed to PxeOS os_family."""
    breed_lower = breed.lower()
    name_lower = name.lower()

    breed_map = {
        "redhat": "fedora",
        "fedora": "fedora",
        "centos": "fedora",
        "rocky": "fedora",
        "alma": "fedora",
        "debian": "debian",
        "ubuntu": "ubuntu",
        "suse": "suse",
        "opensuse": "suse",
        "freebsd": "freebsd",
        "windows": "windows",
        "arch": "arch",
    }

    for key, family in breed_map.items():
        if key in breed_lower or key in name_lower:
            return family

    return breed_lower or "unknown"


def _guess_os_version(name: str) -> str:
    """Try to extract a version number from a distro name."""
    import re

    # Look for version-like patterns: 40, 9.3, 24.04, etc.
    match = re.search(r'(\d+(?:\.\d+)*)', name)
    if match:
        return match.group(1)
    return "unknown"


def _guess_vendor(breed: str, name: str) -> str:
    """Try to guess vendor from breed or name."""
    name_lower = name.lower()
    vendor_keywords = [
        "rocky", "alma", "centos", "rhel", "fedora",
        "ubuntu", "debian", "suse", "opensuse",
    ]
    for keyword in vendor_keywords:
        if keyword in name_lower:
            return keyword
    return breed.lower() if breed else ""


def parse_distros(data: Any) -> List[ImportedDistro]:
    """Parse Cobbler distro export data."""
    distros: List[ImportedDistro] = []

    if isinstance(data, dict):
        items = list(data.values()) if not any(
            k in data for k in ("name", "breed", "kernel")
        ) else [data]
    elif isinstance(data, list):
        items = data
    else:
        return distros

    for entry in items:
        if not isinstance(entry, dict):
            continue

        name = entry.get("name", "")
        if not name:
            continue

        breed = entry.get("breed", "")
        os_family = _guess_os_family(breed, name)
        os_version = entry.get("os_version", "") or _guess_os_version(name)

        distros.append(ImportedDistro(
            name=name,
            os_family=os_family,
            os_version=os_version,
            arch=entry.get("arch", "x86_64"),
            kernel=entry.get("kernel", ""),
            initrd=entry.get("initrd", ""),
            breed=breed,
            comment=entry.get("comment", ""),
        ))

    return distros


def parse_profiles(data: Any) -> List[ImportedProfile]:
    """Parse Cobbler profile export data."""
    profiles: List[ImportedProfile] = []

    if isinstance(data, dict):
        items = list(data.values()) if not any(
            k in data for k in ("name", "distro", "kickstart")
        ) else [data]
    elif isinstance(data, list):
        items = data
    else:
        return profiles

    for entry in items:
        if not isinstance(entry, dict):
            continue

        name = entry.get("name", "")
        if not name:
            continue

        # Cobbler uses "kickstart" or "autoinstall" for the template path
        kickstart = (
            entry.get("kickstart", "")
            or entry.get("autoinstall", "")
            or entry.get("ks_meta", {}).get("autoinstall", "")
            if isinstance(entry.get("ks_meta"), dict)
            else entry.get("kickstart", "")
        )

        kernel_options = entry.get("kernel_options", "")
        if isinstance(kernel_options, dict):
            kernel_options = " ".join(
                f"{k}={v}" for k, v in kernel_options.items()
            )

        profiles.append(ImportedProfile(
            name=name,
            distro=entry.get("distro", ""),
            kickstart=kickstart if isinstance(kickstart, str) else "",
            kernel_options=kernel_options,
            comment=entry.get("comment", ""),
        ))

    return profiles


def parse_systems(data: Any) -> List[ImportedSystem]:
    """Parse Cobbler system export data."""
    systems: List[ImportedSystem] = []

    if isinstance(data, dict):
        items = list(data.values()) if not any(
            k in data for k in ("name", "profile", "interfaces")
        ) else [data]
    elif isinstance(data, list):
        items = data
    else:
        return systems

    for entry in items:
        if not isinstance(entry, dict):
            continue

        name = entry.get("name", "")
        if not name:
            continue

        # Extract MAC from interfaces if present
        mac = ""
        hostname = entry.get("hostname", "")
        ip_address = ""
        gateway = entry.get("gateway", "")
        netmask = ""

        interfaces = entry.get("interfaces", {})
        if isinstance(interfaces, dict):
            # Take first interface with a MAC
            for iface_name, iface_data in interfaces.items():
                if isinstance(iface_data, dict):
                    iface_mac = iface_data.get("mac_address", "")
                    if iface_mac:
                        mac = iface_mac
                        ip_address = iface_data.get("ip_address", ip_address)
                        netmask = iface_data.get("netmask", netmask)
                        if not hostname:
                            hostname = iface_data.get("dns_name", "")
                        break

        # Fallback: MAC at top level
        if not mac:
            mac = entry.get("mac_address", "")

        systems.append(ImportedSystem(
            name=name,
            profile=entry.get("profile", ""),
            mac=mac,
            hostname=hostname,
            ip_address=ip_address,
            gateway=gateway,
            netmask=netmask,
            comment=entry.get("comment", ""),
        ))

    return systems


def import_cobbler_data(
    export_dir: Path,
    registry: PluginRegistry,
    data_dir: Path,
) -> ImportReport:
    """Import Cobbler exported data (distros, profiles, systems) into PxeOS.

    Args:
        export_dir: Directory containing Cobbler export files
            (distros.json, profiles.json, systems.json or .yaml equivalents)
        registry: PxeOS plugin registry (for OS family validation)
        data_dir: PxeOS data directory to write imported configs

    Returns:
        ImportReport with counts and any errors/warnings
    """
    report = ImportReport()

    if not export_dir.exists():
        report.errors.append(f"export directory does not exist: {export_dir}")
        return report

    # --- Parse distros ---
    distro_file = _find_data_file(export_dir, "distros")
    distro_map: Dict[str, ImportedDistro] = {}
    if distro_file:
        try:
            data = _load_json_or_yaml(distro_file)
            parsed = parse_distros(data)
            for d in parsed:
                distro_map[d.name] = d
                report.distros.append(d)
                report.distros_imported += 1
        except Exception as exc:
            report.errors.append(f"failed to parse {distro_file}: {exc}")
    else:
        report.warnings.append("no distros file found in export directory")

    # --- Parse profiles ---
    profile_file = _find_data_file(export_dir, "profiles")
    profile_map: Dict[str, ImportedProfile] = {}
    if profile_file:
        try:
            data = _load_json_or_yaml(profile_file)
            parsed = parse_profiles(data)
            for p in parsed:
                profile_map[p.name] = p
                report.profiles.append(p)
                report.profiles_imported += 1
        except Exception as exc:
            report.errors.append(f"failed to parse {profile_file}: {exc}")
    else:
        report.warnings.append("no profiles file found in export directory")

    # --- Parse systems ---
    system_file = _find_data_file(export_dir, "systems")
    if system_file:
        try:
            data = _load_json_or_yaml(system_file)
            parsed = parse_systems(data)
            for s in parsed:
                report.systems.append(s)
                report.systems_imported += 1
        except Exception as exc:
            report.errors.append(f"failed to parse {system_file}: {exc}")
    else:
        report.warnings.append("no systems file found in export directory")

    # --- Write PxeOS profiles ---
    profiles_dir = data_dir / "profiles"
    profiles_dir.mkdir(parents=True, exist_ok=True)

    for cobbler_profile in report.profiles:
        distro = distro_map.get(cobbler_profile.distro)
        if distro is None:
            report.warnings.append(
                f"profile {cobbler_profile.name!r} references "
                f"unknown distro {cobbler_profile.distro!r}"
            )
            continue

        # Validate os_family is known
        try:
            registry.get(distro.os_family)
        except ValueError:
            report.warnings.append(
                f"distro {distro.name!r} has unknown os_family "
                f"{distro.os_family!r}; writing profile anyway"
            )

        # Write TOML profile
        profile_path = profiles_dir / f"{cobbler_profile.name}.toml"
        _write_profile_toml(profile_path, cobbler_profile, distro)

    # --- Write host rules ---
    hosts_path = data_dir / "hosts.toml"
    _write_host_rules(hosts_path, report.systems, profile_map, distro_map)

    return report


def _write_profile_toml(
    path: Path,
    profile: ImportedProfile,
    distro: ImportedDistro,
) -> None:
    """Write a PxeOS profile TOML file from Cobbler data."""
    lines = [
        "[profile]",
        f'name = "{profile.name}"',
        f'os_family = "{distro.os_family}"',
        f'os_version = "{distro.os_version}"',
        f'vendor = "{_guess_vendor(distro.breed, distro.name)}"',
        f'arch = "{distro.arch}"',
        'firmware = "bios"',
    ]

    if profile.kickstart:
        lines.append(f'autoinstall_url = "{profile.kickstart}"')

    if profile.comment or distro.comment:
        comment = profile.comment or distro.comment
        lines.append(f'# Cobbler comment: {comment}')

    lines.append("")
    path.write_text("\n".join(lines))


def _write_host_rules(
    path: Path,
    systems: List[ImportedSystem],
    profile_map: Dict[str, ImportedProfile],
    distro_map: Dict[str, ImportedDistro],
) -> None:
    """Write PxeOS host rules from Cobbler systems."""
    lines: List[str] = []

    for system in systems:
        if not system.mac:
            continue

        # Resolve profile -> distro for os_family/version
        cobbler_profile = profile_map.get(system.profile)
        os_family = "unknown"
        os_version = "unknown"

        if cobbler_profile:
            distro = distro_map.get(cobbler_profile.distro)
            if distro:
                os_family = distro.os_family
                os_version = distro.os_version

        lines.append("[[host]]")
        lines.append(f'profile = "{system.profile}"')
        lines.append(f'os_family = "{os_family}"')
        lines.append(f'os_version = "{os_version}"')
        lines.append(f'mac = "{system.mac}"')
        lines.append("priority = 100")
        if system.comment:
            lines.append(f"# Cobbler: {system.comment}")
        lines.append("")

    if lines:
        path.parent.mkdir(parents=True, exist_ok=True)
        # Append to existing hosts file if present
        existing = ""
        if path.exists():
            existing = path.read_text()
            if existing and not existing.endswith("\n"):
                existing += "\n"
        path.write_text(existing + "\n".join(lines))
