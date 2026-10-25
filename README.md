# Linux Mint Screen Recorder

A lightweight local-first desktop application for Linux Mint 21/22 and compatible Linux desktops. It uses PySide6 for the interface, FFmpeg for X11 screen recording, and Qt's desktop screen-grab API for screenshots. Captures remain on the local machine.

## Current support

- Full X11 desktop recording to MKV, MP4, or WebM; 15/24/30/60 FPS and three quality presets.
- Full-screen or user-selected rectangular-region recording and screenshots.
- Pause/resume/stop, elapsed timer, unique output filenames, and safe stop on close.
- Optional PulseAudio/PipeWire-Pulse source capture and optional default microphone capture (PulseAudio compatibility required).
- PNG/JPEG screenshots with configurable target, delay, preview, optional clipboard copy, and optional window hiding.
- Local media library with cached thumbnails, video durations, search, open/reveal, rename, and safe trash handling.
- Light, dark, and system themes; in-window shortcuts plus optional system-tray controls.
- Optional minimize-to-tray behavior, mouse cursor inclusion setting, and single-instance CLI controls.
- Dependency and session detection with actionable errors.

Selected monitors/windows and true portal-based Wayland capture are not implemented. Global shortcuts are supported through custom desktop shortcuts calling the CLI commands below. On Wayland the app intentionally refuses FFmpeg X11 capture rather than reporting false success; use an X11 session or a portal-capable recorder such as OBS Studio. Choose **Region** in the Dashboard to select a rectangular capture area; the last area is reused for recording segments until reselected.

Screenshot settings include **Screenshot target** (Primary screen, All screens, or Screen under cursor), a 0/3/5/10-second delay, **Hide window before screenshot**, and **Copy screenshot to clipboard**. In Region mode, the screenshot is cropped to the selected area. In the Library, image thumbnails are generated locally, video thumbnails and durations are loaded in the background, and cached files are reused. Deletion asks before moving an item to Trash; if Trash is unavailable, the app asks separately before permanent deletion.

If the application finds segments left by a crash, it offers recovery, deletion, or Later at startup and never deletes them automatically. Recovery checks and verifies the joined recording before removing the segment folder. A clearly corrupt final segment is excluded from the recovered video but preserved in a sibling `.discarded` folder; it is not silently deleted.

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
sudo apt install ./linux-mint-screen-recorder_0.3.0_*.deb
```

The Debian package build needs `python3-pip` and network access to bundle the PySide6 Essentials runtime into the package. The resulting package does not depend on a distro-specific PySide6 package; APT installs only Python, FFmpeg, and Qt's X11 system libraries. The Qt Python runtime is bundled locally with the application. The package filename's architecture suffix is generated for the build machine.

Uninstall the per-user installation with:

```sh
./uninstall.sh
```

This leaves user captures and settings untouched.

## Use

1. Open **Settings** to choose recording/screenshot folders, output format, frame rate, quality, optional audio inputs, and screenshot behavior/target.
2. Click **Record Screen** and then **Stop**, or use `Ctrl+Shift+R`. Pause/resume with `Ctrl+Shift+P`. Pausing ends one file segment and resuming starts another; the app joins the segments when stopped.
3. Click **Take Screenshot** or use `Ctrl+Shift+S`.
4. Find captures in **Library**. Thumbnails and video durations are populated in the background. Double-click to open; use buttons to reveal or rename. Delete asks before moving an item to Trash, and asks again before permanent deletion if Trash fails.

The system tray menu offers start/stop, pause/resume, screenshot, show-window, and quit commands when a tray is available. The **Minimize to tray while recording** setting is on by default and only hides the window when a tray is present.

For global desktop shortcuts, the application supports single-instance CLI commands. In Cinnamon, open **System Settings → Keyboard → Shortcuts → Custom Shortcuts**, add a command for each desired shortcut, for example:

```text
mint-screen-recorder --toggle-record
mint-screen-recorder --toggle-pause
mint-screen-recorder --screenshot
```

These commands contact the current per-user instance; if none is running, they start the app normally and carry out the requested action. Window-local shortcuts remain available. System audio sources are listed when `pactl` is available. Select a monitor source ending in `.monitor` for system playback audio; select a microphone source explicitly for microphone audio. If no source is selected, recording is silent unless the microphone toggle is enabled. The mouse cursor is included by default and can be disabled in Settings.

## Tests

```sh
python3 -m unittest discover -s tests -v
```

Live audio/video tests require a running graphical session, FFmpeg, and (for audio) an available PulseAudio-compatible source. Recorder process lifecycle tests are mocked and run headlessly. Actual screen recording is disabled in unsupported Wayland sessions and tested hardware/session dependent.
