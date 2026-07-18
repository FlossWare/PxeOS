"""Tests for pxeos.client -- VM hypervisor backends and provisioning workflow."""

from __future__ import annotations

import json
import subprocess
from unittest.mock import MagicMock, patch, call

import pytest

from pxeos.client.base import VirtBackend, detect_hypervisor
from pxeos.client.libvirt_backend import LibvirtBackend
from pxeos.client.bhyve_backend import BhyveBackend
from pxeos.client.vmm_backend import VmmBackend
from pxeos.client.hyperv_backend import HyperVBackend
from pxeos.client.workflow import (
    provision_vm,
    _generate_mac,
    _register_host,
    _poll_provision_status,
)


# ---------------------------------------------------------------------------
# VirtBackend ABC tests
# ---------------------------------------------------------------------------


class TestVirtBackendABC:
    """Tests for the VirtBackend abstract base class."""

    def test_cannot_instantiate_directly(self):
        """VirtBackend cannot be instantiated without implementing all methods."""
        with pytest.raises(TypeError):
            VirtBackend()

    def test_concrete_subclass_must_implement_all(self):
        """A subclass missing any abstract method cannot be instantiated."""
        class IncompleteBackend(VirtBackend):
            def create_vm(self, name, mac, **kw):
                pass
            # Missing other methods

        with pytest.raises(TypeError):
            IncompleteBackend()

    def test_concrete_subclass_works(self):
        """A fully implemented subclass can be instantiated."""
        class DummyBackend(VirtBackend):
            def create_vm(self, name, mac, memory_mb=2048, vcpus=2,
                          disk_gb=20, bridge=None):
                return {"name": name, "mac": mac}
            def start_vm(self, name): pass
            def stop_vm(self, name): pass
            def delete_vm(self, name): pass
            def get_vm_status(self, name): return "stopped"
            def is_available(self): return True
            @property
            def hypervisor_name(self): return "dummy"

        backend = DummyBackend()
        assert backend.hypervisor_name == "dummy"
        assert backend.is_available() is True
        result = backend.create_vm("test", "00:11:22:33:44:55")
        assert result["name"] == "test"


# ---------------------------------------------------------------------------
# detect_hypervisor tests
# ---------------------------------------------------------------------------


class TestDetectHypervisor:
    """Tests for the detect_hypervisor function."""

    @patch("pxeos.client.libvirt_backend.shutil.which", return_value="/usr/bin/virsh")
    def test_detects_libvirt(self, mock_which):
        """detect_hypervisor returns LibvirtBackend when virsh is present."""
        result = detect_hypervisor()
        assert result is not None
        assert result.hypervisor_name == "libvirt"

    @patch("shutil.which")
    def test_detects_bhyve_when_no_libvirt(self, mock_which):
        """detect_hypervisor returns BhyveBackend when only bhyvectl is present."""
        def which_side_effect(cmd):
            if cmd == "bhyvectl":
                return "/usr/sbin/bhyvectl"
            return None
        mock_which.side_effect = which_side_effect

        result = detect_hypervisor()
        assert result is not None
        assert result.hypervisor_name == "bhyve"

    @patch("shutil.which")
    def test_detects_vmm_when_no_libvirt_or_bhyve(self, mock_which):
        """detect_hypervisor returns VmmBackend when only vmctl is present."""
        def which_side_effect(cmd):
            if cmd == "vmctl":
                return "/usr/sbin/vmctl"
            return None
        mock_which.side_effect = which_side_effect

        result = detect_hypervisor()
        assert result is not None
        assert result.hypervisor_name == "vmm"

    @patch("shutil.which", return_value=None)
    def test_returns_none_when_nothing_available(self, mock_which):
        """detect_hypervisor returns None when no hypervisor tools are found."""
        result = detect_hypervisor()
        assert result is None


# ---------------------------------------------------------------------------
# LibvirtBackend tests
# ---------------------------------------------------------------------------


