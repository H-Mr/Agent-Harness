# Day 2：核心循环 — AgentLoop 与 Provider 抽象

> **目标读者**：已经理解 Harness/Agent 分离的架构，想深入 ReAct 循环的实现细节和 LLM 抽象层设计。
> **学完本节后，你应该能回答**：AgentLoop 为什么不知道 sessions/channels/permissions？`chat_with_retry` 如何在不修改子类的情况下为所有 Provider 添加重试能力？Anthropic 的 tool_use block 和 OpenAI 的 tool_calls 在哪个环节被统一成 LLMResponse？

---

## 一、深度解释

### 1.1 AgentLoop：刻意保持"无知"

如果你打开 `src/agent_harness/loop/agent.py`，第一眼会看到一段话：

```python
"""Agent Loop -- pure ReAct skeleton.

All app-specific behavior is injected via LoopCallbacks.
The loop knows nothing about sessions, channels, slash commands, or persistence.
"""
```

这不是注释，是一个架构宣言。AgentLoop 是整个系统的"引擎"，但它的职责被刻意限制在最小范围：**协调 LLM 和工具之间的对话循环**。

看它的构造函数：

```python
class AgentLoop:
    def __init__(
        self,
        provider: LLMProvider,
        callbacks: LoopCallbacks,
        *,
        model: str | None = None,
        max_iterations: int = 40,
        max_concurrent: int = 3,
    ):
        self.provider = provider
        self.callbacks = callbacks
        self.model = model or provider.get_default_model()
        self.max_iterations = max_iterations
```

只有六个参数：provider、callbacks、model、max_iterations、max_concurrent，外加一个内部 `_session_locks` 字典。没有 tools、没有 permissions、没有 sessions、没有 context builder。

**为什么？**

如果你的循环引擎知道"权限"这个概念，那它要么自己实现权限检查（耦合），要么暴露一个钩子让你注入（这是回调模式）。agent-harness 选择了后者。具体来说，AgentLoop 依赖四个核心回调，定义在 `LoopCallbacks` 中：

```python
@dataclass
class LoopCallbacks:
    build_messages: Callable[..., list[dict[str, Any]]]     # 构建 LLM 消息列表
    execute_tool: Callable[[str, dict[str, Any]], Awaitable[str]]  # 执行工具
    get_tool_definitions: Callable[[], list[dict[str, Any]]]      # 获取工具定义
    on_event: Callable[[object], Awaitable[None]] | None = None   # 可观测性事件
```

这四种回调覆盖了循环的全部"外部依赖"：

- **build_messages**：AgentLoop 不知道消息从哪里来、session 历史怎么拼接、system prompt 是什么。它只需要一个消息列表。调一次 `build_messages`，拿到 `initial_messages`，然后循环。
- **execute_tool**：AgentLoop 不知道工具有没有权限、参数是否合法、是不是钩子拦截了。它只需要 `(name, args) -> str`。调用方（`Agent._build_loop` 中注入的回调）在里面嵌入了权限检查、钩子执行、参数验证。
- **get_tool_definitions**：AgentLoop 不需要知道哪些工具被禁用了、哪些是只读的。它只需要一个 OpenAI 格式的工具定义列表，原样传给 LLM。
- **on_event**：AgentLoop 不关心谁在监听事件、是否写入 tracker、是否推送总线。它只需要 `event -> None`。

加上三个可选的流式回调：`on_stream`、`on_stream_end`、`on_progress`，以及一个用户交互回调 `ask_user`— 这就是 AgentLoop 的全部"外部接口"。

这种设计的好处可以用一个数字概括：**AgentLoop 类的代码量是 395 行**，其中核心循环逻辑不到 100 行。你可以在一个下午读完并理解它的全部行为。

### 1.2 LLMProvider 抽象层：模板方法模式的实战

看 `src/agent_harness/providers/base.py`，类开头的注释说得很清楚：

```python
"""
Core design uses the Template Method pattern:
  - chat() / chat_stream() are abstract methods implemented by subclasses
  - chat_with_retry() / chat_stream_with_retry() are template methods with retry logic built in

Call chain:
  AgentLoop.run_react_loop()
    -> provider.chat_with_retry(messages, tools)
      -> provider.chat(messages, tools)          <- subclass implementation
        -> API call (OpenAI / Anthropic / ...)
      -> transient error -> backoff retry (up to 3 attempts)
"""
```

