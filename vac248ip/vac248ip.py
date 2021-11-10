from typing import Union, Optional, Tuple, Iterable, List, Generator, ByteString
import sys
import itertools
import socket
from urllib.parse import urlparse
import enum
import logging
import time
import io

import numpy
from PIL import Image


__all__ = [
    "vac248ip_version",
    "vac248ip_default_port",
    "vac248ip_allow_native_library", "vac248ip_deny_native_library",
    "Vac248IpVideoFormat", "Vac248Ip10BitViewMode", "Vac248IpGamma", "Vac248IpShutter", "Vac248IpCamera",
    "vac248ip_main"
]


# Library version
vac248ip_version = (1, 6, 4)


# Default port
vac248ip_default_port = 1024


def vac248ip_allow_native_library() -> None:
    global _vac248ip_native_library_allowed
    if _vac248ip_native_library_allowed is None:
        _vac248ip_native_library_allowed = True


def vac248ip_deny_native_library() -> None:
    global _vac248ip_native_library_allowed
    if _vac248ip_native_library_allowed is None:
        _vac248ip_native_library_allowed = False


# Camera settings

class Vac248IpVideoFormat(enum.IntEnum):
    """Vac248IP camera video formats."""

    FORMAT_960x600 = 0
    FORMAT_1920x1200 = 1
    FORMAT_960x600_10bit = 2
    FORMAT_1920x1200_10bit = 3


class Vac248Ip10BitViewMode(enum.IntEnum):
    MODE_HIGH_8BIT = 0
    MODE_LOW_8BIT = 1


class Vac248IpGamma(enum.IntEnum):
    GAMMA_1 = 0
    GAMMA_07 = 1
    GAMMA_045 = 2


class Vac248IpShutter(enum.IntEnum):
    SHUTTER_ROLLING = 0
    SHUTTER_GLOBAL = 1


