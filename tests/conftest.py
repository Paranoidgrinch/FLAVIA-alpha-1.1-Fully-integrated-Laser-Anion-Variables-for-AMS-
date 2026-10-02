import sys
import types
from pathlib import Path

# Load backend submodules for isolated unit tests without executing
# backend/__init__.py (which imports optional GUI/MQTT runtime dependencies).
root = Path(__file__).resolve().parents[1]
pkg = types.ModuleType("backend")
pkg.__path__ = [str(root / "backend")]
sys.modules.setdefault("backend", pkg)
