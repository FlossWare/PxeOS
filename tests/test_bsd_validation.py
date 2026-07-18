"""Comprehensive validation tests for BSD plugins: FreeBSD, OpenBSD, NetBSD, DragonFlyBSD.

Covers: mirror selection, filesystem options, package management,
network configuration, firstboot/post-install scripts, boot args,
ISO extraction paths, and profile validation edge cases.

References GitHub issue #27.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pxeos.models import BootFirmware, ProvisionProfile
from pxeos.plugins.dragonflybsd import DragonFlyBSDPlugin
from pxeos.plugins.freebsd import FreeBSDPlugin
from pxeos.plugins.netbsd import NetBSDPlugin
from pxeos.plugins.openbsd import OpenBSDPlugin, _version_tag


# ── helpers ──────────────────────────────────────────────────────────

def _fbsd(**overrides) -> ProvisionProfile:
    defaults = dict(
        name="fbsd-test",
        os_family="freebsd",
        os_version="14.1",
        arch="amd64",
        install_url="http://mirror.example.com/freebsd/14.1",
    )
    defaults.update(overrides)
    return ProvisionProfile(**defaults)


def _obsd(**overrides) -> ProvisionProfile:
    defaults = dict(
        name="obsd-test",
        os_family="openbsd",
        os_version="7.6",
        arch="amd64",
        install_url="http://cdn.openbsd.org/pub/OpenBSD",
    )
    defaults.update(overrides)
    return ProvisionProfile(**defaults)


def _nbsd(**overrides) -> ProvisionProfile:
    defaults = dict(
        name="nbsd-test",
        os_family="netbsd",
        os_version="10.0",
        arch="amd64",
        install_url="http://cdn.netbsd.org/pub/NetBSD",
    )
    defaults.update(overrides)
    return ProvisionProfile(**defaults)


def _dbsd(**overrides) -> ProvisionProfile:
    defaults = dict(
        name="dbsd-test",
        os_family="dragonflybsd",
        os_version="6.4",
        arch="x86_64",
        install_url="http://mirror.example.com/dragonflybsd/6.4",
    )
    defaults.update(overrides)
    return ProvisionProfile(**defaults)


# ═══════════════════════════════════════════════════════════════════
#  FREEBSD
# ═══════════════════════════════════════════════════════════════════


class TestFreeBSDMirrorSelection:
    """Verify FreeBSD mirror/install URL is correctly injected."""

    @pytest.fixture
    def plugin(self) -> FreeBSDPlugin:
        return FreeBSDPlugin()

    def test_install_url_in_distsite(self, plugin: FreeBSDPlugin) -> None:
        profile = _fbsd(install_url="http://ftp.freebsd.org/pub/FreeBSD/releases/14.1-RELEASE")
        output = plugin.generate_autoinstall(profile)
        assert "BSDINSTALL_DISTSITE" in output
        assert "ftp.freebsd.org" in output

    def test_custom_mirror(self, plugin: FreeBSDPlugin) -> None:
        profile = _fbsd(install_url="http://internal-mirror.local/freebsd")
        output = plugin.generate_autoinstall(profile)
        assert "internal-mirror.local" in output

    def test_install_url_required(self, plugin: FreeBSDPlugin) -> None:
        profile = _fbsd(install_url="")
        errors = plugin.validate_profile(profile)
        assert any("install_url" in e for e in errors)


class TestFreeBSDFilesystem:
    """Verify ZFS and UFS configuration branches."""

    @pytest.fixture
    def plugin(self) -> FreeBSDPlugin:
        return FreeBSDPlugin()

    def test_zfs_default(self, plugin: FreeBSDPlugin) -> None:
        profile = _fbsd(disk={"filesystem": "zfs", "device": "ada0"})
        output = plugin.generate_autoinstall(profile)
        assert "ZFSBOOT_DISKS" in output
        assert "ada0" in output

    def test_zfs_custom_pool_name(self, plugin: FreeBSDPlugin) -> None:
        profile = _fbsd(disk={"filesystem": "zfs", "pool_name": "datapool", "device": "da0"})
        output = plugin.generate_autoinstall(profile)
        assert 'ZFSBOOT_POOL_NAME="datapool"' in output

    def test_zfs_default_pool_name(self, plugin: FreeBSDPlugin) -> None:
        profile = _fbsd(disk={"filesystem": "zfs"})
        output = plugin.generate_autoinstall(profile)
        assert 'ZFSBOOT_POOL_NAME="zroot"' in output

    def test_zfs_has_swap(self, plugin: FreeBSDPlugin) -> None:
        profile = _fbsd(disk={"filesystem": "zfs"})
        output = plugin.generate_autoinstall(profile)
        assert "ZFSBOOT_SWAP_SIZE" in output

    def test_ufs_partitions(self, plugin: FreeBSDPlugin) -> None:
        profile = _fbsd(disk={"filesystem": "ufs", "device": "da0"})
        output = plugin.generate_autoinstall(profile)
        assert "PARTITIONS=" in output
        assert "da0" in output
        assert "ZFSBOOT_DISKS" not in output

    def test_invalid_filesystem(self, plugin: FreeBSDPlugin) -> None:
        profile = _fbsd(disk={"filesystem": "btrfs"})
        errors = plugin.validate_profile(profile)
        assert any("unsupported filesystem" in e for e in errors)

    def test_no_filesystem_defaults_zfs(self, plugin: FreeBSDPlugin) -> None:
        profile = _fbsd(disk={})
        output = plugin.generate_autoinstall(profile)
        assert "ZFSBOOT_DISKS" in output


class TestFreeBSDPkgBootstrap:
    """Verify pkg bootstrap and package installation."""

    @pytest.fixture
    def plugin(self) -> FreeBSDPlugin:
        return FreeBSDPlugin()

    def test_pkg_bootstrap_with_packages(self, plugin: FreeBSDPlugin) -> None:
        profile = _fbsd(packages=["nginx", "python3"])
        output = plugin.generate_autoinstall(profile)
        assert "pkg bootstrap -f" in output
        assert "pkg install -y nginx" in output
        assert "pkg install -y python3" in output

    def test_no_pkg_bootstrap_without_packages(self, plugin: FreeBSDPlugin) -> None:
        profile = _fbsd(packages=[])
        output = plugin.generate_autoinstall(profile)
        assert "pkg bootstrap" not in output

    def test_single_package(self, plugin: FreeBSDPlugin) -> None:
        profile = _fbsd(packages=["vim"])
        output = plugin.generate_autoinstall(profile)
        assert "pkg install -y vim" in output


class TestFreeBSDNetwork:
    """Verify FreeBSD network configuration (DHCP and static)."""

    @pytest.fixture
    def plugin(self) -> FreeBSDPlugin:
        return FreeBSDPlugin()

    def test_dhcp_default(self, plugin: FreeBSDPlugin) -> None:
        profile = _fbsd()
        output = plugin.generate_autoinstall(profile)
        assert 'ifconfig_em0="DHCP"' in output

    def test_custom_interface(self, plugin: FreeBSDPlugin) -> None:
        profile = _fbsd(network={"interface": "igb0", "dhcp": True})
        output = plugin.generate_autoinstall(profile)
        assert 'ifconfig_igb0="DHCP"' in output

    def test_static_ip(self, plugin: FreeBSDPlugin) -> None:
        profile = _fbsd(
            network={
                "dhcp": False,
                "interface": "em0",
                "address": "10.0.0.10",
                "netmask": "255.255.255.0",
                "gateway": "10.0.0.1",
                "nameservers": ["10.0.0.2"],
            },
        )
        output = plugin.generate_autoinstall(profile)
        assert "10.0.0.10" in output
        assert "10.0.0.1" in output
        assert "DHCP" not in output

    def test_hostname_from_network(self, plugin: FreeBSDPlugin) -> None:
        profile = _fbsd(network={"hostname": "web01"})
        output = plugin.generate_autoinstall(profile)
        assert "web01" in output

    def test_hostname_fallback_to_name(self, plugin: FreeBSDPlugin) -> None:
        profile = _fbsd(name="fallback-host")
        output = plugin.generate_autoinstall(profile)
        assert "fallback-host" in output

    def test_domain_in_resolv(self, plugin: FreeBSDPlugin) -> None:
        profile = _fbsd(network={"domain": "example.com"})
        output = plugin.generate_autoinstall(profile)
        assert "search example.com" in output

    def test_multiple_nameservers(self, plugin: FreeBSDPlugin) -> None:
        profile = _fbsd(network={"nameservers": ["1.1.1.1", "8.8.8.8", "9.9.9.9"]})
        output = plugin.generate_autoinstall(profile)
        assert "nameserver 1.1.1.1" in output
        assert "nameserver 8.8.8.8" in output
        assert "nameserver 9.9.9.9" in output


class TestFreeBSDPostScripts:
    """Verify FreeBSD post-install script rendering."""

    @pytest.fixture
    def plugin(self) -> FreeBSDPlugin:
        return FreeBSDPlugin()

    def test_post_scripts_rendered(self, plugin: FreeBSDPlugin) -> None:
        profile = _fbsd(post_scripts=["echo done", "reboot"])
        output = plugin.generate_autoinstall(profile)
        assert "echo done" in output
        assert "reboot" in output

    def test_no_post_scripts(self, plugin: FreeBSDPlugin) -> None:
        profile = _fbsd(post_scripts=[])
        output = plugin.generate_autoinstall(profile)
        # Should still render the rest without error
        assert "#!/bin/sh" in output


class TestFreeBSDServices:
    """Verify FreeBSD service enablement."""

    @pytest.fixture
    def plugin(self) -> FreeBSDPlugin:
        return FreeBSDPlugin()

    def test_default_services(self, plugin: FreeBSDPlugin) -> None:
        profile = _fbsd()
        output = plugin.generate_autoinstall(profile)
        assert 'sshd_enable="YES"' in output
        assert 'ntpd_enable="YES"' in output

    def test_custom_services(self, plugin: FreeBSDPlugin) -> None:
        profile = _fbsd(extra={"services": ["sshd", "nginx", "postgresql"]})
        output = plugin.generate_autoinstall(profile)
        assert 'nginx_enable="YES"' in output
        assert 'postgresql_enable="YES"' in output

    def test_sendmail_disabled(self, plugin: FreeBSDPlugin) -> None:
        profile = _fbsd()
        output = plugin.generate_autoinstall(profile)
        assert 'sendmail_enable="NONE"' in output


class TestFreeBSDBootArgs:
    """Verify FreeBSD boot assets and args."""

    @pytest.fixture
    def plugin(self) -> FreeBSDPlugin:
        return FreeBSDPlugin()

    def test_bios_kernel_pxeboot(self, plugin: FreeBSDPlugin) -> None:
        profile = _fbsd(firmware=BootFirmware.BIOS)
        assets = plugin.boot_assets(profile)
        assert assets.kernel.endswith("/boot/pxeboot")

    def test_uefi_kernel_loader_efi(self, plugin: FreeBSDPlugin) -> None:
        profile = _fbsd(firmware=BootFirmware.UEFI)
        assets = plugin.boot_assets(profile)
        assert assets.kernel.endswith("/boot/loader.efi")

    def test_no_initrd(self, plugin: FreeBSDPlugin) -> None:
        profile = _fbsd()
        assets = plugin.boot_assets(profile)
        assert assets.initrd is None

    def test_nfsroot_args(self, plugin: FreeBSDPlugin) -> None:
        profile = _fbsd()
        assets = plugin.boot_assets(profile)
        assert any("boot.nfsroot.server=" in a for a in assets.boot_args)
        assert any("boot.nfsroot.path=" in a for a in assets.boot_args)

    def test_nfsroot_path_includes_version_and_arch(self, plugin: FreeBSDPlugin) -> None:
        profile = _fbsd(os_version="14.2", arch="amd64")
        assets = plugin.boot_assets(profile)
        nfs_path = [a for a in assets.boot_args if "nfsroot.path=" in a][0]
        assert "14.2" in nfs_path
        assert "amd64" in nfs_path

    def test_bootloader_config_mentions_version(self, plugin: FreeBSDPlugin) -> None:
        profile = _fbsd(os_version="13.4")
        assets = plugin.boot_assets(profile)
        assert "13.4" in assets.bootloader_config

    def test_all_versions_valid(self, plugin: FreeBSDPlugin) -> None:
        for v in plugin.supported_versions:
            profile = _fbsd(os_version=v)
            errors = plugin.validate_profile(profile)
            assert errors == [], f"Version {v} should be valid"


class TestFreeBSDArchValidation:
    """Verify FreeBSD architecture validation."""

    @pytest.fixture
    def plugin(self) -> FreeBSDPlugin:
        return FreeBSDPlugin()

    def test_amd64_valid(self, plugin: FreeBSDPlugin) -> None:
        profile = _fbsd(arch="amd64")
        errors = plugin.validate_profile(profile)
        assert not any("architecture" in e for e in errors)

    def test_i386_valid(self, plugin: FreeBSDPlugin) -> None:
        profile = _fbsd(arch="i386")
        errors = plugin.validate_profile(profile)
        assert not any("architecture" in e for e in errors)

    def test_aarch64_valid(self, plugin: FreeBSDPlugin) -> None:
        profile = _fbsd(arch="aarch64")
        errors = plugin.validate_profile(profile)
        assert not any("architecture" in e for e in errors)

    def test_sparc64_invalid(self, plugin: FreeBSDPlugin) -> None:
        profile = _fbsd(arch="sparc64")
        errors = plugin.validate_profile(profile)
        assert any("unsupported architecture" in e for e in errors)


class TestFreeBSDExtractFromIso:
    """Verify FreeBSD ISO extraction."""

    @pytest.fixture
    def plugin(self) -> FreeBSDPlugin:
        return FreeBSDPlugin()

    def test_copies_pxeboot(self, plugin: FreeBSDPlugin, tmp_path: Path) -> None:
        mount = tmp_path / "mount"
        dest = tmp_path / "dest"
        boot_dir = mount / "boot"
        boot_dir.mkdir(parents=True)
        (boot_dir / "pxeboot").write_bytes(b"PXEBOOT")

        assets = plugin.extract_from_iso(mount, dest)
        assert assets.kernel_path == dest / "boot" / "pxeboot"
        assert assets.kernel_path.exists()

    def test_copies_loader_efi(self, plugin: FreeBSDPlugin, tmp_path: Path) -> None:
        mount = tmp_path / "mount"
        dest = tmp_path / "dest"
        boot_dir = mount / "boot"
        boot_dir.mkdir(parents=True)
        (boot_dir / "loader.efi").write_bytes(b"LOADER")

        assets = plugin.extract_from_iso(mount, dest)
        assert assets.boot_loader_path == dest / "boot" / "loader.efi"

    def test_copies_dist_sets(self, plugin: FreeBSDPlugin, tmp_path: Path) -> None:
        mount = tmp_path / "mount"
        dest = tmp_path / "dest"
        (mount / "boot").mkdir(parents=True)
        dist_dir = mount / "usr" / "freebsd-dist"
        dist_dir.mkdir(parents=True)
        (dist_dir / "base.txz").write_bytes(b"BASE")
        (dist_dir / "kernel.txz").write_bytes(b"KERNEL")

        assets = plugin.extract_from_iso(mount, dest)
        assert (dest / "repo" / "base.txz").exists()
        assert (dest / "repo" / "kernel.txz").exists()

    def test_missing_loader_returns_none(self, plugin: FreeBSDPlugin, tmp_path: Path) -> None:
        mount = tmp_path / "mount"
        dest = tmp_path / "dest"
        boot_dir = mount / "boot"
        boot_dir.mkdir(parents=True)
        (boot_dir / "pxeboot").write_bytes(b"PXEBOOT")

        assets = plugin.extract_from_iso(mount, dest)
        assert assets.boot_loader_path is None

    def test_no_initrd(self, plugin: FreeBSDPlugin, tmp_path: Path) -> None:
        mount = tmp_path / "mount"
        dest = tmp_path / "dest"
        mount.mkdir(parents=True)

        assets = plugin.extract_from_iso(mount, dest)
        assert assets.initrd_path is None


class TestFreeBSDDistributions:
    """Verify FreeBSD distribution set configuration."""

    @pytest.fixture
    def plugin(self) -> FreeBSDPlugin:
        return FreeBSDPlugin()

    def test_default_distributions(self, plugin: FreeBSDPlugin) -> None:
        profile = _fbsd()
        output = plugin.generate_autoinstall(profile)
        assert 'DISTRIBUTIONS="base.txz kernel.txz"' in output

    def test_custom_distributions(self, plugin: FreeBSDPlugin) -> None:
        profile = _fbsd(disk={"distributions": "base.txz kernel.txz lib32.txz ports.txz"})
        output = plugin.generate_autoinstall(profile)
        assert "lib32.txz" in output
        assert "ports.txz" in output


class TestFreeBSDTimezone:
    """Verify FreeBSD timezone setup."""

    @pytest.fixture
    def plugin(self) -> FreeBSDPlugin:
        return FreeBSDPlugin()

    def test_default_timezone(self, plugin: FreeBSDPlugin) -> None:
        profile = _fbsd()
        output = plugin.generate_autoinstall(profile)
        assert "tzsetup -s UTC" in output

    def test_custom_timezone(self, plugin: FreeBSDPlugin) -> None:
        profile = _fbsd(extra={"timezone": "America/New_York"})
        output = plugin.generate_autoinstall(profile)
        assert "tzsetup -s America/New_York" in output


# ═══════════════════════════════════════════════════════════════════
#  OPENBSD
# ═══════════════════════════════════════════════════════════════════


class TestOpenBSDVersionTag:
    """Verify the _version_tag helper."""

    def test_75(self) -> None:
        assert _version_tag("7.5") == "75"

    def test_76(self) -> None:
        assert _version_tag("7.6") == "76"

    def test_74(self) -> None:
        assert _version_tag("7.4") == "74"


class TestOpenBSDAutoinstallFormat:
    """Verify OpenBSD install.conf key=value format."""

    @pytest.fixture
    def plugin(self) -> OpenBSDPlugin:
        return OpenBSDPlugin()

    def test_key_value_format(self, plugin: OpenBSDPlugin) -> None:
        profile = _obsd()
        output = plugin.generate_autoinstall(profile)
        assert "System hostname =" in output
        assert "Password for root account =" in output

    def test_hostname_with_domain(self, plugin: OpenBSDPlugin) -> None:
        profile = _obsd(network={"hostname": "fw01", "domain": "corp.local"})
        output = plugin.generate_autoinstall(profile)
        assert "System hostname = fw01.corp.local" in output

    def test_dns_domain(self, plugin: OpenBSDPlugin) -> None:
        profile = _obsd(network={"domain": "test.org"})
        output = plugin.generate_autoinstall(profile)
        assert "DNS domain name = test.org" in output


class TestOpenBSDSetsSelection:
    """Verify OpenBSD distribution set selection."""

    @pytest.fixture
    def plugin(self) -> OpenBSDPlugin:
        return OpenBSDPlugin()

    def test_default_sets_include_version_tag(self, plugin: OpenBSDPlugin) -> None:
        profile = _obsd(os_version="7.6")
        output = plugin.generate_autoinstall(profile)
        assert "base76.tgz" in output
        assert "comp76.tgz" in output

    def test_custom_sets(self, plugin: OpenBSDPlugin) -> None:
        profile = _obsd(
            extra={"sets": ["base76.tgz", "comp76.tgz", "man76.tgz"]},
        )
        output = plugin.generate_autoinstall(profile)
        assert "man76.tgz" in output

    def test_x11_not_excluded_when_enabled(self, plugin: OpenBSDPlugin) -> None:
        profile = _obsd(extra={"x11": True})
        output = plugin.generate_autoinstall(profile)
        assert "-x*" not in output

    def test_x11_excluded_by_default(self, plugin: OpenBSDPlugin) -> None:
        profile = _obsd()
        output = plugin.generate_autoinstall(profile)
        assert "-x*" in output

    def test_sets_for_75(self, plugin: OpenBSDPlugin) -> None:
        profile = _obsd(os_version="7.5")
        output = plugin.generate_autoinstall(profile)
        assert "base75.tgz" in output


class TestOpenBSDMirror:
    """Verify OpenBSD HTTP server and directory parsing."""

    @pytest.fixture
    def plugin(self) -> OpenBSDPlugin:
        return OpenBSDPlugin()

    def test_http_location_set(self, plugin: OpenBSDPlugin) -> None:
        profile = _obsd(install_url="http://cdn.openbsd.org/pub/OpenBSD")
        output = plugin.generate_autoinstall(profile)
        assert "Location of sets = http" in output

    def test_http_server_parsed(self, plugin: OpenBSDPlugin) -> None:
        profile = _obsd(install_url="http://cdn.openbsd.org/pub/OpenBSD")
        output = plugin.generate_autoinstall(profile)
        assert "HTTP Server = cdn.openbsd.org" in output

    def test_server_directory_from_path(self, plugin: OpenBSDPlugin) -> None:
        profile = _obsd(install_url="http://cdn.openbsd.org/pub/OpenBSD/7.6/amd64")
        output = plugin.generate_autoinstall(profile)
        assert "Server directory = pub/OpenBSD/7.6/amd64" in output

    def test_cd_location_when_no_url(self, plugin: OpenBSDPlugin) -> None:
        profile = _obsd(install_url="")
        output = plugin.generate_autoinstall(profile)
        assert "Location of sets = cd0" in output

    def test_custom_mirror(self, plugin: OpenBSDPlugin) -> None:
        profile = _obsd(install_url="http://ftp.eu.openbsd.org/pub/OpenBSD")
        output = plugin.generate_autoinstall(profile)
        assert "HTTP Server = ftp.eu.openbsd.org" in output


class TestOpenBSDNetwork:
    """Verify OpenBSD network configuration."""

    @pytest.fixture
    def plugin(self) -> OpenBSDPlugin:
        return OpenBSDPlugin()

    def test_dhcp_default(self, plugin: OpenBSDPlugin) -> None:
        profile = _obsd()
        output = plugin.generate_autoinstall(profile)
        assert "IPv4 address for em0 = dhcp" in output

    def test_static_ip(self, plugin: OpenBSDPlugin) -> None:
        profile = _obsd(
            network={
                "dhcp": False,
                "interface": "vio0",
                "address": "192.168.1.10",
                "netmask": "255.255.255.0",
                "gateway": "192.168.1.1",
            },
        )
        output = plugin.generate_autoinstall(profile)
        assert "IPv4 address for vio0 = 192.168.1.10" in output
        assert "Netmask for vio0 = 255.255.255.0" in output
        assert "Default IPv4 route = 192.168.1.1" in output

    def test_gateway_none_default(self, plugin: OpenBSDPlugin) -> None:
        profile = _obsd(network={"gateway": "none"})
        output = plugin.generate_autoinstall(profile)
        assert "Default IPv4 route = none" in output

    def test_custom_interface(self, plugin: OpenBSDPlugin) -> None:
        profile = _obsd(network={"interface": "vio0"})
        output = plugin.generate_autoinstall(profile)
        assert "Network interfaces = vio0" in output

    def test_nameservers_joined(self, plugin: OpenBSDPlugin) -> None:
        profile = _obsd(network={"nameservers": ["1.1.1.1", "8.8.8.8"]})
        output = plugin.generate_autoinstall(profile)
        assert "DNS nameservers = 1.1.1.1 8.8.8.8" in output


class TestOpenBSDDiskLayout:
    """Verify OpenBSD disk configuration."""

    @pytest.fixture
    def plugin(self) -> OpenBSDPlugin:
        return OpenBSDPlugin()

    def test_whole_disk_default(self, plugin: OpenBSDPlugin) -> None:
        profile = _obsd()
        output = plugin.generate_autoinstall(profile)
        assert "Which disk is the root disk = sd0" in output
        assert "= W" in output

    def test_gpt_layout(self, plugin: OpenBSDPlugin) -> None:
        profile = _obsd(disk={"layout": "gpt"})
        output = plugin.generate_autoinstall(profile)
        assert "= G" in output

    def test_custom_disk_device(self, plugin: OpenBSDPlugin) -> None:
        profile = _obsd(disk={"device": "wd0"})
        output = plugin.generate_autoinstall(profile)
        assert "Which disk is the root disk = wd0" in output

    def test_duid_enabled(self, plugin: OpenBSDPlugin) -> None:
        profile = _obsd()
        output = plugin.generate_autoinstall(profile)
        assert "Use DUIDs rather than device names in fstab = yes" in output


class TestOpenBSDUserCreation:
    """Verify OpenBSD user creation in install.conf."""

    @pytest.fixture
    def plugin(self) -> OpenBSDPlugin:
        return OpenBSDPlugin()

    def test_no_user_by_default(self, plugin: OpenBSDPlugin) -> None:
        profile = _obsd()
        output = plugin.generate_autoinstall(profile)
        assert "Setup a user = no" in output

    def test_user_creation(self, plugin: OpenBSDPlugin) -> None:
        profile = _obsd(extra={"user": "admin", "user_password": "s3cret"})
        output = plugin.generate_autoinstall(profile)
        assert "Setup a user = admin" in output
        assert "Password for user admin = s3cret" in output

    def test_root_ssh_allowed_by_default(self, plugin: OpenBSDPlugin) -> None:
        profile = _obsd()
        output = plugin.generate_autoinstall(profile)
        assert "Allow root ssh login = yes" in output

    def test_root_ssh_disabled(self, plugin: OpenBSDPlugin) -> None:
        profile = _obsd(extra={"root_ssh": False})
        output = plugin.generate_autoinstall(profile)
        assert "Allow root ssh login = no" in output

    def test_ssh_public_key(self, plugin: OpenBSDPlugin) -> None:
        profile = _obsd(extra={"public_ssh_key": "ssh-ed25519 AAAA... user@host"})
        output = plugin.generate_autoinstall(profile)
        assert "Public ssh key for root account = ssh-ed25519" in output


class TestOpenBSDBootAssets:
    """Verify OpenBSD boot assets."""

    @pytest.fixture
    def plugin(self) -> OpenBSDPlugin:
        return OpenBSDPlugin()

    def test_kernel_is_bsd_rd(self, plugin: OpenBSDPlugin) -> None:
        profile = _obsd()
        assets = plugin.boot_assets(profile)
        assert "bsd.rd" in assets.kernel

    def test_no_initrd(self, plugin: OpenBSDPlugin) -> None:
        """bsd.rd combines kernel and ramdisk; no separate initrd."""
        profile = _obsd()
        assets = plugin.boot_assets(profile)
        assert assets.initrd is None

    def test_kernel_path_includes_version_and_arch(self, plugin: OpenBSDPlugin) -> None:
        profile = _obsd(os_version="7.5", arch="amd64")
        assets = plugin.boot_assets(profile)
        assert "7.5/amd64/bsd.rd" in assets.kernel

    def test_tftproot_in_boot_args(self, plugin: OpenBSDPlugin) -> None:
        profile = _obsd()
        assets = plugin.boot_assets(profile)
        assert any("tftproot=" in a for a in assets.boot_args)

    def test_bios_vs_uefi_same_kernel(self, plugin: OpenBSDPlugin) -> None:
        """OpenBSD uses bsd.rd for both BIOS and UEFI boot."""
        bios = plugin.boot_assets(_obsd(firmware=BootFirmware.BIOS))
        uefi = plugin.boot_assets(_obsd(firmware=BootFirmware.UEFI))
        assert bios.kernel == uefi.kernel

    def test_bootloader_config_bios(self, plugin: OpenBSDPlugin) -> None:
        profile = _obsd(firmware=BootFirmware.BIOS)
        assets = plugin.boot_assets(profile)
        assert "BIOS" in assets.bootloader_config

    def test_bootloader_config_uefi(self, plugin: OpenBSDPlugin) -> None:
        profile = _obsd(firmware=BootFirmware.UEFI)
        assets = plugin.boot_assets(profile)
        assert "UEFI" in assets.bootloader_config


class TestOpenBSDValidation:
    """Verify OpenBSD profile validation edge cases."""

    @pytest.fixture
    def plugin(self) -> OpenBSDPlugin:
        return OpenBSDPlugin()

    def test_valid_profile(self, plugin: OpenBSDPlugin) -> None:
        profile = _obsd()
        assert plugin.validate_profile(profile) == []

    def test_missing_install_url(self, plugin: OpenBSDPlugin) -> None:
        profile = _obsd(install_url="")
        errors = plugin.validate_profile(profile)
        assert any("install_url" in e for e in errors)

    def test_arch_amd64_valid(self, plugin: OpenBSDPlugin) -> None:
        profile = _obsd(arch="amd64")
        assert not any("architecture" in e for e in plugin.validate_profile(profile))

    def test_arch_arm64_valid(self, plugin: OpenBSDPlugin) -> None:
        profile = _obsd(arch="arm64")
        assert not any("architecture" in e for e in plugin.validate_profile(profile))

    def test_arch_i386_valid(self, plugin: OpenBSDPlugin) -> None:
        profile = _obsd(arch="i386")
        assert not any("architecture" in e for e in plugin.validate_profile(profile))

    def test_arch_riscv_invalid(self, plugin: OpenBSDPlugin) -> None:
        profile = _obsd(arch="riscv64")
        errors = plugin.validate_profile(profile)
        assert any("unsupported architecture" in e for e in errors)

    def test_all_versions_valid(self, plugin: OpenBSDPlugin) -> None:
        for v in plugin.supported_versions:
            profile = _obsd(os_version=v)
            assert plugin.validate_profile(profile) == [], f"Version {v} should be valid"

    def test_unsupported_version(self, plugin: OpenBSDPlugin) -> None:
        profile = _obsd(os_version="6.9")
        errors = plugin.validate_profile(profile)
        assert any("unsupported version" in e for e in errors)


class TestOpenBSDExtractFromIso:
    """Verify OpenBSD ISO extraction."""

    @pytest.fixture
    def plugin(self) -> OpenBSDPlugin:
        return OpenBSDPlugin()

    def test_copies_bsd_rd_from_root(self, plugin: OpenBSDPlugin, tmp_path: Path) -> None:
        mount = tmp_path / "mount"
        dest = tmp_path / "dest"
        mount.mkdir(parents=True)
        (mount / "bsd.rd").write_bytes(b"BSD_RD")

        assets = plugin.extract_from_iso(mount, dest)
        assert assets.kernel_path == dest / "boot" / "bsd.rd"
        assert assets.kernel_path.exists()

    def test_copies_bsd_rd_from_version_dir(self, plugin: OpenBSDPlugin, tmp_path: Path) -> None:
        mount = tmp_path / "mount"
        dest = tmp_path / "dest"
        ver_dir = mount / "7.6" / "amd64"
        ver_dir.mkdir(parents=True)
        (ver_dir / "bsd.rd").write_bytes(b"BSD_RD_76")

        assets = plugin.extract_from_iso(mount, dest)
        assert assets.kernel_path.exists()

    def test_copies_tgz_sets(self, plugin: OpenBSDPlugin, tmp_path: Path) -> None:
        mount = tmp_path / "mount"
        dest = tmp_path / "dest"
        mount.mkdir(parents=True)
        (mount / "bsd.rd").write_bytes(b"BSD")
        (mount / "base76.tgz").write_bytes(b"BASE")
        (mount / "comp76.tgz").write_bytes(b"COMP")

        assets = plugin.extract_from_iso(mount, dest)
        assert (dest / "repo" / "base76.tgz").exists()
        assert (dest / "repo" / "comp76.tgz").exists()

    def test_no_bootloader(self, plugin: OpenBSDPlugin, tmp_path: Path) -> None:
        mount = tmp_path / "mount"
        dest = tmp_path / "dest"
        mount.mkdir(parents=True)

        assets = plugin.extract_from_iso(mount, dest)
        assert assets.boot_loader_path is None

    def test_no_initrd(self, plugin: OpenBSDPlugin, tmp_path: Path) -> None:
        mount = tmp_path / "mount"
        dest = tmp_path / "dest"
        mount.mkdir(parents=True)

        assets = plugin.extract_from_iso(mount, dest)
        assert assets.initrd_path is None


# ═══════════════════════════════════════════════════════════════════
#  NETBSD
# ═══════════════════════════════════════════════════════════════════


class TestNetBSDAutoinstallFormat:
    """Verify NetBSD auto_install.cfg format."""

    @pytest.fixture
    def plugin(self) -> NetBSDPlugin:
        return NetBSDPlugin()

    def test_hostname_format(self, plugin: NetBSDPlugin) -> None:
        profile = _nbsd(network={"hostname": "nb-server", "domain": "lab.local"})
        output = plugin.generate_autoinstall(profile)
        assert "hostname=nb-server.lab.local" in output

    def test_network_yes(self, plugin: NetBSDPlugin) -> None:
        profile = _nbsd()
        output = plugin.generate_autoinstall(profile)
        assert "network=yes" in output

    def test_reboot_yes(self, plugin: NetBSDPlugin) -> None:
        profile = _nbsd()
        output = plugin.generate_autoinstall(profile)
        assert "reboot=yes" in output

    def test_noverify(self, plugin: NetBSDPlugin) -> None:
        profile = _nbsd()
        output = plugin.generate_autoinstall(profile)
        assert "noverify=yes" in output


class TestNetBSDFilesystem:
    """Verify NetBSD filesystem configuration."""

    @pytest.fixture
    def plugin(self) -> NetBSDPlugin:
        return NetBSDPlugin()

    def test_ffs_default(self, plugin: NetBSDPlugin) -> None:
        profile = _nbsd()
        output = plugin.generate_autoinstall(profile)
        assert "filesystem=ffs" in output

    def test_lfs_supported(self, plugin: NetBSDPlugin) -> None:
        profile = _nbsd(disk={"filesystem": "lfs"})
        output = plugin.generate_autoinstall(profile)
        assert "filesystem=lfs" in output

    def test_zfs_invalid(self, plugin: NetBSDPlugin) -> None:
        profile = _nbsd(disk={"filesystem": "zfs"})
        errors = plugin.validate_profile(profile)
        assert any("unsupported filesystem" in e for e in errors)

    def test_custom_disk_device(self, plugin: NetBSDPlugin) -> None:
        profile = _nbsd(disk={"device": "sd0"})
        output = plugin.generate_autoinstall(profile)
        assert "disk=sd0" in output

    def test_default_disk_device(self, plugin: NetBSDPlugin) -> None:
        profile = _nbsd()
        output = plugin.generate_autoinstall(profile)
        assert "disk=wd0" in output

    def test_use_entire_disk_default(self, plugin: NetBSDPlugin) -> None:
        profile = _nbsd()
        output = plugin.generate_autoinstall(profile)
        assert "use_entire_disk=yes" in output

    def test_custom_disk_layout(self, plugin: NetBSDPlugin) -> None:
        profile = _nbsd(disk={"layout": "custom"})
        output = plugin.generate_autoinstall(profile)
        assert "use_entire_disk=no" in output


class TestNetBSDSetsAndPkgsrc:
    """Verify NetBSD distribution set and package management."""

    @pytest.fixture
    def plugin(self) -> NetBSDPlugin:
        return NetBSDPlugin()

    def test_default_sets(self, plugin: NetBSDPlugin) -> None:
        profile = _nbsd()
        output = plugin.generate_autoinstall(profile)
        assert "base.tgz" in output
        assert "comp.tgz" in output
        assert "etc.tgz" in output

    def test_kernel_set_for_amd64(self, plugin: NetBSDPlugin) -> None:
        profile = _nbsd(arch="amd64")
        output = plugin.generate_autoinstall(profile)
        assert "kern-GENERIC.tgz" in output

    def test_kernel_set_for_evbarm(self, plugin: NetBSDPlugin) -> None:
        profile = _nbsd(arch="evbarm")
        output = plugin.generate_autoinstall(profile)
        assert "kern-GENERIC64.tgz" in output

    def test_custom_sets(self, plugin: NetBSDPlugin) -> None:
        profile = _nbsd(extra={"sets": ["base.tgz", "kern-GENERIC.tgz"]})
        output = plugin.generate_autoinstall(profile)
        assert "base.tgz" in output
        assert "kern-GENERIC.tgz" in output

    def test_pkg_add_with_packages(self, plugin: NetBSDPlugin) -> None:
        profile = _nbsd(packages=["python311", "vim"])
        output = plugin.generate_autoinstall(profile)
        assert "pkg_add python311 vim" in output

    def test_no_packages(self, plugin: NetBSDPlugin) -> None:
        profile = _nbsd(packages=[])
        output = plugin.generate_autoinstall(profile)
        assert "pkg_add" not in output

    def test_fetch_url_set(self, plugin: NetBSDPlugin) -> None:
        profile = _nbsd(install_url="http://cdn.netbsd.org/pub/NetBSD")
        output = plugin.generate_autoinstall(profile)
        assert "fetch_url=http://cdn.netbsd.org/pub/NetBSD" in output


class TestNetBSDNetwork:
    """Verify NetBSD network configuration."""

    @pytest.fixture
    def plugin(self) -> NetBSDPlugin:
        return NetBSDPlugin()

    def test_dhcp_default(self, plugin: NetBSDPlugin) -> None:
        profile = _nbsd()
        output = plugin.generate_autoinstall(profile)
        assert "dhcp=wm0" in output

    def test_custom_interface_dhcp(self, plugin: NetBSDPlugin) -> None:
        profile = _nbsd(network={"interface": "re0", "dhcp": True})
        output = plugin.generate_autoinstall(profile)
        assert "dhcp=re0" in output

    def test_static_ip(self, plugin: NetBSDPlugin) -> None:
        profile = _nbsd(
            network={
                "dhcp": False,
                "interface": "wm0",
                "address": "10.0.0.5",
                "netmask": "255.255.255.0",
                "gateway": "10.0.0.1",
                "nameservers": ["10.0.0.2"],
            },
        )
        output = plugin.generate_autoinstall(profile)
        assert "interface=wm0" in output
        assert "ip_address=10.0.0.5" in output
        assert "netmask=255.255.255.0" in output
        assert "default_route=10.0.0.1" in output
        assert "dns_server=10.0.0.2" in output

    def test_dns_domain(self, plugin: NetBSDPlugin) -> None:
        profile = _nbsd(network={"domain": "nb.local"})
        output = plugin.generate_autoinstall(profile)
        assert "dns_domain=nb.local" in output


class TestNetBSDPostScripts:
    """Verify NetBSD post-install script rendering."""

    @pytest.fixture
    def plugin(self) -> NetBSDPlugin:
        return NetBSDPlugin()

    def test_post_scripts(self, plugin: NetBSDPlugin) -> None:
        profile = _nbsd(post_scripts=["echo hello", "touch /tmp/done"])
        output = plugin.generate_autoinstall(profile)
        assert "post_install_cmd=echo hello" in output
        assert "post_install_cmd=touch /tmp/done" in output

    def test_post_install_yes(self, plugin: NetBSDPlugin) -> None:
        profile = _nbsd()
        output = plugin.generate_autoinstall(profile)
        assert "post_install=yes" in output


class TestNetBSDBootAssets:
    """Verify NetBSD boot assets."""

    @pytest.fixture
    def plugin(self) -> NetBSDPlugin:
        return NetBSDPlugin()

    def test_bios_kernel_path(self, plugin: NetBSDPlugin) -> None:
        profile = _nbsd(firmware=BootFirmware.BIOS)
        assets = plugin.boot_assets(profile)
        assert "pxeboot_ia32.bin" in assets.kernel
        assert "10.0" in assets.kernel
        assert "amd64" in assets.kernel

    def test_uefi_kernel_path(self, plugin: NetBSDPlugin) -> None:
        profile = _nbsd(firmware=BootFirmware.UEFI)
        assets = plugin.boot_assets(profile)
        assert "XEN3_DOMU" in assets.kernel or "netboot" in assets.kernel

    def test_initrd_present(self, plugin: NetBSDPlugin) -> None:
        """NetBSD uses a separate installer ramdisk unlike FreeBSD/OpenBSD."""
        profile = _nbsd()
        assets = plugin.boot_assets(profile)
        assert assets.initrd is not None
        assert "netbsd-INSTALL.gz" in assets.initrd

    def test_boot_args_contain_root(self, plugin: NetBSDPlugin) -> None:
        profile = _nbsd()
        assets = plugin.boot_assets(profile)
        assert any("root=" in a for a in assets.boot_args)

    def test_boot_args_contain_console(self, plugin: NetBSDPlugin) -> None:
        profile = _nbsd()
        assets = plugin.boot_assets(profile)
        assert any("console=com0" in a for a in assets.boot_args)

    def test_initrd_includes_version(self, plugin: NetBSDPlugin) -> None:
        profile = _nbsd(os_version="9.4")
        assets = plugin.boot_assets(profile)
        assert "9.4" in assets.initrd

    def test_bootloader_config_mentions_version(self, plugin: NetBSDPlugin) -> None:
        profile = _nbsd(os_version="10.1")
        assets = plugin.boot_assets(profile)
        assert "10.1" in assets.bootloader_config


class TestNetBSDValidation:
    """Verify NetBSD profile validation."""

    @pytest.fixture
    def plugin(self) -> NetBSDPlugin:
        return NetBSDPlugin()

    def test_valid_profile(self, plugin: NetBSDPlugin) -> None:
        assert plugin.validate_profile(_nbsd()) == []

    def test_missing_install_url(self, plugin: NetBSDPlugin) -> None:
        profile = _nbsd(install_url="")
        errors = plugin.validate_profile(profile)
        assert any("install_url" in e for e in errors)

    def test_arch_amd64_valid(self, plugin: NetBSDPlugin) -> None:
        assert not any("arch" in e for e in plugin.validate_profile(_nbsd(arch="amd64")))

    def test_arch_i386_valid(self, plugin: NetBSDPlugin) -> None:
        assert not any("arch" in e for e in plugin.validate_profile(_nbsd(arch="i386")))

    def test_arch_evbarm_valid(self, plugin: NetBSDPlugin) -> None:
        assert not any("arch" in e for e in plugin.validate_profile(_nbsd(arch="evbarm")))

    def test_arch_powerpc_invalid(self, plugin: NetBSDPlugin) -> None:
        errors = plugin.validate_profile(_nbsd(arch="powerpc"))
        assert any("unsupported architecture" in e for e in errors)

    def test_filesystem_ffs_valid(self, plugin: NetBSDPlugin) -> None:
        p = _nbsd(disk={"filesystem": "ffs"})
        assert not any("filesystem" in e for e in plugin.validate_profile(p))

    def test_filesystem_lfs_valid(self, plugin: NetBSDPlugin) -> None:
        p = _nbsd(disk={"filesystem": "lfs"})
        assert not any("filesystem" in e for e in plugin.validate_profile(p))

    def test_all_versions_valid(self, plugin: NetBSDPlugin) -> None:
        for v in plugin.supported_versions:
            assert plugin.validate_profile(_nbsd(os_version=v)) == []


class TestNetBSDExtractFromIso:
    """Verify NetBSD ISO extraction."""

    @pytest.fixture
    def plugin(self) -> NetBSDPlugin:
        return NetBSDPlugin()

    def test_copies_pxeboot(self, plugin: NetBSDPlugin, tmp_path: Path) -> None:
        mount = tmp_path / "mount"
        dest = tmp_path / "dest"
        nb_dir = mount / "installation" / "netboot"
        nb_dir.mkdir(parents=True)
        (nb_dir / "pxeboot_ia32.bin").write_bytes(b"PXEBOOT")

        assets = plugin.extract_from_iso(mount, dest)
        assert assets.kernel_path == dest / "boot" / "pxeboot_ia32.bin"
        assert assets.kernel_path.exists()

    def test_copies_initrd(self, plugin: NetBSDPlugin, tmp_path: Path) -> None:
        mount = tmp_path / "mount"
        dest = tmp_path / "dest"
        nb_dir = mount / "installation" / "netboot"
        nb_dir.mkdir(parents=True)
        (nb_dir / "netbsd-INSTALL.gz").write_bytes(b"INITRD")

        assets = plugin.extract_from_iso(mount, dest)
        assert assets.initrd_path is not None
        assert assets.initrd_path.exists()

    def test_copies_binary_sets(self, plugin: NetBSDPlugin, tmp_path: Path) -> None:
        mount = tmp_path / "mount"
        dest = tmp_path / "dest"
        sets_dir = mount / "binary" / "sets"
        sets_dir.mkdir(parents=True)
        (sets_dir / "base.tgz").write_bytes(b"BASE")
        (sets_dir / "comp.tgz").write_bytes(b"COMP")

        assets = plugin.extract_from_iso(mount, dest)
        assert (dest / "repo" / "base.tgz").exists()
        assert (dest / "repo" / "comp.tgz").exists()

    def test_fallback_rglob_for_sets(self, plugin: NetBSDPlugin, tmp_path: Path) -> None:
        """When binary/sets doesn't exist, falls back to rglob."""
        mount = tmp_path / "mount"
        dest = tmp_path / "dest"
        mount.mkdir(parents=True)
        (mount / "base.tgz").write_bytes(b"BASE")

        assets = plugin.extract_from_iso(mount, dest)
        assert (dest / "repo" / "base.tgz").exists()

    def test_missing_netboot_dir(self, plugin: NetBSDPlugin, tmp_path: Path) -> None:
        mount = tmp_path / "mount"
        dest = tmp_path / "dest"
        mount.mkdir(parents=True)

        assets = plugin.extract_from_iso(mount, dest)
        assert not assets.kernel_path.exists()
        assert assets.initrd_path is None

    def test_no_boot_loader(self, plugin: NetBSDPlugin, tmp_path: Path) -> None:
        mount = tmp_path / "mount"
        dest = tmp_path / "dest"
        mount.mkdir(parents=True)

        assets = plugin.extract_from_iso(mount, dest)
        assert assets.boot_loader_path is None


