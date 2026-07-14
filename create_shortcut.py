"""
Run once to create a Windows desktop shortcut for expt_gui.py (unified GUI).

    python create_shortcut.py

Requires: pywin32  (pip install pywin32)

Python resolution order
-----------------------
1. .venv/ inside this directory  (created by install_deps.py)
2. ../usphere-FPGA/.venv/  (shared sibling venv with pylablib)
3. The Python that ran this script  (sys.executable)
"""

import sys
from pathlib import Path

try:
    from win32com.client import Dispatch
except ImportError:
    print("pywin32 is required.  Install it with:\n  pip install pywin32")
    sys.exit(1)

PROJECT_DIR = Path(__file__).resolve().parent
SCRIPT      = PROJECT_DIR / "expt_gui.py"
ICON_PATH   = PROJECT_DIR / "resources" / "icons" / "microsphere.ico"

_shell        = Dispatch("WScript.Shell")
DESKTOP       = Path(_shell.SpecialFolders("Desktop"))
SHORTCUT_PATH = DESKTOP / "usphere EXPT.lnk"


def _find_python() -> str:
    candidates = [
        PROJECT_DIR / ".venv" / "Scripts" / "pythonw.exe",
        PROJECT_DIR / ".venv" / "Scripts" / "python.exe",
        PROJECT_DIR.parent / "usphere-FPGA" / ".venv" / "Scripts" / "pythonw.exe",
        PROJECT_DIR.parent / "usphere-FPGA" / ".venv" / "Scripts" / "python.exe",
    ]
    for c in candidates:
        if c.exists():
            print(f"  Using Python: {c}")
            return str(c)

    fallback = Path(sys.executable).parent / "pythonw.exe"
    chosen = str(fallback if fallback.exists() else sys.executable)
    print(f"  Using Python (fallback): {chosen}")
    return chosen


python_exe = _find_python()

shortcut = _shell.CreateShortCut(str(SHORTCUT_PATH))
shortcut.TargetPath       = python_exe
shortcut.Arguments        = f'"{SCRIPT}"'
shortcut.WorkingDirectory = str(PROJECT_DIR)
shortcut.Description      = "usphere Experiment Control (unified)"
shortcut.IconLocation     = str(ICON_PATH) if ICON_PATH.exists() else python_exe
shortcut.save()

print(f"Shortcut created: {SHORTCUT_PATH}")
