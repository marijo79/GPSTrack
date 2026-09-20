# GPSTrack

Watches [gpsd](https://gpsd.io/) and sends a notification when:

- the fix is lost (FIX -> NOFIX transition)
- the fix is regained (NOFIX -> FIX transition)
- the position moves more than 5 km (configurable) from the last tracked point
- the GPS device disconnects or reconnects (gpsd `DEVICE` activation report, e.g. USB unplug/replug)
- no data of any kind arrives from gpsd for a while (`--stale-timeout-seconds`,
  default 20s) -- catches disconnects gpsd doesn't cleanly report

It also logs the current GPS status (fix coordinates, or `NO FIX`) right after
startup and every `--status-interval-seconds` (default 60s) afterward.

## Requirements

- A running `gpsd` instance (default: `127.0.0.1:2947`)
- Python 3.9+, standard library only
- Optional: `notify-send` (from `libnotify-bin`) for desktop popups; without it, events are just logged

## Usage

```bash
python -m gpstrack.main [--host HOST] [--port PORT] [--distance-threshold-km 5.0] [--db PATH] [--stale-timeout-seconds 20.0] [--status-interval-seconds 60.0] [-v]
```

Every TPV report and every notification event is logged to a SQLite database
at `sqlite/gpstrack.db` (created automatically). Override the path with
`--db PATH`, or pass `--db none` to disable persistence.

The database uses WAL journal mode, so it's safe to query it (see below)
with a separate `sqlite3` session while gpstrack is running -- you'll see
`gpstrack.db-wal` and `gpstrack.db-shm` sidecar files appear alongside it,
which is normal. A storage write failure is logged as a warning and never
crashes the app; GPS monitoring and notifications keep running regardless.

## Notification channels

Every event always goes to the log, plus a desktop popup if `notify-send`
is installed. Email and SMS are additional channels, each enabled by
setting its environment variables -- copy `.env.example` to `.env` and fill
in what you want:

- **Email**: `SMTP_HOST`, `SMTP_TO` (required); `SMTP_PORT`, `SMTP_USER`,
  `SMTP_PASSWORD`, `SMTP_FROM`, `SMTP_USE_TLS` (optional).
- **SMS**: `SMS_TO_NUMBER` (required); `SMS_GATEWAY_TOKEN` (optional but
  strongly recommended); `SMS_GATEWAY_URL` (only needed if the phone isn't
  reachable via USB tethering -- see below). SMS is sent through a small
  REST wrapper you run under Termux on a phone with a SIM -- see
  [`termux/README.md`](termux/README.md) for setup.

  If the phone is connected over USB tethering, its IP is auto-discovered
  on every send from the USB interface's default route (a tethered phone
  acts as the gateway for that link), so `SMS_GATEWAY_URL` can be left
  unset and there's nothing to update if the IP changes across reconnects.

`.env` is gitignored; any channel left unconfigured is silently skipped.

## Querying the database

Open the DB with the `sqlite3` CLI (`sudo apt install sqlite3` if you don't
have it):

```bash
sqlite3 sqlite/gpstrack.db
```

Then, at the `sqlite>` prompt:

```sql
-- list tables
.tables

-- show table schemas (columns, types)
.schema

-- nicer table formatting
.headers on
.mode column

-- most recent events (fix_lost, moved, device_disconnected, gps_stale)
SELECT * FROM events ORDER BY id DESC LIMIT 20;

-- only disconnect-related events
SELECT * FROM events WHERE event_type IN ('device_disconnected', 'gps_stale') ORDER BY id DESC;

-- most recent raw fixes
SELECT * FROM fixes ORDER BY id DESC LIMIT 20;

.quit
```

Or run a one-off query without an interactive session:

```bash
sqlite3 -header -column sqlite/gpstrack.db "SELECT * FROM events ORDER BY id DESC LIMIT 20;"
```

## Running as a daemon (systemd user service)

Create `~/.config/systemd/user/gpstrack.service`:

```ini
[Unit]
Description=GPSTrack - gpsd fix/device/distance notifier
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=/home/dragon/PythonPtojects/GPSTrack
ExecStart=/home/dragon/PythonPtojects/GPSTrack/.venv/bin/python -m gpstrack.main
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
```

Enable lingering so the service starts at boot even without an active login
session, then enable and start it:

```bash
loginctl enable-linger dragon
systemctl --user daemon-reload
systemctl --user enable --now gpstrack.service
```

Useful commands:

```bash
systemctl --user status gpstrack.service          # health check
journalctl --user-unit gpstrack.service -f        # tail logs live
journalctl --user-unit gpstrack.service -n 100    # last 100 lines
systemctl --user restart gpstrack.service
systemctl --user stop gpstrack.service
systemctl --user disable --now gpstrack.service   # stop and remove from boot
```

Note: on some systems `journalctl --user -u gpstrack.service` (the usual
form) returns nothing if journald is configured with `Storage=volatile` and
no split user journal -- use `journalctl --user-unit gpstrack.service`
instead, which reads it from the system journal.

## Tests

```bash
pip install pytest
pytest
```
