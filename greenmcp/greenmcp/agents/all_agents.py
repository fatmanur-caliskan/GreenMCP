from .load_configs import AGENT_CONFIGS
from .agent_base import Agent

# Agent nesnelerini config'e göre oluştur
AGENTS = {
    name: Agent(**config) for name, config in AGENT_CONFIGS.items()
}
