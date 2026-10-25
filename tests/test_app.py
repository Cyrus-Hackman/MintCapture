import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtNetwork import QLocalServer
from PySide6.QtWidgets import QApplication, QSystemTrayIcon

from screen_recorder.app import MainWindow, _accept_commands, _send_command, requested_command

APP = QApplication.instance() or QApplication([])


class AppTests(unittest.TestCase):
    def test_cli_command_selection(self):
        self.assertEqual(requested_command([]), "show")
        self.assertEqual(requested_command(["--toggle-record"]), "toggle-record")
        self.assertEqual(requested_command(["--toggle-pause"]), "toggle-pause")
        self.assertEqual(requested_command(["--screenshot"]), "screenshot")

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


if __name__ == "__main__":
    unittest.main()
