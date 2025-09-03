import os
import re
import yaml

_ENV_RE = re.compile(r"\$\{([A-Z0-9_]+)\|([^}]+)\}")

def _sub_env(val: str) -> str:
    def repl(m):
        key, default = m.group(1), m.group(2)
        return os.getenv(key, default)
    return _ENV_RE.sub(repl, val)

def _walk_and_sub_env(obj):
    if isinstance(obj, dict):
        return {k: _walk_and_sub_env(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_walk_and_sub_env(v) for v in obj]
    if isinstance(obj, str):
        return _sub_env(obj)
    return obj

def load_yaml_with_env(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return _walk_and_sub_env(data)
