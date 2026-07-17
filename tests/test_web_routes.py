"""Tests for the web UI routes."""

from __future__ import annotations

import unittest
from unittest import mock

from fastapi.testclient import TestClient

from pxeos.api import app
from pxeos.models import BootFirmware, ProvisionProfile
from pxeos.registry import PluginRegistry


class WebTestBase(unittest.TestCase):

    def setUp(self):
        self.registry = PluginRegistry()
        self.registry.load_builtins()

        self.tmp = self.enterContext(
            mock.patch("pxeos.api._registry", self.registry)
        )

        self.config = mock.MagicMock()
        self.config.server_host = "0.0.0.0"
        self.config.server_port = 8443
        self.config.tls_cert = None
        self.config.distro_root.exists.return_value = False
        self.config.data_dir.__truediv__ = mock.MagicMock(
            return_value=mock.MagicMock()
        )

        self.enterContext(
            mock.patch("pxeos.api._config", self.config)
        )
        self.enterContext(
            mock.patch("pxeos.api._engine", mock.MagicMock())
        )

        from pxeos.web.routes import router
        if router not in [r for r in app.routes]:
            try:
                app.include_router(router)
            except Exception:
                pass

        self.client = TestClient(app)

    def enterContext(self, cm):
        result = cm.__enter__()
        self.addCleanup(cm.__exit__, None, None, None)
        return result


class TestDashboard(WebTestBase):

    def test_dashboard_returns_200(self):
        resp = self.client.get("/web/")
        self.assertEqual(resp.status_code, 200)

    def test_dashboard_contains_title(self):
        resp = self.client.get("/web/")
        self.assertIn("PxeOS", resp.text)

    def test_dashboard_contains_dashboard_heading(self):
        resp = self.client.get("/web/")
        self.assertIn("Dashboard", resp.text)

    def test_dashboard_contains_plugin_count(self):
        resp = self.client.get("/web/")
        self.assertIn("OS Plugins", resp.text)

    def test_dashboard_contains_flossware_logo(self):
        resp = self.client.get("/web/")
        self.assertIn("avatars.githubusercontent.com", resp.text)

    def test_dashboard_sidebar_nav_links(self):
        resp = self.client.get("/web/")
        for link in ["/web/distros", "/web/profiles", "/web/hosts",
                     "/web/cloud-init", "/web/import"]:
            self.assertIn(link, resp.text)


class TestDistrosPage(WebTestBase):

    def test_distros_page_returns_200(self):
        resp = self.client.get("/web/distros")
        self.assertEqual(resp.status_code, 200)

    def test_distros_page_contains_heading(self):
        resp = self.client.get("/web/distros")
        self.assertIn("Imported Distros", resp.text)

    def test_distros_empty_message(self):
        resp = self.client.get("/web/distros")
        self.assertIn("No distros imported", resp.text)


class TestProfilesPage(WebTestBase):

    def test_profiles_page_returns_200(self):
        resp = self.client.get("/web/profiles")
        self.assertEqual(resp.status_code, 200)

    def test_profiles_page_contains_heading(self):
        resp = self.client.get("/web/profiles")
        self.assertIn("Provisioning Profiles", resp.text)

    def test_profiles_page_has_form(self):
        resp = self.client.get("/web/profiles")
        self.assertIn('name="os_family"', resp.text)

    def test_profiles_page_plugin_options(self):
        resp = self.client.get("/web/profiles")
        self.assertIn("fedora", resp.text)
        self.assertIn("debian", resp.text)


class TestHostsPage(WebTestBase):

    def test_hosts_page_returns_200(self):
        resp = self.client.get("/web/hosts")
        self.assertEqual(resp.status_code, 200)

    def test_hosts_page_contains_heading(self):
        resp = self.client.get("/web/hosts")
        self.assertIn("Host Rules", resp.text)

    def test_hosts_page_has_mac_field(self):
        resp = self.client.get("/web/hosts")
        self.assertIn('name="mac"', resp.text)

    def test_hosts_page_has_priority_field(self):
        resp = self.client.get("/web/hosts")
        self.assertIn('name="priority"', resp.text)


