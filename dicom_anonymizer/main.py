"""DICOM Anonymizer — Entry Point."""

import sys

from PySide6.QtWidgets import QApplication

from .gui.main_window import MainWindow
from .utils.config import APP_NAME, APP_ORG


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(APP_ORG)

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
