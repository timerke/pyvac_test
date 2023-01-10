"""
File with class for real vac248ip camera.
"""

import argparse
import ctypes
import logging
import socket
import struct
import sys
import time
from typing import ByteString, List, Optional, Tuple, Union
import numpy as np
from .vac248ip_base import (Vac248IpCameraBase, Vac248IpGamma, Vac248IpShutter, Vac248IpVideoFormat,
                            vac248ip_frame_parameters_by_format)


__all__ = ["vac248ip_allow_native_library", "vac248ip_deny_native_library", "vac248ip_main", "Vac248IpCamera"]
_VAC248IP_CAMERA_DATA_PACKET_SIZE = 1472
_vac248ip_native_library_allowed = None


def vac248ip_allow_native_library() -> None:
    """
    Function no longer works. In the task #72286, it was decided to abandon the use of the native library,
    since it leaked memory, and the performance gain was not noticeable.
    """

    global _vac248ip_native_library_allowed
    if _vac248ip_native_library_allowed is None:
        _vac248ip_native_library_allowed = True


def vac248ip_deny_native_library() -> None:
    """
    Function no longer works. In the task #72286, it was decided to abandon the use of the native library,
    since it leaked memory, and the performance gain was not noticeable.
    """

    global _vac248ip_native_library_allowed
    if _vac248ip_native_library_allowed is None:
        _vac248ip_native_library_allowed = False