class TestNetBSDTimezone:
    """Verify NetBSD timezone configuration."""

    @pytest.fixture
    def plugin(self) -> NetBSDPlugin:
        return NetBSDPlugin()

    def test_default_timezone(self, plugin: NetBSDPlugin) -> None:
        profile = _nbsd()
        output = plugin.generate_autoinstall(profile)
        assert "timezone=UTC" in output

    def test_custom_timezone(self, plugin: NetBSDPlugin) -> None:
        profile = _nbsd(extra={"timezone": "US/Eastern"})
        output = plugin.generate_autoinstall(profile)
        assert "timezone=US/Eastern" in output


class TestNetBSDX11:
    """Verify NetBSD X11 configuration."""

    @pytest.fixture
    def plugin(self) -> NetBSDPlugin:
        return NetBSDPlugin()

    def test_x11_no_by_default(self, plugin: NetBSDPlugin) -> None:
        profile = _nbsd()
        output = plugin.generate_autoinstall(profile)
        assert "x11=no" in output

    def test_x11_enabled(self, plugin: NetBSDPlugin) -> None:
        profile = _nbsd(extra={"x11": True})
        output = plugin.generate_autoinstall(profile)
        assert "x11=yes" in output


# ═══════════════════════════════════════════════════════════════════
#  DRAGONFLYBSD
# ═══════════════════════════════════════════════════════════════════


