"""
File with useful functions.
"""

import configparser
import os
import sys
from . import config as cn


def get_dir_name() -> str:
    """
    Function returns path to directory with executable file or code files.
    :return: path to directory.
    """

    if getattr(sys, "frozen", False):
        path = os.path.dirname(os.path.abspath(sys.executable))
    else:
        path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return path


def get_info_about_parameters(config_file: str) -> dict:
    """
    Function returns dictionaries with main information about camera parameters.
    :param config_file: name of config file.
    :return: dictionary with main information about parameters of camera and
    dictionary with test settings.
    """

    camera_info = cn.CAMERA_PARAMETERS
    if os.path.exists(config_file):
        read_config_file(config_file, camera_info)
    return camera_info


def read_config_file(file_name: str, camera_info: dict):
    """
    Function reads default values for parameters of camera from config file.
    :param file_name: name of config file;
    :param camera_info: dictionary with main information about camera parameters.
    """

    config_parser = configparser.ConfigParser()
    try:
        config_parser.read(file_name)
    except (configparser.DuplicateOptionError, configparser.DuplicateSectionError,
            configparser.MissingSectionHeaderError, configparser.ParsingError):
        config_parser.clear()
    if not config_parser.has_section("DEFAULT_VALUES"):
        config_parser.add_section("DEFAULT_VALUES")
    for param in cn.CameraParameters.get_all_parameters():
        try:
            value = config_parser.getint("DEFAULT_VALUES", param.name,
                                         fallback=camera_info[param][cn.DEFAULT])
            camera_info[param][cn.DEFAULT] = cn.CameraParameters.get_value(param, value)
        except (KeyError, ValueError):
            pass


def write_config_file(file_name: str, camera_info: dict):
    """
    Function writes default values for camera parameters to config file.
    :param file_name: name of config file;
    :param camera_info: dictionary with main information about camera parameters.
    """

    parser = configparser.ConfigParser()
    parser["DEFAULT_VALUES"] = {}
    for param, param_info in camera_info.items():
        if hasattr(param_info[cn.DEFAULT], "value"):
            default_value = param_info[cn.DEFAULT].value
        else:
            default_value = param_info[cn.DEFAULT]
        parser["DEFAULT_VALUES"][param.name] = str(default_value)
    with open(file_name, "w") as file:
        parser.write(file)
