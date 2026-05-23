"""
LLM Provider abstract base class -- defines the unified interface for all LLM adapters.

Core design uses the Template Method pattern:
  - chat() / chat_stream() are abstract methods implemented by subclasses
  - chat_with_retry() / chat_stream_with_retry() are template methods with retry logic built in

Call chain:
  AgentLoop._run_agent_loop()
    -> provider.chat_with_retry(messages, tools)
      -> provider.chat(messages, tools)          <- subclass implementation
        -> API call (OpenAI / Anthropic / ...)
      -> transient error -> backoff retry (up to 3 attempts)

Retry strategy:
  Backoff delays: 1s -> 2s -> 4s
  Retry condition: error message contains transient keywords (429, rate limit, 500-504, timeout, etc.)
  Image error fallback: non-transient error + image content -> strip images and retry once
"""

import asyncio
import json
import logging
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# ============================================================================
# Data classes
# ============================================================================


@dataclass
class ToolCallRequest:
    """Tool call request returned by the LLM.

    When the LLM decides to call a tool (e.g. web_search, read_file),
    it includes one or more ToolCallRequest entries in the response.
    """

    id: str                                    # unique tool call ID
    name: str                                  # tool name
    arguments: dict[str, Any]                  # tool arguments
    extra_content: dict[str, Any] | None = None           # provider-specific extras (e.g. Gemini)
    provider_specific_fields: dict[str, Any] | None = None # non-standard tool_call-level fields
    function_provider_specific_fields: dict[str, Any] | None = None  # non-standard function-level fields

    def to_openai_tool_call(self) -> dict[str, Any]:
        """Serialize to an OpenAI-style tool_call message block for message history.

        The LLM's tool_call response must be written back into context as an assistant
        message so that subsequent LLM calls understand which tools were invoked.
        """
        tool_call = {
            "id": self.id,
            "type": "function",
            "function": {
                "name": self.name,
                "arguments": json.dumps(self.arguments, ensure_ascii=False),
            },
        }
        if self.extra_content:
            tool_call["extra_content"] = self.extra_content
        if self.provider_specific_fields:
            tool_call["provider_specific_fields"] = self.provider_specific_fields
        if self.function_provider_specific_fields:
            tool_call["function"]["provider_specific_fields"] = self.function_provider_specific_fields
        return tool_call


@dataclass
class LLMResponse:
    """Unified return format for all LLM calls.

    Regardless of whether the underlying API is OpenAI or Anthropic,
    everything is normalised into this structure.
    """

    content: str | None                                      # text reply (when LLM speaks, not tool-calls)
    tool_calls: list[ToolCallRequest] = field(default_factory=list)  # tool call list
    finish_reason: str = "stop"                              # stop / tool_calls / error
    usage: dict[str, int] = field(default_factory=dict)     # token usage stats
    reasoning_content: str | None = None                     # reasoning (Kimi / DeepSeek-R1 etc.)
    thinking_blocks: list[dict] | None = None                # Anthropic extended thinking

    @property
    def has_tool_calls(self) -> bool:
        """Whether the response contains tool calls -- used by the agent loop."""
        return len(self.tool_calls) > 0


@dataclass(frozen=True)
class GenerationSettings:
    """Global default generation parameters stored on the provider.

    Uses _SENTINEL sentinel-value mechanism: when the caller does not pass
    a parameter the provider default is used; explicit arguments override.
    """

    temperature: float = 0.7
    max_tokens: int = 4096
    reasoning_effort: str | None = None


# ============================================================================
# Abstract Provider
# ============================================================================

