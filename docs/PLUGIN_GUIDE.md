# PxeOS Plugin Contribution Guide

This guide explains how to add a new OS plugin to PxeOS. It covers the
plugin architecture, the methods you need to implement, template rendering
patterns, registration, and testing expectations.

---

## Plugin Architecture Overview

PxeOS uses a plugin system to support multiple operating systems. Each OS
family (Fedora, Debian, Ubuntu, OpenBSD, etc.) is implemented as a Python
class that inherits from the `OSPlugin` abstract base class defined in
`pxeos/plugins/base.py`.

Key components:

- **`OSPlugin` (ABC)** -- Abstract base class declaring the interface every
  plugin must satisfy. Located at `pxeos/plugins/base.py`.
- **`PluginRegistry`** -- Discovers and registers plugin classes. Located at
  `pxeos/registry.py`.
- **`ProvisionProfile`** -- Dataclass carrying all provisioning parameters
  (name, OS family/version, architecture, firmware, URLs, network, disk,
  packages, post-scripts, extras). Located at `pxeos/models.py`.
- **`BootAssets`** -- Dataclass returned by `boot_assets()` containing kernel
  path, initrd path, boot arguments, and bootloader configuration text.
- **`DistroAssets`** -- Dataclass returned by `extract_from_iso()` containing
  paths to the extracted kernel, initrd, repository tree, and optional
  squashfs/boot-loader files.
- **Jinja2 templates** -- Autoinstall configs and bootloader configs are
  rendered from `.j2` templates stored in `pxeos/templates/`.

The flow is:

1. A `ProvisionProfile` is created from user input (TOML config, API, or CLI).
2. The registry looks up the plugin for the profile's `os_family`.
3. The plugin's `validate_profile()` checks the profile for errors.
4. `generate_autoinstall()` renders the OS-specific installer config.
5. `boot_assets()` produces the PXE boot configuration.
6. `extract_from_iso()` extracts kernel/initrd/repo from an ISO image.

---

## Step-by-Step: Creating a New OS Plugin

### 1. Create the plugin module

Create a new file under `pxeos/plugins/`. Use the OS family name in
lowercase as the filename:

```
pxeos/plugins/gentoo.py
```

### 2. Implement the required abstract members

Your class must inherit from `OSPlugin` and implement all abstract members:
two abstract properties (`os_family`, `supported_versions`) and four abstract
methods (`autoinstall_filename`, `generate_autoinstall`, `boot_assets`,
`extract_from_iso`). You should also override `validate_profile()`, which
has a default implementation in the base class but should be extended with
OS-specific checks. Here is the minimal interface:

```python
from pxeos.plugins.base import OSPlugin
from pxeos.models import BootAssets, DistroAssets, ProvisionProfile
from pathlib import Path


class GentooPlugin(OSPlugin):

    @property
    def os_family(self) -> str:
        """Return the OS family identifier (lowercase).

        This string is used as the registry key and must match
        the os_family field in ProvisionProfile.
        """
        return "gentoo"

    @property
    def supported_versions(self) -> list[str]:
        """Return the list of OS versions this plugin supports.

        The base class validate_profile() checks that the profile's
        os_version is in this list. Return an empty list to skip
        version validation.
        """
        return ["23.0"]

    def autoinstall_filename(self) -> str:
        """Return the filename for the generated autoinstall config.

        Examples from existing plugins:
        - Fedora: "ks.cfg"
        - Debian: "preseed.cfg"
        - Ubuntu: "user-data"
        - OpenBSD: "install.conf"
        """
        return "install.conf"

    def generate_autoinstall(
        self, profile: ProvisionProfile
    ) -> str:
        """Generate the OS-specific unattended install config.

        Build a context dict from the profile, sanitize it with
        self._sanitize_context(), and render a Jinja2 template.
        Returns the config file content as a string.
        """
        ...

    def boot_assets(
        self, profile: ProvisionProfile
    ) -> BootAssets:
        """Return PXE boot assets for a standard install.

        Must return a BootAssets dataclass with:
        - kernel: relative path to the kernel image
        - initrd: relative path to the initrd (or None)
        - boot_args: tuple of kernel command-line arguments
        - bootloader_config: rendered GRUB or PXELINUX config
        """
        ...

    def extract_from_iso(
        self, mount_path: Path, dest: Path
    ) -> DistroAssets:
        """Extract boot files and repo tree from a mounted ISO.

        Copy kernel, initrd, and distribution files from mount_path
        to dest. Returns a DistroAssets dataclass.
        """
        ...

    def validate_profile(
        self, profile: ProvisionProfile
    ) -> list[str]:
        """Validate a profile for this OS family.

        Always call super().validate_profile(profile) first to get
        base checks (name required, os_family match, version check).
        Append any OS-specific errors (required URLs, valid arches).
        Returns a list of error strings (empty means valid).
        """
        ...
```

