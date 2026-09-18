import importlib.util
import unittest


@unittest.skipUnless(importlib.util.find_spec("PyQt5"), "PyQt5 required")
class KeithleySettingsRangeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PyQt5.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_fixed_range_combo_exposes_only_real_6485_ranges(self):
        from backend.workers.keithley_6485_worker import KEITHLEY_6485_RANGES_NA, TuneSettings
        from gui.windows.keithley_settings import _ModeBox

        box = _ModeBox("TUNE", True, TuneSettings())
        values = [float(box.cb_fixed.itemData(i)) for i in range(box.cb_fixed.count())]
        self.assertEqual(values, list(KEITHLEY_6485_RANGES_NA))

    def test_default_100_na_setting_is_shown_as_200_na_hardware_range(self):
        from backend.workers.keithley_6485_worker import TuneSettings
        from gui.windows.keithley_settings import _ModeBox

        box = _ModeBox("TUNE", True, TuneSettings())
        self.assertEqual(float(box.cb_fixed.currentData()), 200.0)

    def test_build_range_returns_selected_hardware_range(self):
        from backend.workers.keithley_6485_worker import TuneSettings
        from gui.windows.keithley_settings import _ModeBox

        box = _ModeBox("TUNE", True, TuneSettings())
        box.cb_auto.setChecked(False)
        box.cb_fixed.setCurrentIndex(0)
        result = box.build_range()
        self.assertFalse(result.auto)
        self.assertEqual(result.fixed_range_nA, 2.0)


if __name__ == "__main__":
    unittest.main()
