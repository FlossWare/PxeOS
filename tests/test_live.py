"""Tests for live ISO PXE boot support (issue #6)."""

from __future__ import annotations

import shutil
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from pxeos.models import (
    BootAssets,
    BootFirmware,
    DistroAssets,
    ProvisionProfile,
)


# ---------------------------------------------------------------------------
# DistroAssets.squashfs_path
# ---------------------------------------------------------------------------


class TestDistroAssetsSquashfs:
    """Verify the squashfs_path field on DistroAssets."""

    def test_defaults_to_none(self, tmp_path):
        assets = DistroAssets(kernel_path=tmp_path / "vmlinuz")
        assert assets.squashfs_path is None

    def test_accepts_squashfs_path(self, tmp_path):
        sf = tmp_path / "squashfs.img"
        assets = DistroAssets(
            kernel_path=tmp_path / "vmlinuz",
            squashfs_path=sf,
        )
        assert assets.squashfs_path == sf


# ---------------------------------------------------------------------------
# Base plugin -- supports_live defaults
# ---------------------------------------------------------------------------


class TestBasePluginLiveDefaults:
    """Base OSPlugin defaults: supports_live=False, methods raise."""

    def test_supports_live_false_by_default(self):
        from pxeos.plugins.base import OSPlugin

        class MinimalPlugin(OSPlugin):
            @property
            def os_family(self):
                return "test"

            @property
            def supported_versions(self):
                return ["1"]

            def generate_autoinstall(self, profile):
                return ""

            def boot_assets(self, profile):
                return BootAssets(kernel="k")

            def autoinstall_filename(self):
                return "auto.cfg"

            def extract_from_iso(self, mount_path, dest):
                return DistroAssets(kernel_path=mount_path / "k")

        p = MinimalPlugin()
        assert p.supports_live is False

    def test_extract_live_assets_raises(self):
        from pxeos.plugins.base import OSPlugin

        class MinimalPlugin(OSPlugin):
            @property
            def os_family(self):
                return "test"

            @property
            def supported_versions(self):
                return ["1"]

            def generate_autoinstall(self, profile):
                return ""

            def boot_assets(self, profile):
                return BootAssets(kernel="k")

            def autoinstall_filename(self):
                return "auto.cfg"

            def extract_from_iso(self, mount_path, dest):
                return DistroAssets(kernel_path=mount_path / "k")

        p = MinimalPlugin()
        with pytest.raises(NotImplementedError, match="test"):
            p.extract_live_assets(Path("/m"), Path("/d"))

    def test_live_boot_assets_raises(self):
        from pxeos.plugins.base import OSPlugin

        class MinimalPlugin(OSPlugin):
            @property
            def os_family(self):
                return "test"

            @property
            def supported_versions(self):
                return ["1"]

            def generate_autoinstall(self, profile):
                return ""

            def boot_assets(self, profile):
                return BootAssets(kernel="k")

            def autoinstall_filename(self):
                return "auto.cfg"

            def extract_from_iso(self, mount_path, dest):
                return DistroAssets(kernel_path=mount_path / "k")

        p = MinimalPlugin()
        profile = ProvisionProfile(
            name="t", os_family="test", os_version="1"
        )
        with pytest.raises(NotImplementedError, match="test"):
            p.live_boot_assets(profile)


# ---------------------------------------------------------------------------
# is_live_iso detection
# ---------------------------------------------------------------------------


