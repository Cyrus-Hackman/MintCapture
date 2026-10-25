"""FFmpeg screen recording and screenshot capture."""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from typing import BinaryIO

from PySide6.QtGui import QGuiApplication


class CaptureError(RuntimeError):
    """Actionable capture failure."""


def unique_path(directory: Path, suffix: str, stem: str | None = None) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    name = stem or datetime.now().strftime("capture-%Y%m%d-%H%M%S")
    candidate = directory / f"{name}.{suffix}"
    index = 1
    while candidate.exists():
        candidate = directory / f"{name}-{index}.{suffix}"
        index += 1
    return candidate


def save_screenshot(directory: Path, image_format: str = "png") -> Path:
    image_format = image_format.lower()
    if image_format not in ("png", "jpg", "jpeg"):
        raise CaptureError("Screenshot format must be PNG or JPEG.")
    screen = QGuiApplication.primaryScreen()
    if screen is None:
        raise CaptureError("No display was detected.")
    pixmap = screen.grabWindow(0)
    if pixmap.isNull():
        raise CaptureError("The desktop did not provide a screenshot. Check screen capture permissions.")
    suffix = "jpg" if image_format == "jpeg" else image_format
    destination = unique_path(directory, suffix)
    if not pixmap.save(str(destination), "JPEG" if suffix == "jpg" else "PNG"):
        raise CaptureError(f"Could not write screenshot to {destination}. Check disk space and permissions.")
    return destination


class Recorder:
    def __init__(self) -> None:
        self.process: subprocess.Popen[bytes] | None = None
        self.output: Path | None = None
        self.stderr_log: BinaryIO | None = None

    @property
    def running(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def start(
        self,
        output: Path,
        fps: int = 30,
        quality: str = "High",
        audio_source: str = "",
        microphone: bool = False,
        microphone_source: str = "",
    ) -> Path:
        if self.running:
            raise CaptureError("A recording is already in progress.")
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            raise CaptureError("FFmpeg is missing. Install it with: sudo apt install ffmpeg")
        session = os.environ.get("XDG_SESSION_TYPE", "").lower()
        if session == "wayland" or (not session and os.environ.get("WAYLAND_DISPLAY")):
            raise CaptureError(
                "This Wayland session does not expose a supported desktop-portal capture backend. "
                "Use an X11 session, or install/use a portal-capable recorder such as OBS Studio."
            )
        if not os.environ.get("DISPLAY"):
            raise CaptureError("No X11 display was detected (DISPLAY is empty).")
        if fps not in (15, 24, 30, 60):
            raise CaptureError("Frame rate must be 15, 24, 30, or 60 FPS.")
        if output.suffix.lower() not in (".mkv", ".mp4", ".webm"):
            raise CaptureError("Recording format must be MKV, MP4, or WebM.")
        output.parent.mkdir(parents=True, exist_ok=True)
        if output.exists():
            raise CaptureError(f"Refusing to overwrite existing file: {output}")
        suffix = output.suffix.lower()
        if suffix == ".webm":
            quality_args = {
                "High": ["-crf", "30", "-b:v", "0"],
                "Medium": ["-crf", "36", "-b:v", "0"],
                "Low": ["-crf", "42", "-b:v", "0"],
            }
            video_codec = "libvpx-vp9"
        else:
            quality_args = {
                "High": ["-preset", "veryfast", "-crf", "20"],
                "Medium": ["-preset", "veryfast", "-crf", "25"],
                "Low": ["-preset", "ultrafast", "-crf", "30"],
            }
            video_codec = "libx264"
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            raise CaptureError("No primary display was detected.")
        geometry = screen.virtualGeometry()
        scale = screen.devicePixelRatio()
        capture_width = round(geometry.width() * scale)
        capture_height = round(geometry.height() * scale)
        args = [
            ffmpeg,
            "-hide_banner",
            "-loglevel", "error",
            "-n",
            "-f", "x11grab",
            "-video_size", f"{capture_width}x{capture_height}",
            "-framerate", str(fps),
            "-i", f"{os.environ['DISPLAY']}+{geometry.x()},{geometry.y()}",
        ]
        audio_inputs: list[int] = []
        if audio_source:
            args += ["-f", "pulse", "-i", audio_source]
            audio_inputs.append(1)
        if microphone:
            args += ["-f", "pulse", "-i", microphone_source or "default"]
            audio_inputs.append(len(audio_inputs) + 1)
        args += ["-c:v", video_codec, *quality_args.get(quality, quality_args["High"])]
        if len(audio_inputs) == 1:
            args += ["-map", "0:v:0", "-map", f"{audio_inputs[0]}:a:0", "-c:a", "aac", "-b:a", "160k"]
        elif len(audio_inputs) > 1:
            args += [
                "-filter_complex",
                f"[{audio_inputs[0]}:a:0][{audio_inputs[1]}:a:0]amix=inputs=2:duration=longest[aout]",
                "-map", "0:v:0", "-map", "[aout]", "-c:a", "aac", "-b:a", "160k",
            ]
        if suffix == ".webm":
            if "-c:a" in args:
                args[args.index("aac")] = "libopus"
            args += ["-deadline", "realtime", "-cpu-used", "4"]
        args.append(str(output))
        stderr_log = tempfile.TemporaryFile()
        try:
            self.process = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=stderr_log)
        except OSError as exc:
            stderr_log.close()
            raise CaptureError(f"Could not start FFmpeg: {exc}") from exc
        self.output = output
        self.stderr_log = stderr_log
        return output

    def pause(self) -> None:
        if not self.running or self.process is None:
            raise CaptureError("There is no active recording to pause.")
        self.process.send_signal(signal.SIGSTOP)

    def resume(self) -> None:
        if not self.running or self.process is None:
            raise CaptureError("There is no paused recording to resume.")
        self.process.send_signal(signal.SIGCONT)

    def stop(self) -> Path | None:
        if self.process is None:
            return None
        process = self.process
        self.process = None
        if process.poll() is None:
            try:
                process.send_signal(signal.SIGCONT)
                if process.stdin:
                    process.stdin.write(b"q\n")
                    process.stdin.flush()
                    process.stdin.close()
                process.wait(timeout=10)
            except (OSError, subprocess.TimeoutExpired):
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
        output = self.output
        self.output = None
        stderr_log = self.stderr_log
        self.stderr_log = None
        detail = b""
        if stderr_log:
            stderr_log.seek(max(0, stderr_log.tell() - 3000))
            detail = stderr_log.read()
            stderr_log.close()
        if process.returncode not in (0, None):
            raise CaptureError(f"FFmpeg exited with status {process.returncode}: {detail.decode(errors='replace')}")
        if output and (not output.exists() or output.stat().st_size == 0):
            raise CaptureError("FFmpeg did not produce a usable recording.")
        return output

    def close(self) -> None:
        if self.process is not None:
            self.stop()