class TestDragonFlyBSDFilesystem:
    """Verify DragonFlyBSD HAMMER2 and UFS configuration."""

    @pytest.fixture
    def plugin(self) -> DragonFlyBSDPlugin:
        return DragonFlyBSDPlugin()

    def test_hammer2_default(self, plugin: DragonFlyBSDPlugin) -> None:
        profile = _dbsd()
        output = plugin.generate_autoinstall(profile)
        assert "hammer2" in output

    def test_ufs_when_specified(self, plugin: DragonFlyBSDPlugin) -> None:
        profile = _dbsd(disk={"filesystem": "ufs"})
        output = plugin.generate_autoinstall(profile)
        assert "ufs" in output

    def test_invalid_filesystem(self, plugin: DragonFlyBSDPlugin) -> None:
        profile = _dbsd(disk={"filesystem": "ext4"})
        errors = plugin.validate_profile(profile)
        assert any("unsupported filesystem" in e for e in errors)

    def test_custom_device(self, plugin: DragonFlyBSDPlugin) -> None:
        profile = _dbsd(disk={"device": "nvd0"})
        output = plugin.generate_autoinstall(profile)
        assert "nvd0" in output


class TestDragonFlyBSDNetwork:
    """Verify DragonFlyBSD network configuration."""

    @pytest.fixture
    def plugin(self) -> DragonFlyBSDPlugin:
        return DragonFlyBSDPlugin()

    def test_dhcp_default(self, plugin: DragonFlyBSDPlugin) -> None:
        profile = _dbsd()
        output = plugin.generate_autoinstall(profile)
        assert 'ifconfig_em0="DHCP"' in output

    def test_static_ip(self, plugin: DragonFlyBSDPlugin) -> None:
        profile = _dbsd(
            network={
                "dhcp": False,
                "interface": "em0",
                "address": "10.0.0.20",
                "netmask": "255.255.255.0",
                "gateway": "10.0.0.1",
            },
        )
        output = plugin.generate_autoinstall(profile)
        assert "10.0.0.20" in output
        assert "10.0.0.1" in output

    def test_hostname_in_rcconf(self, plugin: DragonFlyBSDPlugin) -> None:
        profile = _dbsd(network={"hostname": "dfly-web"})
        output = plugin.generate_autoinstall(profile)
        assert 'hostname="dfly-web' in output

    def test_resolv_conf_nameservers(self, plugin: DragonFlyBSDPlugin) -> None:
        profile = _dbsd(network={"nameservers": ["1.1.1.1", "8.8.8.8"]})
        output = plugin.generate_autoinstall(profile)
        assert "nameserver 1.1.1.1" in output
        assert "nameserver 8.8.8.8" in output


