"""Tests for the database abstraction layer (pxeos.db)."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest

from pxeos.db import (
    JSONBackend,
    MemoryBackend,
    SQLiteBackend,
    StorageBackend,
    _dict_to_record,
    _record_to_dict,
    migrate_json_to_sqlite,
)
from pxeos.state import ProvisionRecord, ProvisionState, ProvisionTracker


# ---- Helpers ----


def _make_record(
    mac: str = "aa:bb:cc:dd:ee:ff",
    profile: str = "fedora-server",
    os_family: str = "fedora",
    os_version: str = "41",
    state: ProvisionState = ProvisionState.REGISTERED,
) -> ProvisionRecord:
    now = time.time()
    return ProvisionRecord(
        mac=mac,
        profile=profile,
        os_family=os_family,
        os_version=os_version,
        state=state,
        started_at=now,
        updated_at=now,
        history=[(state, now)],
    )


# ---- Serialisation round-trip ----


class TestSerialisation:

    def test_record_to_dict_and_back(self):
        original = _make_record()
        d = _record_to_dict(original)
        restored = _dict_to_record(d)
        assert restored.mac == original.mac
        assert restored.profile == original.profile
        assert restored.state == original.state
        assert restored.started_at == original.started_at
        assert restored.netboot_enabled == original.netboot_enabled
        assert len(restored.history) == len(original.history)

    def test_round_trip_with_error_message(self):
        rec = _make_record(state=ProvisionState.FAILED)
        rec.error_message = "disk not found"
        d = _record_to_dict(rec)
        restored = _dict_to_record(d)
        assert restored.error_message == "disk not found"

    def test_round_trip_preserves_netboot_false(self):
        rec = _make_record()
        rec.netboot_enabled = False
        d = _record_to_dict(rec)
        restored = _dict_to_record(d)
        assert restored.netboot_enabled is False

    def test_round_trip_preserves_history(self):
        rec = _make_record()
        now = time.time()
        rec.history.append((ProvisionState.BOOTING, now))
        d = _record_to_dict(rec)
        restored = _dict_to_record(d)
        assert len(restored.history) == 2
        assert restored.history[1][0] == ProvisionState.BOOTING

    def test_dict_to_record_defaults_netboot_true(self):
        d = {
            "mac": "aa:bb:cc:dd:ee:ff",
            "profile": "p",
            "os_family": "fedora",
            "os_version": "41",
            "state": "registered",
        }
        rec = _dict_to_record(d)
        assert rec.netboot_enabled is True


# ---- StorageBackend contract tests ----
# Run the same battery for each concrete backend.


class _BackendContractTests:
    """Mixin: the concrete test class must set self.backend."""

    backend: StorageBackend

    def test_save_and_get(self):
        rec = _make_record()
        self.backend.save(rec)
        got = self.backend.get("aa:bb:cc:dd:ee:ff")
        assert got is not None
        assert got.mac == rec.mac
        assert got.profile == rec.profile

    def test_get_unknown_returns_none(self):
        assert self.backend.get("ff:ff:ff:ff:ff:ff") is None

    def test_get_is_case_insensitive(self):
        rec = _make_record(mac="AA:BB:CC:DD:EE:FF")
        self.backend.save(rec)
        got = self.backend.get("aa:bb:cc:dd:ee:ff")
        assert got is not None

    def test_list_all_empty(self):
        assert self.backend.list_all() == []

    def test_list_all_returns_saved_records(self):
        self.backend.save(_make_record(mac="aa:bb:cc:dd:ee:01"))
        self.backend.save(_make_record(mac="aa:bb:cc:dd:ee:02"))
        records = self.backend.list_all()
        assert len(records) == 2

    def test_save_overwrites_existing(self):
        self.backend.save(
            _make_record(mac="aa:bb:cc:dd:ee:ff", profile="p1")
        )
        self.backend.save(
            _make_record(mac="aa:bb:cc:dd:ee:ff", profile="p2")
        )
        got = self.backend.get("aa:bb:cc:dd:ee:ff")
        assert got is not None
        assert got.profile == "p2"
        assert len(self.backend.list_all()) == 1

    def test_delete_existing(self):
        self.backend.save(_make_record())
        assert self.backend.delete("aa:bb:cc:dd:ee:ff") is True
        assert self.backend.get("aa:bb:cc:dd:ee:ff") is None

    def test_delete_nonexistent(self):
        assert self.backend.delete("ff:ff:ff:ff:ff:ff") is False

    def test_clear_removes_all(self):
        self.backend.save(_make_record(mac="aa:bb:cc:dd:ee:01"))
        self.backend.save(_make_record(mac="aa:bb:cc:dd:ee:02"))
        self.backend.clear()
        assert self.backend.list_all() == []

    def test_save_preserves_state(self):
        rec = _make_record(state=ProvisionState.INSTALLING)
        self.backend.save(rec)
        got = self.backend.get(rec.mac)
        assert got is not None
        assert got.state == ProvisionState.INSTALLING

    def test_save_preserves_error_message(self):
        rec = _make_record(state=ProvisionState.FAILED)
        rec.error_message = "timeout"
        self.backend.save(rec)
        got = self.backend.get(rec.mac)
        assert got is not None
        assert got.error_message == "timeout"

    def test_save_preserves_completed_at(self):
        rec = _make_record(state=ProvisionState.COMPLETE)
        rec.completed_at = time.time()
        self.backend.save(rec)
        got = self.backend.get(rec.mac)
        assert got is not None
        assert got.completed_at == rec.completed_at

    def test_save_preserves_netboot_enabled(self):
        rec = _make_record()
        rec.netboot_enabled = False
        self.backend.save(rec)
        got = self.backend.get(rec.mac)
        assert got is not None
        assert got.netboot_enabled is False

    def test_save_preserves_history(self):
        rec = _make_record()
        now = time.time()
        rec.history.append((ProvisionState.BOOTING, now))
        rec.history.append((ProvisionState.INSTALLING, now + 1))
        self.backend.save(rec)
        got = self.backend.get(rec.mac)
        assert got is not None
        assert len(got.history) == 3
        assert got.history[1][0] == ProvisionState.BOOTING
        assert got.history[2][0] == ProvisionState.INSTALLING


# ---- Concrete backend tests ----


class TestMemoryBackend(_BackendContractTests):

    @pytest.fixture(autouse=True)
    def _setup(self):
        self.backend = MemoryBackend()

    def test_close_is_noop(self):
        self.backend.close()  # should not raise


class TestSQLiteBackend(_BackendContractTests):

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path):
        self.backend = SQLiteBackend(tmp_path / "test.db")
        yield
        self.backend.close()

    def test_persists_across_instances(self, tmp_path):
        db_path = tmp_path / "persist.db"
        b1 = SQLiteBackend(db_path)
        b1.save(_make_record(mac="aa:bb:cc:dd:ee:ff"))
        b1.close()

        b2 = SQLiteBackend(db_path)
        got = b2.get("aa:bb:cc:dd:ee:ff")
        assert got is not None
        assert got.mac == "aa:bb:cc:dd:ee:ff"
        b2.close()

    def test_query_by_state(self, tmp_path):
        db_path = tmp_path / "query.db"
        b = SQLiteBackend(db_path)
        b.save(_make_record(mac="aa:bb:cc:dd:ee:01",
                            state=ProvisionState.BOOTING))
        b.save(_make_record(mac="aa:bb:cc:dd:ee:02",
                            state=ProvisionState.COMPLETE))
        b.save(_make_record(mac="aa:bb:cc:dd:ee:03",
                            state=ProvisionState.BOOTING))
        booting = b.query_by_state(ProvisionState.BOOTING)
        assert len(booting) == 2
        complete = b.query_by_state(ProvisionState.COMPLETE)
        assert len(complete) == 1
        b.close()

    def test_concurrent_writes(self, tmp_path):
        """10+ simultaneous provisions must not corrupt the database."""
        db_path = tmp_path / "concurrent.db"
        b = SQLiteBackend(db_path)
        errors: list = []

        def _writer(i: int) -> None:
            try:
                mac = f"aa:bb:cc:dd:{i:02x}:00"
                rec = _make_record(mac=mac, profile=f"p{i}")
                b.save(rec)
                # Transition through states
                rec.state = ProvisionState.BOOTING
                rec.updated_at = time.time()
                rec.history.append(
                    (ProvisionState.BOOTING, rec.updated_at)
                )
                b.save(rec)
                rec.state = ProvisionState.COMPLETE
                rec.updated_at = time.time()
                rec.completed_at = rec.updated_at
                rec.history.append(
                    (ProvisionState.COMPLETE, rec.updated_at)
                )
                b.save(rec)
            except Exception as exc:
                errors.append(exc)

        threads = [
            threading.Thread(target=_writer, args=(i,))
            for i in range(20)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == [], f"Concurrent write errors: {errors}"
        records = b.list_all()
        assert len(records) == 20
        for rec in records:
            assert rec.state == ProvisionState.COMPLETE
        b.close()


class TestJSONBackend(_BackendContractTests):

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path):
        self.backend = JSONBackend(tmp_path / "state.json")
        yield

    def test_persists_to_file(self, tmp_path):
        json_path = tmp_path / "persist.json"
        b1 = JSONBackend(json_path)
        b1.save(_make_record(mac="aa:bb:cc:dd:ee:ff"))

        b2 = JSONBackend(json_path)
        got = b2.get("aa:bb:cc:dd:ee:ff")
        assert got is not None

    def test_handles_missing_file(self, tmp_path):
        b = JSONBackend(tmp_path / "nonexistent.json")
        assert b.list_all() == []
        assert b.get("aa:bb:cc:dd:ee:ff") is None

    def test_handles_corrupt_file(self, tmp_path):
        json_path = tmp_path / "corrupt.json"
        json_path.write_text("not valid json{{{")
        b = JSONBackend(json_path)
        assert b.list_all() == []

    def test_close_is_noop(self, tmp_path):
        b = JSONBackend(tmp_path / "noop.json")
        b.close()  # should not raise


# ---- Migration tests ----


class TestMigration:

    def test_migrate_dict_format(self, tmp_path):
        state = {
            "aa:bb:cc:dd:ee:ff": {
                "mac": "aa:bb:cc:dd:ee:ff",
                "profile": "fedora-server",
                "os_family": "fedora",
                "os_version": "41",
                "state": "registered",
                "started_at": 1000.0,
                "updated_at": 1000.0,
                "history": [
                    {"state": "registered", "timestamp": 1000.0}
                ],
            }
        }
        json_path = tmp_path / "state.json"
        json_path.write_text(json.dumps(state))
        db_path = tmp_path / "state.db"

        count = migrate_json_to_sqlite(json_path, db_path)
        assert count == 1

        b = SQLiteBackend(db_path)
        rec = b.get("aa:bb:cc:dd:ee:ff")
        assert rec is not None
        assert rec.profile == "fedora-server"
        assert rec.state == ProvisionState.REGISTERED
        b.close()

    def test_migrate_list_format(self, tmp_path):
        state = [
            {
                "mac": "aa:bb:cc:dd:ee:01",
                "profile": "p1",
                "os_family": "fedora",
                "os_version": "41",
                "state": "booting",
                "history": [],
            },
            {
                "mac": "aa:bb:cc:dd:ee:02",
                "profile": "p2",
                "os_family": "ubuntu",
                "os_version": "24.04",
                "state": "complete",
                "history": [],
            },
        ]
        json_path = tmp_path / "state.json"
        json_path.write_text(json.dumps(state))
        db_path = tmp_path / "state.db"

        count = migrate_json_to_sqlite(json_path, db_path)
        assert count == 2

    def test_migrate_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            migrate_json_to_sqlite(
                tmp_path / "missing.json",
                tmp_path / "state.db",
            )

    def test_migrate_empty_file(self, tmp_path):
        json_path = tmp_path / "empty.json"
        json_path.write_text("{}")
        db_path = tmp_path / "state.db"
        count = migrate_json_to_sqlite(json_path, db_path)
        assert count == 0

    def test_migrate_skips_malformed_records(self, tmp_path):
        state = {
            "good": {
                "mac": "aa:bb:cc:dd:ee:ff",
                "profile": "p1",
                "os_family": "fedora",
                "os_version": "41",
                "state": "registered",
                "history": [],
            },
            "bad": {
                "not_a_real_field": "whoops",
            },
        }
        json_path = tmp_path / "state.json"
        json_path.write_text(json.dumps(state))
        db_path = tmp_path / "state.db"
        count = migrate_json_to_sqlite(json_path, db_path)
        assert count == 1


# ---- ProvisionTracker with backend ----


class TestTrackerWithSQLiteBackend:

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path):
        self.db_path = tmp_path / "tracker.db"
        self.backend = SQLiteBackend(self.db_path)
        self.tracker = ProvisionTracker(backend=self.backend)
        yield
        self.backend.close()

    def test_register_persists(self):
        self.tracker.register(
            "aa:bb:cc:dd:ee:ff", "fedora-server", "fedora", "41"
        )
        # Check directly via backend
        rec = self.backend.get("aa:bb:cc:dd:ee:ff")
        assert rec is not None
        assert rec.state == ProvisionState.REGISTERED

    def test_transition_persists(self):
        self.tracker.register(
            "aa:bb:cc:dd:ee:ff", "fedora-server", "fedora", "41"
        )
        self.tracker.transition(
            "aa:bb:cc:dd:ee:ff", ProvisionState.BOOTING
        )
        rec = self.backend.get("aa:bb:cc:dd:ee:ff")
        assert rec is not None
        assert rec.state == ProvisionState.BOOTING

    def test_disable_netboot_persists(self):
        self.tracker.register(
            "aa:bb:cc:dd:ee:ff", "fedora-server", "fedora", "41"
        )
        self.tracker.disable_netboot("aa:bb:cc:dd:ee:ff")
        rec = self.backend.get("aa:bb:cc:dd:ee:ff")
        assert rec is not None
        assert rec.netboot_enabled is False

    def test_enable_netboot_persists(self):
        self.tracker.register(
            "aa:bb:cc:dd:ee:ff", "fedora-server", "fedora", "41"
        )
        self.tracker.disable_netboot("aa:bb:cc:dd:ee:ff")
        self.tracker.enable_netboot("aa:bb:cc:dd:ee:ff")
        rec = self.backend.get("aa:bb:cc:dd:ee:ff")
        assert rec is not None
        assert rec.netboot_enabled is True

    def test_clear_empties_backend(self):
        self.tracker.register(
            "aa:bb:cc:dd:ee:ff", "fedora-server", "fedora", "41"
        )
        self.tracker.clear()
        assert self.backend.list_all() == []

    def test_preloads_from_backend(self):
        """A new tracker should load existing records from the backend."""
        self.tracker.register(
            "aa:bb:cc:dd:ee:ff", "fedora-server", "fedora", "41"
        )
        # Create a fresh tracker with the same backend
        tracker2 = ProvisionTracker(backend=self.backend)
        rec = tracker2.get("aa:bb:cc:dd:ee:ff")
        assert rec is not None
        assert rec.profile == "fedora-server"

    def test_callbacks_still_work_with_backend(self):
        from unittest.mock import MagicMock

        cb = MagicMock()
        self.tracker.on_state_change(ProvisionState.BOOTING, cb)
        self.tracker.register(
            "aa:bb:cc:dd:ee:ff", "fedora-server", "fedora", "41"
        )
        self.tracker.transition(
            "aa:bb:cc:dd:ee:ff", ProvisionState.BOOTING
        )
        cb.assert_called_once()

    def test_survives_restart(self):
        """Records survive backend close + reopen."""
        self.tracker.register(
            "aa:bb:cc:dd:ee:ff", "fedora-server", "fedora", "41"
        )
        self.tracker.transition(
            "aa:bb:cc:dd:ee:ff", ProvisionState.COMPLETE
        )
        self.backend.close()

        # Reopen
        backend2 = SQLiteBackend(self.db_path)
        tracker2 = ProvisionTracker(backend=backend2)
        rec = tracker2.get("aa:bb:cc:dd:ee:ff")
        assert rec is not None
        assert rec.state == ProvisionState.COMPLETE
        assert len(rec.history) == 2
        backend2.close()


class TestTrackerWithJSONBackend:

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path):
        self.json_path = tmp_path / "state.json"
        self.backend = JSONBackend(self.json_path)
        self.tracker = ProvisionTracker(backend=self.backend)

    def test_register_writes_json(self):
        self.tracker.register(
            "aa:bb:cc:dd:ee:ff", "p1", "fedora", "41"
        )
        assert self.json_path.exists()
        data = json.loads(self.json_path.read_text())
        assert "aa:bb:cc:dd:ee:ff" in data

    def test_transition_updates_json(self):
        self.tracker.register(
            "aa:bb:cc:dd:ee:ff", "p1", "fedora", "41"
        )
        self.tracker.transition(
            "aa:bb:cc:dd:ee:ff", ProvisionState.INSTALLING
        )
        data = json.loads(self.json_path.read_text())
        assert data["aa:bb:cc:dd:ee:ff"]["state"] == "installing"


class TestTrackerWithoutBackend:
    """Verify that the tracker still works without a backend (original behaviour)."""

    def test_register_and_get(self):
        tracker = ProvisionTracker()
        rec = tracker.register(
            "aa:bb:cc:dd:ee:ff", "p1", "fedora", "41"
        )
        assert tracker.get("aa:bb:cc:dd:ee:ff") is rec

    def test_transition(self):
        tracker = ProvisionTracker()
        tracker.register(
            "aa:bb:cc:dd:ee:ff", "p1", "fedora", "41"
        )
        rec = tracker.transition(
            "aa:bb:cc:dd:ee:ff", ProvisionState.BOOTING
        )
        assert rec.state == ProvisionState.BOOTING

    def test_clear(self):
        tracker = ProvisionTracker()
        tracker.register("aa:bb:cc:dd:ee:ff", "p1", "fedora", "41")
        tracker.clear()
        assert tracker.list_all() == []


# ---- CLI migrate-state tests ----


class TestMigrateStateCLI:

    def test_migrate_state_success(self, tmp_path):
        from pxeos.cli import main

        state = {
            "aa:bb:cc:dd:ee:ff": {
                "mac": "aa:bb:cc:dd:ee:ff",
                "profile": "fedora-server",
                "os_family": "fedora",
                "os_version": "41",
                "state": "registered",
                "history": [],
            }
        }
        json_path = tmp_path / "state.json"
        json_path.write_text(json.dumps(state))
        db_path = tmp_path / "state.db"

        result = main([
            "--config", str(tmp_path / "nonexistent.toml"),
            "migrate-state",
            "--state-file", str(json_path),
            "--db-file", str(db_path),
        ])
        assert result == 0
        assert db_path.exists()

    def test_migrate_state_missing_file(self, tmp_path):
        from pxeos.cli import main

        result = main([
            "--config", str(tmp_path / "nonexistent.toml"),
            "migrate-state",
            "--state-file", str(tmp_path / "missing.json"),
            "--db-file", str(tmp_path / "state.db"),
        ])
        assert result == 1
