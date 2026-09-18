import json

from gpstrack.notifier import EmailNotifier, SmsNotifier


def test_email_notifier_from_env_missing_returns_none(monkeypatch):
    monkeypatch.delenv("SMTP_HOST", raising=False)
    monkeypatch.delenv("SMTP_TO", raising=False)
    assert EmailNotifier.from_env() is None


def test_email_notifier_from_env_builds_notifier(monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SMTP_PORT", "465")
    monkeypatch.setenv("SMTP_TO", "a@example.com, b@example.com")
    monkeypatch.setenv("SMTP_USER", "me@example.com")
    monkeypatch.setenv("SMTP_USE_TLS", "false")

    notifier = EmailNotifier.from_env()

    assert notifier is not None
    assert notifier.host == "smtp.example.com"
    assert notifier.port == 465
    assert notifier.to_addrs == ["a@example.com", "b@example.com"]
    assert notifier.from_addr == "me@example.com"
    assert notifier.use_tls is False


def test_email_notifier_send_uses_smtp(monkeypatch):
    sent = {}

    class FakeSMTP:
        def __init__(self, host, port, timeout=None):
            sent["host"] = host
            sent["port"] = port

        def __enter__(self):
            return self

        def __exit__(self, *exc_info):
            return False

        def starttls(self):
            sent["starttls"] = True

        def login(self, username, password):
            sent["login"] = (username, password)

        def send_message(self, msg):
            sent["subject"] = msg["Subject"]
            sent["to"] = msg["To"]

    monkeypatch.setattr("gpstrack.notifier.smtplib.SMTP", FakeSMTP)

    notifier = EmailNotifier(
        host="smtp.example.com",
        port=587,
        from_addr="me@example.com",
        to_addrs=["you@example.com"],
        username="me@example.com",
        password="secret",
    )
    notifier.send("GPS moved", "details here")

    assert sent["host"] == "smtp.example.com"
    assert sent["starttls"] is True
    assert sent["login"] == ("me@example.com", "secret")
    assert sent["subject"] == "GPS moved"
    assert sent["to"] == "you@example.com"


def test_sms_notifier_from_env_missing_returns_none(monkeypatch):
    monkeypatch.delenv("SMS_GATEWAY_URL", raising=False)
    monkeypatch.delenv("SMS_TO_NUMBER", raising=False)
    assert SmsNotifier.from_env() is None


def test_sms_notifier_from_env_without_url_enables_auto_discovery(monkeypatch):
    monkeypatch.delenv("SMS_GATEWAY_URL", raising=False)
    monkeypatch.setenv("SMS_TO_NUMBER", "+1234567890")
    monkeypatch.setenv("SMS_GATEWAY_PORT", "9090")

    notifier = SmsNotifier.from_env()

    assert notifier is not None
    assert notifier.url is None
    assert notifier.port == 9090


def test_sms_notifier_send_posts_json(monkeypatch):
    captured = {}

    class FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *exc_info):
            return False

    def fake_urlopen(request, timeout=None):
        captured["url"] = request.full_url
        captured["method"] = request.get_method()
        captured["headers"] = dict(request.header_items())
        captured["body"] = json.loads(request.data)
        return FakeResponse()

    monkeypatch.setattr("gpstrack.notifier.urllib.request.urlopen", fake_urlopen)

    notifier = SmsNotifier(url="http://phone:8080/sms", to_number="+1234567890", token="secret-token")
    notifier.send("GPS moved", "details here")

    assert captured["url"] == "http://phone:8080/sms"
    assert captured["method"] == "POST"
    assert captured["headers"]["Authorization"] == "Bearer secret-token"
    assert captured["body"] == {"to": "+1234567890", "message": "GPS moved: details here"}


def test_sms_notifier_auto_discovers_url_when_not_configured(monkeypatch):
    captured = {}

    class FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *exc_info):
            return False

    def fake_urlopen(request, timeout=None):
        captured["url"] = request.full_url
        return FakeResponse()

    monkeypatch.setattr("gpstrack.notifier.urllib.request.urlopen", fake_urlopen)
    monkeypatch.setattr("gpstrack.notifier.find_usb_gateway", lambda: "10.40.52.137")

    notifier = SmsNotifier(to_number="+1234567890", port=8080)
    notifier.send("GPS moved", "details here")

    assert captured["url"] == "http://10.40.52.137:8080/sms"


def test_sms_notifier_skips_send_when_discovery_fails(monkeypatch):
    def fail_urlopen(*args, **kwargs):
        raise AssertionError("should not attempt to send when no URL could be resolved")

    monkeypatch.setattr("gpstrack.notifier.urllib.request.urlopen", fail_urlopen)
    monkeypatch.setattr("gpstrack.notifier.find_usb_gateway", lambda: None)

    notifier = SmsNotifier(to_number="+1234567890")
    notifier.send("GPS moved", "details here")  # must not raise
