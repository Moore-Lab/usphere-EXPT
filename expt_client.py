"""
expt_client.py  —  usphere-EXPT top-level client

Loads the module registry from modules.yaml and provides attribute-style
access to each module's ZMQ client.  New modules added to modules.yaml
are picked up automatically.

Usage (interactive / experiment script)::

    from expt_client import ExptClient

    expt = ExptClient()

    print(expt.available())          # all registered modules
    print(expt.online())             # modules currently responding

    # Synchronous commands
    expt.ctrl.send("snapshot")
    expt.daq.send("start_recording", n_files=5)
    expt.daq.send("inject", data={"pressure_mbar": 1e-6})
    expt.q.send("get_charge")

    # Live subscription (runs callback in background thread)
    expt.ctrl.subscribe(lambda msg: print(msg["data"]))

    expt.close()
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

# zmq_base.py is canonical here; submodule copies are kept in sync.
sys.path.insert(0, str(Path(__file__).parent))
from zmq_base import ModuleClient

_REGISTRY_PATH = Path(__file__).parent / "modules.yaml"


def _load_yaml(path: Path) -> dict:
    """Load YAML without requiring PyYAML — fall back to a tiny parser for
    simple key: value files if the package is absent."""
    try:
        import yaml
        with open(path, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except ImportError:
        pass
    # Minimal fallback parser (handles the flat structure of modules.yaml)
    import re
    result: dict[str, Any] = {}
    current_module: str | None = None
    current_section: str | None = None
    with open(path, encoding="utf-8") as f:
        for raw in f:
            line = raw.rstrip()
            if not line or line.lstrip().startswith("#"):
                continue
            indent = len(raw) - len(raw.lstrip())
            stripped = line.strip()
            if indent == 0:
                m = re.match(r"^(\w+)\s*:", stripped)
                if m:
                    current_section = m.group(1)
                    result[current_section] = {}
            elif indent == 2 and current_section:
                m = re.match(r"^(\w+)\s*:", stripped)
                if m:
                    current_module = m.group(1)
                    result[current_section][current_module] = {}
            elif indent >= 4 and current_section and current_module:
                m = re.match(r'^(\w+)\s*:\s*"?([^"#]*)"?\s*$', stripped)
                if m:
                    key, val = m.group(1), m.group(2).strip()
                    try:
                        val = int(val)
                    except ValueError:
                        try:
                            val = float(val)
                        except ValueError:
                            pass
                    result[current_section][current_module][key] = val
    return result


class ExptClient:
    """
    Registry-aware client for all usphere modules.

    Attribute access returns a ModuleClient for the named module::

        expt = ExptClient()
        expt.ctrl.send("snapshot")   # ctrl module
        expt.daq.send("inject", data={...})

    The client does not open any sockets until the first send/subscribe
    call on a given module, so constructing ExptClient is always fast.
    """

    def __init__(self, registry_path: str | Path = _REGISTRY_PATH) -> None:
        self._clients: dict[str, ModuleClient] = {}
        self._registry: dict[str, dict] = {}
        self._load(Path(registry_path))

    def _load(self, path: Path) -> None:
        reg = _load_yaml(path)
        for name, cfg in reg.get("modules", {}).items():
            self._registry[name] = cfg
            self._clients[name] = ModuleClient(
                module_name=name,
                rep_port=int(cfg["rep_port"]),
                pub_port=int(cfg["pub_port"]),
                host=cfg.get("host", "localhost"),
                timeout_ms=int(cfg.get("timeout_ms", 2000)),
            )

    # ------------------------------------------------------------------
    # Module access
    # ------------------------------------------------------------------

    def __getattr__(self, name: str) -> ModuleClient:
        if name.startswith("_"):
            raise AttributeError(name)
        try:
            return self._clients[name]
        except KeyError:
            raise AttributeError(
                f"No module {name!r} in registry. "
                f"Available: {list(self._clients)}"
            )

    def __getitem__(self, name: str) -> ModuleClient:
        return self._clients[name]

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    def available(self) -> list[str]:
        """All module names in the registry."""
        return list(self._clients)

    def online(self) -> list[str]:
        """Module names that respond to a ping right now."""
        return [n for n, c in self._clients.items() if c.ping()]

    def registry_info(self, name: str) -> dict:
        """Return the raw registry entry for a module (ports, path, label)."""
        return dict(self._registry.get(name, {}))

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Close all open sockets."""
        for c in self._clients.values():
            c.close()

    def __enter__(self) -> "ExptClient":
        return self

    def __exit__(self, *_) -> None:
        self.close()
