"""Tool: EditFileTool — edit file contents via sandbox.

Placeholder implementation that reads the file, applies a replacement,
then writes it back through the sandbox backend.
"""

from __future__ import annotations

from typing import ClassVar

from pydantic import BaseModel, Field

from llm_harness.adapters.sandbox.backend import SandboxBackend
from llm_harness.core.tools.base import BaseTool, ToolExecutionContext, ToolResult


class EditFileInput(BaseModel):
    path: str = Field(description="The file path to edit")
    old_text: str = Field(description="The text to find and replace")
    new_text: str = Field(description="The text to replace with")
    replace_all: bool = Field(default=False, description="Replace all occurrences")


class EditFileTool(BaseTool):
    """Edit a file by replacing text.

    Placeholder: reads the whole file, performs replacement, writes back.
    Future versions will use a sandbox-native edit operation.
    """

    name: ClassVar[str] = "edit_file"
    description: ClassVar[str] = (
        "Edit a file by replacing old_text with new_text. "
        "Set replace_all=true to replace every occurrence."
    )
    input_model: ClassVar[type[BaseModel]] = EditFileInput

    def __init__(self, sandbox: SandboxBackend) -> None:
        self._sandbox = sandbox

    async def execute(self, arguments: EditFileInput, context: ToolExecutionContext) -> ToolResult:
        session_key = context.metadata.get("session_key", "")

        # Read current content
        try:
            content = await self._sandbox.read_file(session_key, arguments.path)
        except Exception as exc:
            return ToolResult(output=f"Error reading file: {exc}", is_error=True)

        # Count occurrences
        count = content.count(arguments.old_text)
        if count == 0:
            return ToolResult(
                output=f"Error: old_text not found in {arguments.path}",
                is_error=True,
            )
        if count > 1 and not arguments.replace_all:
            return ToolResult(
                output=(
                    f"Warning: old_text appears {count} times. "
                    "Provide more context to make it unique, or set replace_all=true."
                ),
                is_error=True,
            )

        # Apply replacement
        new_content = content.replace(arguments.old_text, arguments.new_text, 1 if not arguments.replace_all else count)

        # Write back
        try:
            await self._sandbox.write_file(session_key, arguments.path, new_content)
        except Exception as exc:
            return ToolResult(output=f"Error writing file: {exc}", is_error=True)

        return ToolResult(output=f"Successfully edited {arguments.path}")
