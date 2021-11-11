"""
File with class for main window of application.
"""

import logging
import os
import re
import time
from typing import Optional
from PyQt5.QtCore import pyqtSignal, pyqtSlot, QRegExp, QThread
from PyQt5.QtGui import QCloseEvent, QIcon, QRegExpValidator, QResizeEvent
from PyQt5.QtWidgets import QMainWindow, QMessageBox, QVBoxLayout
from PyQt5.uic import loadUi
from vac248ip import vac248ip_default_port, Vac248IpCamera
from .dialog_windows import DefaultValueWindow, TestSettingsWindow
from .image_widget import ImageWidget
from .tests import Tests
from . import config as cn
from . import utils as ut


class MainWindow(QMainWindow):
    """
    Class for main window of application.
    """

    tests_continued = pyqtSignal(int)

    def __init__(self):
        super().__init__()
        self._camera: Vac248IpCamera = None
        dir_name = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self._config_file = os.path.join(dir_name, cn.CONFIG_FILE)
        self._camera_params: dict = ut.get_info_about_parameters(self._config_file)
        self._current_test_failed_by_user: bool = False
        self._ip_address: str = None
        self._logger: logging.Logger = logging.getLogger("pyvac_test")
        self._should_stop: bool = False
        self._start_number: int = -1
        self._temp_tests: Tests = None
        self._test_index: int = 0
        self._tests: Tests = Tests(self._camera, self._camera_params)
        self._tests_number: int = self._tests.get_tests_number()
        self._thread: QThread = None
        self._init_ui()

    def _analyze_test_result(self, result: dict):
        """
        Method analyzes test result.
        :param result: dictionary with test result.
        """

        if not result["ok"]:
            self._logger.error(result["msg"])
        else:
            self._logger.info("Test #%s passed", self._test_index)
        if result["frame"] is not None:
            self.image_widget.create_image(result["frame"])

    def _connect_camera(self):
        """
        Method connects camera.
        """

        self._ip_address = self._get_ip_address()
        if self._ip_address is None:
            QMessageBox.information(self, "Информация", "Введите IP адрес камеры")
            return
        self._camera = Vac248IpCamera(self._ip_address, defer_open=True)
        try:
            self._camera.open_device(1)
        except Exception:
            self._disconnect_camera()
            QMessageBox.warning(self, "Ошибка",
                                f"Не удалось подключить камеру с IP адресом {self._ip_address}")
            self._logger.warning("Failed to connect to camera with IP address %s", self._ip_address)
            return
        self.button_connect_or_disconnect.setText("Отключить")
        self.button_connect_or_disconnect.setChecked(True)
        self._set_widgets_enabled(True)
        self._logger.info("Camera with IP address %s was connected", self._ip_address)

    def _disconnect_camera(self):
        """
        Method disconnects camera.
        """

        if self._camera:
            self._camera.close_device()
            self._camera = None
            self._logger.info("Camera with IP address %s was disconnected", self._ip_address)
        if self._thread:
            self._kill_thread()
        self._ip_address = None
        self.button_connect_or_disconnect.setText("Подключить")
        self.button_connect_or_disconnect.setChecked(False)
        self._set_widgets_to_initial_state()
        self._set_widgets_enabled(False)

    def _get_ip_address(self) -> Optional[str]:
        """
        Method returns IP address and port.
        :return: IP address with port.
        """

        ip_address_and_port = self.line_edit_ip_address.text()
        result = re.search(r"^(?P<ip_address>\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})(:(?P<port>\d+))?$",
                           ip_address_and_port)
        if result:
            ip_address = result.group("ip_address")
            port = result.group("port")
            port = vac248ip_default_port if port is None else port
            return f"{ip_address}:{port}"
        return None

    def _init_ui(self):
        """
        Method initializes widgets on main window.
        """

        dir_name = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        file_name = os.path.join(dir_name, "gui", "main_window.ui")
        loadUi(file_name, self)
        self.setWindowTitle("pyvac_test")
        icon = QIcon(os.path.join(dir_name, "gui", "icon.png"))
        self.setWindowIcon(icon)
        self.action_test_settings.triggered.connect(self.show_test_settings)
        self.action_default_values.triggered.connect(self.show_default_values)
        reg_exp = QRegExp("^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}(:\d+)?$")
        validator = QRegExpValidator(reg_exp, self)
        self.line_edit_ip_address.setValidator(validator)
        self.line_edit_ip_address.setText("172.16.142.153:1024")
        self.line_edit_ip_address.returnPressed.connect(self.connect_or_disconnect_camera)
        self.button_connect_or_disconnect.clicked.connect(self.connect_or_disconnect_camera)
        self.button_start_or_stop_tests.clicked.connect(self.start_or_stop_tests)
        self.button_restart_tests.clicked.connect(self.restart_tests)
        self.button_call_failure.clicked.connect(self.set_test_as_failed)
        self.button_skip_test.clicked.connect(self.skip_test)
        self.image_widget = ImageWidget(self.widget_for_image)
        layout = QVBoxLayout()
        layout.addWidget(self.image_widget.get_view(), 1)
        self.widget_for_image.setLayout(layout)
        self._set_widgets_to_initial_state()
        self._set_widgets_enabled(False)

    def _kill_thread(self):
        """
        Method kills thread in which tests are run.
        """

        self._thread.quit()
        self._thread = None

    def _set_widgets_enabled(self, enabled: bool):
        """
        Method sets some widgets to enabled or disabled state.
        :param enabled: if True then widgets will be enabled.
        """

        self.line_edit_ip_address.setEnabled(not enabled)
        widgets = (self.text_edit_info, self.button_start_or_stop_tests, self.button_restart_tests,
                   self.button_call_failure, self.button_skip_test)
        for widget in widgets:
            widget.setEnabled(enabled)

    def _set_widgets_to_initial_state(self):
        """
        Method sets some widgets to initial state.
        """

        self.text_edit_info.clear()
        self.progress_bar.setVisible(False)
        self.progress_bar.setValue(0)
        self.button_start_or_stop_tests.setText("Старт")
        self.button_start_or_stop_tests.setChecked(False)

    def _start_thread_for_tests(self):
        """
        Method creates thread for tests and runs it.
        """

        if self._thread:
            self._kill_thread()
        self._thread = QThread(parent=self)
        self._thread.setTerminationEnabled(True)
        self._temp_tests = Tests(self._camera, self._camera_params, self._tests.get_tests(),
                                 self._start_number)
        self._temp_tests.moveToThread(self._thread)
        self._temp_tests.test_passed.connect(self.show_test_result)
        self.tests_continued.connect(self._temp_tests.run_test)
        self._thread.start()

    def _terminate_tests(self):
        """
        Method forcibly terminates tests.
        """

        self._kill_thread()
        self.button_start_or_stop_tests.setText("Старт")
        self.button_start_or_stop_tests.setChecked(False)
        time.sleep(0.1)
        self.progress_bar.setVisible(False)

    def closeEvent(self, event: QCloseEvent):
        """
        Method handles close event.
        :param event: close event.
        """

        self._disconnect_camera()
        super().closeEvent(event)

    @pyqtSlot()
    def connect_or_disconnect_camera(self):
        """
        Slot connects or disconnects camera.
        """

        if self._camera is None:
            self._connect_camera()
        else:
            self._disconnect_camera()

    def resizeEvent(self, event: QResizeEvent):
        """
        Method handles resizing of the application window.
        :param event: resizing event.
        """

        self.image_widget.scale()
        super().resizeEvent(event)

    @pyqtSlot()
    def restart_tests(self, test_index: Optional[int] = 0, log: bool = True):
        """
        Slot restarts tests.
        :param test_index: initial index of test;
        :param log: if True then log will be printed.
        """

        self._start_number += 1
        self._test_index = test_index
        self._start_thread_for_tests()
        self.tests_continued.emit(self._test_index)
        self.button_start_or_stop_tests.setText("Стоп")
        self.button_start_or_stop_tests.setChecked(True)
        if self._test_index == self._tests_number:
            self._terminate_tests()
        else:
            self.progress_bar.setValue(int(test_index / self._tests_number * 100))
            self.progress_bar.setVisible(True)
        if log:
            self._logger.info("Tests were started")

    @pyqtSlot(dict)
    def set_default_values(self, default: dict):
        """
        Slot sets new default values for camera parameters.
        :param default: dictionary with new default values.
        """

        for param, new_value in default.items():
            self._camera_params[param][cn.DEFAULT] = new_value
        ut.write_config_file(self._config_file, self._camera_params)

    @pyqtSlot()
    def set_test_as_failed(self):
        """
        Slot sets current test as failed.
        """

        self._current_test_failed_by_user = True

    @pyqtSlot()
    def show_default_values(self):
        """
        Slot shows dialog window with default values for camera settings.
        """

        dialog_wnd = DefaultValueWindow(self, self._camera_params)
        dialog_wnd.default_values_received.connect(self.set_default_values)
        dialog_wnd.exec()

    @pyqtSlot()
    def show_test_settings(self):
        """
        Slot shows dialog window with settings for tests.
        """

        dialog_wnd = TestSettingsWindow(self, {})
        dialog_wnd.exec()

    @pyqtSlot(int, int, dict)
    def show_test_result(self, index: int, tests_id: int, result: dict):
        """
        Slot shows result about test.
        :param index: index of test;
        :param tests_id: ID of tests;
        :param result: dictionary with results of test.
        """

        if self._start_number != tests_id or self._should_stop:
            return
        self.progress_bar.setValue(int((index + 1) / self._tests_number * 100))
        self._analyze_test_result(result)
        self._test_index += 1
        if self._test_index == self._tests_number:
            self._terminate_tests()
            self._logger.info("Execution of tests was completed")
            return
        self.tests_continued.emit(self._test_index)

    @pyqtSlot()
    def skip_test(self):
        """
        Slot skips test.
        """

        if self._thread:
            self._logger.info("Test #%s was skipped", self._test_index)
            self._test_index += 1
            self.restart_tests(self._test_index, False)

    @pyqtSlot(bool)
    def start_or_stop_tests(self, start: bool):
        """
        Slot starts or stops tests.
        :param start: if True then tests should be started otherwise tests should
        be stopped.
        """

        self._should_stop = not start
        if start and self._thread is None:
            self.restart_tests()
            return
        if start:
            self.tests_continued.emit(self._test_index)
            button_text = "Стоп"
            logger_msg = "Execution of tests was continued"
        else:
            button_text = "Старт"
            logger_msg = "Execution of tests was paused"
        self._logger.info(logger_msg)
        self.button_start_or_stop_tests.setText(button_text)
