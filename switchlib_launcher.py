"""Entry point for frozen builds (PyInstaller)."""

import sys

if __name__ == "__main__":
    # windowed builds on Windows have no console (sys.stdout is None): always start the GUI there
    if len(sys.argv) > 1 and sys.stdout is not None:
        from switchlib.cli import main
    else:
        from switchlib.gui.app import main
    sys.exit(main())
