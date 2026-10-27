"""Asynchronous Library media-processing dialog."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QProcess, QTimer, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout,
    QLabel, QLineEdit, QMessageBox, QProgressBar, QPushButton, QVBoxLayout,
)

from .capture import unique_path
from .library import video_duration
from .processing import (
    build_compress_args, build_gif_args, build_trim_args, progress_percent,
    validate_trim_times,
)


class ProcessingDialog(QDialog):
    completed = Signal(str)

    def __init__(self, source: Path, parent=None) -> None:
        super().__init__(parent)
        self.source = source
        self.duration = self._read_duration()
        self._process: QProcess | None = None
        self._output: Path | None = None
        self._cancel_requested = False
        self._progress_buffer = bytearray()
        self._stderr_buffer = bytearray()
        self.setWindowTitle(f"Process {source.name}")
        form = QFormLayout()
        self.mode = QComboBox()
        self.mode.addItems(["Trim", "Export GIF", "Compress"])
        self.mode.currentTextChanged.connect(self._update_mode_controls)
        form.addRow("Operation", self.mode)

        self.start_time = QLineEdit("00:00:00.000")
        self.end_time = QLineEdit(self._duration_as_time())
        form.addRow("Start (HH:MM:SS.mmm)", self.start_time)
        form.addRow("End (HH:MM:SS.mmm)", self.end_time)
        self.fast_trim = QCheckBox("Fast (may cut on a keyframe)")
        self.fast_trim.setChecked(True)
        form.addRow("Trim mode", self.fast_trim)

        self.gif_width = QComboBox()
        self.gif_width.addItems(["480", "640", "800", "original"])
        self.gif_fps = QComboBox()
        self.gif_fps.addItems(["10", "15", "24"])
        gif_row = QHBoxLayout()
        gif_row.addWidget(QLabel("Width"))
        gif_row.addWidget(self.gif_width)
        gif_row.addWidget(QLabel("FPS"))
        gif_row.addWidget(self.gif_fps)
        form.addRow("GIF options", gif_row)

        self.quality = QComboBox()
        self.quality.addItems(["High", "Medium", "Low"])
        self.output_format = QComboBox()
        self.output_format.addItems(["mp4", "webm"])
        compress_row = QHBoxLayout()
        compress_row.addWidget(QLabel("Quality"))
        compress_row.addWidget(self.quality)
        compress_row.addWidget(QLabel("Format"))
        compress_row.addWidget(self.output_format)
        form.addRow("Compression", compress_row)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.status = QLabel("Ready")
        self.run_button = QPushButton("Start")
        self.close_button = QPushButton("Close")
        self.run_button.clicked.connect(self._start)
        self.close_button.clicked.connect(self._cancel_or_close)
        buttons = QHBoxLayout()
        buttons.addWidget(self.run_button)
        buttons.addWidget(self.close_button)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.progress)
        layout.addWidget(self.status)
        layout.addLayout(buttons)
        self._update_mode_controls(self.mode.currentText())

    def _read_duration(self) -> float | None:
        value = video_duration(self.source)
        if not value:
            return None
        try:
            return float(value)
        except ValueError:
            return None

    def _duration_as_time(self) -> str:
        if self.duration is None:
            return "00:00:00.000"
        millis = int(self.duration * 1000)
        hours, remainder = divmod(millis, 3_600_000)
        minutes, remainder = divmod(remainder, 60_000)
        seconds, milliseconds = divmod(remainder, 1000)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{milliseconds:03d}"

    def _update_mode_controls(self, mode: str) -> None:
        trimming = mode == "Trim"
        gif = mode == "Export GIF"
        self.start_time.setEnabled(trimming or gif)
        self.end_time.setEnabled(trimming or gif)
        self.fast_trim.setEnabled(trimming)
        self.gif_width.setEnabled(gif)
        self.gif_fps.setEnabled(gif)
        self.quality.setEnabled(trimming or mode == "Compress")
        self.output_format.setEnabled(mode == "Compress")

    def _build_command(self) -> tuple[list[str], Path]:
        mode = self.mode.currentText()
        if mode == "Trim":
            validate_trim_times(self.start_time.text(), self.end_time.text(), self.duration)
            output = unique_path(self.source.parent, self.source.suffix.lstrip("."), f"{self.source.stem}-trimmed")
            args = build_trim_args(
                "ffmpeg", self.source, output, self.start_time.text(),
                self.end_time.text(), self.fast_trim.isChecked(), self.quality.currentText(),
            )
        elif mode == "Export GIF":
            start = self.start_time.text().strip()
            end = self.end_time.text().strip()
            if (start or end) and not (start and end):
                raise ValueError("Enter both a start and end time, or leave both empty.")
            if start and end:
                validate_trim_times(start, end, self.duration)
            output = unique_path(self.source.parent, "gif", self.source.stem)
            args = build_gif_args(
                "ffmpeg", self.source, output, self.gif_width.currentText(),
                int(self.gif_fps.currentText()), start, end,
            )
        else:
            output_format = self.output_format.currentText()
            output = unique_path(
                self.source.parent, output_format, f"{self.source.stem}-compressed",
            )
            args = build_compress_args(
                "ffmpeg", self.source, output, self.quality.currentText(), output_format,
            )
        return args, output

    def _start(self) -> None:
        try:
            args, self._output = self._build_command()
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Invalid processing options", str(exc))
            return
        self._cancel_requested = False
        self._progress_buffer.clear()
        self._stderr_buffer.clear()
        self.progress.setValue(0)
        process = QProcess(self)
        process.setProcessChannelMode(QProcess.ProcessChannelMode.SeparateChannels)
        process.readyReadStandardOutput.connect(self._read_progress)
        process.readyReadStandardError.connect(self._read_error)
        process.finished.connect(self._finished)
        process.errorOccurred.connect(self._process_error)
        self._process = process
        self.run_button.setEnabled(False)
        self.close_button.setText("Cancel")
        self.status.setText("Processing…")
        process.start(args[0], args[1:])

    def _process_error(self, _error: QProcess.ProcessError) -> None:
        if self._process is None or self._cancel_requested:
            return
        detail = self._process.errorString()
        self._process = None
        self._remove_partial_output()
        self.run_button.setEnabled(True)
        self.close_button.setText("Close")
        QMessageBox.critical(self, "Could not start processing", detail)

    def _read_progress(self) -> None:
        if self._process is None:
            return
        self._progress_buffer.extend(bytes(self._process.readAllStandardOutput()))
        while b"\n" in self._progress_buffer:
            line, _, rest = self._progress_buffer.partition(b"\n")
            self._progress_buffer[:] = rest
            percent = progress_percent(line.decode("ascii", errors="ignore").strip(), self.duration)
            if percent is not None:
                self.progress.setValue(percent)

    def _read_error(self) -> None:
        if self._process is not None:
            data = bytes(self._process.readAllStandardError())
            self._stderr_buffer.extend(data)
            self.status.setText(data.decode(errors="replace")[-250:])

    def _finished(self, exit_code: int, _exit_status: QProcess.ExitStatus) -> None:
        if self._process is None:
            return
        self._stderr_buffer.extend(bytes(self._process.readAllStandardError()))
        self._process = None
        if self._cancel_requested:
            self._remove_partial_output()
            self.status.setText("Cancelled")
            self.run_button.setEnabled(True)
            self.close_button.setText("Close")
            return
        if exit_code == 0 and self._output and self._output.is_file() and self._output.stat().st_size > 0:
            output = self._output
            self.progress.setValue(100)
            self.status.setText(f"Saved {output.name}")
            self.completed.emit(str(output))
            self.run_button.setEnabled(True)
            self.close_button.setText("Close")
            return
        error = self._stderr_buffer.decode(errors="replace").strip()
        self._remove_partial_output()
        QMessageBox.critical(self, "Processing failed", error or f"FFmpeg exited with status {exit_code}.")
        self.run_button.setEnabled(True)
        self.close_button.setText("Close")

    def _cancel_or_close(self) -> None:
        if self._process is None:
            self.reject()
            return
        self._cancel_requested = True
        self.status.setText("Cancelling…")
        self._process.terminate()
        QTimer.singleShot(2000, self._kill_if_running)

    def _kill_if_running(self) -> None:
        if self._process is not None and self._process.state() != QProcess.ProcessState.NotRunning:
            self._process.kill()

    def _remove_partial_output(self) -> None:
        if self._output is None:
            return
        try:
            self._output.unlink(missing_ok=True)
        except OSError as exc:
            self.status.setText(f"Could not remove partial output: {exc}")
