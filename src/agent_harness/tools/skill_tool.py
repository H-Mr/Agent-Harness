"""Tool for reading loaded skill contents."""

from __future__ import annotations

from pydantic import BaseModel, Field

from agent_harness.tools.base import BaseTool, ToolExecutionContext, ToolResult


class SkillToolInput(BaseModel):
    """Arguments for skill lookup."""

    name: str = Field(description="Skill name to read")


class SkillTool(BaseTool):
    """Return the full content of a loaded skill by name."""

    name = "skill"
    description = "Read a loaded skill's full content by name. Use to get detailed instructions for a specific skill."
    input_model = SkillToolInput

    def __init__(self, skill_registry=None):
        self._registry = skill_registry

    def is_read_only(self, arguments: SkillToolInput) -> bool:
        del arguments
        return True

    async def execute(self, arguments: SkillToolInput, context: ToolExecutionContext) -> ToolResult:
        registry = self._registry or context.metadata.get("skill_registry")
        if registry is None:
            return ToolResult(output="Skill registry not available", is_error=True)
        skill = (
            registry.get(arguments.name)
            or registry.get(arguments.name.lower())
            or registry.get(arguments.name.title())
        )
        if skill is None:
            return ToolResult(output=f"Skill not found: {arguments.name}", is_error=True)
        return ToolResult(output=skill.content)
