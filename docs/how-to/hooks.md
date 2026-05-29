# 如何配置生命周期 Hook

## 目标

将自定义逻辑挂接到 agent 的生命周期事件中——会话开始/结束、工具使用前、工具使用后——支持 shell 命令、HTTP 调用或基于 LLM 的验证。

## 前置条件

- 可用的 llm-harness 安装
- 了解 harness 配置模型

## 分步指南

### 1. 理解 Hook 模型

`llm_harness.extensions.hooks.schemas` 中提供了四种 hook 类型：

| Hook 类型 | 说明 |
|---|---|
| `CommandHookDefinition` | 运行 shell 命令。适用于日志记录、指标收集或 sidecar 进程。 |
| `HttpHookDefinition` | 将事件负载 POST 到指定 URL。适用于 webhook 集成。 |
| `PromptHookDefinition` | 要求 LLM 验证某个条件。模型必须返回 `{"ok": true}` 或 `{"ok": false, "reason": "..."}`。 |
| `AgentHookDefinition` | 类似于 prompt hook，但使用系统指令鼓励更深层次的推理。默认超时时间 60s 而非 30s。 |

`HookEvent` 中提供了四个事件：

- `SESSION_START` —— 会话开始时触发
- `SESSION_END` —— 会话结束时触发
- `PRE_TOOL_USE` —— 工具执行前触发（可以**阻止**工具执行）
- `POST_TOOL_USE` —— 工具执行后触发（仅通知）

每个 hook 带有 `matcher`（fnmatch 模式）来过滤哪些工具触发它，以及 `block_on_failure` 标志来控制失败是否停止流水线。

### 2. 在配置中定义 Hook

Hook 位于 harness 设置的 `hooks` 键下：

```python
from llm_harness.config.schema import HarnessConfig
from llm_harness.extensions.hooks.schemas import (
    CommandHookDefinition,
    HttpHookDefinition,
    PromptHookDefinition,
    AgentHookDefinition,
)

config = HarnessConfig(
    hooks={
        "session_start": [
            CommandHookDefinition(
                command="echo 'Session started at $(date)' >> /var/log/harness.log",
                timeout_seconds=10,
            ),
        ],
        "pre_tool_use": [
            PromptHookDefinition(
                prompt=(
                    "The user wants to run tool '{{tool_name}}' with these arguments: "
                    "{{arguments}}. Is there any reason to block this?"
                ),
                matcher="exec*",
                block_on_failure=True,
            ),
            HttpHookDefinition(
                url="http://localhost:9090/audit",
                headers={"X-Source": "harness"},
                matcher="*",
                block_on_failure=False,
            ),
        ],
        "post_tool_use": [
            HttpHookDefinition(
                url="http://localhost:9090/log",
                timeout_seconds=5,
            ),
        ],
        "session_end": [
            CommandHookDefinition(
                command="curl -X POST -d 'session ended' http://alerts/internal",
                timeout_seconds=15,
            ),
        ],
    },
)
```

### 3. 以编程方式加载 Hook

使用 `load_hook_registry` 将设置对象转换为 `HookRegistry`：

```python
from llm_harness.extensions.hooks import load_hook_registry, HookRegistry

registry: HookRegistry = load_hook_registry(config)
print(registry.summary())
# 示例输出：
#   pre_tool_use:
#     - prompt matcher=exec*: ...
#     - http matcher=*: ...
```

### 4. 使用 HookExecutor 执行 Hook

创建带有 `HookExecutionContext` 的 `HookExecutor` 并触发事件：

```python
from pathlib import Path
from llm_harness.extensions.hooks.executor import HookExecutor, HookExecutionContext
from llm_harness.extensions.hooks.events import HookEvent

context = HookExecutionContext(
    cwd=Path("/workspace"),
    provider=provider,       # prompt/agent hook 必须提供
    default_model="deepseek-chat",
)

executor = HookExecutor(registry, context)

# 为 exec 调用触发 tool-use-pre 事件
result = await executor.execute(
    HookEvent.PRE_TOOL_USE,
    payload={
        "tool_name": "exec",
        "arguments": {"command": "rm -rf /data"},
        "session_key": "demo:test",
    },
)

if result.blocked:
    print(f"被阻止: {result.reason}")
else:
    print("所有 hook 通过，工具可以继续执行")
```

`payload` dict 被序列化为 JSON，并通过 `$ARGUMENTS` 占位符注入到命令和 prompt 模板中。

### 5. 示例：PreToolUse 验证

一个常见的模式是在危险工具调用执行前进行验证。以下是一个使用 prompt hook 的完整示例：

