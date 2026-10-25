# Linux Mint Screen Recorder

A lightweight local-first desktop application for Linux Mint 21/22 and compatible Linux desktops. It uses PySide6 for the interface, FFmpeg for X11 screen recording, and Qt's desktop screen-grab API for screenshots. Captures remain on the local machine.

## Current support

- Full X11 desktop recording to MKV, MP4, or WebM; 15/24/30/60 FPS and three quality presets.
- Pause/resume/stop, elapsed timer, unique output filenames, and safe stop on close.
- Optional PulseAudio/PipeWire-Pulse source capture and optional default microphone capture (PulseAudio compatibility required).
- Full desktop PNG/JPEG screenshots, preview, local media library, search, open/reveal, rename, and confirmed deletion.
- Light, dark, and system themes; keyboard shortcuts while the application window is active.
- Dependency and session detection with actionable errors.

Custom regions, selected monitors/windows, global desktop shortcuts, clipboard, and true portal-based Wayland capture are not implemented in this MVP. On Wayland the app intentionally refuses FFmpeg X11 capture rather than reporting false success; use an X11 session or a portal-capable recorder such as OBS Studio. The screenshot currently captures the primary screen.

## Install on Linux Mint

Install OS dependencies (no root Python package modifications):

```sh
sudo apt update
sudo apt install python3 python3-venv python3-pip ffmpeg pulseaudio-utils libxcb-cursor0 libxkbcommon-x11-0
```

From the downloaded/cloned project directory:

```sh
./check-dependencies.sh
./install.sh
```

The installer creates an isolated virtual environment under `~/.local/opt`, installs the application menu launcher, and does not modify system Python packages. Launch from the application menu or run:

```sh
~/.local/bin/mint-screen-recorder
```

To run from source in a development virtual environment:

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e .
python main.py
```

An optional Debian package can be built on Debian/Ubuntu/Mint:

```sh
sudo apt install dpkg-dev python3-pip
./build-deb.sh
sudo apt install ./linux-mint-screen-recorder_0.1.1_amd64.deb
```

The Debian package build needs `python3-pip` and network access to bundle the PySide6 Essentials runtime into the package. The resulting package does not depend on a distro-specific PySide6 package; APT installs only Python, FFmpeg, and Qt's X11 system libraries. The Qt Python runtime is bundled locally with the application. The package filename's architecture suffix is generated for the build machine.

Uninstall the per-user installation with:

```sh
./uninstall.sh
```

This leaves user captures and settings untouched.

## Use

1. Open **Settings** to choose recording/screenshot folders, output format, frame rate, quality, and optional audio inputs.
2. Click **Record Screen** and then **Stop**, or use `Ctrl+Shift+R`. Pause/resume with `Ctrl+Shift+P`.
3. Click **Take Screenshot** or use `Ctrl+Shift+S`.
4. Find captures in **Library**. Double-click to open; use buttons to reveal, rename, or delete after confirmation.

Shortcuts are window-local because reliable global shortcut registration varies by Cinnamon/MATE/Xfce and Wayland policy. System audio sources are listed when `pactl` is available. Select a monitor source ending in `.monitor` for system playback audio; select a microphone source explicitly for microphone audio. If no source is selected, recording is silent unless the microphone toggle is enabled.

## Tests

```sh
python3 -m unittest discover -s tests -v
```

Live audio/video tests require a running graphical session, FFmpeg, and (for audio) an available PulseAudio-compatible source. Actual screen recording is disabled in unsupported Wayland sessions and tested hardware/session dependent.
# MintCapture
