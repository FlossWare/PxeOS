# Known Limitations

Honest assessment of PxeOS project maturity, test coverage, and known gaps.

**Project status:** Functional but pre-production. PxeOS has not been validated against real PXE-booting hardware.

## What IS Tested

PxeOS has **921 unit tests** across 27 test files with **68% branch coverage** (50% minimum enforced by CI). Tests run on Python 3.9, 3.10, 3.11, and 3.12 via GitHub Actions.

### Test coverage by area

| Area | Tests | Coverage | What is validated |
|------|-------|----------|-------------------|
| OS plugins (10 families) | 244 | 63-98% | Template rendering, config generation, parameter handling |
| ISO detection | 88 | Partial | Filename parsing, distro identification patterns |
| Authentication / RBAC | 83 | High | API key validation, role-based access, token lifecycle |
| Named objects (profiles, hosts) | 64 | High | CRUD operations, serialization, validation |
| Secrets management | 55 | 96% | Encryption, storage, retrieval, rotation |
| Live ISO boot | 50 | Partial | Boot script generation for live media |
| Cloud-init generation | 50 | Partial | user-data, meta-data, network-config rendering |
| State management | 44 | Partial | Netboot enable/disable, host state tracking |
| Distro mnemonics | 38 | Partial | Alias resolution, auto-parsing, custom mnemonics |
| Web UI routes | 34 | 49% | Dashboard rendering, form handling |
| Boot-once provisioning | 29 | Partial | Disable/enable netboot, iPXE exit script |
| REST API | 27 | Partial | Endpoint routing, request/response validation |
| Host matching | 21 | Partial | MAC, hostname, subnet, group matching priority |
| CLI | 20 | Partial | Argument parsing, subcommand dispatch |
| Models | 19 | Partial | Data model validation, serialization |
| Plugin registry | 15 | 86% | Entry point discovery, plugin loading |
| Importer | 14 | Partial | ISO mount, kernel/initrd extraction |
| Engine | 11 | Partial | Provisioning orchestration |

### What the tests prove

- Template rendering produces syntactically plausible autoinstall configs for all 10 OS families
- The plugin architecture correctly discovers and loads OS plugins
- Host matching priority chain works as documented (MAC > hostname > subnet > group)
- Boot-once flow correctly toggles netboot state
- API endpoints accept valid requests and reject malformed ones
- Authentication gates protected endpoints when enabled

## What IS NOT Tested

### No real hardware PXE boot validation

The most significant gap: **no test has ever booted a physical or virtual machine via PXE using PxeOS**. All testing validates that the software produces correct-looking output, not that the output actually works end-to-end.

What this means:
- Generated Kickstart files have not been consumed by Anaconda
- Generated Preseed files have not been consumed by debian-installer
- Generated Unattend.xml files have not been consumed by Windows Setup
- Generated bsdinstall configs have not been consumed by FreeBSD installer
- iPXE boot scripts have not been loaded by actual iPXE firmware
- TFTP file serving has not been tested with real TFTP clients (0% coverage on `tftp.py`)

### No production scale testing

- No load testing (concurrent PXE boots)
- No long-running stability testing
- No testing with large numbers of registered hosts (100+)
- No testing of ISO import with real ISO files (all mocked)
- No benchmarking of API response times under load

### No integration testing with external services

- No testing with real DHCP servers (dnsmasq, ISC DHCP)
- No testing with real TFTP servers
- No testing of TLS termination with real certificates
- No testing of reverse proxy configurations (nginx, HAProxy)

## Known Gaps by OS Family

### Linux (most complete)

**Fedora / RHEL / CentOS (Kickstart)**
- Template rendering tested, 76% coverage
- No validation against actual Anaconda installer
- Derivative vendors (Rocky, Alma, CentOS Stream) use the same plugin but have not been individually tested
- No testing of EFI-specific Kickstart directives

**Debian (Preseed)**
- Template rendering tested, good coverage
- No validation against actual debian-installer
- Late-command injection tested at template level only

**Ubuntu (Cloud-Init Autoinstall)**
- Template rendering tested, 70% coverage
- No validation against actual Subiquity installer
- Ubuntu autoinstall format changed between 22.04 and 24.04; only one format tested

**SUSE / openSUSE (AutoYaST)**
- Template rendering tested, 63% coverage
- No validation against actual YaST installer
- SLES vs openSUSE differences not exhaustively tested

**Arch Linux (archinstall)**
- Template rendering tested, good coverage
- No validation against actual archinstall
- Rolling release means config format could drift

### BSD

**FreeBSD (bsdinstall)**
- Template rendering tested, 72% coverage
- No validation against actual bsdinstall
- ZFS-on-root configuration generated but not hardware-validated

**OpenBSD (autoinstall)**
- Template rendering tested, 76% coverage
- No validation against actual OpenBSD installer
- Response file format is simple but has not been tested on real hardware

**NetBSD (sysinst)**
- Template rendering tested, 69% coverage
- No validation against actual sysinst
- NetBSD autoinstall support is less mature than other BSDs

**DragonFly BSD**
- Template rendering tested, 98% coverage (highest)
- No validation against actual DragonFly BSD installer
- Smallest user base of any supported OS family

### Windows

**Windows (Unattend.xml)**
- Template rendering tested, 64% coverage (lowest among plugins)
- No validation against actual Windows Setup
- Basic Unattend.xml generation only
- **No driver injection automation** -- users must manually add drivers
- **No WinPE customization** -- boot.wim is used as-is
- **No product key management** -- key must be hardcoded in profile
- **No answer file validation** -- generated XML is not validated against Microsoft's schema
- Windows PXE boot requires WDS or custom iPXE chain-loading; this path is documented but not tested

## CI/CD Status

Current CI pipeline (GitHub Actions):
- Unit tests on Python 3.9, 3.10, 3.11, 3.12
- Coverage enforcement (50% minimum)
- Coverage report upload as artifact

### What CI does NOT do

- No linting in CI (ruff, flake8 configured but not run in CI)
- No type checking in CI (mypy configured but not run in CI)
- No security scanning in CI (bandit configured but not run in CI)
- No integration tests
- No end-to-end tests
- No performance benchmarks
- No container image builds
- No package publishing automation

## Development Process

PxeOS is developed with AI assistance using multi-model review (Groq Llama, Cohere Command R+, and others). Code is reviewed by multiple AI models for correctness before merge, but this does not replace real-world testing.

## Path to Production Readiness

To move PxeOS from "functional prototype" to "production-ready," the following would be needed:

1. **End-to-end PXE boot testing** -- At minimum, successfully PXE boot and install one distro per OS family in a VM (QEMU/KVM or VirtualBox)
2. **TFTP integration testing** -- Verify file serving works with real TFTP clients
3. **CI quality gates** -- Add ruff, mypy, and bandit to the CI pipeline
4. **Integration test suite** -- Test against real DHCP + TFTP + PxeOS stack
5. **TLS testing** -- Verify TLS termination works with real certificates
6. **Load testing** -- Verify behavior under concurrent PXE boot requests
7. **Security audit** -- Review authentication, input validation, and network exposure
8. **Documentation review** -- Verify all documented features work as described
9. **Packaging** -- Publish to PyPI, provide RPM/DEB packages, container image
10. **Community testing** -- Real users reporting real issues on real hardware
