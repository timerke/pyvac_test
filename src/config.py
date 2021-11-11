"""
File with parameters of camera.
"""

from typing import Union
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
            Union[int, Vac248IpGamma, Vac248IpShutter, Vac248IpVideoFormat]:
        """
        Method converts value of parameter.
        :param param: parameter;
        :param value: integer value.
        :return: converted value.
        """

        if param == CameraParameters.GAMMA:
            value = Vac248IpGamma(value)
        elif param == CameraParameters.SHUTTER:
            value = Vac248IpShutter(value)
        elif param == CameraParameters.VIDEO_FORMAT:
            value = Vac248IpVideoFormat(value)
        return value


DEFAULT = "default"
MAX = "max"
MIN = "min"
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
                                MIN: CONTRAST_MIN},
    CameraParameters.EXPOSURE: {DEFAULT: EXPOSURE_DEFAULT,
                                MAX: EXPOSURE_MAX,
                                MIN: EXPOSURE_MIN},
    CameraParameters.GAIN_ANALOG: {DEFAULT: GAIN_ANALOG_DEFAULT,
                                   MAX: GAIN_ANALOG_MAX,
                                   MIN: GAIN_ANALOG_MIN},
    CameraParameters.GAIN_DIGITAL: {DEFAULT: GAIN_DIGITAL_DEFAULT,
                                    MAX: GAIN_DIGITAL_MAX,
                                    MIN: GAIN_DIGITAL_MIN},
    CameraParameters.GAMMA: {DEFAULT: GAMMA_DEFAULT,
                             VALUES: (Vac248IpGamma.GAMMA_045, Vac248IpGamma.GAMMA_07,
                                      Vac248IpGamma.GAMMA_1)},
    CameraParameters.MAX_GAIN_AUTO: {DEFAULT: MAX_GAIN_AUTO_DEFAULT,
                                     MAX: MAX_GAIN_AUTO_MAX,
                                     MIN: MAX_GAIN_AUTO_MIN},
    CameraParameters.SHUTTER: {DEFAULT: SHUTTER_DEFAULT,
                               VALUES: (Vac248IpShutter.SHUTTER_GLOBAL,
                                        Vac248IpShutter.SHUTTER_ROLLING)},
    CameraParameters.VIDEO_FORMAT: {DEFAULT: VIDEO_FORMAT,
                                    VALUES: (Vac248IpVideoFormat.FORMAT_960x600,
                                             Vac248IpVideoFormat.FORMAT_1920x1200)}
}

CONFIG_FILE = "config.ini"
