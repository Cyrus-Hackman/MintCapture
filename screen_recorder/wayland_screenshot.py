"""Screenshot portal client for Wayland sessions."""

from __future__ import annotations

import uuid
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, QUrl, SLOT, Signal, Slot
from PySide6.QtDBus import (
    QDBusConnection, QDBusInterface, QDBusMessage, QDBusPendingCallWatcher,
)
from PySide6.QtGui import QImage, QPixmap

from .capture import CaptureError, save_screenshot_pixmap


PORTAL_SERVICE = "org.freedesktop.portal.Desktop"
PORTAL_PATH = "/org/freedesktop/portal/desktop"
SCREENSHOT_INTERFACE = "org.freedesktop.portal.Screenshot"
REQUEST_INTERFACE = "org.freedesktop.portal.Request"


class PortalScreenshotError(CaptureError):
    pass


def parse_portal_response(response: int, results: dict[str, object]) -> str:
    if response == 1:
        raise PortalScreenshotError("Screenshot was cancelled in the desktop portal.")
    if response == 2:
        raise PortalScreenshotError("The desktop portal denied the screenshot request.")
    if response != 0:
        raise PortalScreenshotError(f"Screenshot portal returned unknown response code {response}.")
    uri = results.get("uri")
    if not isinstance(uri, str) or not uri:
        raise PortalScreenshotError("The screenshot portal returned no image URI.")
    return uri


def portal_request_path(sender: str, token: str) -> str:
    sender_component = sender.removeprefix(":").replace(".", "_")
    return f"{PORTAL_PATH}/request/{sender_component}/{token}"


def save_portal_screenshot(
    uri: str,
    directory: Path,
    image_format: str,
) -> Path:
    source = QUrl(uri).toLocalFile()
    if not source:
        raise PortalScreenshotError("The screenshot portal returned an invalid local file URI.")
    image = QImage(source)
    if image.isNull():
        raise PortalScreenshotError(f"Could not load the screenshot returned by the desktop portal: {source}")
    return save_screenshot_pixmap(QPixmap.fromImage(image), directory, image_format)


class PortalScreenshotRequest(QObject):
    completed = Signal(str)
    failed = Signal(str)

    def __init__(self, parent: QObject | None = None, interactive: bool = False) -> None:
        super().__init__(parent)
        self._finished = False
        self.connection = QDBusConnection.sessionBus()
        self.interface = QDBusInterface(
            PORTAL_SERVICE,
            PORTAL_PATH,
            SCREENSHOT_INTERFACE,
            self.connection,
            self,
        )
        if not self.interface.isValid():
            QTimer.singleShot(0, lambda: self.failed.emit("The desktop screenshot portal is unavailable."))
            return
        token = f"mintcapture_{uuid.uuid4().hex}"
        self._request_path = portal_request_path(self.connection.baseService(), token)
        connected = self.connection.connect(
            PORTAL_SERVICE,
            self._request_path,
            REQUEST_INTERFACE,
            "Response",
            self,
            SLOT("_response(uint,QVariantMap)"),
        )
        if not connected:
            self.failed.emit("Could not listen for the desktop portal screenshot response.")
            return
        self._timeout = QTimer(self)
        self._timeout.setSingleShot(True)
        self._timeout.timeout.connect(self._request_timeout)
        self._timeout.start(120_000)
        pending = self.interface.asyncCall(
            "Screenshot", "", {"interactive": interactive, "handle_token": token}
        )
        self._watcher = QDBusPendingCallWatcher(pending, self)
        self._watcher.finished.connect(self._request_created)

    @Slot(object)
    def _request_created(self, watcher: QDBusPendingCallWatcher) -> None:
        watcher.deleteLater()
        if self._finished:
            return
        reply: QDBusMessage = watcher.reply()
        if reply.type() == QDBusMessage.MessageType.ErrorMessage or not reply.arguments():
            detail = reply.errorMessage() or "The screenshot portal did not create a request."
            self._finish_request()
            self.failed.emit(detail)
            return
        argument = reply.arguments()[0]
        returned_path = argument.path() if hasattr(argument, "path") else str(argument)
        if returned_path != self._request_path:
            self._disconnect_response()
            self._request_path = returned_path
            connected = self.connection.connect(
                PORTAL_SERVICE,
                self._request_path,
                REQUEST_INTERFACE,
                "Response",
                self,
                SLOT("_response(uint,QVariantMap)"),
            )
        else:
            connected = True
        if not connected:
            self._finish_request()
            self.failed.emit("Could not listen for the desktop portal screenshot response.")

    @Slot("uint", "QVariantMap")
    def _response(self, response: int, results: dict[str, object]) -> None:
        if self._finished:
            return
        self._finish_request()
        try:
            uri = parse_portal_response(response, results)
        except PortalScreenshotError as exc:
            self.failed.emit(str(exc))
            return
        self.completed.emit(uri)

    @Slot()
    def _request_timeout(self) -> None:
        if self._finished:
            return
        self._finish_request()
        self.failed.emit("The desktop portal did not respond to the screenshot request in time.")

    def _disconnect_response(self) -> None:
        if self._request_path:
            self.connection.disconnect(
                PORTAL_SERVICE,
                self._request_path,
                REQUEST_INTERFACE,
                "Response",
                self,
                SLOT("_response(uint,QVariantMap)"),
            )

    def _finish_request(self) -> None:
        if self._finished:
            return
        self._finished = True
        if hasattr(self, "_timeout"):
            self._timeout.stop()
        self._disconnect_response()
