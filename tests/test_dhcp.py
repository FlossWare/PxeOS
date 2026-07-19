"""Tests for pxeos.dhcp -- DHCP/DNS config generators."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from pxeos.dhcp import (
    DHCPEntry,
    DnsmasqConfigGenerator,
    ISCDHCPConfigGenerator,
    _normalize_mac,
    _validate_hostname,
    _validate_ip,
    _validate_mac,
)
from pxeos.named_objects import NamedHost


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


class TestValidateIP:
    def test_valid_ipv4(self):
        assert _validate_ip("192.168.1.1") is True

    def test_valid_ipv4_zeros(self):
        assert _validate_ip("0.0.0.0") is True

    def test_valid_ipv4_broadcast(self):
        assert _validate_ip("255.255.255.255") is True

    def test_invalid_ipv4_too_high(self):
        assert _validate_ip("256.1.1.1") is False

    def test_invalid_ipv4_too_few_octets(self):
        assert _validate_ip("192.168.1") is False

    def test_invalid_ipv4_letters(self):
        assert _validate_ip("abc.def.ghi.jkl") is False

    def test_empty_string(self):
        assert _validate_ip("") is False


class TestValidateMAC:
    def test_valid_colon_separated(self):
        assert _validate_mac("aa:bb:cc:dd:ee:ff") is True

    def test_valid_dash_separated(self):
        assert _validate_mac("AA-BB-CC-DD-EE-FF") is True

    def test_valid_mixed_case(self):
        assert _validate_mac("aA:Bb:cC:Dd:eE:fF") is True

    def test_invalid_too_short(self):
        assert _validate_mac("aa:bb:cc:dd:ee") is False

    def test_invalid_no_separator(self):
        assert _validate_mac("aabbccddeeff") is False

    def test_empty(self):
        assert _validate_mac("") is False


class TestNormalizeMAC:
    def test_already_normalized(self):
        assert _normalize_mac("aa:bb:cc:dd:ee:ff") == "aa:bb:cc:dd:ee:ff"

    def test_uppercase_to_lower(self):
        assert _normalize_mac("AA:BB:CC:DD:EE:FF") == "aa:bb:cc:dd:ee:ff"

    def test_dashes_to_colons(self):
        assert _normalize_mac("AA-BB-CC-DD-EE-FF") == "aa:bb:cc:dd:ee:ff"


class TestValidateHostname:
    def test_simple_hostname(self):
        assert _validate_hostname("server01") is True

    def test_fqdn(self):
        assert _validate_hostname("server01.example.com") is True

    def test_with_dashes(self):
        assert _validate_hostname("my-server-01") is True

    def test_empty(self):
        assert _validate_hostname("") is False

    def test_too_long(self):
        assert _validate_hostname("a" * 254) is False

    def test_starts_with_dot(self):
        assert _validate_hostname(".invalid") is False


# ---------------------------------------------------------------------------
# DHCPEntry
# ---------------------------------------------------------------------------


class TestDHCPEntry:
    def test_from_named_host_basic(self):
        host = NamedHost(
            name="web01",
            mac="aa:bb:cc:dd:ee:ff",
            ip_address="192.168.1.10",
            hostname="web01.local",
        )
        entry = DHCPEntry.from_named_host(host)
        assert entry.name == "web01"
        assert entry.mac == "aa:bb:cc:dd:ee:ff"
        assert entry.ip_address == "192.168.1.10"
        assert entry.hostname == "web01.local"
        assert entry.boot_filename == "lpxelinux.0"

    def test_from_named_host_custom_boot_file(self):
        host = NamedHost(
            name="uefi01",
            mac="aa:bb:cc:dd:ee:ff",
            extra={"boot_filename": "grubx64.efi"},
        )
        entry = DHCPEntry.from_named_host(host)
        assert entry.boot_filename == "grubx64.efi"

    def test_from_named_host_uses_name_as_hostname(self):
        host = NamedHost(
            name="srv01",
            mac="aa:bb:cc:dd:ee:ff",
        )
        entry = DHCPEntry.from_named_host(host)
        assert entry.hostname == "srv01"

    def test_from_named_host_normalizes_mac(self):
        host = NamedHost(
            name="srv01",
            mac="AA-BB-CC-DD-EE-FF",
        )
        entry = DHCPEntry.from_named_host(host)
        assert entry.mac == "aa:bb:cc:dd:ee:ff"

    def test_from_named_host_with_nameservers(self):
        host = NamedHost(
            name="srv01",
            mac="aa:bb:cc:dd:ee:ff",
            nameservers=["8.8.8.8", "8.8.4.4"],
        )
        entry = DHCPEntry.from_named_host(host)
        assert entry.nameservers == ["8.8.8.8", "8.8.4.4"]

    def test_from_named_host_default_boot_filename_override(self):
        host = NamedHost(
            name="srv01",
            mac="aa:bb:cc:dd:ee:ff",
        )
        entry = DHCPEntry.from_named_host(
            host, default_boot_filename="ipxe.efi"
        )
        assert entry.boot_filename == "ipxe.efi"


# ---------------------------------------------------------------------------
# DnsmasqConfigGenerator
# ---------------------------------------------------------------------------


class TestDnsmasqConfigGenerator:
    def _make_hosts(self):
        return [
            NamedHost(
                name="web01",
                mac="aa:bb:cc:dd:ee:01",
                ip_address="192.168.1.10",
                hostname="web01.example.com",
                profile="fedora-42",
            ),
            NamedHost(
                name="db01",
                mac="aa:bb:cc:dd:ee:02",
                ip_address="192.168.1.20",
                hostname="db01.example.com",
                gateway="192.168.1.1",
            ),
        ]

    def test_generate_includes_header(self):
        gen = DnsmasqConfigGenerator()
        output = gen.generate(self._make_hosts())
        assert "Generated by PxeOS" in output

    def test_generate_no_header(self):
        gen = DnsmasqConfigGenerator()
        output = gen.generate(self._make_hosts(), header=False)
        assert "Generated by PxeOS" not in output

    def test_generate_includes_enable_tftp(self):
        gen = DnsmasqConfigGenerator()
        output = gen.generate(self._make_hosts())
        assert "enable-tftp" in output

    def test_generate_disable_tftp(self):
        gen = DnsmasqConfigGenerator(enable_tftp=False)
        output = gen.generate(self._make_hosts())
        assert "enable-tftp" not in output

    def test_generate_includes_tftp_root(self):
        gen = DnsmasqConfigGenerator(tftp_root="/custom/tftp")
        output = gen.generate(self._make_hosts())
        assert "tftp-root=/custom/tftp" in output

    def test_generate_includes_dhcp_boot(self):
        gen = DnsmasqConfigGenerator(
            pxe_server="192.168.1.100",
        )
        output = gen.generate(self._make_hosts())
        assert "dhcp-boot=lpxelinux.0,192.168.1.100,192.168.1.100" in output

    def test_generate_includes_domain(self):
        gen = DnsmasqConfigGenerator(domain="example.com")
        output = gen.generate(self._make_hosts())
        assert "domain=example.com" in output

    def test_generate_host_entries(self):
        gen = DnsmasqConfigGenerator()
        output = gen.generate(self._make_hosts())
        assert "dhcp-host=aa:bb:cc:dd:ee:01" in output
        assert "dhcp-host=aa:bb:cc:dd:ee:02" in output

    def test_generate_host_with_ip(self):
        gen = DnsmasqConfigGenerator()
        output = gen.generate(self._make_hosts())
        assert "192.168.1.10" in output
        assert "192.168.1.20" in output

    def test_generate_host_with_hostname(self):
        gen = DnsmasqConfigGenerator()
        output = gen.generate(self._make_hosts())
        assert "web01.example.com" in output
        assert "db01.example.com" in output

    def test_generate_empty_hosts(self):
        gen = DnsmasqConfigGenerator()
        output = gen.generate([])
        assert "No hosts registered" in output

    def test_generate_skips_invalid_mac(self):
        hosts = [
            NamedHost(name="bad", mac="not-a-mac"),
        ]
        gen = DnsmasqConfigGenerator()
        output = gen.generate(hosts)
        assert "No hosts registered" in output

    def test_generate_custom_boot_file(self):
        gen = DnsmasqConfigGenerator(
            default_boot_filename="ipxe.efi",
        )
        output = gen.generate(self._make_hosts())
        assert "dhcp-boot=ipxe.efi" in output

    def test_generate_lease_time(self):
        gen = DnsmasqConfigGenerator(
            default_lease_time="24h",
        )
        output = gen.generate(self._make_hosts())
        assert "24h" in output

    def test_generate_pxe_server_in_boot_line(self):
        gen = DnsmasqConfigGenerator(
            pxe_server="10.0.0.1",
        )
        output = gen.generate(self._make_hosts())
        assert "10.0.0.1" in output

    def test_generate_dns_records(self):
        gen = DnsmasqConfigGenerator()
        output = gen.generate_dns_records(self._make_hosts())
        assert "address=/web01.example.com/192.168.1.10" in output
        assert "address=/db01.example.com/192.168.1.20" in output

    def test_generate_dns_records_with_domain(self):
        hosts = [
            NamedHost(
                name="srv01",
                mac="aa:bb:cc:dd:ee:01",
                ip_address="192.168.1.10",
                hostname="srv01",
            ),
        ]
        gen = DnsmasqConfigGenerator(domain="example.com")
        output = gen.generate_dns_records(hosts)
        assert "address=/srv01.example.com/192.168.1.10" in output

    def test_generate_dns_records_no_ip(self):
        hosts = [
            NamedHost(
                name="srv01",
                mac="aa:bb:cc:dd:ee:01",
                hostname="srv01",
            ),
        ]
        gen = DnsmasqConfigGenerator()
        output = gen.generate_dns_records(hosts)
        assert "No DNS records to generate" in output

    def test_generate_dns_records_fqdn_not_doubled(self):
        hosts = [
            NamedHost(
                name="srv01",
                mac="aa:bb:cc:dd:ee:01",
                ip_address="192.168.1.10",
                hostname="srv01.already.qualified",
            ),
        ]
        gen = DnsmasqConfigGenerator(domain="example.com")
        output = gen.generate_dns_records(hosts)
        assert "address=/srv01.already.qualified/192.168.1.10" in output

    def test_generate_per_host_boot_override(self):
        hosts = [
            NamedHost(
                name="uefi01",
                mac="aa:bb:cc:dd:ee:01",
                extra={"boot_filename": "grubx64.efi"},
            ),
        ]
        gen = DnsmasqConfigGenerator()
        output = gen.generate(hosts)
        assert "grubx64.efi" in output


# ---------------------------------------------------------------------------
# ISCDHCPConfigGenerator
# ---------------------------------------------------------------------------


class TestISCDHCPConfigGenerator:
    def _make_hosts(self):
        return [
            NamedHost(
                name="web01",
                mac="aa:bb:cc:dd:ee:01",
                ip_address="192.168.1.10",
                hostname="web01.example.com",
                profile="fedora-42",
            ),
            NamedHost(
                name="db01",
                mac="aa:bb:cc:dd:ee:02",
                ip_address="192.168.1.20",
                hostname="db01.example.com",
                gateway="192.168.1.1",
            ),
        ]

    def test_generate_includes_header(self):
        gen = ISCDHCPConfigGenerator()
        output = gen.generate(self._make_hosts())
        assert "Generated by PxeOS" in output

    def test_generate_no_header(self):
        gen = ISCDHCPConfigGenerator()
        output = gen.generate(self._make_hosts(), header=False)
        assert "Generated by PxeOS" not in output

    def test_generate_includes_filename(self):
        gen = ISCDHCPConfigGenerator()
        output = gen.generate(self._make_hosts())
        assert 'filename "lpxelinux.0"' in output

    def test_generate_includes_next_server(self):
        gen = ISCDHCPConfigGenerator(
            pxe_server="192.168.1.100",
        )
        output = gen.generate(self._make_hosts())
        assert "next-server 192.168.1.100;" in output

    def test_generate_host_blocks(self):
        gen = ISCDHCPConfigGenerator()
        output = gen.generate(self._make_hosts())
        assert "host web01 {" in output
        assert "host db01 {" in output

    def test_generate_hardware_ethernet(self):
        gen = ISCDHCPConfigGenerator()
        output = gen.generate(self._make_hosts())
        assert "hardware ethernet aa:bb:cc:dd:ee:01;" in output
        assert "hardware ethernet aa:bb:cc:dd:ee:02;" in output

    def test_generate_fixed_address(self):
        gen = ISCDHCPConfigGenerator()
        output = gen.generate(self._make_hosts())
        assert "fixed-address 192.168.1.10;" in output
        assert "fixed-address 192.168.1.20;" in output

    def test_generate_host_name_option(self):
        gen = ISCDHCPConfigGenerator()
        output = gen.generate(self._make_hosts())
        assert 'option host-name "web01.example.com"' in output
        assert 'option host-name "db01.example.com"' in output

    def test_generate_empty_hosts(self):
        gen = ISCDHCPConfigGenerator()
        output = gen.generate([])
        assert "No hosts registered" in output

    def test_generate_skips_invalid_mac(self):
        hosts = [
            NamedHost(name="bad", mac="not-valid"),
        ]
        gen = ISCDHCPConfigGenerator()
        output = gen.generate(hosts)
        assert "No hosts registered" in output

    def test_generate_with_subnet(self):
        gen = ISCDHCPConfigGenerator(
            subnet="192.168.1.0",
            netmask="255.255.255.0",
            pxe_server="192.168.1.100",
        )
        output = gen.generate(self._make_hosts())
        assert "subnet 192.168.1.0 netmask 255.255.255.0 {" in output

    def test_generate_subnet_with_range(self):
        gen = ISCDHCPConfigGenerator(
            subnet="192.168.1.0",
            netmask="255.255.255.0",
            range_start="192.168.1.100",
            range_end="192.168.1.200",
        )
        output = gen.generate(self._make_hosts())
        assert "range 192.168.1.100 192.168.1.200;" in output

    def test_generate_subnet_with_domain(self):
        gen = ISCDHCPConfigGenerator(
            subnet="192.168.1.0",
            domain_name="example.com",
        )
        output = gen.generate(self._make_hosts())
        assert 'option domain-name "example.com"' in output

    def test_generate_subnet_lease_times(self):
        gen = ISCDHCPConfigGenerator(
            subnet="192.168.1.0",
            default_lease_time=7200,
            max_lease_time=14400,
        )
        output = gen.generate(self._make_hosts())
        assert "default-lease-time 7200;" in output
        assert "max-lease-time 14400;" in output

    def test_generate_custom_boot_filename(self):
        gen = ISCDHCPConfigGenerator(
            default_boot_filename="ipxe.efi",
        )
        output = gen.generate(self._make_hosts())
        assert 'filename "ipxe.efi"' in output

    def test_generate_host_blocks_only(self):
        gen = ISCDHCPConfigGenerator()
        output = gen.generate_host_blocks(self._make_hosts())
        assert "host web01 {" in output
        assert "host db01 {" in output
        # Should not include global options
        assert "next-server" not in output

    def test_generate_per_host_boot_override(self):
        hosts = [
            NamedHost(
                name="uefi01",
                mac="aa:bb:cc:dd:ee:01",
                ip_address="192.168.1.50",
                extra={"boot_filename": "grubx64.efi"},
            ),
        ]
        gen = ISCDHCPConfigGenerator()
        output = gen.generate(hosts)
        assert 'filename "grubx64.efi"' in output

    def test_generate_no_fixed_address_without_ip(self):
        hosts = [
            NamedHost(
                name="dynamic01",
                mac="aa:bb:cc:dd:ee:01",
            ),
        ]
        gen = ISCDHCPConfigGenerator()
        output = gen.generate(hosts)
        assert "fixed-address" not in output

    def test_host_blocks_empty(self):
        gen = ISCDHCPConfigGenerator()
        output = gen.generate_host_blocks([])
        assert output.strip() == ""


# ---------------------------------------------------------------------------
# CLI integration
# ---------------------------------------------------------------------------


class TestDHCPCLI:
    """Test the 'pxeos dhcp' CLI subcommand."""

    def test_parser_has_dhcp_command(self):
        from pxeos.cli import _build_parser

        parser = _build_parser()
        subparser_action = None
        for action in parser._subparsers._actions:
            if hasattr(action, "_parser_class"):
                subparser_action = action
                break

        assert subparser_action is not None
        assert "dhcp" in subparser_action.choices

    def test_dhcp_generate_default_format(self):
        from pxeos.cli import _build_parser

        parser = _build_parser()
        args = parser.parse_args(["dhcp", "generate"])
        assert args.dhcp_format == "dnsmasq"

    def test_dhcp_generate_isc_format(self):
        from pxeos.cli import _build_parser

        parser = _build_parser()
        args = parser.parse_args([
            "dhcp", "generate", "--format", "isc-dhcp",
        ])
        assert args.dhcp_format == "isc-dhcp"

    def test_dhcp_generate_with_pxe_server(self):
        from pxeos.cli import _build_parser

        parser = _build_parser()
        args = parser.parse_args([
            "dhcp", "generate", "--pxe-server", "10.0.0.1",
        ])
        assert args.pxe_server == "10.0.0.1"

    def test_dhcp_generate_with_domain(self):
        from pxeos.cli import _build_parser

        parser = _build_parser()
        args = parser.parse_args([
            "dhcp", "generate", "--domain", "example.com",
        ])
        assert args.domain == "example.com"

    def test_dhcp_generate_with_output_file(self):
        from pxeos.cli import _build_parser

        parser = _build_parser()
        args = parser.parse_args([
            "dhcp", "generate", "-o", "/tmp/dnsmasq.conf",
        ])
        assert args.output == Path("/tmp/dnsmasq.conf")

    def test_dhcp_generate_dns_only(self):
        from pxeos.cli import _build_parser

        parser = _build_parser()
        args = parser.parse_args([
            "dhcp", "generate", "--dns-only",
        ])
        assert args.dns_only is True

    def test_dhcp_generate_main_dnsmasq(self, tmp_path):
        """End-to-end: main() generates dnsmasq config from named hosts."""
        from pxeos.cli import main
        from pxeos.named_objects import NamedHost, NamedObjectStore

        # Set up named hosts
        named_dir = tmp_path / "named"
        named_dir.mkdir(parents=True)
        store = NamedObjectStore(named_dir)
        store.add_host(NamedHost(
            name="test01",
            mac="aa:bb:cc:dd:ee:01",
            ip_address="192.168.1.10",
            hostname="test01.local",
        ))

        config_path = tmp_path / "pxeos.toml"
        config_path.write_text(
            f'[paths]\ndata_dir = "{tmp_path}"\n'
        )

        output_file = tmp_path / "dnsmasq.conf"
        rc = main([
            "--config", str(config_path),
            "dhcp", "generate",
            "--pxe-server", "192.168.1.1",
            "-o", str(output_file),
        ])
        assert rc == 0
        assert output_file.exists()
        content = output_file.read_text()
        assert "dhcp-host=aa:bb:cc:dd:ee:01" in content
        assert "192.168.1.10" in content

    def test_dhcp_generate_main_isc(self, tmp_path):
        """End-to-end: main() generates ISC DHCP config from named hosts."""
        from pxeos.cli import main
        from pxeos.named_objects import NamedHost, NamedObjectStore

        named_dir = tmp_path / "named"
        named_dir.mkdir(parents=True)
        store = NamedObjectStore(named_dir)
        store.add_host(NamedHost(
            name="test01",
            mac="aa:bb:cc:dd:ee:01",
            ip_address="192.168.1.10",
            hostname="test01.local",
        ))

        config_path = tmp_path / "pxeos.toml"
        config_path.write_text(
            f'[paths]\ndata_dir = "{tmp_path}"\n'
        )

        output_file = tmp_path / "dhcpd.conf"
        rc = main([
            "--config", str(config_path),
            "dhcp", "generate",
            "--format", "isc-dhcp",
            "--pxe-server", "192.168.1.1",
            "--subnet", "192.168.1.0",
            "-o", str(output_file),
        ])
        assert rc == 0
        assert output_file.exists()
        content = output_file.read_text()
        assert "host test01 {" in content
        assert "hardware ethernet aa:bb:cc:dd:ee:01;" in content
        assert "subnet 192.168.1.0" in content

    def test_dhcp_generate_main_dns_only(self, tmp_path):
        """End-to-end: main() with --dns-only flag."""
        from pxeos.cli import main
        from pxeos.named_objects import NamedHost, NamedObjectStore

        named_dir = tmp_path / "named"
        named_dir.mkdir(parents=True)
        store = NamedObjectStore(named_dir)
        store.add_host(NamedHost(
            name="test01",
            mac="aa:bb:cc:dd:ee:01",
            ip_address="192.168.1.10",
            hostname="test01.local",
        ))

        config_path = tmp_path / "pxeos.toml"
        config_path.write_text(
            f'[paths]\ndata_dir = "{tmp_path}"\n'
        )

        output_file = tmp_path / "dns.conf"
        rc = main([
            "--config", str(config_path),
            "dhcp", "generate",
            "--dns-only",
            "-o", str(output_file),
        ])
        assert rc == 0
        content = output_file.read_text()
        assert "address=/test01.local/192.168.1.10" in content

    def test_dhcp_generate_stdout(self, tmp_path, capsys):
        """Without -o, output goes to stdout."""
        from pxeos.cli import main
        from pxeos.named_objects import NamedHost, NamedObjectStore

        named_dir = tmp_path / "named"
        named_dir.mkdir(parents=True)
        store = NamedObjectStore(named_dir)
        store.add_host(NamedHost(
            name="test01",
            mac="aa:bb:cc:dd:ee:01",
            ip_address="192.168.1.10",
            hostname="test01.local",
        ))

        config_path = tmp_path / "pxeos.toml"
        config_path.write_text(
            f'[paths]\ndata_dir = "{tmp_path}"\n'
        )

        rc = main([
            "--config", str(config_path),
            "dhcp", "generate",
        ])
        assert rc == 0
        captured = capsys.readouterr()
        assert "dhcp-host=aa:bb:cc:dd:ee:01" in captured.out

    def test_dhcp_no_action_prints_usage(self, tmp_path, capsys):
        """'pxeos dhcp' without subcommand prints usage."""
        from pxeos.cli import main

        config_path = tmp_path / "pxeos.toml"
        config_path.write_text(
            f'[paths]\ndata_dir = "{tmp_path}"\n'
        )

        rc = main([
            "--config", str(config_path),
            "dhcp",
        ])
        assert rc == 1

    def test_dhcp_generate_no_hosts(self, tmp_path, capsys):
        """Generate with no registered hosts produces placeholder."""
        from pxeos.cli import main

        # Create the named dir so NamedObjectStore can initialize
        named_dir = tmp_path / "named"
        named_dir.mkdir(parents=True)
        (named_dir / "hosts").mkdir(parents=True)
        (named_dir / "distros").mkdir(parents=True)

        config_path = tmp_path / "pxeos.toml"
        config_path.write_text(
            f'[paths]\ndata_dir = "{tmp_path}"\n'
        )

        rc = main([
            "--config", str(config_path),
            "dhcp", "generate",
        ])
        assert rc == 0
        captured = capsys.readouterr()
        assert "No hosts registered" in captured.out
