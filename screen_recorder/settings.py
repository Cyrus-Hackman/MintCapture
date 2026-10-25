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
    "show_cursor": True,
    "minimize_to_tray": True,
}
VALID_VALUES = {
    "format": {"mkv", "mp4", "webm"},
    "screenshot_format": {"png", "jpg"},
    "fps": {15, 24, 30, 60},
    "quality": {"High", "Medium", "Low"},
    "theme": {"System", "Light", "Dark"},
}
BOOLEAN_KEYS = {"microphone", "show_cursor", "minimize_to_tray"}
STRING_KEYS = {
    "recordings_dir", "screenshots_dir", "format", "screenshot_format",
    "quality", "theme", "audio_source", "microphone_source",
}


class Settings:
    def __init__(self) -> None:
        base = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppConfigLocation))
        base.mkdir(parents=True, exist_ok=True)
        self.path = base / "settings.json"
        self.values = DEFAULTS.copy()
        self.recovered_from: str | None = None
        if self.path.exists():
            try:
                stored = json.loads(self.path.read_text(encoding="utf-8"))
                if not isinstance(stored, dict):
                    raise ValueError("settings root must be a JSON object")
                for key, value in stored.items():
                    if key not in DEFAULTS or not self._valid_value(key, value):
                        continue
                    self.values[key] = value
            except (OSError, json.JSONDecodeError, ValueError) as exc:
                self._recover(exc)

    @staticmethod
    def _valid_value(key: str, value: object) -> bool:
        if key in BOOLEAN_KEYS:
            return isinstance(value, bool)
        if key == "fps":
            return type(value) is int and value in VALID_VALUES[key]
        if key in STRING_KEYS:
            return isinstance(value, str) and (key not in VALID_VALUES or value in VALID_VALUES[key])
        return False

    def _recover(self, error: Exception) -> None:
        backup = self.path.with_suffix(self.path.suffix + ".bak")
        try:
            self.path.replace(backup)
            self.recovered_from = f"Invalid settings were moved to {backup.name}; defaults were restored."
        except OSError as backup_error:
            self.recovered_from = (
                f"Could not read settings ({error}) and could not back them up ({backup_error}); "
                "defaults are being used."
            )

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.values, indent=2), encoding="utf-8")
        temporary.replace(self.path)