class TestIsLiveIso:
    """Tests for is_live_iso() detection."""

    def test_fedora_live_detected(self, tmp_path):
        from pxeos.iso_detect import is_live_iso

        live_dir = tmp_path / "LiveOS"
        live_dir.mkdir()
        (live_dir / "squashfs.img").write_bytes(b"fake")
        assert is_live_iso(tmp_path) is True

    def test_ubuntu_live_detected(self, tmp_path):
        from pxeos.iso_detect import is_live_iso

        casper = tmp_path / "casper"
        casper.mkdir()
        (casper / "filesystem.squashfs").write_bytes(b"fake")
        assert is_live_iso(tmp_path) is True

    def test_debian_live_detected(self, tmp_path):
        from pxeos.iso_detect import is_live_iso

        live = tmp_path / "live"
        live.mkdir()
        (live / "filesystem.squashfs").write_bytes(b"fake")
        assert is_live_iso(tmp_path) is True

    def test_arch_live_detected(self, tmp_path):
        from pxeos.iso_detect import is_live_iso

        arch = tmp_path / "arch" / "x86_64"
        arch.mkdir(parents=True)
        (arch / "airootfs.sfs").write_bytes(b"fake")
        assert is_live_iso(tmp_path) is True

    def test_installer_iso_not_live(self, tmp_path):
        from pxeos.iso_detect import is_live_iso

        (tmp_path / "images").mkdir()
        assert is_live_iso(tmp_path) is False

    def test_empty_dir_not_live(self, tmp_path):
        from pxeos.iso_detect import is_live_iso

        assert is_live_iso(tmp_path) is False


# ---------------------------------------------------------------------------
# Fedora live plugin
# ---------------------------------------------------------------------------


class TestFedoraLive:
    """Tests for FedoraPlugin live ISO support."""

    def _make_live_iso(self, mount: Path):
        (mount / "images" / "pxeboot").mkdir(parents=True)
        (mount / "images" / "pxeboot" / "vmlinuz").write_bytes(
            b"fedora-kernel"
        )
        (mount / "images" / "pxeboot" / "initrd.img").write_bytes(
            b"fedora-initrd"
        )
        (mount / "LiveOS").mkdir()
        (mount / "LiveOS" / "squashfs.img").write_bytes(
            b"fedora-squashfs"
        )

    def test_supports_live(self):
        from pxeos.plugins.fedora import FedoraPlugin

        assert FedoraPlugin().supports_live is True

    def test_extract_live_assets(self, tmp_path):
        from pxeos.plugins.fedora import FedoraPlugin

        mount = tmp_path / "mount"
        mount.mkdir()
        self._make_live_iso(mount)
        dest = tmp_path / "dest"

        plugin = FedoraPlugin()
        assets = plugin.extract_live_assets(mount, dest)

        assert assets.kernel_path == dest / "vmlinuz"
        assert assets.initrd_path == dest / "initrd.img"
        assert assets.squashfs_path == dest / "LiveOS" / "squashfs.img"
        assert assets.kernel_path.read_bytes() == b"fedora-kernel"
        assert assets.squashfs_path.read_bytes() == b"fedora-squashfs"

    def test_extract_live_assets_with_efi(self, tmp_path):
        from pxeos.plugins.fedora import FedoraPlugin

        mount = tmp_path / "mount"
        mount.mkdir()
        self._make_live_iso(mount)
        efi = mount / "EFI" / "BOOT"
        efi.mkdir(parents=True)
        (efi / "BOOTX64.EFI").write_bytes(b"efi")
        dest = tmp_path / "dest"

        plugin = FedoraPlugin()
        assets = plugin.extract_live_assets(mount, dest)

        assert assets.boot_loader_path == dest / "EFI" / "BOOT"
        assert (dest / "EFI" / "BOOT" / "BOOTX64.EFI").exists()

    def test_live_boot_assets_bios(self):
        from pxeos.plugins.fedora import FedoraPlugin

        profile = ProvisionProfile(
            name="test-live",
            os_family="fedora",
            os_version="42",
            install_url="http://server/fedora-live",
        )
        plugin = FedoraPlugin()
        assets = plugin.live_boot_assets(profile)

        assert "root=live:http://server/fedora-live/LiveOS/squashfs.img" in assets.boot_args
        assert "rd.live.image" in assets.boot_args
        assert "ip=dhcp" in assets.boot_args
        assert assets.kernel == "images/pxeboot/vmlinuz"
        assert assets.initrd == "images/pxeboot/initrd.img"
        assert "pxelinux" in assets.bootloader_config.lower() or "DEFAULT" in assets.bootloader_config

    def test_live_boot_assets_uefi(self):
        from pxeos.plugins.fedora import FedoraPlugin

        profile = ProvisionProfile(
            name="test-live",
            os_family="fedora",
            os_version="42",
            install_url="http://server/fedora-live",
            firmware=BootFirmware.UEFI,
        )
        plugin = FedoraPlugin()
        assets = plugin.live_boot_assets(profile)

        assert "linuxefi" in assets.bootloader_config or "menuentry" in assets.bootloader_config