class TestDragonFlyBSDBootArgs:
    """Verify DragonFlyBSD boot args include vfs.root.mountfrom."""

    @pytest.fixture
    def plugin(self) -> DragonFlyBSDPlugin:
        return DragonFlyBSDPlugin()

    def test_vfs_root_mountfrom(self, plugin: DragonFlyBSDPlugin) -> None:
        profile = _dbsd()
        assets = plugin.boot_assets(profile)
        assert any("vfs.root.mountfrom=ufs:/dev/md0" in a for a in assets.boot_args)

    def test_nfsroot_args(self, plugin: DragonFlyBSDPlugin) -> None:
        profile = _dbsd()
        assets = plugin.boot_assets(profile)
        assert any("boot.nfsroot.server=" in a for a in assets.boot_args)
        assert any("boot.nfsroot.path=" in a for a in assets.boot_args)

    def test_has_initrd(self, plugin: DragonFlyBSDPlugin) -> None:
        profile = _dbsd()
        assets = plugin.boot_assets(profile)
        assert assets.initrd is not None
        assert "initrd" in assets.initrd

    def test_bios_kernel_pxeboot(self, plugin: DragonFlyBSDPlugin) -> None:
        profile = _dbsd(firmware=BootFirmware.BIOS)
        assets = plugin.boot_assets(profile)
        assert assets.kernel.endswith("/boot/pxeboot")

    def test_uefi_kernel_loader(self, plugin: DragonFlyBSDPlugin) -> None:
        profile = _dbsd(firmware=BootFirmware.UEFI)
        assets = plugin.boot_assets(profile)
        assert assets.kernel.endswith("/boot/loader.efi")

    def test_nfsroot_path_dragonflybsd(self, plugin: DragonFlyBSDPlugin) -> None:
        profile = _dbsd(os_version="6.4", arch="x86_64")
        assets = plugin.boot_assets(profile)
        assert any("dragonflybsd/6.4/x86_64" in a for a in assets.boot_args)


