import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QListWidget, QListWidgetItem, QMessageBox

from screen_recorder.app import MainWindow
from screen_recorder.library import thumbnail_cache_key

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
                    patch("screen_recorder.app.QMessageBox.question", return_value=QMessageBox.StandardButton.Yes), \
                    patch.object(window, "_refresh_library"):
                window._delete_selected()
            self.assertFalse(path.exists())
            window.close()


if __name__ == "__main__":
    unittest.main()
