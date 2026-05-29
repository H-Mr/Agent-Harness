# 如何添加自定义 LLM Provider

## 目标

添加你自己的 LLM provider——私有网关、本地模型，或不在内置注册表中的 API。

## 前置条件

- 可用的 llm-harness 安装
- 你的 provider 的 API endpoint URL

## 方式 A：使用 ProviderSpec（兼容 OpenAI 的 API）

如果你的 provider 使用兼容 OpenAI 的 API 格式：

### 1. 创建 ProviderSpec

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

# 注册（在检测 provider 之前）
from llm_harness.adapters.providers import registry
registry.PROVIDERS = registry.PROVIDERS + (my_spec,)
```

### 2. 使用

```python
spec = registry.detect_provider(model="my-gateway-model", api_base="https://api.my-gateway.com/v1")
provider = instantiate_provider(spec)
```

## 方式 B：继承 LLMProvider（非 OpenAI API）

适用于非兼容 OpenAI 的 API 的 provider：

### 1. 继承 LLMProvider

```python
from llm_harness.adapters.providers.base import LLMProvider, LLMResponse, ToolCallRequest

class MyCustomProvider(LLMProvider):
    def __init__(self, api_key=None, api_base=None):
        super().__init__(api_key, api_base)
        self.default_model = "my-model"

    @property
    def api_format(self) -> str:
        return "openai"  # 或 "anthropic"

    async def chat(self, messages, tools=None, model=None, max_tokens=4096,
                   temperature=0.7, reasoning_effort=None, tool_choice=None) -> LLMResponse:
        # 1. 将 messages 转换为你 API 的格式
        # 2. 发起 API 调用
        # 3. 将响应解析为 LLMResponse
        return LLMResponse(content="Response from custom provider", finish_reason="stop")

    def get_default_model(self) -> str:
        return self.default_model
```

### 2. 实现 chat_stream 以支持流式响应

如果你的 API 支持流式响应，请覆写 `chat_stream`：

```python
async def chat_stream(self, messages, tools=None, model=None, ..., on_content_delta=None) -> LLMResponse:
    # 从你的 API 流式获取数据，对每个文本块调用 on_content_delta
    ...
```

## 测试

```python
@pytest.mark.asyncio
async def test_custom_provider():
    provider = MyCustomProvider(api_key="test-key")
    response = await provider.chat([{"role": "user", "content": "Hello"}])
    assert response.content is not None
    assert response.finish_reason in ("stop", "error")
```