# ---------------------------------------------------------------------------
# Ubuntu live plugin
# ---------------------------------------------------------------------------


class TestUbuntuLive:
    """Tests for UbuntuPlugin live ISO support."""

    def _make_live_iso(self, mount: Path):
        (mount / "casper").mkdir()
        (mount / "casper" / "vmlinuz").write_bytes(
            b"ubuntu-kernel"
        )
        (mount / "casper" / "initrd").write_bytes(
            b"ubuntu-initrd"
        )
        (mount / "casper" / "filesystem.squashfs").write_bytes(
            b"ubuntu-squashfs"
        )

    def test_supports_live(self):
        from pxeos.plugins.ubuntu import UbuntuPlugin

        assert UbuntuPlugin().supports_live is True

    def test_extract_live_assets(self, tmp_path):
        from pxeos.plugins.ubuntu import UbuntuPlugin

        mount = tmp_path / "mount"
        mount.mkdir()
        self._make_live_iso(mount)
        dest = tmp_path / "dest"

        plugin = UbuntuPlugin()
        assets = plugin.extract_live_assets(mount, dest)

        assert assets.kernel_path == dest / "vmlinuz"
        assert assets.initrd_path == dest / "initrd"
        assert assets.squashfs_path == dest / "casper" / "filesystem.squashfs"
        assert assets.squashfs_path.read_bytes() == b"ubuntu-squashfs"

    def test_live_boot_assets(self):
        from pxeos.plugins.ubuntu import UbuntuPlugin

        profile = ProvisionProfile(
            name="test-live",
            os_family="ubuntu",
            os_version="24.04",
            install_url="http://server/ubuntu-live",
        )
        plugin = UbuntuPlugin()
        assets = plugin.live_boot_assets(profile)

        assert "boot=casper" in assets.boot_args
        assert "fetch=http://server/ubuntu-live/casper/filesystem.squashfs" in assets.boot_args
        assert "ip=dhcp" in assets.boot_args
        assert assets.kernel == "casper/vmlinuz"
        assert assets.initrd == "casper/initrd"


# ---------------------------------------------------------------------------
# Debian live plugin
# ---------------------------------------------------------------------------


class TestDebianLive:
    """Tests for DebianPlugin live ISO support."""

    def _make_live_iso(self, mount: Path):
        (mount / "live").mkdir()
        (mount / "live" / "vmlinuz").write_bytes(
            b"debian-kernel"
        )
        (mount / "live" / "initrd.img").write_bytes(
            b"debian-initrd"
        )
        (mount / "live" / "filesystem.squashfs").write_bytes(
            b"debian-squashfs"
        )

    def test_supports_live(self):
        from pxeos.plugins.debian import DebianPlugin

        assert DebianPlugin().supports_live is True

    def test_extract_live_assets(self, tmp_path):
        from pxeos.plugins.debian import DebianPlugin

        mount = tmp_path / "mount"
        mount.mkdir()
        self._make_live_iso(mount)
        dest = tmp_path / "dest"

        plugin = DebianPlugin()
        assets = plugin.extract_live_assets(mount, dest)

        assert assets.kernel_path == dest / "vmlinuz"
        assert assets.initrd_path == dest / "initrd.img"
        assert assets.squashfs_path == dest / "live" / "filesystem.squashfs"
        assert assets.squashfs_path.read_bytes() == b"debian-squashfs"

    def test_live_boot_assets(self):
        from pxeos.plugins.debian import DebianPlugin

        profile = ProvisionProfile(
            name="test-live",
            os_family="debian",
            os_version="12",
            install_url="http://server/debian-live",
        )
        plugin = DebianPlugin()
        assets = plugin.live_boot_assets(profile)

        assert "boot=live" in assets.boot_args
        assert "fetch=http://server/debian-live/live/filesystem.squashfs" in assets.boot_args
        assert "ip=dhcp" in assets.boot_args
        assert assets.kernel == "live/vmlinuz"
        assert assets.initrd == "live/initrd.img"


