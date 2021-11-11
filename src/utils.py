"""
File with useful functions.
"""

import configparser
import os
from . import config as cn


def get_info_about_parameters(config_file: str) -> dict:
    """
    Function returns default values for parameters of camera.
    :param config_file: name of config file with default values.
    :return: dictionary with main information about parameters of camera.
    """

    info = cn.CAMERA_PARAMETERS
    if os.path.exists(config_file):
        info = read_config_file(config_file, info)
    return info


def read_config_file(file_name: str, info: dict) -> dict:
    """
    Function reads default values for parameters of camera from config file.
    :param file_name: name of config file with default values;
    :param info: dictionary with main information about camera parameters.
    :return: dictionary with updated information about camera parameters.
    """

    config_parser = configparser.ConfigParser()
    try:
        config_parser.read(file_name)
    except (configparser.DuplicateOptionError, configparser.DuplicateSectionError,
            configparser.MissingSectionHeaderError, configparser.ParsingError):
        config_parser.clear()
    if not config_parser.has_section("INFO"):
        config_parser.add_section("INFO")
    for param in cn.CameraParameters.get_all_parameters():
        try:
            value = config_parser.getint("INFO", param.name, fallback=info[param][cn.DEFAULT])
            info[param][cn.DEFAULT] = cn.CameraParameters.get_value(param, value)
        except (KeyError, ValueError):
            pass
    return info


def write_config_file(file_name: str, info: dict):
    """
    Function writes default values for camera parameters to config file.
    :param file_name: name of config file with default values;
    :param info: dictionary with main information about camera parameters.
    """

    parser = configparser.ConfigParser()
    parser["INFO"] = {}
    for param, param_info in info.items():
        if hasattr(param_info[cn.DEFAULT], "value"):
            default_value = param_info[cn.DEFAULT].value
        else:
            default_value = param_info[cn.DEFAULT]
        parser["INFO"][param.name] = str(default_value)
    with open(file_name, "w") as file:
        parser.write(file)