class TestDragonFlyBSDURLValidation:
    """Verify DragonFlyBSD URL scheme validation."""

    @pytest.fixture
    def plugin(self) -> DragonFlyBSDPlugin:
        return DragonFlyBSDPlugin()

    def test_http_valid(self, plugin: DragonFlyBSDPlugin) -> None:
        profile = _dbsd(install_url="http://mirror.example.com/dragonfly")
        errors = plugin.validate_profile(profile)
        assert not any("install_url must be" in e for e in errors)

    def test_https_valid(self, plugin: DragonFlyBSDPlugin) -> None:
        profile = _dbsd(install_url="https://mirror.example.com/dragonfly")
        errors = plugin.validate_profile(profile)
        assert not any("install_url must be" in e for e in errors)

    def test_ftp_valid(self, plugin: DragonFlyBSDPlugin) -> None:
        profile = _dbsd(install_url="ftp://ftp.dragonflybsd.org/pub")
        errors = plugin.validate_profile(profile)
        assert not any("install_url must be" in e for e in errors)

    def test_nfs_valid(self, plugin: DragonFlyBSDPlugin) -> None:
        profile = _dbsd(install_url="nfs://nas.local/exports/dragonfly")
        errors = plugin.validate_profile(profile)
        assert not any("install_url must be" in e for e in errors)

    def test_invalid_scheme(self, plugin: DragonFlyBSDPlugin) -> None:
        profile = _dbsd(install_url="smb://share.local/dragonfly")
        errors = plugin.validate_profile(profile)
        assert any("install_url must be" in e for e in errors)


