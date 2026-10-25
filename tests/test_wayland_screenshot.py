import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication

from screen_recorder.wayland_screenshot import (
    PortalScreenshotError, PortalScreenshotRequest, parse_portal_response,
    save_portal_screenshot,
)

APP = QApplication.instance() or QApplication([])


class SignalStub:
    def __init__(self):
        self.callback = None

    def connect(self, callback):
        self.callback = callback

    def emit(self, *args):
        if self.callback:
            self.callback(*args)


class PendingWatcher:
    def __init__(self, *_args):
        self.finished = SignalStub()


class PortalTests(unittest.TestCase):
    def test_success_response_returns_screenshot_uri(self):
        uri = "file:///tmp/portal-shot.png"
        self.assertEqual(parse_portal_response(0, {"uri": uri}), uri)

    def test_invalid_and_denied_portal_responses_are_actionable(self):
        with self.assertRaisesRegex(PortalScreenshotError, "cancelled"):
            parse_portal_response(1, {})
        with self.assertRaisesRegex(PortalScreenshotError, "denied"):
            parse_portal_response(2, {})
        with self.assertRaisesRegex(PortalScreenshotError, "no image URI"):
            parse_portal_response(0, {})

    def test_cancelled_response_signal_from_mocked_dbus(self):
        connection = Mock()
        interface = Mock()
        interface.isValid.return_value = True
        interface.asyncCall.return_value = object()
        with patch("screen_recorder.wayland_screenshot.QDBusConnection.sessionBus", return_value=connection), \
                patch("screen_recorder.wayland_screenshot.QDBusInterface", return_value=interface), \
                patch("screen_recorder.wayland_screenshot.QDBusPendingCallWatcher", PendingWatcher):
            request = PortalScreenshotRequest()
            failures = []
            request.failed.connect(failures.append)
            request._request_path = "/org/freedesktop/portal/desktop/request/1"
            request._response(1, {})
            self.assertEqual(failures, ["Screenshot was cancelled in the desktop portal."])
            connection.disconnect.assert_called_once()

    def test_portal_image_is_saved_through_local_screenshot_pipeline(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "portal.png"
            image = QImage(20, 10, QImage.Format.Format_RGB32)
            image.fill(QColor("blue"))
            self.assertTrue(image.save(str(source)))
            output = save_portal_screenshot(source.as_uri(), Path(directory) / "saved", "jpg")
            self.assertEqual(output.suffix, ".jpg")
            self.assertTrue(output.is_file())
            self.assertGreater(output.stat().st_size, 0)


if __name__ == "__main__":
    unittest.main()
