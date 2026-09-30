import importlib.util
import unittest
from types import SimpleNamespace

class Button:
    def setEnabled(self, _value): pass

class Label:
    def setText(self, _text): pass

class Timer:
    def stop(self): pass

@unittest.skipUnless(importlib.util.find_spec("PyQt5"), "PyQt5 required")
class TracerSetpointRestoreTests(unittest.TestCase):
    def test_1d_finish_restores_original_setpoint(self):
        from gui.windows.tracer_1d import Tracer1DDialog
        calls=[]
        obj=SimpleNamespace(tracing_active=True,timer=Timer(),_restore_keithley_settings=lambda:None,stop_btn=Button(),start_btn=Button(),export_btn=Button(),apply_btn=Button(),x_values=[],y_values=[],original_value=12.5,applied_value=None,param=SimpleNamespace(channel="p"),_set_param_value=lambda ch,v:calls.append((ch,v)),_best_index=lambda:None,status_label=Label())
        obj._restore_original_setpoint=lambda:Tracer1DDialog._restore_original_setpoint(obj)
        Tracer1DDialog._finish_trace(obj)
        self.assertEqual(calls, [("p",12.5)])

    def test_1d_stop_restores_original_setpoint(self):
        from gui.windows.tracer_1d import Tracer1DDialog
        calls=[]
        obj=SimpleNamespace(tracing_active=True,timer=Timer(),_restore_keithley_settings=lambda:None,stop_btn=Button(),start_btn=Button(),export_btn=Button(),apply_btn=Button(),x_values=[],y_values=[],original_value=12.5,applied_value=None,param=SimpleNamespace(channel="p"),_set_param_value=lambda ch,v:calls.append((ch,v)),_best_index=lambda:None,status_label=Label())
        obj._restore_original_setpoint=lambda:Tracer1DDialog._restore_original_setpoint(obj)
        Tracer1DDialog.stop_trace(obj)
        self.assertEqual(calls, [("p",12.5)])

    def test_2d_finish_restores_both_original_setpoints(self):
        from gui.windows.tracer_2d import Tracer2DDialog
        calls=[]
        obj=SimpleNamespace(running=True,timer=Timer(),_restore_keithley_settings=lambda:None,btn_stop=Button(),btn_start=Button(),btn_export=Button(),btn_apply=Button(),_has_any_data=lambda:False,_best_cell=lambda:(None,None,None),status=Label(),orig1=1.5,orig2=2.5,applied=None,param1=SimpleNamespace(channel="p1"),param2=SimpleNamespace(channel="p2"),_set_param_value=lambda ch,v:calls.append((ch,v)))
        obj._restore_original_setpoints=lambda:Tracer2DDialog._restore_original_setpoints(obj)
        Tracer2DDialog._finish(obj)
        self.assertEqual(calls, [("p1",1.5),("p2",2.5)])

    def test_2d_stop_restores_both_original_setpoints(self):
        from gui.windows.tracer_2d import Tracer2DDialog
        calls=[]
        obj=SimpleNamespace(running=True,timer=Timer(),_restore_keithley_settings=lambda:None,btn_stop=Button(),btn_start=Button(),btn_export=Button(),btn_apply=Button(),_has_any_data=lambda:False,_best_cell=lambda:(None,None,None),status=Label(),orig1=1.5,orig2=2.5,applied=None,param1=SimpleNamespace(channel="p1"),param2=SimpleNamespace(channel="p2"),_set_param_value=lambda ch,v:calls.append((ch,v)))
        obj._restore_original_setpoints=lambda:Tracer2DDialog._restore_original_setpoints(obj)
        Tracer2DDialog.stop_trace(obj)
        self.assertEqual(calls, [("p1",1.5),("p2",2.5)])

if __name__ == "__main__":
    unittest.main()