class TestLibvirtBackend:
    """Tests for LibvirtBackend (mocked subprocess for virt-install/virsh)."""

    def test_hypervisor_name(self):
        backend = LibvirtBackend()
        assert backend.hypervisor_name == "libvirt"

    @patch("pxeos.client.libvirt_backend.shutil.which", return_value="/usr/bin/virsh")
    def test_is_available_true(self, mock_which):
        assert LibvirtBackend().is_available() is True

    @patch("pxeos.client.libvirt_backend.shutil.which", return_value=None)
    def test_is_available_false(self, mock_which):
        assert LibvirtBackend().is_available() is False

    @patch("pxeos.client.libvirt_backend.subprocess.run")
    def test_create_vm(self, mock_run):
        """create_vm calls virt-install with correct arguments."""
        mock_run.return_value = MagicMock(returncode=0)
        backend = LibvirtBackend()
        result = backend.create_vm(
            "test-vm", "aa:bb:cc:dd:ee:ff",
            memory_mb=4096, vcpus=4, disk_gb=40, bridge="br0",
        )
        assert result["name"] == "test-vm"
        assert result["mac"] == "aa:bb:cc:dd:ee:ff"
        assert result["bridge"] == "br0"

        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "virt-install"
        assert "--pxe" in cmd
        assert "--name" in cmd
        idx = cmd.index("--name")
        assert cmd[idx + 1] == "test-vm"

    @patch("pxeos.client.libvirt_backend.subprocess.run")
    def test_create_vm_default_bridge(self, mock_run):
        """create_vm uses virbr0 as default bridge."""
        mock_run.return_value = MagicMock(returncode=0)
        result = LibvirtBackend().create_vm("vm1", "aa:bb:cc:dd:ee:ff")
        assert result["bridge"] == "virbr0"

    @patch("pxeos.client.libvirt_backend.subprocess.run")
    def test_start_vm(self, mock_run):
        """start_vm calls virsh start."""
        LibvirtBackend().start_vm("test-vm")
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert cmd == ["virsh", "start", "test-vm"]

    @patch("pxeos.client.libvirt_backend.subprocess.run")
    def test_stop_vm(self, mock_run):
        """stop_vm calls virsh destroy."""
        LibvirtBackend().stop_vm("test-vm")
        cmd = mock_run.call_args[0][0]
        assert cmd == ["virsh", "destroy", "test-vm"]

    @patch("pxeos.client.libvirt_backend.subprocess.run")
    def test_delete_vm(self, mock_run):
        """delete_vm calls virsh undefine with --remove-all-storage."""
        LibvirtBackend().delete_vm("test-vm")
        cmd = mock_run.call_args[0][0]
        assert cmd == ["virsh", "undefine", "test-vm", "--remove-all-storage"]

    @patch("pxeos.client.libvirt_backend.subprocess.run")
    def test_get_vm_status(self, mock_run):
        """get_vm_status calls virsh domstate and returns stripped output."""
        mock_run.return_value = MagicMock(
            returncode=0, stdout="running\n"
        )
        status = LibvirtBackend().get_vm_status("test-vm")
        assert status == "running"
        cmd = mock_run.call_args[0][0]
        assert cmd == ["virsh", "domstate", "test-vm"]

    @patch("pxeos.client.libvirt_backend.subprocess.run")
    def test_create_vm_subprocess_error(self, mock_run):
        """create_vm raises CalledProcessError on failure."""
        mock_run.side_effect = subprocess.CalledProcessError(
            1, "virt-install", stderr="error"
        )
        with pytest.raises(subprocess.CalledProcessError):
            LibvirtBackend().create_vm("fail-vm", "aa:bb:cc:dd:ee:ff")


# ---------------------------------------------------------------------------
# BhyveBackend tests
# ---------------------------------------------------------------------------


