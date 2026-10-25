"""Local capture-library helpers."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path


SUPPORTED = {".mp4", ".mkv", ".webm", ".png", ".jpg", ".jpeg"}


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
    return f"{date}  •  {amount:.1f} {units[index]}"
