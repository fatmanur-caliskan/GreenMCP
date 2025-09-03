import os
import importlib
from typing import Dict, Any
from ..config._loader import load_yaml_with_env

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
TOOLS_YAML = os.path.join(ROOT_DIR, "config", "tools.yaml")

def _import_class(path: str):
    mod_name, cls_name = path.rsplit(".", 1)
    mod = importlib.import_module(mod_name)
    return getattr(mod, cls_name)

def load_tools_from_config() -> tuple[Dict[str, object], dict]:
    cfg = load_yaml_with_env(TOOLS_YAML)
    tools_cfg = (cfg.get("tools") or {})
    allow_cfg = (cfg.get("allow") or {})

    registry: Dict[str, object] = {}
    for name, spec in tools_cfg.items():
        if not spec or not bool(spec.get("enabled", True)):
            continue
        cls_path = spec.get("class")
        params: dict[str, Any] = spec.get("params") or {}
        if not cls_path:
            raise ValueError(f"Tool '{name}' için 'class' alanı zorunlu.")
        cls = _import_class(cls_path)
        try:
            obj = cls(**params)
        except TypeError:
            base_url = params.get("base_url")
            obj = cls(base_url=base_url) if base_url else cls()
        registry[name] = obj

    return registry, {"allow": allow_cfg}
