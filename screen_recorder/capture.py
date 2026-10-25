"""FFmpeg screen recording and screenshot capture."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from typing import BinaryIO

from PySide6.QtGui import QGuiApplication


class CaptureError(RuntimeError):
    """Actionable capture failure."""


def build_ffmpeg_args(
    ffmpeg: str,
    display: str,
    geometry: tuple[int, int, int, int],
    output: Path,
    fps: int,
    quality: str,
    audio_source: str,
    microphone: bool,
    microphone_source: str,
    show_cursor: bool = True,
) -> list[str]:
    """Build an FFmpeg command without reading the environment or touching the filesystem."""
    x, y, width, height = geometry
    suffix = output.suffix.lower()
    if suffix == ".webm":
        quality_args = {
            "High": ["-crf", "30", "-b:v", "0"],
            "Medium": ["-crf", "36", "-b:v", "0"],
            "Low": ["-crf", "42", "-b:v", "0"],
        }
        video_codec = "libvpx-vp9"
        audio_codec = "libopus"
    else:
        quality_args = {
            "High": ["-preset", "veryfast", "-crf", "20"],
            "Medium": ["-preset", "veryfast", "-crf", "25"],
            "Low": ["-preset", "ultrafast", "-crf", "30"],
        }
        video_codec = "libx264"
        audio_codec = "aac"

    args = [
        ffmpeg,
        "-hide_banner",
        "-loglevel", "error",
        "-n",
        "-f", "x11grab",
        "-draw_mouse", "1" if show_cursor else "0",
        "-video_size", f"{width}x{height}",
        "-framerate", str(fps),
        "-i", f"{display}+{x},{y}",
    ]
    audio_inputs: list[int] = []
    if audio_source:
        args += ["-f", "pulse", "-i", audio_source]
        audio_inputs.append(1)
    if microphone:
        args += ["-f", "pulse", "-i", microphone_source or "default"]
        audio_inputs.append(len(audio_inputs) + 1)

    args += [
        "-c:v", video_codec,
        *quality_args.get(quality, quality_args["High"]),
        "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",
        "-pix_fmt", "yuv420p",
    ]
    if len(audio_inputs) == 1:
        args += [
            "-map", "0:v:0", "-map", f"{audio_inputs[0]}:a:0",
            "-c:a", audio_codec, "-b:a", "160k",
        ]
    elif len(audio_inputs) == 2:
        args += [
            "-filter_complex",
            f"[{audio_inputs[0]}:a:0][{audio_inputs[1]}:a:0]amix=inputs=2:duration=longest[aout]",
            "-map", "0:v:0", "-map", "[aout]",
            "-c:a", audio_codec, "-b:a", "160k",
        ]
    if suffix == ".webm":
        args += ["-deadline", "realtime", "-cpu-used", "4"]
    elif suffix == ".mp4":
        args += ["-movflags", "+frag_keyframe+empty_moov"]
    args.append(str(output))
    return args


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


def concat_list_content(segments: list[Path]) -> str:
    """Return an FFmpeg concat-demuxer list with escaped paths."""
    lines = []
    for segment in segments:
        path = segment.resolve().as_posix().replace("\\", "\\\\").replace("'", "\\'")
        lines.append(f"file '{path}'")
    return "\n".join(lines) + "\n"


class Recorder:
    def __init__(self) -> None:
        self.process: subprocess.Popen[bytes] | None = None
        self.output: Path | None = None
        self.stderr_log: BinaryIO | None = None
        self.segment_directory: Path | None = None
        self.segments: list[Path] = []
        self._paused = False
        self._ffmpeg = ""
        self._display = ""
        self._geometry = (0, 0, 0, 0)
        self._fps = 30
        self._quality = "High"
        self._audio_source = ""
        self._microphone = False
        self._microphone_source = ""
        self._show_cursor = True

    @property
    def running(self) -> bool:
        return self.output is not None and (
            self._paused or (self.process is not None and self.process.poll() is None)
        )

    def start(
        self,
        output: Path,
        fps: int = 30,
        quality: str = "High",
        audio_source: str = "",
        microphone: bool = False,
        microphone_source: str = "",
        show_cursor: bool = True,
    ) -> Path:
        if self.output is not None:
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
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            raise CaptureError("No primary display was detected.")
        geometry = screen.virtualGeometry()
        scale = screen.devicePixelRatio()
        self.output = output
        try:
            self.segment_directory = Path(
                tempfile.mkdtemp(prefix=f".{output.stem}.segments-", dir=output.parent)
            )
        except OSError as exc:
            self.output = None
            raise CaptureError(f"Could not create a temporary recording folder in {output.parent}: {exc}") from exc
        self.segments = []
        self._paused = False
        self._ffmpeg = ffmpeg
        self._display = os.environ["DISPLAY"]
        self._geometry = (
            geometry.x(),
            geometry.y(),
            round(geometry.width() * scale),
            round(geometry.height() * scale),
        )
        self._fps = fps
        self._quality = quality
        self._audio_source = audio_source
        self._microphone = microphone
        self._microphone_source = microphone_source
        self._show_cursor = show_cursor
        try:
            self._start_segment()
        except (OSError, CaptureError):
            self.output = None
            failed_directory = self.segment_directory
            self.segment_directory = None
            if failed_directory:
                shutil.rmtree(failed_directory, ignore_errors=True)
            raise
        return output

    def _start_segment(self) -> None:
        if self.output is None or self.segment_directory is None:
            raise CaptureError("No recording session is available to resume.")
        segment = self.segment_directory / f"segment-{len(self.segments) + 1:03d}.mkv"
        args = build_ffmpeg_args(
            self._ffmpeg,
            self._display,
            self._geometry,
            segment,
            self._fps,
            self._quality,
            self._audio_source,
            self._microphone,
            self._microphone_source,
            self._show_cursor,
        )
        stderr_log = tempfile.TemporaryFile()
        try:
            self.process = subprocess.Popen(
                args, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=stderr_log
            )
        except OSError as exc:
            stderr_log.close()
            raise CaptureError(f"Could not start FFmpeg: {exc}") from exc
        self.stderr_log = stderr_log
        self._paused = False

    def _stop_segment(self) -> Path:
        if self.process is None or self.segment_directory is None:
            raise CaptureError("There is no active recording segment to stop.")
        process = self.process
        self.process = None
        if process.poll() is None:
            try:
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

        segment = self.segment_directory / f"segment-{len(self.segments) + 1:03d}.mkv"
        stderr_log = self.stderr_log
        self.stderr_log = None
        detail = b""
        if stderr_log:
            stderr_log.seek(max(0, stderr_log.tell() - 3000))
            detail = stderr_log.read()
            stderr_log.close()
        if segment.exists() and segment.stat().st_size > 0:
            self.segments.append(segment)
        if process.returncode not in (0, None):
            raise CaptureError(f"FFmpeg exited with status {process.returncode}: {detail.decode(errors='replace')}")
        if segment not in self.segments:
            raise CaptureError(f"FFmpeg did not produce a usable segment: {segment}")
        return segment

    def pause(self) -> None:
        if not self.running or self.process is None:
            raise CaptureError("There is no active recording to pause.")
        try:
            self._stop_segment()
        finally:
            self._paused = True

    def resume(self) -> None:
        if not self.running or not self._paused:
            raise CaptureError("There is no paused recording to resume.")
        self._start_segment()

    def stop(self) -> Path | None:
        if self.output is None:
            return None
        if self.process is not None:
            try:
                self._stop_segment()
            finally:
                self._paused = True
        if not self.segments:
            raise CaptureError("No recording segments were produced.")
        output = self.output
        segment_directory = self.segment_directory
        if segment_directory is None:
            raise CaptureError("Recording segment directory is unavailable; segment files were preserved.")
        try:
            if len(self.segments) == 1 and output.suffix.lower() == ".mkv":
                os.link(self.segments[0], output)
                self.segments[0].unlink()
            else:
                self._concat_segments(output, segment_directory)
        except (OSError, CaptureError) as exc:
            raise CaptureError(
                f"Could not finalize recording: {exc}. Recording segments were kept in {segment_directory}"
            ) from exc
        if not output.exists() or output.stat().st_size == 0:
            raise CaptureError(f"Final output is empty or missing; segments were kept in {segment_directory}")
        self.output = None
        self.segment_directory = None
        self.segments = []
        self._paused = False
        try:
            shutil.rmtree(segment_directory)
        except OSError as exc:
            raise CaptureError(
                f"Recording was saved to {output}, but temporary segments remain in "
                f"{segment_directory}: {exc}"
            ) from exc
        return output

    def _concat_segments(self, output: Path, segment_directory: Path) -> None:
        concat_list = segment_directory / "concat.txt"
        concat_list.write_text(concat_list_content(self.segments), encoding="utf-8")
        args = [
            self._ffmpeg, "-hide_banner", "-loglevel", "error", "-n",
            "-f", "concat", "-safe", "0", "-i", str(concat_list),
        ]
        if output.suffix.lower() == ".webm":
            webm_crf = {"High": "30", "Medium": "36", "Low": "42"}
            args += [
                "-c:v", "libvpx-vp9", "-crf", webm_crf.get(self._quality, "36"), "-b:v", "0",
                "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2", "-pix_fmt", "yuv420p",
                "-deadline", "realtime", "-cpu-used", "4",
            ]
            if self._audio_source or self._microphone:
                args += ["-c:a", "libopus"]
        else:
            args += ["-c", "copy"]
            if output.suffix.lower() == ".mp4":
                args += ["-movflags", "+frag_keyframe+empty_moov"]
        args.append(str(output))
        result = subprocess.run(args, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            if output.exists():
                output.unlink()
            detail = result.stderr.strip() or f"FFmpeg exited with status {result.returncode}"
            raise CaptureError(detail)

    def close(self) -> None:
        if self.output is not None:
            self.stop()
