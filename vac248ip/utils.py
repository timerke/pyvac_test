"""
File with useful functions.
"""

import io
import os
from typing import List, Optional, Tuple, Union
from urllib.parse import urlparse
import numpy as np
from PIL import Image


vac248ip_default_port = 1024  # default port


def _check_image_file(file_name: str) -> bool:
    """
    Function returns True if file with given name exists and is image file.
    :param file_name: file name;
    :return: True if file is image file.
    """

    extensions = ".bmp", ".jpg", ".png"
    if (os.path.exists(file_name) and os.path.isfile(file_name) and
            os.path.splitext(file_name)[1].lower() in extensions):
        return True
    return False


def _create_image(width: int, height: int, amplitude: int) -> np.array:
    """
    Function creates image.
    :param width: width;
    :param height: height.
    :return: array with pixels of image.
    """

    length = width / 10
    pixels = np.zeros(width * height, dtype=np.uint8)
    pixels = pixels.reshape(height, width)
    for y in range(height):
        for x in range(width):
            r = np.sqrt((x - width / 2) ** 2 + (y - height / 2) ** 2)
            pixels[y][x] = int(amplitude * (1 + np.sin(2 * np.pi * r / length)))
    return pixels


def check_open(func):
    """
    Decorator to check whether camera is open.
    :param func: decorated method of camera.
    """

    def wrapper(self, *args, **kwargs):
        if not self.is_open:
            raise ValueError("Error! Camera is not open")
        return func(self, *args, **kwargs)
    return wrapper


def clip(value: Union[int, float], min_value: Union[int, float], max_value: Union[int, float]) ->\
        Union[int, float]:
    """
    Function returns available value in given range.
    :param value: given value;
    :param min_value: min available value;
    :param max_value: max available value.
    :return: available value.
    """

    if value < min_value:
        return min_value
    if max_value < value:
        return max_value
    return value


def convert_exposure_to_ms_960x600(exposure: int) -> float:
    """
    Converts exposure value in ms for image format 960x600.
    :param exposure: exposure.
    :return: exposure in ms.
    """

    if 1 <= exposure <= 50:
        return exposure * 1 * 0.100
    if 51 <= exposure <= 100:
        return 50 * 1 * 0.100 + exposure * 2 * 0.100
    if exposure <= 190:
        return 50 * 1 * 0.100 + 50 * 2 * 0.100 + (exposure - 100) * 5 * 0.100
    return 0.0


def convert_exposure_to_ms_1920x1200(exposure: int) -> float:
    """
    Converts exposure value in ms for image format 1920x1200.
    :param exposure: exposure.
    :return: exposure in ms.
    """

    if exposure <= 50:
        return exposure * 2 * 0.1833
    if 51 <= exposure <= 100:
        return 50 * 2 * 0.1833 + (exposure - 50) * 4 * 0.1833
    if exposure <= 190:
        return 50 * 2 * 0.1833 + 50 * 4 * 0.1833 + (exposure - 100) * 10 * 0.1833
    return 0.0


def create_image_files_list(image_files: List[str], image_dir: str) -> List[str]:
    """
    Function creates full list with names of files with images.
    :param image_files: list with names of files with images;
    :param image_dir: name of directory with images.
    :return: full list with names of files with images from list
    image_files and from directory image_dir.
    """

    full_image_files = []
    if image_files:
        for image_file in image_files:
            if _check_image_file(image_file):
                full_image_files.append(image_file)
            else:
                print("Warning! Image file '{}' was not found or is not image and will not be used".
                      format(image_file))
    if image_dir:
        if not os.path.exists(image_dir):
            print("Warning! Directory '{}' was not found and will not be used".format(image_dir))
        else:
            for file in os.listdir(image_dir):
                file = os.path.join(image_dir, file)
                if _check_image_file(file):
                    full_image_files.append(file)
    return full_image_files


def create_images(dir_name: str):
    """
    Functions creates images and saves them in directory.
    :param dir_name: name of directory where images will be saved.
    """

    sizes = (960, 600), (1920, 1200)
    amplitudes = 255 / 10, 255 / 5, 255 / 2
    for width, height in sizes:
        for amplitude in amplitudes:
            amplitude = int(amplitude)
            file_name = os.path.join(dir_name, f"{width}x{height} {amplitude}.bmp")
            pixels = _create_image(width, height, amplitude)
            image = Image.fromarray(pixels)
            image.save(file_name)


def encode_bitmap(frame: np.ndarray, image_format: str = "bmp") -> bytes:
    """
    Returns bitmap file data.
    :param frame: frame data;
    :param image_format: image data format ("bmp", "png", etc).
    :return: image data.
    """

    image = Image.fromarray(frame)
    del frame
    b = io.BytesIO()
    image.save(b, image_format)
    del image
    return b.getvalue()


def for_all_methods(decorator):
    def decorate(cls):
        for attr in cls.__bases__[0].__dict__:
            if callable(getattr(cls, attr)) and not attr.startswith("_") and attr != "open_device":
                setattr(cls, attr, decorator(getattr(cls, attr)))
        return cls
    return decorate


def get_host_and_port(address: Union[str, Tuple[str, int]]) -> Tuple[str, int]:
    """
    Returns host and port from given address.
    :param address: address may be string in format 'host' or 'host:port' or tuple
    with host and port.
    :return: host and port.
    """

    if isinstance(address, str):
        parsed_address = urlparse("http://{}".format(address))
        port = parsed_address.port if parsed_address.port is not None else vac248ip_default_port
        return parsed_address.hostname, port
    if (isinstance(address, tuple) and len(address) == 2 and isinstance(address[0], str) and
            isinstance(address[1], int)):
        return address
    raise ValueError("Incorrect address (expected str in format \'host[:port]\' ot tuple "
                     "(host: str, port: int), given value of type: {})".
                     format(type(address).__name__))


def open_image(file_name: str, width: int, height: int) -> Optional[np.ndarray]:
    """
    Function opens image file and returns array of pixels.
    :param file_name: name of file with image;
    :param width: required width of image;
    :param height: required height of image.
    :return: array of pixels.
    """

    image = Image.open(file_name)
    image_width, image_height = image.size
    if image_width != width or image_height != height:
        return None
    pixels = np.array(image)
    pixels_array = pixels.ravel()
    return pixels_array


if __name__ == "__main__":
    open_image("../test.bmp")
    create_images(".")
