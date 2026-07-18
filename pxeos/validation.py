"""Input validation and sanitization for PxeOS.

Provides validators and sanitizers for user-supplied inputs that flow
into autoinstall templates, shell scripts, and XML configurations.
"""

from __future__ import annotations

import re
from typing import List, Optional
from urllib.parse import urlparse

# ---------------------------------------------------------------------------
# MAC address validation (IEEE 802 format)
# ---------------------------------------------------------------------------

# Accepts colon-separated, dash-separated, or bare hex MACs:
#   aa:bb:cc:dd:ee:ff  |  AA-BB-CC-DD-EE-FF  |  aabbccddeeff
_MAC_RE = re.compile(
    r"^([0-9a-fA-F]{2}[:\-]){5}[0-9a-fA-F]{2}$"
    r"|^[0-9a-fA-F]{12}$"
)


def validate_mac(mac: str) -> bool:
    """Return True if *mac* is a valid MAC address."""
    return bool(_MAC_RE.match(mac))


def normalize_mac(mac: str) -> str:
    """Normalize a MAC address to lower-case colon-separated form.

    Raises ``ValueError`` if the address is invalid.
    """
    if not validate_mac(mac):
        raise ValueError(f"invalid MAC address: {mac!r}")
    # Strip colons/dashes, then reformat.
    bare = mac.replace(":", "").replace("-", "").lower()
    return ":".join(bare[i : i + 2] for i in range(0, 12, 2))


# ---------------------------------------------------------------------------
# Hostname validation (RFC 952 / RFC 1123)
# ---------------------------------------------------------------------------

# Labels: alphanumeric + hyphens, 1-63 chars, cannot start/end with hyphen.
_LABEL_RE = re.compile(r"^[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?$")
_MAX_HOSTNAME_LEN = 253


def validate_hostname(hostname: str) -> bool:
    """Return True if *hostname* conforms to RFC 952/1123.

    Accepts both simple hostnames (``web-01``) and FQDNs
    (``web-01.example.com``).  Trailing dots are stripped.
    """
    if not hostname:
        return False
    # Strip trailing dot (FQDN convention).
    hostname = hostname.rstrip(".")
    if len(hostname) > _MAX_HOSTNAME_LEN:
        return False
    labels = hostname.split(".")
    return all(_LABEL_RE.match(label) for label in labels)


def sanitize_hostname(hostname: str) -> str:
    """Validate and return *hostname*, or raise ``ValueError``."""
    if not validate_hostname(hostname):
        raise ValueError(
            f"invalid hostname: {hostname!r} "
            f"(must conform to RFC 952/1123: alphanumeric and "
            f"hyphens, labels 1-63 chars, no leading/trailing hyphens)"
        )
    return hostname.rstrip(".")


# ---------------------------------------------------------------------------
# URL validation
# ---------------------------------------------------------------------------

_ALLOWED_URL_SCHEMES = {"http", "https", "ftp", "nfs", "tftp"}


def validate_url(url: str, allowed_schemes: Optional[set] = None) -> bool:
    """Return True if *url* is a valid URL with an allowed scheme.

    Defaults to allowing http, https, ftp, nfs, tftp.
    """
    if not url:
        return False
    schemes = allowed_schemes or _ALLOWED_URL_SCHEMES
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    if parsed.scheme not in schemes:
        return False
    if not parsed.netloc and parsed.scheme not in ("nfs",):
        return False
    return True


def sanitize_url(url: str, allowed_schemes: Optional[set] = None) -> str:
    """Validate and return *url*, or raise ``ValueError``."""
    if not validate_url(url, allowed_schemes):
        schemes = allowed_schemes or _ALLOWED_URL_SCHEMES
        raise ValueError(
            f"invalid URL: {url!r} "
            f"(allowed schemes: {', '.join(sorted(schemes))})"
        )
    return url


# ---------------------------------------------------------------------------
# Shell-safe string sanitization
# ---------------------------------------------------------------------------

# Characters that must not appear in values interpolated into shell contexts
# (e.g., hostnames, device names, package names used in config templates).
_SHELL_UNSAFE_RE = re.compile(r"[;&|`$\"\'\\\n\r<>(){}!\x00]")


def is_shell_safe(value: str) -> bool:
    """Return True if *value* contains no shell metacharacters."""
    return not bool(_SHELL_UNSAFE_RE.search(value))


def sanitize_shell_value(value: str, field_name: str = "value") -> str:
    """Validate that *value* contains no shell metacharacters.

    Raises ``ValueError`` with the field name if unsafe characters
    are found.  Does NOT attempt to escape -- rejects outright.
    """
    if not is_shell_safe(value):
        raise ValueError(
            f"unsafe characters in {field_name}: {value!r} "
            f"(shell metacharacters are not allowed)"
        )
    return value


# ---------------------------------------------------------------------------
# XML attribute/text sanitization
# ---------------------------------------------------------------------------

_XML_ESCAPE_MAP = {
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&apos;",
}


def escape_xml(value: str) -> str:
    """Escape XML special characters in *value*."""
    for char, replacement in _XML_ESCAPE_MAP.items():
        value = value.replace(char, replacement)
    return value


# ---------------------------------------------------------------------------
# Path traversal prevention
# ---------------------------------------------------------------------------


def validate_safe_name(name: str, field_name: str = "name") -> str:
    """Ensure *name* has no path traversal components.

    Rejects names containing ``..``, ``/``, ``\\``, or null bytes.
    """
    if not name:
        raise ValueError(f"{field_name} must not be empty")
    if ".." in name or "/" in name or "\\" in name or "\x00" in name:
        raise ValueError(
            f"path traversal detected in {field_name}: {name!r}"
        )
    return name


# ---------------------------------------------------------------------------
# Package name validation
# ---------------------------------------------------------------------------

# Package names: alphanumeric, hyphens, underscores, dots, plus signs, colons.
_PACKAGE_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._+:\-]*$")


def validate_package_name(pkg: str) -> bool:
    """Return True if *pkg* looks like a safe package name."""
    if not pkg or len(pkg) > 256:
        return False
    return bool(_PACKAGE_RE.match(pkg))


def sanitize_packages(packages: List[str]) -> List[str]:
    """Validate a list of package names.  Raises ``ValueError`` on
    the first invalid name found.
    """
    for pkg in packages:
        if not validate_package_name(pkg):
            raise ValueError(
                f"invalid package name: {pkg!r} "
                f"(only alphanumeric, hyphens, underscores, "
                f"dots, plus signs, colons allowed)"
            )
    return list(packages)
