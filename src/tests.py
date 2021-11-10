"""
File with tests.
"""

import time
from enum import auto, Enum
from typing import Optional
from PyQt5.QtCore import pyqtSignal, pyqtSlot, QObject
from vac248ip import Vac248IpCamera, Vac248IpGamma, Vac248IpShutter, Vac248IpVideoFormat


class CameraParameters(Enum):
    """
    Class for parameters of camera.
    """

    GAMMA = auto()
    SHUTTER = auto()
    VIDEO_FORMAT = auto()


class Tests(QObject):
    """
    Class with tests for camera.
    """

    test_passed = pyqtSignal(int, int)

    def __init__(self, camera: Vac248IpCamera, tests: Optional[list] = None,
                 obj_id: Optional[int] = None):
        """
        :param camera: camera;
        :param tests: list with tests;
        :param obj_id: ID of tests.
        """

        super().__init__()
        self._camera: Vac248IpCamera = camera
        self._id: int = obj_id
        self._tests: list = self._create_tests() if tests is None else tests

    def _create_tests(self) -> list:
        """
        Method creates tests.
        :return: list of tests.
        """

        tests = []
        methods = (self._get_tests_for_gamma, self._get_tests_for_shutter,
                   self._get_tests_for_video_format)
        for method in methods:
            tests.extend(method())
        return tests

    def _get_tests_for_gamma(self) -> list:
        """
        Method adds tests to check gamma.
        :return: list of tests.
        """

        values = Vac248IpGamma.GAMMA_045, Vac248IpGamma.GAMMA_07, Vac248IpGamma.GAMMA_1
        return [{"parameter": CameraParameters.GAMMA,
                 "value": value,
                 "set": self._camera.set_gamma,
                 "get": self._camera.get_gamma} for value in values]

    def _get_tests_for_shutter(self) -> list:
        """
        Method gets tests to check shutter.
        :return: list of tests.
        """

        values = Vac248IpShutter.SHUTTER_GLOBAL, Vac248IpShutter.SHUTTER_ROLLING
        return [{"parameter": CameraParameters.SHUTTER,
                 "value": value,
                 "set": self._camera.set_shutter,
                 "get": self._camera.get_shutter} for value in values]

    def _get_tests_for_video_format(self) -> list:
        """
        Method adds tests to check video format.
        :return: list of tests.
        """

        values = Vac248IpVideoFormat.FORMAT_960x600, Vac248IpVideoFormat.FORMAT_1920x1200
        return [{"parameter": CameraParameters.VIDEO_FORMAT,
                 "value": value,
                 "set": self._camera.set_video_format,
                 "get": self._camera.get_video_format} for value in values]

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

    @pyqtSlot(int)
    def run_test(self, test_index: int):
        """
        Slot runs test.
        :param test_index: index of test to run.
        """

        if 0 <= test_index < len(self._tests):
            test_params = self._tests[test_index]
            get_method = test_params["get"]
            set_method = test_params["set"]
            value = test_params["value"]
            set_method(value)
            value_to_be = get_method()
            if value_to_be != set_method:
                print("Error: ", value, value_to_be)
            self.test_passed.emit(test_index, self._id)

    @pyqtSlot()
    def set_test_failed(self):
        """
        Slot sets test that is currently running as failed.
        """

        pass
