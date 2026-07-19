"""Tests for TFTPManager — TFTP root directory management for PXE boot files."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from pxeos.models import BootAssets, DistroAssets, HostRule
from pxeos.tftp import TFTPManager


# ---- helpers ----


def _distro_assets(
    tmp_path: Path,
    *,
    with_initrd: bool = True,
    kernel_name: str = "vmlinuz",
    initrd_name: str = "initrd.img",
) -> DistroAssets:
    """Create real files and return a DistroAssets pointing at them."""
    distro_dir = tmp_path / "distros" / "fedora" / "41"
    distro_dir.mkdir(parents=True, exist_ok=True)

    kernel = distro_dir / kernel_name
    kernel.write_bytes(b"\x00KERNEL_CONTENT")

    initrd = None
    if with_initrd:
        initrd = distro_dir / initrd_name
        initrd.write_bytes(b"\x00INITRD_CONTENT")

    return DistroAssets(kernel_path=kernel, initrd_path=initrd)


def _boot_assets(**kwargs) -> BootAssets:
    kwargs.setdefault("kernel", "/images/fedora/41/vmlinuz")
    kwargs.setdefault("initrd", "/images/fedora/41/initrd.img")
    kwargs.setdefault("boot_args", ("ip=dhcp", "rd.live.image"))
    return BootAssets(**kwargs)


def _host_rule(**kwargs) -> HostRule:
    kwargs.setdefault("profile", "fedora-server")
    kwargs.setdefault("os_family", "fedora")
    kwargs.setdefault("os_version", "41")
    return HostRule(**kwargs)


def _manager(tmp_path: Path) -> TFTPManager:
    tftp_root = tmp_path / "tftpboot"
    tftp_root.mkdir(parents=True, exist_ok=True)
    return TFTPManager(tftp_root)


# ---- TFTPManager.__init__ ----


class TestInit:

    def test_stores_root_path(self, tmp_path):
        root = tmp_path / "tftpboot"
        mgr = TFTPManager(root)
        assert mgr._root == root

    def test_accepts_path_object(self, tmp_path):
        mgr = TFTPManager(tmp_path)
        assert isinstance(mgr._root, Path)


# ---- setup_boot_files ----


class TestSetupBootFiles:

    def test_creates_profile_directory(self, tmp_path):
        mgr = _manager(tmp_path)
        distro = _distro_assets(tmp_path)
        mgr.setup_boot_files(distro, "fedora-server")

        profile_dir = mgr._root / "fedora-server"
        assert profile_dir.is_dir()

    def test_creates_kernel_symlink(self, tmp_path):
        mgr = _manager(tmp_path)
        distro = _distro_assets(tmp_path)
        mgr.setup_boot_files(distro, "fedora-server")

        kernel_link = mgr._root / "fedora-server" / "vmlinuz"
        assert kernel_link.is_symlink()
        assert kernel_link.resolve() == distro.kernel_path.resolve()

    def test_creates_initrd_symlink(self, tmp_path):
        mgr = _manager(tmp_path)
        distro = _distro_assets(tmp_path)
        mgr.setup_boot_files(distro, "fedora-server")

        initrd_link = mgr._root / "fedora-server" / "initrd.img"
        assert initrd_link.is_symlink()
        assert initrd_link.resolve() == distro.initrd_path.resolve()

    def test_no_initrd_when_none(self, tmp_path):
        mgr = _manager(tmp_path)
        distro = _distro_assets(tmp_path, with_initrd=False)
        mgr.setup_boot_files(distro, "fedora-server")

        profile_dir = mgr._root / "fedora-server"
        items = list(profile_dir.iterdir())
        assert len(items) == 1
        assert items[0].name == "vmlinuz"

    def test_replaces_existing_kernel_symlink(self, tmp_path):
        mgr = _manager(tmp_path)
        distro1 = _distro_assets(tmp_path, kernel_name="vmlinuz")
        mgr.setup_boot_files(distro1, "myprofile")

        # Create a second distro with different content
        distro_dir2 = tmp_path / "distros2" / "fedora" / "42"
        distro_dir2.mkdir(parents=True)
        kernel2 = distro_dir2 / "vmlinuz"
        kernel2.write_bytes(b"\x00KERNEL_V2")
        distro2 = DistroAssets(kernel_path=kernel2, initrd_path=None)

        mgr.setup_boot_files(distro2, "myprofile")

        kernel_link = mgr._root / "myprofile" / "vmlinuz"
        assert kernel_link.is_symlink()
        assert kernel_link.resolve() == kernel2.resolve()

    def test_replaces_existing_initrd_symlink(self, tmp_path):
        mgr = _manager(tmp_path)
        distro1 = _distro_assets(tmp_path)
        mgr.setup_boot_files(distro1, "myprofile")

        # New initrd
        distro_dir2 = tmp_path / "distros2" / "fedora" / "42"
        distro_dir2.mkdir(parents=True)
        kernel2 = distro_dir2 / "vmlinuz"
        kernel2.write_bytes(b"\x00K2")
        initrd2 = distro_dir2 / "initrd.img"
        initrd2.write_bytes(b"\x00I2")
        distro2 = DistroAssets(kernel_path=kernel2, initrd_path=initrd2)

        mgr.setup_boot_files(distro2, "myprofile")

        initrd_link = mgr._root / "myprofile" / "initrd.img"
        assert initrd_link.is_symlink()
        assert initrd_link.resolve() == initrd2.resolve()

    def test_replaces_dangling_symlink(self, tmp_path):
        """If previous target was deleted, the dangling symlink is replaced."""
        mgr = _manager(tmp_path)
        profile_dir = mgr._root / "myprofile"
        profile_dir.mkdir(parents=True)

        # Create a dangling symlink
        dangling = profile_dir / "vmlinuz"
        dangling.symlink_to(tmp_path / "nonexistent" / "vmlinuz")
        assert dangling.is_symlink()
        assert not dangling.exists()  # dangling

        distro = _distro_assets(tmp_path)
        mgr.setup_boot_files(distro, "myprofile")

        assert dangling.is_symlink()
        assert dangling.exists()  # no longer dangling

    def test_creates_nested_profile_dirs(self, tmp_path):
        """Profile names with slashes should create nested directories."""
        mgr = _manager(tmp_path)
        distro = _distro_assets(tmp_path)
        mgr.setup_boot_files(distro, "fedora/41/server")

        profile_dir = mgr._root / "fedora" / "41" / "server"
        assert profile_dir.is_dir()
        assert (profile_dir / "vmlinuz").is_symlink()

    def test_idempotent_repeated_calls(self, tmp_path):
        """Calling setup_boot_files twice with same args should not error."""
        mgr = _manager(tmp_path)
        distro = _distro_assets(tmp_path)

        mgr.setup_boot_files(distro, "fedora-server")
        mgr.setup_boot_files(distro, "fedora-server")

        kernel_link = mgr._root / "fedora-server" / "vmlinuz"
        assert kernel_link.is_symlink()

    def test_multiple_profiles_coexist(self, tmp_path):
        mgr = _manager(tmp_path)
        distro = _distro_assets(tmp_path)

        mgr.setup_boot_files(distro, "profile-a")
        mgr.setup_boot_files(distro, "profile-b")

        assert (mgr._root / "profile-a" / "vmlinuz").is_symlink()
        assert (mgr._root / "profile-b" / "vmlinuz").is_symlink()

    def test_symlink_targets_are_absolute(self, tmp_path):
        """Symlinks should point to absolute resolved paths."""
        mgr = _manager(tmp_path)
        distro = _distro_assets(tmp_path)
        mgr.setup_boot_files(distro, "fedora-server")

        kernel_link = mgr._root / "fedora-server" / "vmlinuz"
        target = os.readlink(str(kernel_link))
        assert os.path.isabs(target)


# ---- generate_pxe_config ----


class TestGeneratePxeConfig:

    def test_creates_pxelinux_cfg_directory(self, tmp_path):
        mgr = _manager(tmp_path)
        rule = _host_rule()
        assets = _boot_assets()
        mgr.generate_pxe_config(rule, assets, "aa:bb:cc:dd:ee:ff")

        pxelinux_dir = mgr._root / "pxelinux.cfg"
        assert pxelinux_dir.is_dir()

    def test_creates_mac_config_file(self, tmp_path):
        mgr = _manager(tmp_path)
        rule = _host_rule()
        assets = _boot_assets()
        mgr.generate_pxe_config(rule, assets, "AA:BB:CC:DD:EE:FF")

        config_file = mgr._root / "pxelinux.cfg" / "01-aa-bb-cc-dd-ee-ff"
        assert config_file.is_file()

    def test_mac_normalization_lowercase(self, tmp_path):
        mgr = _manager(tmp_path)
        rule = _host_rule()
        assets = _boot_assets()
        mgr.generate_pxe_config(rule, assets, "AA:BB:CC:DD:EE:FF")

        config_file = mgr._root / "pxelinux.cfg" / "01-aa-bb-cc-dd-ee-ff"
        assert config_file.exists()

    def test_mac_normalization_dashes(self, tmp_path):
        """Colons in MAC are replaced with dashes in the filename."""
        mgr = _manager(tmp_path)
        rule = _host_rule()
        assets = _boot_assets()
        mgr.generate_pxe_config(rule, assets, "aa:bb:cc:dd:ee:ff")

        config_file = mgr._root / "pxelinux.cfg" / "01-aa-bb-cc-dd-ee-ff"
        assert config_file.name == "01-aa-bb-cc-dd-ee-ff"
        assert config_file.is_file()

    def test_config_contains_default_and_label(self, tmp_path):
        mgr = _manager(tmp_path)
        rule = _host_rule()
        assets = _boot_assets()
        mgr.generate_pxe_config(rule, assets, "aa:bb:cc:dd:ee:ff")

        content = (
            mgr._root / "pxelinux.cfg" / "01-aa-bb-cc-dd-ee-ff"
        ).read_text()
        assert "DEFAULT install" in content
        assert "PROMPT 0" in content
        assert "TIMEOUT 1" in content
        assert "LABEL install" in content

    def test_config_contains_kernel(self, tmp_path):
        mgr = _manager(tmp_path)
        rule = _host_rule()
        assets = _boot_assets(kernel="/images/fedora/41/vmlinuz")
        mgr.generate_pxe_config(rule, assets, "aa:bb:cc:dd:ee:ff")

        content = (
            mgr._root / "pxelinux.cfg" / "01-aa-bb-cc-dd-ee-ff"
        ).read_text()
        assert "KERNEL /images/fedora/41/vmlinuz" in content

    def test_config_contains_initrd(self, tmp_path):
        mgr = _manager(tmp_path)
        rule = _host_rule()
        assets = _boot_assets(initrd="/images/fedora/41/initrd.img")
        mgr.generate_pxe_config(rule, assets, "aa:bb:cc:dd:ee:ff")

        content = (
            mgr._root / "pxelinux.cfg" / "01-aa-bb-cc-dd-ee-ff"
        ).read_text()
        assert "INITRD /images/fedora/41/initrd.img" in content

    def test_config_contains_append_args(self, tmp_path):
        mgr = _manager(tmp_path)
        rule = _host_rule()
        assets = _boot_assets(boot_args=("ip=dhcp", "rd.live.image"))
        mgr.generate_pxe_config(rule, assets, "aa:bb:cc:dd:ee:ff")

        content = (
            mgr._root / "pxelinux.cfg" / "01-aa-bb-cc-dd-ee-ff"
        ).read_text()
        assert "APPEND ip=dhcp rd.live.image" in content

    def test_config_no_initrd_when_none(self, tmp_path):
        mgr = _manager(tmp_path)
        rule = _host_rule()
        assets = _boot_assets(initrd=None)
        mgr.generate_pxe_config(rule, assets, "aa:bb:cc:dd:ee:ff")

        content = (
            mgr._root / "pxelinux.cfg" / "01-aa-bb-cc-dd-ee-ff"
        ).read_text()
        assert "INITRD" not in content

    def test_config_no_append_when_empty_args(self, tmp_path):
        mgr = _manager(tmp_path)
        rule = _host_rule()
        assets = _boot_assets(boot_args=())
        mgr.generate_pxe_config(rule, assets, "aa:bb:cc:dd:ee:ff")

        content = (
            mgr._root / "pxelinux.cfg" / "01-aa-bb-cc-dd-ee-ff"
        ).read_text()
        assert "APPEND" not in content

    def test_config_no_initrd_no_append(self, tmp_path):
        """Minimal config with only kernel."""
        mgr = _manager(tmp_path)
        rule = _host_rule()
        assets = _boot_assets(initrd=None, boot_args=())
        mgr.generate_pxe_config(rule, assets, "aa:bb:cc:dd:ee:ff")

        content = (
            mgr._root / "pxelinux.cfg" / "01-aa-bb-cc-dd-ee-ff"
        ).read_text()
        assert "KERNEL" in content
        assert "INITRD" not in content
        assert "APPEND" not in content

    def test_config_ends_with_newline(self, tmp_path):
        mgr = _manager(tmp_path)
        rule = _host_rule()
        assets = _boot_assets()
        mgr.generate_pxe_config(rule, assets, "aa:bb:cc:dd:ee:ff")

        content = (
            mgr._root / "pxelinux.cfg" / "01-aa-bb-cc-dd-ee-ff"
        ).read_text()
        assert content.endswith("\n")

    def test_overwrites_existing_config(self, tmp_path):
        mgr = _manager(tmp_path)
        rule = _host_rule()

        assets1 = _boot_assets(kernel="/images/old/vmlinuz")
        mgr.generate_pxe_config(rule, assets1, "aa:bb:cc:dd:ee:ff")

        assets2 = _boot_assets(kernel="/images/new/vmlinuz")
        mgr.generate_pxe_config(rule, assets2, "aa:bb:cc:dd:ee:ff")

        content = (
            mgr._root / "pxelinux.cfg" / "01-aa-bb-cc-dd-ee-ff"
        ).read_text()
        assert "/images/new/vmlinuz" in content
        assert "/images/old/vmlinuz" not in content

    def test_different_macs_get_separate_configs(self, tmp_path):
        mgr = _manager(tmp_path)
        rule = _host_rule()
        assets = _boot_assets()

        mgr.generate_pxe_config(rule, assets, "aa:bb:cc:dd:ee:01")
        mgr.generate_pxe_config(rule, assets, "aa:bb:cc:dd:ee:02")

        pxelinux_dir = mgr._root / "pxelinux.cfg"
        configs = list(pxelinux_dir.iterdir())
        assert len(configs) == 2

    def test_config_exact_format(self, tmp_path):
        """Verify the exact PXE config format for a full config."""
        mgr = _manager(tmp_path)
        rule = _host_rule()
        assets = _boot_assets(
            kernel="/images/fedora/41/vmlinuz",
            initrd="/images/fedora/41/initrd.img",
            boot_args=("ip=dhcp", "inst.repo=http://mirror/fedora/41"),
        )
        mgr.generate_pxe_config(rule, assets, "aa:bb:cc:dd:ee:ff")

        content = (
            mgr._root / "pxelinux.cfg" / "01-aa-bb-cc-dd-ee-ff"
        ).read_text()

        expected_lines = [
            "DEFAULT install",
            "PROMPT 0",
            "TIMEOUT 1",
            "",
            "LABEL install",
            "  KERNEL /images/fedora/41/vmlinuz",
            "  INITRD /images/fedora/41/initrd.img",
            "  APPEND ip=dhcp inst.repo=http://mirror/fedora/41",
            "",
        ]
        assert content == "\n".join(expected_lines)

    def test_boot_args_single_arg(self, tmp_path):
        mgr = _manager(tmp_path)
        rule = _host_rule()
        assets = _boot_assets(boot_args=("ip=dhcp",))
        mgr.generate_pxe_config(rule, assets, "aa:bb:cc:dd:ee:ff")

        content = (
            mgr._root / "pxelinux.cfg" / "01-aa-bb-cc-dd-ee-ff"
        ).read_text()
        assert "APPEND ip=dhcp" in content

    def test_mixed_case_mac(self, tmp_path):
        """MAC with mixed case should normalize to lowercase."""
        mgr = _manager(tmp_path)
        rule = _host_rule()
        assets = _boot_assets()
        mgr.generate_pxe_config(rule, assets, "Aa:Bb:Cc:Dd:Ee:Ff")

        config_file = mgr._root / "pxelinux.cfg" / "01-aa-bb-cc-dd-ee-ff"
        assert config_file.is_file()


# ---- cleanup ----


class TestCleanup:

    def test_removes_profile_directory(self, tmp_path):
        mgr = _manager(tmp_path)
        distro = _distro_assets(tmp_path)
        mgr.setup_boot_files(distro, "fedora-server")

        assert (mgr._root / "fedora-server").exists()
        mgr.cleanup("fedora-server")
        assert not (mgr._root / "fedora-server").exists()

    def test_removes_symlinks_in_profile_dir(self, tmp_path):
        mgr = _manager(tmp_path)
        distro = _distro_assets(tmp_path)
        mgr.setup_boot_files(distro, "fedora-server")

        mgr.cleanup("fedora-server")

        assert not (mgr._root / "fedora-server").exists()

    def test_removes_matching_pxelinux_configs(self, tmp_path):
        mgr = _manager(tmp_path)
        rule = _host_rule(profile="fedora-server")
        assets = _boot_assets(
            kernel="fedora-server/vmlinuz",
            initrd="fedora-server/initrd.img",
        )
        mgr.generate_pxe_config(rule, assets, "aa:bb:cc:dd:ee:ff")

        config_file = mgr._root / "pxelinux.cfg" / "01-aa-bb-cc-dd-ee-ff"
        assert config_file.exists()

        mgr.cleanup("fedora-server")
        assert not config_file.exists()

    def test_preserves_unrelated_pxelinux_configs(self, tmp_path):
        mgr = _manager(tmp_path)
        rule = _host_rule(profile="fedora-server")

        # Config referencing "fedora-server"
        assets1 = _boot_assets(kernel="fedora-server/vmlinuz")
        mgr.generate_pxe_config(rule, assets1, "aa:bb:cc:dd:ee:01")

        # Config NOT referencing "fedora-server"
        rule2 = _host_rule(profile="debian-desktop")
        assets2 = _boot_assets(kernel="debian-desktop/vmlinuz")
        mgr.generate_pxe_config(rule2, assets2, "aa:bb:cc:dd:ee:02")

        mgr.cleanup("fedora-server")

        assert not (
            mgr._root / "pxelinux.cfg" / "01-aa-bb-cc-dd-ee-01"
        ).exists()
        assert (
            mgr._root / "pxelinux.cfg" / "01-aa-bb-cc-dd-ee-02"
        ).exists()

    def test_cleanup_nonexistent_profile_is_noop(self, tmp_path):
        mgr = _manager(tmp_path)
        # Should not raise
        mgr.cleanup("does-not-exist")

    def test_cleanup_no_pxelinux_dir_is_noop(self, tmp_path):
        mgr = _manager(tmp_path)
        # Profile dir exists but no pxelinux.cfg dir
        profile_dir = mgr._root / "myprofile"
        profile_dir.mkdir()
        (profile_dir / "somefile").write_text("data")

        mgr.cleanup("myprofile")
        assert not profile_dir.exists()

    def test_cleanup_removes_regular_files_in_profile(self, tmp_path):
        """cleanup removes plain files (not just symlinks) in profile dir."""
        mgr = _manager(tmp_path)
        profile_dir = mgr._root / "myprofile"
        profile_dir.mkdir()
        (profile_dir / "extra.txt").write_text("notes")
        (profile_dir / "config.cfg").write_text("cfg")

        mgr.cleanup("myprofile")
        assert not profile_dir.exists()

    def test_cleanup_handles_oserror_on_config_read(self, tmp_path):
        """If a pxelinux config file cannot be read, it's silently skipped."""
        mgr = _manager(tmp_path)
        pxelinux_dir = mgr._root / "pxelinux.cfg"
        pxelinux_dir.mkdir(parents=True)

        # Create a config file then make it unreadable
        config_file = pxelinux_dir / "01-aa-bb-cc-dd-ee-ff"
        config_file.write_text("fedora-server content")
        config_file.chmod(0o000)

        try:
            # Should not raise despite unreadable file
            mgr.cleanup("fedora-server")
        finally:
            # Restore permissions for cleanup
            config_file.chmod(0o644)

    def test_cleanup_with_setup_and_config(self, tmp_path):
        """Full lifecycle: setup + config + cleanup removes everything."""
        mgr = _manager(tmp_path)
        distro = _distro_assets(tmp_path)

        # Setup boot files
        mgr.setup_boot_files(distro, "test-profile")

        # Generate PXE config that references the profile
        rule = _host_rule(profile="test-profile")
        assets = _boot_assets(kernel="test-profile/vmlinuz")
        mgr.generate_pxe_config(rule, assets, "aa:bb:cc:dd:ee:ff")

        # Verify everything exists
        assert (mgr._root / "test-profile").is_dir()
        assert (
            mgr._root / "pxelinux.cfg" / "01-aa-bb-cc-dd-ee-ff"
        ).is_file()

        # Cleanup
        mgr.cleanup("test-profile")

        # Verify everything is gone
        assert not (mgr._root / "test-profile").exists()
        assert not (
            mgr._root / "pxelinux.cfg" / "01-aa-bb-cc-dd-ee-ff"
        ).exists()

    def test_cleanup_multiple_matching_configs(self, tmp_path):
        """Cleanup removes ALL configs referencing the profile."""
        mgr = _manager(tmp_path)
        rule = _host_rule(profile="fedora-server")
        assets = _boot_assets(kernel="fedora-server/vmlinuz")

        mgr.generate_pxe_config(rule, assets, "aa:bb:cc:dd:ee:01")
        mgr.generate_pxe_config(rule, assets, "aa:bb:cc:dd:ee:02")
        mgr.generate_pxe_config(rule, assets, "aa:bb:cc:dd:ee:03")

        mgr.cleanup("fedora-server")

        pxelinux_dir = mgr._root / "pxelinux.cfg"
        remaining = list(pxelinux_dir.iterdir())
        assert remaining == []


