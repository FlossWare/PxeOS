# Security Policy

## Supported Python Versions

| Version | Supported |
|---------|-----------|
| 3.13.x  | Yes       |
| 3.12.x  | Yes       |
| 3.11.x  | Yes       |
| 3.10.x  | Yes       |
| < 3.10  | No        |

## Checking for Vulnerabilities

### Using pip-audit

Install `pip-audit` (included in the `[dev]` optional dependency group):

```bash
pip install pxeos[dev]
```

Scan installed packages for known vulnerabilities:

```bash
pip-audit
```

Scan only PxeOS and its direct dependencies:

```bash
pip-audit --requirement <(pip freeze | grep -iE 'pxeos|fastapi|uvicorn|jinja2|pydantic|python-multipart|tomli')
```

### Using pip-audit with the project file directly

```bash
pip-audit --requirement pyproject.toml
```

## Updating Dependencies Safely

1. **Review current pins** -- dependency ranges are specified in `pyproject.toml` under `[project] dependencies`.

2. **Update within pinned ranges** (safe):
   ```bash
   pip install --upgrade pxeos
   ```

3. **Check for breakage after updating**:
   ```bash
   python -m pytest tests/ -q --tb=short
   ```

4. **Bump upper bounds** when a new major version of a dependency is released:
   - Edit the version range in `pyproject.toml`
   - Run the full test suite
   - Test manually with `pxeos server start` and `pxeos server status`

## Reporting a Vulnerability

If you discover a security vulnerability in PxeOS, please report it
by opening a GitHub issue at
<https://github.com/FlossWare/PxeOS/issues> with the label
`security`.  For sensitive issues, contact the maintainer directly at
the email listed in `pyproject.toml`.

## Security Best Practices for Deployment

- Enable TLS (`tls_cert` / `tls_key` in `pxeos.toml`) for all
  production deployments.
- Enable API key authentication (`auth.enabled = true`) and distribute
  keys with least-privilege roles (viewer, operator, admin).
- Run PxeOS as a non-root user; only the ISO import feature requires
  mount privileges.
- Restrict network access to the PxeOS API port to your provisioning
  VLAN.
