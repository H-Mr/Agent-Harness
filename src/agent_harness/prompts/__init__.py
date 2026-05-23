"""System prompt assembly, environment detection, and AGENTS.md discovery."""

from agent_harness.prompts.agentsmd import discover_agents_md_files, load_agents_md_prompt
from agent_harness.prompts.environment import EnvironmentInfo, get_environment_info

__all__ = [
    "EnvironmentInfo",
    "get_environment_info",
    "discover_agents_md_files",
    "load_agents_md_prompt",
]
