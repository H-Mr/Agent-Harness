# Harness

`Harness` 是 **组装器** — 它接收所有依赖项，创建 `MemoryConsolidator`（如果配置了 memory），将回调注入 `AgentLoop`，并返回一个可直接使用的 `Agent`。

源码位置：`llm_harness.core.harness`

## 构造函数

```python
Harness(
    *,
    provider: LLMProvider,          # required
    model: str,                     # required
    tools: ToolRegistry,            # required
    sandbox: SandboxBackend,        # required
    memory: MemoryBackend | None = None,
    swarm: Any = None,
    permissions: PermissionChecker | None = None,
    skills: SkillRegistry | None = None,
    observability: ObservabilityBackend | None = None,
    system_prompt: str = "",
    context_window_tokens: int = 64_000,
    max_completion_tokens: int = 4096,
)
```

| 参数 | 类型 | 必填 | 说明 |
|-----------|------|----------|-------------|
| `provider` | `LLMProvider` | 是 | LLM provider 实例 |
| `model` | `str` | 是 | 模型标识符 |
| `tools` | `ToolRegistry` | 是 | 已注册工具的 ToolRegistry |
| `sandbox` | `SandboxBackend` | 是 | 用于文件 I/O 和执行的沙箱 |
| `memory` | `MemoryBackend` | 否 | 用于整合的 memory 后端 |
| `swarm` | `Any` | 否 | 子代理后端 |
| `permissions` | `PermissionChecker` | 否 | 权限检查器 |
| `skills` | `SkillRegistry` | 否 | 技能注册表（默认为空） |
| `observability` | `ObservabilityBackend` | 否 | 事件后端 |
| `system_prompt` | `str` | 否 | 自定义系统提示（默认："You are a helpful AI assistant."） |
| `context_window_tokens` | `int` | 否 | 整合时的上下文窗口大小 |
| `max_completion_tokens` | `int` | 否 | 整合时的最大补全令牌数 |

## 方法

### create_agent()

```python
def create_agent(self) -> Agent
```

创建并返回一个已配置的 `Agent` 实例。返回的 Agent 包含：
- 一个 `AgentLoop`，其回调连接到 `_build_system`、权限和错误日志记录
- 一个 `MemoryConsolidator`（如果提供了 `memory`）
- 一个 `EventEmitter`（如果提供了 `observability`）

## 内部方法

### _build_system(msg)

从以下部分组装系统提示：
1. `system_prompt`（或默认值）
2. 当前 UTC 时间
3. 可用的子代理定义（来自 swarm）
4. 可用的技能（来自 skill registry）

返回 `[{"role": "system", "content": "..."}]`

### _build_consolidator()

使用构造函数中的 `context_window_tokens` 和 `max_completion_tokens` 创建 `MemoryConsolidator`。仅在提供 `memory` 时在 `__init__` 期间调用。

## 用法

```python
from llm_harness import Harness

harness = Harness(
    provider=OpenAICompatProvider(api_key="sk-xxx"),
    model="deepseek-chat",
    tools=my_tools,
    sandbox=SRTSandboxBackend("/workspace"),
    memory=TencentDBMemoryBackend(),
    permissions=PermissionChecker(PermissionSettings()),
    system_prompt="You are a coding assistant.",
)
agent = harness.create_agent()
```
