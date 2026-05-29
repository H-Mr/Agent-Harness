# Providers

Provider 系统在统一接口背后抽象了 LLM API 调用。

源码位置：`llm_harness.adapters.providers`

## LLMProvider (ABC)

```python
class LLMProvider(ABC):
    # 抽象方法（子类必须实现）
    async def chat(self, messages, tools=None, model=None, ...) -> LLMResponse: ...
    def get_default_model(self) -> str: ...

    # 模板方法（内置重试逻辑）
    async def chat_with_retry(self, messages, tools=None, model=None, ...) -> LLMResponse: ...
    async def chat_stream_with_retry(self, messages, tools=None, model=None, ...) -> LLMResponse: ...

    # 流式（覆盖以实现原生支持）
    async def chat_stream(self, messages, tools=None, model=None, ...,
                          on_content_delta=None) -> LLMResponse: ...
```

## LLMResponse

```python
@dataclass
class LLMResponse:
    content: str | None                     # 文本响应
    tool_calls: list[ToolCallRequest]       # 工具调用列表
    finish_reason: str = "stop"             # stop / tool_calls / error / length
    usage: dict[str, int]                   # 令牌使用统计
    reasoning_content: str | None = None    # 推理内容（DeepSeek-R1、Kimi 等）
    thinking_blocks: list[dict] | None = None  # Anthropic 扩展思考

    @property
    def has_tool_calls(self) -> bool: ...
```

## ToolCallRequest

```python
@dataclass
class ToolCallRequest:
    id: str                                 # 唯一工具调用 ID
    name: str                               # 工具名称
    arguments: dict[str, Any]               # 工具参数
    extra_content: dict | None = None       # provider 特定附加信息（例如 Gemini）
    provider_specific_fields: dict | None = None    # 非标准 tool_call 字段
    function_provider_specific_fields: dict | None = None  # 非标准 function 字段

    def to_openai_tool_call(self) -> dict: ...
```

## 重试策略

| 条件 | 操作 |
|-----------|--------|
| 瞬时错误（429、5xx、超时等） | 以 1s/2s/4s 退避重试 |
| 非瞬时错误 + 图片内容 | 移除图片，重试一次 |
| 非瞬时错误，无图片 | 返回错误响应 |

## 内置 Provider

### OpenAICompatProvider

覆盖所有 OpenAI 兼容 API（OpenAI、DeepSeek、DashScope、OpenRouter、Ollama、vLLM、Gemini、Zhipu、Moonshot、Mistral 等）。

```python
provider = OpenAICompatProvider(
    api_key="sk-xxx",
    api_base="https://api.deepseek.com",
    default_model="deepseek-chat",
)
```

### AnthropicProvider

原生 Anthropic SDK 集成，支持提示缓存和扩展思考。

```python
provider = AnthropicProvider(
    api_key="sk-ant-xxx",
    default_model="claude-sonnet-4-20250514",
)
```

## ProviderSpec 注册表

在 `llm_harness.adapters.providers.registry.PROVIDERS` 中定义了 29 个 provider。

```python
from llm_harness.adapters.providers.registry import detect_provider, instantiate_provider

spec = detect_provider(model="deepseek-chat")
provider = instantiate_provider(spec)
```
