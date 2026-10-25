"""Pure FFmpeg argument and time helpers for Library media processing."""

from __future__ import annotations

import re
from pathlib import Path


QUALITY_ARGS = {
    "High": ["-preset", "veryfast", "-crf", "20"],
    "Medium": ["-preset", "veryfast", "-crf", "25"],
    "Low": ["-preset", "ultrafast", "-crf", "30"],
}
WEBM_CRF = {"High": "30", "Medium": "36", "Low": "42"}
TIME_PATTERN = re.compile(r"^(\d{2,}):([0-5]\d):([0-5]\d)(?:\.(\d{1,3}))?$")


def parse_time_ms(value: str) -> int:
    match = TIME_PATTERN.fullmatch(value.strip())
    if not match:
        raise ValueError("Time must use HH:MM:SS.mmm format.")
    hours, minutes, seconds = (int(match.group(index)) for index in (1, 2, 3))
    milliseconds = int((match.group(4) or "0").ljust(3, "0"))
    return ((hours * 60 + minutes) * 60 + seconds) * 1000 + milliseconds


def validate_trim_times(start: str, end: str, duration_seconds: float | None) -> tuple[int, int]:
    start_ms = parse_time_ms(start)
    end_ms = parse_time_ms(end)
    if end_ms <= start_ms:
        raise ValueError("End time must be later than start time.")
    if duration_seconds is not None and end_ms > int(duration_seconds * 1000):
        raise ValueError("End time exceeds the cached video duration.")
    return start_ms, end_ms


def _progress_args(ffmpeg: str) -> list[str]:
    return [ffmpeg, "-hide_banner", "-loglevel", "error", "-nostats", "-progress", "pipe:1", "-n"]


def build_trim_args(
    ffmpeg: str,
    source: Path,
    output: Path,
    start: str,
    end: str,
    fast: bool,
    quality: str = "High",
) -> list[str]:
    validate_trim_times(start, end, None)
    args = _progress_args(ffmpeg) + ["-ss", start, "-i", str(source), "-to", end]
    if fast:
        args += ["-c", "copy"]
    else:
        args += [
            "-c:v", "libx264", *QUALITY_ARGS.get(quality, QUALITY_ARGS["High"]),
            "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2", "-pix_fmt", "yuv420p",
            "-c:a", "aac",
        ]
    args.append(str(output))
    return args


def build_gif_args(
    ffmpeg: str,
    source: Path,
    output: Path,
    width: str,
    fps: int,
    start: str = "",
    end: str = "",
) -> list[str]:
    if width not in {"480", "640", "800", "original"}:
        raise ValueError("GIF width must be 480, 640, 800, or original.")
    if fps not in {10, 15, 24}:
        raise ValueError("GIF frame rate must be 10, 15, or 24 FPS.")
    args = _progress_args(ffmpeg)
    if start:
        parse_time_ms(start)
        args += ["-ss", start]
    args += ["-i", str(source)]
    if end:
        parse_time_ms(end)
        args += ["-to", end]
    scale = "" if width == "original" else f"scale={width}:-1:flags=lanczos,"
    filter_graph = (
        f"[0:v]fps={fps},{scale}split[s0][s1];"
        "[s0]palettegen=stats_mode=diff[p];[s1][p]paletteuse=dither=sierra2_4a"
    )
    args += ["-filter_complex", filter_graph, "-loop", "0", str(output)]
    return args


def build_compress_args(
    ffmpeg: str,
    source: Path,
    output: Path,
    quality: str,
    output_format: str,
) -> list[str]:
    if output_format not in {"mp4", "webm"}:
        raise ValueError("Compressed output format must be MP4 or WebM.")
    args = _progress_args(ffmpeg) + ["-i", str(source)]
    if output_format == "webm":
        args += [
            "-c:v", "libvpx-vp9", "-crf", WEBM_CRF.get(quality, "36"), "-b:v", "0",
            "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2", "-pix_fmt", "yuv420p",
            "-c:a", "libopus",
        ]
    else:
        args += [
            "-c:v", "libx264", *QUALITY_ARGS.get(quality, QUALITY_ARGS["High"]),
            "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2", "-pix_fmt", "yuv420p",
            "-c:a", "aac",
        ]
    args.append(str(output))
    return args


def progress_percent(line: str, duration_seconds: float | None) -> int | None:
    if not line.startswith("out_time_ms=") or not duration_seconds or duration_seconds <= 0:
        return None
    try:
        elapsed_microseconds = int(line.partition("=")[2])
    except ValueError:
        return None
    return max(0, min(100, round(elapsed_microseconds / (duration_seconds * 1_000_000) * 100)))
