"""Screenshot annotation editor backed by QGraphicsScene."""

from __future__ import annotations

import math
from pathlib import Path

from PySide6.QtCore import QPointF, QRect, QRectF, Qt
from PySide6.QtGui import (
    QBrush, QColor, QImage, QPainter, QPainterPath, QPen, QPixmap, QUndoCommand,
    QUndoStack, QPolygonF, QKeySequence, QShortcut,
)
from PySide6.QtWidgets import (
    QApplication, QComboBox, QDialog, QGraphicsEllipseItem, QGraphicsItem,
    QGraphicsLineItem, QGraphicsPathItem, QGraphicsPixmapItem, QGraphicsRectItem,
    QGraphicsScene, QGraphicsTextItem, QGraphicsView, QHBoxLayout, QInputDialog,
    QMessageBox, QPushButton, QVBoxLayout, QWidget,
)

from .capture import unique_path


COLORS = (
    ("Red", "#ff3b30"),
    ("Orange", "#ff9500"),
    ("Yellow", "#ffcc00"),
    ("Green", "#34c759"),
    ("Blue", "#007aff"),
    ("Purple", "#af52de"),
    ("White", "#ffffff"),
    ("Black", "#000000"),
)


def render_scene(scene: QGraphicsScene) -> QImage:
    rect = scene.sceneRect()
    image = QImage(max(1, round(rect.width())), max(1, round(rect.height())), QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    scene.render(painter, QRectF(image.rect()), rect)
    painter.end()
    return image


class _AddItemCommand(QUndoCommand):
    def __init__(self, scene: QGraphicsScene, item: QGraphicsItem) -> None:
        super().__init__("Add annotation")
        self.scene = scene
        self.item = item

    def redo(self) -> None:
        self.scene.addItem(self.item)

    def undo(self) -> None:
        self.scene.removeItem(self.item)


class _RemoveItemCommand(QUndoCommand):
    def __init__(self, scene: QGraphicsScene, item: QGraphicsItem) -> None:
        super().__init__("Delete annotation")
        self.scene = scene
        self.item = item

    def redo(self) -> None:
        self.scene.removeItem(self.item)

    def undo(self) -> None:
        self.scene.addItem(self.item)


class ArrowItem(QGraphicsItem):
    def __init__(self, rect: QRectF, pen: QPen) -> None:
        super().__init__()
        self.rect = rect.normalized()
        self.pen = pen

    def boundingRect(self) -> QRectF:
        return self.rect.adjusted(-self.pen.widthF(), -self.pen.widthF(), self.pen.widthF(), self.pen.widthF())

    def paint(self, painter: QPainter, _option: object, _widget: QWidget | None = None) -> None:
        start = self.rect.topLeft()
        end = self.rect.bottomRight()
        painter.setPen(self.pen)
        painter.drawLine(start, end)
        angle = math.atan2(end.y() - start.y(), end.x() - start.x())
        size = max(8.0, self.pen.widthF() * 3.0)
        points = QPolygonF([
            end,
            QPointF(
                end.x() - size * math.cos(angle - math.pi / 6),
                end.y() - size * math.sin(angle - math.pi / 6),
            ),
            QPointF(
                end.x() - size * math.cos(angle + math.pi / 6),
                end.y() - size * math.sin(angle + math.pi / 6),
            ),
        ])
        painter.setBrush(self.pen.color())
        painter.drawPolygon(points)


class AnnotationEditor(QDialog):
    def __init__(self, source: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.source = source
        self.background = QPixmap(str(source))
        if self.background.isNull():
            raise OSError(f"Could not open image for annotation: {source}")
        self.scene = QGraphicsScene(self)
        self.scene.setSceneRect(QRectF(0, 0, self.background.width(), self.background.height()))
        self.background_item = self.scene.addPixmap(self.background)
        self.background_item.setZValue(-1000)
        self.background_item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, False)
        self.background_item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, False)
        self.view = QGraphicsView(self.scene)
        self.view.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.view.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        self.undo_stack = QUndoStack(self)
        self.undo_stack.setClean()
        self.tool = QComboBox()
        self.tool.addItems(["Select", "Arrow", "Rectangle", "Ellipse", "Pen", "Text", "Highlighter", "Pixelate"])
        self.color = QComboBox()
        for name, value in COLORS:
            self.color.addItem(name, value)
        self.width = QComboBox()
        self.width.addItems(["2", "5", "10"])
        self.width.setCurrentText("5")
        toolbar = QHBoxLayout()
        toolbar.addWidget(self.tool)
        toolbar.addWidget(self.color)
        toolbar.addWidget(self.width)
        undo = QPushButton("Undo")
        undo.clicked.connect(self.undo_stack.undo)
        redo = QPushButton("Redo")
        redo.clicked.connect(self.undo_stack.redo)
        self._undo_shortcut = QShortcut(QKeySequence("Ctrl+Z"), self)
        self._undo_shortcut.activated.connect(self.undo_stack.undo)
        self._redo_shortcut = QShortcut(QKeySequence("Ctrl+Shift+Z"), self)
        self._redo_shortcut.activated.connect(self.undo_stack.redo)
        delete = QPushButton("Delete selected")
        delete.clicked.connect(self.delete_selected)
        toolbar.addWidget(undo)
        toolbar.addWidget(redo)
        toolbar.addWidget(delete)
        save = QPushButton("Save as new")
        save.clicked.connect(self.save_as_new)
        copy = QPushButton("Copy")
        copy.clicked.connect(self.copy_to_clipboard)
        close = QPushButton("Close")
        close.clicked.connect(self.close)
        actions = QHBoxLayout()
        actions.addWidget(save)
        actions.addWidget(copy)
        actions.addStretch()
        actions.addWidget(close)
        layout = QVBoxLayout(self)
        layout.addLayout(toolbar)
        layout.addWidget(self.view, 1)
        layout.addLayout(actions)
        self.view.viewport().installEventFilter(self)
        self._drag_start: QPointF | None = None
        self._draw_path: QPainterPath | None = None
        self._preview_item: QGraphicsItem | None = None
        self.setWindowTitle(f"Annotate {source.name}")
        self.resize(min(self.background.width() + 40, 1200), min(self.background.height() + 120, 900))
        self.view.fitInView(self.scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def _pen(self, color: QColor | None = None) -> QPen:
        return QPen(color or QColor(self.color.currentData()), int(self.width.currentText()))

    def add_annotation(self, kind: str, rect: QRectF | QRect, text: str = "") -> QGraphicsItem:
        area = QRectF(rect).normalized()
        color = QColor(self.color.currentData())
        pen = self._pen(color)
        if kind == "arrow":
            item: QGraphicsItem = ArrowItem(area, pen)
        elif kind == "rectangle":
            item = QGraphicsRectItem(area)
            item.setPen(pen)
            item.setBrush(Qt.BrushStyle.NoBrush)
        elif kind == "ellipse":
            item = QGraphicsEllipseItem(area)
            item.setPen(pen)
            item.setBrush(Qt.BrushStyle.NoBrush)
        elif kind == "pen":
            path = QPainterPath(area.topLeft())
            path.lineTo(area.bottomRight())
            item = QGraphicsPathItem(path)
            item.setPen(pen)
        elif kind == "text":
            text_item = QGraphicsTextItem(text)
            text_item.setDefaultTextColor(color)
            text_item.setTextInteractionFlags(Qt.TextInteractionFlag.TextEditorInteraction)
            text_item.setPos(area.topLeft())
            item = text_item
        elif kind == "highlighter":
            highlighter = QColor(color)
            highlighter.setAlpha(90)
            item = QGraphicsRectItem(area)
            item.setPen(QPen(Qt.PenStyle.NoPen))
            item.setBrush(QBrush(highlighter))
        elif kind == "pixelate":
            item = self._pixelate_item(area)
        else:
            raise ValueError(f"Unknown annotation type: {kind}")
        item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        self.undo_stack.push(_AddItemCommand(self.scene, item))
        return item

    def _add_pen_path(self, path: QPainterPath) -> None:
        item = QGraphicsPathItem(path)
        item.setPen(self._pen())
        item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        self.undo_stack.push(_AddItemCommand(self.scene, item))

    def _pixelate_item(self, area: QRectF) -> QGraphicsPixmapItem:
        crop = area.toAlignedRect().intersected(self.background.rect())
        source = self.background.toImage().copy(crop)
        if source.isNull():
            raise ValueError("Select a region within the screenshot to pixelate.")
        small = source.scaled(
            max(1, source.width() // 12),
            max(1, source.height() // 12),
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.FastTransformation,
        )
        pixelated = small.scaled(
            source.size(),
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.FastTransformation,
        )
        item = QGraphicsPixmapItem(QPixmap.fromImage(pixelated))
        item.setPos(crop.topLeft())
        return item

    def delete_selected(self) -> None:
        for item in self.scene.selectedItems():
            if item is not self.background_item:
                self.undo_stack.push(_RemoveItemCommand(self.scene, item))

    def save_as_new(self) -> Path:
        output = unique_path(self.source.parent, "png", f"{self.source.stem}-annotated")
        image = render_scene(self.scene)
        if not image.save(str(output), "PNG"):
            raise OSError(f"Could not save annotated image to {output}")
        self.undo_stack.setClean()
        return output

    def copy_to_clipboard(self) -> None:
        QApplication.clipboard().setImage(render_scene(self.scene))

    def eventFilter(self, watched: QWidget, event: object) -> bool:
        if watched is self.view.viewport() and event.type() == event.Type.MouseButtonPress:
            if self.tool.currentText() == "Select":
                return super().eventFilter(watched, event)
            position = self.view.mapToScene(event.position().toPoint())
            if self.tool.currentText() == "Text":
                text, accepted = QInputDialog.getText(self, "Add text", "Text:")
                if accepted and text:
                    self.add_annotation("text", QRectF(position, position), text)
                return True
            self._drag_start = position
            self._draw_path = QPainterPath(position) if self.tool.currentText() == "Pen" else None
            self._preview_item = None
            return True
        if watched is self.view.viewport() and self._drag_start is not None:
            if event.type() == event.Type.MouseMove:
                if self._draw_path is not None:
                    self._draw_path.lineTo(self.view.mapToScene(event.position().toPoint()))
                return True
            if event.type() == event.Type.MouseButtonRelease:
                end = self.view.mapToScene(event.position().toPoint())
                kind = {
                    "Arrow": "arrow", "Rectangle": "rectangle", "Ellipse": "ellipse",
                    "Pen": "pen", "Highlighter": "highlighter", "Pixelate": "pixelate",
                }.get(self.tool.currentText())
                if self._draw_path is not None:
                    self._draw_path.lineTo(end)
                    self._add_pen_path(self._draw_path)
                elif kind:
                    self.add_annotation(kind, QRectF(self._drag_start, end).normalized())
                self._drag_start = None
                self._draw_path = None
                return True
        return super().eventFilter(watched, event)

    def closeEvent(self, event: object) -> None:
        if not self.undo_stack.isClean():
            answer = QMessageBox.question(
                self,
                "Unsaved annotations",
                "Save annotations as a new image before closing?",
                QMessageBox.StandardButton.Save
                | QMessageBox.StandardButton.Discard
                | QMessageBox.StandardButton.Cancel,
            )
            if answer == QMessageBox.StandardButton.Cancel:
                event.ignore()
                return
            if answer == QMessageBox.StandardButton.Save:
                try:
                    self.save_as_new()
                except OSError as exc:
                    QMessageBox.critical(self, "Could not save annotations", str(exc))
                    event.ignore()
                    return
        event.accept()
