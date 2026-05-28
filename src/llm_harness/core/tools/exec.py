"""Tool: ExecTool — execute shell commands via sandbox."""

from __future__ import annotations

from typing import ClassVar

from pydantic import BaseModel, Field

from llm_harness.adapters.sandbox.backend import SandboxBackend
from llm_harness.core.tools.base import BaseTool, ToolExecutionContext, ToolResult


class ExecInput(BaseModel):
    command: str = Field(description="The shell command to execute")
    working_dir: str | None = Field(default=None, description="Optional working directory")
    timeout: int = Field(default=60, ge=1, le=600, description="Timeout in seconds")


class ExecTool(BaseTool):
    """Execute a shell command via the sandbox backend."""

    name: ClassVar[str] = "exec"
    description: ClassVar[str] = "Execute a shell command and return its output."
    input_model: ClassVar[type[BaseModel]] = ExecInput

    def __init__(self, sandbox: SandboxBackend) -> None:
        self._sandbox = sandbox

    async def execute(self, arguments: ExecInput, context: ToolExecutionContext) -> ToolResult:
        session_key = context.metadata.get("session_key", "")
        cwd = arguments.working_dir or "/workspace"
        result = await self._sandbox.execute(
            session_key,
            arguments.command,
            cwd=cwd,
            timeout=arguments.timeout,
        )

        output_parts = [result.output]
        if result.exit_code != 0:
            output_parts.append(f"\nExit code: {result.exit_code}")

        return ToolResult(
            output="\n".join(output_parts),
            is_error=result.is_error,
        )
