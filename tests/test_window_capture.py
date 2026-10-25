import unittest

from PySide6.QtCore import QRect

from screen_recorder.window_capture import (
    parse_xwininfo_geometry, physical_rect_to_capture_geometry,
)


class WindowCaptureTests(unittest.TestCase):
    def test_parse_decorated_window_geometry(self):
        output = """xwininfo: Window id: 0x4600007 \"Terminal\"
  Absolute upper-left X:  42
  Absolute upper-left Y:  71
  Relative upper-left X:  1
  Relative upper-left Y:  23
  Width:  900
  Height:  600
"""
        self.assertEqual(parse_xwininfo_geometry(output), QRect(42, 71, 900, 600))

    def test_parse_negative_monitor_coordinates(self):
        output = """  Absolute upper-left X: -1880
  Absolute upper-left Y: -20
  Width: 1920
  Height: 1080
"""
        self.assertEqual(parse_xwininfo_geometry(output), QRect(-1880, -20, 1920, 1080))

    def test_invalid_or_cancelled_window_output_returns_none(self):
        self.assertIsNone(parse_xwininfo_geometry("No window selected"))
        self.assertIsNone(parse_xwininfo_geometry("Width: 0\nHeight: 10"))

    def test_physical_window_geometry_is_not_dpi_scaled_again(self):
        self.assertEqual(
            physical_rect_to_capture_geometry(QRect(-400, 20, 801, 601)),
            (-400, 20, 800, 600),
        )

    def test_physical_window_geometry_enforces_minimum_dimensions(self):
        self.assertEqual(
            physical_rect_to_capture_geometry(QRect(2, 4, 1, 3)),
            (2, 4, 16, 16),
        )


if __name__ == "__main__":
    unittest.main()
