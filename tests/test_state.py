"""Tests for provisioning state tracking and callbacks."""

from __future__ import annotations

import time
from unittest.mock import MagicMock, call

import pytest

from pxeos.state import ProvisionRecord, ProvisionState, ProvisionTracker


# ---- ProvisionState enum ----


class TestProvisionStateEnum:

    def test_registered_value(self):
        assert ProvisionState.REGISTERED.value == "registered"

    def test_booting_value(self):
        assert ProvisionState.BOOTING.value == "booting"

    def test_installing_value(self):
        assert ProvisionState.INSTALLING.value == "installing"

    def test_post_install_value(self):
        assert ProvisionState.POST_INSTALL.value == "post_install"

    def test_complete_value(self):
        assert ProvisionState.COMPLETE.value == "complete"

    def test_failed_value(self):
        assert ProvisionState.FAILED.value == "failed"

    def test_all_states_count(self):
        assert len(ProvisionState) == 6


# ---- ProvisionRecord ----


class TestProvisionRecord:

    def test_default_state_is_registered(self):
        record = ProvisionRecord(
            mac="aa:bb:cc:dd:ee:ff",
            profile="fedora-server",
            os_family="fedora",
            os_version="41",
        )
        assert record.state == ProvisionState.REGISTERED

    def test_default_timestamps_are_none(self):
        record = ProvisionRecord(
            mac="aa:bb:cc:dd:ee:ff",
            profile="fedora-server",
            os_family="fedora",
            os_version="41",
        )
        assert record.started_at is None
        assert record.updated_at is None
        assert record.completed_at is None

    def test_default_error_message_is_none(self):
        record = ProvisionRecord(
            mac="aa:bb:cc:dd:ee:ff",
            profile="fedora-server",
            os_family="fedora",
            os_version="41",
        )
        assert record.error_message is None

    def test_default_history_is_empty(self):
        record = ProvisionRecord(
            mac="aa:bb:cc:dd:ee:ff",
            profile="fedora-server",
            os_family="fedora",
            os_version="41",
        )
        assert record.history == []

    def test_netboot_enabled_defaults_true(self):
        record = ProvisionRecord(
            mac="aa:bb:cc:dd:ee:ff",
            profile="fedora-server",
            os_family="fedora",
            os_version="41",
        )
        assert record.netboot_enabled is True

    def test_netboot_enabled_can_be_set_false(self):
        record = ProvisionRecord(
            mac="aa:bb:cc:dd:ee:ff",
            profile="fedora-server",
            os_family="fedora",
            os_version="41",
            netboot_enabled=False,
        )
        assert record.netboot_enabled is False

    def test_to_dict_returns_all_fields(self):
        now = time.time()
        record = ProvisionRecord(
            mac="aa:bb:cc:dd:ee:ff",
            profile="fedora-server",
            os_family="fedora",
            os_version="41",
            state=ProvisionState.BOOTING,
            started_at=now,
            updated_at=now,
            history=[(ProvisionState.REGISTERED, now)],
        )
        d = record.to_dict()
        assert d["mac"] == "aa:bb:cc:dd:ee:ff"
        assert d["profile"] == "fedora-server"
        assert d["os_family"] == "fedora"
        assert d["os_version"] == "41"
        assert d["state"] == "booting"
        assert d["started_at"] == now
        assert d["updated_at"] == now
        assert d["completed_at"] is None
        assert d["error_message"] is None
        assert d["netboot_enabled"] is True
        assert len(d["history"]) == 1
        assert d["history"][0]["state"] == "registered"
        assert d["history"][0]["timestamp"] == now

    def test_to_dict_serializes_error_message(self):
        record = ProvisionRecord(
            mac="aa:bb:cc:dd:ee:ff",
            profile="fedora-server",
            os_family="fedora",
            os_version="41",
            error_message="disk not found",
        )
        d = record.to_dict()
        assert d["error_message"] == "disk not found"

    def test_history_entries_are_independent(self):
        """Ensure each ProvisionRecord gets its own history list."""
        r1 = ProvisionRecord(
            mac="aa:bb:cc:dd:ee:01",
            profile="p1",
            os_family="fedora",
            os_version="41",
        )
        r2 = ProvisionRecord(
            mac="aa:bb:cc:dd:ee:02",
            profile="p2",
            os_family="fedora",
            os_version="41",
        )
        r1.history.append((ProvisionState.BOOTING, time.time()))
        assert len(r2.history) == 0