```python
import asyncio
from pathlib import Path
from llm_harness.extensions.hooks import (
    HookRegistry, HookEvent,
    CommandHookDefinition, PromptHookDefinition,
    load_hook_registry,
)
from llm_harness.extensions.hooks.executor import HookExecutor, HookExecutionContext
from llm_harness.adapters.providers.openai_compat_provider import OpenAICompatProvider

async def validate_tool_use():
    provider = OpenAICompatProvider(api_key="...", api_base="https://api.deepseek.com")

    # 构建 registry
    registry = HookRegistry()
    registry.register(
        HookEvent.PRE_TOOL_USE,
        PromptHookDefinition(
            prompt=(
                "Tool: {{tool_name}}\n"
                "Arguments: {{arguments}}\n\n"
                'If the tool is "exec" and the command contains "rm -rf" or '
                '"drop table", respond with {"ok": false, "reason": "..."}. '
                "Otherwise respond {\"ok\": true}."
            ),
            matcher="exec",
            block_on_failure=True,
        ),
    )

    context = HookExecutionContext(
        cwd=Path("/workspace"),
        provider=provider,
        default_model="deepseek-chat",
    )
    executor = HookExecutor(registry, context)

    # 应被阻止
    result = await executor.execute(
        HookEvent.PRE_TOOL_USE,
        payload={
            "tool_name": "exec",
            "arguments": {"command": "rm -rf /"},
        },
    )
    print("被阻止?", result.blocked)   # True

    # 应通过
    result = await executor.execute(
        HookEvent.PRE_TOOL_USE,
        payload={
            "tool_name": "exec",
            "arguments": {"command": "ls -la"},
        },
    )
    print("被阻止?", result.blocked)   # False

asyncio.run(validate_tool_use())
```

### 6. 控制 Matcher 和阻塞行为

`matcher` 字段针对 payload 中的 `tool_name` 使用 fnmatch 语法。`block_on_failure` 决定 hook 失败是否停止后续 hook 并阻塞事件：

```python
# 阻止任何 rm 命令（匹配 exec、glob rm 等）
CommandHookDefinition(
    command="python /scripts/audit_rm.py $ARGUMENTS",
    matcher="*rm*",
    block_on_failure=True,
)

# 非阻塞审计跟踪
HttpHookDefinition(
    url="http://audit:8080/event",
    block_on_failure=False,  # 即发即忘
)
```

## 完整示例

```python
import asyncio
from pathlib import Path
from llm_harness.extensions.hooks import (
    HookRegistry, HookEvent,
    CommandHookDefinition, PromptHookDefinition, HttpHookDefinition,
)
from llm_harness.extensions.hooks.executor import HookExecutor, HookExecutionContext

async def main():
    registry = HookRegistry()

    # 记录会话开始
    registry.register(
        HookEvent.SESSION_START,
        CommandHookDefinition(
            command="echo 'session started' >> ./logs/sessions.log",
            timeout_seconds=5,
        ),
    )

    # 阻止危险的 exec 调用
    registry.register(
        HookEvent.PRE_TOOL_USE,
        CommandHookDefinition(
            command=(
                'python -c "'
                'import json,sys; p=json.loads(sys.argv[1]); '
                'exit(1) if \"rm\" in p.get(\"arguments\",{}).get(\"command\",\"\") else exit(0)'
                '" $ARGUMENTS'
            ),
            matcher="exec",
            block_on_failure=True,
        ),
    )

    # 通过 HTTP 记录审计日志
    registry.register(
        HookEvent.POST_TOOL_USE,
        HttpHookDefinition(
            url="http://localhost:9090/audit",
            headers={"Content-Type": "application/json"},
        ),
    )

    # 运行 hook
    context = HookExecutionContext(cwd=Path("."))
    executor = HookExecutor(registry, context)

    await executor.execute(HookEvent.SESSION_START, payload={"session_key": "demo"})
    result = await executor.execute(
        HookEvent.PRE_TOOL_USE,
        payload={"tool_name": "exec", "arguments": {"command": "rm -rf /data"}},
    )
    print("被阻止?" if result.blocked else "已允许")
    await executor.execute(
        HookEvent.POST_TOOL_USE,
        payload={"tool_name": "exec", "result": "ok"},
    )

asyncio.run(main())
```

## 测试

```python
import pytest
from pathlib import Path
from llm_harness.extensions.hooks import HookRegistry, HookEvent, CommandHookDefinition
from llm_harness.extensions.hooks.executor import HookExecutor, HookExecutionContext

@pytest.mark.asyncio
async def test_pre_tool_use_blocking():
    registry = HookRegistry()
    registry.register(
        HookEvent.PRE_TOOL_USE,
        CommandHookDefinition(
            command="exit 1",
            matcher="dangerous_tool",
            block_on_failure=True,
        ),
    )
    context = HookExecutionContext(cwd=Path("/tmp"))
    executor = HookExecutor(registry, context)

    result = await executor.execute(
        HookEvent.PRE_TOOL_USE,
        payload={"tool_name": "dangerous_tool"},
    )
    assert result.blocked is True

    # 不匹配的工具不应触发 hook
    result = await executor.execute(
        HookEvent.PRE_TOOL_USE,
        payload={"tool_name": "safe_tool"},
    )
    assert result.blocked is False
```