class TestBhyveBackend:
    """Tests for BhyveBackend (mocked subprocess)."""

    def test_hypervisor_name(self):
        assert BhyveBackend().hypervisor_name == "bhyve"

    @patch("pxeos.client.bhyve_backend.shutil.which", return_value="/usr/sbin/bhyvectl")
    def test_is_available_true(self, mock_which):
        assert BhyveBackend().is_available() is True

    @patch("pxeos.client.bhyve_backend.shutil.which", return_value=None)
    def test_is_available_false(self, mock_which):
        assert BhyveBackend().is_available() is False

    @patch("pxeos.client.bhyve_backend.shutil.which")
    @patch("pxeos.client.bhyve_backend.subprocess.run")
    def test_create_vm_with_vm_bhyve(self, mock_run, mock_which):
        """create_vm uses vm-bhyve when available."""
        def which_side_effect(cmd):
            if cmd == "bhyvectl":
                return "/usr/sbin/bhyvectl"
            if cmd == "vm":
                return "/usr/local/sbin/vm"
            return None
        mock_which.side_effect = which_side_effect
        mock_run.return_value = MagicMock(returncode=0)

        backend = BhyveBackend()
        result = backend.create_vm("test-vm", "aa:bb:cc:dd:ee:ff")
        assert result["name"] == "test-vm"
        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "vm"
        assert cmd[1] == "create"

    @patch("pxeos.client.bhyve_backend.shutil.which")
    @patch("pxeos.client.bhyve_backend.subprocess.run")
    def test_create_vm_raw_bhyve(self, mock_run, mock_which):
        """create_vm falls back to raw bhyve when vm-bhyve not available."""
        def which_side_effect(cmd):
            if cmd == "bhyvectl":
                return "/usr/sbin/bhyvectl"
            return None
        mock_which.side_effect = which_side_effect
        mock_run.return_value = MagicMock(
            returncode=0, stdout="tap0\n"
        )

        backend = BhyveBackend()
        result = backend.create_vm("test-vm", "aa:bb:cc:dd:ee:ff")
        assert result["name"] == "test-vm"
        assert "disk" in result

    @patch("pxeos.client.bhyve_backend.shutil.which")
    @patch("pxeos.client.bhyve_backend.subprocess.run")
    def test_stop_vm_with_vm_bhyve(self, mock_run, mock_which):
        """stop_vm uses 'vm stop' when vm-bhyve available."""
        def which_side_effect(cmd):
            if cmd == "bhyvectl":
                return "/usr/sbin/bhyvectl"
            if cmd == "vm":
                return "/usr/local/sbin/vm"
            return None
        mock_which.side_effect = which_side_effect

        BhyveBackend().stop_vm("test-vm")
        cmd = mock_run.call_args[0][0]
        assert cmd == ["vm", "stop", "test-vm"]

    @patch("pxeos.client.bhyve_backend.shutil.which")
    @patch("pxeos.client.bhyve_backend.subprocess.run")
    def test_stop_vm_raw_bhyve(self, mock_run, mock_which):
        """stop_vm uses bhyvectl --destroy when no vm-bhyve."""
        def which_side_effect(cmd):
            if cmd == "bhyvectl":
                return "/usr/sbin/bhyvectl"
            return None
        mock_which.side_effect = which_side_effect

        BhyveBackend().stop_vm("test-vm")
        cmd = mock_run.call_args[0][0]
        assert cmd == ["bhyvectl", "--destroy", "--vm=test-vm"]

    @patch("pxeos.client.bhyve_backend.shutil.which")
    @patch("pxeos.client.bhyve_backend.subprocess.run")
    def test_get_vm_status_with_vm_bhyve(self, mock_run, mock_which):
        """get_vm_status parses vm list output."""
        def which_side_effect(cmd):
            if cmd == "bhyvectl":
                return "/usr/sbin/bhyvectl"
            if cmd == "vm":
                return "/usr/local/sbin/vm"
            return None
        mock_which.side_effect = which_side_effect
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="test-vm  2  2048M  -  Running\n",
        )

        status = BhyveBackend().get_vm_status("test-vm")
        assert status == "Running"


# ---------------------------------------------------------------------------
# VmmBackend tests
# ---------------------------------------------------------------------------


