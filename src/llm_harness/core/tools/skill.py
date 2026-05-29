"""Tool: SkillTool — on-demand skill content loading (progressive disclosure)."""

from __future__ import annotations

from typing import ClassVar

from pydantic import BaseModel, Field

from llm_harness.core.tools.base import BaseTool, ToolExecutionContext, ToolResult


class SkillInput(BaseModel):
    name: str = Field(description="Name of the skill to load")


class SkillTool(BaseTool):
    """Look up a skill's full content by name.

    Skills are registered in the system prompt as a list of names + short
    descriptions.  The LLM invokes this tool to get the complete markdown
    body only when needed — avoiding context-window bloat.
    """

    name: ClassVar[str] = "skill"
    description: ClassVar[str] = (
        "Load a skill's full instructions. Call this when a task matches "
        "a skill's description."
    )
    input_model: ClassVar[type[BaseModel]] = SkillInput

    def __init__(self, registry) -> None:
        from llm_harness.extensions.skills.registry import SkillRegistry
        self._registry: SkillRegistry = registry

    async def execute(self, arguments: SkillInput, context: ToolExecutionContext) -> ToolResult:
        skill = self._registry.get(arguments.name)
        if skill is None:
            available = [s.name for s in self._registry.list_skills()]
            return ToolResult(
                output=f"Unknown skill '{arguments.name}'. Available: {', '.join(available)}",
                is_error=True,
            )
        return ToolResult(output=skill.content)

    @staticmethod
    def is_read_only(arguments: SkillInput) -> bool:
        del arguments
        return True