### 3. Understanding each member in detail

#### `os_family` (abstract property)

A read-only property returning a lowercase string identifying the OS family.
This is the key used in the plugin registry and must match the `os_family`
field on `ProvisionProfile` instances intended for this plugin.

#### `supported_versions` (abstract property)

Returns a list of version strings. The base `validate_profile()` checks that
the profile's `os_version` appears in this list. If you return an empty list,
version checking is skipped.

#### `autoinstall_filename()`

Returns the filename that the generated autoinstall config should be saved as.
This is used by the engine when writing the config to disk. Use the
conventional filename for the OS's installer:

| OS Family | Installer | Filename |
|-----------|-----------|----------|
| Fedora/RHEL | Anaconda/Kickstart | `ks.cfg` |
| Debian | d-i/Preseed | `preseed.cfg` |
| Ubuntu | Subiquity/Cloud-Init | `user-data` |
| SUSE | YaST/AutoYaST | `autoyast.xml` |
| OpenBSD | autoinstall(8) | `install.conf` |
| FreeBSD | bsdinstall | `installerconfig` |
| Windows | WinPE/Unattend | `unattend.xml` |
| Arch | archinstall | `archinstall.json` |

#### `generate_autoinstall(profile)`

Generates the unattended-install config file content as a string. The
typical pattern is:

1. Build a context dictionary from `profile` fields.
2. Call `self._sanitize_context(context)` to validate hostnames, URLs,
   and package names against injection attacks.
3. Call `self._render_template("your-template.j2", context)` to render.

Example from the Fedora plugin:

```python
def generate_autoinstall(self, profile: ProvisionProfile) -> str:
    context = {
        "profile": profile,
        "hostname": profile.network.get("hostname", profile.name),
        "timezone": profile.extra.get("timezone", "America/New_York"),
        "packages": profile.packages,
        "post_scripts": profile.post_scripts,
        "install_url": profile.install_url,
    }
    self._sanitize_context(context)
    return self._render_template("kickstart.cfg.j2", context)
```

#### `boot_assets(profile)`

Returns a `BootAssets` dataclass. You must:

1. Determine the kernel and initrd paths (relative to the TFTP root).
2. Build a list of kernel command-line arguments.
3. Choose between `grub.cfg.j2` (UEFI) and `pxelinux.cfg.j2` (BIOS)
   based on `profile.firmware`.
4. Render the bootloader config.

```python
def boot_assets(self, profile: ProvisionProfile) -> BootAssets:
    boot_args = ["your=args", "ip=dhcp"]

    if profile.firmware == BootFirmware.UEFI:
        template = "grub.cfg.j2"
    else:
        template = "pxelinux.cfg.j2"

    bootloader_cfg = self._render_template(template, {
        "profile": profile,
        "kernel": "path/to/vmlinuz",
        "initrd": "path/to/initrd",
        "boot_args": " ".join(boot_args),
        "menu_label": f"{profile.name} - MyOS {profile.os_version}",
    })

    return BootAssets(
        kernel="path/to/vmlinuz",
        initrd="path/to/initrd",
        boot_args=tuple(boot_args),
        bootloader_config=bootloader_cfg,
    )
```

#### `extract_from_iso(mount_path, dest)`

Extracts boot-critical files from a mounted ISO at `mount_path` into `dest`.
At minimum, copy the kernel and initrd. If the ISO contains a package
repository (e.g., `Packages/`, `pool/`, distribution sets), copy that too.
Check for UEFI boot loaders under `EFI/BOOT` or `EFI/boot`.

Returns a `DistroAssets` dataclass:

```python
return DistroAssets(
    kernel_path=dest / "vmlinuz",
    initrd_path=dest / "initrd.img",
    repo_path=dest / "repo",
    boot_loader_path=dest / "EFI" / "BOOT",  # or None
    squashfs_path=None,  # set if applicable
)
```

#### `validate_profile(profile)` (not abstract -- override recommended)

This method is **not abstract**. The base class provides a default
implementation that checks: profile name is present, `os_family` matches,
and `os_version` is in `supported_versions`. You should override it to
add OS-specific validation, but always call `super().validate_profile()`
first to inherit the base checks:

```python
def validate_profile(self, profile: ProvisionProfile) -> list[str]:
    errors = super().validate_profile(profile)
    if not profile.install_url:
        errors.append("install_url is required for MyOS installs")
    if profile.arch not in ("x86_64", "aarch64"):
        errors.append(f"unsupported arch {profile.arch!r} for MyOS")
    return errors
```

