"""Tests for pxeos.importer -- ISO import, URL import, and helpers."""

from __future__ import annotations

import io
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from pxeos.models import BootAssets, DistroAssets


# ---------------------------------------------------------------------------
# _distro_dir
# ---------------------------------------------------------------------------

class TestDistroDir:
    """Tests for the _distro_dir helper that builds destination directories."""

    def test_creates_correct_directory_name(self, tmp_path):
        """_distro_dir returns distro_root / '{os_family}-{version}-{arch}'."""
        from pxeos.importer import _distro_dir

        result = _distro_dir(tmp_path, "fedora", "40", "x86_64")

        assert result == tmp_path / "fedora-40-x86_64"
        assert result.is_dir()

    def test_creates_parent_directories(self, tmp_path):
        """_distro_dir creates intermediate directories when needed."""
        from pxeos.importer import _distro_dir

        nested = tmp_path / "deep" / "nested" / "root"
        result = _distro_dir(nested, "debian", "12", "amd64")

        assert result == nested / "debian-12-amd64"
        assert result.is_dir()

    def test_idempotent_when_directory_exists(self, tmp_path):
        """Calling _distro_dir twice does not raise even if dir already exists."""
        from pxeos.importer import _distro_dir

        first = _distro_dir(tmp_path, "ubuntu", "24.04", "x86_64")
        second = _distro_dir(tmp_path, "ubuntu", "24.04", "x86_64")

        assert first == second
        assert first.is_dir()


# ---------------------------------------------------------------------------
# import_iso
# ---------------------------------------------------------------------------

class TestImportIso:
    """Tests for import_iso: mount, extract, umount flow."""

    @patch("pxeos.importer.subprocess.run")
    @patch("pxeos.importer.tempfile.mkdtemp")
    def test_calls_mount_and_umount(self, mock_mkdtemp, mock_run, tmp_path):
        """import_iso runs 'mount -o loop,ro' then 'umount' around extraction."""
        mount_dir = str(tmp_path / "mount_point")
        mock_mkdtemp.return_value = mount_dir
        # mkdtemp returns a string but importer wraps it in Path;
        # we need the actual dir to exist so rmdir() succeeds
        Path(mount_dir).mkdir(parents=True, exist_ok=True)

        iso_path = Path("/images/fedora-40.iso")

        fake_assets = DistroAssets(
            kernel_path=tmp_path / "vmlinuz",
            initrd_path=tmp_path / "initrd.img",
            repo_path=tmp_path / "repo",
        )

        mock_plugin = MagicMock()
        mock_plugin.extract_from_iso.return_value = fake_assets

        mock_registry = MagicMock()
        mock_registry.get.return_value = mock_plugin

        from pxeos.importer import import_iso

        result = import_iso(
            iso_path, "fedora", "fedora", "40", "x86_64",
            mock_registry, tmp_path,
        )

        # Verify mount call
        mount_call = mock_run.call_args_list[0]
        assert mount_call == call(
            ["mount", "-o", "loop,ro", str(iso_path), mount_dir],
            check=True,
            capture_output=True,
        )

        # Verify umount call
        umount_call = mock_run.call_args_list[1]
        assert umount_call == call(
            ["umount", mount_dir],
            check=True,
            capture_output=True,
        )

        assert result is fake_assets

    @patch("pxeos.importer.subprocess.run")
    @patch("pxeos.importer.tempfile.mkdtemp")
    def test_extract_from_iso_called_with_correct_paths(
        self, mock_mkdtemp, mock_run, tmp_path,
    ):
        """Plugin's extract_from_iso receives mount_point and dest directory."""
        mount_dir = str(tmp_path / "mnt")
        mock_mkdtemp.return_value = mount_dir
        Path(mount_dir).mkdir(parents=True, exist_ok=True)

        fake_assets = DistroAssets(kernel_path=tmp_path / "vmlinuz")

        mock_plugin = MagicMock()
        mock_plugin.extract_from_iso.return_value = fake_assets

        mock_registry = MagicMock()
        mock_registry.get.return_value = mock_plugin

        from pxeos.importer import import_iso

        import_iso(
            Path("/images/test.iso"), "debian", "debian", "12", "amd64",
            mock_registry, tmp_path,
        )

        mock_plugin.extract_from_iso.assert_called_once()
        call_args = mock_plugin.extract_from_iso.call_args
        mount_arg, dest_arg = call_args[0]

        assert mount_arg == Path(mount_dir)
        assert dest_arg == tmp_path / "debian-12-amd64"

    @patch("pxeos.importer.subprocess.run")
    @patch("pxeos.importer.tempfile.mkdtemp")
    def test_creates_destination_directory(
        self, mock_mkdtemp, mock_run, tmp_path,
    ):
        """import_iso creates distro_root/'{os_family}-{version}-{arch}'."""
        mount_dir = str(tmp_path / "mnt")
        mock_mkdtemp.return_value = mount_dir
        Path(mount_dir).mkdir(parents=True, exist_ok=True)

        mock_plugin = MagicMock()
        mock_plugin.extract_from_iso.return_value = DistroAssets(
            kernel_path=tmp_path / "vmlinuz",
        )

        mock_registry = MagicMock()
        mock_registry.get.return_value = mock_plugin

        from pxeos.importer import import_iso

        distro_root = tmp_path / "distros"
        import_iso(
            Path("/test.iso"), "suse", "suse", "15.5", "x86_64",
            mock_registry, distro_root,
        )

        expected_dir = distro_root / "suse-15.5-x86_64"
        assert expected_dir.is_dir()

    @patch("pxeos.importer.subprocess.run")
    @patch("pxeos.importer.tempfile.mkdtemp")
    def test_registry_get_called_with_os_family(
        self, mock_mkdtemp, mock_run, tmp_path,
    ):
        """import_iso asks the registry for the correct os_family plugin."""
        mount_dir = str(tmp_path / "mnt")
        mock_mkdtemp.return_value = mount_dir
        Path(mount_dir).mkdir(parents=True, exist_ok=True)

        mock_plugin = MagicMock()
        mock_plugin.extract_from_iso.return_value = DistroAssets(
            kernel_path=tmp_path / "vmlinuz",
        )

        mock_registry = MagicMock()
        mock_registry.get.return_value = mock_plugin

        from pxeos.importer import import_iso

        import_iso(
            Path("/test.iso"), "arch", "arch", "rolling", "x86_64",
            mock_registry, tmp_path,
        )

        mock_registry.get.assert_called_once_with("arch")

    @patch("pxeos.importer.subprocess.run")
    @patch("pxeos.importer.tempfile.mkdtemp")
    def test_umount_called_even_on_extract_failure(
        self, mock_mkdtemp, mock_run, tmp_path,
    ):
        """If extract_from_iso raises, umount is still called (finally block)."""
        mount_dir = str(tmp_path / "mnt")
        mock_mkdtemp.return_value = mount_dir
        Path(mount_dir).mkdir(parents=True, exist_ok=True)

        mock_plugin = MagicMock()
        mock_plugin.extract_from_iso.side_effect = RuntimeError("extract failed")

        mock_registry = MagicMock()
        mock_registry.get.return_value = mock_plugin

        from pxeos.importer import import_iso

        with pytest.raises(RuntimeError, match="extract failed"):
            import_iso(
                Path("/test.iso"), "fedora", "fedora", "40", "x86_64",
                mock_registry, tmp_path,
            )

        # umount should still be called even though extract raised
        umount_calls = [
            c for c in mock_run.call_args_list
            if c[0][0][0] == "umount"
        ]
        assert len(umount_calls) == 1


