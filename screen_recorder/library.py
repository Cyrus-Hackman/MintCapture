"""Local capture-library helpers."""

from __future__ import annotations

import hashlib
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QStandardPaths
from PySide6.QtGui import QIcon, QPixmap


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


def duration_cache_path(path: Path) -> Path:
    return cache_root() / "metadata" / f"{thumbnail_cache_key(path)}.txt"


def generate_thumbnail(path: Path) -> Path | None:
    destination = thumbnail_path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    suffix = path.suffix.lower()
    if suffix in IMAGE_EXTENSIONS:
        pixmap = QPixmap(str(path))
        if pixmap.isNull():
            return None
        preview = pixmap.scaled(160, 160, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        if not preview.save(str(destination), "PNG"):
            return None
        return destination
    if suffix in VIDEO_EXTENSIONS:
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            return None
        command = [
            ffmpeg,
            "-ss", "1",
            "-i", str(path),
            "-frames:v", "1",
            "-vf", "scale=160:-1",
            "-y",
            str(destination),
        ]
        result = subprocess.run(command, capture_output=True, check=False)
        if result.returncode != 0:
            return None
        return destination if destination.exists() else None
    return None


def video_duration(path: Path) -> str | None:
    if path.suffix.lower() not in VIDEO_EXTENSIONS:
        return None
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return None
    cache = duration_cache_path(path)
    if cache.exists():
        try:
            return cache.read_text(encoding="utf-8").strip() or None
        except OSError:
            pass
    command = [ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(path)]
    result = subprocess.run(command, capture_output=True, check=False, text=True)
    if result.returncode != 0:
        return None
    duration = result.stdout.strip()
    if not duration:
        return None
    cache.parent.mkdir(parents=True, exist_ok=True)
    try:
        cache.write_text(duration, encoding="utf-8")
    except OSError:
        pass
    return duration


def icon_for_path(path: Path) -> QIcon:
    if not path.exists():
        return QIcon.fromTheme("image-missing")
    cached = None
    try:
        cached = generate_thumbnail(path)
    except (OSError, ValueError):
        cached = None
    if cached and cached.exists():
        return QIcon(str(cached))
    if path.suffix.lower() in VIDEO_EXTENSIONS:
        return QIcon.fromTheme("video-x-generic")
    return QIcon.fromTheme("image-x-generic")


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