**模板方法模式**的核心思想是：父类定义算法的骨架（template method），子类实现具体的步骤（primitive operation）。在 LLMProvider 中：

- 抽象方法（子类必须实现）：`chat()`、`chat_stream()`（可选）、`get_default_model()`
- 模板方法（父类已实现，子类不可覆盖）：`chat_with_retry()`、`chat_stream_with_retry()`

看 `chat_with_retry` 的代码：

```python
async def chat_with_retry(self, messages, tools=None, model=None, ...):
    # Sentinel handling: caller 没传的参数用 provider 默认值
    if max_tokens is self._SENTINEL:
        max_tokens = self.generation.max_tokens
    if temperature is self._SENTINEL:
        temperature = self.generation.temperature
    ...

    for attempt, delay in enumerate(self._CHAT_RETRY_DELAYS, start=1):
        response = await self._safe_chat(**kw)

        if response.finish_reason != "error":
            return response

        if not self._is_transient_error(response.content):
            # 非瞬态错误：尝试去图片重试一次
            stripped = self._strip_image_content(messages)
            if stripped is not None:
                return await self._safe_chat(**{**kw, "messages": stripped})
            return response

        logger.warning(...)
        await asyncio.sleep(delay)

    return await self._safe_chat(**kw)
```

**重试策略**的细节值得逐行分析：

1. **瞬态错误检测**通过 `_TRANSIENT_ERROR_MARKERS` 实现：
   ```python
   _TRANSIENT_ERROR_MARKERS = (
       "429", "rate limit", "500", "502", "503", "504",
       "overloaded", "timeout", "timed out", "connection",
       "server error", "temporarily unavailable",
   )
   ```
   当 LLM 返回 `finish_reason="error"` 且错误内容包含以上关键词时，判定为瞬态错误。

2. **指数退避**：延迟序列为 `(1, 2, 4)` 秒，对应三次重试尝试：
   ```python
   _CHAT_RETRY_DELAYS = (1, 2, 4)
   ```

3. **去图片降级**：如果错误不是瞬态的，但消息中包含图片内容（例如某 provider 不支持图片），`_strip_image_content` 会将 `image_url` 替换为 `[image: path]` 文本占位符，然后重试一次。这是"优雅降级"的经典例子。

4. **安全垫**：`_safe_chat` 将任何非 CancelledError 的异常包装为 `LLMResponse(finish_reason="error")`，确保模板方法永远不会因为子类的异常而崩溃。

这种设计的精妙之处在于：**AnthropicProvider 和 OpenAICompatProvider 都不需要关心重试逻辑**。它们的 `chat()` 方法只需要做一件事：把参数发给 API，解析响应。重试、降级、错误包装都是父类的职责。

### 1.3 LLMResponse：统一的"通用语言"

AgentLoop 和 LLMProvider 之间的契约是 `LLMResponse`：

```python
@dataclass
class LLMResponse:
    content: str | None                              # 文本回复
    tool_calls: list[ToolCallRequest] = field(default_factory=list)  # 工具调用
    finish_reason: str = "stop"                      # stop / tool_calls / error
    usage: dict[str, int] = field(default_factory=dict)  # token 用量
    reasoning_content: str | None = None             # 推理内容（Kimi / DeepSeek-R1）
    thinking_blocks: list[dict] | None = None        # Anthropic 扩展思考

    @property
    def has_tool_calls(self) -> bool:
        return len(self.tool_calls) > 0
```

AgentLoop 的 `run_react_loop` 只用两个分支处理这个响应：

```python
# Branch 1: LLM wants to call tools
if response.has_tool_calls:
    # 执行工具 → 结果追加到 messages → 继续循环

# Branch 2: LLM gave final text response
else:
    final_content = response.content
    break
```

不管底层是 Claude 还是 GPT-4o，是流式还是非流式，是 tool_use block 还是 function calling — 到 AgentLoop 这一层，都只剩下 `has_tool_calls` 一个布尔判断。

### 1.4 AnthropicProvider 与 OpenAICompatProvider：对称的差异

两个 Provider 的核心差异在于**消息格式转换**：

