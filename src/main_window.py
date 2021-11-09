"""
File with class for main window of application.
"""

import os
from PyQt5.QtCore import QRegExp
from PyQt5.QtGui import QIcon, QRegExpValidator
from PyQt5.QtWidgets import QMainWindow
from PyQt5.uic import loadUi


class MainWindow(QMainWindow):
    """
    Class for main window of application.
    """

    def __init__(self, *args):
        super().__init__(*args)
        self._init_ui()

    def _init_ui(self):
        """
        Method initializes widgets on main window.
        """

        dir_name = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        file_name = os.path.join(dir_name, "gui", "main_window.ui")
        loadUi(file_name, self)
        self.setWindowTitle("pyvac_test")
        icon = QIcon(os.path.join(dir_name, "gui", "icon.png"))
        self.setWindowIcon(icon)

        reg_exp = QRegExp("^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$")
        validator = QRegExpValidator(reg_exp, self)
        self.line_edit_ip_address.setValidator(validator)
