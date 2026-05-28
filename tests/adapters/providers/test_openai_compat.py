"""Tests for OpenAICompatProvider -- the unified OpenAI-compatible LLM adapter."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from llm_harness.adapters.providers.base import ToolCallRequest
from llm_harness.adapters.providers.openai_compat_provider import (
    OpenAICompatProvider,
    _short_tool_id,
)


@pytest.fixture
def provider() -> OpenAICompatProvider:
    """Create an OpenAICompatProvider with a mocked HTTP client."""
    with patch("llm_harness.adapters.providers.openai_compat_provider.AsyncOpenAI"):
        prov = OpenAICompatProvider(api_key="sk-test", default_model="gpt-4o")
        prov._client.chat.completions.create = AsyncMock()
        return prov


class TestOpenAICompatProvider:
    """OpenAICompatProvider: kwargs building, message sanitisation, response parsing."""

    # ------------------------------------------------------------------
    # _build_kwargs
    # ------------------------------------------------------------------

    def test_build_kwargs_includes_model_messages_tools(self, provider) -> None:
        """_build_kwargs must include model, messages, and optionally tools."""
        messages = [{"role": "user", "content": "hi"}]
        tools = [{"type": "function", "function": {"name": "test"}}]
        kwargs = provider._build_kwargs(
            messages=messages, tools=tools, model="gpt-4o",
            max_tokens=100, temperature=0.5, reasoning_effort=None,
            tool_choice="auto",
        )
        assert kwargs["model"] == "gpt-4o"
        assert len(kwargs["messages"]) == 1
        assert kwargs["messages"][0]["content"] == "hi"
        assert "tools" in kwargs
        assert kwargs["max_completion_tokens"] == 100
        assert kwargs["temperature"] == 0.5

    def test_build_kwargs_handles_max_tokens_zero(self, provider) -> None:
        """max_tokens of 0 must be clamped to 1."""
        kwargs = provider._build_kwargs(
            messages=[{"role": "user", "content": "hi"}], tools=None,
            model="gpt-4o", max_tokens=0, temperature=0.7,
            reasoning_effort=None, tool_choice=None,
        )
        assert kwargs["max_completion_tokens"] == 1

    def test_build_kwargs_injects_reasoning_effort(self, provider) -> None:
        """When reasoning_effort is provided it must appear in kwargs."""
        kwargs = provider._build_kwargs(
            messages=[{"role": "user", "content": "think"}], tools=None,
            model="gpt-4o", max_tokens=100, temperature=0.7,
            reasoning_effort="high", tool_choice=None,
        )
        assert kwargs["reasoning_effort"] == "high"

    # ------------------------------------------------------------------
    # _sanitize_empty_content (inherited from LLMProvider)
    # ------------------------------------------------------------------

    def test_sanitize_empty_content_replaces_empty_string(self) -> None:
        """Empty string content must be replaced with '(empty)' placeholder."""
        messages = [{"role": "user", "content": ""}]
        result = OpenAICompatProvider._sanitize_empty_content(messages)
        assert result[0]["content"] == "(empty)"

    def test_sanitize_empty_content_assistant_with_tool_calls(self) -> None:
        """Assistant messages with tool_calls and empty content must have None content."""
        messages = [{"role": "assistant", "content": "", "tool_calls": [{"id": "c1"}]}]
        result = OpenAICompatProvider._sanitize_empty_content(messages)
        assert result[0]["content"] is None

    # ------------------------------------------------------------------
    # api_format property
    # ------------------------------------------------------------------

    def test_api_format_returns_openai(self, provider) -> None:
        """api_format must return 'openai' for OpenAI-compatible providers."""
        assert provider.api_format == "openai"

    # ------------------------------------------------------------------
    # Response parsing -- tool calls
    # ------------------------------------------------------------------

    def test_parse_tool_calls_from_dict_response(self, provider) -> None:
        """_parse must extract tool calls from a dict-formatted API response."""
        response = {
            "choices": [{
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [{
                        "id": "call_abc123",
                        "type": "function",
                        "function": {"name": "get_weather", "arguments": '{"city": "Paris"}'},
                    }],
                },
                "finish_reason": "tool_calls",
            }],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        }
        result = provider._parse(response)
        assert result.finish_reason == "tool_calls"
        assert result.has_tool_calls
        assert result.tool_calls[0].name == "get_weather"
        assert result.tool_calls[0].arguments == {"city": "Paris"}

    # ------------------------------------------------------------------
    # Streaming chunk reassembly
    # ------------------------------------------------------------------

    def test_parse_chunks_reassembles_text(self) -> None:
        """_parse_chunks must concatenate text deltas from streaming chunks."""
        chunks = [
            {"choices": [{"delta": {"content": "Hello "}, "index": 0}]},
            {"choices": [{"delta": {"content": "world"}, "index": 0}]},
            {"choices": [{"delta": {}, "finish_reason": "stop"}, {"index": 0}]},
        ]
        result = OpenAICompatProvider._parse_chunks(chunks)
        assert result.content == "Hello world"
        assert result.finish_reason == "stop"

    def test_parse_chunks_reassembles_tool_calls(self) -> None:
        """_parse_chunks must merge tool-call deltas across chunks."""
        chunks = [
            {
                "choices": [{
                    "index": 0,
                    "delta": {
                        "tool_calls": [{
                            "index": 0, "id": "call_1",
                            "function": {"name": "get_weather", "arguments": ""},
                        }],
                    },
                }],
            },
            {
                "choices": [{
                    "index": 0,
                    "delta": {
                        "tool_calls": [{
                            "index": 0, "id": None,
                            "function": {"name": None, "arguments": '{"city":"'},
                        }],
                    },
                }],
            },
            {
                "choices": [{
                    "index": 0,
                    "delta": {
                        "tool_calls": [{
                            "index": 0, "id": None,
                            "function": {"name": None, "arguments": 'Paris"}'},
                        }],
                    },
                }],
            },
        ]
        result = OpenAICompatProvider._parse_chunks(chunks)
        assert result.has_tool_calls
        tc = result.tool_calls[0]
        assert tc.name == "get_weather"
        assert tc.arguments == {"city": "Paris"}

    # ------------------------------------------------------------------
    # Default model
    # ------------------------------------------------------------------

    def test_get_default_model(self, provider) -> None:
        """get_default_model must return the default_model passed at init."""
        assert provider.get_default_model() == "gpt-4o"
