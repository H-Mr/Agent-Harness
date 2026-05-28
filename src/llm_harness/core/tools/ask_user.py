"""Tool: AskUserQuestionTool — ask the interactive user a follow-up question.

Uses a callback injected via constructor (not context.metadata magic).
The app layer wires this to the bus/channel layer.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from pydantic import BaseModel, Field

from llm_harness.core.tools.base import BaseTool, ToolExecutionContext, ToolResult

AskUserCallback = Callable[[str], Awaitable[str]]


class AskUserQuestionToolInput(BaseModel):
    """Arguments for asking the user a question."""

    question: str = Field(description="The exact question to ask the user")


class AskUserQuestionTool(BaseTool):
    """Ask the interactive user a question and return the answer.

    The tool needs an ask_user callback to be injected. Without one,
    it reports that interactive questions are unavailable.
    """

    name = "ask_user_question"
    description = "Ask the interactive user a follow-up question and return their answer."
    input_model = AskUserQuestionToolInput

    def __init__(self, ask_user: AskUserCallback | None = None):
        self._ask_user = ask_user

    def set_callback(self, ask_user: AskUserCallback) -> None:
        """Set or replace the ask-user callback at runtime."""
        self._ask_user = ask_user

    def is_read_only(self, arguments: AskUserQuestionToolInput) -> bool:
        del arguments
        return True

    async def execute(
        self,
        arguments: AskUserQuestionToolInput,
        context: ToolExecutionContext,
    ) -> ToolResult:
        if self._ask_user is None:
            return ToolResult(
                output="ask_user_question is unavailable in this session (no user prompt callback configured)",
                is_error=True,
            )
        try:
            answer = str(await self._ask_user(arguments.question)).strip()
        except Exception as exc:
            return ToolResult(output=f"Failed to get user response: {exc}", is_error=True)
        if not answer:
            return ToolResult(output="(no response)")
        return ToolResult(output=answer)
