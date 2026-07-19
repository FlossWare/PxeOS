"""DHCP/DNS configuration generators for PXE boot infrastructure.

Generates config snippets for dnsmasq and ISC DHCP so that PxeOS can
integrate with existing DHCP infrastructure without embedding its own
DHCP server.  Each generator reads registered hosts (named hosts) and
produces config directives that point PXE clients at the correct TFTP
server and boot files.

Usage::

    from pxeos.dhcp import DnsmasqConfigGenerator, ISCDHCPConfigGenerator

    gen = DnsmasqConfigGenerator(
        tftp_root="/srv/tftp",
        pxe_server="192.168.1.10",
    )
    print(gen.generate(hosts))

    isc = ISCDHCPConfigGenerator(
        tftp_root="/srv/tftp",
        pxe_server="192.168.1.10",
        subnet="192.168.1.0",
        netmask="255.255.255.0",
    )
    print(isc.generate(hosts))
"""

from __future__ import annotations

import re
import textwrap
from dataclasses import dataclass, field
from typing import List, Optional

from pxeos.named_objects import NamedHost


# ------------------------------------------------------------------
# Validation helpers
# ------------------------------------------------------------------

_HOSTNAME_RE = re.compile(
    r"^[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?$"
)

_MAC_RE = re.compile(
    r"^([0-9A-Fa-f]{2}[:\-]){5}[0-9A-Fa-f]{2}$"
)

_IPV4_RE = re.compile(
    r"^(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}"
    r"(?:25[0-5]|2[0-4]\d|[01]?\d\d?)$"
)


def _validate_ip(value: str) -> bool:
    """Return True if *value* is a valid IPv4 address."""
    return bool(_IPV4_RE.match(value))


def _validate_mac(value: str) -> bool:
    """Return True if *value* looks like a colon/dash-separated MAC."""
    return bool(_MAC_RE.match(value))


def _normalize_mac(mac: str) -> str:
    """Normalize a MAC to lowercase colon-separated form."""
    return mac.lower().replace("-", ":")


def _validate_hostname(value: str) -> bool:
    """Return True if *value* is a valid hostname/FQDN."""
    if not value or len(value) > 253:
        return False
    return bool(_HOSTNAME_RE.match(value))


# ------------------------------------------------------------------
# Config data class
# ------------------------------------------------------------------


@dataclass
class DHCPEntry:
    """Normalized DHCP host entry derived from a NamedHost."""

    name: str
    mac: str
    ip_address: str = ""
    hostname: str = ""
    gateway: str = ""
    netmask: str = ""
    nameservers: List[str] = field(default_factory=list)
    profile: str = ""
    boot_filename: str = ""

    @classmethod
    def from_named_host(
        cls,
        host: NamedHost,
        default_boot_filename: str = "lpxelinux.0",
    ) -> "DHCPEntry":
        """Create a DHCPEntry from a NamedHost."""
        boot_filename = (
            host.extra.get("boot_filename", default_boot_filename)
            if host.extra
            else default_boot_filename
        )
        return cls(
            name=host.name,
            mac=_normalize_mac(host.mac),
            ip_address=host.ip_address,
            hostname=host.hostname or host.name,
            gateway=host.gateway,
            netmask=host.netmask,
            nameservers=list(host.nameservers),
            profile=host.profile,
            boot_filename=boot_filename,
        )


# ------------------------------------------------------------------
# Dnsmasq config generator
# ------------------------------------------------------------------


