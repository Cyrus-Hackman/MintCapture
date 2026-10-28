<div align="center">

<img src="assets/linux-mint-screen-recorder.svg" alt="MintCapture Logo" width="128" height="128">

# MintCapture

**Linux Mint Screen Recorder & Snipping Studio**

*A lightweight, privacy-first desktop application crafted for Linux Mint and Debian-based desktops. Record screens, capture custom region screenshots, annotate captures, and edit videos—all locally.*

<p align="center">
  <img src="https://img.shields.io/badge/Platform-Linux%20Mint%20%7C%20Ubuntu%20%7C%20Debian-87cf3e?style=for-the-badge&logo=linuxmint&logoColor=white" alt="Platform">
  <img src="https://img.shields.io/badge/Python-3.10%2B-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/UI-PySide6%20%28Qt%206%29-41CD52?style=for-the-badge&logo=qt&logoColor=white" alt="PySide6">
  <img src="https://img.shields.io/badge/Engine-FFmpeg-007808?style=for-the-badge&logo=ffmpeg&logoColor=white" alt="FFmpeg">
  <img src="https://img.shields.io/badge/Privacy-100%25%20Local-blueviolet?style=for-the-badge" alt="Privacy">
</p>

</div>

---

## ✨ Features

### 🎥 Screen Recording
- **Flexible Modes**: Record your **Full Screen**, a **Custom Rectangular Region**, or select an **Active Window** (X11).
- **Multiple Formats**: Export clean video files in **MKV**, **MP4**, or **WebM**.
- **Frame Rate & Quality Controls**: Choose from 15, 24, 30, or 60 FPS, with **High**, **Medium**, or **Low** compression presets.
- **Pause & Resume**: Seamlessly pause long recordings and resume anytime; segments are joined smoothly upon stopping.

### ✂️ Screenshots & Portion Snipping
- **Interactive Region Snipping**: Click **Select Portion** or press `Ctrl+Shift+A` to draw a box around any part of your screen with real-time dimension feedback.
- **Configurable Target**: Capture Primary Screen, All Connected Monitors, or Screen Under Cursor.
- **Countdown Timer**: 0, 3, 5, or 10-second delay with status bar countdown.
- **Workflow Friendly**: Auto-copy screenshots to clipboard and optionally hide the main window during captures.

### 🎙️ Audio Capture
- Capture system audio output (loopback via PulseAudio or PipeWire-Pulse).
- Record microphone commentary alongside desktop audio.
- Automatically enumerates active audio devices and sources.

### 🎨 Screenshot Annotation Studio
- Built-in graphics editor for quick markups.
- Add **rectangles**, **ellipses**, **arrows**, **lines**, **freehand drawings**, and **styled text**.
- Color palette selection, thickness controls, and full undo/redo stack.

### 🎞️ Video Processing
- **Trim Videos**: Cut start and end timestamps directly within the Library.
- **GIF Generation**: Convert recording clips to animated GIFs for documentation and chat.
- **Video Compression**: Shrink video file sizes without leaving the application.

### 🛡️ Crash & Interruption Recovery
- Unfinished recordings caused by power loss or system interruption are automatically detected at startup.
- Inspect and reconstruct interrupted sessions with 1-click recovery.

---

## ⌨️ Shortcuts & Hotkeys

| Shortcut | Action | Description |
| :--- | :--- | :--- |
| <kbd>Ctrl</kbd> + <kbd>Shift</kbd> + <kbd>R</kbd> | **Start / Stop Recording** | Toggles screen video recording |
| <kbd>Ctrl</kbd> + <kbd>Shift</kbd> + <kbd>P</kbd> | **Pause / Resume** | Pauses or resumes the active recording segment |
| <kbd>Ctrl</kbd> + <kbd>Shift</kbd> + <kbd>S</kbd> | **Take Screenshot** | Captures the configured target (full screen / monitor) |
| <kbd>Ctrl</kbd> + <kbd>Shift</kbd> + <kbd>A</kbd> | **Select Portion** | Interactively snip a portion of the screen |
| <kbd>Esc</kbd> / <kbd>Right Click</kbd> | **Cancel Selection** | Aborts interactive region selection overlay |

---

## 🚀 Installation on Linux Mint

### 1. Install System Dependencies

Open a terminal and install required packages:

```bash
sudo apt update
sudo apt install python3 python3-venv python3-pip ffmpeg pulseaudio-utils libxcb-cursor0 libxkbcommon-x11-0

# Recommended: enables window-selection mode on X11
sudo apt install x11-utils
```

### 2. Install the Application

Clone or download the repository, then run the installer:

```bash
git clone https://github.com/Cyrus-Hackman/MintCapture.git
cd MintCapture

./check-dependencies.sh
./install.sh
```

The installer:
- Creates an isolated Python virtual environment in `~/.local/opt/linux-mint-screen-recorder`.
- Installs the user executable into `~/.local/bin/mint-screen-recorder`.
- Adds an application icon and desktop launcher to your Mint menu under **Sound & Video**.

### 3. Launching

Launch **Screen Recorder** from your application menu, or run:

```bash
~/.local/bin/mint-screen-recorder
```

*(If `~/.local/bin` is on your `$PATH`, you can simply run `mint-screen-recorder`)*.

---

## 🖥️ Global Desktop Shortcuts

To trigger recording or snipping from anywhere in Cinnamon or GNOME, add custom shortcuts in **System Settings → Keyboard → Shortcuts → Custom Shortcuts**:

| Name | Command | Recommended Shortcut |
| :--- | :--- | :--- |
| **Record Screen** | `mint-screen-recorder --toggle-record` | <kbd>Super</kbd> + <kbd>Alt</kbd> + <kbd>R</kbd> |
| **Pause Recording** | `mint-screen-recorder --toggle-pause` | <kbd>Super</kbd> + <kbd>Alt</kbd> + <kbd>P</kbd> |
| **Full Screenshot** | `mint-screen-recorder --screenshot` | <kbd>Print</kbd> |
| **Snip Screen Portion** | `mint-screen-recorder --screenshot-portion` | <kbd>Shift</kbd> + <kbd>Print</kbd> |

These commands connect to the existing running application instance via a local IPC socket. If the application is not running, it launches automatically.

---

## 📦 Building a Debian Package (`.deb`)

To produce an installable Debian package for deployment across machines:

```bash
sudo apt install dpkg-dev python3-pip
./build-deb.sh
sudo apt install ./linux-mint-screen-recorder_*.deb
```

---

## 🛠️ Development Setup

To run directly from source:

```bash
git clone https://github.com/Cyrus-Hackman/MintCapture.git
cd MintCapture

python3 -m venv .venv
source .venv/bin/activate
pip install -e .

python3 main.py
```

### Running the Test Suite

```bash
.venv/bin/python3 -m unittest discover -s tests -v
```

---

## 🗑️ Uninstallation

To remove the local user installation:

```bash
./uninstall.sh
```

*Note: Your recordings and screenshot files in `~/Videos` and `~/Pictures` will remain untouched.*

---

<div align="center">
  <sub>Built for the Linux Mint community • Local-First • Privacy-Focused</sub>
</div>
