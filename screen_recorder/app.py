"""PySide6 user interface."""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QFile, QProcess, QRect, QThreadPool, QTimer, Qt, QUrl
from PySide6.QtGui import QAction, QDesktopServices, QGuiApplication, QIcon, QKeySequence, QPixmap, QShortcut
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog,
    QFormLayout, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget, QMenu,
    QListWidgetItem, QMainWindow, QMessageBox, QPushButton, QTabWidget,
    QSystemTrayIcon, QVBoxLayout, QWidget,
)

from .capture import (
    CaptureError, Recorder, find_orphaned_recordings, recover_orphaned_recording,
    save_screenshot, unique_path,
)
from .annotate import AnnotationEditor
from .library import (
    CachePruneWorker, LibraryWorker, LibraryWorkerSignals, cached_thumbnail,
    captures, describe, icon_for_path, video_duration,
)
from .platform_info import detect_platform
from .processing_dialog import ProcessingDialog
from .region import RegionSelector
from .settings import Settings
from .window_capture import parse_xwininfo_geometry
from .wayland_screenshot import PortalScreenshotRequest, save_portal_screenshot


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
        self.show_cursor = QCheckBox("Show mouse cursor in recordings")
        self.show_cursor.setChecked(bool(settings.values["show_cursor"]))
        form.addRow("Mouse cursor", self.show_cursor)
        self.minimize_to_tray = QCheckBox("Minimize to tray while recording")
        self.minimize_to_tray.setChecked(bool(settings.values["minimize_to_tray"]))
        form.addRow("Recording behavior", self.minimize_to_tray)
        self.screenshot_delay = QComboBox()
        self.screenshot_delay.addItems(["0", "3", "5", "10"])
        self.screenshot_delay.setCurrentText(str(settings.values["screenshot_delay"]))
        form.addRow("Screenshot delay (seconds)", self.screenshot_delay)
        self.hide_window_for_screenshot = QCheckBox("Hide window before screenshot")
        self.hide_window_for_screenshot.setChecked(bool(settings.values["hide_window_for_screenshot"]))
        form.addRow("Screenshot behavior", self.hide_window_for_screenshot)
        self.screenshot_copy_to_clipboard = QCheckBox("Copy screenshot to clipboard")
        self.screenshot_copy_to_clipboard.setChecked(bool(settings.values["screenshot_copy_to_clipboard"]))
        form.addRow("Clipboard", self.screenshot_copy_to_clipboard)
        self.screenshot_target = QComboBox()
        self.screenshot_target.addItems([
            "Primary screen",
            "All screens",
            "Screen under cursor",
            "Selected portion",
        ])
        self.screenshot_target.setCurrentText(settings.values["screenshot_target"])
        form.addRow("Screenshot target", self.screenshot_target)
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
            "show_cursor": self.show_cursor.isChecked(),
            "minimize_to_tray": self.minimize_to_tray.isChecked(),
            "screenshot_delay": int(self.screenshot_delay.currentText()),
            "hide_window_for_screenshot": self.hide_window_for_screenshot.isChecked(),
            "screenshot_copy_to_clipboard": self.screenshot_copy_to_clipboard.isChecked(),
            "screenshot_target": self.screenshot_target.currentText(),
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
        self._screenshot_restore_window = False
        self._screenshot_seconds_remaining = 0
        self._last_region: QRect | None = None
        self._last_region_physical = False
        self._region_selector: RegionSelector | None = None
        self._window_picker: QProcess | None = None
        self._portal_request: PortalScreenshotRequest | None = None
        self._window_pick_callback: Callable[[QRect], None] | None = None
        self._xwininfo = shutil.which("xwininfo")
        self._window_mode_available = bool(
            self._xwininfo and detect_platform().session_type == "x11"
        )
        self._screenshot_countdown_timer = QTimer(self)
        self._screenshot_countdown_timer.setInterval(1000)
        self._screenshot_countdown_timer.timeout.connect(self._update_screenshot_countdown)
        self._library_files: list[Path] = []
        self._library_workers = QThreadPool(self)
        self._library_jobs: set[str] = set()
        self._library_worker_signals: dict[str, LibraryWorkerSignals] = {}
        self._library_workers.start(CachePruneWorker())
        self._build_ui()
        self._refresh_library()
        self._library_directory_timer = QTimer(self)
        self._library_directory_timer.setInterval(2500)
        self._library_directory_timer.timeout.connect(self._check_library_directories)
        self._library_directory_timer.start()
        self.tabs.currentChanged.connect(self._check_library_directories)
        self._set_theme()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._update_timer)
        self._register_shortcuts()
        self.statusBar().showMessage(self._status_text())
        if self.settings.recovered_from:
            self.statusBar().showMessage(self.settings.recovered_from, 10000)
        self._create_tray_icon()

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
        capture_mode_row = QHBoxLayout()
        capture_mode_row.addWidget(QLabel("Capture area"))
        self.capture_mode = QComboBox()
        self.capture_mode.addItems(["Full screen", "Region", "Window"])
        if not self._window_mode_available:
            window_item = self.capture_mode.model().item(2)
            window_item.setEnabled(False)
            window_item.setToolTip(
                "Window capture requires an X11 session and xwininfo. "
                "Install x11-utils with: sudo apt install x11-utils"
            )
        capture_mode = self.settings.values["capture_mode"]
        if capture_mode == "Window" and not self._window_mode_available:
            capture_mode = "Full screen"
            self.settings.values["capture_mode"] = capture_mode
        self.capture_mode.setCurrentText(capture_mode)
        self.capture_mode.currentTextChanged.connect(self._change_capture_mode)
        capture_mode_row.addWidget(self.capture_mode)
        self.select_area_button = QPushButton("Select area…")
        self.select_area_button.clicked.connect(self._select_capture_target)
        capture_mode_row.addWidget(self.select_area_button)
        self.region_label = QLabel("No area selected")
        capture_mode_row.addWidget(self.region_label)
        self._update_region_controls()
        capture_mode_row.addStretch()
        layout.addLayout(capture_mode_row)
        actions = QHBoxLayout()
        self.record_button = QPushButton("●  Record Screen")
        self.record_button.setMinimumHeight(64)
        self.record_button.setStyleSheet("font-size: 18px; font-weight: 600;")
        self.record_button.clicked.connect(self._toggle_recording)
        self.screenshot_button = QPushButton("▣  Take Screenshot")
        self.screenshot_button.setMinimumHeight(64)
        self.screenshot_button.setStyleSheet("font-size: 18px; font-weight: 600;")
        self.screenshot_button.setToolTip("Take a screenshot of the configured target (Ctrl+Shift+S)")
        self.screenshot_button.clicked.connect(self._take_screenshot)
        self.portion_screenshot_button = QPushButton("⬚  Select Portion")
        self.portion_screenshot_button.setMinimumHeight(64)
        self.portion_screenshot_button.setStyleSheet("font-size: 18px; font-weight: 600;")
        self.portion_screenshot_button.setToolTip("Select a portion of the screen to screenshot (Ctrl+Shift+A)")
        self.portion_screenshot_button.clicked.connect(self._take_portion_screenshot)
        actions.addWidget(self.record_button)
        actions.addWidget(self.screenshot_button)
        actions.addWidget(self.portion_screenshot_button)
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
        layout.addWidget(QLabel("Choose Full screen or Region above. Use Settings to choose format, frame rate, quality, and audio inputs."))
        self.window_capture_note = QLabel(
            "Window recording follows the selected screen area; it will not track the window if it moves."
        )
        self.window_capture_note.setWordWrap(True)
        self.window_capture_note.setVisible(self.settings.values["capture_mode"] == "Window")
        layout.addWidget(self.window_capture_note)
        self.window_tool_hint = QLabel(
            "X11 window selection is unavailable. Install x11-utils with: sudo apt install x11-utils"
        )
        self.window_tool_hint.setWordWrap(True)
        self.window_tool_hint.setVisible(not self._window_mode_available)
        layout.addWidget(self.window_tool_hint)
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
        self.search.textChanged.connect(self._filter_library_cache)
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
            ("Process…", self._process_selected),
            ("Annotate", self._annotate_selected),
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
            ("Ctrl+Shift+A", self._take_portion_screenshot, "Select a portion to screenshot"),
            ("Ctrl+Shift+P", self._toggle_pause, "Pause or resume recording"),
        ):
            shortcut = QShortcut(QKeySequence(sequence), self)
            shortcut.activated.connect(callback)
        self.setToolTip("Shortcuts are available while this window is active. Global shortcuts depend on desktop-environment support.")

    def _create_tray_icon(self) -> None:
        self.tray_icon: QSystemTrayIcon | None = None
        self.tray_actions: dict[str, QAction] = {}
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        icon_candidates = (
            Path(__file__).parent.parent / "assets" / "linux-mint-screen-recorder.svg",
            Path("/usr/share/icons/hicolor/scalable/apps/linux-mint-screen-recorder.svg"),
        )
        icon_path = next((candidate for candidate in icon_candidates if candidate.is_file()), None)
        icon = QIcon(str(icon_path)) if icon_path else QIcon.fromTheme("video-display")
        self.tray_icon = QSystemTrayIcon(icon, self)
        menu = QMenu(self)
        self.tray_actions["record"] = menu.addAction("Start Recording")
        self.tray_actions["record"].triggered.connect(self._toggle_recording)
        self.tray_actions["pause"] = menu.addAction("Pause Recording")
        self.tray_actions["pause"].triggered.connect(self._toggle_pause)
        menu.addSeparator()
        screenshot_action = menu.addAction("Take Screenshot")
        screenshot_action.triggered.connect(self._take_screenshot)
        portion_screenshot_action = menu.addAction("Take Portion Screenshot…")
        portion_screenshot_action.triggered.connect(self._take_portion_screenshot)
        region_action = menu.addAction("Reselect Region")
        region_action.triggered.connect(self._reselect_region)
        self.tray_actions["region"] = region_action
        show_action = menu.addAction("Show Window")
        show_action.triggered.connect(self._restore_window)
        quit_action = menu.addAction("Quit")
        quit_action.triggered.connect(self.close)
        self.tray_icon.setContextMenu(menu)
        self.tray_icon.activated.connect(self._tray_activated)
        self.tray_icon.show()
        self._update_tray_state()

    def _tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            self._restore_window()

    def _restore_window(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _change_capture_mode(self, mode: str) -> None:
        self.settings.values["capture_mode"] = mode
        self._update_region_controls()
        try:
            self.settings.save()
        except OSError as exc:
            QMessageBox.critical(self, "Could not save settings", str(exc))
            self.settings.values["capture_mode"] = "Full screen"
            self.capture_mode.setCurrentText("Full screen")

    def _update_region_controls(self) -> None:
        mode = self.settings.values["capture_mode"]
        is_region = mode == "Region"
        if hasattr(self, "select_area_button"):
            self.select_area_button.setText("Select window…" if mode == "Window" else "Select area…")
            self.select_area_button.setEnabled(is_region or (mode == "Window" and self._window_mode_available))
        if hasattr(self, "region_label"):
            if self._last_region is not None:
                rect = self._last_region
                self.region_label.setText(f"{rect.width()}x{rect.height()} at {rect.x()},{rect.y()}")
            else:
                self.region_label.setText("No area selected")
        if hasattr(self, "window_capture_note"):
            self.window_capture_note.setVisible(mode == "Window")

    def _select_region(self, callback: Callable[[QRect], None]) -> None:
        if self._region_selector is not None:
            return
        selector = RegionSelector()
        self._region_selector = selector

        def selected(region: QRect) -> None:
            self._last_region = region
            self._last_region_physical = False
            self._region_selector = None
            self._update_region_controls()
            callback(region)

        def cancelled() -> None:
            self._region_selector = None
            self.statusBar().showMessage("Region selection cancelled")

        selector.selected.connect(selected)
        selector.cancelled.connect(cancelled)
        selector.show()
        selector.raise_()
        selector.activateWindow()

    def _select_capture_target(self) -> None:
        if self.settings.values["capture_mode"] == "Window":
            self._pick_window(self._remember_window)
        else:
            self._select_region(lambda _region: None)

    def _remember_window(self, rect: QRect) -> None:
        self._last_region = rect
        self._last_region_physical = True
        self._update_region_controls()

    def _pick_window(self, callback: Callable[[QRect], None]) -> None:
        if not self._window_mode_available or not self._xwininfo:
            self.statusBar().showMessage(
                "Window selection requires X11 and x11-utils. Install with: sudo apt install x11-utils"
            )
            return
        if self._window_picker is not None:
            return
        process = QProcess(self)
        process.setProcessChannelMode(QProcess.ProcessChannelMode.SeparateChannels)
        process.finished.connect(self._window_pick_finished)
        process.errorOccurred.connect(self._window_pick_error)
        self._window_picker = process
        self._window_pick_callback = callback
        self.statusBar().showMessage("Click a window to select its frame. Press Escape to cancel.")
        process.start(self._xwininfo, ["-frame"])

    def _window_pick_finished(self, exit_code: int, _status: QProcess.ExitStatus) -> None:
        process = self._window_picker
        self._window_picker = None
        callback = self._window_pick_callback
        self._window_pick_callback = None
        output = bytes(process.readAllStandardOutput()).decode(errors="replace") if process else ""
        if exit_code != 0:
            self.statusBar().showMessage("Window selection cancelled")
            return
        rect = parse_xwininfo_geometry(output)
        if rect is None:
            self.statusBar().showMessage("Window selection returned no valid geometry; cancelled")
            return
        self._last_region = rect
        self._last_region_physical = True
        self._update_region_controls()
        if callback:
            callback(rect)

    def _window_pick_error(self, _error: QProcess.ProcessError) -> None:
        process = self._window_picker
        self._window_picker = None
        self._window_pick_callback = None
        detail = process.errorString() if process else "xwininfo failed to start"
        self.statusBar().showMessage(f"Window selection failed: {detail}")

    def _reselect_region(self) -> None:
        self._select_capture_target()

    def _update_tray_state(self) -> None:
        if self.tray_icon is None:
            return
        recording = self.recorder.output is not None
        paused = recording and self.recorder.paused
        self.tray_actions["record"].setText("Stop Recording" if recording else "Start Recording")
        self.tray_actions["pause"].setText("Resume Recording" if paused else "Pause Recording")
        self.tray_actions["pause"].setEnabled(recording)
        self.tray_icon.setToolTip(
            "Screen Recorder — recording paused" if paused else
            "Screen Recorder — recording" if recording else "Screen Recorder"
        )

    def handle_external_command(self, command: str) -> None:
        if command == "toggle-record":
            self._toggle_recording()
        elif command == "toggle-pause":
            self._toggle_pause()
        elif command == "screenshot":
            self._take_screenshot()
        elif command in ("screenshot-portion", "snip"):
            self._take_portion_screenshot()
        elif command == "show":
            self._restore_window()

    def offer_orphan_recovery(self) -> None:
        directory = Path(self.settings.values["recordings_dir"]).expanduser()
        try:
            orphaned = find_orphaned_recordings(directory)
        except OSError as exc:
            self.statusBar().showMessage(f"Could not scan for interrupted recordings: {exc}")
            return
        if orphaned:
            self._offer_orphan_recovery(orphaned, 0)

    def _offer_orphan_recovery(self, orphaned: list[Path], index: int) -> None:
        if index >= len(orphaned):
            return
        segment_dir = orphaned[index]
        dialog = QMessageBox(self)
        dialog.setWindowTitle("Interrupted recording found")
        dialog.setText(f"An unfinished recording was found:\n{segment_dir.name}")
        dialog.setInformativeText("Recover it, delete the temporary segments, or decide later.")
        recover_button = dialog.addButton("Recover", QMessageBox.ButtonRole.AcceptRole)
        delete_button = dialog.addButton("Delete", QMessageBox.ButtonRole.DestructiveRole)
        later_button = dialog.addButton("Later", QMessageBox.ButtonRole.RejectRole)
        dialog.setDefaultButton(recover_button)

        def handle_choice(button: object) -> None:
            if button == recover_button:
                try:
                    discarded_segments = {
                        path.name for path in segment_dir.glob("segment-*.mkv")
                    }
                    output = recover_orphaned_recording(
                        segment_dir,
                        Path(self.settings.values["recordings_dir"]).expanduser(),
                        self.settings.values["format"],
                        self.settings.values["quality"],
                    )
                    recovery_message = f"Recovered recording: {output}"
                    discarded = next(
                        (
                            candidate
                            for candidate in output.parent.glob(f"{output.stem}*.discarded")
                            if candidate.is_dir()
                            and any(
                                child.name in discarded_segments
                                for child in candidate.iterdir()
                            )
                        ),
                        None,
                    )
                    if discarded is not None:
                        recovery_message += f" (corrupt trailing segment preserved in {discarded})"
                    self.statusBar().showMessage(recovery_message)
                    self._refresh_library()
                except (CaptureError, OSError) as exc:
                    QMessageBox.critical(self, "Recovery failed", str(exc))
            elif button == delete_button:
                confirmation = QMessageBox.question(
                    self,
                    "Delete interrupted recording?",
                    f"Permanently delete temporary segments in {segment_dir}?",
                )
                if confirmation == QMessageBox.StandardButton.Yes:
                    try:
                        shutil.rmtree(segment_dir)
                    except OSError as exc:
                        QMessageBox.critical(self, "Delete failed", str(exc))
            if button != later_button:
                QTimer.singleShot(0, lambda: self._offer_orphan_recovery(orphaned, index + 1))

        dialog.buttonClicked.connect(handle_choice)
        dialog.open()

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
        mode = self.settings.values["capture_mode"]
        if mode in {"Region", "Window"}:
            if self._last_region is not None:
                self._start_recording(self._last_region, self._last_region_physical)
            elif mode == "Window":
                self._pick_window(lambda rect: self._start_recording(rect, physical=True))
            else:
                self._select_region(lambda rect: self._start_recording(rect, physical=False))
            return
        self._start_recording(None)

    def _start_recording(self, region: QRect | None, physical: bool = False) -> None:
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
                bool(values["show_cursor"]),
                region=region,
                physical=physical,
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
        self._update_tray_state()
        if self.tray_icon is not None and self.settings.values["minimize_to_tray"]:
            self.hide()

    def _toggle_pause(self) -> None:
        if not self.recorder.running:
            return
        try:
            if not self.recorder.paused:
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
            self._update_tray_state()
        except CaptureError as exc:
            QMessageBox.warning(self, "Recording control failed", str(exc))
            self._update_tray_state()

    def _stop_recording(self) -> None:
        if self.recorder.output is None:
            return
        try:
            path = self.recorder.stop()
        except CaptureError as exc:
            QMessageBox.critical(self, "Recording error", str(exc))
            if self.recorder.output is not None:
                self.timer.stop()
                self.statusBar().showMessage("Recording segments were preserved; retry stop to finalize.")
                self._update_tray_state()
                return
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
            self._restore_window()
        self._update_tray_state()

    def _update_timer(self) -> None:
        if self.started_at:
            paused_now = (datetime.now() - self.pause_started_at).total_seconds() if self.pause_started_at else 0
            seconds = int((datetime.now() - self.started_at).total_seconds() - self.paused_seconds - paused_now)
            self.timer_label.setText(f"{seconds // 3600:02d}:{seconds // 60 % 60:02d}:{seconds % 60:02d}")
        if self.recorder.process and self.recorder.process.poll() is not None:
            self._stop_recording()

    def _take_screenshot(self) -> None:
        if self.settings.values.get("screenshot_target") == "Selected portion":
            self._take_portion_screenshot()
            return
        if detect_platform().session_type == "wayland":
            self.statusBar().showMessage(
                "Wayland portal screenshots capture the desktop; monitor and region selection are not applied."
            )
            self._schedule_screenshot(None)
            return
        mode = self.settings.values["capture_mode"]
        if mode == "Window":
            if self._last_region is not None:
                self._schedule_screenshot(self._last_region, physical=True)
            else:
                self._pick_window(lambda rect: self._schedule_screenshot(rect, physical=True))
            return
        if mode == "Region":
            if self._last_region is None:
                self._take_portion_screenshot()
            else:
                self._schedule_screenshot(self._last_region)
            return
        self._schedule_screenshot(None)

    def _take_portion_screenshot(self) -> None:
        if detect_platform().session_type == "wayland":
            self._start_portal_screenshot(interactive=True)
            return
        if self._region_selector is not None:
            return
        settings = self.settings.values
        should_hide = self.isVisible() and bool(settings.get("hide_window_for_screenshot", True))
        self._screenshot_restore_window = should_hide
        if should_hide:
            self.hide()
            QTimer.singleShot(200, self._open_portion_selector)
        else:
            self._open_portion_selector()

    def _open_portion_selector(self) -> None:
        if self._region_selector is not None:
            return
        selector = RegionSelector()
        self._region_selector = selector

        def on_selected(rect: QRect) -> None:
            self._region_selector = None
            self._last_region = rect
            self._last_region_physical = False
            self._update_region_controls()
            delay = int(self.settings.values.get("screenshot_delay", 0))
            if delay > 0:
                self._screenshot_region = rect
                self._screenshot_region_physical = False
                self._screenshot_seconds_remaining = delay
                self.statusBar().showMessage(f"Screenshot in {delay} seconds…")
                self._screenshot_countdown_timer.start()
                QTimer.singleShot(delay * 1000, self._capture_screenshot_now)
            else:
                self._screenshot_region = rect
                self._screenshot_region_physical = False
                QTimer.singleShot(150, self._capture_screenshot_now)

        def on_cancelled() -> None:
            self._region_selector = None
            if self._screenshot_restore_window:
                self._restore_window()
            self._screenshot_restore_window = False
            self.statusBar().showMessage("Portion screenshot cancelled.")

        selector.selected.connect(on_selected)
        selector.cancelled.connect(on_cancelled)
        selector.show()
        selector.raise_()
        selector.activateWindow()

    def _start_portal_screenshot(self, interactive: bool = False) -> None:
        self.statusBar().showMessage(
            "Select a portion or window in the desktop portal…"
            if interactive else
            "Requesting a screenshot from the desktop portal…"
        )
        request = PortalScreenshotRequest(self, interactive=interactive)
        self._portal_request = request
        request.completed.connect(self._portal_screenshot_completed)
        request.failed.connect(self._portal_screenshot_failed)

    def _schedule_screenshot(self, region: QRect | None, physical: bool = False) -> None:
        self._screenshot_region = region
        self._screenshot_region_physical = physical
        settings = self.settings.values
        self._screenshot_restore_window = (
            self.isVisible() and bool(settings["hide_window_for_screenshot"])
        )
        if self._screenshot_restore_window:
            self.hide()
        delay = int(settings["screenshot_delay"])
        self._screenshot_seconds_remaining = delay
        if delay:
            self.statusBar().showMessage(f"Screenshot in {delay} seconds…")
            self._screenshot_countdown_timer.start()
        wait_ms = delay * 1000 + (250 if self._screenshot_restore_window else 0)
        QTimer.singleShot(wait_ms, self._capture_screenshot_now)

    def _update_screenshot_countdown(self) -> None:
        self._screenshot_seconds_remaining -= 1
        if self._screenshot_seconds_remaining > 0:
            self.statusBar().showMessage(f"Screenshot in {self._screenshot_seconds_remaining} seconds…")
        else:
            self._screenshot_countdown_timer.stop()

    def _capture_screenshot_now(self) -> None:
        self._screenshot_countdown_timer.stop()
        if detect_platform().session_type == "wayland":
            self._start_portal_screenshot(interactive=False)
            return
        region = self._screenshot_region
        region_physical = self._screenshot_region_physical
        self._screenshot_region = None
        self._screenshot_region_physical = False
        try:
            path = save_screenshot(
                Path(self.settings.values["screenshots_dir"]).expanduser(),
                self.settings.values.get("screenshot_format", "png"),
                target=self.settings.values.get("screenshot_target", "Primary screen"),
                region=region,
                region_physical=region_physical,
            )
        except (CaptureError, OSError) as exc:
            QMessageBox.critical(self, "Screenshot failed", str(exc))
            if self._screenshot_restore_window:
                self._restore_window()
            self._screenshot_restore_window = False
            return
        if self._screenshot_restore_window:
            self._restore_window()
        self._screenshot_restore_window = False
        self._show_screenshot_preview(path)

    def _portal_screenshot_completed(self, uri: str) -> None:
        self._portal_request = None
        try:
            path = save_portal_screenshot(
                uri,
                Path(self.settings.values["screenshots_dir"]).expanduser(),
                self.settings.values.get("screenshot_format", "png"),
            )
        except (CaptureError, OSError) as exc:
            self._portal_screenshot_failed(str(exc))
            return
        if self._screenshot_restore_window:
            self._restore_window()
        self._screenshot_restore_window = False
        self._show_screenshot_preview(path)

    def _portal_screenshot_failed(self, message: str) -> None:
        self._portal_request = None
        if self._screenshot_restore_window:
            self._restore_window()
        self._screenshot_restore_window = False
        QMessageBox.warning(self, "Screenshot unavailable", message)

    def _show_screenshot_preview(self, path: Path) -> None:
        if self.settings.values["screenshot_copy_to_clipboard"]:
            QGuiApplication.clipboard().setPixmap(QPixmap(str(path)))
        preview = QDialog(self)
        preview.setWindowTitle(f"Screenshot saved — {path.name}")
        layout = QVBoxLayout(preview)
        image = QLabel()
        pixmap = QPixmap(str(path))
        image.setPixmap(pixmap.scaled(900, 600, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        layout.addWidget(image)
        layout.addWidget(QLabel(str(path)))
        buttons = QDialogButtonBox()
        open_button = buttons.addButton("Open", QDialogButtonBox.ButtonRole.ActionRole)
        open_button.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))))
        annotate_button = buttons.addButton("Annotate", QDialogButtonBox.ButtonRole.ActionRole)
        annotate_button.clicked.connect(lambda: self._open_annotation(path))
        close_button = buttons.addButton("Close", QDialogButtonBox.ButtonRole.RejectRole)
        close_button.clicked.connect(preview.reject)
        layout.addWidget(buttons)
        preview.exec()
        self._refresh_library()

    def _refresh_library(self, *_: object) -> None:
        try:
            self._library_directory_mtimes = self._current_library_directory_mtimes()
            self._library_files = captures([
                Path(self.settings.values["recordings_dir"]).expanduser(),
                Path(self.settings.values["screenshots_dir"]).expanduser(),
            ])
        except OSError as exc:
            self.statusBar().showMessage(f"Could not read capture folders: {exc}")
            self._library_files = []
        self._filter_library_cache()

    def _current_library_directory_mtimes(self) -> tuple[tuple[str, int | None], ...]:
        directories = (
            Path(self.settings.values["recordings_dir"]).expanduser(),
            Path(self.settings.values["screenshots_dir"]).expanduser(),
        )
        result = []
        for directory in directories:
            try:
                modified = directory.stat().st_mtime_ns
            except OSError:
                modified = None
            result.append((str(directory), modified))
        return tuple(result)

    def _check_library_directories(self, *_: object) -> None:
        if getattr(self, "_library_directory_mtimes", None) != self._current_library_directory_mtimes():
            self._refresh_library()

    def _filter_library_cache(self, *_: object) -> None:
        term = self.search.text().casefold() if hasattr(self, "search") else ""
        entries = [path for path in self._library_files if term in path.name.casefold()]
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
                item = QListWidgetItem(icon_for_path(path), f"{path.name}    {description}")
                item.setData(Qt.ItemDataRole.UserRole, str(path))
                item.setToolTip(str(path))
                listing.addItem(item)
        self._schedule_library_jobs(entries[:100])

    def _schedule_library_jobs(self, paths: list[Path]) -> None:
        for path in paths:
            path_key = str(path)
            if path_key in self._library_jobs:
                continue
            if cached_thumbnail(path) is not None and (
                path.suffix.lower() not in {".mp4", ".mkv", ".webm"} or video_duration(path)
            ):
                continue
            self._library_jobs.add(path_key)
            worker = LibraryWorker(path)
            worker.signals.completed.connect(self._library_item_ready)
            self._library_worker_signals[path_key] = worker.signals
            self._library_workers.start(worker)

    def _library_item_ready(self, path_str: str, thumbnail_str: str, duration: str) -> None:
        self._library_jobs.discard(path_str)
        signals = self._library_worker_signals.pop(path_str, None)
        if signals is not None:
            signals.deleteLater()
        path = Path(path_str)
        try:
            description = describe(path)
        except OSError:
            return
        if duration and duration not in description:
            description = f"{description}  •  {duration}"
        icon = QIcon(thumbnail_str) if thumbnail_str else icon_for_path(path)
        for listing in (self.library, self.recent):
            for index in range(listing.count()):
                item = listing.item(index)
                if item.data(Qt.ItemDataRole.UserRole) == path_str:
                    item.setIcon(icon)
                    item.setText(f"{path.name}    {description}")

    def _selected_path(self) -> Path | None:
        item = self.library.currentItem()
        if item is None:
            return None
        value = item.data(Qt.ItemDataRole.UserRole)
        if not value:
            return None
        try:
            return Path(str(value))
        except TypeError:
            return None

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
        base_name = path.stem
        name, ok = QInputDialog.getText(self, "Rename capture", "Base name:", text=base_name)
        if not ok or not name:
            return
        safe_name = str(name).strip()
        if not safe_name or "/" in safe_name or "\\" in safe_name:
            QMessageBox.warning(self, "Invalid name", "Capture names cannot contain path separators.")
            return
        destination = path.with_name(f"{safe_name}{path.suffix}")
        if destination.exists() and destination != path:
            QMessageBox.warning(self, "Already exists", "A file with that name already exists.")
            return
        try:
            path.rename(destination)
        except OSError as exc:
            QMessageBox.critical(self, "Rename failed", str(exc))
            return
        self._refresh_library()

    def _process_selected(self) -> None:
        path = self._selected_path()
        if path is None:
            return
        if path.suffix.lower() not in {".mp4", ".mkv", ".webm"}:
            QMessageBox.information(self, "Video required", "Select a video to trim, export as GIF, or compress.")
            return
        dialog = ProcessingDialog(path, self)
        dialog.completed.connect(self._processing_completed)
        dialog.open()

    def _processing_completed(self, path_str: str) -> None:
        self._refresh_library()
        for index in range(self.library.count()):
            item = self.library.item(index)
            if item.data(Qt.ItemDataRole.UserRole) == path_str:
                self.library.setCurrentItem(item)
                break

    def _annotate_selected(self) -> None:
        path = self._selected_path()
        if path is not None:
            self._open_annotation(path)

    def _open_annotation(self, path: Path) -> None:
        if path.suffix.lower() not in {".png", ".jpg", ".jpeg"}:
            QMessageBox.information(self, "Image required", "Select an image to annotate.")
            return
        try:
            editor = AnnotationEditor(path, self)
        except OSError as exc:
            QMessageBox.critical(self, "Could not open image", str(exc))
            return
        editor.exec()
        self._refresh_library()

    def _delete_selected(self) -> None:
        path = self._selected_path()
        if not path:
            return
        if self.settings.values["confirm_trash"]:
            confirmation = QMessageBox(self)
            confirmation.setIcon(QMessageBox.Icon.Question)
            confirmation.setWindowTitle("Move to Trash?")
            confirmation.setText(f"Move {path.name} to Trash?")
            confirmation.setStandardButtons(
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            dont_ask = QCheckBox("Don't ask again for trash")
            confirmation.setCheckBox(dont_ask)
            if confirmation.exec() != QMessageBox.StandardButton.Yes:
                return
            if dont_ask.isChecked():
                self.settings.values["confirm_trash"] = False
                try:
                    self.settings.save()
                except OSError as exc:
                    QMessageBox.critical(self, "Could not save settings", str(exc))
                    self.settings.values["confirm_trash"] = True
                    return
        if QFile.moveToTrash(str(path)):
            self._refresh_library()
            return
        answer = QMessageBox.question(
            self,
            "Permanent deletion?",
            f"Could not move {path.name} to Trash. Permanently delete it? This cannot be undone.",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            path.unlink()
        except OSError as exc:
            QMessageBox.critical(self, "Delete failed", str(exc))
            return
        self._refresh_library()

    def closeEvent(self, event: object) -> None:
        if self.recorder.output is not None:
            answer = QMessageBox.question(self, "Recording active", "Stop the current recording and quit?")
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            try:
                self.recorder.close()
            except CaptureError as exc:
                QMessageBox.warning(self, "Recording stopped with an error", str(exc))
        if self.tray_icon is not None:
            self.tray_icon.hide()
        self._library_workers.waitForDone(2000)
        event.accept()


def _server_name() -> str:
    return f"mint-screen-recorder-{os.getuid()}"


def _send_command(command: str, timeout_ms: int = 500) -> bool:
    socket = QLocalSocket()
    socket.connectToServer(_server_name())
    if not socket.waitForConnected(timeout_ms):
        return False
    socket.write((command + "\n").encode("utf-8"))
    socket.waitForBytesWritten(timeout_ms)
    socket.disconnectFromServer()
    return True


def _accept_commands(server: QLocalServer, window: MainWindow) -> None:
    while server.hasPendingConnections():
        socket = server.nextPendingConnection()
        if socket is None:
            continue

        def dispatch(sock=socket) -> None:
            for command in bytes(sock.readAll()).decode("utf-8", errors="replace").splitlines():
                window.handle_external_command(command)
            sock.disconnectFromServer()
            sock.deleteLater()

        socket.readyRead.connect(dispatch)
        if socket.bytesAvailable():
            dispatch()


def requested_command(arguments: list[str]) -> str:
    parser = argparse.ArgumentParser(description="Linux Mint Screen Recorder")
    commands = parser.add_mutually_exclusive_group()
    commands.add_argument("--toggle-record", action="store_true", help="Start or stop recording in the running app")
    commands.add_argument("--toggle-pause", action="store_true", help="Pause or resume recording in the running app")
    commands.add_argument("--screenshot", action="store_true", help="Take a screenshot in the running app")
    commands.add_argument(
        "--screenshot-portion",
        "--snip",
        action="store_true",
        dest="screenshot_portion",
        help="Select and capture a portion of the screen",
    )
    args = parser.parse_args(arguments)
    return (
        "toggle-record" if args.toggle_record else
        "toggle-pause" if args.toggle_pause else
        "screenshot-portion" if args.screenshot_portion else
        "screenshot" if args.screenshot else "show"
    )


def main() -> int:
    command = requested_command(sys.argv[1:])
    app = QApplication([sys.argv[0]])
    app.setApplicationName("Linux Mint Screen Recorder")
    app.setOrganizationName("Screen Recorder")
    if _send_command(command):
        return 0
    server = QLocalServer()
    if not server.listen(_server_name()):
        QLocalServer.removeServer(_server_name())
        if not server.listen(_server_name()):
            if _send_command(command):
                return 0
            QMessageBox.critical(None, "Could not start Screen Recorder", server.errorString())
            return 1
    try:
        window = MainWindow()
    except (OSError, RuntimeError) as exc:
        QMessageBox.critical(None, "Could not start Screen Recorder", str(exc))
        return 1
    server.newConnection.connect(lambda: _accept_commands(server, window))
    app.aboutToQuit.connect(server.close)
    window.show()
    QTimer.singleShot(0, window.offer_orphan_recovery)
    if command != "show":
        QTimer.singleShot(0, lambda: window.handle_external_command(command))
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
