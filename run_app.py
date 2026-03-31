"""Top-level entry point for PyInstaller bundling.

PyInstaller runs this as a script, not a module, so we use
absolute imports instead of the package's relative imports.
"""

import sys

from PySide6.QtWidgets import QApplication

from dicom_anonymizer.gui.main_window import MainWindow
from dicom_anonymizer.utils.config import APP_NAME, APP_ORG


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(APP_ORG)

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