class Vac248IpCamera(Vac248IpCameraBase):
    """
    Vac248IP camera handler.
    Warning: when using mixed .get_frame()/.frame and .get_mean_frame()/.mean_frame,
    don't forget update frame before using mean/usual frame!
    """

    logger = logging.getLogger("Vac248ipCamera")
    # In seconds
    send_command_delay = 0.02
    drop_packets_delay = 0.1
    get_frame_delay = 0.02
    open_delay = 0.2

    def __init__(self, address: Union[str, Tuple[str, int]], *args,
                 video_format: Vac248IpVideoFormat = Vac248IpVideoFormat.FORMAT_1920x1200, num_frames: int = 1,
                 open_attempts: Optional[int] = 10, default_attempts: Optional[int] = None, defer_open: bool = False,
                 frame_number_module: int = 1000000, network_operation_timeout: Union[None, int, float] = 1,
                 udp_redundant_coeff: Union[int, float] = 1.5, allow_native_library: Optional[bool] = None) -> None:
        """
        Vac248IpCamera constructor.
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

        super().__init__(address, *args, video_format=video_format, num_frames=num_frames, open_attempts=open_attempts,
                         default_attempts=default_attempts, defer_open=defer_open,
                         frame_number_module=frame_number_module, network_operation_timeout=network_operation_timeout,
                         udp_redundant_coeff=udp_redundant_coeff, allow_native_library=allow_native_library)
        # Setting this on every initialization results in TypeErrors.
        # The function should be None only if the native library is
        # explicitly NOT being used.
        # self._capture_packets_native_fn = None
        self._capture_packets = self._capture_packets_universal
        if self._native_library_used:
            self._capture_packets = self._capture_packets_native
        else:
            self._capture_packets_native_fn = None
        if not defer_open:
            self.open_device(attempts=open_attempts)

    def _apply_config(self, config_buffer: Union[ByteString, np.ndarray, memoryview]) -> None:
        config = _Vac248IpCameraConfig(config_buffer)
        self._shutter = config.shutter
        self._gamma = config.gamma_correction
        self._auto_gain_expo = config.auto_gain_expo
        self._max_gain_auto = config.max_gain
        self._contrast_auto = config.contrast_auto
        self._exposure = config.exposure
        self._sharpness = config.sharpness
        self._gain_analog = config.gain_analog
        self._gain_digital = config.gain_digital
        self._camera_mac_address = config.mac_address
        self._need_update_config = False
        # For version-specific functionality, camera class should contain
        # version information
        self._camera_id = config.camera_id

    def _update_config(self, force: bool = False) -> None:
        if self._need_update_config or force:
            self._send_command_stop()
            self._drop_received_packets()
            self._send_command(0xf2)
            # Receive packet dropping other
            camera_socket = self._socket
            camera_address = self._camera_host
            packet_buffer = np.empty(_Vac248IpCameraConfig.PACKET_LENGTH, dtype=np.uint8)
            packet_length = _Vac248IpCameraConfig.PACKET_LENGTH
            while True:
                # If data packets for the current camera are bigger than config
                # packets, an error can occur when reading into the smaller
                # buffer
                try:
                    result_length, address = camera_socket.recvfrom_into(packet_buffer, packet_length)
                except OSError as e:
                    self.logger.debug("While awaiting configuration packet, "
                                      "error occurred: {}".format(e))
                    continue
                if result_length == packet_length and address[0] == camera_address:
                    break
            self._apply_config(packet_buffer)

    def _capture_packets_native(self, frames: int = 1) -> Tuple[memoryview, int]:
        """
        Captures packets required for building 'frames' frames.
        Returned buffer has structure:
            [type (1-byte) | data (1472 bytes)] ... [...]
            | <-              N chunks               -> |
            Where N = int(frames * (frame_packets + 1) * udp_redundant_coeff),
            type == 0 means data packet, type == 1 means config packet.
        :param frames: count of frames to be built.
        :return: (memory view to buffer, received packets).
        """

        _, _, frame_packets, _ = vac248ip_frame_parameters_by_format[self._video_format]

        # Frames data packets + at max 1 settings data packet (index to it saved to
        # settings_packet_index)
        packet_buffers_count = int(frames * (1 + frame_packets) * self._udp_redundant_coeff)
        packet_buffers = np.empty(packet_buffers_count * (_VAC248IP_CAMERA_DATA_PACKET_SIZE + 1),
                                  dtype=np.uint8)
        packet_buffers[::_VAC248IP_CAMERA_DATA_PACKET_SIZE + 1] = 0  # Default type = 0

        # Total count of received packets
        packets_received = ctypes.c_int(0)
        max_incorrect_length_packets = 100
        camera_ip, camera_port = self._socket.getpeername()

        res = self._capture_packets_native_fn(
            packet_buffers.ctypes.data_as(ctypes.POINTER(ctypes.c_uint8)),  # dst
            packet_buffers.shape[0],  # dst_size
            ctypes.byref(packets_received),  # packets_received
            self._socket.fileno(),  # socket_fd
            frames,  # frames
            frame_packets,  # frame_packets
            struct.unpack("@I", socket.inet_aton(camera_ip))[0],  # camera_ip
            camera_port,  # camera_port
            self._video_format.value,  # video_format
            max_incorrect_length_packets,  # max_incorrect_length_packets
            int(self.send_command_delay * 1000),  # send_command_delay_ms
            int(self.get_frame_delay * 1000),  # get_frame_delay_ms
            int(self.drop_packets_delay * 1000),  # drop_packets_delay_ms
            int(self._network_operation_timeout * 1000),  # network_operation_timeout_ms
            ctypes.c_uint8(self._exposure)  # exposure
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
        self.logger.debug("Received %s packet(s).", packets_received)
        return (memoryview(packet_buffers)[:packets_received * (_VAC248IP_CAMERA_DATA_PACKET_SIZE + 1)],
                packets_received)

    def _capture_packets_universal(self, frames: int = 1) -> Tuple[memoryview, int]:
        """
        Captures packets required for building 'frames' frames.
        Returned buffer has structure:
            [type (1-byte) | data (1472 bytes)] ... [...]
            | <-              N chunks               -> |
            Where N = int(frames * (frame_packets + 1) * udp_redundant_coeff),
            type == 0 means data packet, type == 1 means config packet.
        :param frames: count of frames to be built.
        :return: (memory view to buffer, received packets).
        """

        _, _, frame_packets, _ = vac248ip_frame_parameters_by_format[self._video_format]

        data_packet_size = _VAC248IP_CAMERA_DATA_PACKET_SIZE
        config_packet_size = _Vac248IpCameraConfig.PACKET_LENGTH

        camera_socket = self._socket
        camera_address = self._camera_host

        # Frames data packets + at max 1 settings data packet (index to it saved to
        # settings_packet_index)
        packet_buffers_count = int(frames * (1 + frame_packets) * self._udp_redundant_coeff)
        packet_buffers = np.empty(packet_buffers_count * (data_packet_size + 1), dtype=np.uint8)
        packet_buffers[::data_packet_size + 1] = 0  # Default type = 0 (data packet)
        packet_buffers_mv = memoryview(packet_buffers)

        # Total count of received packets
        packets_received = 0

        incorrect_length_packets = 0
        max_incorrect_length_packets = 100

        # Start video stream
        self._send_command_stop()
        self._drop_received_packets()
        self._send_command_start()

        # It is important to set expositions right here after start() command.
        # This affects for the image brightness.
        # If you will not set exposition here (and set it somewhere else),
        # the brightness will be different from the Vasily’s software.
        # See #41292 for more details
        self._send_command(0xc0, self._exposure)

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
                # [frame number (bytes: 0) | pix number (bytes: 1 hi, 2, 3 low) |
                # pixel data (bytes: [4...1472))]

                # Marked type == 0 by default
                incorrect_length_packets = 0

                # Frame numbers starts with 0
                frame_number = packet_buffer[0]

                if frame_number == 0:
                    # Skip the first frame, which can be overexposed
                    continue

                if frame_number > frames:
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
                continue
            packets_received += 1

        # Stop video stream
        self._send_command_stop()
        time.sleep(self.get_frame_delay)
        self._drop_received_packets()

        self.logger.debug("Received %s packet(s).", packets_received)
        return packet_buffers_mv[:packets_received * (data_packet_size + 1)], packets_received

    def _drop_received_packets(self) -> None:
        time.sleep(self.drop_packets_delay)
        packet_buffer = np.empty(_VAC248IP_CAMERA_DATA_PACKET_SIZE, dtype=np.uint8)
        packet_length = packet_buffer.shape[0]
        try:
            self._socket.setblocking(False)
            while True:
                self._socket.recvfrom_into(packet_buffer, packet_length)
        except BlockingIOError:
            pass
        finally:
            self._set_socket_blocking_with_timeout(self._network_operation_timeout)

    def _load_capture_packets_native_fn(self, native_library) -> None:
        self._capture_packets_native_fn = native_library.pyvac248ipnative_capture_packets
        self._capture_packets_native_fn.restype = ctypes.c_int
        self._capture_packets_native_fn.argtypes = (
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

    def _open(self) -> None:
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        try:
            self._socket.bind(("", self._camera_port))
            if self._network_operation_timeout is not None:
                self._socket.settimeout(self._network_operation_timeout)
            self._socket.connect((self._camera_host, self._camera_port))
            # Adjust receive socket buffer size
            # self.__socket.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 8192 * (64 + 5))

            # Try to stop camera, if it was opened before
            self._send_command_stop()
            time.sleep(self.open_delay)
            self._update_frame_without_frame_number_update(1, 1)
        except Exception:
            self._socket.close()
            self._socket = None
            raise

    def _send_command(self, command: int, data: int = 0) -> None:
        """
        Sends command.
        :param command: command code;
        :param data: data for command.
        """

        self._socket.send(bytes((command & 0xff, data & 0xff, 0, 0, 0, 0, 0, (command + data) & 0xff)))
        time.sleep(self.send_command_delay)

    def _set_socket_blocking_with_timeout(self, timeout: Union[None, int, float]) -> None:
        self._socket.setblocking(True)
        self._socket.settimeout(timeout)

    def _try_load_native_library(self) -> bool:
        try:
            import ctypes.util
        except ImportError:
            return False

        native_library_name = ctypes.util.find_library("pyvac248ipnative")
        if native_library_name is None:
            return False

        native_library = ctypes.CDLL(native_library_name, mode=ctypes.RTLD_LOCAL)
        # TODO: Check native library version.
        self._load_capture_packets_native_fn(native_library)
        return True

    def _update_frame(self, num_frames: int) -> None:
        """
        Updates frame using simple algorithm.
        NOTE: First frame from camera may be overexposed, so actual frames from camera
        will be (num_frames + 1). First frame from camera will be ignored on mean frame
        calculation, so result frame will be calculated using 'num_frames' frames.
        :param num_frames: frames from camera used to glue result frame.
        """

        frame_width, frame_height, frame_packets, bytes_per_pixel = \
            vac248ip_frame_parameters_by_format[self._video_format]
        frame_size = frame_width * frame_height * bytes_per_pixel

        default_frame_data_size = _VAC248IP_CAMERA_DATA_PACKET_SIZE - 4
        max_offset = default_frame_data_size * (frame_packets - 1)

        # Capture frames from video stream
        packet_buffers, packets_received = self._capture_packets(frames=num_frames)

        config_packet_index = None

        # Build frames using data packets
        frame_buffer = self._frame_buffer = np.zeros(frame_size, dtype=np.uint8)

        for packet_index in range(packets_received):
            packet_buffer_offset = packet_index * (_VAC248IP_CAMERA_DATA_PACKET_SIZE + 1)
            if packet_buffers[packet_buffer_offset] == 1:
                # Settings packet
                config_packet_index = packet_index
                continue

            packet_buffer = packet_buffers[packet_buffer_offset + 1:
                                           packet_buffer_offset + 1 + _VAC248IP_CAMERA_DATA_PACKET_SIZE]

            # Packet: [frame number (bytes: 0) | pix number (bytes: 1 hi, 2, 3 low) |
            # pixel data (bytes: [4...1472))]
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
                self._apply_config(packet_buffers[packet_buffer_offset + 1:
                                                  packet_buffer_offset + 1 + _Vac248IpCameraConfig.PACKET_LENGTH])
            except Exception:
                pass

    def _update_mean_frame(self, frames: int, num_frames: int) -> None:
        """
        Updates mean frame using glue-mean algorithm.
        NOTE: First frame from camera may be overexposed, so actual frames from camera
        will be (frames * num_frames + 1). First frame from camera will be ignored on
        mean frame calculation, so result frame will be calculated using (frames * num_frames)
        frames.

        Example: frames = 2, num_frames = 3:
            f1, f2, f3, f4, f5, f6  <- src frames from camera
            |   F1   |, |   F2   |  <- frames received as partially update (cumulative update)
            =        RES         =  <- average of (F1, F2)
        :param frames: glued sub-frames used to calculate mean frame;
        :param num_frames: frames from camera used to glue each sub-frame.
        """

        frame_width, frame_height, frame_packets, bytes_per_pixel = \
            vac248ip_frame_parameters_by_format[self._video_format]
        frame_size = frame_width * frame_height * bytes_per_pixel

        default_frame_data_size = _VAC248IP_CAMERA_DATA_PACKET_SIZE - 4
        max_offset = default_frame_data_size * (frame_packets - 1)

        # Capture frames from video stream
        packet_buffers, packets_received = self._capture_packets(frames=frames * num_frames)

        config_packet_index = None

        # Build frames using data packets
        frame_buffers = np.zeros((frames, frame_size), dtype=np.uint8)

        for packet_index in range(packets_received):
            packet_buffer_offset = packet_index * (_VAC248IP_CAMERA_DATA_PACKET_SIZE + 1)
            if packet_buffers[packet_buffer_offset] == 1:
                # Settings packet
                config_packet_index = packet_index
                continue

            packet_buffer = packet_buffers[packet_buffer_offset + 1:
                                           packet_buffer_offset + 1 + _VAC248IP_CAMERA_DATA_PACKET_SIZE]

            # Packet: [frame number (bytes: 0) | pix number (bytes: 1 hi, 2, 3 low) |
            # pixel data (bytes: [4...1472))]
            # Fix frame_number for skipped overexposed frame (1st frame)
            frame_number = packet_buffer[0] - 1
            offset = packet_buffer[1] << 16 | packet_buffer[2] << 8 | packet_buffer[3]

            # Filter incorrect offsets
            if offset > max_offset or offset % default_frame_data_size != 0:
                continue

            # Glue packet into frame
            actual_packet_size = min(default_frame_data_size, frame_size - offset)
            frame_buffers[frame_number // frames, offset:offset + actual_packet_size] \
                = packet_buffer[4:actual_packet_size + 4]

        self._frame_buffer = frame_buffers.mean(axis=0, dtype=np.uint16).astype(np.uint8)

        if config_packet_index is not None:
            try:
                packet_buffer_offset = config_packet_index * (_VAC248IP_CAMERA_DATA_PACKET_SIZE + 1)
                self._apply_config(
                    packet_buffers[packet_buffer_offset + 1:
                                   packet_buffer_offset + 1 + _Vac248IpCameraConfig.PACKET_LENGTH])
            except Exception:
                pass

    def _update_smart_mean_frame(self, frames: int) -> None:
        """
        Updates mean frame using smart algorithm.
        NOTE: First frame from camera may be overexposed, so actual frames from camera
        will be (frames + 1). First frame from camera will be ignored on mean frame calculation,
        so result frame will be calculated using 'frames' frames.
        :param frames: frames from camera used to calculate mean frame.
        """

        frame_width, frame_height, frame_packets, bytes_per_pixel = \
            vac248ip_frame_parameters_by_format[self._video_format]
        frame_size = frame_width * frame_height * bytes_per_pixel

        default_frame_data_size = _VAC248IP_CAMERA_DATA_PACKET_SIZE - 4
        max_offset = default_frame_data_size * (frame_packets - 1)

        # Capture frames from video stream
        packet_buffers, packets_received = self._capture_packets(frames=frames)

        config_packet_index = None

        # Build frames using data packets
        frame_buffers = np.zeros((frames, frame_size), dtype=np.uint8)

        # Received packets map by frame
        frame_packets_received = np.zeros((frames, frame_packets), dtype=np.bool_)

        for packet_index in range(packets_received):
            packet_buffer_offset = packet_index * (_VAC248IP_CAMERA_DATA_PACKET_SIZE + 1)
            if packet_buffers[packet_buffer_offset] == 1:
                # Settings packet
                config_packet_index = packet_index
                continue

            packet_buffer = packet_buffers[packet_buffer_offset + 1:
                                           packet_buffer_offset + 1 + _VAC248IP_CAMERA_DATA_PACKET_SIZE]

            # Packet: [frame number (bytes: 0) | pix number (bytes: 1 hi, 2, 3 low) |
            # pixel data (bytes: [4...1472))]
            # Fix frame_number for skipped overexposed frame (1st frame)
            frame_number = packet_buffer[0] - 1
            offset = packet_buffer[1] << 16 | packet_buffer[2] << 8 | packet_buffer[3]

            # Filter incorrect offsets
            if offset > max_offset or offset % default_frame_data_size != 0:
                continue

            # Glue packet into current frame
            actual_packet_size = min(default_frame_data_size, frame_size - offset)
            frame_buffers[frame_number, offset:offset + actual_packet_size] = packet_buffer[4:actual_packet_size + 4]

            frame_packets_received[frame_number, offset // default_frame_data_size] = True

        received_packets_counts = np.zeros(frame_packets, dtype=np.int_)

        frame_buffer = self._frame_buffer = np.empty(frame_size, dtype=np.uint8)
        for packet_index in range(frame_packets):
            offset = packet_index * default_frame_data_size
            actual_packet_size = min(default_frame_data_size, frame_size - offset)

            received_packets = frame_buffers[np.nonzero(frame_packets_received.transpose()[packet_index]),
                                             offset:offset + actual_packet_size]
            if received_packets.shape[1] > 0:
                frame_buffer[offset:offset + actual_packet_size] = received_packets.mean(axis=1, dtype=np.uint16)
            else:
                frame_buffer[offset:offset + actual_packet_size] = 0

            received_packets_counts[packet_index] = received_packets.shape[1]

        if config_packet_index is not None:
            try:
                packet_buffer_offset = config_packet_index * (_VAC248IP_CAMERA_DATA_PACKET_SIZE + 1)
                self._apply_config(packet_buffers[packet_buffer_offset + 1:
                                                  packet_buffer_offset + 1 + _Vac248IpCameraConfig.PACKET_LENGTH])
            except Exception:
                pass

    def _update_frame_without_frame_number_update(self, num_frames: Optional[int] = None, attempts: Optional[int] = -1
                                                  ) -> None:
        """
        Updates frame as glued frame.
        """

        if num_frames is None:
            num_frames = self._num_frames
        exception = None
        for _ in self._attempts_sequence(attempts):
            try:
                self._update_frame(num_frames)
                return
            except Exception as exc:
                exception = exc
        if exception is not None:
            raise exception

    def open_device(self, attempts: Optional[int] = 10) -> None:
        if self._socket is None:
            exception = None
            for _ in self._attempts_sequence(attempts):
                try:
                    self._open()
                    return
                except Exception as exc:
                    exception = exc
            if exception is not None:
                raise exception
            self._frame_number = 0

    def close_device(self) -> None:
        if self._socket is not None:
            try:
                self._send_command_stop()
            except Exception as exc:
                self.logger.warning("When closing camera exception caught: %s", exc, exc_info=sys.exc_info())
            finally:
                self._socket.close()
                self._socket = None
            self._frame_number = 0

    @property
    def is_open(self) -> bool:
        return self._socket is not None


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

    def __init__(self, buffer: Union[ByteString, np.ndarray, memoryview]):
        if len(buffer) != _Vac248IpCameraConfig.PACKET_LENGTH:
            raise ValueError("Incorrect buffer length (required: {}, but given: {})".format(
                _Vac248IpCameraConfig.PACKET_LENGTH, len(buffer)))

        # Unpack fields
        for field, value in zip(_Vac248IpCameraConfig.FIELDS, buffer):
            setattr(self, field, value)

        if self.check_0 != _Vac248IpCameraConfig.CHECK_0 or self.check_1 != _Vac248IpCameraConfig.CHECK_1:
            raise ValueError("Incorrect check bytes")
        if (self.camera_id != _Vac248IpCameraConfig.CAMERA_ID) and (self.camera_id != _Vac251IpCameraConfig.CAMERA_ID):
            raise ValueError("Camera ID {} not supported".format(
                hex(self.camera_id)
            ))

    def to_bytes(self) -> bytes:
        """
        Packs current object fields to ready-to-send buffer.
        """

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
        return self.management_data_0 + (self.management_data_1 << 8) + (self.management_data_2 << 16) + \
            (self.management_data_3 << 24)

    @property
    def gamma_correction(self) -> Vac248IpGamma:
        d = self.management_data
        if (d & 0x00080000) != 0:
            return Vac248IpGamma.GAMMA_1
        if (d & 0x00040000) != 0:
            return Vac248IpGamma.GAMMA_07
        return Vac248IpGamma.GAMMA_045

    @property
    def shutter(self) -> Vac248IpShutter:
        if (self.management_data & 0x20000000) != 0:
            return Vac248IpShutter.SHUTTER_GLOBAL
        return Vac248IpShutter.SHUTTER_ROLLING

    @property
    def auto_gain_expo(self) -> bool:
        return (self.management_data & 0x10000000) == 0

    @property
    def mac_address(self) -> bytes:
        return bytes((self.mac_0, self.mac_1, self.mac_2, self.mac_3, self.mac_4, self.mac_5))


class _Vac251IpCameraConfig(_Vac248IpCameraConfig):
    CAMERA_ID = 0xa


class Cameras:
    def __init__(self, addresses: List[str], video_format: Vac248IpVideoFormat = Vac248IpVideoFormat.FORMAT_960x600,
                 num_frames: int = 1, open_attempts: int = 10, default_attempts: Optional[int] = None,
                 allow_native_library: bool = True):
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
            Vac248IpCamera(address=address, video_format=self.__video_format,
                           num_frames=self.__num_frames, defer_open=True,
                           default_attempts=self.__default_attempts,
                           allow_native_library=self.__allow_native_library)
            for address in self.__addresses
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

    parser = argparse.ArgumentParser(prog=args[0])
    parser.add_argument("--count", "-c", dest="count", type=int, nargs="?", default=1,
                        help="Frames to get")
    parser.add_argument("--open-attempts", "-O", dest="open_attempts", type=int, nargs="?",
                        default=10, help="Open attempts for each camera (default: 10)")
    parser.add_argument("--attempts", "-a", dest="attempts", type=int, nargs="?", default=None,
                        help="Frame update attempts for each camera (default: infinity)")
    parser.add_argument("--frames", "-f", dest="frames", type=int, nargs="?", default=3,
                        help="Glued sub-frames to get frame (for mean algorithms)")
    parser.add_argument("--num-frames", "-n", dest="num_frames", type=int, nargs="?", default=1,
                        help="Camera frames used to get for result frame")
    parser.add_argument("--mode", "-m", type=str, nargs="?", default="simple",
                        help="Frame update mode, one of: 'simple' (default), 'mean', 'smart'. "
                             "'simple', uses --num-frames, 'mean' uses --frames and --num-frames, "
                             "'smart' uses --frames")
    parser.add_argument("--format", "-F", type=str, nargs="?", default="bmp",
                        help="Output image format ('bmp', 'png' or any other, supported by Pillow;"
                             " default: 'bmp')")
    parser.add_argument("--deny-native", "-U", dest="deny_native", action="store_true",
                        help="Deny native library usage, force universal version usage "
                             "(native library usage allowed by default)")
    parser.add_argument("--debug", dest="debug", action="store_true", help="Enable debug output")
    parser.add_argument("addresses", type=str, nargs="+",
                        help="Camera addresses in format HOST[:PORT] (default port is 1024)")
    parsed_args = parser.parse_args(args[1:])
    logging.basicConfig(level=logging.DEBUG if parsed_args.debug else logging.WARNING,
                        format="%(asctime)s %(levelname)s  %(message)s", datefmt="%F %T")
    image_format = parsed_args.format
    update_frame_mode_by_name = {
        "simple": lambda cam: cam.get_encoded_bitmap(num_frames=parsed_args.num_frames, image_format=image_format),
        "mean": lambda cam: cam.get_encoded_mean_bitmap(frames=parsed_args.frames, num_frames=parsed_args.num_frames,
                                                        image_format=image_format),
        "smart": lambda cam: cam.get_encoded_smart_mean_bitmap(frames=parsed_args.frames, image_format=image_format)
    }
    mode = parsed_args.mode.lower()
    get_bitmap_fn = update_frame_mode_by_name.get(mode)
    if get_bitmap_fn is None:
        print("Incorrect mode: '{}', expected one of: 'simple' (default), 'mean', 'smart'".format(parsed_args.mode),
              file=sys.stderr)
        return 1
    if parsed_args.debug:
        line_1_end = "\n"
        line_2_prefix = " => "
    else:
        line_1_end = ""
        line_2_prefix = " "

    with Cameras(addresses=parsed_args.addresses, video_format=Vac248IpVideoFormat.FORMAT_1920x1200,
                 num_frames=parsed_args.num_frames, open_attempts=parsed_args.open_attempts,
                 default_attempts=parsed_args.attempts, allow_native_library=not parsed_args.deny_native) as cameras:
        for camera in cameras:
            if camera.native_library_used:
                print("Native library used.")
            else:
                print("Native library not used.")
            break
        count = parsed_args.count
        for attempt_number in range(count):
            for camera_number, camera in enumerate(cameras):
                print("Attempt #{:0>3d}, camera #{:0>3d}...".format(attempt_number, camera_number), end=line_1_end,
                      flush=True)
                start_time = time.monotonic()
                bitmap, frame_number = get_bitmap_fn(camera)
                frame_get_time = time.monotonic() - start_time

                bitmap_name = "bitmap_m{}_a{:0>3d}_c{:0>3d}_f{:0>3d}.{}".format(mode, attempt_number, camera_number,
                                                                                frame_number, image_format)
                print("{}Got frame #{:0>3d}, {:.6f} s. File: {}".format(line_2_prefix, frame_number, frame_get_time,
                                                                        bitmap_name), flush=True)
                with open(bitmap_name, "wb") as file:
                    file.write(bitmap)
    return 0


if __name__ == "__main__":
    sys.exit(vac248ip_main(sys.argv))
