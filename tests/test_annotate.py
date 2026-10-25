import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import (
    QApplication, QGraphicsEllipseItem, QGraphicsPathItem, QGraphicsPixmapItem,
    QGraphicsRectItem, QGraphicsTextItem,
)

from screen_recorder.annotate import AnnotationEditor, ArrowItem, render_scene

APP = QApplication.instance() or QApplication([])


def save_checkerboard(path: Path, width=80, height=60) -> None:
    image = QImage(width, height, QImage.Format.Format_RGB32)
    for y in range(height):
        for x in range(width):
            image.setPixelColor(x, y, QColor("white" if (x + y) % 2 else "black"))
    image.save(str(path))


class AnnotationTests(unittest.TestCase):
    def test_adds_each_annotation_item_type(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.png"
            save_checkerboard(source)
            editor = AnnotationEditor(source)
            rect = QRectF(5, 5, 20, 15)
            items = [
                editor.add_annotation("arrow", rect),
                editor.add_annotation("rectangle", rect),
                editor.add_annotation("ellipse", rect),
                editor.add_annotation("pen", rect),
                editor.add_annotation("text", rect, "label"),
                editor.add_annotation("highlighter", rect),
                editor.add_annotation("pixelate", rect),
            ]
            self.assertIsInstance(items[0], ArrowItem)
            self.assertIsInstance(items[1], QGraphicsRectItem)
            self.assertIsInstance(items[2], QGraphicsEllipseItem)
            self.assertIsInstance(items[3], QGraphicsPathItem)
            self.assertIsInstance(items[4], QGraphicsTextItem)
            self.assertIsInstance(items[5], QGraphicsRectItem)
            self.assertIsInstance(items[6], QGraphicsPixmapItem)
            editor.undo_stack.setClean()
            editor.close()

    def test_undo_and_redo_stacks_restore_items(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.png"
            save_checkerboard(source)
            editor = AnnotationEditor(source)
            item = editor.add_annotation("rectangle", QRectF(2, 3, 20, 10))
            self.assertIn(item, editor.scene.items())
            editor.undo_stack.undo()
            self.assertNotIn(item, editor.scene.items())
            editor.undo_stack.redo()
            self.assertIn(item, editor.scene.items())
            editor.undo_stack.setClean()
            editor.close()

    def test_rendered_image_matches_original_dimensions(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.png"
            save_checkerboard(source, 91, 57)
            editor = AnnotationEditor(source)
            self.assertEqual(render_scene(editor.scene).size(), editor.background.size())
            editor.close()

    def test_save_as_new_never_overwrites(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.png"
            save_checkerboard(source)
            existing = Path(directory) / "source-annotated.png"
            existing.write_bytes(b"original output")
            editor = AnnotationEditor(source)
            output = editor.save_as_new()
            self.assertNotEqual(output, existing)
            self.assertEqual(existing.read_bytes(), b"original output")
            self.assertTrue(output.is_file())
            editor.close()

    def test_pixelate_changes_only_pixels_within_selected_region(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.png"
            save_checkerboard(source)
            editor = AnnotationEditor(source)
            before = render_scene(editor.scene)
            editor.add_annotation("pixelate", QRectF(10, 10, 30, 20))
            after = render_scene(editor.scene)
            inside_differences = [
                (x, y)
                for y in range(10, 30)
                for x in range(10, 40)
                if before.pixelColor(x, y) != after.pixelColor(x, y)
            ]
            self.assertTrue(inside_differences)
            self.assertEqual(before.pixelColor(50, 40), after.pixelColor(50, 40))
            editor.undo_stack.setClean()
            editor.close()


if __name__ == "__main__":
    unittest.main()
