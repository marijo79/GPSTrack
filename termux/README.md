# SMS gateway (Termux)

Exposes a tiny REST API on your phone, backed by `termux-sms-send`, so
gpstrack can send SMS notifications through your phone's SIM.

## One-time setup, on the phone

1. Install **Termux** and **Termux:API** from the same source (both from
   F-Droid, or both from the same store) -- mixing sources breaks the
   plugin link between them.
2. In Termux:
   ```bash
   pkg install python termux-api
   ```
3. Grant the SMS permission by sending yourself a test message once
   (Android will prompt for the permission the first time):
   ```bash
   termux-sms-send -n <your own number> "test"
   ```
4. Copy `sms_gateway.py` onto the phone (e.g. via `git clone`, `scp`, or
   just retyping it) and pick a long random shared secret:
   ```bash
   python -c "import secrets; print(secrets.token_urlsafe(32))"
   ```

## Running

```bash
python sms_gateway.py --token YOUR_SHARED_SECRET
```

**If using USB tethering** (the common case), you don't need to look up or
configure any IP address: on the machine running gpstrack, just set in
`.env`:

```
SMS_GATEWAY_TOKEN=YOUR_SHARED_SECRET
SMS_TO_NUMBER=+1234567890
```

and leave `SMS_GATEWAY_URL` unset. gpstrack auto-discovers the phone's IP
on every send by reading the default route of the USB-tethering interface
(`gpstrack/usb_discovery.py`) -- a USB-tethered phone acts as the gateway
for that link, so this works even if the interface gets renamed or the
host's own IP on that link changes across reconnects (we verified both
across an actual disconnect/reconnect). If it's ever on a different port
than 8080, set `SMS_GATEWAY_PORT` instead.

**If the phone is on Wi-Fi instead**, auto-discovery won't find a USB
route, so set the IP explicitly (`ip addr` in Termux, look for `wlan0`):

```
SMS_GATEWAY_URL=http://<phone-ip>:8080/sms
SMS_GATEWAY_TOKEN=YOUR_SHARED_SECRET
SMS_TO_NUMBER=+1234567890
```

(We also tried mDNS hostname discovery as a fancier alternative for this
case, but it turned out unnecessary once USB auto-discovery covered the
common case -- ask if you want it added for a Wi-Fi setup.)

To keep it running in the background: run `termux-wake-lock` first (stops
Android from suspending Termux), and run the server inside `tmux` or with
`nohup ... &` so it survives closing the Termux window.

Also turn off battery optimization for **both Termux and Termux:API**
(Android Settings -> Apps -> [app] -> Battery -> Unrestricted). Without
this, `termux-sms-send` can work fine while Termux is foregrounded but
have the actual SMS delivery delayed by up to ~30s once it's backgrounded,
since Android throttles the background broadcast to Termux:API.

## Auto-start on boot (Termux:Boot)

Install the **Termux:Boot** app (same source as Termux/Termux:API), then
**open it once** -- Android requires an app to have been launched at least
once before it's allowed to register a boot-completed receiver, so this
step doesn't do anything visible but is required. Also set Termux:Boot to
"Unrestricted" battery usage.

Then, in Termux:

```bash
mkdir -p ~/.termux/boot

# keep the token out of `ps` output by storing it in a private file
echo "YOUR_SHARED_SECRET" > ~/.sms_gateway_token
chmod 600 ~/.sms_gateway_token

cat > ~/.termux/boot/start-sms-gateway.sh <<'EOF'
#!/data/data/com.termux/files/usr/bin/sh
termux-wake-lock
export SMS_GATEWAY_TOKEN=$(cat ~/.sms_gateway_token)
nohup python ~/sms_gateway.py >> ~/sms_gateway.log 2>&1 &
EOF
chmod 700 ~/.termux/boot/start-sms-gateway.sh
```

`sms_gateway.py` reads the token from the `SMS_GATEWAY_TOKEN` environment
variable if `--token` isn't passed, which is what the boot script uses
above -- this avoids leaking the shared secret to any app that can read
`/proc` or run `ps`. Run `sh ~/.termux/boot/start-sms-gateway.sh` once by
hand to start it immediately, without waiting for a reboot; from then on
it restarts automatically whenever the phone boots.

## Security note

There's no TLS and the token is a plain shared secret compared with a
simple string equality check -- fine on a trusted home/local network, not
something to expose on the open internet. If you need it reachable
remotely, put it behind a VPN (e.g. Tailscale) rather than port-forwarding
it directly.

## API

```
POST /sms
Authorization: Bearer YOUR_SHARED_SECRET
Content-Type: application/json

{"to": "+1234567890", "message": "GPS moved: ..."}
```

Responds `200 {"status": "sent"}` on success, `401`/`400`/`502` with an
`{"error": "..."}` body otherwise.
