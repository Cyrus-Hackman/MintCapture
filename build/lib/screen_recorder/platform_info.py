"""Platform and dependency detection."""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass


@dataclass(frozen=True)
class PlatformInfo:
    session_type: str
    ffmpeg: str | None
    ffplay: str | None
    audio_devices: tuple[str, ...]


def detect_platform() -> PlatformInfo:
    session = os.environ.get("XDG_SESSION_TYPE", "").lower()
    if not session:
        session = "wayland" if os.environ.get("WAYLAND_DISPLAY") else "x11"
    audio_devices: list[str] = []
    pactl = shutil.which("pactl")
    if pactl:
        try:
            result = subprocess.run(
                [pactl, "list", "short", "sources"],
                capture_output=True,
                text=True,
                timeout=3,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            result = None
        if result and result.returncode == 0:
            audio_devices = [line.split("\t", 2)[1] for line in result.stdout.splitlines() if len(line.split("\t")) > 1]
    return PlatformInfo(session, shutil.which("ffmpeg"), shutil.which("ffplay"), tuple(audio_devices))
