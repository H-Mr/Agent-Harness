# Providers -- LLM Provider Abstraction

## Overview

The provider abstraction is a unified interface for all LLM backends. Whether
you're calling Anthropic Claude, OpenAI GPT, DeepSeek, Gemini, or any of the
25 supported providers, the API is identical.

```python
from agent_harness.providers.base import LLMProvider, LLMResponse

# Any provider implements the same interface
response: LLMResponse = await provider.chat(messages, tools)
```

## LLMProvider ABC

```python
class LLMProvider(ABC):
    async def chat(self, messages, tools=None, model=None,
                   max_tokens=4096, temperature=0.7, ...) -> LLMResponse: ...

    async def chat_stream(self, messages, tools=None, ...,
                          on_content_delta=None) -> LLMResponse: ...

    def get_default_model(self) -> str: ...
```

### Core Methods

| Method | Description |
|--------|-------------|
| `chat()` | Non-streaming completion. Returns structured `LLMResponse`. |
| `chat_stream()` | Streaming completion. Calls `on_content_delta` for each text chunk. Default falls back to non-streaming. |
| `get_default_model()` | Returns the default model identifier for this provider. |

### Unified Return Type: LLMResponse

```python
@dataclass
class LLMResponse:
    content: str | None                         # Text reply (when LLM speaks, not tool-calls)
    tool_calls: list[ToolCallRequest]            # Tool calls requested by the LLM
    finish_reason: str                           # "stop" | "tool_calls" | "error"
    usage: dict[str, int]                        # Token usage stats
    reasoning_content: str | None                # Reasoning text (Kimi, DeepSeek-R1, etc.)
    thinking_blocks: list[dict] | None           # Anthropic extended thinking blocks

    @property
    def has_tool_calls(self) -> bool: ...
```

### ToolCallRequest

```python
@dataclass
class ToolCallRequest:
    id: str                                      # Unique tool call ID
    name: str                                    # Tool name
    arguments: dict[str, Any]                    # Tool arguments
    extra_content: dict | None                   # Provider-specific extras (e.g., Gemini)
    provider_specific_fields: dict | None         # Non-standard tool_call-level fields
    function_provider_specific_fields: dict | None # Non-standard function-level fields
```

## Template Method Pattern

The provider uses the **Template Method** pattern: `chat()` and `chat_stream()`
are abstract methods implemented by subclasses, while `chat_with_retry()` and
`chat_stream_with_retry()` are template methods with built-in retry logic.

```
AgentLoop._run_agent_loop()
  └─ provider.chat_with_retry(messages, tools)
       └─ for attempt in 1..3:
            └─ provider.chat(messages, tools)    # Subclass implementation
                 └─ API call (Anthropic / OpenAI / ...)
            └─ transient error? → backoff(1s) → retry
            └─ image error? → strip images → retry once
```

## Retry Strategy

The retry logic is built into `chat_with_retry()` and `chat_stream_with_retry()`:

### Transient Error Detection

Errors are considered transient if the message contains any of:
`429`, `rate limit`, `500`, `502`, `503`, `504`, `overloaded`, `timeout`,
`timed out`, `connection`, `server error`, `temporarily unavailable`

### Backoff Schedule

| Attempt | Delay Before Retry |
|---------|-------------------|
| 1 | 1 second |
| 2 | 2 seconds |
| 3 | 4 seconds |

### Image-Strip Fallback

If a non-transient error occurs and the request contains image content, the
provider automatically strips images (replaces them with `[image: path]`
placeholders) and retries once. This handles providers that don't support
vision or have intermittent vision errors.

```python
def _strip_image_content(messages):
    # Replaces image_url content blocks with text placeholders
    # Returns None if no images found (no retry needed)
```

### Sentinel Default Parameter Pattern

The `chat_with_retry()` methods use a sentinel value to distinguish "caller
did not pass this parameter" from "caller explicitly passed None":