# ---------------------------------------------------------------------------
# _download
# ---------------------------------------------------------------------------

class TestDownload:
    """Tests for the _download helper."""

    @patch("pxeos.importer.urllib.request.urlopen")
    def test_downloads_content_to_file(self, mock_urlopen, tmp_path):
        """_download writes response body to the destination file."""
        content = b"fake kernel binary content"
        mock_response = MagicMock()
        mock_response.__enter__ = MagicMock(
            return_value=io.BytesIO(content),
        )
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_response

        dest = tmp_path / "vmlinuz"

        from pxeos.importer import _download

        _download("http://mirror.example.com/vmlinuz", dest)

        assert dest.read_bytes() == content
        mock_urlopen.assert_called_once_with(
            "http://mirror.example.com/vmlinuz",
        )


# ---------------------------------------------------------------------------
# import_url
# ---------------------------------------------------------------------------

class TestImportUrl:
    """Tests for import_url: download kernel and optional initrd."""

    @patch("pxeos.importer._download")
    def test_downloads_kernel_and_initrd(self, mock_download, tmp_path):
        """import_url downloads both kernel and initrd when boot_assets has both."""
        mock_plugin = MagicMock()
        mock_plugin.boot_assets.return_value = BootAssets(
            kernel="http://mirror.example.com/images/pxeboot/vmlinuz",
            initrd="http://mirror.example.com/images/pxeboot/initrd.img",
        )

        mock_registry = MagicMock()
        mock_registry.get.return_value = mock_plugin

        from pxeos.importer import import_url

        result = import_url(
            "http://mirror.example.com/fedora/40/x86_64",
            "fedora", "fedora", "40", "x86_64",
            mock_registry, tmp_path,
        )

        assert mock_download.call_count == 2

        # First call is the kernel
        kernel_url = mock_download.call_args_list[0][0][0]
        assert kernel_url == "http://mirror.example.com/images/pxeboot/vmlinuz"

        # Second call is the initrd
        initrd_url = mock_download.call_args_list[1][0][0]
        assert initrd_url == "http://mirror.example.com/images/pxeboot/initrd.img"

        # Result has both paths set
        assert result.kernel_path is not None
        assert result.initrd_path is not None
        assert result.kernel_path.name == "vmlinuz"
        assert result.initrd_path.name == "initrd.img"

    @patch("pxeos.importer._download")
    def test_no_initrd_download_when_boot_assets_lacks_initrd(
        self, mock_download, tmp_path,
    ):
        """import_url skips initrd download when boot_assets.initrd is None."""
        mock_plugin = MagicMock()
        mock_plugin.boot_assets.return_value = BootAssets(
            kernel="http://mirror.example.com/freebsd/boot/kernel",
            initrd=None,
        )

        mock_registry = MagicMock()
        mock_registry.get.return_value = mock_plugin

        from pxeos.importer import import_url

        result = import_url(
            "http://mirror.example.com/freebsd/14.1",
            "freebsd", "freebsd", "14.1", "amd64",
            mock_registry, tmp_path,
        )

        # Only one download call (kernel only)
        assert mock_download.call_count == 1
        kernel_url = mock_download.call_args_list[0][0][0]
        assert kernel_url == "http://mirror.example.com/freebsd/boot/kernel"

        assert result.kernel_path is not None
        assert result.initrd_path is None

    @patch("pxeos.importer._download")
    def test_creates_destination_directories(self, mock_download, tmp_path):
        """import_url creates the kernel/ and repo/ subdirectories."""
        mock_plugin = MagicMock()
        mock_plugin.boot_assets.return_value = BootAssets(
            kernel="http://example.com/vmlinuz",
            initrd=None,
        )

        mock_registry = MagicMock()
        mock_registry.get.return_value = mock_plugin

        from pxeos.importer import import_url

        distro_root = tmp_path / "distros"
        import_url(
            "http://example.com/ubuntu/24.04",
            "ubuntu", "ubuntu", "24.04", "x86_64",
            mock_registry, distro_root,
        )

        dest = distro_root / "ubuntu-24.04-x86_64"
        assert (dest / "kernel").is_dir()
        assert (dest / "repo").is_dir()

    @patch("pxeos.importer._download")
    def test_returns_distro_assets(self, mock_download, tmp_path):
        """import_url returns a DistroAssets with correct paths."""
        mock_plugin = MagicMock()
        mock_plugin.boot_assets.return_value = BootAssets(
            kernel="http://example.com/images/vmlinuz",
            initrd="http://example.com/images/initrd.img",
        )

        mock_registry = MagicMock()
        mock_registry.get.return_value = mock_plugin

        from pxeos.importer import import_url

        result = import_url(
            "http://example.com/fedora/40",
            "fedora", "fedora", "40", "x86_64",
            mock_registry, tmp_path,
        )

        assert isinstance(result, DistroAssets)
        expected_dest = tmp_path / "fedora-40-x86_64"
        assert result.kernel_path == expected_dest / "kernel" / "vmlinuz"
        assert result.initrd_path == expected_dest / "kernel" / "initrd.img"
        assert result.repo_path == expected_dest / "repo"

    @patch("pxeos.importer._download")
    def test_plugin_boot_assets_receives_stub_profile(
        self, mock_download, tmp_path,
    ):
        """import_url passes a ProvisionProfile stub to plugin.boot_assets."""
        mock_plugin = MagicMock()
        mock_plugin.boot_assets.return_value = BootAssets(
            kernel="http://example.com/vmlinuz",
        )

        mock_registry = MagicMock()
        mock_registry.get.return_value = mock_plugin

        from pxeos.importer import import_url

        import_url(
            "http://example.com/mirror",
            "debian", "debian", "12", "amd64",
            mock_registry, tmp_path,
        )

        mock_plugin.boot_assets.assert_called_once()
        profile_arg = mock_plugin.boot_assets.call_args[0][0]

        assert profile_arg.name == "debian-12-amd64"
        assert profile_arg.os_family == "debian"
        assert profile_arg.vendor == "debian"
        assert profile_arg.os_version == "12"
        assert profile_arg.arch == "amd64"
        assert profile_arg.install_url == "http://example.com/mirror"
