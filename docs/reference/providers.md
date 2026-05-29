# Providers

The provider system abstracts LLM API calls behind a unified interface.

Source: `llm_harness.adapters.providers`

## LLMProvider (ABC)

```python
class LLMProvider(ABC):
    # Abstract methods (subclass must implement)
    async def chat(self, messages, tools=None, model=None, ...) -> LLMResponse: ...
    def get_default_model(self) -> str: ...

    # Template methods (retry logic built-in)
    async def chat_with_retry(self, messages, tools=None, model=None, ...) -> LLMResponse: ...
    async def chat_stream_with_retry(self, messages, tools=None, model=None, ...) -> LLMResponse: ...

    # Streaming (override for native support)
    async def chat_stream(self, messages, tools=None, model=None, ...,
                          on_content_delta=None) -> LLMResponse: ...
```

## LLMResponse

```python
@dataclass
class LLMResponse:
    content: str | None                     # text response
    tool_calls: list[ToolCallRequest]       # tool call list
    finish_reason: str = "stop"             # stop / tool_calls / error / length
    usage: dict[str, int]                   # token usage stats
    reasoning_content: str | None = None    # reasoning (DeepSeek-R1, Kimi, etc.)
    thinking_blocks: list[dict] | None = None  # Anthropic extended thinking

    @property
    def has_tool_calls(self) -> bool: ...
```

## ToolCallRequest

```python
@dataclass
class ToolCallRequest:
    id: str                                 # unique tool call ID
    name: str                               # tool name
    arguments: dict[str, Any]               # tool arguments
    extra_content: dict | None = None       # provider-specific extras (e.g., Gemini)
    provider_specific_fields: dict | None = None    # non-standard tool_call fields
    function_provider_specific_fields: dict | None = None  # non-standard function fields

    def to_openai_tool_call(self) -> dict: ...
```

## Retry Strategy

| Condition | Action |
|-----------|--------|
| Transient error (429, 5xx, timeout, etc.) | Retry with 1s/2s/4s backoff |
| Non-transient error + image content | Strip images, retry once |
| Non-transient error, no images | Return error response |

## Built-in Providers

### OpenAICompatProvider

Covers all OpenAI-compatible APIs (OpenAI, DeepSeek, DashScope, OpenRouter,
Ollama, vLLM, Gemini, Zhipu, Moonshot, Mistral, and more).

```python
provider = OpenAICompatProvider(
    api_key="sk-xxx",
    api_base="https://api.deepseek.com",
    default_model="deepseek-chat",
)
```

### AnthropicProvider

Native Anthropic SDK integration with prompt caching and extended thinking.

```python
provider = AnthropicProvider(
    api_key="sk-ant-xxx",
    default_model="claude-sonnet-4-20250514",
)
```

## ProviderSpec Registry

29 providers defined in `llm_harness.adapters.providers.registry.PROVIDERS`.

```python
from llm_harness.adapters.providers.registry import detect_provider, instantiate_provider

spec = detect_provider(model="deepseek-chat")
provider = instantiate_provider(spec)
```
