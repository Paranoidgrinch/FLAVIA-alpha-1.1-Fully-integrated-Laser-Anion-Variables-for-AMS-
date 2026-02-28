# main.py
from __future__ import annotations

import sys

from PyQt5.QtWidgets import QApplication

from backend.backend import Backend
from gui.mainwindow import MainWindow


def main() -> int:
    app = QApplication(sys.argv)

    backend = Backend()  # defaults in backend/channels.py
    backend.start()

    win = MainWindow(backend)
    win.show()

    return app.exec_()


if __name__ == "__main__":
    raise SystemExit(main())