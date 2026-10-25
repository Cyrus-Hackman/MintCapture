"""FFmpeg screen recording and screenshot capture."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from typing import BinaryIO

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QCursor, QGuiApplication, QPainter, QPixmap
from .window_capture import physical_rect_to_capture_geometry


ACTIVE_RECORDING_SEGMENT_DIRS: set[Path] = set()


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


def logical_rect_to_physical(rect: QRect, screens: object) -> tuple[int, int, int, int]:
    screen_list = list(screens) if isinstance(screens, (list, tuple)) else [screens]
    if not screen_list:
        raise CaptureError("No displays were detected.")
    geometries = [screen.geometry() for screen in screen_list]
    top_left_screen = next(
        (screen for screen, geometry in zip(screen_list, geometries) if geometry.contains(rect.topLeft())),
        screen_list[0],
    )
    scale = float(top_left_screen.devicePixelRatio())
    region_screens = [
        screen for screen, geometry in zip(screen_list, geometries)
        if geometry.intersects(rect)
    ]
    if len({float(screen.devicePixelRatio()) for screen in region_screens}) > 1:
        # FFmpeg accepts one rectangular capture size, so mixed-DPI spans use the largest scale.
        scale = max(float(screen.devicePixelRatio()) for screen in region_screens)
    top_left_geometry = top_left_screen.geometry()
    x = round(top_left_geometry.x() + (rect.x() - top_left_geometry.x()) * scale)
    y = round(top_left_geometry.y() + (rect.y() - top_left_geometry.y()) * scale)
    width = max(16, int(rect.width() * scale) & ~1)
    height = max(16, int(rect.height() * scale) & ~1)
    physical_bounds = [
        QRect(
            geometry.x(),
            geometry.y(),
            round(geometry.width() * float(screen.devicePixelRatio())),
            round(geometry.height() * float(screen.devicePixelRatio())),
        )
        for screen, geometry in zip(screen_list, geometries)
    ]
    left = min(bounds.left() for bounds in physical_bounds)
    top = min(bounds.top() for bounds in physical_bounds)
    right = max(bounds.right() for bounds in physical_bounds) + 1
    bottom = max(bounds.bottom() for bounds in physical_bounds) + 1
    x = min(max(x, left), right - 16)
    y = min(max(y, top), bottom - 16)
    width = max(16, min(width, right - x)) & ~1
    height = max(16, min(height, bottom - y)) & ~1
    return x, y, width, height


def composite_screens(screens: list[object]) -> QPixmap:
    if not screens:
        raise CaptureError("No displays were detected.")
    geometries = [screen.geometry() for screen in screens]
    left = min(rect.x() for rect in geometries)
    top = min(rect.y() for rect in geometries)
    right = max(rect.x() + rect.width() for rect in geometries)
    bottom = max(rect.y() + rect.height() for rect in geometries)
    scale = max(float(screen.devicePixelRatio()) for screen in screens)
    canvas = QPixmap(round((right - left) * scale), round((bottom - top) * scale))
    canvas.fill(Qt.GlobalColor.transparent)
    painter = QPainter(canvas)
    for screen, geometry in zip(screens, geometries):
        pixmap = screen.grabWindow(0)
        if pixmap.isNull():
            painter.end()
            raise CaptureError(f"Could not capture display at ({geometry.x()}, {geometry.y()}).")
        destination = QRect(
            round((geometry.x() - left) * scale),
            round((geometry.y() - top) * scale),
            round(geometry.width() * scale),
            round(geometry.height() * scale),
        )
        painter.drawPixmap(destination, pixmap)
    painter.end()
    return canvas


def save_screenshot(
    directory: Path,
    image_format: str = "png",
    target: str = "Primary screen",
    region: QRect | None = None,
    region_physical: bool = False,
) -> Path:
    image_format = image_format.lower()
    if image_format not in ("png", "jpg", "jpeg"):
        raise CaptureError("Screenshot format must be PNG or JPEG.")
    screens = QGuiApplication.screens()
    if not screens:
        raise CaptureError("No display was detected.")
    if region is not None:
        geometries = [screen.geometry() for screen in screens]
        left = min(rect.x() for rect in geometries)
        top = min(rect.y() for rect in geometries)
        scale = max(float(screen.devicePixelRatio()) for screen in screens)
        desktop = composite_screens(screens)
        if region_physical:
            crop = QRect(
                round(region.x() - left * scale),
                round(region.y() - top * scale),
                region.width(),
                region.height(),
            )
        else:
            crop = QRect(
                round((region.x() - left) * scale),
                round((region.y() - top) * scale),
                round(region.width() * scale),
                round(region.height() * scale),
            )
        crop = crop.intersected(desktop.rect())
        pixmap = desktop.copy(crop)
    elif target == "All screens":
        pixmap = composite_screens(screens)
    elif target == "Screen under cursor":
        screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        if screen is None:
            raise CaptureError("No display was detected.")
        pixmap = screen.grabWindow(0)
    elif target == "Primary screen":
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            raise CaptureError("No primary display was detected.")
        pixmap = screen.grabWindow(0)
    else:
        raise CaptureError(f"Unknown screenshot target: {target}")
    if pixmap.isNull():
        raise CaptureError("The desktop did not provide a screenshot. Check screen capture permissions.")
    suffix = "jpg" if image_format == "jpeg" else image_format
    return save_screenshot_pixmap(pixmap, directory, suffix)


def save_screenshot_pixmap(pixmap: QPixmap, directory: Path, image_format: str = "png") -> Path:
    suffix = image_format.lower()
    if suffix == "jpeg":
        suffix = "jpg"
    if suffix not in {"png", "jpg"}:
        raise CaptureError("Screenshot format must be PNG or JPEG.")
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


def find_orphaned_recordings(directory: Path) -> list[Path]:
    active = {path.resolve() for path in ACTIVE_RECORDING_SEGMENT_DIRS}
    orphaned = []
    for segment_dir in sorted(directory.glob(".*.segments-*")):
        if not segment_dir.is_dir() or segment_dir.resolve() in active:
            continue
        if any(segment.is_file() and segment.stat().st_size > 0 for segment in segment_dir.glob("segment-*.mkv")):
            orphaned.append(segment_dir)
    return orphaned


def _segment_is_readable(ffmpeg: str, segment: Path, last_segment: bool = False) -> bool | None:
    ffprobe = shutil.which("ffprobe")
    try:
        if ffprobe:
            probe = subprocess.run(
                [
                    ffprobe, "-v", "error", "-show_entries", "format=duration",
                    "-of", "default=noprint_wrappers=1:nokey=1", str(segment),
                ],
                capture_output=True,
                text=True,
                check=False,
                timeout=60,
            )
            if probe.returncode == 0 and not last_segment:
                return True
        result = subprocess.run(
            [ffmpeg, "-v", "error", "-i", str(segment), "-c", "copy", "-f", "null", "-"],
            capture_output=True,
            text=True,
            check=False,
            timeout=120 if last_segment else 60,
        )
    except subprocess.TimeoutExpired:
        return None
    except OSError:
        return None
    if last_segment:
        return result.returncode == 0 and not result.stderr.strip()
    return result.returncode == 0


def _segments_have_audio(ffprobe: str, segments: list[Path]) -> bool:
    for segment in segments:
        try:
            result = subprocess.run(
                [
                    ffprobe, "-v", "error", "-select_streams", "a",
                    "-show_entries", "stream=codec_type", "-of", "csv=p=0", str(segment),
                ],
                capture_output=True,
                text=True,
                check=False,
                timeout=60,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise CaptureError(f"Could not inspect audio streams in {segment}: {exc}") from exc
        if result.returncode != 0:
            raise CaptureError(f"Could not inspect audio streams in {segment}: {result.stderr.strip()}")
        if result.stdout.strip():
            return True
    return False


def _verify_recovered_output(ffprobe: str, output: Path) -> bool:
    try:
        result = subprocess.run(
            [
                ffprobe, "-v", "error", "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1", str(output),
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    if result.returncode != 0:
        return False
    try:
        return float(result.stdout.strip()) > 0
    except ValueError:
        return False


def concatenate_segments(
    ffmpeg: str,
    segments: list[Path],
    output: Path,
    quality: str,
    has_audio: bool,
    concat_directory: Path,
) -> None:
    if not segments:
        raise CaptureError("No usable recording segments were found.")
    concat_list = concat_directory / "concat.txt"
    concat_list.write_text(concat_list_content(segments), encoding="utf-8")
    args = [
        ffmpeg, "-hide_banner", "-loglevel", "error", "-n",
        "-f", "concat", "-safe", "0", "-i", str(concat_list),
    ]
    if output.suffix.lower() == ".webm":
        webm_crf = {"High": "30", "Medium": "36", "Low": "42"}
        args += [
            "-c:v", "libvpx-vp9", "-crf", webm_crf.get(quality, "36"), "-b:v", "0",
            "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2", "-pix_fmt", "yuv420p",
            "-deadline", "realtime", "-cpu-used", "4",
        ]
        if has_audio:
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


def recover_orphaned_recording(segment_dir: Path, output_dir: Path, fmt: str, quality: str) -> Path:
    normalized_format = fmt.lower().lstrip(".")
    if normalized_format not in {"mkv", "mp4", "webm"}:
        raise CaptureError("Recovery format must be MKV, MP4, or WebM.")
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise CaptureError("FFmpeg is missing. Install it with: sudo apt install ffmpeg")
    output_dir.mkdir(parents=True, exist_ok=True)
    candidates = sorted(
        segment for segment in segment_dir.glob("segment-*.mkv") if segment.is_file()
    )
    if not candidates:
        raise CaptureError(f"No recording segments were found in {segment_dir}.")

    verified: list[Path] = []
    discarded: Path | None = None
    for index, segment in enumerate(candidates):
        status = _segment_is_readable(ffmpeg, segment, last_segment=index == len(candidates) - 1)
        if status is True or status is None:
            verified.append(segment)
        elif index == len(candidates) - 1:
            discarded = segment
        else:
            raise CaptureError(f"Recording segment is corrupt: {segment}")
    if not verified:
        raise CaptureError(f"No readable recording segments were found in {segment_dir}.")
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        raise CaptureError("FFprobe is missing. Install FFmpeg tools with: sudo apt install ffmpeg")
    has_audio = _segments_have_audio(ffprobe, verified)

    output = unique_path(
        output_dir,
        normalized_format,
        f"recovered-{datetime.now().strftime('%Y%m%d-%H%M%S')}",
    )
    try:
        concatenate_segments(ffmpeg, verified, output, quality, has_audio, segment_dir)
        if not output.exists() or output.stat().st_size == 0:
            raise CaptureError("FFmpeg did not create a usable recovered recording.")
        if not _verify_recovered_output(ffprobe, output):
            raise CaptureError(f"Recovered output could not be verified by FFprobe: {output}")
    except (OSError, CaptureError) as exc:
        raise CaptureError(f"Could not recover recording: {exc}. Segments were kept in {segment_dir}") from exc
    if discarded is not None:
        discarded_dir = output_dir / f"{output.stem}.discarded"
        index = 1
        while discarded_dir.exists():
            discarded_dir = output_dir / f"{output.stem}-{index}.discarded"
            index += 1
        try:
            discarded_dir.mkdir(parents=True)
            shutil.move(str(discarded), str(discarded_dir / discarded.name))
        except OSError as exc:
            raise CaptureError(
                f"Recovered recording to {output}, but could not preserve the corrupt segment "
                f"in {discarded_dir}; original segments remain in {segment_dir}: {exc}"
            ) from exc
    try:
        shutil.rmtree(segment_dir)
    except OSError as exc:
        raise CaptureError(
            f"Recovered recording to {output}, but temporary segments remain in {segment_dir}: {exc}"
        ) from exc
    return output


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
        self._region: QRect | None = None

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
        region: QRect | None = None,
        physical: bool = False,
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
        if region is None:
            self._geometry = (
                geometry.x(),
                geometry.y(),
                round(geometry.width() * scale),
                round(geometry.height() * scale),
            )
        elif physical:
            self._geometry = physical_rect_to_capture_geometry(region)
        else:
            self._geometry = logical_rect_to_physical(region, QGuiApplication.screens())
        self._region = region
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
        ACTIVE_RECORDING_SEGMENT_DIRS.add(self.segment_directory.resolve())
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
        ACTIVE_RECORDING_SEGMENT_DIRS.discard(segment_directory.resolve())
        return output

    def _concat_segments(self, output: Path, segment_directory: Path) -> None:
        concatenate_segments(
            self._ffmpeg,
            self.segments,
            output,
            self._quality,
            bool(self._audio_source or self._microphone),
            segment_directory,
        )

    def close(self) -> None:
        if self.output is not None:
            self.stop()