| 维度 | AnthropicProvider | OpenAICompatProvider |
|------|-------------------|---------------------|
| SDK | `anthropic.AsyncAnthropic` | `openai.AsyncOpenAI` |
| 消息格式 | Messages API（system/ user/assistant 交替） | OpenAI Chat（任意 role 顺序） |
| 工具格式 | `name + input_schema` | `function + parameters` |
| 工具调用格式 | `tool_use` block（id/name/input） | `tool_calls`（id/function/arguments） |
| 图片格式 | `image` block（base64/url） | `image_url` block |
| 扩展思考 | `thinking` block | `reasoning_content` 字段 |
| 流式实现 | `stream.text_stream` 逐文本块推送 | SSE chunks，需 `_parse_chunks` 汇总 |

核心转换发生在各自的 `_build_kwargs` 和 `_parse_response` / `_parse` 方法中。

以 AnthropicProvider 的响应解析为例：

```python
@staticmethod
def _parse_response(response: Any) -> LLMResponse:
    content_parts: list[str] = []
    tool_calls: list[ToolCallRequest] = []

    for block in response.content:
        if block.type == "text":
            content_parts.append(block.text)
        elif block.type == "tool_use":
            tool_calls.append(ToolCallRequest(
                id=block.id, name=block.name,
                arguments=block.input if isinstance(block.input, dict) else {},
            ))

    stop_map = {"tool_use": "tool_calls", "end_turn": "stop", "max_tokens": "length"}
    finish_reason = stop_map.get(response.stop_reason or "", response.stop_reason or "stop")

    usage = {
        "prompt_tokens": response.usage.input_tokens,
        "completion_tokens": response.usage.output_tokens,
    }
    # 额外读取 cache_creation_input_tokens / cache_read_input_tokens

    return LLMResponse(content="".join(content_parts) or None,
                       tool_calls=tool_calls,
                       finish_reason=finish_reason, usage=usage, ...)
```

而 OpenAICompatProvider 的 `_parse` 则处理 choices[0].message.tool_calls，两者最终都产出 `LLMResponse`。这种对称性是抽象层成功的标志：**添加一个新的 Provider，只需要实现从"SDK 原生格式"到"LLMResponse"的转换**。

### 1.5 registry.py：ProviderSpec 自动检测

`src/agent_harness/providers/registry.py` 是所有 LLM Provider 的元数据中心。每个 Provider 用一个 `ProviderSpec` 描述：

```python
@dataclass(frozen=True)
class ProviderSpec:
    name: str                                          # 配置字段名，如 "dashscope"
    keywords: tuple[str, ...]                          # 模型名关键词匹配
    env_key: str                                       # API key 环境变量名
    backend: str = "openai_compat"                     # "openai_compat" | "anthropic"
    default_api_base: str = ""                         # 默认 API 地址
    strip_model_prefix: bool = False                   # gateway 是否去掉模型名前缀
    model_overrides: tuple[tuple[str, dict], ...] = () # 特定模型的参数覆盖
    supports_prompt_caching: bool = False              # 是否支持 cache_control
    detect_by_key_prefix: str = ""                     # 通过 API key 前缀检测
    detect_by_base_keyword: str = ""                   # 通过 API base URL 关键词检测
```

`detect_provider` 函数按照"key 前缀 → base URL 关键词 → 模型名关键词"的优先级自动匹配 Provider：

```python
def detect_provider(model, api_key=None, api_base=None):
    # 1. 匹配 API key 前缀 (如 sk-or- → OpenRouter)
    # 2. 匹配 base URL 关键词 (如 aihubmix → AiHubMix)
    # 3. 匹配模型名关键词 (如 claude → Anthropic, gpt → OpenAI)
```

这种设计让用户只需提供模型名和 API key，系统就能自动选择正确的 Provider 实现。

---

## 二、源码导读

### 2.1 `loop/agent.py` — run_react_loop 逐行分析

这是 Day 2 最核心的代码段。我们从第 136 行开始逐行走：

```python
async def run_react_loop(
    self,
    initial_messages: list[dict[str, Any]],
    *,
    channel: str = "cli",
    chat_id: str = "direct",
) -> TurnResult:
```

