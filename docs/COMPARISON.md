# PxeOS vs Other PXE Provisioning Tools

Honest comparison of PxeOS against established provisioning tools. PxeOS is a younger project with broader OS family coverage but less production validation than the alternatives.

## Quick Comparison

| Feature | PxeOS | Cobbler | Foreman | MAAS | Ironic |
|---------|-------|---------|---------|------|--------|
| **OS families** | 10 (Linux, BSD, Windows) | Linux + ESXi | Linux (Red Hat, Debian, SUSE) | Ubuntu-focused + others | Linux |
| **Plugin architecture** | Yes (OSPlugin ABC) | Template-based | Provisioning templates | Curtin preseed | Deploy drivers |
| **REST API** | FastAPI + OpenAPI | XML-RPC (legacy) + REST | Full REST (Hammer CLI) | Full REST | Full REST (OpenStack) |
| **Web UI** | Basic Flask dashboard | Yes (Django Cobbler-web) | Full-featured (Rails) | Full-featured (React) | Horizon (OpenStack) |
| **RBAC** | API key + roles | Basic (users/groups) | Full LDAP/AD/Kerberos | RBAC with MAAS auth | Keystone (OpenStack IAM) |
| **Cloud-init** | Yes (NoCloud datasource) | Yes (configdrive) | Yes | Core feature | Yes (configdrive) |
| **IPMI/BMC control** | No (planned, [#29]) | Yes (power management) | Yes (smart proxy) | Yes (core feature) | Core feature |
| **Live ISO boot** | Yes | No | No | No | No |
| **DHCP management** | External (dnsmasq/ISC) | Built-in (ISC DHCP/dnsmasq) | External (smart proxy) | Built-in | External (Neutron) |
| **DNS management** | No | Yes (BIND) | External (smart proxy) | Built-in | No |
| **PXE boot modes** | BIOS + UEFI | BIOS + UEFI | BIOS + UEFI | BIOS + UEFI | BIOS + UEFI |
| **Configuration mgmt** | None (profiles only) | Puppet/Ansible integration | Puppet/Ansible/Salt/Chef | Juju/Ansible | None |
| **Bare metal discovery** | No | No | Yes (discovery plugin) | Yes (enlistment) | Yes (introspection) |
| **Multi-tenant** | No | No | Yes (organizations) | No | Yes (OpenStack projects) |
| **Cobbler migration** | No (planned, [#30]) | N/A | Importer available | No | No |
| **License** | GPL-3.0 | GPL-2.0 | GPL-3.0 | AGPL-3.0 | Apache-2.0 |
| **Production maturity** | Pre-production | Mature (15+ years) | Mature (10+ years) | Mature (10+ years) | Mature (10+ years) |
| **Language** | Python | Python | Ruby (Rails) | Python (Django) + Go | Python |
| **Min resources** | 512 MB RAM, 1 vCPU | 2 GB RAM, 2 vCPUs | 4 GB RAM, 2 vCPUs | 8 GB RAM, 2 vCPUs | OpenStack deployment |

[#29]: https://github.com/FlossWare/PxeOS/issues/29
[#30]: https://github.com/FlossWare/PxeOS/issues/30

## Detailed Comparison

### PxeOS

**What it does well:**
- Broadest OS family support (10 families including 4 BSDs and Windows)
- Lightweight -- runs on a Raspberry Pi 4
- Clean plugin architecture (add an OS family by implementing one Python ABC)
- Modern Python stack (FastAPI, Pydantic, type hints)
- Cloud-init generation for both VMs and bare metal
- Live ISO PXE boot support
- Distro mnemonics for quick setup
- Boot-once provisioning (auto-disable netboot after install)
- 921 unit tests, CI on 4 Python versions

**What it lacks:**
- No real-world PXE boot validation (see [KNOWN_LIMITATIONS.md](KNOWN_LIMITATIONS.md))
- No IPMI/BMC power management (cannot remotely power on machines)
- No built-in DHCP/DNS (requires external dnsmasq or ISC DHCP)
- No configuration management integration
- No bare metal discovery
- No multi-tenant support
- Basic web UI (dashboard only, not full management)
- Small community (single-developer project)
- Pre-production maturity

**Best for:** Lab environments, multi-OS provisioning, users who want BSD/Windows PXE boot support, lightweight deployments, integration with VirtOS.

### Cobbler

[Cobbler](https://cobbler.github.io/) is the most direct competitor and the longest-running open-source PXE provisioning tool.

**What it does well:**
- Mature and battle-tested (since ~2006)
- Built-in DHCP and DNS management
- Power management (IPMI, iLO, DRAC, virsh)
- Puppet/Ansible integration for post-install configuration
- ISO import and repository mirroring
- Template-based config generation (Cheetah/Jinja2)
- Cobbler-web Django UI
- Large community and extensive documentation

**What it lacks:**
- No native BSD support (Linux + VMware ESXi only)
- No Windows support (possible with custom templates but not officially supported)
- Legacy XML-RPC API (REST API added later)
- No cloud-init generation
- No live ISO boot support
- Cheetah templating legacy (migrating to Jinja2)

**Best for:** Linux-only data centers, environments needing built-in DHCP/DNS, Puppet/Ansible shops, users who want a proven, mature tool.

**Migration from Cobbler:** Planned ([#30](https://github.com/FlossWare/PxeOS/issues/30)) but not yet implemented. Cobbler stores profiles and systems in a flat-file or MongoDB database; a migration tool would need to translate Cobbler profiles to PxeOS profiles and re-import distro kernels.

### Foreman (with Katello)

[Foreman](https://theforeman.org/) is a complete lifecycle management tool, not just a provisioning tool.

**What it does well:**
- Full lifecycle management (provisioning, configuration, patching)
- Multi-tenant with organizations and locations
- Deep Red Hat ecosystem integration (Satellite is Foreman + Katello)
- Puppet/Ansible/Salt/Chef integration
- Bare metal discovery
- Comprehensive RBAC with LDAP/AD/Kerberos
- Full-featured Rails web UI
- Large community and commercial support (Red Hat Satellite)
- Content management (Katello) for repository management and patching

**What it lacks:**
- Heavy resource requirements (4+ GB RAM minimum)
- Complex installation and maintenance
- Ruby/Rails stack can be harder to extend for Python shops
- No native BSD or Windows PXE support
- No live ISO boot
- Steep learning curve

**Best for:** Enterprise Linux environments, Red Hat shops (via Satellite), organizations needing full lifecycle management, environments with complex RBAC requirements.

### MAAS (Canonical)

[MAAS](https://maas.io/) (Metal as a Service) treats bare metal like cloud instances.

**What it does well:**
- Cloud-like API for bare metal (allocate, deploy, release)
- Built-in DHCP, DNS, and NTP
- Machine discovery and enlistment
- Hardware testing before deployment
- Network fabric management (VLANs, subnets, spaces)
- Composable hardware support (Intel RSD, Virsh)
- KVM pod management
- Juju integration for application deployment
- Full-featured React web UI

**What it lacks:**
- Ubuntu-focused (other Linux distros supported but less tested)
- No BSD or Windows support
- No live ISO boot
- Requires PostgreSQL + MAAS region/rack controller architecture
- Heavier resource requirements (8+ GB RAM recommended)
- Canonical-centric ecosystem

**Best for:** Ubuntu-heavy environments, cloud-like bare metal management, environments needing hardware testing and discovery, Juju users.

### Ironic (OpenStack)

[Ironic](https://docs.openstack.org/ironic/) is OpenStack's bare metal provisioning service.

**What it does well:**
- Treats bare metal as an OpenStack resource (like Nova instances)
- Deep integration with OpenStack services (Neutron, Glance, Keystone)
- Hardware introspection (auto-detect hardware specs)
- Multiple deploy drivers (PXE, iPXE, virtual media, Redfish)
- Multi-tenant via OpenStack projects
- Cleaning and inspection workflows
- BIOS/UEFI configuration management
- Firmware updates
- Standalone mode (without full OpenStack)

**What it lacks:**
- Designed for OpenStack -- standalone mode is an afterthought
- Complex deployment (even standalone requires several services)
- Linux-only provisioning
- No BSD or Windows support
- No live ISO boot
- Steep learning curve
- Heavyweight (requires Keystone, Glance, at minimum)

**Best for:** OpenStack environments, large-scale cloud infrastructure, environments needing hardware introspection and firmware management.

## Decision Guide

| If you need... | Consider |
|----------------|----------|
| Multi-OS (Linux + BSD + Windows) provisioning | **PxeOS** (only option with all three) |
| Battle-tested Linux provisioning | **Cobbler** (15+ years of production use) |
| Full lifecycle management | **Foreman** (provisioning + config + patching) |
| Cloud-like bare metal management | **MAAS** (allocate/deploy/release API) |
| OpenStack integration | **Ironic** (native OpenStack service) |
| Lightweight lab setup | **PxeOS** (runs on Raspberry Pi, minimal deps) |
| Built-in DHCP/DNS | **Cobbler** or **MAAS** (PxeOS requires external) |
| IPMI/BMC power management | **Cobbler**, **Foreman**, **MAAS**, or **Ironic** (PxeOS: planned) |
| Live ISO PXE boot | **PxeOS** (unique feature) |
| Enterprise/production deployment | **Foreman** or **MAAS** (mature, supported) |
| VirtOS integration | **PxeOS** (designed for it) |

## Maturity Comparison

It is important to be transparent: PxeOS is a pre-production project. The comparison above reflects feature parity, not production readiness.

| Aspect | PxeOS | Cobbler | Foreman | MAAS | Ironic |
|--------|-------|---------|---------|------|--------|
| First release | 2025 | ~2006 | ~2009 | ~2012 | ~2013 |
| Production deployments | 0 known | Thousands | Thousands (+ Satellite) | Thousands | Thousands |
| Commercial support | No | Community | Red Hat (Satellite) | Canonical | Multiple vendors |
| CVE history | None (new project) | Several (addressed) | Several (addressed) | Several (addressed) | Several (addressed) |
| Community size | 1 developer | Small-medium | Large | Medium | Large (OpenStack) |
| Package availability | pip only | RPM, DEB, pip | RPM, DEB | Snap, DEB | RPM, DEB, pip |

See [KNOWN_LIMITATIONS.md](KNOWN_LIMITATIONS.md) for a detailed assessment of what PxeOS has and has not validated.
