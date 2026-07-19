"""Shared HTTP helper for PxeOS Ansible modules.

Provides a thin wrapper around ``open_url`` (ansible.module_utils.urls)
for making authenticated requests to the PxeOS REST API.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional, Tuple

from ansible.module_utils.urls import open_url


class PxeOSAPIError(Exception):
    """Raised when the PxeOS API returns a non-success status."""

    def __init__(self, status: int, body: str) -> None:
        self.status = status
        self.body = body
        super().__init__(f"HTTP {status}: {body}")


def build_headers(api_key: Optional[str] = None) -> Dict[str, str]:
    """Return common HTTP headers, optionally with Bearer auth."""
    headers: Dict[str, str] = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


def api_request(
    url: str,
    method: str = "GET",
    data: Optional[Dict[str, Any]] = None,
    api_key: Optional[str] = None,
    validate_certs: bool = True,
    timeout: int = 30,
) -> Tuple[int, Dict[str, Any]]:
    """Execute an HTTP request against the PxeOS API.

    Returns ``(status_code, response_body_dict)``.
    Raises :class:`PxeOSAPIError` on HTTP errors (>=400).
    """
    headers = build_headers(api_key)
    body: Optional[str] = None
    if data is not None:
        body = json.dumps(data)

    try:
        resp = open_url(
            url,
            method=method,
            data=body,
            headers=headers,
            validate_certs=validate_certs,
            timeout=timeout,
        )
        status = resp.getcode()
        raw = resp.read().decode("utf-8")
    except Exception as exc:
        # open_url raises urllib errors for non-2xx responses
        status = getattr(exc, "code", 0)
        raw = ""
        if hasattr(exc, "read"):
            try:
                raw = exc.read().decode("utf-8")
            except Exception:
                raw = str(exc)
        if not raw:
            raw = str(exc)
        if status >= 400:
            raise PxeOSAPIError(status, raw) from exc
        if status == 0:
            raise PxeOSAPIError(0, raw) from exc

    if raw:
        try:
            result = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            result = {"raw": raw}
    else:
        result = {}

    return status, result
