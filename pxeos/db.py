"""Database abstraction layer for PxeOS provisioning state.

Provides a pluggable storage backend so provisioning records can be
persisted to SQLite (default), JSON files (fallback), or kept purely
in memory (for tests).
"""

from __future__ import annotations

import abc
import json
import logging
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from pxeos.state import ProvisionRecord, ProvisionState

logger = logging.getLogger("pxeos.db")


# ---- Abstract interface ----


class StorageBackend(abc.ABC):
    """Abstract base class for provision-record persistence."""

    @abc.abstractmethod
    def save(self, record: ProvisionRecord) -> None:
        """Persist a provision record (insert or update)."""

    @abc.abstractmethod
    def get(self, mac: str) -> Optional[ProvisionRecord]:
        """Retrieve a provision record by MAC address."""

    @abc.abstractmethod
    def list_all(self) -> List[ProvisionRecord]:
        """Return every stored provision record."""

    @abc.abstractmethod
    def delete(self, mac: str) -> bool:
        """Delete a provision record.  Return True if it existed."""

    @abc.abstractmethod
    def clear(self) -> None:
        """Remove all stored provision records."""

    @abc.abstractmethod
    def close(self) -> None:
        """Release any resources held by the backend."""


# ---- Serialisation helpers ----


def _record_to_dict(record: ProvisionRecord) -> Dict[str, Any]:
    """Serialize a ProvisionRecord to a plain dict for storage."""
    return {
        "mac": record.mac,
        "profile": record.profile,
        "os_family": record.os_family,
        "os_version": record.os_version,
        "state": record.state.value,
        "started_at": record.started_at,
        "updated_at": record.updated_at,
        "completed_at": record.completed_at,
        "error_message": record.error_message,
        "history": [
            {"state": s.value, "timestamp": ts}
            for s, ts in record.history
        ],
        "netboot_enabled": record.netboot_enabled,
    }


def _dict_to_record(d: Dict[str, Any]) -> ProvisionRecord:
    """Deserialize a plain dict back into a ProvisionRecord."""
    history = [
        (ProvisionState(h["state"]), h["timestamp"])
        for h in d.get("history", [])
    ]
    return ProvisionRecord(
        mac=d["mac"],
        profile=d["profile"],
        os_family=d["os_family"],
        os_version=d["os_version"],
        state=ProvisionState(d["state"]),
        started_at=d.get("started_at"),
        updated_at=d.get("updated_at"),
        completed_at=d.get("completed_at"),
        error_message=d.get("error_message"),
        history=history,
        netboot_enabled=d.get("netboot_enabled", True),
    )


# ---- SQLite backend ----


_SCHEMA_SQL = """\
CREATE TABLE IF NOT EXISTS provisions (
    mac            TEXT PRIMARY KEY,
    profile        TEXT NOT NULL,
    os_family      TEXT NOT NULL,
    os_version     TEXT NOT NULL,
    state          TEXT NOT NULL,
    started_at     REAL,
    updated_at     REAL,
    completed_at   REAL,
    error_message  TEXT,
    history        TEXT NOT NULL DEFAULT '[]',
    netboot_enabled INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_provisions_state
    ON provisions(state);
CREATE INDEX IF NOT EXISTS idx_provisions_updated
    ON provisions(updated_at);
"""


