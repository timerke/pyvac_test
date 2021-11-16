"""
File with classes for dialog windows.
"""

from PyQt5.QtCore import pyqtSignal, pyqtSlot, Qt
from PyQt5.QtWidgets import (QComboBox, QDialog, QFormLayout, QHBoxLayout, QLayout, QPushButton,
                             QSpinBox, QVBoxLayout)
from . import config as cn


class DefaultValueWindow(QDialog):
    """
    Class for dialog window to set default values for camera parameters.
    """

    values_received = pyqtSignal(dict)

    def __init__(self, parent: "MainWindow", params_info: dict):
        """
        :param parent: main window of application;
        :param params_info: dictionary with main information about camera
        parameters.
        """

        super().__init__(parent, Qt.WindowTitleHint | Qt.WindowCloseButtonHint)
        self._widgets: dict = {}
        self._init_ui(params_info)

    @staticmethod
    def _create_combo_box(info: dict) -> QComboBox:
        """
        Method creates combo box for values of given parameter.
        :param info: dictionary with information about parameter.
        :return: combo box.
        """

        combo_box = QComboBox()
        for value in info[cn.VALUES]:
            combo_box.addItem(value.name, value)
        combo_box.setCurrentText(info[cn.DEFAULT].name)
        return combo_box

    @staticmethod
    def _create_spin_box(info: dict) -> QSpinBox:
        """
        Method creates spin box for values of given parameter.
        :param info: dictionary with information about parameter.
        :return: spin box.
        """

        spin_box = QSpinBox()
        spin_box.setMaximum(info[cn.MAX])
        spin_box.setMinimum(info[cn.MIN])
        spin_box.setValue(info[cn.DEFAULT])
        return spin_box

    def _init_ui(self, params_info: dict):
        """
        Method initializes widgets on window.
        :param params_info: dictionary with main information about camera
        parameters.
        """

        self.setWindowTitle("Значения по умолчанию")
        form_layout_left = QFormLayout()
        form_layout_right = QFormLayout()
        for index, param in enumerate(cn.CameraParameters.get_all_parameters()):
            if params_info[param].get(cn.VALUES) is None:
                widget = self._create_spin_box(params_info[param])
            else:
                widget = self._create_combo_box(params_info[param])
            self._widgets[param] = widget
            if index % 2:
                form_layout_right.addRow(param.name, widget)
            else:
                form_layout_left.addRow(param.name, widget)
        h_layout = QHBoxLayout()
        h_layout.addLayout(form_layout_left)
        h_layout.addLayout(form_layout_right)

        button_set_values = QPushButton("Задать значения")
        button_set_values.clicked.connect(self.set_default_values)
        button_cancel = QPushButton("Отмена")
        button_cancel.clicked.connect(self.close)
        h_layout_for_buttons = QHBoxLayout()
        h_layout_for_buttons.addStretch(1)
        h_layout_for_buttons.addWidget(button_set_values)
        h_layout_for_buttons.addWidget(button_cancel)

        v_layout = QVBoxLayout()
        v_layout.setSizeConstraint(QLayout.SetFixedSize)
        v_layout.addLayout(h_layout)
        v_layout.addLayout(h_layout_for_buttons)
        self.setLayout(v_layout)
        self.adjustSize()

    @pyqtSlot()
    def set_default_values(self):
        """
        Slot sets new default values for camera parameters.
        """

        default = {}
        for param, widget in self._widgets.items():
            if isinstance(widget, QComboBox):
                default[param] = widget.currentData()
            else:
                default[param] = widget.value()
        self.values_received.emit(default)
        self.close()
