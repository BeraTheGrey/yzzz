from __future__ import annotations

import traceback
from typing import Callable

from PySide6.QtCore import QThread, Signal

from ..library import Library


class LibraryWorker(QThread):
    """Run fn(library, progress, should_stop) on a thread with its own DB connection."""

    progress = Signal(int, int, str)
    result = Signal(object)
    failed = Signal(str)

    def __init__(self, db_path: str, fn: Callable, parent=None):
        super().__init__(parent)
        self.db_path = db_path
        self.fn = fn
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        lib = None
        try:
            lib = Library(self.db_path)
            value = self.fn(lib, lambda i, n, msg="": self.progress.emit(int(i), int(n), str(msg)),
                            lambda: self._stop)
            self.result.emit(value)
        except Exception as exc:  # reported to the user
            traceback.print_exc()
            self.failed.emit(str(exc) or exc.__class__.__name__)
        finally:
            if lib:
                lib.close()