# ---------------------------------------------------------------------------
# Arch live plugin
# ---------------------------------------------------------------------------


class TestArchLive:
    """Tests for ArchPlugin live ISO support."""

    def _make_live_iso(self, mount: Path):
        (mount / "arch" / "boot" / "x86_64").mkdir(parents=True)
        (mount / "arch" / "boot" / "x86_64" / "vmlinuz-linux").write_bytes(
            b"arch-kernel"
        )
        (mount / "arch" / "boot" / "x86_64" / "initramfs-linux.img").write_bytes(
            b"arch-initrd"
        )
        (mount / "arch" / "x86_64").mkdir(parents=True, exist_ok=True)
        (mount / "arch" / "x86_64" / "airootfs.sfs").write_bytes(
            b"arch-squashfs"
        )

    def test_supports_live(self):
        from pxeos.plugins.arch import ArchPlugin

        assert ArchPlugin().supports_live is True

    def test_extract_live_assets(self, tmp_path):
        from pxeos.plugins.arch import ArchPlugin

        mount = tmp_path / "mount"
        mount.mkdir()
        self._make_live_iso(mount)
        dest = tmp_path / "dest"

        plugin = ArchPlugin()
        assets = plugin.extract_live_assets(mount, dest)

        assert assets.kernel_path == dest / "vmlinuz-linux"
        assert assets.initrd_path == dest / "initramfs-linux.img"
        assert assets.squashfs_path == dest / "arch" / "x86_64" / "airootfs.sfs"
        assert assets.squashfs_path.read_bytes() == b"arch-squashfs"

    def test_live_boot_assets(self):
        from pxeos.plugins.arch import ArchPlugin

        profile = ProvisionProfile(
            name="test-live",
            os_family="arch",
            os_version="latest",
            install_url="http://server/arch-live",
        )
        plugin = ArchPlugin()
        assets = plugin.live_boot_assets(profile)

        assert "archisobasedir=arch" in assets.boot_args
        assert "archiso_http_srv=http://server/arch-live/" in assets.boot_args
        assert "ip=dhcp" in assets.boot_args

    def test_live_boot_assets_cow_spacesize(self):
        from pxeos.plugins.arch import ArchPlugin

        profile = ProvisionProfile(
            name="test-live",
            os_family="arch",
            os_version="latest",
            install_url="http://server/arch",
            extra={"cow_spacesize": "4G"},
        )
        plugin = ArchPlugin()
        assets = plugin.live_boot_assets(profile)

        assert "cow_spacesize=4G" in assets.boot_args


# ---------------------------------------------------------------------------
# Importer -- live=True
# ---------------------------------------------------------------------------


