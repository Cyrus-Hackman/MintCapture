import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from screen_recorder.region import RegionSelector

APP = QApplication.instance() or QApplication([])


class RegionSelectorTests(unittest.TestCase):
    def test_region_selector_opens_and_closes_offscreen(self):
        selector = RegionSelector()
        self.assertTrue(selector.geometry().isValid())
        selector.show()
        APP.processEvents()
        self.assertTrue(selector.isVisible())
        selector.close()


if __name__ == "__main__":
    unittest.main()
