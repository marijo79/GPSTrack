"""Notification backends.

Keep this dead simple: a Notifier is anything with a `.send(title, message)`
method. LogNotifier always works; the others degrade to a no-op (with a
logged reason) when they're not configured or not available.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import smtplib
import subprocess
import urllib.error
import urllib.request
from email.message import EmailMessage
from typing import Iterable, List, Optional, Protocol

from gpstrack.usb_discovery import find_usb_gateway

logger = logging.getLogger(__name__)


class Notifier(Protocol):
    def send(self, title: str, message: str) -> None: ...


class LogNotifier:
    def send(self, title: str, message: str) -> None:
        logger.info("%s: %s", title, message)


class DesktopNotifier:
    """Sends a desktop notification via notify-send, if installed."""

    def __init__(self) -> None:
        self._available = shutil.which("notify-send") is not None
        if not self._available:
            logger.debug("notify-send not found; desktop notifications disabled")

    def send(self, title: str, message: str) -> None:
        if not self._available:
            return
        try:
            subprocess.run(["notify-send", title, message], check=False, timeout=5)
        except OSError as exc:
            logger.warning("Failed to send desktop notification: %s", exc)


class EmailNotifier:
    """Sends notifications by SMTP email."""

    def __init__(
        self,
        host: str,
        port: int,
        from_addr: str,
        to_addrs: List[str],
        username: Optional[str] = None,
        password: Optional[str] = None,
        use_tls: bool = True,
    ):
        self.host = host
        self.port = port
        self.from_addr = from_addr
        self.to_addrs = to_addrs
        self.username = username
        self.password = password
        self.use_tls = use_tls

    def send(self, title: str, message: str) -> None:
        msg = EmailMessage()
        msg["Subject"] = title
        msg["From"] = self.from_addr
        msg["To"] = ", ".join(self.to_addrs)
        msg.set_content(message)

        try:
            with smtplib.SMTP(self.host, self.port, timeout=10) as server:
                if self.use_tls:
                    server.starttls()
                if self.username:
                    server.login(self.username, self.password or "")
                server.send_message(msg)
        except (OSError, smtplib.SMTPException) as exc:
            logger.warning("Failed to send email to %s via %s: %s", self.to_addrs, self.host, exc)
        else:
            logger.info("Sent email to %s via %s", self.to_addrs, self.host)

    @classmethod
    def from_env(cls) -> Optional["EmailNotifier"]:
        host = os.environ.get("SMTP_HOST")
        to_raw = os.environ.get("SMTP_TO")
        if not host or not to_raw:
            return None

        username = os.environ.get("SMTP_USER")
        return cls(
            host=host,
            port=int(os.environ.get("SMTP_PORT", "587")),
            from_addr=os.environ.get("SMTP_FROM", username or ""),
            to_addrs=[addr.strip() for addr in to_raw.split(",") if addr.strip()],
            username=username,
            password=os.environ.get("SMTP_PASSWORD"),
            use_tls=os.environ.get("SMTP_USE_TLS", "true").strip().lower() not in ("0", "false", "no"),
        )


class SmsNotifier:
    """Sends SMS via a small REST wrapper (see termux/sms_gateway.py) running
    on a phone under Termux, which shells out to termux-sms-send.

    If `url` isn't given, the gateway's address is auto-discovered on every
    send by reading the default route on a USB-tethering-looking interface
    (see gpstrack.usb_discovery) -- this is what a USB-tethered phone's IP
    looks like from the host's side, and it survives the interface being
    renamed or the host's own IP changing across reconnects.
    """

    def __init__(
        self,
        to_number: str,
        url: Optional[str] = None,
        port: int = 8080,
        token: str = "",
        timeout: float = 10.0,
    ):
        self.to_number = to_number
        self.url = url
        self.port = port
        self.token = token
        self.timeout = timeout

    def _resolve_url(self) -> Optional[str]:
        if self.url:
            return self.url
        gateway_ip = find_usb_gateway()
        if gateway_ip is None:
            return None
        return f"http://{gateway_ip}:{self.port}/sms"

    def send(self, title: str, message: str) -> None:
        url = self._resolve_url()
        if url is None:
            logger.warning(
                "Could not send SMS: no SMS_GATEWAY_URL configured and no "
                "USB-tethering default route found to auto-discover it"
            )
            return

        body = json.dumps({"to": self.to_number, "message": f"{title}: {message}"}).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"

        logger.info("Sending SMS to %s via %s", self.to_number, url)
        request = urllib.request.Request(url, data=body, method="POST", headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                if response.status >= 300:
                    logger.warning("SMS gateway at %s returned HTTP %s", url, response.status)
                else:
                    logger.info("Sent SMS to %s via %s", self.to_number, url)
        except (urllib.error.URLError, OSError) as exc:
            logger.warning("Failed to send SMS to %s via %s: %s", self.to_number, url, exc)

    @classmethod
    def from_env(cls) -> Optional["SmsNotifier"]:
        to_number = os.environ.get("SMS_TO_NUMBER")
        if not to_number:
            return None

        return cls(
            to_number=to_number,
            url=os.environ.get("SMS_GATEWAY_URL"),
            port=int(os.environ.get("SMS_GATEWAY_PORT", "8080")),
            token=os.environ.get("SMS_GATEWAY_TOKEN", ""),
        )


class MultiNotifier:
    """Fans a notification out to several backends."""

    def __init__(self, notifiers: Iterable[Notifier]):
        self._notifiers = list(notifiers)

    def send(self, title: str, message: str) -> None:
        for notifier in self._notifiers:
            notifier.send(title, message)


def default_notifier() -> Notifier:
    notifiers: List[Notifier] = [LogNotifier(), DesktopNotifier()]

    email_notifier = EmailNotifier.from_env()
    if email_notifier is not None:
        notifiers.append(email_notifier)
    else:
        logger.debug("Email notifications disabled (set SMTP_HOST and SMTP_TO to enable)")

    sms_notifier = SmsNotifier.from_env()
    if sms_notifier is not None:
        notifiers.append(sms_notifier)
    else:
        logger.debug("SMS notifications disabled (set SMS_TO_NUMBER to enable)")

    return MultiNotifier(notifiers)
