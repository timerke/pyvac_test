"""
File with class for widget to show information about tests.
"""

from functools import partial
import numpy as np
from PyQt5.QtCore import pyqtSlot, Qt
from PyQt5.QtGui import QPalette
from PyQt5.QtWidgets import (QAbstractButton, QCheckBox, QFormLayout, QLabel, QLineEdit, QTextEdit,
                             QToolBox, QVBoxLayout, QWidget)
from . import config as cn


class TestsWidget(QToolBox):
    """
    Class for test widgets.
    """

    def __init__(self, params_info: dict):
        """
        :param params_info: dictionary with information about camera parameters.
        """

        super().__init__()
        self._params_info: dict = params_info
        self._tests: list = []
        self._widgets_for_tests: list = []

    def _clear(self):
        """
        Method clears widget for tests.
        """

        for index in range(len(self._tests) - 1, -1, -1):
            self.removeItem(index)
        self._tests.clear()

    def _create_tests(self) -> list:
        """
        Method creates tests.
        :return: list of tests.
        """

        tests = []
        for param, param_info in self._params_info.items():
            if cn.VALUES in param_info:
                tests.extend(self._create_tests_for_param_enumeration(param, param_info))
            elif cn.MAX in param_info:
                tests.extend(self._create_tests_for_param_with_max_and_min(param, param_info))
        return tests

    @staticmethod
    def _create_tests_for_param_enumeration(param: cn.CameraParameters, param_info: dict) -> list:
        """
        Method creates tests for camera parameter of enumeration type.
        :param param: parameter for which tests are created;
        :param param_info: dictionary with information about camera parameter.
        :return: list with tests for given camera parameter.
        """

        tests = [{cn.PARAMETER: param,
                  cn.GET: param_info[cn.GET],
                  cn.SET: param_info[cn.SET],
                  cn.VALUE: value} for value in param_info[cn.VALUES]]
        return tests

    @staticmethod
    def _create_tests_for_param_with_max_and_min(param: cn.CameraParameters, param_info: dict) -> list:
        """
        Method creates tests for camera parameter with min and max ranges.
        :param param: parameter for which tests are created;
        :param param_info: dictionary with information about camera parameter.
        :return: list with tests for given camera parameter.
        """

        values = (param_info[cn.MIN], int((param_info[cn.MIN] + param_info[cn.MAX]) // 2),
                  param_info[cn.MAX])
        tests = [{cn.PARAMETER: param,
                  cn.GET: param_info[cn.GET],
                  cn.SET: param_info[cn.SET],
                  cn.VALUE: value} for value in values]
        return tests

    def _init_ui(self):
        """
        Method initializes widgets.
        """

        self._widgets_for_tests = []
        for index, test in enumerate(self._tests):
            form_layout = QFormLayout()
            for param in cn.CameraParameters.get_all_parameters():
                line_edit = QLineEdit()
                line_edit.setReadOnly(True)
                if param == test[cn.PARAMETER]:
                    value = test[cn.VALUE]
                else:
                    value = self._params_info[param][cn.DEFAULT]
                if hasattr(value, "name"):
                    value = value.name
                line_edit.setText(str(value))
                form_layout.addRow(QLabel(param.name), line_edit)
            frame_good = QCheckBox()
            frame_good.setEnabled(False)
            frame_good.stateChanged.connect(partial(self.set_image_property, index))
            form_layout.addRow(QLabel("Кадр хороший"), frame_good)
            test_passed = QCheckBox()
            test_passed.setEnabled(False)
            form_layout.addRow(QLabel("Тест пройден"), test_passed)
            layout = QVBoxLayout()
            layout.addLayout(form_layout)
            msg = QTextEdit()
            msg.setReadOnly(True)
            msg.setVisible(False)
            layout.addWidget(msg)
            self._widgets_for_tests.append({"test_passed": test_passed,
                                            "frame_good": frame_good,
                                            "msg": msg})
            widget = QWidget()
            widget.setLayout(layout)
            self.addItem(widget, f"Тест #{index}")

    def _set_color(self, test_index: int, result: bool):
        """
        Method sets special color for test tab in tool box.
        :param test_index: index of test;
        :param result: if True then test is passed otherwise test is failed.
        """

        color = Qt.green if result else Qt.red
        buttons = self.findChildren(QAbstractButton)
        buttons = [btn for btn in buttons if btn.metaObject().className() == "QToolBoxButton"]
        palette = buttons[test_index].palette()
        palette.setColor(QPalette.Button, color)
        buttons[test_index].setPalette(palette)

    def get_frame(self, index: int) -> np.ndarray:
        """
        Nethod returns frame for test with given index.
        :param index: index of test.
        :return: frame data.
        """

        return self._tests[index].get(cn.TEST_FRAME)

    def get_tests(self) -> list:
        """
        Method returns list of tests.
        :return: list of tests.
        """

        return self._tests

    def get_tests_number(self) -> int:
        """
        Method returns number of tests.
        :return: number of tests.
        """

        return len(self._tests)

    @pyqtSlot(int, int)
    def set_image_property(self, index: int, state: int):
        """
        Slot sets test
        :param index: index of test;
        :param state: if True then frame of test is good.
        """

        self._tests[index][cn.TEST_FRAME_GOOD] = bool(state)
        self._widgets_for_tests[index]["test_passed"].setChecked(bool(state))
        self._set_color(index, bool(state))

    def set_test_result(self, test_index: int, result: dict):
        """
        Method sets result to test with given index.
        :param test_index: index of test;
        :param result: dictionary with test result.
        """

        if test_index < 0 or test_index >= len(self._tests):
            return
        self._widgets_for_tests[test_index]["test_passed"].setChecked(result[cn.TEST_RESULT])
        self._widgets_for_tests[test_index]["frame_good"].setChecked(result[cn.TEST_RESULT])
        self._widgets_for_tests[test_index]["frame_good"].setEnabled(True)
        if not result[cn.TEST_RESULT]:
            self._widgets_for_tests[test_index]["frame_good"].setEnabled(False)
            self._widgets_for_tests[test_index]["msg"].setVisible(True)
            self._widgets_for_tests[test_index]["msg"].setText(result[cn.TEST_ERROR])
        self._tests[test_index][cn.TEST_RESULT] = result[cn.TEST_RESULT]
        self._tests[test_index][cn.TEST_ERROR] = result[cn.TEST_ERROR]
        self._tests[test_index][cn.TEST_FRAME] = result[cn.TEST_FRAME]
        self._set_color(test_index, self._tests[test_index][cn.TEST_RESULT])

    def set_to_initial_state(self):
        """
        Method sets widgets to initial state.
        """

        self._clear()
        self._tests = self._create_tests()
        self._init_ui()