# Camera
class Vac248IpCamera:
    """
    Vac248IP camera handler.
    Warning: when using mixed .get_frame()/.frame and .get_mean_frame()/.mean_frame, don't forget update frame
             before using mean/usual frame!
    """

    logger = logging.getLogger("Vac248ipCamera")

    # In seconds
    send_command_delay = 0.02
    drop_packets_delay = 0.1
    get_frame_delay = 0.02
    open_delay = 0.2

    ##################################################
    # vvv Interface                              vvv #
    ##################################################

    def __init__(
            self,
            address: Union[str, Tuple[str, int]],
            *args,
            video_format: Vac248IpVideoFormat = Vac248IpVideoFormat.FORMAT_1920x1200,
            num_frames: int = 1,
            open_attempts: Optional[int] = 10,
            default_attempts: Optional[int] = None,
            defer_open: bool = False,
            frame_number_module: int = 1000000,
            network_operation_timeout: Union[None, int, float] = 1,
            udp_redundant_coeff: Union[int, float] = 1.5,
            allow_native_library: Optional[bool] = None
    ) -> None:
        """
        Vac248IpCamera constructor.

        :param address: str with camera address (maybe, trailing with ":<port>"; default port is vac248ip_default_port)
                        or tuple: (ip address: str, port: int)
        :param network_operation_timeout: None, int or float: None for blocking mode of value in seconds.
                                          Default: 0.5s (hope, will be enough) + 30% reserve = 0.65s
        :param video_format: Vac248IpVideoFormat: Camera video format.
        :param num_frames: int: Number of frames received from camera used to glue result frame.
        :param open_attempts: Optional[int]: Attempts parameter for method open().
        :param default_attempts: Optional[int]: Default attempts for operations (excluding open(), see open_attempts).
        :param defer_open: bool: Do NOT call open() automatically (so open_attemts will NOT be used).
        :param frame_number_module: int: Positive integer for frame number calculation (returned frame number always
                                         is %-ed to this value). Use 0 to disable % (mod) operation or -1 to disable
                                         frame counting.
        :param network_operation_timeout: Union[None, int, float]: Network operation timeout.
        :param udp_redundant_coeff: Union[int, float]: Expected average UDP packet count divided by unique packets
                                                       (your network generates ~20 duplicates => give value >= 1.2).
        :param allow_native_library: Optional[bool]: Allow this library try to load native extension (if available)
                                                     for speed up some operations for you.
        """

        if len(args) > 0:
            raise ValueError("Named arguments required")

        frame_number_module = int(frame_number_module)
        if frame_number_module > 0:
            def update_frame_number_generator() -> Generator[int, None, None]:
                frame_number = 0
                while True:
                    if frame_number_module == -1:
                        yield 0
                    else:
                        yield frame_number
                        if frame_number_module > 0:
                            frame_number = (frame_number + 1) % frame_number_module
                        elif frame_number_module == 0:
                            frame_number += 1
                        else:
                            raise ValueError(
                                "Incorrect frame_number_module value ({}, "
                                "but expected int in range: [-1, +inf))".format(frame_number_module))
        self.__update_frame_number_it = iter(update_frame_number_generator())

        self.__frame_number = 0
        self.__frame_number_module = frame_number_module

        self.__network_operation_timeout = network_operation_timeout
        self.__udp_redundant_coeff = udp_redundant_coeff

        self.__default_attempts = None
        self.default_attempts = default_attempts

        self.__video_format = Vac248IpVideoFormat(video_format)
        self.__view_mode_10bit = Vac248Ip10BitViewMode.MODE_LOW_8BIT

        self.__need_update_config = True
        self.__shutter = Vac248IpShutter.SHUTTER_GLOBAL
        self.__gamma = Vac248IpGamma.GAMMA_1
        self.__auto_gain_expo = True
        self.__max_gain_auto = 1  # 1..10
        self.__contrast_auto = 0  # -70..70
        self.__exposure = 0x01  # 0x01..0xbe
        self.__sharpness = 0  # sharpness: 0..8 (means 0, 12, 25, 37, 50, 62, 75, 87, 100 %)
        self.__gain_analog = 1  # gain_analog: 1..4 (means gain 1, 2, 4, 8)
        self.__gain_digital = 1  # gain_digital: 1..48 (means gain 0.25..12.0)
        self.__camera_mac_address = bytes(6)

        self.__num_frames = num_frames

        self.__socket = None

        host, port = _vac248ip_get_host_and_port(address)
        if port < 1023:
            raise ValueError("Port >= 1023 required")

        self.__camera_host = host
        self.__camera_port = port

        # Buffers for receiving frames
        frame_width, frame_height, frame_packets, bytes_per_pixel = \
            _vac248ip_frame_parameters_by_format[self.__video_format]
        self.__frame_buffer = numpy.zeros(frame_width * frame_height * bytes_per_pixel, dtype=numpy.uint8)

        self.__capture_packets_native_fn = None
        self.__capture_packets = self.__capture_packets_universal

        if allow_native_library is None:
            if _vac248ip_native_library_allowed is None:
                allow_native_library = True
            else:
                allow_native_library = _vac248ip_native_library_allowed
        else:
            allow_native_library = bool(allow_native_library)

        self.__native_library_used = allow_native_library and self.__try_load_native_library()
        if self.__native_library_used:
            self.__capture_packets = self.__capture_packets_native

        if not defer_open:
            self.open_device(attempts=open_attempts)

    def __del__(self) -> None:
        self.close_device()

    def __enter__(self) -> "Vac248IpCamera":
        self.open_device()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close_device()

    @property
    def host(self) -> str:
        return self.__camera_host

    @property
    def port(self) -> int:
        return self.__camera_port

    @property
    def address(self) -> Tuple[str, int]:
        return self.__camera_host, self.__camera_port

    @property
    def uri(self) -> str:
        """
        Camera address in format HOST:PORT
        :return:
        """

        return "{}:{}".format(self.__camera_host, self.__camera_port)

    @property
    def default_attempts(self) -> Optional[int]:
        return self.__default_attempts

    @default_attempts.setter
    def default_attempts(self, value: Optional[int]) -> None:
        if value is None:
            self.__default_attempts = None
        else:
            default_attempts = int(value)
            if default_attempts < 0:
                default_attempts = None
            self.__default_attempts = default_attempts

    @property
    def native_library_used(self) -> bool:
        return self.__native_library_used

    def open_device(self, attempts: Optional[int] = 10) -> None:
        if self.__socket is None:
            exception = None
            for _ in self.__attempts_sequence(attempts):
                try:
                    self.__open()
                    return
                except Exception as e:
                    exception = e

            if exception is not None:
                raise exception

            self.__frame_number = 0

    def close_device(self) -> None:
        if self.__socket is not None:
            try:
                self.__send_command_stop()
            except Exception as e:
                self.logger.warning("When closing camera exception caught: {}".format(e), exc_info=sys.exc_info())
            finally:
                self.__socket.close()
                self.__socket = None

            self.__frame_number = 0

    @property
    def is_open(self) -> bool:
        return self.__socket is not None

    def update_config(self, force: bool = False, attempts: Optional[int] = -1):
        if self.__need_update_config or force:
            exception = None
            for _ in self.__attempts_sequence(attempts):
                try:
                    self.__update_config(force=force)
                    return
                except Exception as e:
                    exception = e
            if exception is not None:
                raise exception

    def update_frame(self, num_frames: Optional[int] = None, attempts: Optional[int] = -1):
        """
        Updates frame as glued frame. For more help see doc for get_frame().
        """

        if num_frames is None:
            num_frames = self.__num_frames

        exception = None
        for _ in self.__attempts_sequence(attempts):
            try:
                self.__update_frame(num_frames=num_frames)
                self.__frame_number = next(self.__update_frame_number_it)
                return
            except Exception as e:
                exception = e

        if exception is not None:
            raise exception

    def update_mean_frame(self, frames: int = 3, num_frames: Optional[int] = None,
                          attempts: Optional[int] = -1):
        """
        Updates frame as mean frame. For more help see doc for get_mean_frame().
        """

        if num_frames is None:
            num_frames = self.__num_frames

        exception = None
        for _ in self.__attempts_sequence(attempts):
            try:
                self.__update_mean_frame(frames=frames, num_frames=num_frames)
                self.__frame_number = next(self.__update_frame_number_it)
                return
            except Exception as e:
                exception = e

        if exception is not None:
            raise exception

    def update_smart_mean_frame(self, frames: int = 3, attempts: Optional[int] = -1):
        """
        Updates frame as mean frame using smart algorithm. For more help see
        doc for get_smart_mean_frame().
        """

        exception = None
        for _ in self.__attempts_sequence(attempts):
            try:
                self.__update_smart_mean_frame(frames=frames)
                self.__frame_number = next(self.__update_frame_number_it)
                return
            except Exception as e:
                exception = e

        if exception is not None:
            raise exception

    def get_frame(self, update: bool = True, num_frames: Optional[int] = None,
                  attempts: Optional[int] = -1) -> Tuple[numpy.ndarray, int]:
        """
        Returns frame as glued of `num_frames' frames from camera.
        :param update: Update frame (default) or use old frame data.
        :param num_frames: Number of frames for glue frame (if updating).
        :param attempts: Update attempts.
        :return: (Frame, Frame number)
        """

        if update:
            self.update_frame(num_frames=num_frames, attempts=attempts)
        return self.__get_frame()

    frame = property(get_frame)

    def get_mean_frame(self, update: bool = True, frames: int = 3, num_frames: Optional[int] = None,
                       attempts: Optional[int] = -1) -> Tuple[numpy.ndarray, int]:
        """
        Returns mean frame as average of `frames' sub-frames, when every sub-frame is glue between `num_frames'
        frames from camera.
        :param update: Update frame (default) or use old frame data.
        :param frames: Number of frames for calculating mean frame (if updating).
        :param num_frames: Number of frames for glue sub-frame (if updating).
        :param attempts: Update attempts.
        :return: (Frame, Frame number)
        """

        if update:
            self.update_mean_frame(frames=frames, num_frames=num_frames, attempts=attempts)
        return self.__get_frame()

    mean_frame = property(get_mean_frame)

    def get_smart_mean_frame(self, update: bool = True, frames: int = 3,
                             attempts: Optional[int] = -1) -> Tuple[numpy.ndarray, int]:
        """
        Returns mean frame as sequence of mean frame-part packets, received from camera.
        Each frame part will be received max `frames' times. If nothing received for
        this part, will be black pixels.
        :param update: Update frame (default) or use old frame data.
        :param frames: Number of frames for calculating mean frame (if updating).
        :param attempts: Update attempts.
        :return: (Frame, Frame number)
        """

        if update:
            self.update_smart_mean_frame(frames=frames, attempts=attempts)
        return self.__get_frame()

    smart_mean_frame = property(get_smart_mean_frame)

    def get_encoded_image_size(self) -> int:
        frame_width, frame_height, frame_packets, bytes_per_pixel = \
            _vac248ip_frame_parameters_by_format[self.__video_format]
        return frame_width * frame_height * bytes_per_pixel

    encoded_image_size = property(get_encoded_image_size)

    def get_encoded_image(self, update: bool = True, num_frames: Optional[int] = None,
                          attempts: Optional[int] = -1) -> Tuple[bytes, int]:
        """
        Returns encoded image data and frame number.
        """

        exception = None
        for _ in self.__attempts_sequence(attempts):
            try:
                if update:
                    self.update_frame(num_frames=num_frames, attempts=1)
                encoded_image_data, frame_number = self.__get_encoded_image()
            except Exception as e:
                exception = e
            else:
                return encoded_image_data, frame_number
        if exception is not None:
            raise exception

    encoded_image = property(get_encoded_image)

    def get_encoded_mean_image(self, update: bool = True, frames: int = 3,
                               num_frames: Optional[int] = None, attempts: Optional[int] = -1
                               ) -> Tuple[bytes, int]:
        """
        Returns encoded image data and frame number.
        """

        exception = None
        for _ in self.__attempts_sequence(attempts):
            try:
                if update:
                    self.update_mean_frame(frames=frames, num_frames=num_frames, attempts=1)
                encoded_mean_image_data, frame_number = self.__get_encoded_image()
            except Exception as e:
                exception = e
            else:
                return encoded_mean_image_data, frame_number
        if exception is not None:
            raise exception

    encoded_mean_image = property(get_encoded_mean_image)

    def get_encoded_bitmap_size(self) -> int:
        """
        Returns bitmap file size.
        """

        return len(self.get_encoded_bitmap(update=False))

    encoded_bitmap_size = property(get_encoded_bitmap_size)

    def get_encoded_bitmap(self, update: bool = True, num_frames: Optional[int] = None,
                           attempts: Optional[int] = -1, image_format: str = "bmp"
                           ) -> Tuple[bytes, int]:
        """
        See doc for get_frame().
        :param update: See doc for get_frame().
        :param num_frames: See doc for get_frame().
        :param attempts: See doc for get_frame().
        :param image_format: Image data format ("bmp", "png", etc).
        :return: (Encoded bitmap, frame number)
        """

        frame, frame_number = self.get_frame(update, num_frames, attempts)
        return _vac248ip_encode_bitmap(frame, image_format=image_format), frame_number

    encoded_bitmap = property(get_encoded_bitmap)

    def get_encoded_mean_bitmap(self, update: bool = True, frames: int = 3,
                                num_frames: Optional[int] = None, attempts: Optional[int] = -1,
                                image_format: str = "bmp") -> Tuple[bytes, int]:
        """
        See doc for get_mean_frame().
        :param update: See doc for get_mean_frame().
        :param frames: See doc for get_mean_frame().
        :param num_frames: See doc for get_mean_frame().
        :param attempts: See doc for get_mean_frame().
        :param image_format: Image data format ("bmp", "png", etc).
        :return: (Encoded bitmap, frame number)
        """

        mean_frame, frame_number = self.get_mean_frame(update, frames, num_frames, attempts)
        return _vac248ip_encode_bitmap(mean_frame, image_format=image_format), frame_number

    encoded_mean_bitmap = property(get_encoded_mean_bitmap)

    def get_encoded_smart_mean_bitmap(self, update: bool = True, frames: int = 3,
                                      attempts: Optional[int] = -1, image_format: str = "bmp"
                                      ) -> Tuple[bytes, int]:
        """
        See doc for get_smart_mean_frame().
        :param update: See doc for get_smart_mean_frame().
        :param frames: See doc for get_smart_mean_frame().
        :param attempts: See doc for get_smart_mean_frame().
        :param image_format: Image data format ("bmp", "png", etc).
        :return: (Encoded bitmap, frame number)
        """

        mean_frame, frame_number = self.get_smart_mean_frame(update, frames, attempts)
        return _vac248ip_encode_bitmap(mean_frame, image_format=image_format), frame_number

    encoded_smart_mean_bitmap = property(get_encoded_smart_mean_bitmap)

    def get_video_format(self) -> Vac248IpVideoFormat:
        """
        Returns video format.
        :return: Vac248IpVideoFormat: Video format.
        """

        return self.__video_format

    def set_video_format(self, video_format: Vac248IpVideoFormat):
        """
        Sets video format.
        :param video_format: Vac248IpVideoFormat: Video format.
        """

        if video_format in (Vac248IpVideoFormat.FORMAT_960x600_10bit,
                            Vac248IpVideoFormat.FORMAT_1920x1200_10bit):
            raise ValueError("10-bit video mode not supported")

        self.__video_format = Vac248IpVideoFormat(video_format)
        frame_width, frame_height, frame_packets, bytes_per_pixel = \
            _vac248ip_frame_parameters_by_format[self.__video_format]
        self.__frame_buffer = numpy.zeros(frame_width * frame_height * bytes_per_pixel,
                                          dtype=numpy.uint8)

    video_format = property(get_video_format)

    def get_shutter(self, attempts: Optional[int] = -1) -> Vac248IpShutter:
        """
        Returns shutter value.
        :param attempts: int: Update config attempts.
        :return: Vac248IpShutter: Shutter value.
        """

        self.update_config(attempts=attempts)
        return self.__shutter

    def set_shutter(self, shutter: Vac248IpShutter):
        """
        Sets shutter value.
        :param shutter: Vac248IpShutter: Shutter value.
        """

        command_for_shutter = {Vac248IpShutter.SHUTTER_GLOBAL: 0x36,
                               Vac248IpShutter.SHUTTER_ROLLING: 0x38}
        shutter = Vac248IpShutter(shutter)
        self.__send_command(command_for_shutter[shutter])
        self.__shutter = shutter
        self.__need_update_config = True

    shutter = property(get_shutter, set_shutter)

    def get_gamma(self, attempts: Optional[int] = -1) -> Vac248IpGamma:
        """
        Returns gamma value.
        :param attempts: int: Update config attempts.
        :return: Vac248IpGamma: Gamma value.
        """

        self.update_config(attempts=attempts)
        return self.__gamma

    def set_gamma(self, gamma: Vac248IpGamma):
        """
        Sets gamma value.
        :param gamma: Vac248IpGamma: Gamma value.
        """

        command_for_gamma = {Vac248IpGamma.GAMMA_045: 0x8c,
                             Vac248IpGamma.GAMMA_07: 0x8a,
                             Vac248IpGamma.GAMMA_1: 0x8e}
        gamma = Vac248IpGamma(gamma)
        self.__send_command(command_for_gamma[gamma])
        self.__gamma = gamma
        self.__need_update_config = True

    gamma = property(get_gamma, set_gamma)

    def get_auto_gain_expo(self, attempts: Optional[int] = -1) -> bool:
        """
        Returns auto/manual exposure mode.
        :param attempts: int: Update config attempts.
        :return: bool: True, if automatic mode enabled or False, if manual mode enabled.
        """

        self.update_config(attempts=attempts)
        return self.__auto_gain_expo

    def set_auto_gain_expo(self, auto_gain_expo: bool):
        """
        Toggle auto/manual exposure mode.
        :param auto_gain_expo: True means "enable automatic mode", False -- "enable manual mode".
        """

        self.__send_command(0x94, 0 if auto_gain_expo else 1)
        self.__auto_gain_expo = bool(auto_gain_expo)
        self.__need_update_config = True

    auto_gain_expo = property(get_auto_gain_expo, set_auto_gain_expo)

    def get_max_gain_auto(self, attempts: Optional[int] = -1) -> int:
        """
        Returns max gain auto value: 1..10.
        :param attempts: int: Update config attempts.
        :return: int: Max gain auto value.
        """

        self.update_config(attempts=attempts)
        return self.__max_gain_auto

    def set_max_gain_auto(self, max_gain_auto: int):
        """
        Sets max gain auto value: 1..10.
        :param max_gain_auto: int: Max gain auto value.
        """

        max_gain_auto = _vac248ip_clip(int(max_gain_auto), 0x01, 0x0a)
        self.__send_command(0xd4, max_gain_auto)
        self.__max_gain_auto = max_gain_auto
        self.__need_update_config = True

    max_gain_auto = property(get_max_gain_auto, set_max_gain_auto)

    def get_contrast_auto(self, attempts: Optional[int] = -1) -> int:
        """
        Returns contrast auto value: -70..70.
        :param attempts: int: Update config attempts.
        :return: int: Contrast auto value.
        """

        self.update_config(attempts=attempts)
        return self.__contrast_auto

    def set_contrast_auto(self, contrast_auto: int):
        """
        Sets contrast auto value: -70..70.
        :param contrast_auto: int: Contrast auto value.
        """

        contrast_auto = _vac248ip_clip(int(contrast_auto), -70, 70)
        self.__send_command(0xd2, contrast_auto)
        self.__contrast_auto = contrast_auto
        self.__need_update_config = True

    contrast_auto = property(get_contrast_auto, set_contrast_auto)

    def get_exposure(self, attempts: Optional[int] = -1) -> int:
        """
        Returns current exposure.
        :param attempts: int: Update config attempts.
        :return: int: [1..190] or [0x01..0xbe]
        """

        self.update_config(attempts=attempts)
        return self.__exposure

    def set_exposure(self, exposure: int):
        """
        Sets exposure and turns on manual mode.
        :param exposure: int: [1..190] or [0x01..0xbe]
        """

        exposure = _vac248ip_clip(int(exposure), 1, 190)
        self.set_auto_gain_expo(False)  # Remember switch to manual mode
        # The exposure is also set right after start() command.
        # Search it in this file
        # See #41292 for more details
        self.__send_command(0xc0, exposure)
        self.__exposure = exposure
        self.__need_update_config = True

    exposure = property(get_exposure, set_exposure)

    # For compatibility
    get_exposition = get_exposure
    set_exposition = set_exposure
    exposition = property(get_exposition, set_exposition)

    def get_exposure_ms(self, attempts: Optional[int] = -1) -> float:
        """
        Returns exposure value in milliseconds.
        :param attempts: int: Update config attempts.
        :return: float: Exposure value in ms.
        """

        self.update_config(attempts=attempts)
        return _vac248ip_exposure_to_ms_by_video_format[self.__video_format](self.__exposure)

    exposure_ms = property(get_exposure_ms)

    # For compatibility
    get_exposition_ms = get_exposure_ms
    exposition_ms = property(get_exposition_ms)

    def get_gain_analog(self, attempts: Optional[int] = -1) -> int:
        """
        Returns analog gain value: 1..4 (means gain 1, 2, 4, 8).
        :param attempts: int: Update config attempts.
        :return: int: Analog gain.
        """

        self.update_config(attempts=attempts)
        return self.__gain_analog

    def set_gain_analog(self, gain_analog: int):
        """
        Sets analog gain value: 1..4 (means gain 1, 2, 4, 8).
        :param gain_analog: int: Analog gain value.
        """

        gain_analog = _vac248ip_clip(int(gain_analog), 1, 4)
        self.__send_command(0xb2, gain_analog)
        self.__gain_analog = gain_analog
        self.__need_update_config = True

    gain_analog = property(get_gain_analog, set_gain_analog)

    def get_gain_digital(self, attempts: Optional[int] = -1) -> int:
        """
        Returns digital gain value: 1..48 (means gain 0.25..12.0).
        :param attempts: int: Update config attempts.
        :return: int: Digital gain.
        """

        self.update_config(attempts=attempts)
        return self.__gain_digital

    def set_gain_digital(self, gain_digital: int):
        """
        Sets digital gain value: 1..48 (means gain 0.25..12.0).
        :param gain_digital: int: Digital gain value.
        """

        gain_digital = _vac248ip_clip(int(gain_digital), 1, 48)
        self.__send_command(0xb8, gain_digital)
        self.__gain_digital = gain_digital
        self.__need_update_config = True

    gain_digital = property(get_gain_digital, set_gain_digital)

    def get_sharpness(self, attempts: Optional[int] = -1) -> int:
        """
        Returns sharpness value: 0..8 (means 0, 12, 25, 37, 50, 62, 75, 87, 100 %).
        :param attempts: int: Update config attempts.
        :return: int: Sharpness.
        """

        self.update_config(attempts=attempts)
        return self.__sharpness

    def set_sharpness(self, sharpness: int):
        """
        Sets sharpness value: 0..8 (means 0, 12, 25, 37, 50, 62, 75, 87, 100 %).
        :param sharpness: int: Sharpness value.
        """

        sharpness = _vac248ip_clip(int(sharpness), 0, 8)
        self.__send_command(0xc6, sharpness)
        self.__sharpness = sharpness
        self.__need_update_config = True

    sharpness = property(get_sharpness, set_sharpness)

    def get_view_mode_10bit(self) -> Vac248Ip10BitViewMode:
        """
        Returns 10-bit view mode.
        :return: Vac248Ip10BitViewMode: 10-bit view mode.
        """

        return self.__view_mode_10bit

    def set_view_mode_10bit(self, view_mode_10bit: Vac248Ip10BitViewMode):
        """
        Sets 10-bit view mode.
        :param view_mode_10bit: Vac248Ip10BitViewMode: 10-bit view mode.
        """

        self.__view_mode_10bit = Vac248Ip10BitViewMode(view_mode_10bit)

    view_mode_10bit = property(get_view_mode_10bit, set_view_mode_10bit)

    def get_mac_address(self, attempts: Optional[int] = -1) -> bytes:
        """
        Returns camera MAC address.
        :param attempts: int: Update config attempts.
        :return: bytes: Camera MAC address.
        """

        self.update_config(attempts=attempts)
        return self.__camera_mac_address

    mac_address = property(get_mac_address)

    def get_frame_number(self) -> int:
        """
        Returns last frame number.
        :return: int: Frame number.
        """

        return self.__frame_number

    frame_number = property(get_frame_number)

    def get_frame_number_module(self) -> int:
        """
        :return: int: Positive integer for frame number calculation (returned frame number always is %-ed to this
                      value). Use 0 to disable % (mod) operation or -1 to disable frame counting.
        """

        return self.__frame_number_module

    frame_number_module = property(get_frame_number_module)

    ##################################################
    # ^^^ Interface                              ^^^ #
    ##################################################

    ##################################################
    # >>> Equator                                <<< #
    ##################################################

    ##################################################
    # vvv Implementation                         vvv #
    ##################################################

    def __send_command_start(self):
        self.__send_command(0x5a, self.__video_format.value | 0x80)

    def __send_command_stop(self):
        self.__send_command(0x5a)

    def __send_command_get_single_frame(self):
        self.__send_command(0xe8)

    def __send_command_get_config(self):
        self.__send_command(0xf2)

    def __send_command(self, command: int, data: int = 0):
        self.__socket.send(bytes((command & 0xff, data & 0xff, 0, 0, 0, 0, 0, (command + data) & 0xff)))
        time.sleep(self.send_command_delay)

    def __drop_received_packets(self):
        time.sleep(self.drop_packets_delay)
        packet_buffer = numpy.empty(_VAC248IP_CAMERA_DATA_PACKET_SIZE, dtype=numpy.uint8)
        packet_length = packet_buffer.shape[0]
        try:
            self.__socket.setblocking(False)
            while True:
                self.__socket.recvfrom_into(packet_buffer, packet_length)
        except BlockingIOError:
            pass
        finally:
            self.__set_socket_blocking_with_timeout(self.__network_operation_timeout)

    def __set_socket_blocking_with_timeout(self, timeout: Union[None, int, float]):
        self.__socket.setblocking(True)
        self.__socket.settimeout(timeout)

    def __update_config(self, force: bool = False):
        if self.__need_update_config or force:
            self.__send_command_stop()
            self.__drop_received_packets()
            self.__send_command(0xf2)

            # Receive packet dropping other
            camera_socket = self.__socket
            camera_address = self.__camera_host
            packet_buffer = numpy.empty(_Vac248IpCameraConfig.PACKET_LENGTH, dtype=numpy.uint8)
            packet_length = _Vac248IpCameraConfig.PACKET_LENGTH
            while True:
                result_length, address = camera_socket.recvfrom_into(packet_buffer, packet_length)
                if result_length == packet_length and address[0] == camera_address:
                    break

            self.__apply_config(packet_buffer)

    def __apply_config(self, config_buffer: Union[ByteString, numpy.ndarray, memoryview]):
        config = _Vac248IpCameraConfig(config_buffer)

        self.__shutter = config.shutter
        self.__gamma = config.gamma_correction
        self.__auto_gain_expo = config.auto_gain_expo
        self.__max_gain_auto = config.max_gain
        self.__contrast_auto = config.contrast_auto
        self.__exposure = config.exposure
        self.__sharpness = config.sharpness
        self.__gain_analog = config.gain_analog
        self.__gain_digital = config.gain_digital
        self.__camera_mac_address = config.mac_address

        self.__need_update_config = False

    def __open(self):
        self.__socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        try:
            self.__socket.bind(("", self.__camera_port))

            if self.__network_operation_timeout is not None:
                self.__socket.settimeout(self.__network_operation_timeout)

            self.__socket.connect((self.__camera_host, self.__camera_port))

            # Adjust receive socket buffer size
            # self.__socket.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 8192 * (64 + 5))

            # Try to stop camera, if it was opened before
            self.__send_command_stop()
            time.sleep(self.open_delay)

            self.__update_frame_without_frame_number_update(num_frames=1, attempts=1)
        except Exception:
            self.__socket.close()
            self.__socket = None
            raise

    def __get_encoded_image(self) -> Tuple[bytes, int]:
        return self.__frame_buffer.tobytes(), self.__frame_number

    def __get_frame(self) -> Tuple[numpy.ndarray, int]:
        frame_width, frame_height, frame_packets, bytes_per_pixel = \
            _vac248ip_frame_parameters_by_format[self.__video_format]
        return self.__frame_buffer.reshape(frame_height, frame_width), self.__frame_number

    def __update_frame_without_frame_number_update(self, num_frames: Optional[int] = None,
                                                   attempts: Optional[int] = -1):
        """
        Updates frame as glued frame. For more help see doc for get_frame().
        """

        if num_frames is None:
            num_frames = self.__num_frames
        exception = None
        for _ in self.__attempts_sequence(attempts):
            try:
                self.__update_frame(num_frames=num_frames)
                return
            except Exception as e:
                exception = e

        if exception is not None:
            raise exception

    def __update_frame(self, num_frames: int):
        """
        Updates frame using simple algorithm.
        NOTE: First frame from camera may be overexposed, so actual frames from camera will be
              (num_frames + 1). First frame from camera will be ignored on mean frame calculation, so result
              frame will be calculated using `num_frames' frames.

        :param num_frames: Frames from camera used to glue result frame.
        """

        frame_width, frame_height, frame_packets, bytes_per_pixel = \
            _vac248ip_frame_parameters_by_format[self.__video_format]
        frame_size = frame_width * frame_height * bytes_per_pixel

        default_frame_data_size = _VAC248IP_CAMERA_DATA_PACKET_SIZE - 4
        max_offset = default_frame_data_size * (frame_packets - 1)

        # Capture frames from video stream
        packet_buffers, packets_received = self.__capture_packets(frames=num_frames)

        config_packet_index = None

        # Build frames using data packets
        frame_buffer = self.__frame_buffer = numpy.zeros(frame_size, dtype=numpy.uint8)

        for packet_index in range(packets_received):
            packet_buffer_offset = packet_index * (_VAC248IP_CAMERA_DATA_PACKET_SIZE + 1)
            if packet_buffers[packet_buffer_offset] == 1:
                # Settings packet
                config_packet_index = packet_index
                continue

            packet_buffer = \
                packet_buffers[packet_buffer_offset + 1:packet_buffer_offset + 1 + _VAC248IP_CAMERA_DATA_PACKET_SIZE]

            # Packet: [frame number (bytes: 0) | pix number (bytes: 1 hi, 2, 3 low) | pixel data (bytes: [4...1472))]
            offset = packet_buffer[1] << 16 | packet_buffer[2] << 8 | packet_buffer[3]

            # Filter incorrect offsets
            if offset > max_offset or offset % default_frame_data_size != 0:
                continue

            # Glue packet into frame
            actual_packet_size = min(default_frame_data_size, frame_size - offset)
            frame_buffer[offset:offset + actual_packet_size] = packet_buffer[4:actual_packet_size + 4]

        if config_packet_index is not None:
            try:
                packet_buffer_offset = config_packet_index * (_VAC248IP_CAMERA_DATA_PACKET_SIZE + 1)
                self.__apply_config(
                    packet_buffers[
                        packet_buffer_offset + 1:
                        packet_buffer_offset + 1 + _Vac248IpCameraConfig.PACKET_LENGTH
                    ]
                )
            except Exception:
                pass

    def __update_mean_frame(self, frames: int, num_frames: int):
        """
        Updates mean frame using glue-mean algorithm.
        NOTE: First frame from camera may be overexposed, so actual frames from camera will be
              (frames * num_frames + 1). First frame from camera will be ignored on mean frame calculation, so result
              frame will be calculated using (frames * num_frames) frames.

        Example: frames = 2, num_frames = 3:
            f1, f2, f3, f4, f5, f6  <- src frames from camera
            |   F1   |, |   F2   |  <- frames received as partially update (cumulative update)
            =        RES         =  <- average of (F1, F2)

        :param frames: Glued sub-frames used to calculate mean frame.
        :param num_frames: Frames from camera used to glue each sub-frame.
        """

        frame_width, frame_height, frame_packets, bytes_per_pixel = \
            _vac248ip_frame_parameters_by_format[self.__video_format]
        frame_size = frame_width * frame_height * bytes_per_pixel

        default_frame_data_size = _VAC248IP_CAMERA_DATA_PACKET_SIZE - 4
        max_offset = default_frame_data_size * (frame_packets - 1)

        # Capture frames from video stream
        packet_buffers, packets_received = self.__capture_packets(frames=frames * num_frames)

        config_packet_index = None

        # Build frames using data packets
        frame_buffers = numpy.zeros((frames, frame_size), dtype=numpy.uint8)

        for packet_index in range(packets_received):
            packet_buffer_offset = packet_index * (_VAC248IP_CAMERA_DATA_PACKET_SIZE + 1)
            if packet_buffers[packet_buffer_offset] == 1:
                # Settings packet
                config_packet_index = packet_index
                continue

            packet_buffer = \
                packet_buffers[packet_buffer_offset + 1:packet_buffer_offset + 1 + _VAC248IP_CAMERA_DATA_PACKET_SIZE]

            # Packet: [frame number (bytes: 0) | pix number (bytes: 1 hi, 2, 3 low) | pixel data (bytes: [4...1472))]
            frame_number = packet_buffer[0] - 1  # Fix frame_number for skipped overexposed frame (1st frame)
            offset = packet_buffer[1] << 16 | packet_buffer[2] << 8 | packet_buffer[3]

            # Filter incorrect offsets
            if offset > max_offset or offset % default_frame_data_size != 0:
                continue

            # Glue packet into frame
            actual_packet_size = min(default_frame_data_size, frame_size - offset)
            frame_buffers[frame_number // frames, offset:offset + actual_packet_size] \
                = packet_buffer[4:actual_packet_size + 4]

        self.__frame_buffer = frame_buffers.mean(axis=0, dtype=numpy.uint16).astype(numpy.uint8)

        if config_packet_index is not None:
            try:
                packet_buffer_offset = config_packet_index * (_VAC248IP_CAMERA_DATA_PACKET_SIZE + 1)
                self.__apply_config(
                    packet_buffers[
                        packet_buffer_offset + 1:
                        packet_buffer_offset + 1 + _Vac248IpCameraConfig.PACKET_LENGTH
                    ]
                )
            except Exception:
                pass

    def __update_smart_mean_frame(self, frames: int):
        """
        Updates mean frame using smart algorithm.
        NOTE: First frame from camera may be overexposed, so actual frames from camera will be (frames + 1).
              First frame from camera will be ignored on mean frame calculation, so result frame will be calculated
              using `frames' frames.

        :param frames: Frames from camera used to calculate mean frame.
        """

        frame_width, frame_height, frame_packets, bytes_per_pixel = \
            _vac248ip_frame_parameters_by_format[self.__video_format]
        frame_size = frame_width * frame_height * bytes_per_pixel

        default_frame_data_size = _VAC248IP_CAMERA_DATA_PACKET_SIZE - 4
        max_offset = default_frame_data_size * (frame_packets - 1)

        # Capture frames from video stream
        packet_buffers, packets_received = self.__capture_packets(frames=frames)

        config_packet_index = None

        # Build frames using data packets
        frame_buffers = numpy.zeros((frames, frame_size), dtype=numpy.uint8)

        # Received packets map by frame
        frame_packets_received = numpy.zeros((frames, frame_packets), dtype=numpy.bool_)

        for packet_index in range(packets_received):
            packet_buffer_offset = packet_index * (_VAC248IP_CAMERA_DATA_PACKET_SIZE + 1)
            if packet_buffers[packet_buffer_offset] == 1:
                # Settings packet
                config_packet_index = packet_index
                continue

            packet_buffer = \
                packet_buffers[packet_buffer_offset + 1:packet_buffer_offset + 1 + _VAC248IP_CAMERA_DATA_PACKET_SIZE]

            # Packet: [frame number (bytes: 0) | pix number (bytes: 1 hi, 2, 3 low) | pixel data (bytes: [4...1472))]
            frame_number = packet_buffer[0] - 1  # Fix frame_number for skipped overexposed frame (1st frame)
            offset = packet_buffer[1] << 16 | packet_buffer[2] << 8 | packet_buffer[3]

            # Filter incorrect offsets
            if offset > max_offset or offset % default_frame_data_size != 0:
                continue

            # Glue packet into current frame
            actual_packet_size = min(default_frame_data_size, frame_size - offset)
            frame_buffers[frame_number, offset:offset + actual_packet_size] = \
                packet_buffer[4:actual_packet_size + 4]

            frame_packets_received[frame_number, offset // default_frame_data_size] = True

        received_packets_counts = numpy.zeros(frame_packets, dtype=numpy.int_)

        frame_buffer = self.__frame_buffer = numpy.empty(frame_size, dtype=numpy.uint8)
        for packet_index in range(frame_packets):
            offset = packet_index * default_frame_data_size
            actual_packet_size = min(default_frame_data_size, frame_size - offset)

            received_packets = \
                frame_buffers[
                    numpy.nonzero(frame_packets_received.transpose()[packet_index]),
                    offset:offset + actual_packet_size
                ]
            if received_packets.shape[1] > 0:
                frame_buffer[offset:offset + actual_packet_size] = received_packets.mean(axis=1, dtype=numpy.uint16)
            else:
                frame_buffer[offset:offset + actual_packet_size] = 0

            received_packets_counts[packet_index] = received_packets.shape[1]

        if config_packet_index is not None:
            try:
                packet_buffer_offset = config_packet_index * (_VAC248IP_CAMERA_DATA_PACKET_SIZE + 1)
                self.__apply_config(
                    packet_buffers[
                        packet_buffer_offset + 1:
                        packet_buffer_offset + 1 + _Vac248IpCameraConfig.PACKET_LENGTH
                    ]
                )
            except Exception:
                pass

    def __capture_packets_universal(self, frames: int = 1) -> Tuple[memoryview, int]:
        """
        Captures packets required for building `frames' frames.
        Returned buffer has structure:
            [type (1-byte) | data (1472 bytes)] ... [...]
            | <-              N chunks               -> |
            Where N = int(frames * (frame_packets + 1) * udp_redundant_coeff),
            type == 0 means data packet, type == 1 means config packet.

        :param frames: int: Count of frames to be built.
        :return: Tuple[memoryview, int]: (memory view to buffer, received packets)
        """

        frame_width, frame_height, frame_packets, bytes_per_pixel = \
            _vac248ip_frame_parameters_by_format[self.__video_format]

        data_packet_size = _VAC248IP_CAMERA_DATA_PACKET_SIZE
        config_packet_size = _Vac248IpCameraConfig.PACKET_LENGTH

        camera_socket = self.__socket
        camera_address = self.__camera_host

        # Frames data packets + at max 1 settings data packet (index to it saved to settings_packet_index)
        packet_buffers_count = int(frames * (1 + frame_packets) * self.__udp_redundant_coeff)
        packet_buffers = numpy.empty(packet_buffers_count * (data_packet_size + 1), dtype=numpy.uint8)
        packet_buffers[::data_packet_size + 1] = 0  # Default type = 0 (data packet)
        packet_buffers_mv = memoryview(packet_buffers)

        # Total count of received packets
        packets_received = 0

        incorrect_length_packets = 0
        max_incorrect_length_packets = 100

        # Start video stream
        self.__send_command_stop()
        self.__drop_received_packets()
        self.__send_command_start()

        # It is important to set expositions right here after start() command.
        # This affects for the image brightness.
        # If you will not set exposition here (and set it somewhere else),
        # the brightness will be different from the Vasily’s software.
        # See #41292 for more details
        self.__send_command(0xc0, self.__exposure)

        # Receive packets
        while packets_received < packet_buffers_count:
            # Buffer for current packet
            packet_offset = packets_received * (data_packet_size + 1)
            packet_buffer = packet_buffers_mv[packet_offset + 1: packet_offset + 1 + data_packet_size]

            # Receive data or settings packet dropping other
            try:
                result_length, address = camera_socket.recvfrom_into(packet_buffer)
            except ValueError:
                # Received > _VAC248IP_CAMERA_DATA_PACKET_SIZE bytes
                continue

            # Check packet source and type (by size)
            if result_length == data_packet_size:
                if address[0] != camera_address:
                    continue

                # Data packet received:
                # [frame number (bytes: 0) | pix number (bytes: 1 hi, 2, 3 low) | pixel data (bytes: [4...1472))]

                # Marked type == 0 by default
                incorrect_length_packets = 0

                # Frame numbers starts with 0
                frame_number = packet_buffer[0]
                if frame_number == 0:
                    # Skip the first frame, which can be overexposed
                    continue
                elif frame_number > frames:
                    # All required frames received, stop packets collecting algorithm
                    break
            elif result_length == config_packet_size:
                if address[0] != camera_address:
                    continue

                # Config packet received
                packet_buffers_mv[packet_offset] = 1
                incorrect_length_packets = 0
            else:
                incorrect_length_packets += 1
                if incorrect_length_packets > max_incorrect_length_packets:
                    break
                else:
                    continue

            packets_received += 1

        # Stop video stream
        self.__send_command_stop()
        time.sleep(self.get_frame_delay)
        self.__drop_received_packets()

        self.logger.debug("Received {} packet(s).".format(packets_received))
        return packet_buffers_mv[:packets_received * (data_packet_size + 1)], packets_received

    def __capture_packets_native(self, frames: int = 1) -> Tuple[memoryview, int]:
        """
        Captures packets required for building `frames' frames.
        Returned buffer has structure:
            [type (1-byte) | data (1472 bytes)] ... [...]
            | <-              N chunks               -> |
            Where N = int(frames * (frame_packets + 1) * udp_redundant_coeff),
            type == 0 means data packet, type == 1 means config packet.

        :param frames: int: Count of frames to be built.
        :return: Tuple[memoryview, int]: (memory view to buffer, received packets)
        """

        import ctypes
        import struct

        frame_width, frame_height, frame_packets, bytes_per_pixel = \
            _vac248ip_frame_parameters_by_format[self.__video_format]

        # Frames data packets + at max 1 settings data packet (index to it saved to settings_packet_index)
        packet_buffers_count = int(frames * (1 + frame_packets) * self.__udp_redundant_coeff)
        packet_buffers = numpy.empty(packet_buffers_count * (_VAC248IP_CAMERA_DATA_PACKET_SIZE + 1), dtype=numpy.uint8)
        packet_buffers[::_VAC248IP_CAMERA_DATA_PACKET_SIZE + 1] = 0  # Default type = 0 (data packet)

        # Total count of received packets
        packets_received = ctypes.c_int(0)

        max_incorrect_length_packets = 100

        camera_ip, camera_port = self.__socket.getpeername()

        res = self.__capture_packets_native_fn(
            packet_buffers.ctypes.data_as(ctypes.POINTER(ctypes.c_uint8)),  # dst
            packet_buffers.shape[0],  # dst_size
            ctypes.byref(packets_received),  # packets_received

            self.__socket.fileno(),  # socket_fd
            frames,  # frames
            frame_packets,  # frame_packets
            struct.unpack("@I", socket.inet_aton(camera_ip))[0],  # camera_ip
            camera_port,  # camera_port
            self.__video_format.value,  # video_format
            max_incorrect_length_packets,  # max_incorrect_length_packets

            int(self.send_command_delay * 1000),  # send_command_delay_ms
            int(self.get_frame_delay * 1000),  # get_frame_delay_ms
            int(self.drop_packets_delay * 1000),  # drop_packets_delay_ms
            int(self.__network_operation_timeout * 1000),  # network_operation_timeout_ms

            ctypes.c_uint8(self.__exposure)  # exposure
        )

        if res == 0:
            # OK
            pass
        elif res < 0:
            # (-1) Some error occurred, see errno
            raise OSError(ctypes.get_errno())
        elif res == 1:
            # Timeout error
            raise socket.timeout("Socket timeout error in native library")
        elif res == 2:
            # Incorrect-length-packets count > max_incorrect_length_packets
            pass
        else:
            raise RuntimeError("Unknown error in native library")

        packets_received = packets_received.value
        self.logger.debug("Received {} packet(s).".format(packets_received))
        return memoryview(packet_buffers)[:packets_received * (_VAC248IP_CAMERA_DATA_PACKET_SIZE + 1)], packets_received

    def __try_load_native_library(self) -> bool:
        try:
            import ctypes
            import ctypes.util
        except ImportError:
            return False

        native_library_name = ctypes.util.find_library("pyvac248ipnative")
        if native_library_name is None:
            return False

        native_library = ctypes.CDLL(native_library_name, mode=ctypes.RTLD_LOCAL)

        # TODO: Check native library version.
        self.__load_capture_packets_native_fn(native_library)

        return True

    def __load_capture_packets_native_fn(self, native_library):
        import ctypes

        self.__capture_packets_native_fn = native_library.pyvac248ipnative_capture_packets
        self.__capture_packets_native_fn.restype = ctypes.c_int
        self.__capture_packets_native_fn.argtypes = (
            ctypes.c_void_p,  # dst
            ctypes.c_int,  # dst_size
            ctypes.POINTER(ctypes.c_int),  # packets_received
            ctypes.c_int,  # socket_fd
            ctypes.c_int,  # frames
            ctypes.c_int,  # frame_packets
            ctypes.c_uint32,  # camera_ip
            ctypes.c_uint16,  # camera_port
            ctypes.c_int,  # video_format
            ctypes.c_int,  # max_incorrect_length_packets
            ctypes.c_int,  # send_command_delay_ms
            ctypes.c_int,  # get_frame_delay_ms
            ctypes.c_int,  # drop_packets_delay_ms
            ctypes.c_int,  # network_operation_timeout_ms
            ctypes.c_uint8  # exposure
        )

    def __attempts_sequence(self, attempts: Optional[int]) -> Iterable[int]:
        if attempts == -1:
            attempts = self.__default_attempts
        return itertools.repeat(0) if attempts is None else range(max(attempts, 1))

    ##################################################
    # ^^^ Implementation                         ^^^ #
    ##################################################


_VAC248IP_CAMERA_DATA_PACKET_SIZE = 1472


_vac248ip_native_library_allowed = None


def _vac248ip_encode_bitmap(frame: numpy.ndarray, image_format: str = "bmp") -> bytes:
    """
    Returns bitmap file data.

    :param frame: numpy.ndarray: Frame data.
    :param image_format: Image data format ("bmp", "png", etc).
    :return: bytes: Image data.
    """

    image = Image.fromarray(frame)
    del frame
    b = io.BytesIO()
    image.save(b, image_format)
    del image
    return b.getvalue()


def _vac248ip_get_host_and_port(address: Union[str, Tuple[str, int]]) -> Tuple[str, int]:
    if isinstance(address, str):
        parsed_address = urlparse("http://{}".format(address))  # Expected address like "1.2.3.4" or "1.2.3.4:5"
        port = parsed_address.port if parsed_address.port is not None else vac248ip_default_port
        return parsed_address.hostname, port
    elif isinstance(address, tuple) \
            and len(address) == 2 and isinstance(address[0], str) and isinstance(address[1], int):
        return address
    else:
        raise ValueError(
            "Incorrect address (expected str in format \'POST[:PORT]\' ot tuple (host: str, port: int), "
            "given value of type: {})".format(
                type(address).__name__
            )
        )


_vac248ip_frame_parameters_by_format = {  # (width, height, data_packets, bytes_per_pixel)
    Vac248IpVideoFormat.FORMAT_960x600: (960, 600, 393, 1),
    Vac248IpVideoFormat.FORMAT_1920x1200: (1920, 1200, 1570, 1),
    Vac248IpVideoFormat.FORMAT_960x600_10bit: (960, 600, 785, 2),
    Vac248IpVideoFormat.FORMAT_1920x1200_10bit: (1920, 1200, 3139, 2)
}


class _Vac248IpCameraConfig:
    """
    See vac248ip.h: VAC248_CAM_CONFIG.
    """

    CAMERA_ID = 6  # For Vac248IP

    CHECK_0 = 0xaa
    CHECK_1 = 0x55

    FIELDS = (
        "video_mode",  # 0

        "packet_count_0",  # 1
        "packet_count_1",  # 2

        "camera_id",  # 3; 248 => 6
        "temperature",  # 4
        "voltage",  # 5
        "focus",  # 6
        "scale",  # 7

        "ip_0",  # 8
        "ip_1",  # 9
        "ip_2",  # 10
        "ip_3",  # 11

        "mac_0",  # 12
        "mac_1",  # 13
        "mac_2",  # 14
        "mac_3",  # 15
        "mac_4",  # 16
        "mac_5",  # 17

        "video_port_0",  # 18; Primary UDP port: Management and data
        "video_port_1",  # 19

        "mask_0",  # 20  # Not used
        "mask_1",  # 21
        "mask_2",  # 22
        "mask_3",  # 23

        "gateway_0",  # 24; Not used
        "gateway_1",  # 25
        "gateway_2",  # 26
        "gateway_3",  # 27

        "manage_port_0",  # 28; Additional UDP port: Management (video port + 1); not used
        "manage_port_1",  # 29

        "exposure",  # 30
        "gain_digital",  # 31
        "gain_analog",  # 32
        "nrpix",  # 33; Not used
        "sharpness",  # 34; [0..8]
        "max_gain",  # 35
        "max_fps",  # 36
        "contrast_auto",  # 37; [-70..+70]

        "reserved_0_0",  # 38
        "reserved_0_1",  # 39

        "management_data_0",  # 40
        "management_data_1",  # 41
        "management_data_2",  # 42
        "management_data_3",  # 43

        "reserved_1_0",  # 44
        "reserved_1_1",  # 45

        "check_0",  # 46; Should be CHECK_0
        "check_1"  # 47; Should be CHECK_1
    )

    PACKET_LENGTH = len(FIELDS)

    def __init__(self, buffer: Union[ByteString, numpy.ndarray, memoryview]):
        if len(buffer) != _Vac248IpCameraConfig.PACKET_LENGTH:
            raise ValueError(
                "Incorrect buffer length (required: {}, but given: {})".format(
                    _Vac248IpCameraConfig.PACKET_LENGTH,
                    len(buffer)
                )
            )

        # Unpack fields
        for field, value in zip(_Vac248IpCameraConfig.FIELDS, buffer):
            setattr(self, field, value)

        if self.check_0 != _Vac248IpCameraConfig.CHECK_0 or self.check_1 != _Vac248IpCameraConfig.CHECK_1:
            raise ValueError("Incorrect check bytes")

        if self.camera_id != _Vac248IpCameraConfig.CAMERA_ID:
            raise ValueError("Camera not supported")

    def to_bytes(self) -> bytes:
        """Packs current object fields to ready-to-send buffer."""

        return bytes(getattr(self, field) for field in _Vac248IpCameraConfig.FIELDS)

    @property
    def video_port(self) -> int:
        return self.video_port_0 + (self.video_port_1 << 8)

    @property
    def video_format(self) -> Vac248IpVideoFormat:
        return Vac248IpVideoFormat(self.video_mode)

    @property
    def packet_count(self) -> int:
        return self.packet_count_0 + (self.packet_count_1 << 8)

    @property
    def management_data(self) -> int:
        return self.management_data_0 + (self.management_data_1 << 8) + \
            (self.management_data_2 << 16) + (self.management_data_3 << 24)

    @property
    def gamma_correction(self) -> Vac248IpGamma:
        d = self.management_data
        if (d & 0x00080000) != 0:
            return Vac248IpGamma.GAMMA_1
        elif (d & 0x00040000) != 0:
            return Vac248IpGamma.GAMMA_07
        else:
            return Vac248IpGamma.GAMMA_045

    @property
    def shutter(self) -> Vac248IpShutter:
        return Vac248IpShutter.SHUTTER_GLOBAL if (self.management_data & 0x20000000) != 0 \
            else Vac248IpShutter.SHUTTER_ROLLING

    @property
    def auto_gain_expo(self) -> bool:
        return (self.management_data & 0x10000000) == 0

    @property
    def mac_address(self) -> bytes:
        return bytes((self.mac_0, self.mac_1, self.mac_2, self.mac_3, self.mac_4, self.mac_5))


def _vac248ip_exposure_to_ms_960x600(e: int) -> float:
    if 1 <= e <= 50:
        return e * 1 * 0.100
    elif 51 <= e <= 100:
        return 50 * 1 * 0.100 + e * 2 * 0.100
    elif e <= 190:
        return 50 * 1 * 0.100 + 50 * 2 * 0.100 + (e - 100) * 5 * 0.100
    else:
        return 0.0


def _vac248ip_exposure_to_ms_1920x1200(e: int) -> float:
    if e <= 50:
        return e * 2 * 0.1833
    elif 51 <= e <= 100:
        return 50 * 2 * 0.1833 + (e - 50) * 4 * 0.1833
    elif e <= 190:
        return 50 * 2 * 0.1833 + 50 * 4 * 0.1833 + (e - 100) * 10 * 0.1833
    else:
        return 0.0


_vac248ip_exposure_to_ms_by_video_format = {
    Vac248IpVideoFormat.FORMAT_960x600: _vac248ip_exposure_to_ms_960x600,
    Vac248IpVideoFormat.FORMAT_960x600_10bit: _vac248ip_exposure_to_ms_960x600,
    Vac248IpVideoFormat.FORMAT_1920x1200: _vac248ip_exposure_to_ms_1920x1200,
    Vac248IpVideoFormat.FORMAT_1920x1200_10bit: _vac248ip_exposure_to_ms_1920x1200,
}


def _vac248ip_clip(value, min_value, max_value):
    if value < min_value:
        return min_value
    elif max_value < value:
        return max_value
    else:
        return value


class Cameras:
    def __init__(
            self,
            addresses: List[str],
            video_format: Vac248IpVideoFormat = Vac248IpVideoFormat.FORMAT_960x600,
            num_frames: int = 1,
            open_attempts: int = 10,
            default_attempts: Optional[int] = None,
            allow_native_library: bool = True
    ) -> None:
        self.__cameras = None
        self.__addresses = addresses
        self.__video_format = video_format
        self.__num_frames = num_frames
        self.__open_attempts = open_attempts
        self.__default_attempts = default_attempts
        self.__allow_native_library = allow_native_library

    def __getitem__(self, item: int) -> Vac248IpCamera:
        return self.__cameras[item]

    def __iter__(self):
        return iter(self.__cameras)

    def __len__(self) -> int:
        return len(self.__cameras)

    def __enter__(self) -> "Cameras":
        self.__cameras = [
            Vac248IpCamera(
                address=address,
                video_format=self.__video_format,
                num_frames=self.__num_frames,
                defer_open=True,
                default_attempts=self.__default_attempts,
                allow_native_library=self.__allow_native_library
            ) for address in self.__addresses
        ]

        opened_cameras = []
        try:
            for camera in self.__cameras:
                camera.open_device(attempts=self.__open_attempts)
                opened_cameras.append(camera)
        except BaseException:
            for camera in opened_cameras:
                camera.close_device()
            self.__cameras = None
            raise

        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if self.__cameras is not None:
            for camera in self.__cameras:
                camera.close_device()
            self.__cameras = None


def vac248ip_main(args: List[str]) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog=args[0])

    parser.add_argument(
        "--count", "-c", dest="count", type=int, nargs="?", default=1,
        help="Frames to get"
    )
    parser.add_argument(
        "--open-attempts", "-O", dest="open_attempts", type=int, nargs="?", default=10,
        help="Open attempts for each camera (default: 10)"
    )
    parser.add_argument(
        "--attempts", "-a", dest="attempts", type=int, nargs="?", default=None,
        help="Frame update attempts for each camera (default: infinity)"
    )
    parser.add_argument(
        "--frames", "-f", dest="frames", type=int, nargs="?", default=3,
        help="Glued sub-frames to get frame (for mean algorithms)"
    )
    parser.add_argument(
        "--num-frames", "-n", dest="num_frames", type=int, nargs="?", default=1,
        help="Camera frames used to get for result frame"
    )
    parser.add_argument(
        "--mode", "-m", type=str, nargs="?", default="simple",
        help="Frame update mode, one of: {\'simple\' (default), \'mean\', \'smart\'}. "
             "\'simple\', uses --num-frames, \'mean\' uses --frames and --num-frames, \'smart\' uses --frames"
    )
    parser.add_argument(
        "--format", "-F", type=str, nargs="?", default="bmp",
        help="Output image format (\'bmp\', \'png\' or any other, supported by Pillow; default: \'bmp\')"
    )
    parser.add_argument(
        "--deny-native", "-U", dest="deny_native", action="store_true",
        help="Deny native library usage, force universal version usage (native library usage allowed by default)"
    )
    parser.add_argument(
        "--debug", dest="debug", action="store_true",
        help="Enable debug output"
    )
    parser.add_argument(
        "addresses", type=str, nargs="+",
        help="Camera addresses in format HOST[:PORT] (default port is 1024)"
    )

    parsed_args = parser.parse_args(args[1:])

    logging.basicConfig(
        level=logging.DEBUG if parsed_args.debug else logging.WARNING,
        format="%(asctime)s %(levelname)s  %(message)s",
        datefmt="%F %T"
    )

    image_format = parsed_args.format

    update_frame_mode_by_name = {
        "simple":
            lambda cam: cam.get_encoded_bitmap(
                num_frames=parsed_args.num_frames,
                image_format=image_format
            ),
        "mean":
            lambda cam: cam.get_encoded_mean_bitmap(
                frames=parsed_args.frames,
                num_frames=parsed_args.num_frames,
                image_format=image_format
            ),
        "smart":
            lambda cam: cam.get_encoded_smart_mean_bitmap(
                frames=parsed_args.frames,
                image_format=image_format
            )
    }

    mode = parsed_args.mode.lower()
    get_bitmap_fn = update_frame_mode_by_name.get(mode)
    if get_bitmap_fn is None:
        print(
            "Incorrect mode: \'{}\', expected one of: {{\'simple\' (default), \'mean\', \'smart\'}}".format(
                parsed_args.mode
            ),
            file=sys.stderr
        )
        return 1

    if parsed_args.debug:
        line_1_end = "\n"
        line_2_prefix = " => "
    else:
        line_1_end = ""
        line_2_prefix = " "

    with Cameras(
            addresses=parsed_args.addresses,
            video_format=Vac248IpVideoFormat.FORMAT_1920x1200,
            num_frames=parsed_args.num_frames,
            open_attempts=parsed_args.open_attempts,
            default_attempts=parsed_args.attempts,
            allow_native_library=not parsed_args.deny_native
    ) as cameras:
        for camera in cameras:
            print("Native library used." if camera.native_library_used else "Native library not used.")
            break

        count = parsed_args.count
        for attempt_number in range(count):
            for camera_number, camera in enumerate(cameras):
                print(
                    "Attempt #{:0>3d}, camera #{:0>3d}...".format(attempt_number, camera_number),
                    end=line_1_end,
                    flush=True
                )

                start_time = time.monotonic()
                bitmap, frame_number = get_bitmap_fn(camera)
                frame_get_time = time.monotonic() - start_time

                bitmap_name = "bitmap_m{}_a{:0>3d}_c{:0>3d}_f{:0>3d}.{}".format(
                    mode,
                    attempt_number,
                    camera_number,
                    frame_number,
                    image_format
                )
                print(
                    "{}Got frame #{:0>3d}, {:.6f} s. File: {}".format(
                        line_2_prefix,
                        frame_number,
                        frame_get_time,
                        bitmap_name
                    ),
                    flush=True
                )

                with open(bitmap_name, "wb") as file:
                    file.write(bitmap)

    return 0


if __name__ == "__main__":
    sys.exit(vac248ip_main(sys.argv))
