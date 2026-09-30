from __future__ import annotations

import unittest
from types import SimpleNamespace

from backend.backend import Backend


class SteererDefaultShutdownTests(unittest.TestCase):
    def test_defaults_do_not_write_after_backend_has_stopped(self):
        calls=[]
        backend=Backend.__new__(Backend)
        backend._started=False
        backend._default_steerer_channels=["steerer/1x/set_u"]
        backend.model=SimpleNamespace(get=lambda key: SimpleNamespace(value=None))
        backend.set_channel=lambda key,value: calls.append((key,value))

        Backend.apply_default_steerer_values_if_empty(backend)

        self.assertEqual(calls,[])


if __name__ == "__main__":
    unittest.main()
