
import os
import yaml


ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
YAML_PATH = os.path.join(ROOT_DIR, "agent_configs.yaml")

if not os.path.isfile(YAML_PATH):
    raise FileNotFoundError(
        f"agent_configs.yaml bulunamadı. Beklenen konum: {YAML_PATH}"
    )

with open(YAML_PATH, "r", encoding="utf-8") as f:
    data = yaml.safe_load(f) or {}

AGENT_CONFIGS = data.get("agents", {})
DISPATCHER_CONFIG = data.get("dispatcher", {})