class DnsmasqConfigGenerator:
    """Generate dnsmasq configuration snippets for PXE booting.

    Produces ``dhcp-host``, ``dhcp-boot``, and ``tftp-root`` directives
    suitable for inclusion in ``/etc/dnsmasq.d/pxeos.conf`` or similar.

    Parameters
    ----------
    tftp_root:
        Absolute path to the TFTP root directory.
    pxe_server:
        IP address of the PXE/TFTP server.  If not provided, dnsmasq
        will serve TFTP from the machine it runs on.
    default_boot_filename:
        Boot file sent via DHCP option 67 (default: ``lpxelinux.0``).
    domain:
        Optional DNS domain to append to hostnames.
    default_lease_time:
        Lease time string for dnsmasq (e.g. ``"12h"``, ``"infinite"``).
    enable_tftp:
        Whether to include ``enable-tftp`` directive (default True).
    """

    def __init__(
        self,
        tftp_root: str = "/srv/tftp",
        pxe_server: str = "",
        default_boot_filename: str = "lpxelinux.0",
        domain: str = "",
        default_lease_time: str = "12h",
        enable_tftp: bool = True,
    ) -> None:
        self.tftp_root = tftp_root
        self.pxe_server = pxe_server
        self.default_boot_filename = default_boot_filename
        self.domain = domain
        self.default_lease_time = default_lease_time
        self.enable_tftp = enable_tftp

    def generate(
        self,
        hosts: List[NamedHost],
        header: bool = True,
    ) -> str:
        """Generate a dnsmasq config snippet for the given hosts.

        Parameters
        ----------
        hosts:
            List of ``NamedHost`` objects to generate entries for.
        header:
            If True, include a comment header and global PXE settings.

        Returns
        -------
        str
            The generated dnsmasq config text.
        """
        lines: List[str] = []

        if header:
            lines.append(
                "# Generated by PxeOS -- do not edit manually"
            )
            lines.append("")

            # Global PXE/TFTP settings
            if self.enable_tftp:
                lines.append("enable-tftp")
            lines.append(f"tftp-root={self.tftp_root}")

            # Global dhcp-boot
            boot_parts = [self.default_boot_filename]
            if self.pxe_server:
                boot_parts.append(self.pxe_server)
                boot_parts.append(self.pxe_server)
            lines.append(
                "dhcp-boot=" + ",".join(boot_parts)
            )

            if self.domain:
                lines.append(f"domain={self.domain}")

            lines.append("")

        # Per-host entries
        entries = self._build_entries(hosts)

        if not entries:
            lines.append("# No hosts registered")
            return "\n".join(lines) + "\n"

        lines.append("# Host entries")
        for entry in entries:
            lines.extend(self._render_host_entry(entry))
            lines.append("")

        return "\n".join(lines) + "\n"

    def generate_dns_records(
        self, hosts: List[NamedHost],
    ) -> str:
        """Generate dnsmasq DNS (address) records for hosts with IPs.

        Returns ``address=/hostname/ip`` lines for each host that has
        both a hostname and an IP address.
        """
        lines = [
            "# DNS records generated by PxeOS",
            "",
        ]
        entries = self._build_entries(hosts)
        found = False
        for entry in entries:
            if entry.ip_address and entry.hostname:
                fqdn = entry.hostname
                if (
                    self.domain
                    and "." not in fqdn
                ):
                    fqdn = f"{fqdn}.{self.domain}"
                lines.append(
                    f"address=/{fqdn}/{entry.ip_address}"
                )
                found = True

        if not found:
            lines.append("# No DNS records to generate")

        return "\n".join(lines) + "\n"

    def _build_entries(
        self, hosts: List[NamedHost],
    ) -> List[DHCPEntry]:
        """Convert NamedHosts to validated DHCPEntry objects."""
        entries: List[DHCPEntry] = []
        for host in hosts:
            if not _validate_mac(host.mac):
                continue
            entry = DHCPEntry.from_named_host(
                host,
                default_boot_filename=self.default_boot_filename,
            )
            entries.append(entry)
        return entries

    def _render_host_entry(
        self, entry: DHCPEntry,
    ) -> List[str]:
        """Render a single DHCPEntry as dnsmasq config lines."""
        lines: List[str] = []

        # dhcp-host line: mac,hostname,ip,leasetime
        parts = [entry.mac]
        hostname = entry.hostname or entry.name
        if _validate_hostname(hostname):
            parts.append(hostname)
        if entry.ip_address and _validate_ip(entry.ip_address):
            parts.append(entry.ip_address)
        parts.append(self.default_lease_time)

        lines.append(f"dhcp-host={','.join(parts)}")

        # Per-host boot file override if different from default
        if (
            entry.boot_filename
            and entry.boot_filename != self.default_boot_filename
        ):
            # Sanitize tag name to alphanumeric/dash/underscore
            safe_tag = re.sub(
                r"[^A-Za-z0-9_-]", "_", entry.name,
            )
            tag = f"tag:{safe_tag}"
            lines.append(
                f"dhcp-host={entry.mac},set:{safe_tag}"
            )
            boot_parts = [tag, entry.boot_filename]
            if self.pxe_server:
                boot_parts.append(self.pxe_server)
                boot_parts.append(self.pxe_server)
            lines.append(
                "dhcp-boot=" + ",".join(boot_parts)
            )

        return lines


# ------------------------------------------------------------------
# ISC DHCP config generator
# ------------------------------------------------------------------


