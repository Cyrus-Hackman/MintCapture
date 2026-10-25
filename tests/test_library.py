import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QListWidget, QListWidgetItem, QMessageBox

from screen_recorder.app import MainWindow
from screen_recorder.library import (
    describe, generate_thumbnail, prune_cache, thumbnail_cache_key,
    thumbnail_path,
)

APP = QApplication.instance() or QApplication([])


class LibraryTests(unittest.TestCase):
    def test_thumbnail_cache_key_changes_with_file_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sample.mkv"
            path.write_bytes(b"video")
            first = thumbnail_cache_key(path)
            new_time = path.stat().st_mtime_ns + 10_000
            os.utime(path, ns=(new_time, new_time))
            second = thumbnail_cache_key(path)
            self.assertNotEqual(first, second)

    def test_thumbnail_cache_hit_skips_ffmpeg(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "sample.mkv"
            path.write_bytes(b"video")
            cached = root / "thumbnail.png"
            cached.write_bytes(b"thumbnail")
            with patch("screen_recorder.library.thumbnail_path", return_value=cached), \
                    patch("screen_recorder.library.subprocess.run") as run:
                self.assertEqual(generate_thumbnail(path), cached)
                run.assert_not_called()

    def test_thumbnail_cache_miss_runs_ffmpeg_once(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "sample.mkv"
            path.write_bytes(b"video")
            cached = root / "thumbnail.png"

            def run(args, **kwargs):
                cached.write_bytes(b"thumbnail")
                return type("Result", (), {"returncode": 0})()

            with patch("screen_recorder.library.thumbnail_path", return_value=cached), \
                    patch("screen_recorder.library.shutil.which", return_value="ffmpeg"), \
                    patch("screen_recorder.library.subprocess.run", side_effect=run) as mocked:
                self.assertEqual(generate_thumbnail(path), cached)
                mocked.assert_called_once()
                self.assertEqual(mocked.call_args.kwargs["timeout"], 15)
                self.assertIn("-loglevel", mocked.call_args.args[0])

    def test_thumbnail_falls_back_to_zero_seek(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "short.webm"
            path.write_bytes(b"video")
            cached = root / "thumbnail.png"
            calls = []

            def run(args, **_kwargs):
                calls.append(args)
                if args[args.index("-ss") + 1] == "0":
                    cached.write_bytes(b"frame")
                return type("Result", (), {"returncode": 0})()

            with patch("screen_recorder.library.thumbnail_path", return_value=cached), \
                    patch("screen_recorder.library.shutil.which", return_value="ffmpeg"), \
                    patch("screen_recorder.library.subprocess.run", side_effect=run):
                self.assertEqual(generate_thumbnail(path), cached)
            self.assertEqual([args[args.index("-ss") + 1] for args in calls], ["1", "0"])

    def test_thumbnail_failure_removes_partial_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "broken.mkv"
            path.write_bytes(b"video")
            cached = root / "thumbnail.png"

            def run(*_args, **_kwargs):
                cached.write_bytes(b"")
                return type("Result", (), {"returncode": 1})()

            with patch("screen_recorder.library.thumbnail_path", return_value=cached), \
                    patch("screen_recorder.library.shutil.which", return_value="ffmpeg"), \
                    patch("screen_recorder.library.subprocess.run", side_effect=run):
                self.assertIsNone(generate_thumbnail(path))
            self.assertFalse(cached.exists())

    def test_thumbnail_timeout_is_handled_and_cleans_partial_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "slow.mkv"
            path.write_bytes(b"video")
            cached = root / "thumbnail.png"

            def timeout(*_args, **_kwargs):
                cached.write_bytes(b"partial")
                raise __import__("subprocess").TimeoutExpired("ffmpeg", 15)

            with patch("screen_recorder.library.thumbnail_path", return_value=cached), \
                    patch("screen_recorder.library.shutil.which", return_value="ffmpeg"), \
                    patch("screen_recorder.library.subprocess.run", side_effect=timeout) as run:
                self.assertIsNone(generate_thumbnail(path))
                self.assertEqual(run.call_count, 2)
                self.assertEqual(
                    [call.args[0][call.args[0].index("-ss") + 1] for call in run.call_args_list],
                    ["1", "0"],
                )
            self.assertFalse(cached.exists())

    def test_describe_does_not_run_ffprobe(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "video.mkv"
            path.write_bytes(b"video")
            with patch("screen_recorder.library.subprocess.run") as run:
                describe(path)
                run.assert_not_called()

    def test_duplicate_library_thumbnail_jobs_are_suppressed(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch("screen_recorder.settings.QStandardPaths.writableLocation", return_value=directory):
            window = MainWindow()
            path = Path(directory) / "video.mkv"
            path.write_bytes(b"video")
            window._library_files = [path]
            with patch.object(window._library_workers, "start") as start:
                window._filter_library_cache()
                window._filter_library_cache()
                self.assertEqual(start.call_count, 1)
                self.assertIn(str(path), window._library_jobs)
            window.close()

    def test_cache_pruning_removes_oldest_files_above_limit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch("screen_recorder.library.cache_root", return_value=root):
                for index in range(502):
                    file_path = root / f"{index:03d}.cache"
                    file_path.write_text("cache")
                    os.utime(file_path, (index, index))
                prune_cache()
            remaining = list(root.iterdir())
            self.assertEqual(len(remaining), 500)
            self.assertFalse((root / "000.cache").exists())
            self.assertFalse((root / "001.cache").exists())

    def test_rename_validates_safe_names(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch("screen_recorder.settings.QStandardPaths.writableLocation", return_value=directory):
            window = MainWindow()
            path = Path(directory) / "capture.png"
            path.write_bytes(b"png")
            item = QListWidgetItem(str(path))
            item.setData(Qt.ItemDataRole.UserRole, str(path))
            window.library = QListWidget()
            window.library.addItem(item)
            window.library.setCurrentItem(item)
            with patch("screen_recorder.app.QInputDialog.getText", return_value=("bad/name", True)), \
                    patch("screen_recorder.app.QMessageBox.warning") as warning:
                window._rename_selected()
            warning.assert_called_once()
            window.close()

    def test_filter_uses_cached_file_list(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch("screen_recorder.settings.QStandardPaths.writableLocation", return_value=directory):
            window = MainWindow()
            window._library_files = [
                Path(directory) / "alpha.png",
                Path(directory) / "beta.webm",
            ]
            for path in window._library_files:
                path.write_bytes(b"data")
            window.search.setText("alpha")
            window._filter_library_cache()
            self.assertEqual(window.library.count(), 1)
            self.assertIn("alpha", window.library.item(0).text())
            window.close()

    def test_delete_selected_falls_back_to_confirmed_delete(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch("screen_recorder.settings.QStandardPaths.writableLocation", return_value=directory):
            window = MainWindow()
            path = Path(directory) / "capture.png"
            path.write_bytes(b"data")
            item = QListWidgetItem(str(path))
            item.setData(Qt.ItemDataRole.UserRole, str(path))
            window.library = QListWidget()
            window.library.addItem(item)
            window.library.setCurrentItem(item)
            with patch("screen_recorder.app.QFile.moveToTrash", return_value=False), \
                    patch("screen_recorder.app.QMessageBox.exec", return_value=QMessageBox.StandardButton.Yes), \
                    patch("screen_recorder.app.QMessageBox.question", return_value=QMessageBox.StandardButton.Yes), \
                    patch.object(window, "_refresh_library"):
                window._delete_selected()
            self.assertFalse(path.exists())
            window.close()

    def test_delete_confirms_before_moving_to_trash(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch("screen_recorder.settings.QStandardPaths.writableLocation", return_value=directory):
            window = MainWindow()
            path = Path(directory) / "capture.png"
            path.write_bytes(b"data")
            item = QListWidgetItem(str(path))
            item.setData(Qt.ItemDataRole.UserRole, str(path))
            window.library = QListWidget()
            window.library.addItem(item)
            window.library.setCurrentItem(item)
            with patch("screen_recorder.app.QMessageBox.exec", return_value=QMessageBox.StandardButton.Yes), \
                    patch("screen_recorder.app.QFile.moveToTrash", return_value=True) as move_to_trash, \
                    patch.object(window, "_refresh_library"):
                window._delete_selected()
            move_to_trash.assert_called_once_with(str(path))
            self.assertTrue(path.exists())
            window.close()

    def test_library_refreshes_when_folder_mtime_changes(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch("screen_recorder.settings.QStandardPaths.writableLocation", return_value=directory):
            window = MainWindow()
            recordings = Path(directory) / "recordings"
            screenshots = Path(directory) / "screenshots"
            recordings.mkdir()
            screenshots.mkdir()
            window.settings.values["recordings_dir"] = str(recordings)
            window.settings.values["screenshots_dir"] = str(screenshots)
            window._refresh_library()
            capture = recordings / "new.png"
            capture.write_bytes(b"data")
            window._check_library_directories()
            self.assertIn(capture, window._library_files)
            window.close()


if __name__ == "__main__":
    unittest.main()
