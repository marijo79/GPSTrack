from __future__ import annotations

import argparse
import logging
import time
from pathlib import Path

from gpstrack.config import load_dotenv
from gpstrack.gpsd_client import DEFAULT_HOST, DEFAULT_PORT, GpsdClient
from gpstrack.notifier import default_notifier
from gpstrack.storage import TrackStorage
from gpstrack.tracker import FixTracker

logger = logging.getLogger("gpstrack")

RECONNECT_DELAY_SECONDS = 5
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = str(PROJECT_ROOT / "sqlite" / "gpstrack.db")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Watch gpsd and notify on fix loss / large movement")
    parser.add_argument("--host", default=DEFAULT_HOST, help="gpsd host (default: %(default)s)")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="gpsd port (default: %(default)s)")
    parser.add_argument(
        "--distance-threshold-km",
        type=float,
        default=5.0,
        help="notify when position moves this many km from the last tracked point (default: %(default)s)",
    )
    parser.add_argument(
        "--db",
        default=DEFAULT_DB_PATH,
        help="SQLite file to log fixes and events to, or 'none' to disable (default: %(default)s)",
    )
    parser.add_argument(
        "--stale-timeout-seconds",
        type=float,
        default=20.0,
        help="notify if no gpsd report of any kind arrives for this long, e.g. on device unplug (default: %(default)s)",
    )
    parser.add_argument(
        "--status-interval-seconds",
        type=float,
        default=60.0,
        help="log current fix/no-fix status at startup and on this interval (default: %(default)s)",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="enable debug logging")
    return parser.parse_args()


def run(
    host: str,
    port: int,
    distance_threshold_km: float,
    db_path: str,
    stale_timeout_seconds: float,
    status_interval_seconds: float,
) -> None:
    notifier = default_notifier()
    storage = TrackStorage(db_path) if db_path.lower() != "none" else None
    if storage is not None:
        logger.info("Logging fixes and events to %s", db_path)
    tracker = FixTracker(
        notifier,
        distance_threshold_km=distance_threshold_km,
        storage=storage,
        status_interval_seconds=status_interval_seconds,
    )

    try:
        while True:
            try:
                with GpsdClient(host, port) as client:
                    for report in client.reports(stale_after=stale_timeout_seconds):
                        tracker.process(report)
            except (ConnectionError, OSError) as exc:
                logger.warning("Lost connection to gpsd (%s); retrying in %ss", exc, RECONNECT_DELAY_SECONDS)
                time.sleep(RECONNECT_DELAY_SECONDS)
    finally:
        if storage is not None:
            storage.close()


def main() -> None:
    load_dotenv(PROJECT_ROOT / ".env")
    args = parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        run(
            args.host,
            args.port,
            args.distance_threshold_km,
            args.db,
            args.stale_timeout_seconds,
            args.status_interval_seconds,
        )
    except KeyboardInterrupt:
        logger.info("Stopped")


if __name__ == "__main__":
    main()
