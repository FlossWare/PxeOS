"""Tests for pxeos.cobbler_import -- Cobbler data migration to PxeOS."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pxeos.cobbler_import import (
    ImportReport,
    import_cobbler_data,
    parse_distros,
    parse_profiles,
    parse_systems,
)
from pxeos.registry import PluginRegistry


# ---------------------------------------------------------------------------
# parse_distros
# ---------------------------------------------------------------------------


class TestParseDistros:

    def test_parses_list_of_distros(self):
        data = [
            {
                "name": "fedora40-x86_64",
                "breed": "redhat",
                "os_version": "40",
                "arch": "x86_64",
                "kernel": "/var/lib/cobbler/distros/fedora40/vmlinuz",
                "initrd": "/var/lib/cobbler/distros/fedora40/initrd.img",
            },
            {
                "name": "ubuntu2404-x86_64",
                "breed": "ubuntu",
                "os_version": "24.04",
                "arch": "x86_64",
                "kernel": "/var/lib/cobbler/distros/ubuntu2404/vmlinuz",
                "initrd": "/var/lib/cobbler/distros/ubuntu2404/initrd",
            },
        ]

        distros = parse_distros(data)
        assert len(distros) == 2
        assert distros[0].name == "fedora40-x86_64"
        assert distros[0].os_family == "fedora"
        assert distros[0].os_version == "40"
        assert distros[1].name == "ubuntu2404-x86_64"
        assert distros[1].os_family == "ubuntu"

    def test_parses_dict_format(self):
        data = {
            "rhel9": {
                "name": "rhel9-x86_64",
                "breed": "redhat",
                "os_version": "9",
                "arch": "x86_64",
                "kernel": "/vmlinuz",
                "initrd": "/initrd.img",
            }
        }

        distros = parse_distros(data)
        assert len(distros) == 1
        assert distros[0].name == "rhel9-x86_64"
        assert distros[0].os_family == "fedora"

    def test_guesses_os_family_from_name(self):
        data = [{"name": "rocky9-x86_64", "breed": ""}]
        distros = parse_distros(data)
        assert distros[0].os_family == "fedora"

    def test_guesses_version_from_name(self):
        data = [{"name": "debian12-x86_64", "breed": "debian"}]
        distros = parse_distros(data)
        assert distros[0].os_version == "12"

    def test_skips_entries_without_name(self):
        data = [{"breed": "redhat"}]
        distros = parse_distros(data)
        assert len(distros) == 0

    def test_handles_empty_data(self):
        assert parse_distros([]) == []
        assert parse_distros({}) == []

    def test_handles_single_dict(self):
        data = {
            "name": "suse15",
            "breed": "suse",
            "os_version": "15",
        }
        distros = parse_distros(data)
        assert len(distros) == 1
        assert distros[0].os_family == "suse"


# ---------------------------------------------------------------------------
# parse_profiles
# ---------------------------------------------------------------------------


class TestParseProfiles:

    def test_parses_list_of_profiles(self):
        data = [
            {
                "name": "webserver",
                "distro": "fedora40-x86_64",
                "kickstart": "/var/lib/cobbler/kickstarts/web.ks",
                "comment": "Web server profile",
            },
            {
                "name": "database",
                "distro": "rhel9-x86_64",
                "autoinstall": "/var/lib/cobbler/autoinstalls/db.cfg",
            },
        ]

        profiles = parse_profiles(data)
        assert len(profiles) == 2
        assert profiles[0].name == "webserver"
        assert profiles[0].distro == "fedora40-x86_64"
        assert "web.ks" in profiles[0].kickstart
        assert profiles[1].name == "database"

    def test_parses_dict_kernel_options(self):
        data = [
            {
                "name": "custom",
                "distro": "fedora40",
                "kernel_options": {"console": "ttyS0", "net.ifnames": "0"},
            },
        ]

        profiles = parse_profiles(data)
        assert "console=ttyS0" in profiles[0].kernel_options

    def test_skips_entries_without_name(self):
        data = [{"distro": "fedora40"}]
        profiles = parse_profiles(data)
        assert len(profiles) == 0

    def test_handles_empty_data(self):
        assert parse_profiles([]) == []


# ---------------------------------------------------------------------------
# parse_systems
# ---------------------------------------------------------------------------


class TestParseSystems:

    def test_parses_systems_with_interfaces(self):
        data = [
            {
                "name": "web-01",
                "profile": "webserver",
                "hostname": "web-01.example.com",
                "gateway": "10.0.0.1",
                "interfaces": {
                    "eth0": {
                        "mac_address": "aa:bb:cc:dd:ee:ff",
                        "ip_address": "10.0.0.10",
                        "netmask": "255.255.255.0",
                    }
                },
            }
        ]

        systems = parse_systems(data)
        assert len(systems) == 1
        assert systems[0].name == "web-01"
        assert systems[0].mac == "aa:bb:cc:dd:ee:ff"
        assert systems[0].ip_address == "10.0.0.10"
        assert systems[0].hostname == "web-01.example.com"
        assert systems[0].gateway == "10.0.0.1"

    def test_parses_top_level_mac(self):
        data = [
            {
                "name": "db-01",
                "profile": "database",
                "mac_address": "11:22:33:44:55:66",
            }
        ]

        systems = parse_systems(data)
        assert systems[0].mac == "11:22:33:44:55:66"

    def test_extracts_dns_name_as_hostname(self):
        data = [
            {
                "name": "app-01",
                "profile": "webserver",
                "interfaces": {
                    "eth0": {
                        "mac_address": "aa:bb:cc:11:22:33",
                        "dns_name": "app-01.local",
                    }
                },
            }
        ]

        systems = parse_systems(data)
        assert systems[0].hostname == "app-01.local"

    def test_skips_entries_without_name(self):
        data = [{"profile": "webserver"}]
        systems = parse_systems(data)
        assert len(systems) == 0

    def test_handles_empty_data(self):
        assert parse_systems([]) == []

    def test_handles_missing_interfaces(self):
        data = [
            {
                "name": "bare-01",
                "profile": "default",
            }
        ]

        systems = parse_systems(data)
        assert len(systems) == 1
        assert systems[0].mac == ""


# ---------------------------------------------------------------------------
# import_cobbler_data (integration)
# ---------------------------------------------------------------------------


class TestImportCobblerData:

    @pytest.fixture
    def registry(self):
        reg = PluginRegistry()
        reg.load_builtins()
        return reg

    def test_imports_all_three_types(self, tmp_path, registry):
        export_dir = tmp_path / "cobbler_export"
        export_dir.mkdir()
        data_dir = tmp_path / "pxeos_data"
        data_dir.mkdir()

        # Write distros
        distros = [
            {
                "name": "fedora40-x86_64",
                "breed": "redhat",
                "os_version": "40",
                "arch": "x86_64",
                "kernel": "/vmlinuz",
                "initrd": "/initrd.img",
            }
        ]
        (export_dir / "distros.json").write_text(json.dumps(distros))

        # Write profiles
        profiles = [
            {
                "name": "webserver",
                "distro": "fedora40-x86_64",
                "kickstart": "/var/lib/cobbler/ks/web.ks",
            }
        ]
        (export_dir / "profiles.json").write_text(json.dumps(profiles))

        # Write systems
        systems = [
            {
                "name": "web-01",
                "profile": "webserver",
                "interfaces": {
                    "eth0": {"mac_address": "aa:bb:cc:dd:ee:ff"}
                },
            }
        ]
        (export_dir / "systems.json").write_text(json.dumps(systems))

        report = import_cobbler_data(export_dir, registry, data_dir)

        assert report.distros_imported == 1
        assert report.profiles_imported == 1
        assert report.systems_imported == 1
        assert len(report.errors) == 0

        # Check profile TOML was written
        profile_path = data_dir / "profiles" / "webserver.toml"
        assert profile_path.exists()
        content = profile_path.read_text()
        assert 'name = "webserver"' in content
        assert 'os_family = "fedora"' in content

        # Check hosts were written
        hosts_path = data_dir / "hosts.toml"
        assert hosts_path.exists()
        hosts_content = hosts_path.read_text()
        assert "aa:bb:cc:dd:ee:ff" in hosts_content

    def test_nonexistent_export_dir(self, tmp_path, registry):
        data_dir = tmp_path / "pxeos_data"
        data_dir.mkdir()

        report = import_cobbler_data(
            tmp_path / "nonexistent", registry, data_dir
        )
        assert len(report.errors) == 1
        assert "does not exist" in report.errors[0]

    def test_missing_distros_file(self, tmp_path, registry):
        export_dir = tmp_path / "export"
        export_dir.mkdir()
        data_dir = tmp_path / "data"
        data_dir.mkdir()

        report = import_cobbler_data(export_dir, registry, data_dir)
        assert any("no distros file" in w for w in report.warnings)

    def test_profile_referencing_unknown_distro(self, tmp_path, registry):
        export_dir = tmp_path / "export"
        export_dir.mkdir()
        data_dir = tmp_path / "data"
        data_dir.mkdir()

        profiles = [
            {"name": "orphan", "distro": "nonexistent-distro"}
        ]
        (export_dir / "profiles.json").write_text(json.dumps(profiles))
        (export_dir / "distros.json").write_text("[]")
        (export_dir / "systems.json").write_text("[]")

        report = import_cobbler_data(export_dir, registry, data_dir)
        assert any("unknown distro" in w for w in report.warnings)

    def test_yaml_format(self, tmp_path, registry):
        """Test importing YAML format (falls back to JSON parser)."""
        export_dir = tmp_path / "export"
        export_dir.mkdir()
        data_dir = tmp_path / "data"
        data_dir.mkdir()

        # JSON with .yaml extension still works
        distros = [
            {"name": "test", "breed": "debian", "os_version": "12"}
        ]
        (export_dir / "distros.yaml").write_text(json.dumps(distros))

        report = import_cobbler_data(export_dir, registry, data_dir)
        assert report.distros_imported == 1
