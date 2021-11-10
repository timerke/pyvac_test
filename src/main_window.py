"""
File with class for main window of application.
"""

import os
import re
import time
from typing import Optional
from PyQt5.QtCore import pyqtSignal, pyqtSlot, QRegExp, QThread
from PyQt5.QtGui import QCloseEvent, QIcon, QRegExpValidator
from PyQt5.QtWidgets import QMainWindow, QMessageBox
from PyQt5.uic import loadUi
from vac248ip import vac248ip_default_port, Vac248IpCamera
from .tests import Tests


class MainWindow(QMainWindow):
    """
    Class for main window of application.
    """

    test_failed = pyqtSignal()
    tests_continued = pyqtSignal(int)

    def __init__(self, *args):
        super().__init__(*args)
        self._camera: Vac248IpCamera = None
        self._should_stop: bool = False
        self._start_number: int = -1
        self._temp_tests: Tests = None
        self._test_index: int = 0
        self._tests: Tests = Tests(self._camera)
        self._tests_number: int = self._tests.get_tests_number()
        self._thread: QThread = None
        self._init_ui()

    def _connect_camera(self):
        """
        Method connects camera.
        """

        ip_address = self._get_ip_address()
        if ip_address is None:
            QMessageBox.information(self, "Информация", "Введите IP адрес камеры")
            return
        self._camera = Vac248IpCamera(ip_address, defer_open=True)
        try:
            self._camera.open_device(1)
        except Exception:
            self._disconnect_camera()
            QMessageBox.warning(self, "Ошибка",
                                f"Не удалось подключить камеру с IP адресом {ip_address}")
            return
        self.button_connect_or_disconnect.setText("Отключить")
        self.button_connect_or_disconnect.setChecked(True)
        self._set_widgets_enabled(True)

    def _disconnect_camera(self):
        """
        Method disconnects camera.
        """

        if self._camera:
            self._camera.close_device()
            self._camera = None
        if self._thread:
            self._kill_thread()
        self.button_connect_or_disconnect.setText("Подключить")
        self.button_connect_or_disconnect.setChecked(False)
        self._set_widgets_to_initial_state()
        self._set_widgets_enabled(False)

    def _finish_tests(self):
        """
        Method finishes tests.
        """

        self._kill_thread()
        self.button_start_or_stop_tests.setText("Старт")
        self.button_start_or_stop_tests.setChecked(False)
        time.sleep(0.1)
        self.progress_bar.setVisible(False)

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
        reg_exp = QRegExp("^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}(:\d+)?$")
        validator = QRegExpValidator(reg_exp, self)
        self.line_edit_ip_address.setValidator(validator)
        self.line_edit_ip_address.setText("172.16.142.153:1024")
        self.line_edit_ip_address.returnPressed.connect(self.connect_or_disconnect_camera)
        self.button_connect_or_disconnect.clicked.connect(self.connect_or_disconnect_camera)
        self.button_start_or_stop_tests.clicked.connect(self.start_or_stop_tests)
        self.button_restart_tests.clicked.connect(self.restart_tests)
        self.button_call_failure.clicked.connect(self.test_failed.emit)
        self.button_skip_test.clicked.connect(self.skip_test)
        self._set_widgets_to_initial_state()
        self._set_widgets_enabled(False)

    def _kill_thread(self):
        """
        Method kills thread.
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
        self._temp_tests = Tests(self._camera, self._tests.get_tests(), self._start_number)
        self._temp_tests.moveToThread(self._thread)
        self._temp_tests.test_passed.connect(self.show_test_result)
        self.test_failed.connect(self._temp_tests.set_test_failed)
        self.tests_continued.connect(self._temp_tests.run_test)
        self._thread.start()

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

    @pyqtSlot()
    def restart_tests(self, test_index: Optional[int] = 0):
        """
        Slot restarts tests.
        :param test_index: initial index of test.
        """

        self._start_number += 1
        self._test_index = test_index
        self._start_thread_for_tests()
        self.tests_continued.emit(self._test_index)
        self.button_start_or_stop_tests.setText("Стоп")
        self.button_start_or_stop_tests.setChecked(True)
        if self._test_index == self._tests_number:
            self._finish_tests()
        else:
            self.progress_bar.setValue(int(test_index / self._tests_number * 100))
            self.progress_bar.setVisible(True)

    @pyqtSlot(int, int)
    def show_test_result(self, index: int, tests_id: int):
        """
        Slot shows result about test.
        :param index: index of test;
        :param tests_id: ID of tests.
        """

        if self._start_number != tests_id or self._should_stop:
            return
        progress = int((index + 1) / self._tests_number * 100)
        self.progress_bar.setValue(progress)
        self._test_index += 1
        if self._test_index == self._tests_number:
            self._finish_tests()
            return
        if not self._should_stop:
            self.tests_continued.emit(self._test_index)

    @pyqtSlot()
    def skip_test(self):
        """
        Slot skips test.
        """

        if self._thread:
            self._test_index += 1
            self.restart_tests(self._test_index)

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
        else:
            button_text = "Старт"
        self.button_start_or_stop_tests.setText(button_text)
