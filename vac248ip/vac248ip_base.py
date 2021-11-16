"""
File with base class for vac248ip cameras.
"""

import enum
import itertools
from abc import abstractmethod
from typing import ByteString, Generator, Iterable, Optional, Tuple, Union
import numpy as np
from . import utils as ut


_vac248ip_native_library_allowed = None


# Camera settings
class Vac248IpVideoFormat(enum.IntEnum):
    FORMAT_960x600 = 0
    FORMAT_1920x1200 = 1
    FORMAT_960x600_10bit = 2
    FORMAT_1920x1200_10bit = 3

    @classmethod
    def get_10_bit_formats(cls):
        return cls.FORMAT_960x600_10bit, cls.FORMAT_1920x1200_10bit


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


vac248ip_frame_parameters_by_format = {  # (width, height, data_packets, bytes_per_pixel)
    Vac248IpVideoFormat.FORMAT_960x600: (960, 600, 393, 1),
    Vac248IpVideoFormat.FORMAT_1920x1200: (1920, 1200, 1570, 1),
    Vac248IpVideoFormat.FORMAT_960x600_10bit: (960, 600, 785, 2),
    Vac248IpVideoFormat.FORMAT_1920x1200_10bit: (1920, 1200, 3139, 2)
}

vac248ip_exposure_to_ms_by_video_format = {
    Vac248IpVideoFormat.FORMAT_960x600: ut.convert_exposure_to_ms_960x600,
    Vac248IpVideoFormat.FORMAT_960x600_10bit: ut.convert_exposure_to_ms_960x600,
    Vac248IpVideoFormat.FORMAT_1920x1200: ut.convert_exposure_to_ms_1920x1200,
    Vac248IpVideoFormat.FORMAT_1920x1200_10bit: ut.convert_exposure_to_ms_1920x1200,
}


