"""
File with class for creating widget to display image.
"""

import numpy as np
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QImage, QPixmap
from PyQt5.QtWidgets import QWidget, QGraphicsScene, QGraphicsView, QSizePolicy


class ImageWidget(QWidget):
    """
    Class for widget to show image.
    """

    def __init__(self, parent=None):
        """
        :param parent: parent widget.
        """

        super().__init__(parent)
        self._scene = QGraphicsScene()
        self._scene.setBackgroundBrush(Qt.gray)
        self._view = QGraphicsView(self)
        self._view.setScene(self._scene)
        self._view.horizontalScrollBar().blockSignals(True)
        self._view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._view.verticalScrollBar().blockSignals(True)
        self._view.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._view.setResizeAnchor(QGraphicsView.AnchorViewCenter)
        self._view.setAlignment(Qt.AlignCenter)
        self._view.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._image: QPixmap = None

    def _set_image(self, image: QPixmap):
        """
        Method sets image to widget.
        :param image: image to be set.
        """

        self._image = image
        width = self._view.size().width()
        height = self._view.size().height()
        image = image.scaled(width, height, Qt.KeepAspectRatio)
        self._scene.clear()
        self._scene.addPixmap(image)
        self._scene.setSceneRect(0, 0, image.width(), image.height())

    def clear(self):
        """
        Method clears image widget.
        """

        self._image = None
        self._scene.clear()

    def create_image(self, image_array: np.ndarray):
        """
        Method sets image to widget.
        :param image_array: array with data of image.
        """

        if image_array is None:
            return
        gray_scale = QImage.Format_Grayscale16 if image_array.dtype == np.uint16 else QImage.Format_Grayscale8
        height, width = image_array.shape
        image = QPixmap(QImage(image_array, width, height, gray_scale))
        self._set_image(image)

    def get_view(self) -> QGraphicsView:
        """
        Method returns view widget.
        :return: view widget.
        """

        return self._view

    def scale(self):
        """
        Method scales image size to given width and height.
        """

        if self._image:
            self._set_image(self._image)
