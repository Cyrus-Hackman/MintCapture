#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
VERSION="0.1.1"
ARCH="$(dpkg --print-architecture)"
WORK="$(mktemp -d)"
trap 'rm -rf -- "$WORK"' EXIT
PKG="${WORK}/linux-mint-screen-recorder_${VERSION}_${ARCH}"
mkdir -p "${PKG}/DEBIAN" "${PKG}/opt/linux-mint-screen-recorder" "${PKG}/usr/share/applications" "${PKG}/usr/share/icons/hicolor/scalable/apps" "${PKG}/usr/bin"
cp -a "${ROOT}/screen_recorder" "${PKG}/opt/linux-mint-screen-recorder/"
find "${PKG}/opt/linux-mint-screen-recorder" -type d -name __pycache__ -prune -exec rm -rf -- {} +
python3 -m pip install --disable-pip-version-check --target "${PKG}/opt/linux-mint-screen-recorder/python-deps" -r "${ROOT}/requirements.txt"
install -m 644 "${ROOT}/assets/linux-mint-screen-recorder.svg" "${PKG}/usr/share/icons/hicolor/scalable/apps/linux-mint-screen-recorder.svg"
sed 's|@HOME@|/usr|g; s|/usr/.local/bin/mint-screen-recorder|/usr/bin/mint-screen-recorder|' "${ROOT}/packaging/linux-mint-screen-recorder.desktop.in" > "${PKG}/usr/share/applications/linux-mint-screen-recorder.desktop"
cat > "${PKG}/usr/bin/mint-screen-recorder" <<'EOF'
#!/usr/bin/env bash
export PYTHONPATH="/opt/linux-mint-screen-recorder/python-deps:/opt/linux-mint-screen-recorder${PYTHONPATH:+:$PYTHONPATH}"
exec /usr/bin/python3 -m screen_recorder.app "$@"
EOF
chmod 755 "${PKG}/usr/bin/mint-screen-recorder"
cat > "${PKG}/DEBIAN/control" <<EOF
Package: linux-mint-screen-recorder
Version: ${VERSION}
Section: video
Priority: optional
Architecture: ${ARCH}
Depends: python3 (>= 3.10), ffmpeg, libxcb-cursor0, libxkbcommon-x11-0
Maintainer: Local User
Description: Local screen recording and screenshot application
EOF
dpkg-deb --root-owner-group --build "$PKG" "${ROOT}/linux-mint-screen-recorder_${VERSION}_${ARCH}.deb"
echo "Built ${ROOT}/linux-mint-screen-recorder_${VERSION}_${ARCH}.deb"