class TestDragonFlyBSDServices:
    """Verify DragonFlyBSD service configuration."""

    @pytest.fixture
    def plugin(self) -> DragonFlyBSDPlugin:
        return DragonFlyBSDPlugin()

    def test_default_sshd(self, plugin: DragonFlyBSDPlugin) -> None:
        profile = _dbsd()
        output = plugin.generate_autoinstall(profile)
        assert 'sshd_enable="YES"' in output

    def test_custom_services(self, plugin: DragonFlyBSDPlugin) -> None:
        profile = _dbsd(extra={"services": ["sshd", "ntpd", "nginx"]})
        output = plugin.generate_autoinstall(profile)
        assert 'nginx_enable="YES"' in output

    def test_sendmail_disabled(self, plugin: DragonFlyBSDPlugin) -> None:
        profile = _dbsd()
        output = plugin.generate_autoinstall(profile)
        assert 'sendmail_enable="NONE"' in output


class TestDragonFlyBSDPackages:
    """Verify DragonFlyBSD package installation."""

    @pytest.fixture
    def plugin(self) -> DragonFlyBSDPlugin:
        return DragonFlyBSDPlugin()

    def test_packages_installed(self, plugin: DragonFlyBSDPlugin) -> None:
        profile = _dbsd(packages=["git", "tmux", "python3"])
        output = plugin.generate_autoinstall(profile)
        assert "pkg install -y git tmux python3" in output

    def test_no_packages(self, plugin: DragonFlyBSDPlugin) -> None:
        profile = _dbsd(packages=[])
        output = plugin.generate_autoinstall(profile)
        assert "pkg install" not in output


