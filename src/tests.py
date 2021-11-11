"""
File with tests.
"""

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

    test_passed = pyqtSignal(int, int, dict)

    def __init__(self, camera: Vac248IpCamera, info: dict, tests: Optional[list] = None,
                 tests_id: Optional[int] = None):
        """
        :param camera: tested camera;
        :param info: dictionary with information about camera parameters;
        :param tests: list of tests;
        :param tests_id: ID of tests.
        """

        super().__init__()
        self._camera: Vac248IpCamera = camera
        self._id: int = tests_id
        self._params_info = info
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

    @staticmethod
    def _get_tests_for_gamma() -> list:
        """
        Method adds tests to check gamma.
        :return: list of tests.
        """

        values = Vac248IpGamma.GAMMA_045, Vac248IpGamma.GAMMA_07, Vac248IpGamma.GAMMA_1
        return [{"parameter": CameraParameters.GAMMA,
                 "value": value,
                 "set": "set_gamma",
                 "get": "get_gamma"} for value in values]

    @staticmethod
    def _get_tests_for_shutter() -> list:
        """
        Method gets tests to check shutter.
        :return: list of tests.
        """

        values = Vac248IpShutter.SHUTTER_GLOBAL, Vac248IpShutter.SHUTTER_ROLLING
        return [{"parameter": CameraParameters.SHUTTER,
                 "value": value,
                 "set": "set_shutter",
                 "get": "get_shutter"} for value in values]

    @staticmethod
    def _get_tests_for_video_format() -> list:
        """
        Method adds tests to check video format.
        :return: list of tests.
        """

        values = Vac248IpVideoFormat.FORMAT_960x600, Vac248IpVideoFormat.FORMAT_1920x1200
        return [{"parameter": CameraParameters.VIDEO_FORMAT,
                 "value": value,
                 "set": "set_video_format",
                 "get": "get_video_format"} for value in values]

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
            result = {"ok": True,
                      "msg": "",
                      "frame": None}
            msg_base = f"Test #{test_index} failed:"
            test_params = self._tests[test_index]
            parameter = test_params["parameter"]
            get_method = getattr(self._camera, test_params["get"])
            set_method = getattr(self._camera, test_params["set"])
            value_to_be = test_params["value"]
            try:
                set_method(value_to_be)
            except Exception:
                result["ok"] = False
                result["msg"] = (f"{msg_base} failed to set value '{value_to_be}' to parameter "
                                 f"'{parameter}'")
                self.test_passed.emit(test_index, self._id, result)
                return
            try:
                value_real = get_method()
            except Exception:
                result["ok"] = False
                result["msg"] = f"{msg_base} failed to read value of parameter '{parameter}'"
                self.test_passed.emit(test_index, self._id, result)
                return
            if value_to_be != value_real:
                result["ok"] = False
                result["msg"] = (f"{msg_base} parameter '{parameter}' has been set value "
                                 f"'{value_to_be}', but read value is '{value_real}'")
                self.test_passed.emit(test_index, self._id, result)
                return
            try:
                result["frame"] = self._camera.get_frame()[0]
            except Exception:
                result["ok"] = False
                result["msg"] = f"{msg_base} failed to get frame"
                self.test_passed.emit(test_index, self._id, result)
            self.test_passed.emit(test_index, self._id, result)
