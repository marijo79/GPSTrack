"""Turns a stream of gpsd reports into notification events.

Events detected:
  * fix -> no-fix transition
  * position moving more than `distance_threshold_km` from the last
    *tracked* point (the tracked point is updated each time the threshold
    is crossed, so distance is measured from wherever we last notified,
    not from the very first point ever seen)
  * GPS device disconnected (gpsd DEVICE report, e.g. USB unplugged)
  * no report of any kind received for a while (StaleTimeout) -- catches
    disconnects gpsd doesn't cleanly report
"""
from __future__ import annotations

import logging
import math
from typing import Optional

from gpstrack.gpsd_client import DeviceEvent, Report, StaleTimeout, TPV
from gpstrack.notifier import Notifier
from gpstrack.storage import TrackStorage

logger = logging.getLogger(__name__)

EARTH_RADIUS_KM = 6371.0088


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


class FixTracker:
    def __init__(
        self,
        notifier: Notifier,
        distance_threshold_km: float = 5.0,
        storage: Optional[TrackStorage] = None,
    ):
        self.notifier = notifier
        self.distance_threshold_km = distance_threshold_km
        self.storage = storage

        self._had_fix: Optional[bool] = None
        self._last_point: Optional[tuple[float, float]] = None
        self._device_connected: Optional[bool] = None
        self._stale_notified = False

    def process(self, report: Report) -> None:
        if isinstance(report, TPV):
            self._process_tpv(report)
        elif isinstance(report, DeviceEvent):
            self._process_device_event(report)
        elif isinstance(report, StaleTimeout):
            self._process_stale_timeout()

    def _notify(self, event_type: str, title: str, message: str, lat: Optional[float] = None, lon: Optional[float] = None) -> None:
        self.notifier.send(title, message)
        if self.storage is not None:
            self.storage.record_event(event_type, message, lat, lon)

    def _process_tpv(self, tpv: TPV) -> None:
        if self.storage is not None:
            self.storage.record_fix(tpv)

        # Any TPV means gpsd is actively reporting again.
        self._clear_stale()

        self._check_fix_transition(tpv)
        if tpv.has_fix and tpv.lat is not None and tpv.lon is not None:
            self._check_distance(tpv.lat, tpv.lon)

    def _check_fix_transition(self, tpv: TPV) -> None:
        has_fix = tpv.has_fix
        if self._had_fix is True and has_fix is False:
            lat, lon = self._last_point if self._last_point else (None, None)
            self._notify("fix_lost", "GPS fix lost", "gpsd reports NO FIX", lat, lon)
            logger.info("Fix -> no-fix transition detected")
        elif self._had_fix is False and has_fix is True:
            self._notify("fix_regained", "GPS fix regained", "gpsd reports a fix again", tpv.lat, tpv.lon)
            logger.info("No-fix -> fix transition detected")
        self._had_fix = has_fix

    def _check_distance(self, lat: float, lon: float) -> None:
        if self._last_point is None:
            self._last_point = (lat, lon)
            logger.info("Initial tracked point set to (%.6f, %.6f)", lat, lon)
            return

        distance = haversine_km(*self._last_point, lat, lon)
        if distance >= self.distance_threshold_km:
            self._notify(
                "moved",
                "GPS moved",
                f"Moved {distance:.2f} km from last tracked point "
                f"(now at {lat:.6f}, {lon:.6f})",
                lat,
                lon,
            )
            logger.info("Distance threshold crossed: %.2f km", distance)
            self._last_point = (lat, lon)

    def _process_device_event(self, event: DeviceEvent) -> None:
        self._clear_stale()

        if self._device_connected is True and event.activated is False:
            self._notify(
                "device_disconnected",
                "GPS device disconnected",
                f"gpsd reports device deactivated: {event.path or 'unknown device'}",
            )
            logger.info("Device disconnected: %s", event.path)
        elif self._device_connected is False and event.activated is True:
            self._notify(
                "device_connected",
                "GPS device connected",
                f"gpsd reports device activated: {event.path or 'unknown device'}",
            )
            logger.info("Device (re)connected: %s", event.path)
        self._device_connected = event.activated

    def _process_stale_timeout(self) -> None:
        if not self._stale_notified:
            self._notify(
                "gps_stale",
                "GPS data stopped",
                "No data received from gpsd for a while; the device may be disconnected",
            )
            logger.info("No gpsd reports received within the stale timeout")
        self._stale_notified = True

    def _clear_stale(self) -> None:
        if self._stale_notified:
            logger.info("Receiving gpsd reports again")
        self._stale_notified = False
