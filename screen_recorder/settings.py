"""Persistent user preferences."""

from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import QStandardPaths


DEFAULTS = {
    "recordings_dir": str(Path.home() / "Videos" / "ScreenRecorder"),
    "screenshots_dir": str(Path.home() / "Pictures" / "Screenshots"),
    "format": "mkv",
    "screenshot_format": "png",
    "fps": 30,
    "quality": "High",
    "theme": "System",
    "audio_source": "",
    "microphone_source": "",
    "microphone": False,
}


class Settings:
    def __init__(self) -> None:
        base = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppConfigLocation))
        base.mkdir(parents=True, exist_ok=True)
        self.path = base / "settings.json"
        self.values = DEFAULTS.copy()
        if self.path.exists():
            try:
                stored = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(stored, dict):
                    self.values.update({k: v for k, v in stored.items() if k in DEFAULTS})
            except (OSError, json.JSONDecodeError) as exc:
                raise RuntimeError(f"Could not read settings file {self.path}: {exc}") from exc

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.values, indent=2), encoding="utf-8")
        temporary.replace(self.path)
