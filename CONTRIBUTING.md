# Contributing to PxeOS

Thank you for your interest in contributing to PxeOS.

## Development Setup

```bash
git clone https://github.com/FlossWare/PxeOS.git
cd PxeOS
pip install -e ".[dev]"
```

## Running Tests

```bash
pytest tests/ -v
```

## Code Quality

All contributions must pass:

```bash
ruff check pxeos/
ruff format --check pxeos/ tests/
mypy pxeos/
bandit -r pxeos/ -c pyproject.toml
```

## Adding an OS Plugin

1. Create `pxeos/plugins/youros.py` implementing `OSPlugin` from `pxeos/plugins/base.py`
2. Create `pxeos/templates/youros.j2` with the native autoinstall format
3. Register in `pyproject.toml` under `[project.entry-points."pxeos.plugins"]`
4. Add tests in `tests/plugins/test_youros.py`

### Required methods

| Method | Purpose |
|--------|---------|
| `os_family` | Return the OS family identifier (e.g. `"fedora"`) |
| `supported_versions` | Return list of supported version strings |
| `generate_autoinstall(profile)` | Render the native autoinstall config from a `ProvisionProfile` |
| `boot_assets(profile)` | Return `BootAssets` (kernel path, initrd path, boot args) |
| `validate_profile(profile)` | Return list of validation error strings (empty = valid) |
| `autoinstall_filename()` | Return the filename the installer expects (e.g. `"ks.cfg"`) |
| `extract_from_iso(mount_path, dest)` | Extract boot assets from a mounted ISO to `dest` |

### Vendor taxonomy

`os_family` groups OSes that share an installer. `vendor` distinguishes distributions within a family:

- `os_family="fedora"` covers `vendor` values: `fedora`, `rhel`, `centos`, `rocky`, `alma`
- `os_family="debian"` covers `vendor` values: `debian`
- `os_family="ubuntu"` covers `vendor` values: `ubuntu`

## Pull Requests

- One feature or fix per PR
- Include tests for new functionality
- Follow existing code style (ruff + black enforce this)
- Update README if adding user-facing features

## Reporting Issues

Use [GitHub Issues](https://github.com/FlossWare/PxeOS/issues). Include:
- PxeOS version (`pxeos --version`)
- OS and Python version
- Steps to reproduce
- Expected vs actual behavior

## License

By contributing, you agree that your contributions will be licensed under the GPLv3.
