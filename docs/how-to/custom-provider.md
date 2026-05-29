# How to Add a Custom LLM Provider

## Goal

Add your own LLM provider -- a private gateway, local model, or an API not in the built-in registry.

## Prerequisites

- Working llm-harness installation
- Your provider's API endpoint URL

## Approach A: Use ProviderSpec (OpenAI-compatible APIs)

If your provider speaks OpenAI-compatible API format:

### 1. Create a ProviderSpec

```python
from llm_harness.adapters.providers.registry import ProviderSpec, PROVIDERS, instantiate_provider

my_spec = ProviderSpec(
    name="my_gateway",
    keywords=("my-gateway",),
    env_key="MY_GATEWAY_API_KEY",
    display_name="My Gateway",
    backend="openai_compat",
    default_api_base="https://api.my-gateway.com/v1",
)

# Register (before detecting provider)
from llm_harness.adapters.providers import registry
registry.PROVIDERS = registry.PROVIDERS + (my_spec,)
```

### 2. Use

```python
spec = registry.detect_provider(model="my-gateway-model", api_base="https://api.my-gateway.com/v1")
provider = instantiate_provider(spec)
```

## Approach B: Subclass LLMProvider (non-OpenAI APIs)

For providers with non-OpenAI-compatible APIs:

### 1. Subclass LLMProvider

```python
from llm_harness.adapters.providers.base import LLMProvider, LLMResponse, ToolCallRequest

class MyCustomProvider(LLMProvider):
    def __init__(self, api_key=None, api_base=None):
        super().__init__(api_key, api_base)
        self.default_model = "my-model"

    @property
    def api_format(self) -> str:
        return "openai"  # or "anthropic"

    async def chat(self, messages, tools=None, model=None, max_tokens=4096,
                   temperature=0.7, reasoning_effort=None, tool_choice=None) -> LLMResponse:
        # 1. Convert messages to your API format
        # 2. Make the API call
        # 3. Parse response into LLMResponse
        return LLMResponse(content="Response from custom provider", finish_reason="stop")

    def get_default_model(self) -> str:
        return self.default_model
```

### 2. Implement chat_stream for streaming support

Override `chat_stream` if your API supports streaming responses:

```python
async def chat_stream(self, messages, tools=None, model=None, ..., on_content_delta=None) -> LLMResponse:
    # Stream from your API, call on_content_delta for each text chunk
    ...
```

## Testing

```python
@pytest.mark.asyncio
async def test_custom_provider():
    provider = MyCustomProvider(api_key="test-key")
    response = await provider.chat([{"role": "user", "content": "Hello"}])
    assert response.content is not None
    assert response.finish_reason in ("stop", "error")
```
