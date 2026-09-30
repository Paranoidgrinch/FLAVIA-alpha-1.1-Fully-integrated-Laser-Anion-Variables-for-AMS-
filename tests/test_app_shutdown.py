from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

import main


class FakeSignal:
    def __init__(self):
        self.callback = None
    def connect(self, callback):
        self.callback = callback


class FakeApp:
    def __init__(self):
        self.aboutToQuit = FakeSignal()
    def exec_(self):
        if self.aboutToQuit.callback is not None:
            self.aboutToQuit.callback()
        return 0


class ApplicationShutdownTests(unittest.TestCase):
    def test_backend_is_stopped_when_application_quits(self):
        app = FakeApp()
        backend = MagicMock()
        window = MagicMock()

        with patch.object(main, "QApplication", return_value=app), patch.object(main, "Backend", return_value=backend), patch.object(main, "MainWindow", return_value=window):
            result = main.main()

        self.assertEqual(result, 0)
        backend.start.assert_called_once_with()
        backend.stop.assert_called_once_with()
        window.show.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
