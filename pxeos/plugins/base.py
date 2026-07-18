"""Abstract base for OS provisioning plugins."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import List

from jinja2 import Environment, FileSystemLoader, select_autoescape

from pxeos.models import BootAssets, DistroAssets, ProvisionProfile
from pxeos.validation import (
    sanitize_hostname,
    sanitize_packages,
    sanitize_shell_value,
    validate_hostname,
    validate_url,
)

_TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates"


class OSPlugin(ABC):

    @property
    @abstractmethod
    def os_family(self) -> str: ...

    @property
    @abstractmethod
    def supported_versions(self) -> list[str]: ...

    @abstractmethod
    def generate_autoinstall(
        self, profile: ProvisionProfile
    ) -> str: ...

    @abstractmethod
    def boot_assets(
        self, profile: ProvisionProfile
    ) -> BootAssets: ...

    @abstractmethod
    def autoinstall_filename(self) -> str: ...

    @abstractmethod
    def extract_from_iso(
        self, mount_path: Path, dest: Path
    ) -> DistroAssets: ...

    @property
    def supports_live(self) -> bool:
        return False

    def extract_live_assets(
        self, mount_path: Path, dest: Path
    ) -> "DistroAssets":
        raise NotImplementedError(
            f"{self.os_family} does not support live ISO import"
        )

    def live_boot_assets(
        self, profile: ProvisionProfile
    ) -> "BootAssets":
        raise NotImplementedError(
            f"{self.os_family} does not support live boot"
        )

    def validate_profile(
        self, profile: ProvisionProfile
    ) -> list[str]:
        errors: list[str] = []
        if not profile.name:
            errors.append("profile name is required")
        if profile.os_family != self.os_family:
            errors.append(
                f"os_family mismatch: expected {self.os_family}, "
                f"got {profile.os_family}"
            )
        if (
            self.supported_versions
            and profile.os_version not in self.supported_versions
        ):
            errors.append(
                f"unsupported version {profile.os_version!r}; "
                f"supported: {self.supported_versions}"
            )
        return errors

    def _sanitize_context(self, context: dict) -> dict:
        """Validate and sanitize common template context values.

        Checks hostname, install_url, and packages for injection
        risks.  Raises ``ValueError`` if any value is unsafe.
        """
        if "hostname" in context and context["hostname"]:
            sanitize_hostname(context["hostname"])
        if "install_url" in context and context["install_url"]:
            if not validate_url(context["install_url"]):
                raise ValueError(
                    f"invalid install_url: "
                    f"{context['install_url']!r}"
                )
        if "packages" in context:
            sanitize_packages(context["packages"])
        return context

    def _render_template(
        self, template_name: str, context: dict
    ) -> str:
        # Enable autoescape for XML templates to prevent
        # XML injection attacks.
        autoescape_exts = ["xml", "xml.j2"]
        env = Environment(
            loader=FileSystemLoader(str(_TEMPLATE_DIR)),
            autoescape=select_autoescape(
                enabled_extensions=autoescape_exts,
                default_for_string=False,
            ),
            keep_trailing_newline=True,
            trim_blocks=True,
            lstrip_blocks=True,
        )
        template = env.get_template(template_name)
        return template.render(**context)