```python
_SENTINEL = object()

async def chat_with_retry(self, ..., max_tokens=_SENTINEL, temperature=_SENTINEL):
    if max_tokens is self._SENTINEL:
        max_tokens = self.generation.max_tokens
    if temperature is self._SENTINEL:
        temperature = self.generation.temperature
```

This allows provider-level defaults (set in `GenerationSettings`) to apply when
the caller doesn't specify a value, while explicit values always win.

### Safe Error Wrapping

Both `chat()` and `chat_stream()` have `_safe_*` wrappers that convert any
exception into a `LLMResponse` with `finish_reason="error"`, ensuring the
retry logic never sees raw exceptions.

```python
async def _safe_chat(self, **kwargs) -> LLMResponse:
    try:
        return await self.chat(**kwargs)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        return LLMResponse(content=f"Error calling LLM: {exc}", finish_reason="error")
```

## Message Normalization

The base provider includes static methods for normalizing messages before sending
to the LLM API:

- **`_sanitize_empty_content()`** -- Replaces empty string content with `"(empty)"`
  (or `None` for assistant messages with tool_calls), removes empty content blocks,
  and converts dict-type content to list format.
- **`_sanitize_request_messages()`** -- Filters message fields by an allow-list to
  drop keys the provider doesn't recognise.

## 25 Backend Providers

The provider registry contains specs for 25 providers, all listed below.

### Gateways (OpenAI-Compatible)

| Provider | Detection | Default API Base | Notes |
|----------|-----------|-----------------|-------|
| OpenRouter | Key prefix `sk-or-` | `https://openrouter.ai/api/v1` | Supports prompt caching |
| AiHubMix | Base keyword `aihubmix` | `https://aihubmix.com/v1` | Strips model prefix |
| SiliconFlow | Base keyword `siliconflow` | `https://api.siliconflow.cn/v1` | |
| VolcEngine | Base keyword `volces` | `https://ark.cn-beijing.volces.com/api/v3` | |
| VolcEngine Coding Plan | Model keyword `volcengine-plan` | `https://ark.cn-beijing.volces.com/api/coding/v3` | Strips model prefix |
| BytePlus | Base keyword `bytepluses` | `https://ark.ap-southeast.bytepluses.com/api/v3` | Strips model prefix |
| BytePlus Coding Plan | Model keyword `byteplus-plan` | `https://ark.ap-southeast.bytepluses.com/api/coding/v3` | Strips model prefix |

### Standard Providers

| Provider | Keywords | API Key Env Var | Backend |
|----------|----------|----------------|---------|
| Anthropic | `anthropic`, `claude` | `ANTHROPIC_API_KEY` | `anthropic` (native SDK) |
| OpenAI | `openai`, `gpt` | `OPENAI_API_KEY` | `openai_compat` |
| Azure OpenAI | `azure`, `azure-openai` | (direct config) | `azure_openai` |
| OpenAI Codex | `openai-codex` | OAuth | `openai_codex` |
| GitHub Copilot | `github_copilot`, `copilot` | OAuth | `openai_compat` |
| DeepSeek | `deepseek` | `DEEPSEEK_API_KEY` | `openai_compat` |
| Gemini | `gemini` | `GEMINI_API_KEY` | `openai_compat` |
| Zhipu AI | `zhipu`, `glm`, `zai` | `ZAI_API_KEY` | `openai_compat` |
| DashScope (Qwen) | `qwen`, `dashscope` | `DASHSCOPE_API_KEY` | `openai_compat` |
| Moonshot (Kimi) | `moonshot`, `kimi` | `MOONSHOT_API_KEY` | `openai_compat` |
| MiniMax | `minimax` | `MINIMAX_API_KEY` | `openai_compat` |
| Mistral AI | `mistral` | `MISTRAL_API_KEY` | `openai_compat` |
| Step Fun | `stepfun`, `step` | `STEPFUN_API_KEY` | `openai_compat` |

