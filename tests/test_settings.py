import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from screen_recorder.settings import DEFAULTS, Settings

APP = QApplication.instance() or QApplication([])


class SettingsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.settings_path = self.root / "settings.json"
        self.location_patch = patch(
            "screen_recorder.settings.QStandardPaths.writableLocation",
            return_value=str(self.root),
        )
        self.location_patch.start()
        self.addCleanup(self.location_patch.stop)

    def test_missing_file_uses_defaults_without_recovery_notice(self):
        settings = Settings()
        self.assertEqual(settings.values, DEFAULTS)
        self.assertIsNone(settings.recovered_from)

    def test_valid_file_loads_known_values(self):
        self.settings_path.write_text(json.dumps({"fps": 60, "theme": "Dark", "show_cursor": False}))
        settings = Settings()
        self.assertEqual(settings.values["fps"], 60)
        self.assertEqual(settings.values["theme"], "Dark")
        self.assertFalse(settings.values["show_cursor"])
        self.assertIsNone(settings.recovered_from)

    def test_corrupt_json_is_backed_up_and_defaults_restored(self):
        self.settings_path.write_text("{bad json")
        backup = self.root / "settings.json.bak"
        backup.write_text("older backup")
        settings = Settings()
        self.assertEqual(settings.values, DEFAULTS)
        self.assertTrue(settings.recovered_from)
        self.assertEqual(backup.read_text(), "{bad json")
        self.assertFalse(self.settings_path.exists())

    def test_non_object_json_is_backed_up(self):
        self.settings_path.write_text("[]")
        settings = Settings()
        self.assertEqual(settings.values, DEFAULTS)
        self.assertTrue(settings.recovered_from)
        self.assertEqual((self.root / "settings.json.bak").read_text(), "[]")

    def test_unreadable_file_falls_back_and_is_backed_up(self):
        self.settings_path.write_text('{"fps": 60}')
        with patch.object(Path, "read_text", side_effect=PermissionError("permission denied")):
            settings = Settings()
        self.assertEqual(settings.values, DEFAULTS)
        self.assertTrue(settings.recovered_from)
        self.assertTrue((self.root / "settings.json.bak").exists())

    def test_invalid_individual_values_fall_back_to_defaults(self):
        self.settings_path.write_text(json.dumps({
            "fps": 120,
            "format": "avi",
            "quality": "Extreme",
            "theme": "Neon",
            "show_cursor": "false",
            "microphone": 1,
            "recordings_dir": 42,
            "screenshots_dir": "/tmp/custom",
            "screenshot_delay": 6,
            "hide_window_for_screenshot": "yes",
            "screenshot_copy_to_clipboard": 1,
            "screenshot_target": "Unknown",
        }))
        settings = Settings()
        self.assertEqual(settings.values["fps"], DEFAULTS["fps"])
        self.assertEqual(settings.values["format"], DEFAULTS["format"])
        self.assertEqual(settings.values["quality"], DEFAULTS["quality"])
        self.assertEqual(settings.values["theme"], DEFAULTS["theme"])
        self.assertEqual(settings.values["show_cursor"], DEFAULTS["show_cursor"])
        self.assertEqual(settings.values["microphone"], DEFAULTS["microphone"])
        self.assertEqual(settings.values["recordings_dir"], DEFAULTS["recordings_dir"])
        self.assertEqual(settings.values["screenshots_dir"], "/tmp/custom")
        self.assertEqual(settings.values["screenshot_delay"], DEFAULTS["screenshot_delay"])
        self.assertEqual(
            settings.values["hide_window_for_screenshot"],
            DEFAULTS["hide_window_for_screenshot"],
        )
        self.assertEqual(
            settings.values["screenshot_copy_to_clipboard"],
            DEFAULTS["screenshot_copy_to_clipboard"],
        )
        self.assertEqual(settings.values["screenshot_target"], DEFAULTS["screenshot_target"])


if __name__ == "__main__":
    unittest.main()
