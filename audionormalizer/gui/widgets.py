"""Wiederverwendbare Qt-Widgets."""
from __future__ import annotations

import os

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QDragEnterEvent, QDropEvent, QMouseEvent
from PyQt6.QtWidgets import QDoubleSpinBox, QLabel, QLineEdit

from ..models import SUPPORTED_EXTS


class CustomDoubleSpinBox(QDoubleSpinBox):
    """SpinBox, die bei Fokus den Inhalt markiert und Enter sauber behandelt."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setButtonSymbols(QDoubleSpinBox.ButtonSymbols.UpDownArrows)

    def focusInEvent(self, event):
        super().focusInEvent(event)
        self.lineEdit().selectAll()

    def mousePressEvent(self, event):
        super().mousePressEvent(event)
        self.lineEdit().selectAll()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if not self.lineEdit().text():
                self.setValue(self.minimum())
            self.clearFocus()
        else:
            super().keyPressEvent(event)


class CustomLineEdit(QLineEdit):
    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.clearFocus()
        else:
            super().keyPressEvent(event)


class DropZone(QLabel):
    """Drag&Drop-Feld für Audiodateien und Ordner.

    Emittiert die **rohen** abgelegten Pfade (Ordner bleiben Ordner). Das
    Einsammeln übernimmt ``batch.collect_selection`` – nur so bleibt die
    Herkunft erhalten, aus der später die Zielstruktur gebildet wird.
    """

    clicked = pyqtSignal()
    filesDropped = pyqtSignal(list)

    _BASE_STYLE = """
        QLabel {
            border: 2px dashed #0078d4;
            border-radius: 8px;
            background-color: white;
            color: #0078d4;
            font-size: 15px;
            padding: 10px;
        }
        QLabel:hover {
            background-color: #f0f7ff;
            border-color: #005a9e;
        }
    """
    _DRAG_STYLE = """
        QLabel {
            border: 2px dashed #004578;
            border-radius: 8px;
            background-color: #e1f0ff;
            color: #004578;
            font-size: 16px;
            padding: 20px;
        }
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setText(
            "<b>Dateien oder Ordner hierher ziehen</b><br>"
            "<span style='color: #666; font-size: 13px;'>oder klicken zum Durchsuchen</span>"
        )
        self.setMinimumHeight(100)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet(self._BASE_STYLE)
        self.setAcceptDrops(True)

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self.setStyleSheet(self._DRAG_STYLE)

    def dragLeaveEvent(self, event):
        self.setStyleSheet(self._BASE_STYLE)

    def dropEvent(self, event: QDropEvent):
        self.setStyleSheet(self._BASE_STYLE)
        paths = []
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if os.path.isdir(path) or path.lower().endswith(SUPPORTED_EXTS):
                paths.append(path)
        if paths:
            self.filesDropped.emit(paths)