class SQLiteBackend(StorageBackend):
    """SQLite-backed storage with ACID transactions.

    The database is created automatically if it does not exist.
    Thread-safe via an internal lock (SQLite itself serialises
    writes, but the lock avoids Python-level races).
    """

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._lock = threading.Lock()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(
            str(db_path),
            check_same_thread=False,
        )
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._conn.executescript(_SCHEMA_SQL)
        self._conn.commit()
        logger.info("SQLite backend opened: %s", db_path)

    # -- public API --

    def save(self, record: ProvisionRecord) -> None:
        history_json = json.dumps([
            {"state": s.value, "timestamp": ts}
            for s, ts in record.history
        ])
        with self._lock:
            self._conn.execute(
                """\
                INSERT OR REPLACE INTO provisions
                    (mac, profile, os_family, os_version, state,
                     started_at, updated_at, completed_at,
                     error_message, history, netboot_enabled)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.mac.lower(),
                    record.profile,
                    record.os_family,
                    record.os_version,
                    record.state.value,
                    record.started_at,
                    record.updated_at,
                    record.completed_at,
                    record.error_message,
                    history_json,
                    int(record.netboot_enabled),
                ),
            )
            self._conn.commit()

    def get(self, mac: str) -> Optional[ProvisionRecord]:
        with self._lock:
            cur = self._conn.execute(
                "SELECT * FROM provisions WHERE mac = ?",
                (mac.lower(),),
            )
            row = cur.fetchone()
        if row is None:
            return None
        return self._row_to_record(row, cur.description)

    def list_all(self) -> List[ProvisionRecord]:
        with self._lock:
            cur = self._conn.execute(
                "SELECT * FROM provisions ORDER BY updated_at DESC"
            )
            rows = cur.fetchall()
            desc = cur.description
        return [self._row_to_record(r, desc) for r in rows]

    def delete(self, mac: str) -> bool:
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM provisions WHERE mac = ?",
                (mac.lower(),),
            )
            self._conn.commit()
            return cur.rowcount > 0

    def clear(self) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM provisions")
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()
        logger.info("SQLite backend closed: %s", self._db_path)

    def query_by_state(self, state: ProvisionState) -> List[ProvisionRecord]:
        """Return all records in the given state (uses index)."""
        with self._lock:
            cur = self._conn.execute(
                "SELECT * FROM provisions WHERE state = ? "
                "ORDER BY updated_at DESC",
                (state.value,),
            )
            rows = cur.fetchall()
            desc = cur.description
        return [self._row_to_record(r, desc) for r in rows]

    # -- internal helpers --

    @staticmethod
    def _row_to_record(
        row: tuple, description: Any,
    ) -> ProvisionRecord:
        cols = [d[0] for d in description]
        d = dict(zip(cols, row))
        history = json.loads(d.get("history", "[]"))
        history_tuples = [
            (ProvisionState(h["state"]), h["timestamp"])
            for h in history
        ]
        return ProvisionRecord(
            mac=d["mac"],
            profile=d["profile"],
            os_family=d["os_family"],
            os_version=d["os_version"],
            state=ProvisionState(d["state"]),
            started_at=d.get("started_at"),
            updated_at=d.get("updated_at"),
            completed_at=d.get("completed_at"),
            error_message=d.get("error_message"),
            history=history_tuples,
            netboot_enabled=bool(d.get("netboot_enabled", 1)),
        )


# ---- JSON file backend (fallback) ----


class JSONBackend(StorageBackend):
    """JSON-file-backed storage.

    Reads/writes the entire state on every operation.  Simple but
    not concurrent-safe -- use SQLiteBackend for production.
    """

    def __init__(self, json_path: Path) -> None:
        self._path = json_path
        self._lock = threading.Lock()
        json_path.parent.mkdir(parents=True, exist_ok=True)
        logger.info("JSON backend opened: %s", json_path)

    def save(self, record: ProvisionRecord) -> None:
        with self._lock:
            data = self._load()
            data[record.mac.lower()] = _record_to_dict(record)
            self._dump(data)

    def get(self, mac: str) -> Optional[ProvisionRecord]:
        with self._lock:
            data = self._load()
        entry = data.get(mac.lower())
        if entry is None:
            return None
        return _dict_to_record(entry)

    def list_all(self) -> List[ProvisionRecord]:
        with self._lock:
            data = self._load()
        return [_dict_to_record(v) for v in data.values()]

    def delete(self, mac: str) -> bool:
        with self._lock:
            data = self._load()
            if mac.lower() in data:
                del data[mac.lower()]
                self._dump(data)
                return True
            return False

    def clear(self) -> None:
        with self._lock:
            self._dump({})

    def close(self) -> None:
        pass  # nothing to release

    # -- internal --

    def _load(self) -> Dict[str, Any]:
        if not self._path.exists():
            return {}
        try:
            text = self._path.read_text()
            return json.loads(text) if text.strip() else {}
        except (json.JSONDecodeError, OSError):
            logger.warning(
                "Failed to read JSON state file: %s", self._path,
            )
            return {}

    def _dump(self, data: Dict[str, Any]) -> None:
        self._path.write_text(json.dumps(data, indent=2))


# ---- In-memory backend (for tests / ephemeral use) ----


class MemoryBackend(StorageBackend):
    """Purely in-memory backend -- no persistence."""

    def __init__(self) -> None:
        self._records: Dict[str, ProvisionRecord] = {}

    def save(self, record: ProvisionRecord) -> None:
        self._records[record.mac.lower()] = record

    def get(self, mac: str) -> Optional[ProvisionRecord]:
        return self._records.get(mac.lower())

    def list_all(self) -> List[ProvisionRecord]:
        return list(self._records.values())

    def delete(self, mac: str) -> bool:
        return self._records.pop(mac.lower(), None) is not None

    def clear(self) -> None:
        self._records.clear()

    def close(self) -> None:
        pass


# ---- Migration helpers ----


def migrate_json_to_sqlite(
    json_path: Path,
    db_path: Path,
) -> int:
    """Import records from a JSON state file into a SQLite database.

    Returns the number of records migrated.
    """
    if not json_path.exists():
        raise FileNotFoundError(
            f"State file not found: {json_path}"
        )

    text = json_path.read_text()
    raw = json.loads(text) if text.strip() else {}

    # The JSON file might be a flat dict keyed by MAC, or a list.
    if isinstance(raw, list):
        records = raw
    elif isinstance(raw, dict):
        records = list(raw.values())
    else:
        raise ValueError(
            f"Unexpected JSON structure in {json_path}"
        )

    backend = SQLiteBackend(db_path)
    count = 0
    for entry in records:
        try:
            record = _dict_to_record(entry)
            backend.save(record)
            count += 1
        except (KeyError, ValueError) as exc:
            logger.warning(
                "Skipping malformed record: %s (%s)", entry, exc,
            )
    backend.close()
    return count