class TestImporterLive:
    """Tests for import_iso with live=True."""

    @patch("pxeos.importer.subprocess.run")
    @patch("pxeos.importer.tempfile.mkdtemp")
    def test_import_iso_live_calls_extract_live_assets(
        self, mock_mkdtemp, mock_run, tmp_path
    ):
        from pxeos.importer import import_iso

        mount = tmp_path / "mount"
        mount.mkdir()
        mock_mkdtemp.return_value = str(mount)

        mock_plugin = MagicMock()
        mock_plugin.supports_live = True
        mock_plugin.extract_live_assets.return_value = DistroAssets(
            kernel_path=tmp_path / "vmlinuz",
            squashfs_path=tmp_path / "squashfs.img",
        )

        mock_registry = MagicMock()
        mock_registry.get.return_value = mock_plugin

        distro_root = tmp_path / "distros"
        distro_root.mkdir()

        assets = import_iso(
            tmp_path / "test.iso",
            "fedora", "fedora", "42", "x86_64",
            mock_registry, distro_root,
            live=True,
        )

        mock_plugin.extract_live_assets.assert_called_once()
        mock_plugin.extract_from_iso.assert_not_called()
        assert assets.squashfs_path == tmp_path / "squashfs.img"

    @patch("pxeos.importer.subprocess.run")
    @patch("pxeos.importer.tempfile.mkdtemp")
    def test_import_iso_live_unsupported_raises(
        self, mock_mkdtemp, mock_run, tmp_path
    ):
        from pxeos.importer import import_iso

        mount = tmp_path / "mount"
        mount.mkdir()
        mock_mkdtemp.return_value = str(mount)

        mock_plugin = MagicMock()
        mock_plugin.supports_live = False

        mock_registry = MagicMock()
        mock_registry.get.return_value = mock_plugin

        distro_root = tmp_path / "distros"
        distro_root.mkdir()

        with pytest.raises(ValueError, match="does not support live"):
            import_iso(
                tmp_path / "test.iso",
                "windows", "windows", "11", "x86_64",
                mock_registry, distro_root,
                live=True,
            )

    @patch("pxeos.importer.subprocess.run")
    @patch("pxeos.importer.tempfile.mkdtemp")
    def test_import_iso_live_dir_suffix(
        self, mock_mkdtemp, mock_run, tmp_path
    ):
        from pxeos.importer import import_iso

        mount = tmp_path / "mount"
        mount.mkdir()
        mock_mkdtemp.return_value = str(mount)

        mock_plugin = MagicMock()
        mock_plugin.supports_live = True
        mock_plugin.extract_live_assets.return_value = DistroAssets(
            kernel_path=tmp_path / "vmlinuz",
        )

        mock_registry = MagicMock()
        mock_registry.get.return_value = mock_plugin

        distro_root = tmp_path / "distros"
        distro_root.mkdir()

        import_iso(
            tmp_path / "test.iso",
            "fedora", "fedora", "42", "x86_64",
            mock_registry, distro_root,
            live=True,
        )

        call_args = mock_plugin.extract_live_assets.call_args
        dest = call_args[0][1]
        assert "fedora-live" in str(dest)

    @patch("pxeos.importer.is_live_iso")
    @patch("pxeos.importer.subprocess.run")
    @patch("pxeos.importer.tempfile.mkdtemp")
    def test_import_iso_auto_detects_live(
        self, mock_mkdtemp, mock_run, mock_is_live, tmp_path
    ):
        from pxeos.importer import import_iso

        mount = tmp_path / "mount"
        mount.mkdir()
        mock_mkdtemp.return_value = str(mount)
        mock_is_live.return_value = True

        mock_plugin = MagicMock()
        mock_plugin.supports_live = True
        mock_plugin.extract_live_assets.return_value = DistroAssets(
            kernel_path=tmp_path / "vmlinuz",
        )

        mock_registry = MagicMock()
        mock_registry.get.return_value = mock_plugin

        distro_root = tmp_path / "distros"
        distro_root.mkdir()

        import_iso(
            tmp_path / "test.iso",
            "fedora", "fedora", "42", "x86_64",
            mock_registry, distro_root,
        )

        mock_plugin.extract_live_assets.assert_called_once()


# ---------------------------------------------------------------------------
# Engine -- live boot iPXE script
# ---------------------------------------------------------------------------


