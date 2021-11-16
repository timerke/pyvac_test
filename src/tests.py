"""
File with tests.
"""

from enum import auto, Enum
from typing import Optional
from PyQt5.QtCore import pyqtSignal, pyqtSlot, QObject
from vac248ip import Vac248IpCamera
from . import config as cn


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

    log_ready: pyqtSignal = pyqtSignal(str)
    test_passed: pyqtSignal = pyqtSignal(int, int, dict)

    def __init__(self, camera: Vac248IpCamera, params_info: dict, tests: Optional[list] = None,
                 tests_id: Optional[int] = None):
        """
        :param camera: tested camera;
        :param params_info: dictionary with information about camera parameters;
        :param tests: list of tests;
        :param tests_id: ID of tests.
        """

        super().__init__()
        self._camera: Vac248IpCamera = camera
        self._id: int = tests_id
        self._params_info: dict = params_info
        self._tests: list = tests

    def _set_auto_or_manual_regime(self, log_base: str, parameter: cn.CameraParameters
                                   ) -> Optional[str]:
        """
        Method sets auto or manual regime for gain/exposure.
        :param log_base: base of logging;
        :param parameter: camera parameter for which test will be performed.
        :return: text of exception.
        """

        auto_mode = cn.CameraParameters.is_auto_required(parameter)
        mode = "auto" if auto_mode else "manual"
        try:
            self._camera.set_auto_gain_expo(auto_mode)
        except Exception:
            return f"{log_base} failed to set {mode} mode for gain/exposure"
        self.log_ready.emit(f"{log_base} set to {mode} mode for gain/exposure")
        return None

    def _set_default_values(self, log_base: str) -> Optional[str]:
        """
        Method sets default values to camera.
        :param log_base: base for logging.
        :return: text of exception.
        """

        for param, param_info in self._params_info.items():
            get_method = getattr(self._camera, param_info[cn.GET])
            set_method = getattr(self._camera, param_info[cn.SET])
            default_value = param_info[cn.DEFAULT]
            try:
                set_method(default_value)
            except Exception:
                exc_text = (f"{log_base} failed to set value '{default_value}' to parameter "
                            f"'{param.name}'")
                return exc_text
            try:
                value_real = get_method()
            except Exception:
                exc_text = f"{log_base} failed to read value of parameter '{param.name}'"
                return exc_text
            if value_real != default_value:
                exc_text = (f"{log_base} parameter '{param.name}' has been set value "
                            f"'{default_value}', but read value is '{value_real}'")
                return exc_text
            self.log_ready.emit(f"{log_base} parameter '{param.name}' set to default value "
                                f"'{default_value}'")
        return None

    @pyqtSlot(int)
    def run_test(self, test_index: int):
        """
        Slot runs test.
        :param test_index: index of test to run.
        """

        if test_index < 0 or test_index >= len(self._tests):
            return
        result = {cn.TEST_RESULT: True,
                  cn.TEST_ERROR: "",
                  cn.TEST_FRAME: None}
        log_base = f"Test #{test_index}:"
        test_params = self._tests[test_index]
        parameter = test_params[cn.PARAMETER]
        get_method = getattr(self._camera, test_params[cn.GET])
        set_method = getattr(self._camera, test_params[cn.SET])
        value_to_be = test_params[cn.VALUE]
        exc_text = self._set_default_values(log_base)
        if exc_text is not None:
            result[cn.TEST_RESULT] = False
            result[cn.TEST_ERROR] = exc_text
            self.test_passed.emit(test_index, self._id, result)
            return
        exc_text = self._set_auto_or_manual_regime(log_base, parameter)
        if exc_text is not None:
            result[cn.TEST_RESULT] = False
            result[cn.TEST_ERROR] = exc_text
            self.test_passed.emit(test_index, self._id, result)
            return
        try:
            set_method(value_to_be)
            self.log_ready.emit(f"{log_base} parameter '{parameter.name}' set to value "
                                f"'{value_to_be}'")
        except Exception:
            result[cn.TEST_RESULT] = False
            result[cn.TEST_ERROR] = (f"{log_base} failed to set value '{value_to_be}' to "
                                     f"parameter '{parameter.name}'")
            self.test_passed.emit(test_index, self._id, result)
            return
        try:
            value_real = get_method()
            self.log_ready.emit(f"{log_base} read value '{value_real}' of parameter "
                                f"'{parameter.name}'")
        except Exception:
            result[cn.TEST_RESULT] = False
            result[cn.TEST_ERROR] = (f"{log_base} failed to read value of parameter "
                                     f"'{parameter.name}'")
            self.test_passed.emit(test_index, self._id, result)
            return
        if value_to_be != value_real:
            result[cn.TEST_RESULT] = False
            result[cn.TEST_ERROR] = (f"{log_base} parameter '{parameter.name}' has been set value "
                                     f"'{value_to_be}', but read value is '{value_real}'")
            self.test_passed.emit(test_index, self._id, result)
            return
        try:
            result[cn.TEST_FRAME] = self._camera.get_frame(attempts=1)[0]
        except Exception:
            result[cn.TEST_RESULT] = False
            result[cn.TEST_ERROR] = f"{log_base} failed to get frame"
            self.test_passed.emit(test_index, self._id, result)
            return
        self.log_ready.emit(f"{log_base} frame was received")
        self.test_passed.emit(test_index, self._id, result)
