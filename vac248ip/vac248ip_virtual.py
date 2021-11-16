"""
File with class to create virtual vac248ip camera.
"""

import logging
from typing import ByteString, List, Optional, Tuple, Union
import numpy as np
from . import utils as ut
from .vac248ip_base import (vac248ip_frame_parameters_by_format, Vac248IpCameraBase,
                            Vac248IpVideoFormat)


_vac248ip_native_library_allowed = None


@ut.for_all_methods(ut.check_open)
class Vac248IpCameraVirtual(Vac248IpCameraBase):
    """
    Virtual vac248ip camera handler.
    """

    logger = logging.getLogger("Virtual_vac248ip_camera")

    def __init__(self, address: Union[str, Tuple[str, int]], *args,
                 video_format: Vac248IpVideoFormat = Vac248IpVideoFormat.FORMAT_1920x1200,
                 num_frames: int = 1, open_attempts: Optional[int] = 10,
                 default_attempts: Optional[int] = None, defer_open: bool = False,
                 frame_number_module: int = 1000000,
                 network_operation_timeout: Union[None, int, float] = 1,
                 udp_redundant_coeff: Union[int, float] = 1.5,
                 allow_native_library: Optional[bool] = None, image_files: List[str] = None,
                 image_dir: str = None):
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
        for speed up some operations for you;
        :param image_files: list with names of files in which images are stored;
        :param image_dir: name of directory where images are stored.
        """

        super().__init__(address, *args, video_format=video_format, num_frames=num_frames,
                         open_attempts=open_attempts, default_attempts=default_attempts,
                         defer_open=defer_open, frame_number_module=frame_number_module,
                         network_operation_timeout=network_operation_timeout,
                         udp_redundant_coeff=udp_redundant_coeff,
                         allow_native_library=allow_native_library)
        self._is_open = False
        self._image_files = ut.create_image_files_list(image_files, image_dir)
        self._image_number = 0
        if not defer_open:
            self.open_device(attempts=open_attempts)

    def _apply_config(self, config_buffer: Union[ByteString, np.ndarray, memoryview]):
        self.__need_update_config = False

    def _update_config(self, force: bool = False):
        pass

    def _send_command(self, command: int, data: int = 0):
        """
        Sends command.
        :param command: command code;
        :param data: data for command.
        """

        pass

    def _try_load_native_library(self) -> bool:
        return True

    def _update_frame(self, num_frames: int = None):
        """
        Updates frame using simple algorithm.
        :param num_frames: frames from camera used to glue result frame.
        """

        if len(self._image_files) == 0:
            return
        width, height, _, _ = vac248ip_frame_parameters_by_format[self._video_format]
        init_image_number = self._image_number
        while True:
            if self._image_number >= len(self._image_files):
                self._image_number = 0
            image_file = self._image_files[self._image_number]
            self._image_number += 1
            frame_buffer = ut.open_image(image_file, width, height)
            if frame_buffer is not None:
                self._frame_buffer = frame_buffer
                break
            if self._image_number == init_image_number:
                print("Warning! There is not image with required sizes")
                break

    def _update_mean_frame(self, frames: int = None, num_frames: int = None):
        """
        Updates mean frame using glue-mean algorithm.
        :param frames: glued sub-frames used to calculate mean frame;
        :param num_frames: frames from camera used to glue each sub-frame.
        """

        self._update_frame()

    def _update_smart_mean_frame(self, frames: int = None):
        """
        Updates mean frame using smart algorithm.
        :param frames: frames from camera used to calculate mean frame.
        """

        self._update_frame()

    def open_device(self, attempts: Optional[int] = 10):
        self._is_open = True
        self._frame_number = 0
        self._image_number = 0

    def close_device(self):
        self._is_open = False
        self._frame_number = 0
        self._image_number = 0

    @property
    def is_open(self) -> bool:
        return self._is_open
