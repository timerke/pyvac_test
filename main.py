"""
File to run application.
"""

import logging
import os
import sys
import traceback
from PyQt5.QtCore import pyqtSignal, QObject
from PyQt5.QtWidgets import QApplication, QMessageBox
from src.main_window import MainWindow
from src.utils import get_dir_name


def create_logger() -> logging.Logger:
    """
    Function creates logger for application.
    :return: logger.
    """

    formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    stream_handler.setLevel(logging.INFO)
    file_name = os.path.join(get_dir_name(), "logs.log")
    file_handler = logging.FileHandler(file_name)
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.INFO)
    logger = logging.getLogger("pyvac_test")
    logger.addHandler(stream_handler)
    logger.addHandler(file_handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    return logger


def show_exception(msg_title: str, msg_text: str, exc: str = ""):
    """
    Function shows message box with error.
    :param msg_title: title of message box;
    :param msg_text: message text;
    :param exc: text of exception.
    """

    msg = QMessageBox()
    msg.setIcon(QMessageBox.Warning)
    msg.setWindowTitle(msg_title)
    msg.setText(msg_text)
    if exc:
        msg.setInformativeText(str(exc)[-500:])
    msg.exec_()


class ExceptionHandler(QObject):
    """
    Class to handle unexpected errors.
    """

    exception_raised = pyqtSignal(str, str, str)

    def exception_hook(self, exc_type: Exception, exc_value: Exception, exc_traceback: "traceback"):
        """
        Method handles unexpected errors.
        :param exc_type: exception class;
        :param exc_value: exception instance;
        :param exc_traceback: traceback object.
        """

        traceback.print_exception(exc_type, exc_value, exc_traceback)
        traceback_text = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
        full_msg_text = (f"Произошла ошибка. Сфотографируйте сообщение с ошибкой и обратитесь "
                         f"в техподдержку.\n\n{str(exc_value)}")
        self.exception_raised.emit("Error", full_msg_text, traceback_text)


if __name__ == "__main__":

    create_logger()
    app = QApplication(sys.argv)
    exceprion_handler = ExceptionHandler()
    sys.excepthook = exceprion_handler.exception_hook
    exceprion_handler.exception_raised.connect(show_exception)
    main_window = MainWindow()
    main_window.show()
    app.exec()