class Vac248IpCameraBase:
    """
    Base class for vac248ip cameras.
    """

    # In seconds
    send_command_delay = 0.02
    drop_packets_delay = 0.1
    get_frame_delay = 0.02
    open_delay = 0.2

    def __init__(self, address: Union[str, Tuple[str, int]], *args,
                 video_format: Vac248IpVideoFormat = Vac248IpVideoFormat.FORMAT_1920x1200,
                 num_frames: int = 1, open_attempts: Optional[int] = 10,
                 default_attempts: Optional[int] = None, defer_open: bool = False,
                 frame_number_module: int = 1000000,
                 network_operation_timeout: Union[None, int, float] = 1,
                 udp_redundant_coeff: Union[int, float] = 1.5,
                 allow_native_library: Optional[bool] = None):
        """
        :param address: string with camera address (maybe, trailing with ":<port>",
        default port is vac248ip_default_port) or tuple (ip address: str, port: int);
        :param video_format: camera video format;
        :param num_frames: number of frames received from camera used to glue result frame;
        :param open_attempts: number of attempts for method open();
        :param default_attempts: default attempts for operations (excluding open(),
        see open_attempts);
        :param defer_open: do NOT call open() automatically (so open_attempts will NOT be used);
        :param frame_number_module: positive integer for frame number calculation (returned
        frame number always is %-ed to this value). Use 0 to disable % (mod) operation or
        -1 to disable frame counting;
        :param network_operation_timeout: network operation timeout, None for blocking mode of
        value in seconds;
        :param udp_redundant_coeff: expected average UDP packet count divided by unique packets
        (your network generates ~20 duplicates => give value >= 1.2);
        :param allow_native_library: allow this library try to load native extension (if available)
        for speed up some operations for you.
        """

        if len(args) > 0:
            raise ValueError("Named arguments required")
        host, port = ut.get_host_and_port(address)
        if port < 1023:
            raise ValueError("Port >= 1023 required")
        self._camera_host = host
        self._camera_port = port

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
                            raise ValueError("Incorrect frame_number_module value ({}, "
                                             "but expected int in range: [-1, +inf))".
                                             format(frame_number_module))
        self._update_frame_number_it = iter(update_frame_number_generator())
        self._frame_number = 0
        self._frame_number_module = frame_number_module
        self._network_operation_timeout = network_operation_timeout
        self._udp_redundant_coeff = udp_redundant_coeff
        self._default_attempts = None
        self.default_attempts = default_attempts

        self._video_format = Vac248IpVideoFormat(video_format)
        self._view_mode_10bit = Vac248Ip10BitViewMode.MODE_LOW_8BIT

        self._need_update_config = True
        self._shutter = Vac248IpShutter.SHUTTER_GLOBAL
        self._gamma = Vac248IpGamma.GAMMA_1
        self._auto_gain_expo = True
        self._max_gain_auto = 1  # 1..10
        self._contrast_auto = 0  # -70..70
        self._exposure = 0x01  # 0x01..0xbe
        self._sharpness = 0  # sharpness: 0..8 (means 0, 12, 25, 37, 50, 62, 75, 87, 100 %)
        self._gain_analog = 1  # gain_analog: 1..4 (means gain 1, 2, 4, 8)
        self._gain_digital = 1  # gain_digital: 1..48 (means gain 0.25..12.0)
        self._camera_mac_address = bytes(6)

        self._num_frames = num_frames
        self._socket = None

        # Buffers for receiving frames
        frame_width, frame_height, _, bytes_per_pixel = \
            vac248ip_frame_parameters_by_format[self._video_format]
        self._frame_buffer = np.zeros(frame_width * frame_height * bytes_per_pixel, dtype=np.uint8)

        if allow_native_library is None:
            if _vac248ip_native_library_allowed is None:
                allow_native_library = True
            else:
                allow_native_library = _vac248ip_native_library_allowed
        else:
            allow_native_library = bool(allow_native_library)
        self._native_library_used = allow_native_library and self._try_load_native_library()

    def __del__(self):
        self.close_device()

    def __enter__(self) -> "Vac248IpCameraBase":
        self.open_device()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close_device()

    @abstractmethod
    def _apply_config(self, config_buffer: Union[ByteString, np.ndarray, memoryview]):
        raise NotImplementedError

    @abstractmethod
    def _update_config(self, force: bool = False):
        raise NotImplementedError

    def _attempts_sequence(self, attempts: Optional[int]) -> Iterable[int]:
        if attempts == -1:
            attempts = self._default_attempts
        return itertools.repeat(0) if attempts is None else range(max(attempts, 1))

    def _get_encoded_image(self) -> Tuple[bytes, int]:
        return self._frame_buffer.tobytes(), self._frame_number

    def _get_frame(self) -> Tuple[np.ndarray, int]:
        frame_width, frame_height, _, _ = vac248ip_frame_parameters_by_format[self._video_format]
        return self._frame_buffer.reshape(frame_height, frame_width), self._frame_number

    @abstractmethod
    def _send_command(self, command: int, data: int = 0):
        """
        Sends command.
        :param command: command code;
        :param data: data for command.
        """

        raise NotImplementedError

    def _send_command_get_config(self):
        self._send_command(0xf2)

    def _send_command_get_single_frame(self):
        self._send_command(0xe8)

    def _send_command_start(self):
        self._send_command(0x5a, self._video_format.value | 0x80)

    def _send_command_stop(self):
        self._send_command(0x5a)

    @abstractmethod
    def _try_load_native_library(self) -> bool:
        raise NotImplementedError

    @abstractmethod
    def _update_frame(self, num_frames: int):
        """
        Updates frame using simple algorithm.
        :param num_frames: frames from camera used to glue result frame.
        """

        raise NotImplementedError

    @abstractmethod
    def _update_mean_frame(self, frames: int, num_frames: int):
        """
        Updates mean frame using glue-mean algorithm.
        :param frames: glued sub-frames used to calculate mean frame;
        :param num_frames: frames from camera used to glue each sub-frame.
        """

        raise NotImplementedError

    @abstractmethod
    def _update_smart_mean_frame(self, frames: int):
        """
        Updates mean frame using smart algorithm.
        :param frames: frames from camera used to calculate mean frame.
        """

        raise NotImplementedError

    @property
    def address(self) -> Tuple[str, int]:
        return self._camera_host, self._camera_port

    @property
    def host(self) -> str:
        return self._camera_host

    @property
    def port(self) -> int:
        return self._camera_port

    @property
    def uri(self) -> str:
        """
        Camera address in format host:port.
        """

        return "{}:{}".format(self._camera_host, self._camera_port)

    @property
    def default_attempts(self) -> Optional[int]:
        return self._default_attempts

    @default_attempts.setter
    def default_attempts(self, value: Optional[int]):
        if value is None:
            self._default_attempts = None
        else:
            default_attempts = int(value)
            if default_attempts < 0:
                default_attempts = None
            self._default_attempts = default_attempts

    @property
    def native_library_used(self) -> bool:
        return self._native_library_used

    @abstractmethod
    def open_device(self, attempts: Optional[int] = 10):
        raise NotImplementedError

    @abstractmethod
    def close_device(self):
        raise NotImplementedError

    @property
    @abstractmethod
    def is_open(self) -> bool:
        raise NotImplementedError

    def get_frame(self, update: bool = True, num_frames: Optional[int] = None,
                  attempts: Optional[int] = -1) -> Tuple[np.ndarray, int]:
        """
        Returns frame as glued of 'num_frames' frames from camera.
        :param update: update frame (default) or use old frame data;
        :param num_frames: number of frames for glue frame (if updating);
        :param attempts: update attempts.
        :return: (frame, frame number).
        """

        if update:
            self.update_frame(num_frames, attempts)
        return self._get_frame()

    frame = property(get_frame)

    def get_mean_frame(self, update: bool = True, frames: int = 3, num_frames: Optional[int] = None,
                       attempts: Optional[int] = -1) -> Tuple[np.ndarray, int]:
        """
        Returns mean frame as average of 'frames' sub-frames, when every sub-frame is
        glue between 'num_frames' frames from camera.
        :param update: update frame (default) or use old frame data;
        :param frames: number of frames for calculating mean frame (if updating);
        :param num_frames: number of frames for glue sub-frame (if updating);
        :param attempts: update attempts.
        :return: (frame, frame number).
        """

        if update:
            self.update_mean_frame(frames, num_frames, attempts)
        return self._get_frame()

    mean_frame = property(get_mean_frame)

    def get_smart_mean_frame(self, update: bool = True, frames: int = 3,
                             attempts: Optional[int] = -1) -> Tuple[np.ndarray, int]:
        """
        Returns mean frame as sequence of mean frame-part packets, received from camera.
        Each frame part will be received max 'frames' times. If nothing received for this
        part, will be black pixels.
        :param update: update frame (default) or use old frame data;
        :param frames: number of frames for calculating mean frame (if updating);
        :param attempts: update attempts.
        :return: (frame, frame number).
        """

        if update:
            self.update_smart_mean_frame(frames, attempts)
        return self._get_frame()

    smart_mean_frame = property(get_smart_mean_frame)

    def get_encoded_image_size(self) -> int:
        frame_width, frame_height, _, bytes_per_pixel = \
            vac248ip_frame_parameters_by_format[self._video_format]
        return frame_width * frame_height * bytes_per_pixel

    encoded_image_size = property(get_encoded_image_size)

    def get_encoded_image(self, update: bool = True, num_frames: Optional[int] = None,
                          attempts: Optional[int] = -1) -> Tuple[bytes, int]:
        """
        Returns encoded image data and frame number.
        """

        exception = None
        for _ in self._attempts_sequence(attempts):
            try:
                if update:
                    self.update_frame(num_frames, 1)
                encoded_image_data, frame_number = self._get_encoded_image()
            except Exception as exc:
                exception = exc
            else:
                return encoded_image_data, frame_number
        if exception is not None:
            raise exception

    encoded_image = property(get_encoded_image)

    def get_encoded_mean_image(self, update: bool = True, frames: int = 3,
                               num_frames: Optional[int] = None, attempts: Optional[int] = -1) ->\
            Tuple[bytes, int]:
        """
        Returns encoded image data and frame number.
        """

        exception = None
        for _ in self._attempts_sequence(attempts):
            try:
                if update:
                    self.update_mean_frame(frames, num_frames, 1)
                encoded_mean_image_data, frame_number = self._get_encoded_image()
            except Exception as exc:
                exception = exc
            else:
                return encoded_mean_image_data, frame_number
        if exception is not None:
            raise exception

    encoded_mean_image = property(get_encoded_mean_image)

    def get_encoded_bitmap(self, update: bool = True, num_frames: Optional[int] = None,
                           attempts: Optional[int] = -1, image_format: str = "bmp") ->\
            Tuple[bytes, int]:
        """
        Returns encoded image data and frame number.
        :param update: update frame (default) or use old frame data;
        :param num_frames: number of frames for glue frame (if updating);
        :param attempts: update attempts;
        :param image_format: image data format ("bmp", "png", etc).
        :return: (encoded bitmap, frame number).
        """

        frame, frame_number = self.get_frame(update, num_frames, attempts)
        return ut.encode_bitmap(frame, image_format), frame_number

    encoded_bitmap = property(get_encoded_bitmap)

    def get_encoded_bitmap_size(self) -> int:
        """
        Returns bitmap file size.
        """

        return len(self.get_encoded_bitmap(update=False))

    encoded_bitmap_size = property(get_encoded_bitmap_size)

    def get_encoded_mean_bitmap(self, update: bool = True, frames: int = 3,
                                num_frames: Optional[int] = None, attempts: Optional[int] = -1,
                                image_format: str = "bmp") -> Tuple[bytes, int]:
        """
        Returns encoded image data and frame number.
        :param update: update frame (default) or use old frame data;
        :param frames: number of frames for calculating mean frame (if updating);
        :param num_frames: number of frames for glue sub-frame (if updating);
        :param attempts: update attempts;
        :param image_format: image data format ("bmp", "png", etc).
        :return: (encoded bitmap, frame number).
        """

        mean_frame, frame_number = self.get_mean_frame(update, frames, num_frames, attempts)
        return ut.encode_bitmap(mean_frame, image_format), frame_number

    encoded_mean_bitmap = property(get_encoded_mean_bitmap)

    def get_encoded_smart_mean_bitmap(self, update: bool = True, frames: int = 3,
                                      attempts: Optional[int] = -1, image_format: str = "bmp") ->\
            Tuple[bytes, int]:
        """
        See doc for get_smart_mean_frame().
        :param update: update frame (default) or use old frame data;
        :param frames: number of frames for calculating mean frame (if updating);
        :param attempts: update attempts;
        :param image_format: image data format ("bmp", "png", etc).
        :return: (encoded bitmap, frame number).
        """

        mean_frame, frame_number = self.get_smart_mean_frame(update, frames, attempts)
        return ut.encode_bitmap(mean_frame, image_format=image_format), frame_number

    encoded_smart_mean_bitmap = property(get_encoded_smart_mean_bitmap)

    def update_config(self, force: bool = False, attempts: Optional[int] = -1):
        """
        Updates parameters of camera.
        :param force: if True then update is needed;
        :param attempts: number of attempts to update config data of camera.
        """

        if self._need_update_config or force:
            exception = None
            for _ in self._attempts_sequence(attempts):
                try:
                    self._update_config(force)
                    return
                except Exception as exc:
                    exception = exc
            if exception is not None:
                raise exception

    def update_frame(self, num_frames: Optional[int] = None, attempts: Optional[int] = -1):
        """
        Updates frame as glued frame.
        """

        if num_frames is None:
            num_frames = self._num_frames
        exception = None
        for _ in self._attempts_sequence(attempts):
            try:
                self._update_frame(num_frames)
                self._frame_number = next(self._update_frame_number_it)
                return
            except Exception as exc:
                exception = exc
        if exception is not None:
            raise exception

    def update_mean_frame(self, frames: int = 3, num_frames: Optional[int] = None,
                          attempts: Optional[int] = -1):
        """
        Updates frame as mean frame.
        """

        if num_frames is None:
            num_frames = self._num_frames
        exception = None
        for _ in self._attempts_sequence(attempts):
            try:
                self._update_mean_frame(frames, num_frames)
                self._frame_number = next(self._update_frame_number_it)
                return
            except Exception as exc:
                exception = exc
        if exception is not None:
            raise exception

    def update_smart_mean_frame(self, frames: int = 3, attempts: Optional[int] = -1):
        """
        Updates frame as mean frame using smart algorithm.
        """

        exception = None
        for _ in self._attempts_sequence(attempts):
            try:
                self._update_smart_mean_frame(frames)
                self._frame_number = next(self._update_frame_number_it)
                return
            except Exception as exc:
                exception = exc
        if exception is not None:
            raise exception

    def get_auto_gain_expo(self, attempts: Optional[int] = -1) -> bool:
        """
        Returns auto/manual exposure mode.
        :param attempts: number of attempts to update config.
        :return: bool: True if automatic mode enabled, False if manual mode enabled.
        """

        self.update_config(attempts=attempts)
        return self._auto_gain_expo

    def set_auto_gain_expo(self, auto_gain_expo: bool):
        """
        Set auto/manual exposure mode.
        :param auto_gain_expo: True means "enable automatic mode", False - "enable manual mode".
        """

        self._send_command(0x94, 0 if auto_gain_expo else 1)
        self._auto_gain_expo = bool(auto_gain_expo)
        self._need_update_config = True

    auto_gain_expo = property(get_auto_gain_expo, set_auto_gain_expo)

    def get_contrast_auto(self, attempts: Optional[int] = -1) -> int:
        """
        Returns contrast auto value: -70..70.
        :param attempts: number of attempts to update config.
        :return: contrast auto value.
        """

        self.update_config(attempts=attempts)
        if self._contrast_auto > 70:
            return self._contrast_auto - 255 - 1
        return self._contrast_auto

    def set_contrast_auto(self, contrast_auto: int):
        """
        Sets contrast auto value: -70..70.
        :param contrast_auto: contrast auto value.
        """

        contrast_auto = ut.clip(int(contrast_auto), -70, 70)
        self._send_command(0xd2, contrast_auto)
        self._contrast_auto = contrast_auto
        self._need_update_config = True

    contrast_auto = property(get_contrast_auto, set_contrast_auto)

    def get_exposure(self, attempts: Optional[int] = -1) -> int:
        """
        Returns current exposure.
        :param attempts: number of attempts to update config.
        :return: exposure value [1..190].
        """

        self.update_config(attempts=attempts)
        return self._exposure

    def set_exposure(self, exposure: int):
        """
        Sets exposure and turns on manual mode.
        :param exposure: exposure [1..190] to set.
        """

        exposure = ut.clip(int(exposure), 1, 190)
        self.set_auto_gain_expo(False)  # Remember switch to manual mode
        # The exposure is also set right after start() command.
        # Search it in this file
        # See #41292 for more details
        self._send_command(0xc0, exposure)
        self._exposure = exposure
        self._need_update_config = True

    exposure = property(get_exposure, set_exposure)

    # For compatibility
    get_exposition = get_exposure
    set_exposition = set_exposure
    exposition = property(get_exposition, set_exposition)

    def get_exposure_ms(self, attempts: Optional[int] = -1) -> float:
        """
        Returns exposure value in ms.
        :param attempts: number of attempts to update config.
        :return: exposure value in ms.
        """

        self.update_config(attempts=attempts)
        return vac248ip_exposure_to_ms_by_video_format[self._video_format](self._exposure)

    exposure_ms = property(get_exposure_ms)

    # For compatibility
    get_exposition_ms = get_exposure_ms
    exposition_ms = property(get_exposition_ms)

    def get_frame_number(self) -> int:
        """
        Returns last frame number.
        :return: frame number.
        """

        return self._frame_number

    frame_number = property(get_frame_number)

    def get_frame_number_module(self) -> int:
        """
        Returns positive integer for frame number calculation (returned frame number
        always is %-ed to this value). If returned value is 0 then % (mod) operation
        is disabled. If returned value is -1 then frame counting is disabled.
        """

        return self._frame_number_module

    frame_number_module = property(get_frame_number_module)

    def get_gain_analog(self, attempts: Optional[int] = -1) -> int:
        """
        Returns analog gain value: 1..4 (means gain 1, 2, 4, 8).
        :param attempts: number of attempts to update config.
        :return: analog gain.
        """

        self.update_config(attempts=attempts)
        return self._gain_analog

    def set_gain_analog(self, gain_analog: int):
        """
        Sets analog gain value: 1..4 (means gain 1, 2, 4, 8).
        :param gain_analog: analog gain value to set.
        """

        gain_analog = ut.clip(int(gain_analog), 1, 4)
        self._send_command(0xb2, gain_analog)
        self._gain_analog = gain_analog
        self._need_update_config = True

    gain_analog = property(get_gain_analog, set_gain_analog)

    def get_gain_digital(self, attempts: Optional[int] = -1) -> int:
        """
        Returns digital gain value: 1..48 (means gain 0.25..12.0).
        :param attempts: number of attempts to update config.
        :return: digital gain.
        """

        self.update_config(attempts=attempts)
        return self._gain_digital

    def set_gain_digital(self, gain_digital: int):
        """
        Sets digital gain value: 1..48 (means gain 0.25..12.0).
        :param gain_digital: digital gain value.
        """

        gain_digital = ut.clip(int(gain_digital), 1, 48)
        self._send_command(0xb8, gain_digital)
        self._gain_digital = gain_digital
        self._need_update_config = True

    gain_digital = property(get_gain_digital, set_gain_digital)

    def get_gamma(self, attempts: Optional[int] = -1) -> Vac248IpGamma:
        """
        Returns gamma value.
        :param attempts: number of attempts to update config.
        :return: gamma value.
        """

        self.update_config(attempts=attempts)
        return self._gamma

    def set_gamma(self, gamma: Vac248IpGamma):
        """
        Sets gamma value.
        :param gamma: gamma value to set.
        """

        command_for_gamma = {Vac248IpGamma.GAMMA_045: 0x8c,
                             Vac248IpGamma.GAMMA_07: 0x8a,
                             Vac248IpGamma.GAMMA_1: 0x8e}
        gamma = Vac248IpGamma(gamma)
        self._send_command(command_for_gamma[gamma])
        self._gamma = gamma
        self._need_update_config = True

    gamma = property(get_gamma, set_gamma)

    def get_mac_address(self, attempts: Optional[int] = -1) -> bytes:
        """
        Returns camera MAC address.
        :param attempts: number of attempts to update config.
        :return: camera MAC address.
        """

        self.update_config(attempts=attempts)
        return self._camera_mac_address

    mac_address = property(get_mac_address)

    def get_max_gain_auto(self, attempts: Optional[int] = -1) -> int:
        """
        Returns max gain auto value: 1..10.
        :param attempts: number of attempts to update config.
        :return: max gain auto value.
        """

        self.update_config(attempts=attempts)
        return self._max_gain_auto

    def set_max_gain_auto(self, max_gain_auto: int) -> None:
        """
        Sets max gain auto value: 1..10.
        :param max_gain_auto: max gain auto value.
        """

        max_gain_auto = ut.clip(int(max_gain_auto), 0x01, 0x0a)
        self._send_command(0xd4, max_gain_auto)
        self._max_gain_auto = max_gain_auto
        self._need_update_config = True

    max_gain_auto = property(get_max_gain_auto, set_max_gain_auto)

    def get_sharpness(self, attempts: Optional[int] = -1) -> int:
        """
        Returns sharpness value: 0..8 (means 0, 12, 25, 37, 50, 62, 75, 87, 100%).
        :param attempts: number of attempts to update config.
        :return: sharpness.
        """

        self.update_config(attempts=attempts)
        return self._sharpness

    def set_sharpness(self, sharpness: int) -> None:
        """
        Sets sharpness value: 0..8 (means 0, 12, 25, 37, 50, 62, 75, 87, 100%).
        :param sharpness: sharpness value to set.
        """

        sharpness = ut.clip(int(sharpness), 0, 8)
        self._send_command(0xc6, sharpness)
        self._sharpness = sharpness
        self._need_update_config = True

    sharpness = property(get_sharpness, set_sharpness)

    def get_shutter(self, attempts: Optional[int] = -1) -> Vac248IpShutter:
        """
        Returns shutter value.
        :param attempts: number of attempts to update config.
        :return: shutter value.
        """

        self.update_config(attempts=attempts)
        return self._shutter

    def set_shutter(self, shutter: Vac248IpShutter):
        """
        Sets shutter value.
        :param shutter: shutter value to set.
        """

        command_for_shutter = {Vac248IpShutter.SHUTTER_GLOBAL: 0x36,
                               Vac248IpShutter.SHUTTER_ROLLING: 0x38}
        shutter = Vac248IpShutter(shutter)
        self._send_command(command_for_shutter[shutter])
        self._shutter = shutter
        self._need_update_config = True

    shutter = property(get_shutter, set_shutter)

    def get_video_format(self) -> Vac248IpVideoFormat:
        """
        Returns video format.
        :return: video format.
        """

        return self._video_format

    def set_video_format(self, video_format: Vac248IpVideoFormat):
        """
        Sets video format.
        :param video_format: video format to set.
        """

        if video_format in Vac248IpVideoFormat.get_10_bit_formats():
            raise ValueError("10-bit video mode not supported")
        self._video_format = Vac248IpVideoFormat(video_format)
        frame_width, frame_height, _, bytes_per_pixel = \
            vac248ip_frame_parameters_by_format[self._video_format]
        self._frame_buffer = np.zeros(frame_width * frame_height * bytes_per_pixel, dtype=np.uint8)

    video_format = property(get_video_format)

    def get_view_mode_10bit(self) -> Vac248Ip10BitViewMode:
        """
        Returns 10-bit view mode.
        :return: 10-bit view mode.
        """

        return self._view_mode_10bit

    def set_view_mode_10bit(self, view_mode_10bit: Vac248Ip10BitViewMode):
        """
        Sets 10-bit view mode.
        :param view_mode_10bit: 10-bit view mode.
        """

        self._view_mode_10bit = Vac248Ip10BitViewMode(view_mode_10bit)

    view_mode_10bit = property(get_view_mode_10bit, set_view_mode_10bit)
