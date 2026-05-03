"""
expt_gui.py  —  usphere-EXPT unified GUI

Launches all registered modules in a single process, embeds each module's
widget as a tab, and starts their ZMQ servers in background threads so
external scripts can still connect and command the live session.

Run with::

    python expt_gui.py                  # load all modules from modules.yaml
    python expt_gui.py --modules ctrl daq   # load a subset

Architecture
------------
- Each module's server (ctrl_server.CtrlServer, etc.) is started in a
  background thread sharing the same backend object as the GUI widget.
- Experiment scripts connect via ZMQ as usual — the server ports match
  those in modules.yaml.
- New modules added to modules.yaml appear automatically as tabs the next
  time the GUI is launched.

Adding a new module
-------------------
1. Add an entry to modules.yaml.
2. Implement <module>_server.py with a server class and a widget class
   (or just the server; the tab falls back to a status panel if no widget
   is importable).
"""

from __future__ import annotations

import argparse
import importlib
import logging
import sys
import threading
import time
from pathlib import Path
from typing import Any

from PyQt5.QtCore import QTimer, Qt, pyqtSignal, QObject
from PyQt5.QtGui import QFont, QIcon
from PyQt5.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QStatusBar,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

_HERE = Path(__file__).parent
_ROOT = _HERE.parent   # repo root — all submodule paths are relative to this

if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from expt_client import ExptClient, _load_yaml

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Module descriptor — one per entry in modules.yaml
# ---------------------------------------------------------------------------

class ModuleDescriptor:
    """Runtime state for one registered module."""

    def __init__(self, name: str, cfg: dict) -> None:
        self.name     = name
        self.label    = cfg.get("label", name)
        self.rep_port = int(cfg["rep_port"])
        self.pub_port = int(cfg["pub_port"])
        self.path     = _ROOT / cfg["path"]   # absolute path to submodule dir
        self.entry    = cfg.get("entry", f"{name}_server.py")

        self.server   = None    # ModuleServer instance
        self.widget   = None    # QWidget instance (None → status fallback tab)
        self.online   = False


# ---------------------------------------------------------------------------
# Per-module loading logic
# ---------------------------------------------------------------------------

_MODULE_LOADERS: dict[str, Any] = {}   # name → loader fn, populated below


def _add_submodule_path(desc: ModuleDescriptor) -> None:
    """Make the submodule importable."""
    path_str = str(desc.path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)


def _load_ctrl(desc: ModuleDescriptor) -> None:
    _add_submodule_path(desc)
    from fpga_core import FPGAController
    from ctrl_server import CtrlServer
    from fpga_gui import FPGAWidget

    fpga = FPGAController()
    server = CtrlServer(fpga, rep_port=desc.rep_port, pub_port=desc.pub_port)
    server.start()
    widget = FPGAWidget(controller=fpga)

    desc.server = server
    desc.widget = widget
    desc.online = True
    log.info("ctrl: server started (REP=%d PUB=%d)", desc.rep_port, desc.pub_port)


def _load_daq(desc: ModuleDescriptor) -> None:
    _add_submodule_path(desc)
    from daq_server import DAQServer
    from daq_gui import DAQWidget

    server = DAQServer(rep_port=desc.rep_port, pub_port=desc.pub_port)
    server.start()
    widget = DAQWidget(server=server)

    desc.server = server
    desc.widget = widget
    desc.online = True
    log.info("daq: server started (REP=%d PUB=%d)", desc.rep_port, desc.pub_port)


def _load_q(desc: ModuleDescriptor) -> None:
    _add_submodule_path(desc)
    from q_server import QServer
    from charge_gui import ChargeWidget

    server = QServer(rep_port=desc.rep_port, pub_port=desc.pub_port)
    server.start()
    widget = ChargeWidget(
        controller=server._controller,
        flashlamp=server._flashlamp,
        filament=server._filament,
    )

    desc.server = server
    desc.widget = widget
    desc.online = True
    log.info("q: server started (REP=%d PUB=%d)", desc.rep_port, desc.pub_port)


