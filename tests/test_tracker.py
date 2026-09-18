from gpstrack.gpsd_client import MODE_2D, MODE_NO_FIX, DeviceEvent, StaleTimeout, TPV
from gpstrack.tracker import FixTracker, haversine_km


class FakeNotifier:
    def __init__(self):
        self.sent = []

    def send(self, title, message):
        self.sent.append((title, message))


def test_haversine_known_distance():
    # Vilnius to Kaunas is roughly 90 km apart.
    distance = haversine_km(54.6872, 25.2797, 54.8985, 23.9036)
    assert 85 < distance < 95


def test_fix_loss_triggers_notification():
    notifier = FakeNotifier()
    tracker = FixTracker(notifier)

    tracker.process(TPV(mode=MODE_2D, lat=54.6872, lon=25.2797))
    tracker.process(TPV(mode=MODE_NO_FIX))

    assert len(notifier.sent) == 1
    assert notifier.sent[0][0] == "GPS fix lost"


def test_no_notification_while_fix_held():
    notifier = FakeNotifier()
    tracker = FixTracker(notifier)

    tracker.process(TPV(mode=MODE_2D, lat=54.6872, lon=25.2797))
    tracker.process(TPV(mode=MODE_2D, lat=54.6873, lon=25.2798))

    assert notifier.sent == []


def test_distance_threshold_triggers_notification_and_resets_reference_point():
    notifier = FakeNotifier()
    tracker = FixTracker(notifier, distance_threshold_km=5.0)

    tracker.process(TPV(mode=MODE_2D, lat=54.6872, lon=25.2797))  # sets initial point
    tracker.process(TPV(mode=MODE_2D, lat=54.8985, lon=23.9036))  # ~90km away

    assert len(notifier.sent) == 1
    assert notifier.sent[0][0] == "GPS moved"

    # Small move from the new reference point should not re-trigger.
    tracker.process(TPV(mode=MODE_2D, lat=54.8986, lon=23.9037))
    assert len(notifier.sent) == 1


def test_no_fix_reports_do_not_affect_distance_tracking():
    notifier = FakeNotifier()
    tracker = FixTracker(notifier, distance_threshold_km=5.0)

    tracker.process(TPV(mode=MODE_2D, lat=54.6872, lon=25.2797))
    tracker.process(TPV(mode=MODE_NO_FIX))
    notifier.sent.clear()

    tracker.process(TPV(mode=MODE_2D, lat=54.6873, lon=25.2798))
    # A small move right after regaining fix shouldn't also trigger "GPS moved".
    assert [title for title, _ in notifier.sent] == ["GPS fix regained"]


def test_fix_regained_triggers_notification():
    notifier = FakeNotifier()
    tracker = FixTracker(notifier)

    tracker.process(TPV(mode=MODE_2D, lat=54.6872, lon=25.2797))
    tracker.process(TPV(mode=MODE_NO_FIX))
    tracker.process(TPV(mode=MODE_2D, lat=54.6873, lon=25.2798))

    assert [title for title, _ in notifier.sent] == ["GPS fix lost", "GPS fix regained"]


def test_device_disconnect_triggers_notification():
    notifier = FakeNotifier()
    tracker = FixTracker(notifier)

    tracker.process(DeviceEvent(path="/dev/ttyACM0", activated=True))
    tracker.process(DeviceEvent(path="/dev/ttyACM0", activated=False))

    assert len(notifier.sent) == 1
    assert notifier.sent[0][0] == "GPS device disconnected"


def test_device_reconnect_triggers_notification():
    notifier = FakeNotifier()
    tracker = FixTracker(notifier)

    tracker.process(DeviceEvent(path="/dev/ttyACM0", activated=True))  # initial connect -- no notification
    tracker.process(DeviceEvent(path="/dev/ttyACM0", activated=False))  # disconnect
    tracker.process(DeviceEvent(path="/dev/ttyACM0", activated=True))  # reconnect

    assert [title for title, _ in notifier.sent] == ["GPS device disconnected", "GPS device connected"]


def test_device_disconnect_does_not_notify_without_prior_connection():
    notifier = FakeNotifier()
    tracker = FixTracker(notifier)

    # First-ever DEVICE report already shows deactivated -- nothing to compare against.
    tracker.process(DeviceEvent(path="/dev/ttyACM0", activated=False))

    assert notifier.sent == []


def test_stale_timeout_triggers_notification_once():
    notifier = FakeNotifier()
    tracker = FixTracker(notifier)

    tracker.process(StaleTimeout())
    tracker.process(StaleTimeout())
    tracker.process(StaleTimeout())

    assert len(notifier.sent) == 1
    assert notifier.sent[0][0] == "GPS data stopped"


def test_stale_timeout_notifies_again_after_recovering():
    notifier = FakeNotifier()
    tracker = FixTracker(notifier)

    tracker.process(StaleTimeout())
    tracker.process(TPV(mode=MODE_2D, lat=54.6872, lon=25.2797))  # data resumes
    tracker.process(StaleTimeout())

    assert [title for title, _ in notifier.sent] == ["GPS data stopped", "GPS data stopped"]
