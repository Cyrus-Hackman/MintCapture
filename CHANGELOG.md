# Changelog

## 0.3.0

- Load Library thumbnails and video durations asynchronously, with cache reuse and pruning.
- Make interrupted-recording recovery safer by preserving uncertain segments and quarantining a corrupt trailing segment.
- Confirm moving captures to Trash, with a separate confirmation before permanent deletion.
- Refresh the cached Library listing when its folders change.
- Add rectangular region recording and screenshots, with pause/resume reusing the chosen area.
- Document screenshot targets, delay, clipboard, and recovery behavior.

## 0.2.0

- Add a PySide6 desktop interface with X11 screen recording and screenshot capture.
- Add FFmpeg format, quality, frame-rate, and audio settings.
- Add recording pause/resume segments, crash recovery, a system tray, and single-instance CLI controls.
- Add screenshot settings and a searchable local capture library.
