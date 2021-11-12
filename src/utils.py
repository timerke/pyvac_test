"""
File with useful functions.
"""

import configparser
import os
from typing import Tuple
from . import config as cn


def get_info_about_parameters(config_file: str) -> Tuple[dict, dict]:
    """
    Function returns dictionaries with main information about camera parameters
    and test settings.
    :param config_file: name of config file.
    :return: dictionary with main information about parameters of camera and
    dictionary with test settings.
    """

    camera_info = cn.CAMERA_PARAMETERS
    test_settings = cn.TEST_SETTINGS
    if os.path.exists(config_file):
        read_config_file(config_file, camera_info, test_settings)
    return camera_info, test_settings


def read_config_file(file_name: str, camera_info: dict, test_settings: dict):
    """
    Function reads default values for parameters of camera and test settings
    from config file.
    :param file_name: name of config file;
    :param camera_info: dictionary with main information about camera parameters;
    :param test_settings: dictionary with test settings.
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
    if not config_parser.has_section("TESTS"):
        config_parser.add_section("TESTS")
    for setting in cn.TestSettings.get_all_parameters():
        try:
            value = config_parser.getint("TESTS", setting.name,
                                         fallback=test_settings[setting][cn.VALUE])
            test_settings[setting][cn.VALUE] = cn.TestSettings.get_value(setting, value)
        except (KeyError, ValueError):
            pass


def write_config_file(file_name: str, camera_info: dict, test_settings: dict):
    """
    Function writes default values for camera parameters and test settings to
    config file.
    :param file_name: name of config file;
    :param camera_info: dictionary with main information about camera parameters;
    :param test_settings: dictionary with test settings.
    """

    parser = configparser.ConfigParser()
    parser["DEFAULT_VALUES"] = {}
    for param, param_info in camera_info.items():
        if hasattr(param_info[cn.DEFAULT], "value"):
            default_value = param_info[cn.DEFAULT].value
        else:
            default_value = param_info[cn.DEFAULT]
        parser["DEFAULT_VALUES"][param.name] = str(default_value)
    parser["TESTS"] = {}
    for setting, setting_info in test_settings.items():
        parser["TESTS"][setting.name] = str(setting_info[cn.VALUE])
    with open(file_name, "w") as file:
        parser.write(file)
