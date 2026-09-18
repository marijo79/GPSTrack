#!/usr/bin/env python3
"""Small REST wrapper around `termux-sms-send`.

Run this inside Termux (with the Termux:API app installed alongside the
`termux-api` package) to expose an HTTP endpoint that gpstrack can POST to
for sending SMS notifications. Uses only the standard library.

Setup (once), inside Termux:
    pkg install python termux-api
    termux-sms-send -n <your own number> "test"   # grants the SMS permission

Run:
    python sms_gateway.py --token YOUR_SHARED_SECRET [--port 8080]

Or, to avoid the token showing up in `ps` output, set it via environment
variable instead of --token:
    SMS_GATEWAY_TOKEN=YOUR_SHARED_SECRET python sms_gateway.py

Then, on the machine running gpstrack, set in .env:
    SMS_GATEWAY_URL=http://<phone-ip>:8080/sms
    SMS_GATEWAY_TOKEN=YOUR_SHARED_SECRET
    SMS_TO_NUMBER=+1234567890

The token is a shared secret, not real authentication (no TLS here) --
only run this on a network you trust, and pick a long random token, e.g.:
    python -c "import secrets; print(secrets.token_urlsafe(32))"
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def make_handler(token: str) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def _json(self, status: int, payload: dict) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
            if self.path != "/sms":
                self._json(404, {"error": "not found"})
                return

            if self.headers.get("Authorization") != f"Bearer {token}":
                self._json(401, {"error": "unauthorized"})
                return

            length = int(self.headers.get("Content-Length", 0))
            raw_body = self.rfile.read(length) if length else b"{}"
            try:
                data = json.loads(raw_body)
            except json.JSONDecodeError:
                self._json(400, {"error": "invalid json"})
                return

            to_number = data.get("to")
            message = data.get("message")
            if not to_number or not message:
                self._json(400, {"error": "'to' and 'message' are required"})
                return

            try:
                result = subprocess.run(
                    ["termux-sms-send", "-n", to_number, message],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                self._json(502, {"error": str(exc)})
                return

            if result.returncode != 0:
                self._json(502, {"error": result.stderr.strip() or "termux-sms-send failed"})
                return

            self._json(200, {"status": "sent"})

        def log_message(self, format: str, *args) -> None:  # noqa: A002 - stdlib signature
            print(f"{self.address_string()} - {format % args}")

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser(description="Expose termux-sms-send over a small REST API")
    parser.add_argument(
        "--token",
        default=None,
        help="shared secret required as 'Authorization: Bearer <token>' "
        "(or set the SMS_GATEWAY_TOKEN env var instead, to keep it out of `ps` output)",
    )
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--host", default="0.0.0.0")
    args = parser.parse_args()

    token = args.token or os.environ.get("SMS_GATEWAY_TOKEN")
    if not token:
        parser.error("provide --token or set the SMS_GATEWAY_TOKEN environment variable")

    server = ThreadingHTTPServer((args.host, args.port), make_handler(token))
    print(f"Listening on {args.host}:{args.port} (POST /sms, Bearer token required)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
