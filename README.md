# PxeOS

Cross-OS PXE boot provisioning system supporting Linux, BSD, and Windows.

## Overview

PxeOS is a standalone PXE provisioning tool with a plugin architecture that supports automated installation across 9 OS families. Define a profile once, PxeOS renders the correct native autoinstall format for the target OS.

Works standalone for bare-metal provisioning, or as a composable service that [VirtOS](https://github.com/FlossWare/VirtOS) can call for VM provisioning.

## Supported OS Families

| OS Family | Autoinstall Mechanism | Config File |
|-----------|----------------------|-------------|
| Fedora / RHEL / CentOS | Kickstart | `ks.cfg` |
| Debian | Preseed | `preseed.cfg` |
| Ubuntu (22.04+) | Cloud-Init Autoinstall | `user-data` |
| SUSE / openSUSE | AutoYaST | `autoinst.xml` |
| FreeBSD | bsdinstall | `installerconfig` |
| OpenBSD | autoinstall(8) | `install.conf` |
| NetBSD | sysinst | `auto_install.cfg` |
| Arch Linux | archinstall | `user_configuration.json` |
| Windows | Unattended Install | `unattend.xml` |

## Quick Start

```bash
pip install pxeos

# Import an OS ISO (vendor distinguishes e.g. fedora vs rhel vs rocky within the same os family)
pxeos import --iso Fedora-42-x86_64.iso --os fedora --vendor fedora --version 42
pxeos import --iso rhel-9.4-x86_64-dvd.iso --os fedora --vendor rhel --version 9

# Import from a mirror URL
pxeos import --url https://download.fedoraproject.org/.../os/ --os fedora --vendor fedora --version 42

# Start the server
pxeos server start --config /etc/pxeos/pxeos.toml

# Register a host
pxeos host add --mac aa:bb:cc:dd:ee:f1 --profile webserver --os fedora --vendor fedora --version 42

# List profiles
pxeos profile list
```

## Architecture

```
CLI (argparse) / REST API (FastAPI)
         │
    Provisioning Engine
         │
    ┌────┴────┐
    │ Plugin  │ ← OS Plugin Registry (entry_points discovery)
    │ Registry│
    └────┬────┘
         │
    ┌────┴──────────────────────────────────────────┐
    │  fedora │ debian │ ubuntu │ suse │ freebsd │  │
    │  openbsd│ netbsd │ arch   │ windows           │
    └───────────────────────────────────────────────┘
         │
    Jinja2 Templates → OS-native configs
```

### Host Matching

Machines are matched to profiles via a priority chain:

```
MAC address → hostname pattern → subnet CIDR → group → OS default → global default
```

```toml
# Example host configuration
[[hosts]]
mac = "aa:bb:cc:dd:ee:f1"
profile = "webserver"
os_family = "fedora"
vendor = "fedora"
os_version = "42"

[[hosts]]
hostname_pattern = "rhel-*"
profile = "webserver"
os_family = "fedora"
vendor = "rhel"
os_version = "9"

[[hosts]]
hostname_pattern = "db-*"
profile = "database"
os_family = "freebsd"
vendor = "freebsd"
os_version = "14.2"

[[hosts]]
group = "lab"
profile = "minimal"
os_family = "debian"
vendor = "debian"
os_version = "12"
```

### PXE Boot Flow

1. Machine PXE boots, DHCP points to iPXE
2. iPXE fetches boot script from PxeOS: `GET /api/v1/boot/{mac}`
3. PxeOS matches MAC to profile, returns iPXE script with kernel/initrd
4. Machine boots installer kernel
5. Installer fetches autoinstall config from PxeOS: `GET /api/v1/autoinstall/{mac}`
6. Automated installation proceeds

### ISO Import

```bash
# Linux ISOs (os family + vendor + version)
pxeos import --iso Fedora-42-x86_64.iso --os fedora --vendor fedora --version 42
pxeos import --iso rhel-9.4-x86_64-dvd.iso --os fedora --vendor rhel --version 9
pxeos import --iso Rocky-9.4-x86_64-dvd.iso --os fedora --vendor rocky --version 9
pxeos import --iso debian-12-amd64-netinst.iso --os debian --vendor debian --version 12
pxeos import --iso ubuntu-24.04-live-server-amd64.iso --os ubuntu --vendor ubuntu --version 24.04

# BSD ISOs
pxeos import --iso FreeBSD-14.2-RELEASE-amd64-disc1.iso --os freebsd --vendor freebsd --version 14.2
pxeos import --iso install76.iso --os openbsd --vendor openbsd --version 7.6

# Windows ISOs
pxeos import --iso Win11_24H2_English_x64.iso --os windows --vendor windows --version 11
```

## REST API

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/v1/boot/{mac}` | iPXE boot script for MAC |
| `GET` | `/api/v1/autoinstall/{mac}` | Rendered autoinstall config |
| `GET` | `/api/v1/profiles` | List all profiles |
| `GET` | `/api/v1/distros` | List imported distros |
| `POST` | `/api/v1/hosts` | Register a host |
| `GET` | `/api/v1/health` | Health check |

## Plugin Architecture

PxeOS uses setuptools entry points for plugin discovery. To add support for a new OS:

```python
from pxeos.plugins.base import OSPlugin

class MyOSPlugin(OSPlugin):
    @property
    def os_family(self) -> str:
        return "myos"

    def generate_autoinstall(self, profile):
        return self._render_template("myos.j2", {...})

    # ... implement remaining abstract methods
```

Register in `pyproject.toml`:
```toml
[project.entry-points."pxeos.plugins"]
myos = "my_package.plugin:MyOSPlugin"
```

## VirtOS Integration

PxeOS works standalone or as a service consumed by VirtOS:

- VirtOS can proxy PxeOS endpoints through `virtos-api` ([#1](https://github.com/FlossWare/PxeOS/issues/1))
- VirtOS `platform-java` can trigger PXE provisioning via YAML descriptors ([#2](https://github.com/FlossWare/PxeOS/issues/2))
- No circular dependency: PxeOS never depends on VirtOS

## Development

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Lint
ruff check pxeos/

# Type check
mypy pxeos/

# Format
black pxeos/ tests/
```

## FlossWare Standards

- X.Y versioning (no patch numbers)
- GPLv3 license
- 82% minimum test coverage
- Ruff + Black + MyPy quality gates
- CI/CD via GitHub Actions

## License

GNU General Public License v3.0 - see [LICENSE](LICENSE) for details.
