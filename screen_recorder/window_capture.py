"""X11 window geometry parsing and physical capture dimensions."""

from __future__ import annotations

import re

from PySide6.QtCore import QRect


def parse_xwininfo_geometry(output: str) -> QRect | None:
    fields = {}
    for name in ("Absolute upper-left X", "Absolute upper-left Y", "Width", "Height"):
        match = re.search(rf"^\s*{re.escape(name)}:\s*(-?\d+)\s*$", output, re.MULTILINE)
        if not match:
            return None
        fields[name] = int(match.group(1))
    width = fields["Width"]
    height = fields["Height"]
    if width <= 0 or height <= 0:
        return None
    return QRect(
        fields["Absolute upper-left X"],
        fields["Absolute upper-left Y"],
        width,
        height,
    )


def physical_rect_to_capture_geometry(rect: QRect) -> tuple[int, int, int, int]:
    x = rect.x()
    y = rect.y()
    width = max(16, rect.width() & ~1)
    height = max(16, rect.height() & ~1)
    return x, y, width, height