class TestEngineLiveBoot:
    """Tests for ProvisioningEngine live boot iPXE script generation."""

    def _make_engine(self, tmp_path, plugin, live=False):
        from pxeos.config import PxeOSConfig
        from pxeos.engine import ProvisioningEngine
        from pxeos.matcher import HostMatcher
        from pxeos.models import HostRule
        from pxeos.registry import PluginRegistry

        rule = HostRule(
            profile="live-test",
            os_family=plugin.os_family,
            os_version="42",
            mac="aa:bb:cc:dd:ee:ff",
        )
        matcher = HostMatcher([rule])
        config = PxeOSConfig(data_dir=tmp_path / "data")
        registry = MagicMock(spec=PluginRegistry)
        registry.get.return_value = plugin

        profiles_dir = config.data_dir / "profiles"
        profiles_dir.mkdir(parents=True, exist_ok=True)

        profile_content = f"""[profile]
name = "live-test"
os_family = "{plugin.os_family}"
os_version = "42"
install_url = "http://server/distro"
autoinstall_url = "http://server/autoinstall"
"""
        if live:
            profile_content += '\n[profile.extra]\nlive = true\n'

        (profiles_dir / "live-test.toml").write_text(profile_content)

        return ProvisioningEngine(registry, matcher, config)

    def test_live_boot_skips_autoinstall(self, tmp_path):
        from pxeos.plugins.fedora import FedoraPlugin

        plugin = FedoraPlugin()
        engine = self._make_engine(tmp_path, plugin, live=True)
        script = engine.render_ipxe_script("aa:bb:cc:dd:ee:ff")

        assert "#!ipxe" in script
        assert "kernel" in script
        assert "inst.ks=" not in script
        assert "rd.live.image" in script

    def test_install_boot_includes_autoinstall(self, tmp_path):
        from pxeos.plugins.fedora import FedoraPlugin

        plugin = FedoraPlugin()
        engine = self._make_engine(tmp_path, plugin, live=False)
        script = engine.render_ipxe_script("aa:bb:cc:dd:ee:ff")

        assert "inst.ks=" in script


# ---------------------------------------------------------------------------
# CLI --live flag
# ---------------------------------------------------------------------------


class TestCLILiveFlag:
    """Tests for pxeos import --live CLI flag."""

    def test_parser_accepts_live_flag(self):
        from pxeos.cli import _build_parser

        parser = _build_parser()
        args = parser.parse_args([
            "import", "--iso", "/tmp/live.iso",
            "--os", "fedora", "--version", "42",
            "--live",
        ])
        assert args.live is True

    def test_parser_live_defaults_false(self):
        from pxeos.cli import _build_parser

        parser = _build_parser()
        args = parser.parse_args([
            "import", "--iso", "/tmp/live.iso",
            "--os", "fedora", "--version", "42",
        ])
        assert args.live is False


# ---------------------------------------------------------------------------
# API -- ImportResponse squashfs_path
# ---------------------------------------------------------------------------


class TestAPIImportResponseSquashfs:
    """Tests for ImportResponse model with squashfs_path."""

    def test_import_response_accepts_squashfs(self):
        from pxeos.api import ImportResponse

        resp = ImportResponse(
            kernel_path="/path/vmlinuz",
            repo_path="/path/repo",
            squashfs_path="/path/squashfs.img",
        )
        assert resp.squashfs_path == "/path/squashfs.img"

    def test_import_response_squashfs_defaults_none(self):
        from pxeos.api import ImportResponse

        resp = ImportResponse(
            kernel_path="/path/vmlinuz",
            repo_path="/path/repo",
        )
        assert resp.squashfs_path is None


# ---------------------------------------------------------------------------
# Serial console support in live boot
# ---------------------------------------------------------------------------