class TestDragonFlyBSDValidation:
    """Verify DragonFlyBSD profile validation edge cases."""

    @pytest.fixture
    def plugin(self) -> DragonFlyBSDPlugin:
        return DragonFlyBSDPlugin()

    def test_valid_profile(self, plugin: DragonFlyBSDPlugin) -> None:
        assert plugin.validate_profile(_dbsd()) == []

    def test_arch_x86_64_valid(self, plugin: DragonFlyBSDPlugin) -> None:
        p = _dbsd(arch="x86_64")
        assert not any("architecture" in e for e in plugin.validate_profile(p))

    def test_arch_amd64_valid(self, plugin: DragonFlyBSDPlugin) -> None:
        p = _dbsd(arch="amd64")
        assert not any("architecture" in e for e in plugin.validate_profile(p))

    def test_arch_arm64_invalid(self, plugin: DragonFlyBSDPlugin) -> None:
        p = _dbsd(arch="arm64")
        errors = plugin.validate_profile(p)
        assert any("unsupported architecture" in e for e in errors)

    def test_all_versions_valid(self, plugin: DragonFlyBSDPlugin) -> None:
        for v in plugin.supported_versions:
            assert plugin.validate_profile(_dbsd(os_version=v)) == []

    def test_os_family_mismatch(self, plugin: DragonFlyBSDPlugin) -> None:
        p = _dbsd(os_family="freebsd")
        errors = plugin.validate_profile(p)
        assert any("os_family mismatch" in e for e in errors)

    def test_missing_name(self, plugin: DragonFlyBSDPlugin) -> None:
        p = _dbsd(name="")
        errors = plugin.validate_profile(p)
        assert any("profile name" in e for e in errors)


