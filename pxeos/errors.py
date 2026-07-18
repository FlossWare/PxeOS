"""Custom exception hierarchy for PxeOS.

Provides structured exceptions with optional user-facing suggestions
and context dictionaries for richer error reporting in both the CLI
and the REST API.
"""

from __future__ import annotations

import traceback
from typing import Any, Dict, Optional


class PxeOSError(Exception):
    """Base exception for all PxeOS errors.

    Attributes:
        message:    Human-readable error description.
        suggestion: Optional actionable hint for the user.
        context:    Optional dict of structured data (paths, values, etc.).
        error_code: Machine-readable error code for API responses.
    """

    error_code: str = "PXEOS_ERROR"

    def __init__(
        self,
        message: str,
        *,
        suggestion: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.suggestion = suggestion
        self.context = context or {}


class ConfigError(PxeOSError):
    """Raised when a configuration file cannot be loaded or is invalid."""

    error_code: str = "CONFIG_ERROR"


class ValidationError(PxeOSError):
    """Raised when user-supplied input fails validation."""

    error_code: str = "VALIDATION_ERROR"


class ProvisionError(PxeOSError):
    """Raised when a provisioning operation fails."""

    error_code: str = "PROVISION_ERROR"


class PluginError(PxeOSError):
    """Raised when a plugin cannot be found or fails."""

    error_code: str = "PLUGIN_ERROR"


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------


def format_error(exc: PxeOSError, *, verbose: bool = False) -> str:
    """Format a PxeOSError for CLI output.

    Returns a string containing the error message and, when present,
    an indented suggestion line.  When *verbose* is True the full
    traceback is appended.
    """
    parts: list[str] = [f"error: {exc.message}"]

    if exc.suggestion:
        parts.append(f"hint: {exc.suggestion}")

    if exc.context:
        for key, value in exc.context.items():
            parts.append(f"  {key}: {value}")

    if verbose:
        parts.append("")
        parts.append(
            "".join(
                traceback.format_exception(
                    type(exc), exc, exc.__traceback__
                )
            )
        )

    return "\n".join(parts)