# ---- ProvisionTracker: register ----


class TestTrackerRegister:

    def test_register_returns_record(self):
        tracker = ProvisionTracker()
        record = tracker.register(
            "aa:bb:cc:dd:ee:ff", "fedora-server", "fedora", "41"
        )
        assert isinstance(record, ProvisionRecord)
        assert record.mac == "aa:bb:cc:dd:ee:ff"
        assert record.profile == "fedora-server"
        assert record.os_family == "fedora"
        assert record.os_version == "41"

    def test_register_sets_started_at(self):
        tracker = ProvisionTracker()
        before = time.time()
        record = tracker.register(
            "aa:bb:cc:dd:ee:ff", "fedora-server", "fedora", "41"
        )
        after = time.time()
        assert before <= record.started_at <= after

    def test_register_sets_updated_at(self):
        tracker = ProvisionTracker()
        before = time.time()
        record = tracker.register(
            "aa:bb:cc:dd:ee:ff", "fedora-server", "fedora", "41"
        )
        after = time.time()
        assert before <= record.updated_at <= after

    def test_register_initializes_history(self):
        tracker = ProvisionTracker()
        record = tracker.register(
            "aa:bb:cc:dd:ee:ff", "fedora-server", "fedora", "41"
        )
        assert len(record.history) == 1
        assert record.history[0][0] == ProvisionState.REGISTERED

    def test_register_state_is_registered(self):
        tracker = ProvisionTracker()
        record = tracker.register(
            "aa:bb:cc:dd:ee:ff", "fedora-server", "fedora", "41"
        )
        assert record.state == ProvisionState.REGISTERED


# ---- ProvisionTracker: transition ----


class TestTrackerTransition:

    def test_transition_updates_state(self):
        tracker = ProvisionTracker()
        tracker.register(
            "aa:bb:cc:dd:ee:ff", "fedora-server", "fedora", "41"
        )
        record = tracker.transition(
            "aa:bb:cc:dd:ee:ff", ProvisionState.BOOTING
        )
        assert record.state == ProvisionState.BOOTING

    def test_transition_updates_updated_at(self):
        tracker = ProvisionTracker()
        tracker.register(
            "aa:bb:cc:dd:ee:ff", "fedora-server", "fedora", "41"
        )
        before = time.time()
        record = tracker.transition(
            "aa:bb:cc:dd:ee:ff", ProvisionState.BOOTING
        )
        after = time.time()
        assert before <= record.updated_at <= after

    def test_transition_appends_to_history(self):
        tracker = ProvisionTracker()
        tracker.register(
            "aa:bb:cc:dd:ee:ff", "fedora-server", "fedora", "41"
        )
        tracker.transition(
            "aa:bb:cc:dd:ee:ff", ProvisionState.BOOTING
        )
        record = tracker.get("aa:bb:cc:dd:ee:ff")
        assert len(record.history) == 2
        assert record.history[0][0] == ProvisionState.REGISTERED
        assert record.history[1][0] == ProvisionState.BOOTING

    def test_transition_complete_sets_completed_at(self):
        tracker = ProvisionTracker()
        tracker.register(
            "aa:bb:cc:dd:ee:ff", "fedora-server", "fedora", "41"
        )
        before = time.time()
        record = tracker.transition(
            "aa:bb:cc:dd:ee:ff", ProvisionState.COMPLETE
        )
        after = time.time()
        assert record.completed_at is not None
        assert before <= record.completed_at <= after

    def test_transition_non_complete_does_not_set_completed_at(self):
        tracker = ProvisionTracker()
        tracker.register(
            "aa:bb:cc:dd:ee:ff", "fedora-server", "fedora", "41"
        )
        record = tracker.transition(
            "aa:bb:cc:dd:ee:ff", ProvisionState.BOOTING
        )
        assert record.completed_at is None

    def test_transition_failed_sets_error_message(self):
        tracker = ProvisionTracker()
        tracker.register(
            "aa:bb:cc:dd:ee:ff", "fedora-server", "fedora", "41"
        )
        record = tracker.transition(
            "aa:bb:cc:dd:ee:ff",
            ProvisionState.FAILED,
            error_message="disk failure",
        )
        assert record.error_message == "disk failure"

    def test_transition_without_error_preserves_none(self):
        tracker = ProvisionTracker()
        tracker.register(
            "aa:bb:cc:dd:ee:ff", "fedora-server", "fedora", "41"
        )
        record = tracker.transition(
            "aa:bb:cc:dd:ee:ff", ProvisionState.INSTALLING
        )
        assert record.error_message is None

    def test_transition_unknown_mac_raises_valueerror(self):
        tracker = ProvisionTracker()
        with pytest.raises(
            ValueError, match="No provisioning record"
        ):
            tracker.transition(
                "ff:ff:ff:ff:ff:ff", ProvisionState.BOOTING
            )

    def test_multiple_transitions_build_full_history(self):
        tracker = ProvisionTracker()
        tracker.register(
            "aa:bb:cc:dd:ee:ff", "fedora-server", "fedora", "41"
        )
        tracker.transition(
            "aa:bb:cc:dd:ee:ff", ProvisionState.BOOTING
        )
        tracker.transition(
            "aa:bb:cc:dd:ee:ff", ProvisionState.INSTALLING
        )
        tracker.transition(
            "aa:bb:cc:dd:ee:ff", ProvisionState.POST_INSTALL
        )
        tracker.transition(
            "aa:bb:cc:dd:ee:ff", ProvisionState.COMPLETE
        )
        record = tracker.get("aa:bb:cc:dd:ee:ff")
        states = [s for s, _ in record.history]
        assert states == [
            ProvisionState.REGISTERED,
            ProvisionState.BOOTING,
            ProvisionState.INSTALLING,
            ProvisionState.POST_INSTALL,
            ProvisionState.COMPLETE,
        ]


