from gpstrack.gpsd_client import MODE_2D, TPV
from gpstrack.storage import TrackStorage
from gpstrack.tracker import FixTracker


class FakeNotifier:
    def send(self, title, message):
        pass


def test_record_fix_and_event(tmp_path):
    db_path = str(tmp_path / "gpstrack.db")
    storage = TrackStorage(db_path)
    try:
        storage.record_fix(TPV(mode=MODE_2D, lat=54.6872, lon=25.2797, time="2026-09-18T00:00:00Z"))
        storage.record_event("moved", "test event", lat=54.6872, lon=25.2797)

        fixes = storage._conn.execute("SELECT mode, lat, lon FROM fixes").fetchall()
        events = storage._conn.execute("SELECT event_type, message FROM events").fetchall()
    finally:
        storage.close()

    assert fixes == [(MODE_2D, 54.6872, 25.2797)]
    assert events == [("moved", "test event")]


def test_tracker_persists_fixes_and_events(tmp_path):
    db_path = str(tmp_path / "gpstrack.db")
    storage = TrackStorage(db_path)
    tracker = FixTracker(FakeNotifier(), distance_threshold_km=5.0, storage=storage)

    try:
        tracker.process(TPV(mode=MODE_2D, lat=54.6872, lon=25.2797))
        tracker.process(TPV(mode=MODE_2D, lat=54.8985, lon=23.9036))  # ~90km away

        fix_count = storage._conn.execute("SELECT COUNT(*) FROM fixes").fetchone()[0]
        events = storage._conn.execute("SELECT event_type FROM events").fetchall()
    finally:
        storage.close()

    assert fix_count == 2
    assert events == [("moved",)]


def test_record_fix_swallows_sqlite_errors(tmp_path, caplog):
    db_path = str(tmp_path / "gpstrack.db")
    storage = TrackStorage(db_path)
    storage._conn.close()  # simulate a broken connection (e.g. readonly database)

    with caplog.at_level("WARNING"):
        storage.record_fix(TPV(mode=MODE_2D, lat=1.0, lon=2.0))  # must not raise

    assert "Failed to record fix" in caplog.text


def test_wal_mode_enabled(tmp_path):
    db_path = str(tmp_path / "gpstrack.db")
    storage = TrackStorage(db_path)
    try:
        mode = storage._conn.execute("PRAGMA journal_mode").fetchone()[0]
    finally:
        storage.close()

    assert mode.lower() == "wal"
