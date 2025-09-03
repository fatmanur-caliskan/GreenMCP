GreenMCP

GreenMCP is a modular, intelligent assistant system built upon the Model Context Protocol (MCP) architecture. It enables a seamless combination of local (in-code) LLMs, task-specific agents, and external microservices — all accessible through a unified natural language interface.

What is MCP?

Model Context Protocol (MCP) is an architectural pattern for multi-agent systems. It analyzes a user’s natural language input, intelligently determines which component (agent or tool) is responsible, routes the request accordingly, and merges the responses into a coherent final output.

MCP allows for:

Separation of concerns between reasoning, data access, and action

Dynamic routing of user input based on intent and context

Combining model-generated, tool-driven, and rule-based outputs in a single flow


What is GreenMCP?

GreenMCP is a sustainability-focused implementation of the MCP pattern. It is designed to:

Help users make eco-friendly lifestyle decisions

Provide smart insights through in-house LLM agents

Integrate real-time data via external tools


GreenMCP includes:
Dispatcher (dispatcher_agent.py)

Analyzes incoming prompts and selects the appropriate component

Relies on a prompt-based routing guide (prompts/dispatcher.txt)


Agents (agents/)

Modular agents for QA, coaching, narrative analysis, and reporting

Each agent is defined via agent_configs.yaml (name, model, backend, prompt)

Uses agent_base.py for prompt loading and response formatting


In-code LLMs

Configurable models via transformers_backend.py or ollama

Supports quantization and device selection via environment variables and llm_runner.py


Microservice Tools (tools/, services/)

Defined modularly in tools.yaml with tool ID, endpoint, method, parameters

Registered at runtime via load_tools.py and tool_registry.py

Called via tools/client.py using JSON-RPC or HTTP


Configuration Driven Design

agent_configs.yaml: Defines all agents and their models/prompts

tools.yaml: Describes external microservices

prompts/*.txt: All prompt templates are externalized and editable

mcp.yaml: (optional) Project-level metadata for orchestrating deployments


How It Works

User sends a natural language input.

Dispatcher decides whether an agent or tool should handle it.

The selected component executes the task (e.g., calls LLM, queries an API).

The system merges and formats the output into a complete, human-readable response.

GreenMCP blends reasoning (agents), real-world data (tools), and natural language (LLMs) into a unified, intelligent assistant system — privacy-friendly, explainable, and extensible by design.
