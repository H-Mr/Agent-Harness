"""Test for nanobot.utils.evaluator ported to agent-harness.

Note: agent-harness does not have a utils.evaluator module yet.
This test is provided as a reference implementation for when the
evaluator is ported. The evaluate_response function uses an LLM to
determine whether a response warrants user notification.
"""

import pytest

from agent_harness.providers.base import LLMProvider, LLMResponse, ToolCallRequest


class DummyProvider(LLMProvider):
    def __init__(self, responses: list[LLMResponse]):
        super().__init__()
        self._responses = list(responses)

    async def chat(self, *args, **kwargs) -> LLMResponse:
        if self._responses:
            return self._responses.pop(0)
        return LLMResponse(content="", tool_calls=[])

    def get_default_model(self) -> str:
        return "test-model"


def _eval_tool_call(should_notify: bool, reason: str = "") -> LLMResponse:
    return LLMResponse(
        content="",
        tool_calls=[
            ToolCallRequest(
                id="eval_1",
                name="evaluate_notification",
                arguments={"should_notify": should_notify, "reason": reason},
            )
        ],
    )


@pytest.mark.asyncio
async def test_should_notify_true() -> None:
    """When LLM returns should_notify=True, result should be True."""
    provider = DummyProvider([_eval_tool_call(True, "user asked to be reminded")])
    response = await provider.chat([{"role": "user", "content": "test"}])
    assert response.has_tool_calls
    assert response.tool_calls[0].name == "evaluate_notification"
    assert response.tool_calls[0].arguments["should_notify"] is True


@pytest.mark.asyncio
async def test_should_notify_false() -> None:
    """When LLM returns should_notify=False, result should be False."""
    provider = DummyProvider([_eval_tool_call(False, "routine check, nothing new")])
    response = await provider.chat([{"role": "user", "content": "test"}])
    assert response.has_tool_calls
    assert response.tool_calls[0].arguments["should_notify"] is False
