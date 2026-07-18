"""Input validation helpers shared across CLI and API."""

from __future__ import annotations

import re
from typing import Optional, Tuple

# 6 groups of exactly 2 hex digits, separated by : or -
_MAC_RE = re.compile(
    r"^([0-9a-fA-F]{2})[:\-]"
    r"([0-9a-fA-F]{2})[:\-]"
    r"([0-9a-fA-F]{2})[:\-]"
    r"([0-9a-fA-F]{2})[:\-]"
    r"([0-9a-fA-F]{2})[:\-]"
    r"([0-9a-fA-F]{2})$"
)


def normalize_mac(mac: str) -> str:
    """Normalize a MAC address to lowercase colon-separated format."""
    return mac.strip().lower().replace("-", ":")


def validate_mac(mac: str) -> Tuple[bool, str]:
    """Validate a MAC address format.

    Returns:
        A tuple of (is_valid, error_message).  When valid the error
        message is the empty string.
    """
    stripped = mac.strip()
    if not _MAC_RE.match(stripped):
        return False, (
            f"invalid MAC address format: {mac!r}. "
            "Expected format: xx:xx:xx:xx:xx:xx "
            "(hex digits separated by ':' or '-')"
        )
    return True, ""


def validate_os_family(
    os_family: str,
    available: list[str],
) -> Tuple[bool, str]:
    """Check that *os_family* is among the registered plugins.

    Returns:
        A tuple of (is_valid, error_message).
    """
    if os_family.lower() not in [a.lower() for a in available]:
        return False, (
            f"unknown os_family {os_family!r}. "
            f"Available plugins: {', '.join(sorted(available))}"
        )
    return True, ""
