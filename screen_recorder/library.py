"""Local capture-library helpers."""

from __future__ import annotations

import hashlib
import math
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, Qt, QStandardPaths, Signal
from PySide6.QtGui import QIcon, QImage


SUPPORTED = {".mp4", ".mkv", ".webm", ".png", ".jpg", ".jpeg"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg"}
VIDEO_EXTENSIONS = {".mp4", ".mkv", ".webm"}


def cache_root() -> Path:
    return Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.CacheLocation)) / "mint-screen-recorder"


def thumbnail_cache_key(path: Path) -> str:
    stat = path.stat()
    digest = hashlib.sha256(
        f"{path.resolve()}::{stat.st_mtime_ns}::{stat.st_size}".encode("utf-8")
    ).hexdigest()
    return digest


def thumbnail_path(path: Path) -> Path:
    return cache_root() / "thumbnails" / f"{thumbnail_cache_key(path)}.png"


def cached_thumbnail(path: Path) -> Path | None:
    try:
        cached = thumbnail_path(path)
        return cached if cached.is_file() and cached.stat().st_size > 0 else None
    except OSError:
        return None


def duration_cache_path(path: Path) -> Path:
    return cache_root() / "metadata" / f"{thumbnail_cache_key(path)}.txt"


def generate_thumbnail(path: Path) -> Path | None:
    destination = thumbnail_path(path)
    if destination.is_file() and destination.stat().st_size > 0:
        return destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    suffix = path.suffix.lower()
    if suffix in IMAGE_EXTENSIONS:
        image = QImage(str(path))
        if image.isNull():
            return None
        preview = image.scaled(
            160,
            160,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        if not preview.save(str(destination), "PNG"):
            return None
        return destination
    if suffix in VIDEO_EXTENSIONS:
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            return None
        for seek in ("1", "0"):
            command = [
                ffmpeg,
                "-loglevel", "error",
                "-ss", seek,
                "-i", str(path),
                "-frames:v", "1",
                "-vf", "scale=160:-1",
                "-y",
                str(destination),
            ]
            try:
                result = subprocess.run(command, capture_output=True, check=False, timeout=15)
            except subprocess.TimeoutExpired:
                _remove_partial_thumbnail(destination)
                if seek == "1":
                    continue
                return None
            except OSError:
                _remove_partial_thumbnail(destination)
                return None
            if result.returncode == 0 and destination.is_file() and destination.stat().st_size > 0:
                return destination
            _remove_partial_thumbnail(destination)
        return None
    return None


def _remove_partial_thumbnail(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def video_duration(path: Path) -> str | None:
    if path.suffix.lower() not in VIDEO_EXTENSIONS:
        return None
    cache = duration_cache_path(path)
    try:
        duration = cache.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    try:
        return duration if math.isfinite(float(duration)) and float(duration) > 0 else None
    except ValueError:
        return None


def generate_duration(path: Path) -> str | None:
    if path.suffix.lower() not in VIDEO_EXTENSIONS:
        return None
    cached = video_duration(path)
    if cached:
        return cached
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return None
    command = [
        ffprobe, "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", str(path),
    ]
    try:
        result = subprocess.run(command, capture_output=True, check=False, text=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    duration = result.stdout.strip()
    if not duration:
        return None
    cache = duration_cache_path(path)
    try:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(duration, encoding="utf-8")
    except OSError:
        return None
    return duration


def icon_for_path(path: Path) -> QIcon:
    cached = cached_thumbnail(path)
    if cached:
        return QIcon(str(cached))
    if path.suffix.lower() in VIDEO_EXTENSIONS:
        return QIcon.fromTheme("video-x-generic")
    return QIcon.fromTheme("image-x-generic")


def prune_cache(max_files: int = 500) -> None:
    root = cache_root()
    try:
        files = [path for path in root.rglob("*") if path.is_file()]
        if len(files) <= max_files:
            return
        files.sort(key=lambda path: path.stat().st_mtime_ns)
        for path in files[:len(files) - max_files]:
            try:
                path.unlink()
            except OSError:
                continue
    except OSError:
        return


class LibraryWorkerSignals(QObject):
    completed = Signal(str, str, str)


class LibraryWorker(QRunnable):
    def __init__(self, path: Path) -> None:
        super().__init__()
        self.path = path
        self.signals = LibraryWorkerSignals()

    def run(self) -> None:
        thumbnail = ""
        duration_text = ""
        try:
            result = generate_thumbnail(self.path)
            if result:
                thumbnail = str(result)
        except (OSError, ValueError):
            pass
        try:
            duration = generate_duration(self.path)
            if duration:
                total_seconds = float(duration)
                minutes, seconds = divmod(int(total_seconds), 60)
                hours, minutes = divmod(minutes, 60)
                duration_text = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        except (OSError, ValueError):
            pass
        self.signals.completed.emit(str(self.path), thumbnail, duration_text)


class CachePruneWorker(QRunnable):
    def run(self) -> None:
        prune_cache()


def captures(directories: list[Path]) -> list[Path]:
    files = [item for directory in directories if directory.exists() for item in directory.iterdir()
             if item.is_file() and item.suffix.lower() in SUPPORTED]
    return sorted(files, key=lambda item: item.stat().st_mtime, reverse=True)


def describe(path: Path) -> str:
    stat = path.stat()
    size = stat.st_size
    units = ("B", "KB", "MB", "GB")
    index = 0
    amount = float(size)
    while amount >= 1024 and index < len(units) - 1:
        amount /= 1024
        index += 1
    date = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M")
    duration = video_duration(path)
    if duration:
        total_seconds = float(duration)
        minutes, seconds = divmod(int(total_seconds), 60)
        hours, minutes = divmod(minutes, 60)
        duration_text = f"  •  {hours:02d}:{minutes:02d}:{seconds:02d}"
    else:
        duration_text = ""
    return f"{date}  •  {amount:.1f} {units[index]}{duration_text}"
