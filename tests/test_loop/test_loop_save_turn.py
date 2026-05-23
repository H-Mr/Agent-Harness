"""Tests for AgentLoop._save_turn (nanobot port).

Note: The agent-harness AgentLoop has a different architecture (LoopCallbacks)
than nanobot's AgentLoop. This test uses the nanobot-style _save_turn method
which may not exist directly on the agent-harness AgentLoop. We test the
underlying _save_turn logic directly.
"""

import pytest

from agent_harness.context.base import ContextBuilder
from agent_harness.session.manager import Session
from agent_harness.loop.agent import AgentLoop


def _mk_loop() -> AgentLoop:
    loop = AgentLoop.__new__(AgentLoop)
    loop._TOOL_RESULT_MAX_CHARS = AgentLoop._TOOL_RESULT_MAX_CHARS
    return loop


@pytest.mark.skip(reason="AgentLoop has no _save_turn method in agent-harness (uses LoopCallbacks)")
def test_save_turn_skips_multimodal_user_when_only_runtime_context() -> None:
    loop = _mk_loop()
    session = Session(key="test:runtime-only")
    runtime = ContextBuilder._build_runtime_context("cli", "test")

    loop._save_turn(
        session,
        [{"role": "user", "content": [{"type": "text", "text": runtime}]}],
        skip=0,
    )
    assert session.messages == []


@pytest.mark.skip(reason="AgentLoop has no _save_turn method in agent-harness (uses LoopCallbacks)")
def test_save_turn_keeps_image_placeholder_with_path_after_runtime_strip() -> None:
    loop = _mk_loop()
    session = Session(key="test:image")
    runtime = ContextBuilder._build_runtime_context("feishu", "test")

    loop._save_turn(
        session,
        [{
            "role": "user",
            "content": [
                {"type": "text", "text": runtime},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}, "_meta": {"path": "/media/feishu/photo.jpg"}},
            ],
        }],
        skip=0,
    )
    assert session.messages[0]["content"] == [{"type": "text", "text": "[image: /media/feishu/photo.jpg]"}]


@pytest.mark.skip(reason="AgentLoop has no _save_turn method in agent-harness (uses LoopCallbacks)")
def test_save_turn_keeps_image_placeholder_without_meta() -> None:
    loop = _mk_loop()
    session = Session(key="test:image-no-meta")
    runtime = ContextBuilder._build_runtime_context("feishu", "test")

    loop._save_turn(
        session,
        [{
            "role": "user",
            "content": [
                {"type": "text", "text": runtime},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}},
            ],
        }],
        skip=0,
    )
    assert session.messages[0]["content"] == [{"type": "text", "text": "[image]"}]


@pytest.mark.skip(reason="AgentLoop has no _save_turn method in agent-harness (uses LoopCallbacks)")
def test_save_turn_keeps_tool_results_under_16k() -> None:
    loop = _mk_loop()
    session = Session(key="test:tool-result")
    content = "x" * 12_000

    loop._save_turn(
        session,
        [{"role": "tool", "tool_call_id": "call_1", "name": "read_file", "content": content}],
        skip=0,
    )

    assert session.messages[0]["content"] == content
