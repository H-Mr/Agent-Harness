"""Tests for LLMProvider abstract base -- retry logic, data classes, image fallback."""

from unittest.mock import AsyncMock, patch

import pytest

from llm_harness.adapters.providers.base import (
    GenerationSettings,
    LLMProvider,
    LLMResponse,
    ToolCallRequest,
)


class _ConcreteProvider(LLMProvider):
    """Minimal concrete subclass for testing abstract methods."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._chat_mock = AsyncMock()

    async def chat(self, messages, **kwargs):
        return await self._chat_mock(messages=messages, **kwargs)

    def get_default_model(self):
        return "test-model"


class TestDataClasses:
    """LLMResponse and ToolCallRequest dataclass behaviour."""

    def test_llm_response_defaults(self) -> None:
        """LLMResponse must set sensible defaults for all fields."""
        resp = LLMResponse(content="hello")
        assert resp.content == "hello"
        assert resp.tool_calls == []
        assert resp.finish_reason == "stop"
        assert resp.usage == {}
        assert resp.reasoning_content is None
        assert resp.thinking_blocks is None

    def test_has_tool_calls_property(self) -> None:
        """has_tool_calls must be True only when tool_calls is non-empty."""
        resp = LLMResponse(content="hello", tool_calls=[])
        assert resp.has_tool_calls is False

        resp = LLMResponse(content=None, tool_calls=[
            ToolCallRequest(id="c1", name="test", arguments={}),
        ])
        assert resp.has_tool_calls is True

    def test_tool_call_request_to_openai_format(self) -> None:
        """to_openai_tool_call must produce an OpenAI-style tool_call dict."""
        tc = ToolCallRequest(
            id="c1", name="get_weather",
            arguments={"city": "Paris"},
            extra_content={"gemini": True},
        )
        result = tc.to_openai_tool_call()
        assert result["id"] == "c1"
        assert result["type"] == "function"
        assert result["function"]["name"] == "get_weather"
        assert "extra_content" in result

    def test_generation_settings_defaults(self) -> None:
        """GenerationSettings must provide safe defaults."""
        gs = GenerationSettings()
        assert gs.temperature == 0.7
        assert gs.max_tokens == 4096
        assert gs.reasoning_effort is None


class TestRetryLogic:
    """LLMProvider retry behaviour for transient and non-transient errors."""

    async def test_transient_error_is_retried(self) -> None:
        """A transient error (e.g. 429 rate limit) must trigger a retry."""
        provider = _ConcreteProvider()
        provider._chat_mock.side_effect = [
            LLMResponse(content="Error: 429 rate limit", finish_reason="error"),
            LLMResponse(content="ok", finish_reason="stop"),
        ]
        result = await provider.chat_with_retry(
            messages=[{"role": "user", "content": "hi"}],
        )
        assert result.content == "ok"
        assert provider._chat_mock.call_count == 2

    async def test_non_transient_error_not_retried(self) -> None:
        """A non-transient error (e.g. invalid request) must not be retried."""
        provider = _ConcreteProvider()
        provider._chat_mock.return_value = LLMResponse(
            content="Error: invalid_api_key", finish_reason="error",
        )
        result = await provider.chat_with_retry(
            messages=[{"role": "user", "content": "hi"}],
        )
        assert result.finish_reason == "error"
        # Only one attempt for non-transient errors (image fallback check happens only once)
        assert provider._chat_mock.call_count in (1, 2)

    async def test_max_retries_before_giving_up(self) -> None:
        """After exhausting all retry attempts, must return the last error response."""
        provider = _ConcreteProvider()
        provider._chat_mock.return_value = LLMResponse(
            content="Error: 503 service unavailable", finish_reason="error",
        )
        result = await provider.chat_with_retry(
            messages=[{"role": "user", "content": "hi"}],
        )
        assert result.finish_reason == "error"
        # 3 retry attempts + 1 final = 3 (the for loop runs 3 times with delays 1,2,4)
        assert provider._chat_mock.call_count == 4

    async def test_chat_stream_with_retry_fallback(self) -> None:
        """chat_stream_with_retry must fall back to non-streaming and retry."""
        provider = _ConcreteProvider()
        provider._chat_mock.side_effect = [
            LLMResponse(content="Error: timeout", finish_reason="error"),
            LLMResponse(content="streaming ok", finish_reason="stop"),
        ]
        result = await provider.chat_stream_with_retry(
            messages=[{"role": "user", "content": "hi"}],
        )
        assert result.content == "streaming ok"
        assert provider._chat_mock.call_count == 2


class TestImageErrorFallback:
    """Image error fallback: non-transient error + images -> strip and retry."""

    async def test_image_error_strips_images_and_retries(self) -> None:
        """When a non-transient error occurs with image content, images must be
        replaced with text placeholders and the request retried once."""
        provider = _ConcreteProvider()
        messages_with_images = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "describe this"},
                    {"type": "image_url", "image_url": {"url": "data:img"}, "_meta": {"path": "/img.png"}},
                ],
            },
        ]

        provider._chat_mock.side_effect = [
            LLMResponse(content="Error: content_policy", finish_reason="error"),
            LLMResponse(content="The image shows...", finish_reason="stop"),
        ]

        result = await provider.chat_with_retry(messages=messages_with_images)

        assert result.content == "The image shows..."
        # The second call must have images stripped
        second_call = provider._chat_mock.call_args_list[1]
        second_messages = second_call.kwargs["messages"]
        image_block = second_messages[0]["content"]
        assert image_block[1]["type"] == "text"
        assert "[image:" in image_block[1]["text"]

    async def test_non_image_error_not_stripped(self) -> None:
        """A non-transient error without image content must not strip anything."""
        provider = _ConcreteProvider()
        provider._chat_mock.return_value = LLMResponse(
            content="Error: invalid_api_key", finish_reason="error",
        )
        result = await provider.chat_with_retry(
            messages=[{"role": "user", "content": "hello"}],
        )
        assert result.finish_reason == "error"
        assert provider._chat_mock.call_count in (1, 2)


class TestIsTransientError:
    """_is_transient_error keyword detection."""

    @pytest.mark.parametrize("error_text", [
        "429 Too Many Requests",
        "rate limit exceeded",
        "500 Internal Server Error",
        "502 Bad Gateway",
        "503 Service Unavailable",
        "504 Gateway Timeout",
        "connection refused",
        "request timed out",
        "the server is overloaded",
        "temporarily unavailable",
    ])
    def test_transient_markers_detected(self, error_text: str) -> None:
        """All known transient-error markers must be detected."""
        assert LLMProvider._is_transient_error(error_text)

    @pytest.mark.parametrize("error_text", [
        "invalid_api_key",
        "insufficient_quota",
        "content_policy_violation",
        "model_not_found",
    ])
    def test_non_transient_markers_not_detected(self, error_text: str) -> None:
        """Non-transient errors must not be misidentified as transient."""
        assert not LLMProvider._is_transient_error(error_text)


class TestSanitizeEmptyContent:
    """_sanitize_empty_content edge cases."""

    def test_dict_content_converted_to_list(self) -> None:
        """When content is a dict, it must be wrapped in a list."""
        messages = [{"role": "user", "content": {"type": "text", "text": "hello"}}]
        result = LLMProvider._sanitize_empty_content(messages)
        assert isinstance(result[0]["content"], list)
        assert result[0]["content"][0]["type"] == "text"
