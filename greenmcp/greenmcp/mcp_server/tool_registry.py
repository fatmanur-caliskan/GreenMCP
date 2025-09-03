
from typing import Dict
from greenmcp.agents.all_agents import AGENTS
from .load_tools import load_tools_from_config  


_ALLOW_MAP: dict[str, list[str]] = {}

def get_allow_map() -> dict[str, list[str]]:
    """İzin haritasını (agent -> [tool, ...]) döndürür."""
    return _ALLOW_MAP

def build_tool_registry() -> Dict[str, object]:
  
    # 1) Ajanları ekle
    registry: Dict[str, object] = dict(AGENTS)

    # 2) Tool'ları config'ten yükle
    tools, meta = load_tools_from_config()
    registry.update(tools)

    # 3) allow-list bilgisini sakla
    global _ALLOW_MAP
    _ALLOW_MAP = meta.get("allow", {})

    return registry