class TestLiveBootSerialConsole:
    """Verify serial_console extra propagates to live boot args."""

    def test_fedora_live_serial_console(self):
        from pxeos.plugins.fedora import FedoraPlugin

        profile = ProvisionProfile(
            name="serial-test",
            os_family="fedora",
            os_version="42",
            install_url="http://server/live",
            extra={"serial_console": "ttyS0,115200"},
        )
        assets = FedoraPlugin().live_boot_assets(profile)
        assert "console=ttyS0,115200" in assets.boot_args

    def test_ubuntu_live_serial_console(self):
        from pxeos.plugins.ubuntu import UbuntuPlugin

        profile = ProvisionProfile(
            name="serial-test",
            os_family="ubuntu",
            os_version="24.04",
            install_url="http://server/live",
            extra={"serial_console": "ttyS0,115200"},
        )
        assets = UbuntuPlugin().live_boot_assets(profile)
        assert "console=ttyS0,115200" in assets.boot_args

    def test_debian_live_serial_console(self):
        from pxeos.plugins.debian import DebianPlugin

        profile = ProvisionProfile(
            name="serial-test",
            os_family="debian",
            os_version="12",
            install_url="http://server/live",
            extra={"serial_console": "ttyS0,115200"},
        )
        assets = DebianPlugin().live_boot_assets(profile)
        assert "console=ttyS0,115200" in assets.boot_args

    def test_arch_live_serial_console(self):
        from pxeos.plugins.arch import ArchPlugin

        profile = ProvisionProfile(
            name="serial-test",
            os_family="arch",
            os_version="latest",
            install_url="http://server/live",
            extra={"serial_console": "ttyS0,115200"},
        )
        assets = ArchPlugin().live_boot_assets(profile)
        assert "console=ttyS0,115200" in assets.boot_args


# ---------------------------------------------------------------------------
# UEFI firmware mode for live boot
# ---------------------------------------------------------------------------


class TestLiveBootUEFI:
    """Verify UEFI firmware produces grub config in live boot."""

    def test_ubuntu_live_uefi_grub_config(self):
        from pxeos.plugins.ubuntu import UbuntuPlugin

        profile = ProvisionProfile(
            name="uefi-test",
            os_family="ubuntu",
            os_version="24.04",
            install_url="http://server/live",
            firmware=BootFirmware.UEFI,
        )
        assets = UbuntuPlugin().live_boot_assets(profile)
        assert "linuxefi" in assets.bootloader_config or "menuentry" in assets.bootloader_config

    def test_debian_live_uefi_grub_config(self):
        from pxeos.plugins.debian import DebianPlugin

        profile = ProvisionProfile(
            name="uefi-test",
            os_family="debian",
            os_version="12",
            install_url="http://server/live",
            firmware=BootFirmware.UEFI,
        )
        assets = DebianPlugin().live_boot_assets(profile)
        assert "linuxefi" in assets.bootloader_config or "menuentry" in assets.bootloader_config


# ---------------------------------------------------------------------------
# Extract live assets with no EFI directory
# ---------------------------------------------------------------------------