class TestVmmBackend:
    """Tests for VmmBackend (mocked subprocess for vmctl)."""

    def test_hypervisor_name(self):
        assert VmmBackend().hypervisor_name == "vmm"

    @patch("pxeos.client.vmm_backend.shutil.which", return_value="/usr/sbin/vmctl")
    def test_is_available_true(self, mock_which):
        assert VmmBackend().is_available() is True

    @patch("pxeos.client.vmm_backend.shutil.which", return_value=None)
    def test_is_available_false(self, mock_which):
        assert VmmBackend().is_available() is False

    @patch("pxeos.client.vmm_backend.subprocess.run")
    def test_create_vm(self, mock_run):
        """create_vm calls vmctl create with correct size."""
        mock_run.return_value = MagicMock(returncode=0)
        result = VmmBackend().create_vm(
            "test-vm", "aa:bb:cc:dd:ee:ff", disk_gb=30,
        )
        assert result["name"] == "test-vm"
        assert result["mac"] == "aa:bb:cc:dd:ee:ff"
        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "vmctl"
        assert cmd[1] == "create"
        assert "30G" in cmd

    @patch("pxeos.client.vmm_backend.subprocess.run")
    def test_start_vm(self, mock_run):
        """start_vm calls vmctl start with PXE boot flag."""
        VmmBackend().start_vm("test-vm")
        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "vmctl"
        assert cmd[1] == "start"
        assert "-B" in cmd
        assert "net" in cmd

    @patch("pxeos.client.vmm_backend.subprocess.run")
    def test_stop_vm(self, mock_run):
        """stop_vm calls vmctl stop -f."""
        VmmBackend().stop_vm("test-vm")
        cmd = mock_run.call_args[0][0]
        assert cmd == ["vmctl", "stop", "test-vm", "-f"]

    @patch("pxeos.client.vmm_backend.subprocess.run")
    @patch("os.unlink")
    def test_delete_vm(self, mock_unlink, mock_run):
        """delete_vm stops the VM and removes the disk."""
        VmmBackend().delete_vm("test-vm")
        # Should call vmctl stop first
        stop_cmd = mock_run.call_args_list[0][0][0]
        assert stop_cmd == ["vmctl", "stop", "test-vm", "-f"]
        # Should remove disk
        mock_unlink.assert_called_once_with("/var/vm/test-vm.qcow2")

    @patch("pxeos.client.vmm_backend.subprocess.run")
    def test_get_vm_status_running(self, mock_run):
        """get_vm_status detects running VM from vmctl output."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="   ID   PID VCPUS  MAXMEM  CURMEM     TTY        OWNER NAME\n"
                   "    1  1234     2    2.0G   512M   ttyp0         root test-vm\n",
        )
        status = VmmBackend().get_vm_status("test-vm")
        assert status == "running"

    @patch("pxeos.client.vmm_backend.subprocess.run")
    def test_get_vm_status_stopped(self, mock_run):
        """get_vm_status detects stopped VM from vmctl output."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="   ID   PID VCPUS  MAXMEM  CURMEM     TTY        OWNER NAME\n"
                   "    1     -     2    2.0G       -       -         root test-vm\n",
        )
        status = VmmBackend().get_vm_status("test-vm")
        assert status == "stopped"

    @patch("pxeos.client.vmm_backend.subprocess.run")
    def test_get_vm_status_not_found(self, mock_run):
        """get_vm_status returns 'not found' when VM not in list."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="   ID   PID VCPUS  MAXMEM  CURMEM     TTY        OWNER NAME\n",
        )
        status = VmmBackend().get_vm_status("nonexistent")
        assert status == "not found"


# ---------------------------------------------------------------------------
# HyperVBackend tests
# ---------------------------------------------------------------------------


class TestHyperVBackend:
    """Tests for HyperVBackend (mocked subprocess for PowerShell)."""

    def test_hypervisor_name(self):
        assert HyperVBackend().hypervisor_name == "hyperv"

    @patch("pxeos.client.hyperv_backend.shutil.which", return_value=None)
    def test_is_available_no_powershell(self, mock_which):
        """is_available returns False when no PowerShell found."""
        assert HyperVBackend().is_available() is False

    @patch("pxeos.client.hyperv_backend.subprocess.run")
    @patch("pxeos.client.hyperv_backend.shutil.which", return_value="/usr/bin/pwsh")
    def test_is_available_with_hyperv_module(self, mock_which, mock_run):
        """is_available returns True when Hyper-V module is found."""
        mock_run.return_value = MagicMock(
            returncode=0, stdout="Hyper-V   2.0.0   Hyper-V\n"
        )
        assert HyperVBackend().is_available() is True

    @patch("pxeos.client.hyperv_backend.subprocess.run")
    @patch("pxeos.client.hyperv_backend.shutil.which", return_value="/usr/bin/pwsh")
    def test_is_available_without_hyperv_module(self, mock_which, mock_run):
        """is_available returns False when Hyper-V module not found."""
        mock_run.return_value = MagicMock(
            returncode=0, stdout=""
        )
        assert HyperVBackend().is_available() is False

    @patch("pxeos.client.hyperv_backend.shutil.which", return_value="/usr/bin/pwsh")
    @patch("pxeos.client.hyperv_backend.subprocess.run")
    def test_create_vm(self, mock_run, mock_which):
        """create_vm calls New-VM, Set-VMProcessor, Set-VMNetworkAdapter."""
        mock_run.return_value = MagicMock(returncode=0)
        result = HyperVBackend().create_vm(
            "test-vm", "aa:bb:cc:dd:ee:ff", vcpus=4,
        )
        assert result["name"] == "test-vm"
        assert result["mac"] == "aa:bb:cc:dd:ee:ff"
        # Should have 3 subprocess calls: New-VM, Set-VMProcessor, Set-VMNetworkAdapter
        assert mock_run.call_count == 3

    @patch("pxeos.client.hyperv_backend.shutil.which", return_value="/usr/bin/pwsh")
    @patch("pxeos.client.hyperv_backend.subprocess.run")
    def test_start_vm(self, mock_run, mock_which):
        """start_vm calls Start-VM."""
        HyperVBackend().start_vm("test-vm")
        cmd = mock_run.call_args[0][0]
        # cmd is [ps, "-NoProfile", "-Command", "Start-VM ..."]
        cmd_str = " ".join(cmd)
        assert "Start-VM" in cmd_str

    @patch("pxeos.client.hyperv_backend.shutil.which", return_value="/usr/bin/pwsh")
    @patch("pxeos.client.hyperv_backend.subprocess.run")
    def test_stop_vm(self, mock_run, mock_which):
        """stop_vm calls Stop-VM -Force."""
        HyperVBackend().stop_vm("test-vm")
        cmd_str = " ".join(mock_run.call_args[0][0])
        assert "Stop-VM" in cmd_str
        assert "-Force" in cmd_str

    @patch("pxeos.client.hyperv_backend.shutil.which", return_value="/usr/bin/pwsh")
    @patch("pxeos.client.hyperv_backend.subprocess.run")
    def test_delete_vm(self, mock_run, mock_which):
        """delete_vm calls Stop-VM then Remove-VM."""
        HyperVBackend().delete_vm("test-vm")
        assert mock_run.call_count == 2
        # Second call should be Remove-VM
        remove_cmd = " ".join(mock_run.call_args_list[1][0][0])
        assert "Remove-VM" in remove_cmd

    @patch("pxeos.client.hyperv_backend.shutil.which", return_value="/usr/bin/pwsh")
    @patch("pxeos.client.hyperv_backend.subprocess.run")
    def test_get_vm_status(self, mock_run, mock_which):
        """get_vm_status returns lowercased state from Get-VM."""
        mock_run.return_value = MagicMock(
            returncode=0, stdout="Running\n"
        )
        status = HyperVBackend().get_vm_status("test-vm")
        assert status == "running"


# ---------------------------------------------------------------------------
# _generate_mac tests
# ---------------------------------------------------------------------------


class TestGenerateMac:
    """Tests for the MAC address generation helper."""

    def test_locally_administered_bit(self):
        """Generated MAC starts with 02 (locally administered, unicast)."""
        mac = _generate_mac("any-vm")
        assert mac.startswith("02:")

    def test_deterministic(self):
        """Same name produces the same MAC."""
        assert _generate_mac("test-vm") == _generate_mac("test-vm")

    def test_different_names_different_macs(self):
        """Different names produce different MACs."""
        assert _generate_mac("vm-a") != _generate_mac("vm-b")

    def test_valid_format(self):
        """Generated MAC has 6 colon-separated hex octets."""
        mac = _generate_mac("test-vm")
        octets = mac.split(":")
        assert len(octets) == 6
        for octet in octets:
            assert len(octet) == 2
            int(octet, 16)  # raises ValueError if not hex


# ---------------------------------------------------------------------------
# Workflow tests
# ---------------------------------------------------------------------------


class TestWorkflow:
    """Tests for the provision_vm workflow (mocked HTTP and backend)."""

    def _make_mock_backend(self, name="libvirt"):
        backend = MagicMock(spec=VirtBackend)
        backend.hypervisor_name = name
        backend.create_vm.return_value = {
            "name": "test-vm", "mac": "02:ab:cd:ef:01:23",
        }
        return backend

    @patch("pxeos.client.workflow._poll_provision_status")
    @patch("pxeos.client.workflow._register_host")
    def test_provision_vm_success(self, mock_register, mock_poll):
        """provision_vm calls create, register, start, poll in order."""
        mock_register.return_value = {"status": "ok"}
        mock_poll.return_value = {"state": "complete", "mac": "02:ab:cd:ef:01:23"}

        backend = self._make_mock_backend()
        result = provision_vm(
            server_url="http://pxe.local:8443",
            profile="test-profile",
            backend=backend,
            name="test-vm",
        )

        assert result["status"] == "complete"
        assert result["name"] == "test-vm"
        assert result["hypervisor"] == "libvirt"
        backend.create_vm.assert_called_once()
        backend.start_vm.assert_called_once_with("test-vm")
        mock_register.assert_called_once()
        mock_poll.assert_called_once()

    @patch("pxeos.client.workflow._poll_provision_status")
    @patch("pxeos.client.workflow._register_host")
    def test_provision_vm_create_failure(self, mock_register, mock_poll):
        """provision_vm raises RuntimeError if create_vm fails."""
        backend = self._make_mock_backend()
        backend.create_vm.side_effect = subprocess.CalledProcessError(
            1, "virt-install"
        )

        with pytest.raises(RuntimeError, match="failed to create VM"):
            provision_vm(
                server_url="http://pxe.local:8443",
                profile="test-profile",
                backend=backend,
                name="fail-vm",
            )

    @patch("pxeos.client.workflow._poll_provision_status")
    @patch("pxeos.client.workflow._register_host")
    def test_provision_vm_register_failure(self, mock_register, mock_poll):
        """provision_vm raises RuntimeError if registration fails."""
        mock_register.side_effect = RuntimeError("HTTP 500")
        backend = self._make_mock_backend()

        with pytest.raises(RuntimeError, match="failed to register MAC"):
            provision_vm(
                server_url="http://pxe.local:8443",
                profile="test-profile",
                backend=backend,
                name="test-vm",
            )

    @patch("pxeos.client.workflow._poll_provision_status")
    @patch("pxeos.client.workflow._register_host")
    def test_provision_vm_start_failure(self, mock_register, mock_poll):
        """provision_vm raises RuntimeError if start_vm fails."""
        mock_register.return_value = {"status": "ok"}
        backend = self._make_mock_backend()
        backend.start_vm.side_effect = subprocess.CalledProcessError(
            1, "virsh start"
        )

        with pytest.raises(RuntimeError, match="failed to start VM"):
            provision_vm(
                server_url="http://pxe.local:8443",
                profile="test-profile",
                backend=backend,
                name="test-vm",
            )

    @patch("pxeos.client.workflow._poll_provision_status")
    @patch("pxeos.client.workflow._register_host")
    def test_provision_vm_strips_trailing_slash(self, mock_register, mock_poll):
        """provision_vm strips trailing slashes from server_url."""
        mock_register.return_value = {"status": "ok"}
        mock_poll.return_value = {"state": "complete"}
        backend = self._make_mock_backend()

        provision_vm(
            server_url="http://pxe.local:8443/",
            profile="p",
            backend=backend,
            name="vm",
        )

        # The register call should use the stripped URL
        register_args = mock_register.call_args[0]
        assert register_args[0] == "http://pxe.local:8443"

    @patch("pxeos.client.workflow._poll_provision_status")
    @patch("pxeos.client.workflow._register_host")
    def test_provision_vm_failed_status(self, mock_register, mock_poll):
        """provision_vm returns failed status when provisioning fails."""
        mock_register.return_value = {"status": "ok"}
        mock_poll.return_value = {
            "state": "failed",
            "error_message": "disk full",
        }
        backend = self._make_mock_backend()

        result = provision_vm(
            server_url="http://pxe.local:8443",
            profile="p",
            backend=backend,
            name="vm",
        )
        assert result["status"] == "failed"


# ---------------------------------------------------------------------------
# _register_host tests
# ---------------------------------------------------------------------------


class TestRegisterHost:
    """Tests for the _register_host HTTP helper."""

    @patch("pxeos.client.workflow.urllib.request.urlopen")
    def test_register_success(self, mock_urlopen):
        """_register_host sends correct JSON payload."""
        mock_response = MagicMock()
        mock_response.read.return_value = b'{"status": "created"}'
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_response

        result = _register_host(
            "http://pxe.local:8443",
            "aa:bb:cc:dd:ee:ff",
            "test-profile",
            "fedora",
            "40",
        )
        assert result["status"] == "created"

        # Verify the request
        req = mock_urlopen.call_args[0][0]
        assert req.full_url == "http://pxe.local:8443/api/v1/hosts"
        assert req.method == "POST"
        payload = json.loads(req.data.decode())
        assert payload["profile"] == "test-profile"
        assert payload["mac"] == "aa:bb:cc:dd:ee:ff"

    @patch("pxeos.client.workflow.urllib.request.urlopen")
    def test_register_http_error(self, mock_urlopen):
        """_register_host raises RuntimeError on HTTP error."""
        import io
        import urllib.error
        mock_exc = urllib.error.HTTPError(
            "http://x", 500, "Internal Server Error", {},
            io.BytesIO(b"server error"),
        )
        mock_urlopen.side_effect = mock_exc

        with pytest.raises(RuntimeError, match="HTTP 500"):
            _register_host("http://x", "mac", "p", "f", "v")
        mock_exc.close()


# ---------------------------------------------------------------------------
# _poll_provision_status tests
# ---------------------------------------------------------------------------


class TestPollProvisionStatus:
    """Tests for the _poll_provision_status helper."""

    @patch("pxeos.client.workflow.time.sleep")
    @patch("pxeos.client.workflow.urllib.request.urlopen")
    def test_returns_on_complete(self, mock_urlopen, mock_sleep):
        """Polling returns immediately when state is 'complete'."""
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(
            {"state": "complete", "mac": "aa:bb:cc:dd:ee:ff"}
        ).encode()
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_response

        result = _poll_provision_status(
            "http://pxe.local:8443", "aa:bb:cc:dd:ee:ff", 5.0, 60.0,
        )
        assert result["state"] == "complete"
        mock_sleep.assert_not_called()

    @patch("pxeos.client.workflow.time.sleep")
    @patch("pxeos.client.workflow.urllib.request.urlopen")
    def test_returns_on_failed(self, mock_urlopen, mock_sleep):
        """Polling returns when state is 'failed'."""
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(
            {"state": "failed", "error_message": "timeout"}
        ).encode()
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_response

        result = _poll_provision_status(
            "http://pxe.local:8443", "aa:bb:cc:dd:ee:ff", 5.0, 60.0,
        )
        assert result["state"] == "failed"

    @patch("pxeos.client.workflow.time.monotonic")
    @patch("pxeos.client.workflow.time.sleep")
    @patch("pxeos.client.workflow.urllib.request.urlopen")
    def test_timeout_raises(self, mock_urlopen, mock_sleep, mock_monotonic):
        """Polling raises RuntimeError on timeout."""
        # Simulate time passing beyond deadline
        mock_monotonic.side_effect = [0.0, 100.0]

        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(
            {"state": "installing"}
        ).encode()
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_response

        with pytest.raises(RuntimeError, match="timed out"):
            _poll_provision_status(
                "http://pxe.local:8443", "aa:bb:cc:dd:ee:ff", 5.0, 10.0,
            )


# ---------------------------------------------------------------------------
# CLI virt subcommand tests
# ---------------------------------------------------------------------------


class TestCliVirtSubcommand:
    """Tests for 'pxeos client virt' CLI subcommand."""

    def test_parser_accepts_virt(self):
        """'client virt' is a valid subcommand."""
        from pxeos.cli import _build_parser
        parser = _build_parser()
        args = parser.parse_args([
            "client", "virt",
            "--server", "http://pxe.local:8443",
            "--profile", "test-profile",
        ])
        assert args.client_action == "virt"
        assert args.server == "http://pxe.local:8443"
        assert args.profile == "test-profile"

    def test_parser_accepts_all_options(self):
        """'client virt' accepts all optional arguments."""
        from pxeos.cli import _build_parser
        parser = _build_parser()
        args = parser.parse_args([
            "client", "virt",
            "--server", "http://pxe.local:8443",
            "--profile", "test-profile",
            "--backend", "libvirt",
            "--name", "my-vm",
            "--os", "debian",
            "--version", "12",
            "--memory", "4096",
            "--vcpus", "4",
            "--disk", "40",
            "--bridge", "br0",
        ])
        assert args.backend == "libvirt"
        assert args.name == "my-vm"
        assert args.os_family == "debian"
        assert args.os_version == "12"
        assert args.memory == 4096
        assert args.vcpus == 4
        assert args.disk == 40
        assert args.bridge == "br0"

    def test_parser_defaults(self):
        """'client virt' has sensible defaults."""
        from pxeos.cli import _build_parser
        parser = _build_parser()
        args = parser.parse_args([
            "client", "virt",
            "--server", "http://pxe.local:8443",
            "--profile", "p",
        ])
        assert args.backend is None
        assert args.name is None
        assert args.os_family == "fedora"
        assert args.os_version == "40"
        assert args.memory == 2048
        assert args.vcpus == 2
        assert args.disk == 20
        assert args.bridge is None

    @patch("pxeos.cli._init_stack")
    @patch("pxeos.cli._get_backend_by_name")
    @patch("pxeos.client.workflow.provision_vm")
    def test_virt_with_explicit_backend(self, mock_provision, mock_get_backend, mock_init_stack, capsys):
        """'client virt --backend libvirt' uses the specified backend."""
        from pxeos.cli import main
        from pxeos.config import PxeOSConfig
        from pxeos.matcher import HostMatcher

        config = PxeOSConfig()
        mock_registry = MagicMock()
        mock_registry.available = []
        matcher = HostMatcher([])
        mock_init_stack.return_value = (config, mock_registry, matcher)

        mock_backend = MagicMock()
        mock_backend.is_available.return_value = True
        mock_backend.hypervisor_name = "libvirt"
        mock_get_backend.return_value = mock_backend

        mock_provision.return_value = {
            "name": "test-vm",
            "mac": "02:ab:cd:ef:01:23",
            "hypervisor": "libvirt",
            "status": "complete",
        }

        result = main([
            "client", "virt",
            "--server", "http://pxe.local:8443",
            "--profile", "test-profile",
            "--backend", "libvirt",
            "--name", "test-vm",
        ])

        assert result == 0
        captured = capsys.readouterr()
        assert "test-vm" in captured.out
        assert "complete" in captured.out

    @patch("pxeos.cli._init_stack")
    @patch("pxeos.cli._get_backend_by_name")
    def test_virt_unavailable_backend(self, mock_get_backend, mock_init_stack, capsys):
        """'client virt --backend vmm' returns 1 when backend is unavailable."""
        from pxeos.cli import main
        from pxeos.config import PxeOSConfig
        from pxeos.matcher import HostMatcher

        config = PxeOSConfig()
        mock_registry = MagicMock()
        mock_registry.available = []
        matcher = HostMatcher([])
        mock_init_stack.return_value = (config, mock_registry, matcher)

        mock_backend = MagicMock()
        mock_backend.is_available.return_value = False
        mock_get_backend.return_value = mock_backend

        result = main([
            "client", "virt",
            "--server", "http://pxe.local:8443",
            "--profile", "test-profile",
            "--backend", "vmm",
        ])

        assert result == 1
        captured = capsys.readouterr()
        assert "not available" in captured.err

    @patch("pxeos.cli._init_stack")
    @patch("pxeos.client.base.detect_hypervisor", return_value=None)
    def test_virt_no_hypervisor_detected(self, mock_detect, mock_init_stack, capsys):
        """'client virt' returns 1 when no hypervisor is detected."""
        from pxeos.cli import main
        from pxeos.config import PxeOSConfig
        from pxeos.matcher import HostMatcher

        config = PxeOSConfig()
        mock_registry = MagicMock()
        mock_registry.available = []
        matcher = HostMatcher([])
        mock_init_stack.return_value = (config, mock_registry, matcher)

        result = main([
            "client", "virt",
            "--server", "http://pxe.local:8443",
            "--profile", "test-profile",
        ])

        assert result == 1
        captured = capsys.readouterr()
        assert "no supported hypervisor" in captured.err

    def test_has_virt_in_subcommands(self):
        """The registered subcommands for 'client' include 'virt'."""
        from pxeos.cli import _build_parser
        parser = _build_parser()

        # Navigate to client subparser
        for action in parser._subparsers._actions:
            if hasattr(action, "_parser_class"):
                client_parser = action.choices.get("client")
                if client_parser:
                    for sub_action in client_parser._subparsers._actions:
                        if hasattr(sub_action, "_parser_class"):
                            assert "virt" in sub_action.choices
                            return
        pytest.fail("Could not find 'virt' in client subcommands")


# ---------------------------------------------------------------------------
# _get_backend_by_name tests
# ---------------------------------------------------------------------------


class TestGetBackendByName:
    """Tests for the _get_backend_by_name helper."""

    def test_libvirt(self):
        from pxeos.cli import _get_backend_by_name
        backend = _get_backend_by_name("libvirt")
        assert isinstance(backend, LibvirtBackend)

    def test_bhyve(self):
        from pxeos.cli import _get_backend_by_name
        backend = _get_backend_by_name("bhyve")
        assert isinstance(backend, BhyveBackend)

    def test_vmm(self):
        from pxeos.cli import _get_backend_by_name
        backend = _get_backend_by_name("vmm")
        assert isinstance(backend, VmmBackend)

    def test_hyperv(self):
        from pxeos.cli import _get_backend_by_name
        backend = _get_backend_by_name("hyperv")
        assert isinstance(backend, HyperVBackend)

    def test_unknown(self):
        from pxeos.cli import _get_backend_by_name
        assert _get_backend_by_name("xen") is None


# ---------------------------------------------------------------------------
# __init__ imports test
# ---------------------------------------------------------------------------


class TestClientInit:
    """Tests for pxeos.client package imports."""

    def test_imports_virt_backend(self):
        from pxeos.client import VirtBackend
        assert VirtBackend is not None

    def test_imports_detect_hypervisor(self):
        from pxeos.client import detect_hypervisor
        assert callable(detect_hypervisor)