def _load_generic(desc: ModuleDescriptor) -> None:
    """
    Fallback for modules not listed in _MODULE_LOADERS.
    Tries to import <name>_server.py and call its server class,
    and optionally a widget from <name>_gui.py.
    """
    _add_submodule_path(desc)
    server_mod_name = Path(desc.entry).stem   # e.g. "slowctrl_server"
    try:
        srv_mod = importlib.import_module(server_mod_name)
        # Find the first ModuleServer subclass in the module
        from zmq_base import ModuleServer
        srv_cls = next(
            (v for v in vars(srv_mod).values()
             if isinstance(v, type) and issubclass(v, ModuleServer) and v is not ModuleServer),
            None,
        )
        if srv_cls:
            server = srv_cls(rep_port=desc.rep_port, pub_port=desc.pub_port)
            server.start()
            desc.server = server
            desc.online = True
            log.info("%s: server started (REP=%d)", desc.name, desc.rep_port)
    except Exception as exc:
        log.warning("%s: could not load server — %s", desc.name, exc)

    # Try widget
    gui_mod_name = f"{desc.name}_gui"
    try:
        gui_mod = importlib.import_module(gui_mod_name)
        widget_cls = getattr(gui_mod, f"{desc.name.capitalize()}Widget", None)
        if widget_cls:
            desc.widget = widget_cls()
    except Exception:
        pass


_MODULE_LOADERS = {
    "ctrl": _load_ctrl,
    "daq":  _load_daq,
    "q":    _load_q,
}


# ---------------------------------------------------------------------------
# Status fallback tab (shown when a module has no widget)
# ---------------------------------------------------------------------------

class _StatusTab(QWidget):
    def __init__(self, desc: ModuleDescriptor) -> None:
        super().__init__()
        vbox = QVBoxLayout(self)
        vbox.setAlignment(Qt.AlignCenter)

        state = "ONLINE" if desc.online else "OFFLINE / NOT LOADED"
        colour = "#2ecc71" if desc.online else "#e74c3c"
        lbl = QLabel(f"{desc.label}\n\n{state}\nREP port: {desc.rep_port}")
        lbl.setAlignment(Qt.AlignCenter)
        lbl.setStyleSheet(f"color: {colour}; font-size: 14px;")
        vbox.addWidget(lbl)

        if desc.online:
            note = QLabel("Widget not available — use the CLI or experiment scripts.")
            note.setAlignment(Qt.AlignCenter)
            note.setStyleSheet("color: gray; font-size: 11px;")
            vbox.addWidget(note)


# ---------------------------------------------------------------------------
# Unified main window
# ---------------------------------------------------------------------------

class ExptWindow(QMainWindow):
    """
    Unified usphere experiment GUI.

    One tab per registered module (ctrl, daq, q, …).
    Each module's ZMQ server runs in a background thread sharing the same
    backend objects as the embedded widget — external scripts connect normally.
    """

    def __init__(self, module_names: list[str] | None = None) -> None:
        super().__init__()
        self.setWindowTitle("usphere — Experiment Control")
        self.resize(1500, 950)

        self._descriptors: list[ModuleDescriptor] = []
        self._load_modules(module_names)
        self._build_ui()
        self._start_status_poll()

    # ------------------------------------------------------------------
    # Module loading
    # ------------------------------------------------------------------

    def _load_modules(self, names: list[str] | None) -> None:
        reg = _load_yaml(_HERE / "modules.yaml")
        for name, cfg in reg.get("modules", {}).items():
            if names and name not in names:
                continue
            desc = ModuleDescriptor(name, cfg)
            loader = _MODULE_LOADERS.get(name, _load_generic)
            try:
                loader(desc)
            except Exception as exc:
                log.error("Failed to load module %r: %s", name, exc)
            self._descriptors.append(desc)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        self._tabs = QTabWidget()
        self._tabs.setTabPosition(QTabWidget.West)
        self.setCentralWidget(self._tabs)

        for desc in self._descriptors:
            widget = desc.widget if desc.widget is not None else _StatusTab(desc)
            self._tabs.addTab(widget, desc.label)

        # Status bar — shows ZMQ server states
        self._status_bar = self.statusBar()
        self._update_status_bar()

    def _update_status_bar(self) -> None:
        parts = []
        for desc in self._descriptors:
            icon = "●" if desc.online else "○"
            parts.append(f"{icon} {desc.name}:{desc.rep_port}")
        self._status_bar.showMessage("   ".join(parts))

    def _start_status_poll(self) -> None:
        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self._update_status_bar)
        self._poll_timer.start(5000)   # refresh status bar every 5 s

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def closeEvent(self, event) -> None:
        for desc in self._descriptors:
            if desc.server is not None:
                try:
                    desc.server.stop()
                except Exception:
                    pass
        super().closeEvent(event)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="usphere unified experiment GUI")
    p.add_argument(
        "--modules", nargs="*", metavar="NAME",
        help="names of modules to load (default: all from modules.yaml)",
    )
    return p.parse_args()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-7s  %(name)s  %(message)s",
    )
    args = _parse_args()

    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "yale.usphere.expt"
        )
    except Exception:
        pass

    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    window = ExptWindow(module_names=args.modules)
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
