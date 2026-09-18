"""SQLite persistence for fixes and notification events."""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from gpstrack.gpsd_client import TPV

logger = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS fixes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    received_at TEXT NOT NULL,
    gps_time TEXT,
    mode INTEGER NOT NULL,
    lat REAL,
    lon REAL
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    occurred_at TEXT NOT NULL,
    event_type TEXT NOT NULL,
    message TEXT NOT NULL,
    lat REAL,
    lon REAL
);
"""


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class TrackStorage:
    """Thin wrapper around a SQLite database of fixes and events.

    Uses WAL journal mode so the database can be safely queried (read-only)
    with a separate `sqlite3` session while gpstrack is running and writing
    to it. Write failures are logged and swallowed rather than raised, so a
    storage hiccup never takes down GPS monitoring/notifications, which are
    the primary function.

    Not thread-safe; use one instance per connection/thread, matching the
    single-threaded gpstrack main loop.
    """

    def __init__(self, db_path: str):
        self.db_path = db_path
        if db_path != ":memory:":
            Path(db_path).resolve().parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def record_fix(self, tpv: TPV) -> None:
        try:
            self._conn.execute(
                "INSERT INTO fixes (received_at, gps_time, mode, lat, lon) VALUES (?, ?, ?, ?, ?)",
                (_utc_now_iso(), tpv.time, tpv.mode, tpv.lat, tpv.lon),
            )
            self._conn.commit()
        except sqlite3.Error as exc:
            logger.warning("Failed to record fix in %s: %s", self.db_path, exc)

    def record_event(
        self,
        event_type: str,
        message: str,
        lat: Optional[float] = None,
        lon: Optional[float] = None,
    ) -> None:
        try:
            self._conn.execute(
                "INSERT INTO events (occurred_at, event_type, message, lat, lon) VALUES (?, ?, ?, ?, ?)",
                (_utc_now_iso(), event_type, message, lat, lon),
            )
            self._conn.commit()
        except sqlite3.Error as exc:
            logger.warning("Failed to record event in %s: %s", self.db_path, exc)

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "TrackStorage":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()