### Local Deployments

| Provider | Keywords | Default API Base |
|----------|----------|-----------------|
| vLLM | `vllm` | (configurable) |
| Ollama | `ollama`, `nemotron` | `http://localhost:11434/v1` |
| OpenVINO Model Server | `openvino`, `ovms` | `http://localhost:8000/v3` |

### Auxiliary

| Provider | Keywords | Purpose |
|----------|----------|---------|
| Groq | `groq` | Whisper transcription + LLM |
| Custom | (direct) | Any OpenAI-compatible endpoint |

## `detect_provider()` Auto-Detection

The registry's `detect_provider()` function performs three-stage auto-detection:

```python
def detect_provider(model, api_key=None, api_base=None) -> ProviderSpec | None:
```

**Stage 1 -- Key Prefix:** Match `api_key` against `detect_by_key_prefix`.

```python
# "sk-or-v1-abc..." -> OpenRouter
# No match -> continue to Stage 2
```

**Stage 2 -- Base URL Keyword:** Match `api_base` against `detect_by_base_keyword`.

```python
# "https://api.deepseek.com" -> contains no keyword -> continue to Stage 3
# "https://openrouter.ai/api/v1" -> contains "openrouter" -> OpenRouter
```

**Stage 3 -- Model Name Keyword:** Match model name against `keywords`.

```python
# "claude-sonnet-4-20250514" -> contains "claude" -> Anthropic
# "gpt-4o" -> contains "gpt" -> OpenAI
# "deepseek-chat" -> contains "deepseek" -> DeepSeek
```

## AnthropicProvider (Native SDK)

The `AnthropicProvider` uses the official Anthropic Python SDK and supports:

- **Prompt caching** -- Automatic via `supports_prompt_caching=True` in the spec
- **Extended thinking** -- Returns `thinking_blocks` in `LLMResponse`
- **Full message conversion** -- Converts OpenAI-format tool calls to Anthropic format internally

```python
from agent_harness.providers.anthropic_provider import AnthropicProvider

provider = AnthropicProvider(api_key="sk-ant-...")
```

## OpenAICompatProvider (20+ Backends)

The `OpenAICompatProvider` uses the OpenAI Python SDK and powers all
OpenAI-compatible backends (OpenAI, DeepSeek, Gemini, Zhipu, DashScope, etc.).

Key features:

- **Chunk accumulation** -- Streams text deltas and accumulates them into the
  final response
- **Nullable schema normalization** -- Handles providers that return `null` schemas
  or nullable required fields
- **Single `api_key` + `api_base` + `model`** pattern covers all 20+ backends

```python
from agent_harness.providers.openai_compat_provider import OpenAICompatProvider

# OpenAI
provider = OpenAICompatProvider(api_key="sk-...", model="gpt-4o")

# DeepSeek
provider = OpenAICompatProvider(
    api_key="sk-...",
    api_base="https://api.deepseek.com",
    model="deepseek-chat",
)

# Gemini
provider = OpenAICompatProvider(
    api_key="AI...",
    api_base="https://generativelanguage.googleapis.com/v1beta/openai/",
    model="gemini-2.0-flash",
)
```

## Making Requests Without Tools

Both the provider base class and the Agent use tool-less requests for specific
flows:

- **Consolidation** -- The `MemoryConsolidator` calls the LLM without tools to
  generate memory summaries
- **Heartbeat** -- Periodic health-check calls that don't need tool access
- **Simple chat** -- When the agent has no tools configured

For these flows, simply omit the `tools` parameter:

```python
response = await provider.chat(messages)  # No tools parameter
```

The `AgentLoop` always passes tool definitions when they exist, but the
underlying `chat_with_retry()` method handles `tools=None` gracefully.

---

**Prev:** [Tools](tools.md) | **Next:** [Memory & Sessions](memory-session.md)
