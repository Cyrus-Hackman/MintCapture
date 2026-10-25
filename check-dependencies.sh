#!/usr/bin/env bash
set -u
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
missing=0
for bin in python3 ffmpeg; do
    if command -v "$bin" >/dev/null; then
        printf 'OK   %s: %s\n' "$bin" "$(command -v "$bin")"
    else
        printf 'MISS %s\n' "$bin"
        missing=1
    fi
done
PYTHON=python3
if [ -x "${SCRIPT_DIR}/.venv/bin/python" ]; then
    PYTHON="${SCRIPT_DIR}/.venv/bin/python"
fi
"$PYTHON" -c 'import PySide6; print("OK   PySide6:", PySide6.__version__)' 2>/dev/null || {
    echo "MISS PySide6 (install in a virtual environment with: python3 -m pip install PySide6)"
    missing=1
}
for package in libxcb-cursor0 libxkbcommon-x11-0; do
    if dpkg-query -W -f='${Status}' "$package" 2>/dev/null | grep -q 'install ok installed'; then
        printf 'OK   %s\n' "$package"
    else
        printf 'MISS %s (install with: sudo apt install %s)\n' "$package" "$package"
        missing=1
    fi
done
printf 'Session: %s\n' "${XDG_SESSION_TYPE:-unknown}"
if command -v pactl >/dev/null; then
    echo "Audio sources:"
    pactl list short sources || true
else
    echo "Optional audio discovery unavailable (install pulseaudio-utils)."
fi
exit "$missing"