**第 150 行：复制消息列表**
```python
messages = list(initial_messages)
```
为什么要 `list(initial_messages)` 而不是直接引用？因为循环会在 `messages` 上反复 `append`（每次工具执行后追加 assistant 消息和 tool result）。如果直接引用调用方的列表，会修改外部状态。浅拷贝保证循环内部的消息积累不会污染调用方的消息历史。

**第 151-153 行：初始化循环变量**
```python
iteration = 0
final_content = None
tools_used: list[str] = []
```
`iteration` 用于防护无限循环。`final_content` 既是循环终止条件（`break` 后被赋值），也是调用方判断是否成功的标志（如果为 `None` 说明超限）。

**第 155-157 行：缓存回调引用**
```python
on_stream = self.callbacks.on_stream
on_stream_end = self.callbacks.on_stream_end
on_progress = self.callbacks.on_progress
```
为什么不每次循环都访问 `self.callbacks`？这是微优化。在 40 次迭代中节省属性访问开销并不是关键，但它让代码更清晰——一眼看出循环中用了哪些回调。

**第 159 行：while 循环入口 — max_iterations 防护**
```python
while iteration < self.max_iterations:
    iteration += 1
```
默认 `max_iterations=40`。为什么是 40？因为大多数 Agent 任务在 3-5 轮工具调用内完成，40 是一个"永远不会触发的上限"。它的存在不是约束正常使用，而是防止 bug 导致无限循环。

**第 162 行：获取工具定义**
```python
tool_defs = self.callbacks.get_tool_definitions()
```
每次循环都重新获取。为什么不在循环外缓存？因为工具列表可能在运行时变化—权限变更、技能热加载、对话上下文的 tool choice 更新。每次重新获取是最简单的"无状态"策略。

**第 165-177 行：调用 LLM**
```python
if on_stream:
    response = await self.provider.chat_stream_with_retry(
        messages=messages, tools=tool_defs, model=self.model,
        on_content_delta=on_stream,
    )
else:
    response = await self.provider.chat_with_retry(
        messages=messages, tools=tool_defs, model=self.model,
    )
```
如果注册了 `on_stream` 回调就使用流式调用，否则非流式。注意 `chat_stream_with_retry` 和 `chat_with_retry` 的最后一个参数差异——流式版本需要一个 `on_content_delta` 来逐块推送文本。

**第 179-183 行：记录 token 用量**
```python
usage = response.usage or {}
self._last_usage = {
    "prompt_tokens": int(usage.get("prompt_tokens", 0) or 0),
    "completion_tokens": int(usage.get("completion_tokens", 0) or 0),
}
```
`int(... or 0)` 模式处理了 `None` 和 `""` 的情况。为什么要用 `int()` 再包一层？因为某些 provider 可能返回字符串型的数字。

**第 186 行：工具调用分支**
```python
if response.has_tool_calls:
    if on_stream and on_stream_end:
        await on_stream_end(resuming=True)
    
    # 并发执行工具（asyncio.gather）
    results = await asyncio.gather(
        *(self.callbacks.execute_tool(tc.name, tc.arguments)
          for tc in response.tool_calls),
        return_exceptions=True,
    )
```
关键设计决策：**同一轮 LLM 返回的所有工具并发执行**。`asyncio.gather` 的 `return_exceptions=True` 保证一个工具失败不会阻塞其他工具。失败的工具结果被包装成 `"Error: ExceptionType: message"` 字符串返回给 LLM。

**第 213-219 行：工具结果入消息**
```python
for tc, result in zip(response.tool_calls, results):
    is_err = isinstance(result, BaseException)
    if is_err:
        result = f"Error: {type(result).__name__}: {result}"
    messages.append({
        "role": "tool",
        "tool_call_id": tc.id,
        "name": tc.name,
        "content": str(result)[:self._TOOL_RESULT_MAX_CHARS],
    })
```
注意 `_TOOL_RESULT_MAX_CHARS = 16_000` 的截断。为什么是 16K？大多数 LLM 对 tool result 的内容长度没有严格限制，但过长的内容会浪费 token。16K 是一个合理的平衡值。

