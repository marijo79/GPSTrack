"""Minimal client for gpsd's JSON socket protocol.

Speaks the protocol directly over a TCP socket so the project has no
dependency beyond the standard library. See:
https://gpsd.gitlab.io/gpsd/gpsd_json.html
"""
from __future__ import annotations

import json
import logging
import socket
from dataclasses import dataclass
from typing import Iterator, Optional, Union

logger = logging.getLogger(__name__)

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 2947

# gpsd TPV "mode" values.
MODE_UNKNOWN = 0
MODE_NO_FIX = 1
MODE_2D = 2
MODE_3D = 3


@dataclass
class TPV:
    """A Time-Position-Velocity report from gpsd."""

    mode: int
    lat: Optional[float] = None
    lon: Optional[float] = None
    time: Optional[str] = None

    @property
    def has_fix(self) -> bool:
        return self.mode >= MODE_2D


@dataclass
class DeviceEvent:
    """A device add/remove report from gpsd (e.g. USB GPS plugged/unplugged)."""

    path: Optional[str]
    activated: bool


class StaleTimeout:
    """Sentinel: no message of any kind arrived from gpsd within the configured window."""


Report = Union[TPV, DeviceEvent, StaleTimeout]


class GpsdClient:
    """Connects to gpsd and yields reports (TPV / DeviceEvent / StaleTimeout) as they arrive."""

    def __init__(self, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT, timeout: float = 30.0):
        self.host = host
        self.port = port
        self.timeout = timeout
        self._sock: Optional[socket.socket] = None

    def connect(self) -> None:
        logger.info("Connecting to gpsd at %s:%s", self.host, self.port)
        self._sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        self._sock.sendall(b'?WATCH={"enable":true,"json":true};\n')

    def close(self) -> None:
        if self._sock is not None:
            self._sock.close()
            self._sock = None

    def reports(self, stale_after: Optional[float] = None) -> Iterator[Report]:
        """Yield reports forever. Reconnects are the caller's job.

        If `stale_after` is set, a StaleTimeout is yielded whenever that many
        seconds pass with no message of any kind from gpsd (e.g. because the
        USB device was unplugged and gpsd has nothing left to report).
        """
        if self._sock is None:
            self.connect()

        sock = self._sock
        assert sock is not None
        sock.settimeout(stale_after)

        buffer = ""
        while True:
            try:
                chunk = sock.recv(4096)
            except socket.timeout:
                yield StaleTimeout()
                continue

            if not chunk:
                raise ConnectionError("gpsd closed the connection")
            buffer += chunk.decode("utf-8", errors="replace")
            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                line = line.strip()
                if not line:
                    continue
                report = self._parse_line(line)
                if report is not None:
                    yield report

    @staticmethod
    def _parse_line(line: str) -> Optional[Report]:
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            logger.warning("Ignoring malformed gpsd message: %r", line)
            return None

        message_class = data.get("class")

        if message_class == "TPV":
            return TPV(
                mode=data.get("mode", MODE_UNKNOWN),
                lat=data.get("lat"),
                lon=data.get("lon"),
                time=data.get("time"),
            )

        if message_class == "DEVICE":
            return DeviceEvent(path=data.get("path"), activated=bool(data.get("activated")))

        return None

    def __enter__(self) -> "GpsdClient":
        self.connect()
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()
