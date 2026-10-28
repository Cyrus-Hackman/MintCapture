import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QPointF, QRect, Qt
from PySide6.QtGui import QKeyEvent, QMouseEvent, QPaintEvent
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

    def test_drag_and_release_emits_selected(self):
        selector = RegionSelector()
        selected_regions = []
        selector.selected.connect(selected_regions.append)

        press = QMouseEvent(
            QMouseEvent.Type.MouseButtonPress,
            QPointF(20, 30),
            QPointF(20, 30),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        selector.mousePressEvent(press)

        move = QMouseEvent(
            QMouseEvent.Type.MouseMove,
            QPointF(120, 150),
            QPointF(120, 150),
            Qt.MouseButton.NoButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        selector.mouseMoveEvent(move)

        release = QMouseEvent(
            QMouseEvent.Type.MouseButtonRelease,
            QPointF(120, 150),
            QPointF(120, 150),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
        )
        selector.mouseReleaseEvent(release)

        self.assertEqual(len(selected_regions), 1)
        self.assertEqual(selected_regions[0], QRect(20, 30, 101, 121))

    def test_right_click_cancels_selection(self):
        selector = RegionSelector()
        cancelled = []
        selector.cancelled.connect(lambda: cancelled.append(True))

        right = QMouseEvent(
            QMouseEvent.Type.MouseButtonPress,
            QPointF(10, 10),
            QPointF(10, 10),
            Qt.MouseButton.RightButton,
            Qt.MouseButton.RightButton,
            Qt.KeyboardModifier.NoModifier,
        )
        selector.mousePressEvent(right)
        self.assertEqual(cancelled, [True])

    def test_escape_cancels_selection(self):
        selector = RegionSelector()
        cancelled = []
        selector.cancelled.connect(lambda: cancelled.append(True))

        key = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier)
        selector.keyPressEvent(key)
        self.assertEqual(cancelled, [True])

    def test_paint_event_runs_without_error(self):
        selector = RegionSelector()
        selector.resize(800, 600)
        selector.show()
        APP.processEvents()

        # Set selection and render
        selector._origin = QPoint(10, 10)
        selector._current = QPoint(200, 200)
        selector._selection = QRect(selector._origin, selector._current)
        selector.update()
        APP.processEvents()
        selector.close()


if __name__ == "__main__":
    unittest.main()