# ---- ProvisionTracker: get ----


class TestTrackerGet:

    def test_get_returns_registered_record(self):
        tracker = ProvisionTracker()
        tracker.register(
            "aa:bb:cc:dd:ee:ff", "fedora-server", "fedora", "41"
        )
        record = tracker.get("aa:bb:cc:dd:ee:ff")
        assert record is not None
        assert record.mac == "aa:bb:cc:dd:ee:ff"

    def test_get_returns_none_for_unknown(self):
        tracker = ProvisionTracker()
        assert tracker.get("ff:ff:ff:ff:ff:ff") is None

    def test_get_is_case_insensitive(self):
        tracker = ProvisionTracker()
        tracker.register(
            "AA:BB:CC:DD:EE:FF", "fedora-server", "fedora", "41"
        )
        record = tracker.get("aa:bb:cc:dd:ee:ff")
        assert record is not None

    def test_register_is_case_insensitive(self):
        tracker = ProvisionTracker()
        tracker.register(
            "aa:bb:cc:dd:ee:ff", "fedora-server", "fedora", "41"
        )
        record = tracker.get("AA:BB:CC:DD:EE:FF")
        assert record is not None

    def test_transition_is_case_insensitive(self):
        tracker = ProvisionTracker()
        tracker.register(
            "AA:BB:CC:DD:EE:FF", "fedora-server", "fedora", "41"
        )
        record = tracker.transition(
            "aa:bb:cc:dd:ee:ff", ProvisionState.BOOTING
        )
        assert record.state == ProvisionState.BOOTING


# ---- ProvisionTracker: list_all ----


class TestTrackerListAll:

    def test_list_all_empty(self):
        tracker = ProvisionTracker()
        assert tracker.list_all() == []

    def test_list_all_returns_all_records(self):
        tracker = ProvisionTracker()
        tracker.register(
            "aa:bb:cc:dd:ee:01", "p1", "fedora", "41"
        )
        tracker.register(
            "aa:bb:cc:dd:ee:02", "p2", "ubuntu", "24.04"
        )
        records = tracker.list_all()
        assert len(records) == 2
        macs = {r.mac for r in records}
        assert "aa:bb:cc:dd:ee:01" in macs
        assert "aa:bb:cc:dd:ee:02" in macs