**第 242-259 行：文本回复分支**
```python
else:
    if on_stream and on_stream_end:
        await on_stream_end(resuming=False)
    
    if response.finish_reason == "error":
        final_content = response.content or "Sorry, I encountered an error."
        break
    
    messages.append(self._build_assistant_msg(response))
    final_content = response.content
    break
```
三种退出条件：
1. LLM 返回纯文本且 `finish_reason != "error"` ✓
2. LLM 返回 `finish_reason == "error"` — 记错误日志，返回错误消息
3. 循环结束（`iteration >= max_iterations`）— 第 261-266 行的兜底逻辑

**第 261-266 行：max_iterations 兜底**
```python
if final_content is None and iteration >= self.max_iterations:
    final_content = (
        f"Reached maximum iterations ({self.max_iterations}) without completion. "
        "Try breaking the task into smaller steps."
    )
```
这句话由系统生成，不是 LLM 的输出。它明确告诉调用方：循环被强制终止了，不是因为 LLM 完成了任务。

### 2.2 `providers/base.py` — 抽象方法的完整清单

除了前面分析的模板方法和重试策略，`LLMProvider` 还提供了一些"开箱即用"的工具方法：

**`_sanitize_empty_content`**：消息内容规范化。空字符串改为 `"(empty)"`（普通角色）或 `None`（assistant 带 tool_calls 时）。不同类型的内容（dict/list/str）统一为标准格式。

**`_sanitize_request_messages`**：用白名单过滤消息字段。不同 provider 对消息中的自定义字段有不同容忍度。这个函数确保只有 `role/content/tool_calls/tool_call_id/name` 这些标准字段被发送。

**`_strip_image_content`**：将 `image_url` 替换为文本占位符。用于"不支持图片的 provider"降级。

### 2.3 `providers/anthropic_provider.py` — 消息格式转换详解

AnthropicProvider 最复杂的部分不是调用 API，而是**消息格式转换**。

OpenAI Chat 格式和 Anthropic Messages API 格式的差异在于：

- Anthropic 需要 `system` 参数单独传递，不在 messages 列表中
- Anthropic 要求 user/assistant 角色交替，不允许连续两个相同的 role
- Anthropic 的 tool result 必须跟在对应的 user message 后
- Anthropic 支持 `thinking` block 用于扩展思考

`_convert_messages` 方法逐一处理这些差异：

```python
def _convert_messages(self, messages):
    for msg in messages:
        role = msg.get("role", "")

        if role == "system":
            system = content  # 单独抽出 system
            continue

        if role == "tool":
            # 转为 tool_result block，追加到上一条 user 消息后
            block = self._tool_result_block(msg)
            ...

        if role == "assistant":
            # 将 tool_calls 转为 tool_use blocks
            raw.append({"role": "assistant", "content": self._assistant_blocks(msg)})
            ...
```

`_assistant_blocks` 方法同时处理了三种情况：thinking blocks、文本内容、tool_use blocks。这让 Anthropic 的扩展思考功能对系统其他部分完全透明。

### 2.4 `providers/registry.py` — 30 个 Provider 的"户籍系统"

`PROVIDERS` 元组包含了 30 个预定义的 `ProviderSpec`，按优先级排序。Gateway 类 Provider（OpenRouter、AiHubMix）排在前面，因为它们通过 key/base URL 而不是模型名匹配。

每个 ProviderSpec 的核心价值在于：**让自动配置成为可能**。用户只需要提供 `model="claude-sonnet-4-20250514"`，`detect_provider` 就能匹配到 `keywords=("anthropic", "claude")` 的 Anthropic spec，然后读取 `env_key="ANTHROPIC_API_KEY"` 从环境变量获取 API key，并创建一个 `AnthropicProvider`。

---

## 三、动手练习：给 AgentLoop 加一个工具调用次数限制

这个练习的目的是让你**理解 AgentLoop 的回调机制**。你将通过两种方式实现工具调用次数限制，对比哪一种更干净。

### 3.1 练习背景

默认 AgentLoop 只通过 `max_iterations` 限制循环总轮数，但它无法区分"纯文本响应"和"工具调用"占了多少轮。假设你想让 Agent 在连续调用工具 5 次后自动停止（不管 `max_iterations` 还有多少剩余），应该怎么做？

### 3.2 方案一：通过 LoopCallbacks 的 execute_tool 注入计数