# ═══════════════════════════════════════════════════════════════════
#  CROSS-BSD COMPARISONS
# ═══════════════════════════════════════════════════════════════════

class TestCrossBSDComparisons:
    """Compare behaviours across BSD variants to catch inconsistencies."""

    def test_all_bsd_autoinstall_filenames(self) -> None:
        """FreeBSD and DragonFlyBSD share 'installerconfig'; others are unique."""
        assert FreeBSDPlugin().autoinstall_filename() == "installerconfig"
        assert DragonFlyBSDPlugin().autoinstall_filename() == "installerconfig"
        assert OpenBSDPlugin().autoinstall_filename() == "install.conf"
        assert NetBSDPlugin().autoinstall_filename() == "auto_install.cfg"
        # Three unique filenames total (FreeBSD and DragonFlyBSD share one)
        filenames = {
            FreeBSDPlugin().autoinstall_filename(),
            OpenBSDPlugin().autoinstall_filename(),
            NetBSDPlugin().autoinstall_filename(),
            DragonFlyBSDPlugin().autoinstall_filename(),
        }
        assert len(filenames) == 3

    def test_all_bsd_os_families_unique(self) -> None:
        families = {
            FreeBSDPlugin().os_family,
            OpenBSDPlugin().os_family,
            NetBSDPlugin().os_family,
            DragonFlyBSDPlugin().os_family,
        }
        assert len(families) == 4

    def test_freebsd_and_openbsd_no_initrd(self) -> None:
        """FreeBSD and OpenBSD boot without a separate initrd."""
        fb = FreeBSDPlugin().boot_assets(_fbsd())
        ob = OpenBSDPlugin().boot_assets(_obsd())
        assert fb.initrd is None
        assert ob.initrd is None

    def test_netbsd_and_dragonfly_have_initrd(self) -> None:
        """NetBSD and DragonFlyBSD do use an initrd."""
        nb = NetBSDPlugin().boot_assets(_nbsd())
        db = DragonFlyBSDPlugin().boot_assets(_dbsd())
        assert nb.initrd is not None
        assert db.initrd is not None

    def test_all_bsd_installers_shell_or_conf(self) -> None:
        """FreeBSD and DragonFlyBSD use shell scripts; OpenBSD/NetBSD use config files."""
        fb = FreeBSDPlugin().generate_autoinstall(_fbsd())
        db = DragonFlyBSDPlugin().generate_autoinstall(_dbsd())
        assert fb.startswith("#!/bin/sh")
        assert db.startswith("#!/bin/sh")

        ob = OpenBSDPlugin().generate_autoinstall(_obsd())
        nb = NetBSDPlugin().generate_autoinstall(_nbsd())
        assert not ob.startswith("#!/bin/sh")
        assert not nb.startswith("#!/bin/sh")

    def test_supports_live_false_for_all_bsd(self) -> None:
        """No BSD plugin supports live ISO mode."""
        for cls in (FreeBSDPlugin, OpenBSDPlugin, NetBSDPlugin, DragonFlyBSDPlugin):
            assert cls().supports_live is False
