#!/usr/bin/env bash
set -euo pipefail

APP_ID="linux-mint-screen-recorder"
SOURCE_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR="${HOME}/.local/opt/${APP_ID}"
BIN_DIR="${HOME}/.local/bin"
APP_DIR="${HOME}/.local/share/applications"
ICON_DIR="${HOME}/.local/share/icons/hicolor/scalable/apps"
VENV_DIR="${INSTALL_DIR}/.venv"

if ! command -v python3 >/dev/null || ! command -v ffmpeg >/dev/null; then
    echo "Install system dependencies first: sudo apt install python3 python3-venv python3-pip ffmpeg libxcb-cursor0 libxkbcommon-x11-0"
    exit 1
fi
mkdir -p "${INSTALL_DIR}" "${BIN_DIR}" "${APP_DIR}" "${ICON_DIR}"
cp -a "${SOURCE_DIR}/screen_recorder" "${INSTALL_DIR}/"
find "${INSTALL_DIR}/screen_recorder" -type d -name __pycache__ -prune -exec rm -rf -- {} +
cp "${SOURCE_DIR}/main.py" "${INSTALL_DIR}/"
python3 -m venv "${VENV_DIR}"
"${VENV_DIR}/bin/pip" install "${SOURCE_DIR}"
install -m 644 "${SOURCE_DIR}/assets/linux-mint-screen-recorder.svg" "${ICON_DIR}/${APP_ID}.svg"
cat > "${BIN_DIR}/mint-screen-recorder" <<EOF
#!/usr/bin/env bash
exec "${VENV_DIR}/bin/mint-screen-recorder" "\$@"
EOF
chmod 755 "${BIN_DIR}/mint-screen-recorder"
sed "s|@HOME@|${HOME}|g" "${SOURCE_DIR}/packaging/linux-mint-screen-recorder.desktop.in" > "${APP_DIR}/${APP_ID}.desktop"
echo "Installed. Launch with: ${BIN_DIR}/mint-screen-recorder"
echo "If ~/.local/bin is not on PATH, use the full path above or launch it from the application menu."
