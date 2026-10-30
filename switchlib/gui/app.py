from __future__ import annotations

import sys


def main() -> int:
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError:
        print("PySide6 is required for the GUI: pip install PySide6", file=sys.stderr)
        return 1

    from .. import i18n
    from ..library import Library
    from .main_window import MainWindow

    app = QApplication(sys.argv)
    app.setApplicationName("SwitchLib")
    app.setOrganizationName("SwitchLib")
    app.setStyle("Fusion")
    lib = Library()
    i18n.set_language(lib.get_setting("language", "") or i18n.system_language())
    window = MainWindow(lib)
    window.show()
    code = app.exec()
    lib.close()
    return code
