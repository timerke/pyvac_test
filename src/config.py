"""
File with parameters of camera.
"""

from typing import Optional, Union
from enum import auto, Enum
from vac248ip import Vac248IpGamma, Vac248IpShutter, Vac248IpVideoFormat


class CameraParameters(Enum):
    """
    Class for parameters of camera.
    """

    CONTRAST = auto()
    EXPOSURE = auto()
    GAIN_ANALOG = auto()
    GAIN_DIGITAL = auto()
    GAMMA = auto()
    MAX_GAIN_AUTO = auto()
    SHUTTER = auto()
    VIDEO_FORMAT = auto()

    @classmethod
    def get_all_parameters(cls) -> tuple:
        """
        Method returns names of all parameters (attributes of given class).
        :return: names of all parameters.
        """

        return (cls.CONTRAST, cls.EXPOSURE, cls.GAIN_ANALOG, cls.GAIN_DIGITAL, cls.GAMMA,
                cls.MAX_GAIN_AUTO, cls.SHUTTER, cls.VIDEO_FORMAT)

    @classmethod
    def get_value(cls, param: "CameraParameters", value: int) ->\
            Optional[Union[int, Vac248IpGamma, Vac248IpShutter, Vac248IpVideoFormat]]:
        """
        Method converts value of parameter.
        :param param: parameter;
        :param value: integer value.
        :return: converted value.
        """

        if param not in cls.get_all_parameters():
            return None
        try:
            if param == CameraParameters.GAMMA:
                return Vac248IpGamma(value)
            if param == CameraParameters.SHUTTER:
                return Vac248IpShutter(value)
            if param == CameraParameters.VIDEO_FORMAT:
                return Vac248IpVideoFormat(value)
            value = int(value)
        except ValueError:
            return CAMERA_PARAMETERS[param][DEFAULT]
        if value < CAMERA_PARAMETERS[param][MIN]:
            return CAMERA_PARAMETERS[param][MIN]
        if value > CAMERA_PARAMETERS[param][MAX]:
            return CAMERA_PARAMETERS[param][MAX]
        return value

    @classmethod
    def is_auto_required(cls, parameter: "CameraParameters") -> bool:
        """
        Method determines whether auto mode is required for the parameter test.
        :param parameter: camera parameter.
        :return: True if auto mode is required.
        """

        if parameter in (cls.CONTRAST, cls.GAMMA, cls.MAX_GAIN_AUTO):
            return True
        return False


DEFAULT = "default"
GET = "get"
MAX = "max"
MIN = "min"
PARAMETER = "parameter"
SET = "set"
TEST_ERROR = "test_error"
TEST_FRAME = "test_frame"
TEST_FRAME_GOOD = "test_frame_good"
TEST_RESULT = "test_result"
VALUE = "value"
VALUES = "values"

CONTRAST_DEFAULT = 0
CONTRAST_MAX = 70
CONTRAST_MIN = -70
EXPOSURE_DEFAULT = 8
EXPOSURE_MAX = 190
EXPOSURE_MIN = 1
GAIN_ANALOG_DEFAULT = 2
GAIN_ANALOG_MAX = 4
GAIN_ANALOG_MIN = 1
GAIN_DIGITAL_DEFAULT = 4
GAIN_DIGITAL_MAX = 48
GAIN_DIGITAL_MIN = 1
GAMMA_DEFAULT = Vac248IpGamma.GAMMA_1
MAX_GAIN_AUTO_DEFAULT = 10
MAX_GAIN_AUTO_MAX = 10
MAX_GAIN_AUTO_MIN = 1
SHUTTER_DEFAULT = Vac248IpShutter.SHUTTER_ROLLING
VIDEO_FORMAT = Vac248IpVideoFormat.FORMAT_960x600

CAMERA_PARAMETERS = {
    CameraParameters.CONTRAST: {DEFAULT: CONTRAST_DEFAULT,
                                MAX: CONTRAST_MAX,
                                MIN: CONTRAST_MIN,
                                GET: "get_contrast_auto",
                                SET: "set_contrast_auto"},
    CameraParameters.EXPOSURE: {DEFAULT: EXPOSURE_DEFAULT,
                                MAX: EXPOSURE_MAX,
                                MIN: EXPOSURE_MIN,
                                GET: "get_exposure",
                                SET: "set_exposure"},
    CameraParameters.GAIN_ANALOG: {DEFAULT: GAIN_ANALOG_DEFAULT,
                                   MAX: GAIN_ANALOG_MAX,
                                   MIN: GAIN_ANALOG_MIN,
                                   GET: "get_gain_analog",
                                   SET: "set_gain_analog"},
    CameraParameters.GAIN_DIGITAL: {DEFAULT: GAIN_DIGITAL_DEFAULT,
                                    MAX: GAIN_DIGITAL_MAX,
                                    MIN: GAIN_DIGITAL_MIN,
                                    GET: "get_gain_digital",
                                    SET: "set_gain_digital"},
    CameraParameters.GAMMA: {DEFAULT: GAMMA_DEFAULT,
                             VALUES: (Vac248IpGamma.GAMMA_045, Vac248IpGamma.GAMMA_07,
                                      Vac248IpGamma.GAMMA_1),
                             GET: "get_gamma",
                             SET: "set_gamma"},
    CameraParameters.MAX_GAIN_AUTO: {DEFAULT: MAX_GAIN_AUTO_DEFAULT,
                                     MAX: MAX_GAIN_AUTO_MAX,
                                     MIN: MAX_GAIN_AUTO_MIN,
                                     GET: "get_max_gain_auto",
                                     SET: "set_max_gain_auto"},
    CameraParameters.SHUTTER: {DEFAULT: SHUTTER_DEFAULT,
                               VALUES: (Vac248IpShutter.SHUTTER_GLOBAL,
                                        Vac248IpShutter.SHUTTER_ROLLING),
                               GET: "get_shutter",
                               SET: "set_shutter"},
    CameraParameters.VIDEO_FORMAT: {DEFAULT: VIDEO_FORMAT,
                                    VALUES: (Vac248IpVideoFormat.FORMAT_960x600,
                                             Vac248IpVideoFormat.FORMAT_1920x1200),
                                    GET: "get_video_format",
                                    SET: "set_video_format"}
}

CONFIG_FILE = "config.ini"