### 4. Optional: Live boot support

If your OS supports PXE-booted live images, override these methods:

```python
@property
def supports_live(self) -> bool:
    return True

def extract_live_assets(
    self, mount_path: Path, dest: Path
) -> DistroAssets:
    """Extract live boot files (kernel, initrd, squashfs)."""
    ...

def live_boot_assets(
    self, profile: ProvisionProfile
) -> BootAssets:
    """Return boot assets for a live (non-install) PXE boot."""
    ...
```

The base class defaults `supports_live` to `False` and raises
`NotImplementedError` for the live methods. Only override these if
live boot is meaningful for your OS.

### 5. Create the Jinja2 template

Create a `.j2` file in `pxeos/templates/` for your autoinstall format.
The template receives the context dict you build in
`generate_autoinstall()`.

Important template rules:

- XML templates (filenames containing `.xml`) get automatic escaping via
  Jinja2's `select_autoescape`. Non-XML templates do not autoescape, so
  avoid inserting raw user input directly.
- Always sanitize context values through `self._sanitize_context()` before
  rendering. This validates hostnames (RFC 952/1123), URLs (allowed schemes),
  and package names (alphanumeric pattern).
- Use `trim_blocks` and `lstrip_blocks` (both enabled by default) to keep
  clean output formatting.

### 6. Register in the plugin registry

Two registration mechanisms exist:

**A. Builtin registration (recommended for bundled plugins)**

Add your module to the `builtin_modules` list in `pxeos/registry.py`:

```python
builtin_modules = [
    "pxeos.plugins.fedora",
    "pxeos.plugins.debian",
    # ...
    "pxeos.plugins.gentoo",  # <-- add here
]
```

The registry scans each module for classes that subclass `OSPlugin` and
registers them automatically.

**B. Entry-point registration (for external/third-party plugins)**

Add an entry point in `pyproject.toml` under `[project.entry-points."pxeos.plugins"]`:

```toml
[project.entry-points."pxeos.plugins"]
gentoo = "pxeos.plugins.gentoo:GentooPlugin"
```

The `PluginRegistry.discover()` method uses `importlib.metadata.entry_points`
to find and load these at runtime. This works for plugins installed as
separate packages.

---

## Template Rendering Patterns

The base class provides two helpers:

### `_sanitize_context(context)`

Validates and sanitizes common template context values:

- `hostname`: Must conform to RFC 952/1123 (raises `ValueError` if invalid).
- `install_url`: Must have an allowed scheme (`http`, `https`, `ftp`, `nfs`,
  `tftp`) and a valid netloc (raises `ValueError` if invalid).
- `packages`: Each package name must match `^[a-zA-Z0-9][a-zA-Z0-9._+:\-]*$`
  (raises `ValueError` on the first invalid name).

Always call this before rendering to prevent injection attacks.

### `_render_template(template_name, context)`

Loads a Jinja2 template from `pxeos/templates/` and renders it with the
given context dict. Configuration:

- **Autoescape:** Enabled for `.xml` and `.xml.j2` extensions (prevents
  XML injection). Disabled for all other templates.
- **`keep_trailing_newline`:** `True` -- preserves final newline.
- **`trim_blocks`:** `True` -- strips first newline after a block tag.
- **`lstrip_blocks`:** `True` -- strips leading whitespace before block tags.

---

## The `ProvisionProfile` Dataclass