# ---- edge cases and integration ----


class TestEdgeCases:

    def test_empty_profile_name(self, tmp_path):
        """Empty profile name still works (creates root-level files)."""
        mgr = _manager(tmp_path)
        distro = _distro_assets(tmp_path)
        # Empty string profile creates files directly in root
        mgr.setup_boot_files(distro, "")
        assert (mgr._root / "vmlinuz").is_symlink()

    def test_profile_name_with_special_chars(self, tmp_path):
        """Profile names with dots and underscores work."""
        mgr = _manager(tmp_path)
        distro = _distro_assets(tmp_path)
        mgr.setup_boot_files(distro, "fedora_41.server-x86_64")

        profile_dir = mgr._root / "fedora_41.server-x86_64"
        assert profile_dir.is_dir()

    def test_kernel_and_initrd_with_unusual_names(self, tmp_path):
        """Boot files with non-standard names are handled correctly."""
        mgr = _manager(tmp_path)
        distro = _distro_assets(
            tmp_path,
            kernel_name="bzImage-5.10.0",
            initrd_name="rootfs.cpio.gz",
        )
        mgr.setup_boot_files(distro, "custom")

        assert (mgr._root / "custom" / "bzImage-5.10.0").is_symlink()
        assert (mgr._root / "custom" / "rootfs.cpio.gz").is_symlink()

    def test_cleanup_then_recreate(self, tmp_path):
        """After cleanup, setup_boot_files should work again."""
        mgr = _manager(tmp_path)
        distro = _distro_assets(tmp_path)

        mgr.setup_boot_files(distro, "myprofile")
        mgr.cleanup("myprofile")
        assert not (mgr._root / "myprofile").exists()

        mgr.setup_boot_files(distro, "myprofile")
        assert (mgr._root / "myprofile" / "vmlinuz").is_symlink()

    def test_generate_config_for_multiple_hosts(self, tmp_path):
        """Different hosts get separate PXE configs."""
        mgr = _manager(tmp_path)
        rule = _host_rule()

        for i in range(5):
            mac = f"aa:bb:cc:dd:ee:{i:02x}"
            assets = _boot_assets(
                kernel=f"profile-{i}/vmlinuz",
            )
            mgr.generate_pxe_config(rule, assets, mac)

        pxelinux_dir = mgr._root / "pxelinux.cfg"
        configs = sorted(pxelinux_dir.iterdir())
        assert len(configs) == 5

    def test_pxelinux_cfg_reuses_existing_directory(self, tmp_path):
        """If pxelinux.cfg already exists, it is reused."""
        mgr = _manager(tmp_path)
        pxelinux_dir = mgr._root / "pxelinux.cfg"
        pxelinux_dir.mkdir()

        rule = _host_rule()
        assets = _boot_assets()
        mgr.generate_pxe_config(rule, assets, "aa:bb:cc:dd:ee:ff")

        assert pxelinux_dir.is_dir()
        assert len(list(pxelinux_dir.iterdir())) == 1

    def test_boot_args_with_spaces_in_values(self, tmp_path):
        """Boot args are joined with spaces."""
        mgr = _manager(tmp_path)
        rule = _host_rule()
        assets = _boot_assets(
            boot_args=(
                "ip=dhcp",
                "inst.ks=http://pxe.example.com/ks cfg",
                "console=ttyS0,115200",
            )
        )
        mgr.generate_pxe_config(rule, assets, "aa:bb:cc:dd:ee:ff")

        content = (
            mgr._root / "pxelinux.cfg" / "01-aa-bb-cc-dd-ee-ff"
        ).read_text()
        assert (
            "APPEND ip=dhcp inst.ks=http://pxe.example.com/ks cfg"
            " console=ttyS0,115200"
        ) in content


class TestCleanupPartialContent:
    """Test cleanup when profile_name appears as substring in config content."""

    def test_cleanup_matches_profile_in_kernel_path(self, tmp_path):
        mgr = _manager(tmp_path)
        pxelinux_dir = mgr._root / "pxelinux.cfg"
        pxelinux_dir.mkdir(parents=True)

        config_file = pxelinux_dir / "01-aa-bb-cc-dd-ee-ff"
        config_file.write_text(
            "DEFAULT install\nKERNEL my-profile/vmlinuz\n"
        )

        mgr.cleanup("my-profile")
        assert not config_file.exists()

    def test_cleanup_does_not_match_unrelated_content(self, tmp_path):
        mgr = _manager(tmp_path)
        pxelinux_dir = mgr._root / "pxelinux.cfg"
        pxelinux_dir.mkdir(parents=True)

        config_file = pxelinux_dir / "01-aa-bb-cc-dd-ee-ff"
        config_file.write_text(
            "DEFAULT install\nKERNEL other-profile/vmlinuz\n"
        )

        mgr.cleanup("my-profile")
        assert config_file.exists()
