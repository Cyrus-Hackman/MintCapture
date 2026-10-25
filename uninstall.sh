#!/usr/bin/env bash
set -euo pipefail
rm -rf -- "${HOME}/.local/opt/linux-mint-screen-recorder"
rm -f -- "${HOME}/.local/bin/mint-screen-recorder"
rm -f -- "${HOME}/.local/share/applications/linux-mint-screen-recorder.desktop"
rm -f -- "${HOME}/.local/share/icons/hicolor/scalable/apps/linux-mint-screen-recorder.svg"
echo "Application removed. User recordings, screenshots, and settings were kept."
