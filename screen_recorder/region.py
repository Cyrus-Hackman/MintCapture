"""Interactive rectangular capture selection."""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QGuiApplication, QKeyEvent, QMouseEvent, QPainter, QPen
from PySide6.QtWidgets import QWidget


class RegionSelector(QWidget):
    selected = Signal(QRect)
    cancelled = Signal()

    def __init__(self) -> None:
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.CrossCursor)
        screens = QGuiApplication.screens()
        geometries = [screen.geometry() for screen in screens]
        if geometries:
            bounds = geometries[0]
            for geometry in geometries[1:]:
                bounds = bounds.united(geometry)
            self.setGeometry(bounds)
        self._origin: QPoint | None = None
        self._current = QPoint()
        self._selection = QRect()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._origin = event.globalPosition().toPoint()
            self._current = self._origin
            self._selection = QRect(self._origin, self._current)
            self.update()
        elif event.button() == Qt.MouseButton.RightButton:
            self.cancelled.emit()
            self.close()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        self._current = event.globalPosition().toPoint()
        if self._origin is not None:
            self._selection = QRect(self._origin, self._current).normalized()
        self.update()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._origin is not None:
            self._current = event.globalPosition().toPoint()
            self._selection = QRect(self._origin, self._current).normalized()
            self._confirm()
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.cancelled.emit()
            self.close()
            return
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._confirm()
            return
        super().keyPressEvent(event)

    def paintEvent(self, _event: object) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 130))
        if not self._selection.isNull() and not self._selection.isEmpty():
            local = self._to_local(self._selection)
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
            painter.fillRect(local, Qt.GlobalColor.transparent)
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
            painter.setPen(QPen(QColor(255, 255, 255), 2))
            painter.drawRect(local)
            label = f"{self._selection.width()} × {self._selection.height()}"
            label_size = painter.fontMetrics().size(0, label)
            cursor = self.mapFromGlobal(self._current) + QPoint(12, 12)
            label_width = label_size.width() + 16
            label_height = label_size.height() + 8
            label_x = min(cursor.x(), max(0, self.width() - label_width - 8))
            label_y = min(cursor.y(), max(0, self.height() - label_height - 8))
            label_rect = QRect(label_x, label_y, label_width, label_height)
            painter.fillRect(label_rect, QColor(0, 0, 0, 190))
            painter.setPen(QPen(QColor(255, 255, 255, 160), 1))
            painter.drawRect(label_rect)
            painter.setPen(QColor(255, 255, 255))
            painter.drawText(label_rect, Qt.AlignmentFlag.AlignCenter, label)
        else:
            hint = "Drag to select a portion • Esc or Right-click to cancel"
            hint_size = painter.fontMetrics().size(0, hint)
            hint_rect = QRect(
                (self.width() - hint_size.width() - 24) // 2,
                32,
                hint_size.width() + 24,
                hint_size.height() + 12,
            )
            painter.fillRect(hint_rect, QColor(0, 0, 0, 190))
            painter.setPen(QPen(QColor(255, 255, 255, 120), 1))
            painter.drawRect(hint_rect)
            painter.setPen(QColor(255, 255, 255))
            painter.drawText(hint_rect, Qt.AlignmentFlag.AlignCenter, hint)
        painter.end()

    def _to_local(self, rect: QRect) -> QRect:
        return QRect(self.mapFromGlobal(rect.topLeft()), rect.size())

    def _confirm(self) -> None:
        if self._selection.width() < 1 or self._selection.height() < 1:
            return
        selection = self._selection.normalized()
        self.close()
        self.selected.emit(selection)