class LLMProvider(ABC):
    """
    LLM Provider abstract base class.

    Subclasses must implement:
      chat()           -> non-streaming call
      chat_stream()    -> streaming call (optional, defaults to non-streaming)
      get_default_model() -> return the default model name

    Built-in retry logic:
      chat_with_retry()        -> calls chat(), auto-retries on transient errors
      chat_stream_with_retry() -> calls chat_stream(), auto-retries on transient errors
    """

    # Retry parameters: up to 3 attempts, backoff delays 1s / 2s / 4s
    _CHAT_RETRY_DELAYS = (1, 2, 4)

    # Transient-error keywords (if matched the call is retried)
    _TRANSIENT_ERROR_MARKERS = (
        "429",
        "rate limit",
        "500",
        "502",
        "503",
        "504",
        "overloaded",
        "timeout",
        "timed out",
        "connection",
        "server error",
        "temporarily unavailable",
    )

    # Sentinel -- distinguishes "caller did not pass" from "caller passed None".
    # When absent, self.generation default is used.
    _SENTINEL = object()

    def __init__(self, api_key: str | None = None, api_base: str | None = None):
        self.api_key = api_key
        self.api_base = api_base
        self.generation: GenerationSettings = GenerationSettings()

    # ------------------------------------------------------------------
    # Message content normalisation (utility methods)
    # ------------------------------------------------------------------

    @staticmethod
    def _sanitize_empty_content(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Clean empty content in messages:
        - empty string -> replaced with "(empty)" or None (when assistant has tool_calls)
        - empty content block -> removed
        - dict-type content -> converted to list
        """
        result: list[dict[str, Any]] = []
        for msg in messages:
            content = msg.get("content")

            if isinstance(content, str) and not content:
                clean = dict(msg)
                clean["content"] = None if (msg.get("role") == "assistant" and msg.get("tool_calls")) else "(empty)"
                result.append(clean)
                continue

            if isinstance(content, list):
                new_items: list[Any] = []
                changed = False
                for item in content:
                    if (
                        isinstance(item, dict)
                        and item.get("type") in ("text", "input_text", "output_text")
                        and not item.get("text")
                    ):
                        changed = True
                        continue
                    if isinstance(item, dict) and "_meta" in item:
                        new_items.append({k: v for k, v in item.items() if k != "_meta"})
                        changed = True
                    else:
                        new_items.append(item)
                if changed:
                    clean = dict(msg)
                    if new_items:
                        clean["content"] = new_items
                    elif msg.get("role") == "assistant" and msg.get("tool_calls"):
                        clean["content"] = None
                    else:
                        clean["content"] = "(empty)"
                    result.append(clean)
                    continue

            if isinstance(content, dict):
                clean = dict(msg)
                clean["content"] = [content]
                result.append(clean)
                continue

            result.append(msg)
        return result

    @staticmethod
    def _sanitize_request_messages(
        messages: list[dict[str, Any]],
        allowed_keys: frozenset[str],
    ) -> list[dict[str, Any]]:
        """Filter message fields by an allow-list, dropping keys the provider does not recognise."""
        sanitized = []
        for msg in messages:
            clean = {k: v for k, v in msg.items() if k in allowed_keys}
            if clean.get("role") == "assistant" and "content" not in clean:
                clean["content"] = None
            sanitized.append(clean)
        return sanitized

    # ------------------------------------------------------------------
    # Abstract methods -- subclasses must implement
    # ------------------------------------------------------------------

    @abstractmethod
    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        reasoning_effort: str | None = None,
        tool_choice: str | dict[str, Any] | None = None,
    ) -> LLMResponse:
        """
        Send a chat completion request (non-streaming).

        Unified parameters:
          messages: list of messages, each with role and content
          tools: optional tool definitions (OpenAI function schema format)
          model: provider-specific model identifier
          max_tokens / temperature / reasoning_effort: generation parameters
          tool_choice: tool selection strategy ("auto" / "required" / specific tool)

        Returns:
          LLMResponse: unified response structure (text content and/or tool calls)
        """
        pass

    @classmethod
    def _is_transient_error(cls, content: str | None) -> bool:
        """Check whether the error content indicates a transient (retriable) error."""
        err = (content or "").lower()
        return any(marker in err for marker in cls._TRANSIENT_ERROR_MARKERS)

    @staticmethod
    def _strip_image_content(messages: list[dict[str, Any]]) -> list[dict[str, Any]] | None:
        """Replace image content in messages with text placeholders. Returns None if no images found."""
        found = False
        result = []
        for msg in messages:
            content = msg.get("content")
            if isinstance(content, list):
                new_content = []
                for b in content:
                    if isinstance(b, dict) and b.get("type") == "image_url":
                        path = (b.get("_meta") or {}).get("path", "")
                        placeholder = f"[image: {path}]" if path else "[image omitted]"
                        new_content.append({"type": "text", "text": placeholder})
                        found = True
                    else:
                        new_content.append(b)
                result.append({**msg, "content": new_content})
            else:
                result.append(msg)
        return result if found else None

    async def _safe_chat(self, **kwargs: Any) -> LLMResponse:
        """Safely call chat(), converting unexpected exceptions into an error response."""
        try:
            return await self.chat(**kwargs)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            return LLMResponse(content=f"Error calling LLM: {exc}", finish_reason="error")

    # ------------------------------------------------------------------
    # Streaming -- default implementation falls back to non-streaming
    # ------------------------------------------------------------------

    async def chat_stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        reasoning_effort: str | None = None,
        tool_choice: str | dict[str, Any] | None = None,
        on_content_delta: Callable[[str], Awaitable[None]] | None = None,
    ) -> LLMResponse:
        """
        Streaming chat completion -- calls on_content_delta on each text chunk.

        Default implementation falls back to non-streaming (returns the full
        content as a single delta). Providers with native streaming support
        (e.g. OpenAICompatProvider) should override this method.
        """
        response = await self.chat(
            messages=messages, tools=tools, model=model,
            max_tokens=max_tokens, temperature=temperature,
            reasoning_effort=reasoning_effort, tool_choice=tool_choice,
        )
        if on_content_delta and response.content:
            await on_content_delta(response.content)
        return response

    async def _safe_chat_stream(self, **kwargs: Any) -> LLMResponse:
        """Safely call chat_stream(), converting exceptions into an error response."""
        try:
            return await self.chat_stream(**kwargs)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            return LLMResponse(content=f"Error calling LLM: {exc}", finish_reason="error")

    # ------------------------------------------------------------------
    # Retry-enabled calls -- template methods (core)
    # ------------------------------------------------------------------

    async def chat_stream_with_retry(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: object = _SENTINEL,
        temperature: object = _SENTINEL,
        reasoning_effort: object = _SENTINEL,
        tool_choice: str | dict[str, Any] | None = None,
        on_content_delta: Callable[[str], Awaitable[None]] | None = None,
    ) -> LLMResponse:
        """
        [Template method] Streaming call to chat_stream() with automatic retry on transient errors.

        Retry strategy:
          1. Attempt chat_stream()
          2. If finish_reason == "error":
             a. Check if transient error (matches _TRANSIENT_ERROR_MARKERS)
             b. Yes -> wait and retry (backoff: 1s, 2s, 4s)
             c. No -> check for images -> strip and retry once -> still fail -> return error
          3. Max retries: len(_CHAT_RETRY_DELAYS) times
        """
        # Sentinel handling: if the caller didn't pass a parameter, use the provider default
        if max_tokens is self._SENTINEL:
            max_tokens = self.generation.max_tokens
        if temperature is self._SENTINEL:
            temperature = self.generation.temperature
        if reasoning_effort is self._SENTINEL:
            reasoning_effort = self.generation.reasoning_effort

        kw: dict[str, Any] = dict(
            messages=messages, tools=tools, model=model,
            max_tokens=max_tokens, temperature=temperature,
            reasoning_effort=reasoning_effort, tool_choice=tool_choice,
            on_content_delta=on_content_delta,
        )

        for attempt, delay in enumerate(self._CHAT_RETRY_DELAYS, start=1):
            response = await self._safe_chat_stream(**kw)

            if response.finish_reason != "error":
                return response

            if not self._is_transient_error(response.content):
                stripped = self._strip_image_content(messages)
                if stripped is not None:
                    logger.warning("Non-transient LLM error with image content, retrying without images")
                    return await self._safe_chat_stream(**{**kw, "messages": stripped})
                return response

            logger.warning(
                "LLM transient error (attempt %s/%s), retrying in %ss: %s",
                attempt, len(self._CHAT_RETRY_DELAYS), delay,
                (response.content or "")[:120].lower(),
            )
            await asyncio.sleep(delay)

        # All retries exhausted, one final attempt
        return await self._safe_chat_stream(**kw)

    async def chat_with_retry(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: object = _SENTINEL,
        temperature: object = _SENTINEL,
        reasoning_effort: object = _SENTINEL,
        tool_choice: str | dict[str, Any] | None = None,
    ) -> LLMResponse:
        """
        [Template method] Non-streaming call to chat() with automatic retry on transient errors.

        Same logic as chat_stream_with_retry, but calls chat() instead of chat_stream().
        """
        if max_tokens is self._SENTINEL:
            max_tokens = self.generation.max_tokens
        if temperature is self._SENTINEL:
            temperature = self.generation.temperature
        if reasoning_effort is self._SENTINEL:
            reasoning_effort = self.generation.reasoning_effort

        kw: dict[str, Any] = dict(
            messages=messages, tools=tools, model=model,
            max_tokens=max_tokens, temperature=temperature,
            reasoning_effort=reasoning_effort, tool_choice=tool_choice,
        )

        for attempt, delay in enumerate(self._CHAT_RETRY_DELAYS, start=1):
            response = await self._safe_chat(**kw)

            if response.finish_reason != "error":
                return response

            if not self._is_transient_error(response.content):
                stripped = self._strip_image_content(messages)
                if stripped is not None:
                    logger.warning("Non-transient LLM error with image content, retrying without images")
                    return await self._safe_chat(**{**kw, "messages": stripped})
                return response

            logger.warning(
                "LLM transient error (attempt %s/%s), retrying in %ss: %s",
                attempt, len(self._CHAT_RETRY_DELAYS), delay,
                (response.content or "")[:120].lower(),
            )
            await asyncio.sleep(delay)

        return await self._safe_chat(**kw)

    @abstractmethod
    def get_default_model(self) -> str:
        """Return the default model identifier for this provider."""
        pass