# ---- ProvisionTracker: callbacks ----


class TestTrackerCallbacks:

    def test_callback_fires_on_register(self):
        tracker = ProvisionTracker()
        cb = MagicMock()
        tracker.on_state_change(ProvisionState.REGISTERED, cb)
        record = tracker.register(
            "aa:bb:cc:dd:ee:ff", "fedora-server", "fedora", "41"
        )
        cb.assert_called_once_with(record)

    def test_callback_fires_on_transition(self):
        tracker = ProvisionTracker()
        cb = MagicMock()
        tracker.on_state_change(ProvisionState.BOOTING, cb)
        tracker.register(
            "aa:bb:cc:dd:ee:ff", "fedora-server", "fedora", "41"
        )
        tracker.transition(
            "aa:bb:cc:dd:ee:ff", ProvisionState.BOOTING
        )
        cb.assert_called_once()

    def test_callback_not_fired_for_different_state(self):
        tracker = ProvisionTracker()
        cb = MagicMock()
        tracker.on_state_change(ProvisionState.COMPLETE, cb)
        tracker.register(
            "aa:bb:cc:dd:ee:ff", "fedora-server", "fedora", "41"
        )
        tracker.transition(
            "aa:bb:cc:dd:ee:ff", ProvisionState.BOOTING
        )
        cb.assert_not_called()

    def test_multiple_callbacks_for_same_state(self):
        tracker = ProvisionTracker()
        cb1 = MagicMock()
        cb2 = MagicMock()
        tracker.on_state_change(ProvisionState.COMPLETE, cb1)
        tracker.on_state_change(ProvisionState.COMPLETE, cb2)
        tracker.register(
            "aa:bb:cc:dd:ee:ff", "fedora-server", "fedora", "41"
        )
        tracker.transition(
            "aa:bb:cc:dd:ee:ff", ProvisionState.COMPLETE
        )
        cb1.assert_called_once()
        cb2.assert_called_once()

    def test_callback_receives_correct_record(self):
        tracker = ProvisionTracker()
        received = []
        tracker.on_state_change(
            ProvisionState.FAILED,
            lambda r: received.append(r),
        )
        tracker.register(
            "aa:bb:cc:dd:ee:ff", "fedora-server", "fedora", "41"
        )
        tracker.transition(
            "aa:bb:cc:dd:ee:ff",
            ProvisionState.FAILED,
            error_message="timeout",
        )
        assert len(received) == 1
        assert received[0].mac == "aa:bb:cc:dd:ee:ff"
        assert received[0].error_message == "timeout"
        assert received[0].state == ProvisionState.FAILED

    def test_callbacks_for_different_states(self):
        tracker = ProvisionTracker()
        boot_cb = MagicMock()
        install_cb = MagicMock()
        tracker.on_state_change(ProvisionState.BOOTING, boot_cb)
        tracker.on_state_change(
            ProvisionState.INSTALLING, install_cb
        )
        tracker.register(
            "aa:bb:cc:dd:ee:ff", "fedora-server", "fedora", "41"
        )
        tracker.transition(
            "aa:bb:cc:dd:ee:ff", ProvisionState.BOOTING
        )
        assert boot_cb.call_count == 1
        assert install_cb.call_count == 0
        tracker.transition(
            "aa:bb:cc:dd:ee:ff", ProvisionState.INSTALLING
        )
        assert boot_cb.call_count == 1
        assert install_cb.call_count == 1


# ---- ProvisionTracker: overwrite on re-register ----


class TestTrackerOverwrite:

    def test_register_overwrites_existing(self):
        tracker = ProvisionTracker()
        tracker.register(
            "aa:bb:cc:dd:ee:ff", "p1", "fedora", "41"
        )
        tracker.transition(
            "aa:bb:cc:dd:ee:ff", ProvisionState.BOOTING
        )
        # re-register same MAC
        record = tracker.register(
            "aa:bb:cc:dd:ee:ff", "p2", "ubuntu", "24.04"
        )
        assert record.profile == "p2"
        assert record.os_family == "ubuntu"
        assert record.state == ProvisionState.REGISTERED
        assert len(record.history) == 1
