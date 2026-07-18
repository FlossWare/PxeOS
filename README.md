# PxeOS

Cross-OS PXE boot provisioning system supporting Linux, BSD, and Windows.

## Overview

PxeOS is a standalone PXE provisioning tool with a plugin architecture that supports automated installation across 10 OS families. Define a profile once, PxeOS renders the correct native autoinstall format for the target OS.

Works standalone for bare-metal provisioning, or as a composable service that [VirtOS](https://github.com/FlossWare/VirtOS) can call for VM provisioning.

## Project Status

PxeOS is **functional but pre-production**. It has 921 unit tests with 68% branch coverage across all 10 OS plugins, but has not yet been validated with real PXE-booting hardware. See the documentation below for full details:

- **[Deployment Guide](docs/DEPLOYMENT.md)** -- Installation, systemd service, firewall rules, SELinux, TLS, and HA
- **[Known Limitations](docs/KNOWN_LIMITATIONS.md)** -- Honest assessment of test coverage gaps and what needs work
- **[Comparison with Other Tools](docs/COMPARISON.md)** -- How PxeOS compares to Cobbler, Foreman, MAAS, and Ironic

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

# Import using mnemonics (short aliases for common distros)
pxeos import --iso Fedora-42-x86_64.iso --distro fedora42
pxeos import --iso rhel-9.4-x86_64-dvd.iso --distro rhel9

# Or use explicit flags
pxeos import --iso Fedora-42-x86_64.iso --os fedora --vendor fedora --version 42

# Import from a mirror URL
pxeos import --url https://download.fedoraproject.org/.../os/ --distro fedora42

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

### Vendor / OS Family Taxonomy

PxeOS uses a two-level taxonomy: **os_family** identifies the autoinstall mechanism (kickstart, preseed, etc.) while **vendor** distinguishes derivatives that share the same mechanism. For example, Fedora, RHEL, Rocky, and AlmaLinux all use Kickstart, so they share `os_family = "fedora"` but differ by vendor.

### Host Matching

Machines are matched to profiles via a priority chain:

```
MAC address → hostname pattern → subnet CIDR → group → OS default → global default
```

```toml
# Match by exact MAC address (highest priority)
[[hosts]]
mac = "aa:bb:cc:dd:ee:f1"
profile = "webserver"
os_family = "fedora"
vendor = "fedora"
os_version = "42"

# Match by hostname glob
[[hosts]]
hostname_pattern = "rhel-*"
profile = "webserver"
os_family = "fedora"
vendor = "rhel"
os_version = "9"

# Match by subnet CIDR
[[hosts]]
subnet = "10.0.5.0/24"
profile = "database"
os_family = "freebsd"
vendor = "freebsd"
os_version = "14.2"

# Match by group (lowest specificity)
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
7. Post-install script calls `POST /api/v1/provision/{mac}/disable-netboot` to prevent re-provisioning on next reboot

### Boot-Once Provisioning

By default, a machine that PXE boots will receive its install script every time. After successful provisioning, disable netboot so the machine boots from local disk on subsequent reboots:

```bash
# Automatically (add to post_scripts in the profile):
curl -X POST https://pxeos:8443/api/v1/provision/aa:bb:cc:dd:ee:f1/disable-netboot

# Manually via CLI (talks to running PxeOS server):
pxeos host disable-netboot aa:bb:cc:dd:ee:f1

# Re-enable for re-provisioning:
pxeos host enable-netboot aa:bb:cc:dd:ee:f1
curl -X POST https://pxeos:8443/api/v1/provision/aa:bb:cc:dd:ee:f1/enable-netboot

# Check current status:
curl https://pxeos:8443/api/v1/provision/aa:bb:cc:dd:ee:f1/netboot-status
```

When netboot is disabled for a MAC, `GET /api/v1/boot/{mac}` returns a minimal iPXE script (`#!ipxe\nexit`) that causes iPXE to fall through to the next boot device (local disk). The host rule and profile remain intact so re-enabling netboot restores the original install flow.

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

## Distro Mnemonics

PxeOS provides shorthand aliases for common distros so you don't have to type `--os`, `--vendor`, and `--version` every time.

```bash
# List all available mnemonics
pxeos distro aliases

# Resolve a mnemonic to see what it maps to
pxeos distro resolve rhel9
# os_family: fedora
# vendor:    rhel
# version:   9
```

Built-in mnemonics include:

| Mnemonic | OS Family | Vendor | Version |
|----------|-----------|--------|---------|
| `fedora42` | fedora | fedora | 42 |
| `rhel9` | fedora | rhel | 9 |
| `rocky9` | fedora | rocky | 9 |
| `deb12`, `bookworm` | debian | debian | 12 |
| `ubuntu2404`, `noble` | ubuntu | ubuntu | 24.04 |
| `sles15` | suse | sles | 15 |
| `fbsd14` | freebsd | freebsd | 14 |
| `obsd76` | openbsd | openbsd | 7.6 |
| `nbsd10` | netbsd | netbsd | 10 |
| `arch` | arch | arch | latest |
| `win11` | windows | windows | 11 |

Unknown mnemonics are parsed automatically if they match a known prefix (e.g. `fedora99` resolves to fedora/fedora/99).

Custom mnemonics can be added in the config file:

```toml
[mnemonics]
myos = { os_family = "custom", vendor = "myvendor", version = "1.0" }
```

The REST API also accepts a `mnemonic` field on import endpoints:

```bash
curl -X POST https://pxeos:8443/api/v1/import/fetch \
  -H "Content-Type: application/json" \
  -d '{"url":"https://mirror.example.com/Fedora-42.iso", "mnemonic":"fedora42"}'
```

## Cloud-Init Config Generation

PxeOS generates cloud-init configs (absorbed from VirtOS `virtos-cloud-init`). Works with any cloud image that supports the NoCloud datasource.

```bash
# Generate cloud-init configs to stdout
pxeos cloud-init generate --name myvm --hostname myvm \
  --user admin --ssh-key ~/.ssh/id_rsa.pub \
  --packages "nginx,git" --network dhcp

# Write configs to a directory
pxeos cloud-init generate --name myvm --hostname myvm \
  --user admin --ssh-key ~/.ssh/id_rsa.pub \
  --output-dir /tmp/myvm-cloud-init/

# Create a config drive ISO (attach to VM as CDROM)
pxeos cloud-init iso --name myvm --hostname myvm \
  --user admin --ssh-key ~/.ssh/id_rsa.pub \
  --packages "nginx,certbot" --network static \
  --ip 10.0.0.50/24 --gateway 10.0.0.1 --dns 8.8.8.8 \
  -o /tmp/myvm-cloud-init.iso
```

Generates three files:
- **user-data**: `#cloud-config` YAML (hostname, users, SSH keys, packages, runcmd)
- **meta-data**: instance-id and local-hostname
- **network-config**: Netplan v2 format (DHCP or static)

### Bare-Metal Cloud-Init Provisioning

Cloud-init works on bare metal via the NoCloud datasource. Register configs on PxeOS, then point the PXE-booted installer at PxeOS's HTTP endpoints:

```bash
# 1. Register cloud-init configs for a machine
curl -X POST https://pxeos:8443/api/v1/cloud-init/register \
  -H "Content-Type: application/json" \
  -d '{"name":"web01","hostname":"web01.lab","user":"admin",
       "ssh_authorized_keys":["ssh-ed25519 AAAA..."],
       "packages":["nginx","certbot"]}'

# 2. PXE boot the machine with NoCloud kernel args pointing at PxeOS.
#    The trailing slash is required — NoCloud treats the URL as a directory
#    and appends user-data, meta-data, network-config to fetch each file.
#    ds=nocloud-net;s=https://pxeos:8443/api/v1/cloud-init/web01-/
#
# The installer fetches user-data, meta-data, and network-config
# from PxeOS during boot and applies them automatically.

# Or create a config drive ISO and attach it (VM or USB for bare metal):
pxeos cloud-init iso --name web01 --hostname web01.lab \
  --user admin --ssh-key ~/.ssh/id_rsa.pub -o web01-cidata.iso
```

## Remote ISO Import

Import ISOs to the PxeOS server remotely via the REST API:

```bash
# Upload an ISO to the server
curl -X POST https://pxeos:8443/api/v1/import/upload \
  -F "file=@Fedora-42-x86_64.iso" \
  -F "os_family=fedora" -F "vendor=fedora" \
  -F "os_version=42" -F "arch=x86_64"

# Tell the server to fetch an ISO from a URL
curl -X POST https://pxeos:8443/api/v1/import/fetch \
  -H "Content-Type: application/json" \
  -d '{"url":"https://download.fedoraproject.org/.../Fedora-42.iso",
       "os_family":"fedora","vendor":"fedora","os_version":"42"}'
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
| `POST` | `/api/v1/cloud-init/generate` | Generate cloud-init configs |
| `POST` | `/api/v1/cloud-init/iso` | Generate config drive ISO |
| `POST` | `/api/v1/cloud-init/register` | Register configs for HTTP serving |
| `GET` | `/api/v1/cloud-init/{id}/user-data` | Serve registered user-data |
| `GET` | `/api/v1/cloud-init/{id}/meta-data` | Serve registered meta-data |
| `POST` | `/api/v1/import/upload` | Upload ISO (multipart) |
| `POST` | `/api/v1/import/fetch` | Fetch ISO from URL |
| `POST` | `/api/v1/provision/{mac}/disable-netboot` | Disable PXE boot (boot-once) |
| `POST` | `/api/v1/provision/{mac}/enable-netboot` | Re-enable PXE boot |
| `GET` | `/api/v1/provision/{mac}/netboot-status` | Check netboot status |

## Configuration

Server settings are stored in a TOML config file (default: `/etc/pxeos/pxeos.toml`):

```toml
[server]
host = "0.0.0.0"
port = 8443
# tls_cert = "/etc/pxeos/tls/cert.pem"
# tls_key = "/etc/pxeos/tls/key.pem"

[paths]
tftp_root = "/srv/tftp"
distro_root = "/srv/pxeos/distros"
data_dir = "/etc/pxeos"

[mnemonics]
# Custom distro aliases (in addition to built-ins)
myrhel = { os_family = "fedora", vendor = "rhel", version = "9" }
```

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

- VirtOS can proxy PxeOS endpoints through its API gateway
- VirtOS can trigger PXE provisioning via YAML descriptors
- No circular dependency: PxeOS never depends on VirtOS

## System Requirements

| Resource | Minimum | Recommended |
|----------|---------|-------------|
| CPU | 1 vCPU | 2-4 vCPUs |
| RAM | 512 MB | 2-4 GB |
| Disk | 20 GB + ISO storage | 100 GB+ (SSD recommended) |
| Network | 100 Mbps | 1 Gbps |
| Python | 3.9+ | 3.11+ |

**Disk planning:** Each imported distro stores extracted kernel + initrd files (~50-200 MB per distro). Full ISOs are not retained after import. Budget approximately `(number of distros) × 200 MB` for the distro store, plus working space for config drive ISO generation.

**Network:** Network throughput is the primary bottleneck during PXE boot. A 1 Gbps link prevents boot timeouts when provisioning multiple machines concurrently. For 10+ simultaneous boots, consider dedicated NICs or network bonding.

**Optional tools:** `genisoimage`, `mkisofs`, or `xorriso` for cloud-init config drive ISO creation.

**Runs on:** Any Linux or BSD system with Python 3.9+. Tested on Fedora, RHEL, Debian, and Ubuntu. Raspberry Pi 4 (4 GB) is sufficient for small lab environments.

## Security Considerations

### Post-install scripts run as root

- `post_scripts` entries are injected verbatim into autoinstall configs (Kickstart `%post`, Preseed `late_command`, AutoYaST `<post-scripts>`, cloud-init `runcmd`, bsdinstall shell)
- They execute as **root** on the target machine during installation with no sandboxing
- Never put untrusted or unreviewed commands in `post_scripts` -- treat them like sudoers entries
- Audit all post_scripts before deploying a profile to production hosts

### Transport security

- Autoinstall configs (including post_scripts) are served over HTTP by default
- An attacker on the network can intercept or modify configs in transit
- **Enable TLS** (`tls_cert` / `tls_key` in `pxeos.toml`) for all production deployments
- iPXE boot scripts (`/api/v1/boot/{mac}`) are equally sensitive -- they control which kernel a machine boots

### Network exposure

- PxeOS serves boot configs to **any PXE client** that can reach it on the network
- There is no authentication on boot or autoinstall endpoints (PXE clients cannot authenticate)
- Restrict access to the provisioning VLAN using firewall rules:
  ```bash
  # Example: only allow the provisioning subnet
  iptables -A INPUT -p tcp --dport 8443 -s 10.0.5.0/24 -j ACCEPT
  iptables -A INPUT -p tcp --dport 8443 -j DROP
  ```
- Do not expose PxeOS to the public internet or untrusted networks

### Password handling

- Passwords in profiles (`rootpw_hash`, `user_password_hash`) must be SHA-512 hashed -- never store plaintext
- Generate hashes with: `python3 -c "import crypt; print(crypt.crypt('password', crypt.mksalt(crypt.METHOD_SHA512)))"`
- Hashes are embedded in rendered autoinstall configs -- see transport security above

### Secrets in profiles

- Profiles may contain sensitive data: password hashes, SSH private keys, registration keys, API tokens
- These are stored in PxeOS's config files and served to any machine that PXE boots
- See [issue #10](https://github.com/FlossWare/PxeOS/issues/10) for planned secrets management improvements

### ISO import

- `pxeos import` mounts ISOs and extracts kernel/initrd files
- Only import ISOs from trusted sources -- a malicious ISO can supply a compromised kernel
- Verify ISO checksums before import (GPG signatures where available)
- The `import/fetch` REST endpoint downloads ISOs from arbitrary URLs -- restrict API access accordingly

## Production Readiness

PxeOS is an **alpha-stage** project (see `pyproject.toml` classifier). Before using in production, be aware of:

**What works (tested):**
- Autoinstall config generation for all 10 OS families (921 unit tests)
- Plugin discovery and loading via setuptools entry points
- Host matching (MAC, hostname, subnet, group priority chain)
- Boot-once provisioning (disable/enable netboot)
- Cloud-init config generation (user-data, meta-data, network-config)
- REST API endpoints (FastAPI with OpenAPI documentation)
- API key authentication and RBAC

**What has NOT been tested:**
- Actual PXE boot on real or virtual hardware
- TFTP file serving with real TFTP clients
- Integration with real DHCP servers
- TLS termination with real certificates
- Concurrent provisioning under load
- Long-running stability

**What is missing:**
- IPMI/BMC power management ([#29](https://github.com/FlossWare/PxeOS/issues/29))
- Cobbler migration tool ([#30](https://github.com/FlossWare/PxeOS/issues/30))
- Built-in DHCP/DNS management
- Configuration management integration (Puppet/Ansible)
- Database backend (currently file-based)

For full details, see [Known Limitations](docs/KNOWN_LIMITATIONS.md) and [Comparison](docs/COMPARISON.md).

## Deployment

See the [Deployment Guide](docs/DEPLOYMENT.md) for:
- Installation and configuration
- Systemd service setup (`contrib/pxeos.service`)
- Firewall rules (`contrib/pxeos.firewalld.xml`)
- SELinux and AppArmor notes
- TLS configuration
- DHCP server setup (dnsmasq / ISC DHCP)
- Backup and high availability
- Troubleshooting

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

## Shell Completion

Install with completion support and activate:

```bash
pip install pxeos[completion]
eval "$(register-python-argcomplete pxeos)"
```

For permanent activation, add the eval line to your `~/.bashrc` or `~/.zshrc`.

## FlossWare Standards

- X.Y versioning (no patch numbers)
- GPLv3 license
- 82% minimum test coverage
- Ruff + Black + MyPy quality gates
- CI/CD via GitHub Actions

## License

GNU General Public License v3.0 - see [LICENSE](LICENSE) for details.