class ISCDHCPConfigGenerator:
    """Generate ISC DHCP (dhcpd) config snippets for PXE booting.

    Produces ``host`` stanzas and ``subnet`` declarations suitable for
    inclusion in ``/etc/dhcp/dhcpd.conf`` or a file included from it.

    Parameters
    ----------
    tftp_root:
        Absolute path to the TFTP root directory.
    pxe_server:
        IP address of the PXE/TFTP server (``next-server`` directive).
    default_boot_filename:
        Boot file sent via ``filename`` directive (default:
        ``"lpxelinux.0"``).
    subnet:
        Network address for the subnet declaration (e.g.
        ``"192.168.1.0"``).  Optional.
    netmask:
        Netmask for the subnet declaration (e.g.
        ``"255.255.255.0"``).  Optional.
    domain_name:
        Domain name option for the subnet.
    default_lease_time:
        Default lease time in seconds (default: 43200 = 12 hours).
    max_lease_time:
        Maximum lease time in seconds (default: 86400 = 24 hours).
    range_start:
        Start of dynamic IP range.  Optional.
    range_end:
        End of dynamic IP range.  Optional.
    """

    def __init__(
        self,
        tftp_root: str = "/srv/tftp",
        pxe_server: str = "",
        default_boot_filename: str = "lpxelinux.0",
        subnet: str = "",
        netmask: str = "255.255.255.0",
        domain_name: str = "",
        default_lease_time: int = 43200,
        max_lease_time: int = 86400,
        range_start: str = "",
        range_end: str = "",
    ) -> None:
        self.tftp_root = tftp_root
        self.pxe_server = pxe_server
        self.default_boot_filename = default_boot_filename
        self.subnet = subnet
        self.netmask = netmask
        self.domain_name = domain_name
        self.default_lease_time = default_lease_time
        self.max_lease_time = max_lease_time
        self.range_start = range_start
        self.range_end = range_end

    def generate(
        self,
        hosts: List[NamedHost],
        header: bool = True,
    ) -> str:
        """Generate an ISC DHCP config snippet for the given hosts.

        Parameters
        ----------
        hosts:
            List of ``NamedHost`` objects to generate entries for.
        header:
            If True, include a comment header.

        Returns
        -------
        str
            The generated dhcpd.conf text.
        """
        lines: List[str] = []

        if header:
            lines.append(
                "# Generated by PxeOS -- do not edit manually"
            )
            lines.append("")

        # Global options
        if self.pxe_server:
            lines.append(
                f"next-server {self.pxe_server};"
            )
        lines.append(
            f'filename "{self.default_boot_filename}";'
        )
        lines.append("")

        # Subnet declaration (optional)
        if self.subnet:
            lines.extend(
                self._render_subnet_block(hosts)
            )
        else:
            # Just host blocks, no subnet wrapper
            entries = self._build_entries(hosts)
            if not entries:
                lines.append("# No hosts registered")
            else:
                for entry in entries:
                    lines.extend(
                        self._render_host_block(entry)
                    )
                    lines.append("")

        return "\n".join(lines) + "\n"

    def generate_host_blocks(
        self, hosts: List[NamedHost],
    ) -> str:
        """Generate only the ``host { ... }`` blocks, no subnet wrapper.

        Useful when the user wants to include these blocks inside an
        existing subnet declaration.
        """
        entries = self._build_entries(hosts)
        lines: List[str] = []
        for entry in entries:
            lines.extend(self._render_host_block(entry))
            lines.append("")
        return "\n".join(lines) + "\n"

    def _build_entries(
        self, hosts: List[NamedHost],
    ) -> List[DHCPEntry]:
        """Convert NamedHosts to validated DHCPEntry objects."""
        entries: List[DHCPEntry] = []
        for host in hosts:
            if not _validate_mac(host.mac):
                continue
            entry = DHCPEntry.from_named_host(
                host,
                default_boot_filename=self.default_boot_filename,
            )
            entries.append(entry)
        return entries

    def _render_host_block(
        self, entry: DHCPEntry,
    ) -> List[str]:
        """Render a single ``host { ... }`` block."""
        lines = [f"host {entry.name} {{"]
        lines.append(
            f"    hardware ethernet {entry.mac};"
        )
        if entry.ip_address and _validate_ip(entry.ip_address):
            lines.append(
                f"    fixed-address {entry.ip_address};"
            )
        hostname = entry.hostname or entry.name
        if _validate_hostname(hostname):
            lines.append(
                f'    option host-name "{hostname}";'
            )
        if (
            entry.boot_filename
            and entry.boot_filename
            != self.default_boot_filename
        ):
            lines.append(
                f'    filename "{entry.boot_filename}";'
            )
        lines.append("}")
        return lines

    def _render_subnet_block(
        self, hosts: List[NamedHost],
    ) -> List[str]:
        """Render a ``subnet { ... }`` block containing host entries."""
        lines = [
            f"subnet {self.subnet} "
            f"netmask {self.netmask} {{"
        ]

        # Subnet options
        if self.range_start and self.range_end:
            lines.append(
                f"    range {self.range_start} "
                f"{self.range_end};"
            )

        if self.domain_name:
            lines.append(
                f'    option domain-name "{self.domain_name}";'
            )

        lines.append(
            f"    default-lease-time "
            f"{self.default_lease_time};"
        )
        lines.append(
            f"    max-lease-time {self.max_lease_time};"
        )

        if self.pxe_server:
            lines.append(
                f"    next-server {self.pxe_server};"
            )
        lines.append(
            f'    filename "{self.default_boot_filename}";'
        )

        lines.append("")

        # Host entries inside subnet
        entries = self._build_entries(hosts)
        if not entries:
            lines.append("    # No hosts registered")
        else:
            for entry in entries:
                for line in self._render_host_block(entry):
                    lines.append(f"    {line}")
                lines.append("")

        lines.append("}")
        return lines
