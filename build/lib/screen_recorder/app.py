"""PySide6 user interface."""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QTimer, Qt, QUrl
from PySide6.QtGui import QAction, QDesktopServices, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog,
    QFormLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMainWindow, QMessageBox, QPushButton, QTabWidget,
    QVBoxLayout, QWidget,
)

from .capture import CaptureError, Recorder, save_screenshot, unique_path
from .library import captures, describe
from .platform_info import detect_platform
from .settings import Settings


class SettingsDialog(QDialog):
    def __init__(self, settings: Settings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle("Settings")
        form = QFormLayout(self)
        self.recordings = QLineEdit(settings.values["recordings_dir"])
        self.screenshots = QLineEdit(settings.values["screenshots_dir"])
        for label, field in (
            ("Recordings folder", self.recordings),
            ("Screenshots folder", self.screenshots),
        ):
            row = QWidget()
            layout = QHBoxLayout(row)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.addWidget(field)
            browse = QPushButton("Browse…")
            browse.clicked.connect(lambda _=False, f=field: self._browse(f))
            layout.addWidget(browse)
            form.addRow(label, row)
        self.format = QComboBox()
        self.format.addItems(["mkv", "mp4", "webm"])
        self.format.setCurrentText(settings.values["format"])
        form.addRow("Video format", self.format)
        self.screenshot_format = QComboBox()
        self.screenshot_format.addItems(["png", "jpg"])
        self.screenshot_format.setCurrentText(settings.values.get("screenshot_format", "png"))
        form.addRow("Screenshot format", self.screenshot_format)
        self.fps = QComboBox()
        self.fps.addItems(["15", "24", "30", "60"])
        self.fps.setCurrentText(str(settings.values["fps"]))
        form.addRow("Frame rate", self.fps)
        self.quality = QComboBox()
        self.quality.addItems(["High", "Medium", "Low"])
        self.quality.setCurrentText(settings.values["quality"])
        form.addRow("Quality", self.quality)
        self.theme = QComboBox()
        self.theme.addItems(["System", "Light", "Dark"])
        self.theme.setCurrentText(settings.values["theme"])
        form.addRow("Theme", self.theme)
        self.audio_source = QComboBox()
        self.audio_source.addItem("No system audio", "")
        for device in detect_platform().audio_devices:
            self.audio_source.addItem(device, device)
        self.audio_source.setCurrentIndex(max(0, self.audio_source.findData(settings.values.get("audio_source", ""))))
        form.addRow("System audio source", self.audio_source)
        self.microphone_source = QComboBox()
        self.microphone_source.addItem("Default microphone", "")
        for device in detect_platform().audio_devices:
            self.microphone_source.addItem(device, device)
        self.microphone_source.setCurrentIndex(max(0, self.microphone_source.findData(settings.values.get("microphone_source", ""))))
        form.addRow("Microphone device", self.microphone_source)
        self.mic = QCheckBox("Record selected microphone input")
        self.mic.setChecked(bool(settings.values["microphone"]))
        form.addRow("Microphone", self.mic)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def _browse(self, field: QLineEdit) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Choose folder", field.text())
        if folder:
            field.setText(folder)

    def accept(self) -> None:
        for key, field in (("recordings_dir", self.recordings), ("screenshots_dir", self.screenshots)):
            path = Path(field.text()).expanduser()
            if not path.is_absolute():
                QMessageBox.warning(self, "Invalid folder", "Save folders must be absolute paths.")
                return
            self.settings.values[key] = str(path)
        self.settings.values.update({
            "format": self.format.currentText(),
            "screenshot_format": self.screenshot_format.currentText(),
            "fps": int(self.fps.currentText()),
            "quality": self.quality.currentText(),
            "theme": self.theme.currentText(),
            "audio_source": self.audio_source.currentData() or "",
            "microphone_source": self.microphone_source.currentData() or "",
            "microphone": self.mic.isChecked(),
        })
        try:
            self.settings.save()
        except OSError as exc:
            QMessageBox.critical(self, "Could not save settings", str(exc))
            return
        super().accept()


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Screen Recorder")
        self.resize(1000, 700)
        self.settings = Settings()
        self.recorder = Recorder()
        self.started_at: datetime | None = None
        self.pause_started_at: datetime | None = None
        self.paused_seconds = 0.0
        self._build_ui()
        self._refresh_library()
        self._set_theme()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._update_timer)
        self._register_shortcuts()
        self.statusBar().showMessage(self._status_text())

    def _build_ui(self) -> None:
        central = QWidget()
        root = QVBoxLayout(central)
        header = QHBoxLayout()
        title = QLabel("Screen Recorder")
        title.setStyleSheet("font-size: 26px; font-weight: 700;")
        header.addWidget(title)
        header.addStretch()
        settings_button = QPushButton("⚙ Settings")
        settings_button.clicked.connect(self._open_settings)
        header.addWidget(settings_button)
        root.addLayout(header)
        self.tabs = QTabWidget()
        root.addWidget(self.tabs)
        dashboard = QWidget()
        layout = QVBoxLayout(dashboard)
        self.platform_label = QLabel(self._status_text())
        self.platform_label.setWordWrap(True)
        layout.addWidget(self.platform_label)
        actions = QHBoxLayout()
        self.record_button = QPushButton("●  Record Screen")
        self.record_button.setMinimumHeight(64)
        self.record_button.setStyleSheet("font-size: 18px; font-weight: 600;")
        self.record_button.clicked.connect(self._toggle_recording)
        self.screenshot_button = QPushButton("▣  Take Screenshot")
        self.screenshot_button.setMinimumHeight(64)
        self.screenshot_button.setStyleSheet("font-size: 18px; font-weight: 600;")
        self.screenshot_button.clicked.connect(self._take_screenshot)
        actions.addWidget(self.record_button)
        actions.addWidget(self.screenshot_button)
        layout.addLayout(actions)
        controls = QHBoxLayout()
        self.pause_button = QPushButton("Pause")
        self.pause_button.setEnabled(False)
        self.pause_button.clicked.connect(self._toggle_pause)
        controls.addWidget(self.pause_button)
        self.timer_label = QLabel("00:00:00")
        self.timer_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.timer_label.setStyleSheet("font-size: 22px; font-weight: 600;")
        controls.addWidget(self.timer_label)
        self.stop_button = QPushButton("Stop")
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self._stop_recording)
        controls.addWidget(self.stop_button)
        layout.addLayout(controls)
        layout.addWidget(QLabel("Recording captures the full X11 desktop. Use Settings to choose format, frame rate, quality, and audio inputs."))
        layout.addWidget(QLabel("Recent captures"))
        self.recent = QListWidget()
        self.recent.itemDoubleClicked.connect(self._open_item)
        layout.addWidget(self.recent, 1)
        self.tabs.addTab(dashboard, "Dashboard")
        library_page = QWidget()
        library_layout = QVBoxLayout(library_page)
        tools = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search captures…")
        self.search.textChanged.connect(self._refresh_library)
        tools.addWidget(self.search)
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self._refresh_library)
        tools.addWidget(refresh)
        library_layout.addLayout(tools)
        self.library = QListWidget()
        self.library.itemDoubleClicked.connect(self._open_item)
        library_layout.addWidget(self.library)
        row = QHBoxLayout()
        for text, callback in (
            ("Open", self._open_selected), ("Show in File Manager", self._reveal_selected),
            ("Rename", self._rename_selected), ("Delete", self._delete_selected),
        ):
            button = QPushButton(text)
            button.clicked.connect(callback)
            row.addWidget(button)
        library_layout.addLayout(row)
        self.tabs.addTab(library_page, "Library")
        self.setCentralWidget(central)
        file_menu = self.menuBar().addMenu("&File")
        settings_action = QAction("Settings…", self)
        settings_action.triggered.connect(self._open_settings)
        file_menu.addAction(settings_action)
        file_menu.addSeparator()
        exit_action = QAction("Quit", self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

    def _status_text(self) -> str:
        platform = detect_platform()
        capture_text = "X11 desktop capture available" if platform.session_type == "x11" else f"{platform.session_type.title()} session: X11 backend unavailable"
        ffmpeg_text = "FFmpeg available" if platform.ffmpeg else "FFmpeg missing (install with: sudo apt install ffmpeg)"
        return f"{capture_text} · {ffmpeg_text}"

    def _set_theme(self) -> None:
        theme = self.settings.values["theme"]
        if theme == "Dark":
            self.setStyleSheet("QWidget { background: #202124; color: #eeeeee; } QPushButton { padding: 8px; } QListWidget, QLineEdit, QComboBox { background: #303134; }")
        elif theme == "Light":
            self.setStyleSheet("QWidget { background: #fafafa; color: #202124; } QPushButton { padding: 8px; }")
        else:
            self.setStyleSheet("")

    def _register_shortcuts(self) -> None:
        for sequence, callback, tip in (
            ("Ctrl+Shift+R", self._toggle_recording, "Start or stop recording"),
            ("Ctrl+Shift+S", self._take_screenshot, "Take screenshot"),
            ("Ctrl+Shift+P", self._toggle_pause, "Pause or resume recording"),
        ):
            shortcut = QShortcut(QKeySequence(sequence), self)
            shortcut.activated.connect(callback)
        self.setToolTip("Shortcuts are available while this window is active. Global shortcuts depend on desktop-environment support.")

    def _open_settings(self) -> None:
        dialog = SettingsDialog(self.settings, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._set_theme()
            self._refresh_library()
            self.statusBar().showMessage(self._status_text())

    def _toggle_recording(self) -> None:
        if self.recorder.running:
            self._stop_recording()
            return
        values = self.settings.values
        ext = values["format"]
        try:
            output = unique_path(
                Path(values["recordings_dir"]).expanduser(),
                ext,
                datetime.now().strftime("recording-%Y%m%d-%H%M%S"),
            )
            self.recorder.start(
                output,
                int(values["fps"]),
                values["quality"],
                values.get("audio_source", ""),
                bool(values["microphone"]),
                values.get("microphone_source", ""),
            )
        except (CaptureError, OSError) as exc:
            QMessageBox.critical(self, "Could not start recording", str(exc))
            return
        self.started_at = datetime.now()
        self.pause_started_at = None
        self.paused_seconds = 0.0
        self.record_button.setText("●  Recording… (Stop)")
        self.pause_button.setEnabled(True)
        self.stop_button.setEnabled(True)
        self.timer.start(500)
        self.statusBar().showMessage(f"Recording to {output}")

    def _toggle_pause(self) -> None:
        if not self.recorder.running:
            return
        try:
            if self.pause_button.text() == "Pause":
                self.recorder.pause()
                self.pause_started_at = datetime.now()
                self.pause_button.setText("Resume")
                self.statusBar().showMessage("Recording paused")
            else:
                self.recorder.resume()
                if self.pause_started_at:
                    self.paused_seconds += (datetime.now() - self.pause_started_at).total_seconds()
                self.pause_started_at = None
                self.pause_button.setText("Pause")
                self.statusBar().showMessage("Recording resumed")
        except CaptureError as exc:
            QMessageBox.warning(self, "Recording control failed", str(exc))

    def _stop_recording(self) -> None:
        if self.recorder.process is None:
            return
        try:
            path = self.recorder.stop()
        except CaptureError as exc:
            QMessageBox.critical(self, "Recording error", str(exc))
            path = None
        self.timer.stop()
        self.started_at = None
        self.pause_started_at = None
        self.paused_seconds = 0.0
        self.timer_label.setText("00:00:00")
        self.record_button.setText("●  Record Screen")
        self.pause_button.setText("Pause")
        self.pause_button.setEnabled(False)
        self.stop_button.setEnabled(False)
        self._refresh_library()
        if path:
            self.statusBar().showMessage(f"Recording saved: {path}")

    def _update_timer(self) -> None:
        if self.started_at:
            paused_now = (datetime.now() - self.pause_started_at).total_seconds() if self.pause_started_at else 0
            seconds = int((datetime.now() - self.started_at).total_seconds() - self.paused_seconds - paused_now)
            self.timer_label.setText(f"{seconds // 3600:02d}:{seconds // 60 % 60:02d}:{seconds % 60:02d}")
        if self.recorder.process and self.recorder.process.poll() is not None:
            self._stop_recording()

    def _take_screenshot(self) -> None:
        try:
            path = save_screenshot(
                Path(self.settings.values["screenshots_dir"]).expanduser(),
                self.settings.values.get("screenshot_format", "png"),
            )
        except (CaptureError, OSError) as exc:
            QMessageBox.critical(self, "Screenshot failed", str(exc))
            return
        preview = QDialog(self)
        preview.setWindowTitle(f"Screenshot saved — {path.name}")
        layout = QVBoxLayout(preview)
        image = QLabel()
        pixmap = QPixmap(str(path))
        image.setPixmap(pixmap.scaled(900, 600, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        layout.addWidget(image)
        layout.addWidget(QLabel(str(path)))
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Open | QDialogButtonBox.StandardButton.Close)
        buttons.button(QDialogButtonBox.StandardButton.Open).clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))))
        buttons.rejected.connect(preview.reject)
        buttons.accepted.connect(preview.accept)
        layout.addWidget(buttons)
        preview.exec()
        self._refresh_library()

    def _refresh_library(self, *_: object) -> None:
        try:
            files = captures([
                Path(self.settings.values["recordings_dir"]).expanduser(),
                Path(self.settings.values["screenshots_dir"]).expanduser(),
            ])
        except OSError as exc:
            self.statusBar().showMessage(f"Could not read capture folders: {exc}")
            files = []
        term = self.search.text().casefold() if hasattr(self, "search") else ""
        entries = [path for path in files if term in path.name.casefold()]
        for listing in (getattr(self, "library", None), getattr(self, "recent", None)):
            if listing is None:
                continue
            listing.clear()
            for path in entries[:100]:
                try:
                    description = describe(path)
                except OSError as exc:
                    self.statusBar().showMessage(f"Could not read capture metadata: {exc}")
                    continue
                item = QListWidgetItem(f"{path.name}    {description}")
                item.setData(Qt.ItemDataRole.UserRole, str(path))
                item.setToolTip(str(path))
                listing.addItem(item)

    def _selected_path(self) -> Path | None:
        item = self.library.currentItem()
        return Path(item.data(Qt.ItemDataRole.UserRole)) if item else None

    def _open_item(self, item: QListWidgetItem) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(item.data(Qt.ItemDataRole.UserRole)))

    def _open_selected(self) -> None:
        path = self._selected_path()
        if path:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def _reveal_selected(self) -> None:
        path = self._selected_path()
        if path:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent)))

    def _rename_selected(self) -> None:
        path = self._selected_path()
        if not path:
            return
        name, ok = QFileDialog.getSaveFileName(self, "Rename capture", str(path.parent / path.name), f"{path.suffix.upper()} (*{path.suffix})")
        if not ok or not name:
            return
        destination = Path(name)
        if destination.exists() and destination != path:
            QMessageBox.warning(self, "Already exists", "A file with that name already exists.")
            return
        try:
            path.rename(destination)
        except OSError as exc:
            QMessageBox.critical(self, "Rename failed", str(exc))
            return
        self._refresh_library()

    def _delete_selected(self) -> None:
        path = self._selected_path()
        if not path:
            return
        answer = QMessageBox.question(self, "Delete capture?", f"Delete {path.name}? This cannot be undone.")
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            path.unlink()
        except OSError as exc:
            QMessageBox.critical(self, "Delete failed", str(exc))
            return
        self._refresh_library()

    def closeEvent(self, event: object) -> None:
        if self.recorder.process is not None:
            answer = QMessageBox.question(self, "Recording active", "Stop the current recording and quit?")
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            try:
                self.recorder.close()
            except CaptureError as exc:
                QMessageBox.warning(self, "Recording stopped with an error", str(exc))
        event.accept()


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Linux Mint Screen Recorder")
    app.setOrganizationName("Screen Recorder")
    try:
        window = MainWindow()
    except (OSError, RuntimeError) as exc:
        QMessageBox.critical(None, "Could not start Screen Recorder", str(exc))
        return 1
    window.show()
    return app.exec()
