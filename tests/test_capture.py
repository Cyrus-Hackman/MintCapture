import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from screen_recorder.capture import save_screenshot, unique_path
from screen_recorder.library import captures

APP = QApplication.instance() or QApplication([])


class CaptureTests(unittest.TestCase):
    def test_unique_path_never_overwrites(self):
        with tempfile.TemporaryDirectory() as directory:
            first = unique_path(Path(directory), "png", "test")
            first.touch()
            second = unique_path(Path(directory), "png", "test")
            self.assertNotEqual(first, second)
            self.assertEqual(second.name, "test-1.png")

    def test_library_filters_supported_media(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "image.png").touch()
            (root / "video.mkv").touch()
            (root / "notes.txt").touch()
            self.assertEqual({p.suffix for p in captures([root])}, {".png", ".mkv"})

    def test_screenshot_saves_png_and_jpeg(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for image_format, suffix in (("png", ".png"), ("jpg", ".jpg")):
                path = save_screenshot(root, image_format)
                self.assertEqual(path.suffix, suffix)
                self.assertGreater(path.stat().st_size, 0)


if __name__ == "__main__":
    unittest.main()
