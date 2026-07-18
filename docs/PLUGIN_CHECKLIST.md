# Plugin Contribution Checklist

Use this checklist when developing a new PxeOS plugin or reviewing a plugin
pull request. Every item should be verified before merging.

---

## Plugin Class

- [ ] Plugin class inherits from `OSPlugin` (`pxeos.plugins.base`)
- [ ] Plugin file is located at `pxeos/plugins/<os_family>.py`
- [ ] Module docstring describes the OS family and installer type

## Abstract Properties

- [ ] `os_family` property returns a lowercase string identifier
- [ ] `os_family` value is unique (not already used by another plugin)
- [ ] `supported_versions` property returns a list of version strings
- [ ] Version strings match the format used by the OS (e.g., `"40"` for
      Fedora, `"7.5"` for OpenBSD, `"24.04"` for Ubuntu)

## Abstract Methods

- [ ] `autoinstall_filename()` returns the conventional filename for the
      OS installer config (e.g., `ks.cfg`, `preseed.cfg`, `user-data`)
- [ ] `generate_autoinstall(profile)` produces valid installer config text
- [ ] `generate_autoinstall()` calls `self._sanitize_context(context)`
      before rendering the template
- [ ] `generate_autoinstall()` uses `self._render_template()` (not raw
      string formatting) for config generation
- [ ] `boot_assets(profile)` returns a valid `BootAssets` dataclass
- [ ] `boot_assets()` handles both `BootFirmware.BIOS` and
      `BootFirmware.UEFI` (selecting `pxelinux.cfg.j2` or `grub.cfg.j2`)
- [ ] `boot_assets()` includes `ip=dhcp` or equivalent network boot argument
- [ ] `extract_from_iso(mount_path, dest)` returns a valid `DistroAssets`
      dataclass
- [ ] `extract_from_iso()` creates destination directories with
      `dest.mkdir(parents=True, exist_ok=True)`
- [ ] `extract_from_iso()` copies kernel and initrd from the ISO
- [ ] `extract_from_iso()` checks for and copies UEFI boot loader files
      (`EFI/BOOT` or `EFI/boot`) when present

## Validation (override of base implementation)

- [ ] `validate_profile()` is overridden (not abstract, but every plugin
      should extend it with OS-specific checks)
- [ ] `validate_profile()` calls `super().validate_profile(profile)` as
      the first line
- [ ] `validate_profile()` checks for required URLs (`install_url` and/or
      `autoinstall_url`)
- [ ] `validate_profile()` checks that `profile.arch` is in the set of
      supported architectures
- [ ] `validate_profile()` returns a list of error strings (empty = valid)
- [ ] Error messages are descriptive and mention the field name

## Template

- [ ] Jinja2 template file exists in `pxeos/templates/`
- [ ] Template filename follows the pattern `<format>.<ext>.j2`
      (e.g., `kickstart.cfg.j2`, `preseed.cfg.j2`)
- [ ] Template does not insert raw user input without sanitization
- [ ] XML templates use `.xml.j2` extension (enables Jinja2 autoescape)
- [ ] Template renders correctly with the context dict built in
      `generate_autoinstall()`
- [ ] Template output is valid for the target installer

## Live Boot (if applicable)

- [ ] `supports_live` property returns `True`
- [ ] `extract_live_assets()` is implemented and copies kernel, initrd,
      and squashfs
- [ ] `live_boot_assets()` is implemented and returns valid `BootAssets`
- [ ] Live boot arguments are correct for the OS (e.g., `boot=live`,
      `root=live:`, `boot=casper`)

## Registration

- [ ] Plugin module is listed in `PluginRegistry.load_builtins()` in
      `pxeos/registry.py`
- [ ] Entry point is declared in `pyproject.toml` under
      `[project.entry-points."pxeos.plugins"]`
- [ ] Plugin name in the entry point matches `os_family`

## Tests

- [ ] Test file exists at `tests/plugins/test_<os_family>.py`
- [ ] Test file has a `plugin` fixture returning an instance of the plugin
- [ ] Test file has a `valid_profile` fixture with realistic profile data
- [ ] Tests cover `os_family` property
- [ ] Tests cover `supported_versions` property
- [ ] Tests cover `autoinstall_filename()`
- [ ] Tests cover `generate_autoinstall()` output content
- [ ] Tests cover `validate_profile()` with valid input (no errors)
- [ ] Tests cover `validate_profile()` with missing URLs
- [ ] Tests cover `validate_profile()` with unsupported architecture
- [ ] Tests cover `validate_profile()` with OS family mismatch
- [ ] Tests cover `validate_profile()` with unsupported version
- [ ] Tests cover `boot_assets()` kernel and initrd paths
- [ ] Tests cover `boot_assets()` boot arguments
- [ ] Tests cover bootloader config for BIOS firmware
- [ ] Tests cover bootloader config for UEFI firmware
- [ ] Tests cover live boot methods (if `supports_live` is `True`)
- [ ] All tests pass: `python -m pytest tests/plugins/test_<os_family>.py -v`
- [ ] Full test suite passes: `python -m pytest tests/ -q --tb=short`

## Code Quality

- [ ] Code passes linting: `ruff check pxeos/plugins/<os_family>.py`
- [ ] No hardcoded secrets or credentials in plugin or template
- [ ] Constants (version lists, paths) are module-level, not inline
- [ ] Type hints are present on all method signatures
- [ ] `from __future__ import annotations` is the first import
