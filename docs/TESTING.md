# PxeOS Testing Guide

## Running Tests Locally

### Prerequisites

Install development dependencies:

```bash
pip install -e ".[dev]"
```

### Run All Tests

```bash
python -m pytest tests/ -v
```

### Run with Coverage

```bash
pytest tests/ \
  --cov=pxeos \
  --cov-report=term-missing:skip-covered \
  --cov-report=html \
  --cov-branch \
  --cov-fail-under=50
```

Coverage HTML report is written to `htmlcov/`.

### Run Specific Test Files

```bash
pytest tests/test_power.py -v           # Power management
pytest tests/test_cobbler_import.py -v  # Cobbler migration
pytest tests/test_performance.py -v     # Cache / performance
pytest tests/test_engine.py -v          # Core engine
pytest tests/test_api.py -v             # API endpoints
```

### Run Tests by Marker

```bash
pytest -m unit           # Unit tests only
pytest -m integration    # Integration tests only
pytest -m "not slow"     # Skip slow tests
```

## Adding Tests for New Plugins

1. Create `tests/plugins/test_<os_family>.py`
2. Use the shared fixtures from `tests/conftest.py`:
   - `sample_profile` -- generic Fedora profile
   - `plugin_registry` -- registry with all builtins loaded
   - `pxeos_config` -- config pointing at temp dirs
   - `tmp_config_dir` -- populated temp directory with TOML files
3. Test at minimum:
   - `generate_autoinstall()` produces valid output
   - `boot_assets()` returns correct kernel/initrd paths
   - `validate_profile()` catches invalid profiles
   - `extract_from_iso()` with mocked mount path

Example:

```python
def test_my_plugin_autoinstall(plugin_registry):
    plugin = plugin_registry.get("myos")
    profile = ProvisionProfile(
        name="test", os_family="myos", os_version="1.0"
    )
    output = plugin.generate_autoinstall(profile)
    assert "expected_directive" in output
```

## CI Pipeline

Tests run automatically on push to `main` and on pull requests via
`.github/workflows/test.yml`:

- **Matrix:** Python 3.10, 3.11, 3.12
- **Coverage threshold:** 50% minimum (branch coverage)
- **Fail-fast:** disabled (all matrix entries run even if one fails)

## Coverage Targets

| Module               | Target | Notes                          |
|----------------------|--------|--------------------------------|
| `pxeos/engine.py`    | 80%    | Core provisioning logic        |
| `pxeos/matcher.py`   | 90%    | Rule matching is critical path |
| `pxeos/power.py`     | 75%    | Mocked BMC calls               |
| `pxeos/cache.py`     | 85%    | Cache correctness matters      |
| `pxeos/api.py`       | 60%    | Endpoint coverage              |
| `pxeos/plugins/*.py` | 50%    | Per-plugin minimum             |
| **Overall**          | **50%** | CI enforced minimum           |

## QEMU Smoke Test Plan

For future hardware-level validation of PXE boot flows:

### Setup

1. Create a QEMU VM with PXE-capable NIC:
   ```bash
   qemu-system-x86_64 \
     -m 2048 \
     -boot n \
     -device virtio-net,netdev=net0,mac=52:54:00:12:34:56 \
     -netdev user,id=net0,tftp=/srv/tftp,bootfile=ipxe.pxe \
     -nographic
   ```

2. Start PxeOS server on the host:
   ```bash
   pxeos server start --host 0.0.0.0 --port 8443
   ```

3. Register a host rule for the QEMU MAC:
   ```bash
   pxeos host add \
     --mac 52:54:00:12:34:56 \
     --profile test-server \
     --os fedora --version 40
   ```

### Test Cases

1. **PXE boot sequence** -- VM requests iPXE script, receives kernel/initrd
2. **Autoinstall delivery** -- VM fetches kickstart/preseed from API
3. **Boot-once** -- After provisioning, VM boots from disk on next cycle
4. **Profile switching** -- Change profile, re-provision with new OS
5. **Power management** -- Use virtual BMC (vbmc) to test IPMI commands

### Virtual BMC for IPMI Testing

```bash
pip install virtualbmc
vbmc add qemu-vm --port 6230 --username admin --password password
vbmc start qemu-vm
ipmitool -I lanplus -H 127.0.0.1 -p 6230 -U admin -P password power status
```

This validates the full IPMI driver path without physical hardware.
