# AgentLoop

`AgentLoop` 是 **ReAct 骨架** — 核心循环，负责调用 LLM、检查工具调用、执行工具并组装消息历史。

源码位置：`llm_harness.core.loop`

## 构造函数

```python
AgentLoop(
    provider: LLMProvider,
    tools: ToolRegistry,
    model: str,
    *,
    on_build_context: BuildContextCallback,
    on_tool_check: ToolCheckCallback,
    on_error: ErrorCallback,
    on_event: EventCallback | None = None,
    emitter: EventEmitter | None = None,
    max_iterations: int = 40,
)
```

| 参数 | 类型 | 说明 |
|-----------|------|-------------|
| `provider` | `LLMProvider` | LLM provider |
| `tools` | `ToolRegistry` | 工具注册表 |
| `model` | `str` | 模型标识符 |
| `on_build_context` | `BuildContextCallback` | 为 LLM 组装消息 |
| `on_tool_check` | `ToolCheckCallback` | 工具执行前的权限检查 |
| `on_error` | `ErrorCallback` | 错误处理程序 |
| `on_event` | `EventCallback` 或 `None` | 遗留事件回调 |
| `emitter` | `EventEmitter` 或 `None` | 结构化可观测性 |
| `max_iterations` | `int` | 最大 ReAct 迭代次数（默认：40） |

## 回调签名

```python
# BuildContextCallback
Callable[[msg, history], list[dict] | Awaitable[list[dict]]]

# ToolCheckCallback
Callable[[name: str, tool: BaseTool, args: Any], Any | Awaitable[Any]]

# ErrorCallback
Callable[[exc: Exception, ctx: str], None]

# EventCallback
Callable[[event_type: str, payload: dict], Awaitable[None]]
```

## 方法

### run(msg, history, *, cwd=None) → TurnResult

```python
async def run(
    self,
    msg: Any,
    history: list[dict[str, Any]],
    *,
    cwd: Path | None = None,
) -> TurnResult
```

执行 ReAct 循环：

1. 调用 `on_build_context(msg, history)` → 消息列表
2. 循环（最多 `max_iterations` 次）：
   a. `provider.chat_with_retry(messages, tools, model)` → LLMResponse
   b. 如果没有 tool_calls：追加 assistant 消息，返回 TurnResult
   c. 对每个工具调用：检查 → 解析 → 执行 → 追加结果
3. 如果达到最大迭代次数：返回 "Max iterations reached."

## TurnResult

```python
@dataclass
class TurnResult:
    final_content: str | None = None       # LLM 文本响应
    tools_used: list[str] = field(default_factory=list)  # 已调用的工具名称
    messages: list[dict[str, Any]] = field(default_factory=list)  # 完整消息历史
    new_messages_start: int = 0  # 新消息开始的索引
```

## 常量

- `TOOL_RESULT_MAX_CHARS = 16_000` — 工具输出截断限制

## 用法

直接使用（绕过 Harness）：

```python
loop = AgentLoop(
    provider=provider,
    tools=registry,
    model="deepseek-chat",
    on_build_context=lambda m, h: [
        {"role": "system", "content": "Be helpful."},
        {"role": "user", "content": m.content},
    ],
    on_tool_check=lambda n, t, a: type("OK", (), {"allowed": True})(),
    on_error=lambda e, c: None,
)

result = await loop.run(msg, history, cwd=Path("/workspace"))
```
