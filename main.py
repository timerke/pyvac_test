"""
File to run application.
"""

import sys
import traceback
from PyQt5.QtCore import pyqtSignal, QObject
from PyQt5.QtWidgets import QApplication, QMessageBox
from src.main_window import MainWindow


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

    app = QApplication(sys.argv)
    exceprion_handler = ExceptionHandler()
    sys.excepthook = exceprion_handler.exception_hook
    exceprion_handler.exception_raised.connect(show_exception)
    main_window = MainWindow()
    main_window.show()
    app.exec()