这个方案的思路是：在 `execute_tool` 回调中包裹一个计数器，当工具调用次数超过 N 时，返回一条特殊消息告诉 LLM "停止调用工具"，而不是抛出异常。

```python
"""
tool_limit_demo.py — 通过 LoopCallbacks 注入工具调用次数限制

用法: python tool_limit_demo.py
预期: Agent 在调用工具 3 次后自动停止，返回友好提示
"""

import asyncio
from agent_harness import AgentLoop, LoopCallbacks
from agent_harness.providers.base import LLMProvider, LLMResponse, ToolCallRequest


class MockProvider(LLMProvider):
    """模拟 LLM：前 4 次返回工具调用，第 5 次返回纯文本。"""

    def __init__(self):
        super().__init__(api_key="mock")
        self.call_count = 0

    async def chat(self, messages, tools=None, model=None, **kwargs):
        self.call_count += 1
        if self.call_count <= 4:
            return LLMResponse(
                content=None,
                tool_calls=[
                    ToolCallRequest(
                        id=f"call_{self.call_count}",
                        name="calculator",
                        arguments={"expr": f"{self.call_count}+1"},
                    )
                ],
                finish_reason="tool_calls",
            )
        return LLMResponse(
            content=f"Done after {self.call_count - 1} tool calls.",
            finish_reason="stop",
        )

    async def chat_stream(self, messages, tools=None, model=None,
                          on_content_delta=None, **kwargs):
        return await self.chat(messages, tools, model, **kwargs)

    def get_default_model(self):
        return "mock-model"


def build_tool_limited_loop(max_tool_calls: int = 3) -> AgentLoop:
    """创建一个带工具调用次数限制的 AgentLoop。"""

    tool_call_count = 0

    async def counting_execute_tool(name: str, args: dict) -> str:
        """带计数器的 execute_tool 实现。"""
        nonlocal tool_call_count
        tool_call_count += 1

        if tool_call_count > max_tool_calls:
            return (
                f"[LIMIT REACHED] 工具调用次数已达上限 ({max_tool_calls} 次)。"
                "请停止调用工具，直接回复用户。"
            )

        # 正常执行工具（这里用 mock 返回值）
        return f"calculator({args.get('expr', '?')}) = OK"

    callbacks = LoopCallbacks(
        build_messages=lambda msg: [
            {"role": "system", "content": "你是一个计算助手，使用 calculator 工具计算表达式。"},
            {"role": "user", "content": msg.content},
        ],
        execute_tool=counting_execute_tool,
        get_tool_definitions=lambda: [
            {
                "type": "function",
                "function": {
                    "name": "calculator",
                    "description": "计算表达式",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "expr": {"type": "string", "description": "数学表达式"}
                        },
                        "required": ["expr"],
                    },
                },
            }
        ],
    )

    return AgentLoop(provider=MockProvider(), callbacks=callbacks, max_iterations=10)


async def main():
    loop = build_tool_limited_loop(max_tool_calls=3)
    result = await loop.process_direct(
        content="请帮我计算 1+1, 2+2, 3+3, 4+4, 5+5",
    )

    print(f"最终回复: {result.final_content}")
    print(f"使用的工具: {result.tools_used}")
    print(f"调用次数: {len(result.tools_used)}")

    # 验证：工具调用应该不超过 3 次
    assert len(result.tools_used) <= 3, (
        f"工具调用次数 {len(result.tools_used)} 超过了上限 3"
    )
    assert result.final_content is not None
    # 注意：上限在第 4 次工具调用时被阻止，所以实际执行了 3 次
    print("✓ 工具调用次数限制生效")


if __name__ == "__main__":
    asyncio.run(main())
```

**方案一的原理**：`counting_execute_tool` 是一个闭包（closure），它捕获了 `tool_call_count` 变量。每次 `execute_tool` 被调用时，计数递增。当超过 `max_tool_calls` 时，不再真正执行工具，而是返回一条描述性错误消息。这条消息会被追加到 `messages` 中，LLM 在下一次迭代时会看到它并决定停止调用工具。

