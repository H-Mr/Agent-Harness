"""Concrete SectionProvider implementations that plug into the ContextBuilder."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_harness.context.base import SectionProvider
from agent_harness.prompts.agentsmd import load_agents_md_prompt
from agent_harness.prompts.environment import get_environment_info


class EnvironmentSection(SectionProvider):
    """System prompt section describing the runtime environment."""

    section_name = "environment"
    priority = 5

    def __init__(self, cwd: str | Path | None = None) -> None:
        self.cwd = cwd

    async def get_section(self) -> str:
        info = get_environment_info(cwd=str(self.cwd) if self.cwd else None)
        lines = [
            "# Environment",
            f"- OS: {info.os_name} {info.os_version}",
            f"- Platform: {info.platform_machine}",
            f"- Shell: {info.shell}",
            f"- Working Directory: {info.cwd}",
            f"- Date: {info.date}",
            f"- Python: {info.python_version}",
        ]
        if info.hostname:
            lines.append(f"- Hostname: {info.hostname}")
        if info.git_branch:
            lines.append(f"- Git Branch: {info.git_branch}")
        for key, value in info.extra.items():
            lines.append(f"- {key}: {value}")
        return "\n".join(lines)


class AgentsMDSection(SectionProvider):
    """System prompt section embedding project AGENTS.md instructions."""

    section_name = "project_instructions"
    priority = 20

    def __init__(self, cwd: str | Path) -> None:
        self.cwd = cwd

    async def get_section(self) -> str:
        prompt = load_agents_md_prompt(self.cwd)
        return prompt or ""


class MemorySection(SectionProvider):
    """System prompt section for relevant memory context."""

    section_name = "memory"
    priority = 40

    def __init__(self, memory_store: Any) -> None:
        self.memory_store = memory_store

    async def get_section(self) -> str:
        if self.memory_store is None:
            return ""
        try:
            if hasattr(self.memory_store, "get_prompt_section"):
                result = self.memory_store.get_prompt_section()
                if isinstance(result, str):
                    return result
            memories = str(self.memory_store)
            if memories and memories.strip() not in ("{}", "[]", ""):
                return f"# Memory\n\n{memories}"
        except Exception:
            pass
        return ""


class SkillsSection(SectionProvider):
    """System prompt section listing available skills."""

    section_name = "skills"
    priority = 30

    def __init__(self, skill_registry: Any) -> None:
        self.skill_registry = skill_registry

    async def get_section(self) -> str:
        if self.skill_registry is None:
            return ""
        try:
            if hasattr(self.skill_registry, "list_skills"):
                skills = self.skill_registry.list_skills()
            elif hasattr(self.skill_registry, "get_all"):
                skills = self.skill_registry.get_all()
            else:
                skills = []
            if not skills:
                return ""
            lines = [
                "# Available Skills",
                "",
                "The following skills are available via the `skill` tool. "
                "When a user's request matches a skill, invoke it with `skill(name=\"<skill_name>\")` "
                "to load detailed instructions before proceeding.",
                "",
            ]
            for skill in skills:
                name = getattr(skill, "name", str(skill))
                description = getattr(skill, "description", "")
                lines.append(f"- **{name}**: {description}")
            return "\n".join(lines)
        except Exception:
            return ""


class IdentitySection(SectionProvider):
    """System prompt section defining the agent's identity."""

    section_name = "identity"
    priority = 10

    def __init__(self, identity_text: str = "") -> None:
        self.identity_text = identity_text

    async def get_section(self) -> str:
        if not self.identity_text:
            return ""
        return self.identity_text.strip()
