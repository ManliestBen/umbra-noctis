"""Zoomable, pannable image canvas with live autostretch preview."""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QImage, QPainter, QPixmap
from PySide6.QtWidgets import QGraphicsPixmapItem, QGraphicsScene, QGraphicsView

from ..process.display import auto_stretch_display


def ndarray_to_qimage(data: np.ndarray) -> QImage:
    """float [0,1] (H,W) or (H,W,3) -> QImage (copies, so the array may die)."""
    arr = (np.clip(data, 0.0, 1.0) * 255.0).astype(np.uint8)
    if arr.ndim == 2:
        arr = np.repeat(arr[..., None], 3, axis=2)
    arr = np.ascontiguousarray(arr)
    h, w, _ = arr.shape
    return QImage(arr.data, w, h, 3 * w, QImage.Format_RGB888).copy()


class ImageCanvas(QGraphicsView):
    """Pan with left-drag, zoom with the wheel, double-click to fit.

    ``set_image`` takes the LINEAR float array; the canvas applies the display
    autostretch itself when ``autostretch`` is on, so the preview always
    matches what the processing engine sees.
    """

    zoom_changed = Signal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self._item: QGraphicsPixmapItem | None = None
        self._raw: np.ndarray | None = None
        self._autostretch = True
        self._fit_pending = True
        self.setRenderHints(QPainter.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)

    # ------------------------------------------------------------ contents
    def set_image(self, data: np.ndarray | None, keep_view: bool = False):
        self._raw = data
        if data is None:
            self._scene.clear()
            self._item = None
            return
        shown = auto_stretch_display(data) if self._autostretch else data
        pix = QPixmap.fromImage(ndarray_to_qimage(shown))
        if self._item is None or not keep_view:
            self._scene.clear()
            self._item = self._scene.addPixmap(pix)
            self._scene.setSceneRect(self._item.boundingRect())
            if not keep_view:
                self.fit()
        else:
            self._item.setPixmap(pix)

    def set_autostretch(self, on: bool):
        if on != self._autostretch:
            self._autostretch = on
            if self._raw is not None:
                self.set_image(self._raw, keep_view=True)

    def autostretch_enabled(self) -> bool:
        return self._autostretch

    # ------------------------------------------------------------- viewing
    def fit(self):
        if self._item is not None:
            self.fitInView(self._item, Qt.KeepAspectRatio)
            self.zoom_changed.emit(self.transform().m11())

    def zoom_1_1(self):
        self.resetTransform()
        self.zoom_changed.emit(1.0)

    def wheelEvent(self, event):
        if self._item is None:
            return
        factor = 1.25 if event.angleDelta().y() > 0 else 0.8
        current = self.transform().m11()
        if 0.02 < current * factor < 40:
            self.scale(factor, factor)
            self.zoom_changed.emit(self.transform().m11())

    def mouseDoubleClickEvent(self, event):
        self.fit()
        super().mouseDoubleClickEvent(event)