Your plugin receives this dataclass. Here are the fields:

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `name` | `str` | (required) | Profile identifier |
| `os_family` | `str` | (required) | OS family (must match plugin's `os_family`) |
| `os_version` | `str` | (required) | OS version string |
| `vendor` | `str` | `""` | Vendor name (e.g., "Rocky", "Alma") |
| `arch` | `str` | `"x86_64"` | CPU architecture |
| `firmware` | `BootFirmware` | `BIOS` | `BootFirmware.BIOS` or `BootFirmware.UEFI` |
| `install_url` | `str` | `""` | URL to OS install media / mirror |
| `autoinstall_url` | `str` | `""` | URL to the generated autoinstall config |
| `network` | `dict` | `{}` | Network settings (hostname, bootproto, device, nameservers) |
| `disk` | `dict` | `{}` | Disk settings (method, device, partitions/layout) |
| `packages` | `list[str]` | `[]` | Packages to install |
| `post_scripts` | `list[str]` | `[]` | Post-install shell commands |
| `extra` | `dict` | `{}` | OS-specific extra settings (timezone, locale, etc.) |
| `ipxe_commands` | `list[str]` | `[]` | Custom iPXE script lines |
| `dhcp_options` | `dict[str, str]` | `{}` | Custom DHCP options |

---

## Testing Requirements

### File location

Plugin tests go in `tests/plugins/test_<os_family>.py`.

### Test structure

Follow the established pattern (see `tests/plugins/test_fedora.py` for a
complete example):

```python
import pytest
from pxeos.models import BootFirmware, ProvisionProfile
from pxeos.plugins.gentoo import GentooPlugin


@pytest.fixture
def plugin() -> GentooPlugin:
    return GentooPlugin()


@pytest.fixture
def valid_profile() -> ProvisionProfile:
    return ProvisionProfile(
        name="gentoo-server",
        os_family="gentoo",
        os_version="23.0",
        install_url="http://mirror.example.com/gentoo",
        autoinstall_url="http://pxe.example.com/gentoo/install.conf",
        packages=["vim", "tmux"],
    )
```

### Required test classes

Each plugin test file should contain test classes covering:

1. **`TestOsFamily`** -- Verify `plugin.os_family` returns the correct string.

2. **`TestSupportedVersions`** -- Verify all expected versions are present.

3. **`TestAutoinstallFilename`** -- Verify the correct filename is returned.

4. **`TestGenerateAutoinstall`** -- Verify the generated config contains
   expected content (installer directives, URLs, packages, post-scripts,
   hostnames). Use substring assertions (`assert "expected" in output`).

5. **`TestValidateProfile`** -- Verify:
   - A valid profile returns no errors.
   - Missing required URLs produce errors.
   - Unsupported architectures produce errors.
   - OS family mismatch produces errors.
   - Unsupported versions produce errors.
   - Valid architectures are accepted.

6. **`TestBootAssets`** -- Verify:
   - Kernel path is correct.
   - Initrd path is correct (or `None` for OS families like OpenBSD).
   - Boot arguments contain required entries.
   - Boot argument values are correct.

7. **`TestBootloaderConfig`** -- Verify:
   - BIOS profile produces PXELINUX-style config.
   - UEFI profile produces GRUB-style config.
   - Config contains the profile name and boot arguments.

8. **(If live supported) `TestLiveBootAssets`** -- Verify live boot assets
   are correctly generated.

### Running tests

```bash
# Run all tests
python -m pytest tests/ -q --tb=short

# Run only your plugin's tests
python -m pytest tests/plugins/test_gentoo.py -v

# Run with coverage
python -m pytest tests/ --cov=pxeos --cov-report=term-missing
```

The project requires a minimum of 50% code coverage (configured in
`pyproject.toml`).

---

## Review Checklist Summary

Before submitting a pull request, verify every item on the
[Plugin Contribution Checklist](PLUGIN_CHECKLIST.md). Key points:

1. Class inherits from `OSPlugin`.
2. All abstract members are implemented (2 properties + 4 methods).
3. `validate_profile()` is overridden and calls `super().validate_profile()` first.
4. `generate_autoinstall()` calls `_sanitize_context()` before rendering.
5. `boot_assets()` handles both BIOS and UEFI firmware.
6. Jinja2 template exists in `pxeos/templates/`.
7. Plugin is registered in `registry.py` and `pyproject.toml`.
8. Tests cover all methods with both valid and invalid inputs.
9. `python -m pytest tests/ -q --tb=short` passes with no failures.

---

## Existing Plugins as Reference

| Plugin | File | Installer | Template |
|--------|------|-----------|----------|
| Fedora/RHEL | `pxeos/plugins/fedora.py` | Kickstart | `kickstart.cfg.j2` |
| Debian | `pxeos/plugins/debian.py` | Preseed | `preseed.cfg.j2` |
| Ubuntu | `pxeos/plugins/ubuntu.py` | Cloud-Init | `cloud-init.yaml.j2` |
| SUSE | `pxeos/plugins/suse.py` | AutoYaST | `autoyast.xml.j2` |
| OpenBSD | `pxeos/plugins/openbsd.py` | autoinstall(8) | `install.conf.j2` |
| FreeBSD | `pxeos/plugins/freebsd.py` | bsdinstall | `installerconfig.j2` |
| DragonFlyBSD | `pxeos/plugins/dragonflybsd.py` | bsdinstall | `dragonflybsd-installerconfig.j2` |
| NetBSD | `pxeos/plugins/netbsd.py` | sysinst | `netbsd-auto.j2` |
| Arch | `pxeos/plugins/arch.py` | archinstall | `archinstall.json.j2` |
| Windows | `pxeos/plugins/windows.py` | WinPE/Unattend | `unattend.xml.j2` |

For a copy-pasteable starting point, see [PLUGIN_TEMPLATE.py](PLUGIN_TEMPLATE.py).