class TestExtractLiveNoEFI:
    """Verify live extraction works when no EFI directory exists."""

    def test_fedora_no_efi(self, tmp_path):
        from pxeos.plugins.fedora import FedoraPlugin

        mount = tmp_path / "mount"
        mount.mkdir()
        (mount / "images" / "pxeboot").mkdir(parents=True)
        (mount / "images" / "pxeboot" / "vmlinuz").write_bytes(b"k")
        (mount / "images" / "pxeboot" / "initrd.img").write_bytes(b"i")
        (mount / "LiveOS").mkdir()
        (mount / "LiveOS" / "squashfs.img").write_bytes(b"s")
        dest = tmp_path / "dest"

        assets = FedoraPlugin().extract_live_assets(mount, dest)
        assert assets.boot_loader_path is None

    def test_ubuntu_no_efi(self, tmp_path):
        from pxeos.plugins.ubuntu import UbuntuPlugin

        mount = tmp_path / "mount"
        mount.mkdir()
        (mount / "casper").mkdir()
        (mount / "casper" / "vmlinuz").write_bytes(b"k")
        (mount / "casper" / "initrd").write_bytes(b"i")
        (mount / "casper" / "filesystem.squashfs").write_bytes(b"s")
        dest = tmp_path / "dest"

        assets = UbuntuPlugin().extract_live_assets(mount, dest)
        assert assets.boot_loader_path is None

    def test_debian_no_efi(self, tmp_path):
        from pxeos.plugins.debian import DebianPlugin

        mount = tmp_path / "mount"
        mount.mkdir()
        (mount / "live").mkdir()
        (mount / "live" / "vmlinuz").write_bytes(b"k")
        (mount / "live" / "initrd.img").write_bytes(b"i")
        (mount / "live" / "filesystem.squashfs").write_bytes(b"s")
        dest = tmp_path / "dest"

        assets = DebianPlugin().extract_live_assets(mount, dest)
        assert assets.boot_loader_path is None

    def test_arch_no_efi(self, tmp_path):
        from pxeos.plugins.arch import ArchPlugin

        mount = tmp_path / "mount"
        mount.mkdir()
        (mount / "arch" / "boot" / "x86_64").mkdir(parents=True)
        (mount / "arch" / "boot" / "x86_64" / "vmlinuz-linux").write_bytes(b"k")
        (mount / "arch" / "boot" / "x86_64" / "initramfs-linux.img").write_bytes(b"i")
        (mount / "arch" / "x86_64").mkdir(parents=True, exist_ok=True)
        (mount / "arch" / "x86_64" / "airootfs.sfs").write_bytes(b"s")
        dest = tmp_path / "dest"

        assets = ArchPlugin().extract_live_assets(mount, dest)
        assert assets.boot_loader_path is None


# ---------------------------------------------------------------------------
# Trailing-slash handling in rootfs URLs
# ---------------------------------------------------------------------------


class TestRootfsURLSlash:
    """Ensure no double slashes in rootfs URLs."""

    def test_fedora_trailing_slash(self):
        from pxeos.plugins.fedora import FedoraPlugin

        profile = ProvisionProfile(
            name="t", os_family="fedora", os_version="42",
            install_url="http://server/distro/",
        )
        assets = FedoraPlugin().live_boot_assets(profile)
        rootfs_arg = [a for a in assets.boot_args if "root=live:" in a][0]
        assert "//" not in rootfs_arg.split("://", 1)[1]

    def test_ubuntu_trailing_slash(self):
        from pxeos.plugins.ubuntu import UbuntuPlugin

        profile = ProvisionProfile(
            name="t", os_family="ubuntu", os_version="24.04",
            install_url="http://server/distro/",
        )
        assets = UbuntuPlugin().live_boot_assets(profile)
        fetch_arg = [a for a in assets.boot_args if "fetch=" in a][0]
        assert "//" not in fetch_arg.split("://", 1)[1]

    def test_debian_trailing_slash(self):
        from pxeos.plugins.debian import DebianPlugin

        profile = ProvisionProfile(
            name="t", os_family="debian", os_version="12",
            install_url="http://server/distro/",
        )
        assets = DebianPlugin().live_boot_assets(profile)
        fetch_arg = [a for a in assets.boot_args if "fetch=" in a][0]
        assert "//" not in fetch_arg.split("://", 1)[1]

    def test_arch_trailing_slash(self):
        from pxeos.plugins.arch import ArchPlugin

        profile = ProvisionProfile(
            name="t", os_family="arch", os_version="latest",
            install_url="http://server/distro/",
        )
        assets = ArchPlugin().live_boot_assets(profile)
        http_arg = [a for a in assets.boot_args if "archiso_http_srv=" in a][0]
        assert "//" not in http_arg.split("://", 1)[1]