**关键设计决策**：
- 为什么返回消息而不是抛出异常？因为 `run_react_loop` 对异常的处理是包装成 `"Error: ..."` 字符串，行为相同。但返回一条语义明确的消息（"请停止调用工具，直接回复用户"）比错误信息更友好，LLM 更可能正确响应。
- 为什么不直接在 `execute_tool` 中调用 `sys.exit` 或 break？因为 `execute_tool` 只是一个返回 `str` 的普通函数，它无法影响 AgentLoop 的控制流。这是回调模式的"限制"也是它的优点——回调不知道循环的存在，循环也不知道回调的实现。

### 3.3 方案二：通过 AgentLoop 继承覆盖 max_iterations 动态调整

```python
class ToolLimitAgentLoop(AgentLoop):
    """在每次工具调用后动态减少 max_iterations。"""

    def __init__(self, *args, max_tool_calls: int = 3, **kwargs):
        super().__init__(*args, **kwargs)
        self.max_tool_calls = max_tool_calls
        self._tool_call_count = 0

    async def run_react_loop(self, initial_messages, **kwargs):
        original_execute = self.callbacks.execute_tool

        async def counting_execute(name, args):
            self._tool_call_count += 1
            if self._tool_call_count > self.max_tool_calls:
                return (
                    f"[LIMIT REACHED] 工具调用已达上限 "
                    f"({self.max_tool_calls} 次)。请直接回复。"
                )
            return await original_execute(name, args)

        self.callbacks.execute_tool = counting_execute
        return await super().run_react_loop(initial_messages, **kwargs)
```

方案二使用了子类继承 + 方法重写。相比方案一，它不需要在调用方创建闭包，而是将逻辑封装在 AgentLoop 子类中。

### 3.4 对比

| 维度 | 方案一（回调注入） | 方案二（继承覆盖） |
|------|-------------------|-------------------|
| 侵入性 | 无需修改 AgentLoop | 需要创建子类 |
| 灵活性 | 可在调用方按需启用 | 需要预先定义 |
| 测试难度 | 构造回调时注入 | 需要实例化子类 |
| 耦合度 | 低（回调对循环无感知） | 中（子类依赖父类实现） |

在 agent-harness 的设计哲学中，**方案一更符合"回调注入"的初衷**。AgentLoop 保持纯净，所有业务逻辑通过 `LoopCallbacks` 注入。

### 3.5 验证你的理解

1. 把 `max_tool_calls` 改为 0，观察会发生什么？
2. 如果把方案一中的 `counting_execute_tool` 改为抛出 `RuntimeError("tool limit exceeded")`，行为有何不同？
3. 修改 MockProvider，让它在收到包含 `[LIMIT REACHED]` 的消息后直接返回纯文本，而不是继续返回 `tool_calls`。这模拟了 LLM 听从指令的真实行为。
4. （进阶）在方案一的基础上，给 `counting_execute_tool` 添加一个"软限制"和"硬限制"：软限制时只记录日志（仍允许执行），硬限制时才阻止。

---

## 本节小结

| 概念 | 核心要点 |
|------|---------|
| **AgentLoop** | 纯 ReAct 骨架，不知道 sessions/channels/permissions，职责是协调 LLM↔Tools 循环 |
| **LoopCallbacks** | 四个核心回调（build_messages, execute_tool, get_tool_definitions, on_event）+ 三个可选流式回调 |
| **LLMProvider** | 模板方法模式：子类实现 `chat()`/`chat_stream()`，父类提供 `chat_with_retry()`/`chat_stream_with_retry()` |
| **重试策略** | 指数退避 1s→2s→4s，瞬态错误关键字匹配，图片降级重试，`_safe_chat` 异常安全垫 |
| **LLMResponse** | 统一模型：content / tool_calls / finish_reason / usage，`has_tool_calls` 属性是循环的关键分支 |
| **Anthropic vs OpenAI** | 消息格式、工具格式、图片格式、流式实现各有不同，但在 LLMResponse 层面完全统一 |
| **ProviderSpec** | 30 个预定义 Provider 元数据，`detect_provider` 按 key→base→model 三级匹配 |
| **回调注入优势** | 可在不修改 AgentLoop 的前提下实现工具调用计数、权限检查、钩子执行等机制 |

**明天预告**：Day 3 将深入 Tool 系统 — `BaseTool` 的 `input_model`/`output_model` 设计、`ToolRegistry` 的注册机制、以及 `build_tools_from_config` 的配置驱动工具构建过程。