class TestCloudInitPage(WebTestBase):

    def test_cloud_init_page_returns_200(self):
        resp = self.client.get("/web/cloud-init")
        self.assertEqual(resp.status_code, 200)

    def test_cloud_init_page_contains_heading(self):
        resp = self.client.get("/web/cloud-init")
        self.assertIn("Cloud-Init Config Generator", resp.text)

    def test_cloud_init_page_has_name_field(self):
        resp = self.client.get("/web/cloud-init")
        self.assertIn('name="name"', resp.text)

    def test_cloud_init_generate_returns_config(self):
        resp = self.client.post(
            "/web/cloud-init/generate",
            data={"name": "testvm", "user": "admin"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn("#cloud-config", resp.text)
        self.assertIn("user-data", resp.text)

    def test_cloud_init_generate_includes_hostname(self):
        resp = self.client.post(
            "/web/cloud-init/generate",
            data={"name": "myhost", "hostname": "myhost.lab", "user": "admin"},
        )
        self.assertIn("myhost.lab", resp.text)

    def test_cloud_init_generate_static_network(self):
        resp = self.client.post(
            "/web/cloud-init/generate",
            data={
                "name": "staticvm",
                "user": "admin",
                "network": "static",
                "ip": "10.0.0.50/24",
                "gateway": "10.0.0.1",
                "dns": "1.1.1.1,8.8.8.8",
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn("network-config", resp.text)

    def test_cloud_init_generate_with_packages(self):
        resp = self.client.post(
            "/web/cloud-init/generate",
            data={"name": "pkgvm", "user": "admin", "packages": "nginx, git"},
        )
        self.assertIn("nginx", resp.text)

    def test_cloud_init_generate_with_ssh_keys(self):
        resp = self.client.post(
            "/web/cloud-init/generate",
            data={
                "name": "sshvm",
                "user": "admin",
                "ssh_keys": "ssh-ed25519 AAAA testkey",
            },
        )
        self.assertIn("ssh-ed25519", resp.text)


class TestImportPage(WebTestBase):

    def test_import_page_returns_200(self):
        resp = self.client.get("/web/import")
        self.assertEqual(resp.status_code, 200)

    def test_import_page_contains_heading(self):
        resp = self.client.get("/web/import")
        self.assertIn("Import Distro", resp.text)

    def test_import_page_has_upload_form(self):
        resp = self.client.get("/web/import")
        self.assertIn("Upload ISO", resp.text)

    def test_import_page_has_fetch_form(self):
        resp = self.client.get("/web/import")
        self.assertIn("Fetch from URL", resp.text)

    def test_import_page_has_plugin_options(self):
        resp = self.client.get("/web/import")
        self.assertIn("fedora", resp.text)

    @mock.patch("pxeos.importer.import_url")
    def test_import_fetch_success(self, mock_import_url):
        from pxeos.models import DistroAssets
        from pathlib import Path

        mock_import_url.return_value = DistroAssets(
            kernel_path=Path("/srv/pxeos/distros/fedora-42-x86_64/vmlinuz"),
            initrd_path=Path("/srv/pxeos/distros/fedora-42-x86_64/initrd.img"),
            repo_path=Path("/srv/pxeos/distros/fedora-42-x86_64"),
        )
        resp = self.client.post(
            "/web/import/fetch",
            data={
                "os_family": "fedora",
                "version": "42",
                "vendor": "fedora",
                "arch": "x86_64",
                "kernel_url": "https://mirror.example.com/vmlinuz",
                "initrd_url": "https://mirror.example.com/initrd.img",
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Fetch import successful", resp.text)
        self.assertIn("vmlinuz", resp.text)

    @mock.patch("pxeos.importer.import_url")
    def test_import_fetch_failure(self, mock_import_url):
        mock_import_url.side_effect = RuntimeError("mirror down")
        resp = self.client.post(
            "/web/import/fetch",
            data={
                "os_family": "fedora",
                "version": "42",
                "kernel_url": "https://mirror.example.com/vmlinuz",
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Fetch failed", resp.text)


class TestDeleteDistro(WebTestBase):

    def test_delete_distro(self):
        distro_path = mock.MagicMock()
        distro_path.exists.return_value = True
        distro_path.is_dir.return_value = True
        self.config.distro_root.__truediv__ = mock.MagicMock(return_value=distro_path)

        with mock.patch("shutil.rmtree") as mock_rmtree:
            resp = self.client.request("DELETE", "/web/distros/test-distro")
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp.text, "")


class TestDeleteProfile(WebTestBase):

    def test_delete_profile(self):
        profile_path = mock.MagicMock()
        profiles_dir = mock.MagicMock()
        profiles_dir.__truediv__ = mock.MagicMock(return_value=profile_path)
        self.config.data_dir.__truediv__ = mock.MagicMock(return_value=profiles_dir)

        resp = self.client.request("DELETE", "/web/profiles/webserver")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.text, "")
