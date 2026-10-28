import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, QRect, Signal
from PySide6.QtNetwork import QLocalServer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication, QSystemTrayIcon

from screen_recorder.app import MainWindow, _accept_commands, _send_command, requested_command

APP = QApplication.instance() or QApplication([])


class AppTests(unittest.TestCase):
    def test_cli_command_selection(self):
        self.assertEqual(requested_command([]), "show")
        self.assertEqual(requested_command(["--toggle-record"]), "toggle-record")
        self.assertEqual(requested_command(["--toggle-pause"]), "toggle-pause")
        self.assertEqual(requested_command(["--screenshot"]), "screenshot")
        self.assertEqual(requested_command(["--screenshot-portion"]), "screenshot-portion")
        self.assertEqual(requested_command(["--snip"]), "screenshot-portion")

    def test_single_instance_command_transport(self):
        name = f"mint-recorder-test-{os.getpid()}"
        QLocalServer.removeServer(name)
        server = QLocalServer()
        self.assertTrue(server.listen(name), server.errorString())
        self.addCleanup(server.close)
        self.addCleanup(lambda: QLocalServer.removeServer(name))
        with patch("screen_recorder.app._server_name", return_value=name):
            self.assertTrue(_send_command("toggle-pause"))
        self.assertTrue(server.waitForNewConnection(1000))
        socket = server.nextPendingConnection()
        self.assertIsNotNone(socket)
        self.assertTrue(socket.waitForReadyRead(1000))
        self.assertEqual(bytes(socket.readAll()), b"toggle-pause\n")
        socket.disconnectFromServer()

    def test_single_instance_dispatches_received_command(self):
        class CommandReceiver:
            def __init__(self):
                self.commands = []

            def handle_external_command(self, command):
                self.commands.append(command)

        name = f"mint-recorder-dispatch-{os.getpid()}"
        QLocalServer.removeServer(name)
        server = QLocalServer()
        self.assertTrue(server.listen(name), server.errorString())
        self.addCleanup(server.close)
        self.addCleanup(lambda: QLocalServer.removeServer(name))
        receiver = CommandReceiver()
        server.newConnection.connect(lambda: _accept_commands(server, receiver))
        with patch("screen_recorder.app._server_name", return_value=name):
            self.assertTrue(_send_command("screenshot"))
        server.waitForNewConnection(1000)
        for _ in range(20):
            APP.processEvents()
            if receiver.commands:
                break
        self.assertEqual(receiver.commands, ["screenshot"])

    def test_main_window_skips_unavailable_tray(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch("screen_recorder.settings.QStandardPaths.writableLocation", return_value=directory), \
                patch.object(QSystemTrayIcon, "isSystemTrayAvailable", return_value=False):
            window = MainWindow()
            self.assertIsNone(window.tray_icon)
            self.assertEqual(window.settings.values["minimize_to_tray"], True)
            window.close()

    def test_screenshot_hides_captures_and_restores_window(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch("screen_recorder.settings.QStandardPaths.writableLocation", return_value=directory), \
                patch.object(QSystemTrayIcon, "isSystemTrayAvailable", return_value=False):
            window = MainWindow()
            window.settings.values["screenshots_dir"] = directory
            window.settings.values["screenshot_delay"] = 0
            window.settings.values["hide_window_for_screenshot"] = True
            window.show()
            APP.processEvents()
            self.assertTrue(window.isVisible())
            screenshot_path = Path(directory) / "capture.png"
            ordering = []

            def capture(*_args, **_kwargs):
                ordering.append("capture")
                self.assertTrue(window.isHidden())
                return screenshot_path

            with patch("screen_recorder.app.save_screenshot", side_effect=capture), \
                    patch.object(window, "_show_screenshot_preview", side_effect=lambda _path: ordering.append("preview")), \
                    patch("screen_recorder.app.QTimer.singleShot", side_effect=lambda _ms, callback: callback()):
                window._take_screenshot()
            self.assertEqual(ordering, ["capture", "preview"])
            self.assertTrue(window.isVisible())
            window.close()

    def test_screenshot_copy_option_uses_clipboard(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch("screen_recorder.settings.QStandardPaths.writableLocation", return_value=directory), \
                patch.object(QSystemTrayIcon, "isSystemTrayAvailable", return_value=False):
            window = MainWindow()
            window.settings.values["screenshot_copy_to_clipboard"] = True
            path = Path(directory) / "clip.png"
            path.touch()
            clipboard = Mock()
            with patch.object(QGuiApplication, "clipboard", return_value=clipboard), \
                    patch("PySide6.QtWidgets.QDialog.exec", return_value=0), \
                    patch.object(window, "_refresh_library"):
                window._show_screenshot_preview(path)
            clipboard.setPixmap.assert_called_once()
            window.close()

    def test_cancelled_region_selection_does_not_start_recording(self):
        class FakeSelector(QObject):
            selected = Signal(QRect)
            cancelled = Signal()

            def show(self):
                pass

            def raise_(self):
                pass

            def activateWindow(self):
                pass

        with tempfile.TemporaryDirectory() as directory, \
                patch("screen_recorder.settings.QStandardPaths.writableLocation", return_value=directory), \
                patch.object(QSystemTrayIcon, "isSystemTrayAvailable", return_value=False), \
                patch("screen_recorder.app.RegionSelector", FakeSelector):
            window = MainWindow()
            window.settings.values["capture_mode"] = "Region"
            with patch.object(window.recorder, "start") as start:
                window._toggle_recording()
                self.assertIsNotNone(window._region_selector)
                window._region_selector.cancelled.emit()
                start.assert_not_called()
                self.assertIsNone(window.recorder.output)
            window.close()

    def test_region_controls_are_enabled_only_in_region_mode(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch("screen_recorder.settings.QStandardPaths.writableLocation", return_value=directory), \
                patch.object(QSystemTrayIcon, "isSystemTrayAvailable", return_value=False):
            window = MainWindow()
            self.assertFalse(window.select_area_button.isEnabled())
            window.capture_mode.setCurrentText("Region")
            self.assertTrue(window.select_area_button.isEnabled())
            window._last_region = QRect(100, 200, 1280, 720)
            window._update_region_controls()
            self.assertEqual(window.region_label.text(), "1280x720 at 100,200")
            window.close()

    def test_window_mode_is_disabled_when_xwininfo_is_missing(self):
        platform = type("Platform", (), {"session_type": "x11", "ffmpeg": None, "audio_devices": ()})()
        with tempfile.TemporaryDirectory() as directory, \
                patch("screen_recorder.settings.QStandardPaths.writableLocation", return_value=directory), \
                patch.object(QSystemTrayIcon, "isSystemTrayAvailable", return_value=False), \
                patch("screen_recorder.app.shutil.which", return_value=None), \
                patch("screen_recorder.app.detect_platform", return_value=platform):
            window = MainWindow()
            self.assertFalse(window.capture_mode.model().item(2).isEnabled())
            self.assertFalse(window.window_tool_hint.isHidden())
            self.assertIn("sudo apt install x11-utils", window.window_tool_hint.text())
            window.close()

    def test_window_pick_cancel_does_not_start_capture(self):
        platform = type("Platform", (), {"session_type": "x11", "ffmpeg": None, "audio_devices": ()})()
        with tempfile.TemporaryDirectory() as directory, \
                patch("screen_recorder.settings.QStandardPaths.writableLocation", return_value=directory), \
                patch.object(QSystemTrayIcon, "isSystemTrayAvailable", return_value=False), \
                patch("screen_recorder.app.shutil.which", return_value="/usr/bin/xwininfo"), \
                patch("screen_recorder.app.detect_platform", return_value=platform):
            window = MainWindow()
            window.settings.values["capture_mode"] = "Window"
            window._window_picker = Mock()
            window._window_picker.readAllStandardOutput.return_value = b"No window selected"
            callback = Mock()
            window._window_pick_callback = callback
            with patch.object(window.recorder, "start") as start:
                window._window_pick_finished(1, None)
                start.assert_not_called()
                callback.assert_not_called()
            window.close()
            window._library_workers.waitForDone()

    def test_portion_screenshot_hides_window_opens_selector_and_saves(self):
        class FakeSelector(QObject):
            selected = Signal(QRect)
            cancelled = Signal()

            def show(self):
                pass

            def raise_(self):
                pass

            def activateWindow(self):
                pass

        with tempfile.TemporaryDirectory() as directory, \
                patch("screen_recorder.settings.QStandardPaths.writableLocation", return_value=directory), \
                patch.object(QSystemTrayIcon, "isSystemTrayAvailable", return_value=False), \
                patch("screen_recorder.app.RegionSelector", FakeSelector):
            window = MainWindow()
            window.settings.values["screenshots_dir"] = directory
            window.settings.values["screenshot_delay"] = 0
            window.settings.values["hide_window_for_screenshot"] = True
            window.show()
            APP.processEvents()
            self.assertTrue(window.isVisible())

            screenshot_path = Path(directory) / "portion.png"
            captured_kwargs = {}

            def fake_save(*args, **kwargs):
                captured_kwargs.update(kwargs)
                return screenshot_path

            with patch("screen_recorder.app.save_screenshot", side_effect=fake_save), \
                    patch.object(window, "_show_screenshot_preview") as mock_preview, \
                    patch("screen_recorder.app.QTimer.singleShot", side_effect=lambda _ms, callback: callback()):
                window._take_portion_screenshot()
                self.assertIsNotNone(window._region_selector)
                window._region_selector.selected.emit(QRect(50, 60, 300, 200))

            self.assertEqual(captured_kwargs.get("region"), QRect(50, 60, 300, 200))
            mock_preview.assert_called_once_with(screenshot_path)
            self.assertTrue(window.isVisible())
            window.close()
            window._library_workers.waitForDone()

    def test_portion_screenshot_cancel_restores_window(self):
        class FakeSelector(QObject):
            selected = Signal(QRect)
            cancelled = Signal()

            def show(self):
                pass

            def raise_(self):
                pass

            def activateWindow(self):
                pass

        with tempfile.TemporaryDirectory() as directory, \
                patch("screen_recorder.settings.QStandardPaths.writableLocation", return_value=directory), \
                patch.object(QSystemTrayIcon, "isSystemTrayAvailable", return_value=False), \
                patch("screen_recorder.app.RegionSelector", FakeSelector):
            window = MainWindow()
            window.settings.values["hide_window_for_screenshot"] = True
            window.show()
            APP.processEvents()
            self.assertTrue(window.isVisible())

            with patch("screen_recorder.app.QTimer.singleShot", side_effect=lambda _ms, callback: callback()):
                window._take_portion_screenshot()
                self.assertIsNotNone(window._region_selector)
                window._region_selector.cancelled.emit()

            self.assertIsNone(window._region_selector)
            self.assertTrue(window.isVisible())
            window.close()
            window._library_workers.waitForDone()

    def test_screenshot_target_selected_portion_invokes_portion_screenshot(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch("screen_recorder.settings.QStandardPaths.writableLocation", return_value=directory), \
                patch.object(QSystemTrayIcon, "isSystemTrayAvailable", return_value=False):
            window = MainWindow()
            window.settings.values["screenshot_target"] = "Selected portion"
            with patch.object(window, "_take_portion_screenshot") as mock_portion:
                window._take_screenshot()
                mock_portion.assert_called_once()
            window.close()
            window._library_workers.waitForDone()


if __name__ == "__main__":
    unittest.main()
