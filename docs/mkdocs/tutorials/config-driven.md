# 教程：配置文件驱动

不想写代码配置 Agent？llm-harness 支持完整的**配置文件驱动**模式 —— 所有设置都可以写在 `config.json` 中，代码只需要三行。

---

## Config 结构

配置文件的顶层结构对应 Python 的 `Config` 类：

```json
{
    "agent": {           // LLM 模型和 Agent 行为
        "model": "gpt-4o",
        "provider": "auto",
        "api_key": "sk-...",
        "api_base": "https://api.openai.com/v1",
        "workspace": "~/.my-agent",
        "max_tokens": 8192,
        "max_iterations": 40
    },
    "tools": {           // 工具启用/禁用和执行参数
        "enabled": ["*"],
        "disabled": [],
        "exec_timeout": 60,
        "restrict_to_workspace": false
    },
    "permission": {      // 权限模式
        "mode": "default",
        "allowed_tools": [],
        "denied_tools": []
    },
    "observability": {   // 观测追踪
        "track_file": null
    },
    "sandbox": {         // 沙箱隔离
        "enabled": false,
        "fail_if_unavailable": false
    }
}
```

!!! note "所有字段都有默认值"
    上面任何字段都是可选的。`Config()` 创建一个完全可用的默认配置。

---

## 完整示例

### config.json

```json title="~/.agent-harness/config.json"
{
    "agent": {
        "model": "claude-sonnet-4-20250514",
        "provider": "anthropic",
        "api_key": "sk-ant-...",
        "workspace": "~/.my-agent",
        "max_tokens": 4096,
        "max_iterations": 30,
        "temperature": 0.7,
        "timezone": "Asia/Shanghai"
    },
    "tools": {
        "enabled": ["read_file", "write_file", "edit_file", "exec",
                     "web_search", "web_fetch", "glob", "grep"],
        "disabled": [],
        "exec_timeout": 120,
        "exec_enable": true,
        "web_search_provider": "duckduckgo",
        "web_search_max_results": 5,
        "restrict_to_workspace": false
    },
    "permission": {
        "mode": "default",
        "allowed_tools": [],
        "denied_tools": []
    },
    "observability": {
        "track_file": "~/.my-agent/track.jsonl"
    }
}
```

### 对应的 Python 代码

```python title="run.py"
import asyncio
from agent_harness import Agent, Harness, InboundMessage, load_config

async def main():
    # 三行代码搞定一切
    config = load_config()
    harness = Harness.from_config(config)
    agent = Agent(harness)

    result = await agent.process(
        InboundMessage("cli", "user", "c1", "Hello!")
    )
    print(result.content)

asyncio.run(main())
```

!!! tip "代码量对比"
    - 纯代码方式：~20 行配置代码 + ~10 行运行代码
    - 配置文件方式：~3 行运行代码，所有配置在 JSON 中

---

## Harness.from_config() 详解

`Harness.from_config()` 根据 `Config` 对象完成以下自动装配：

| 组件 | 来源 | 说明 |
|------|------|------|
| `provider` | `agent.provider` / 自动检测 | 根据模型名、API Key 前缀、API Base URL 自动判断 |
| `tools` | `tools.enabled` / `tools.disabled` | 只加载启用列表中的工具，跳过禁用列表中的 |
| `permissions` | `permission.mode` | 创建 `PermissionChecker` 并设置模式 |
| `memory` | `workspace / memory` | 自动在 workspace 下创建 memory 目录 |
| `sessions` | `workspace` | 自动在 workspace 下创建会话存储 |
| `tracker` | `observability.track_file` | 如果设置了路径，自动启动 JSONL 追踪 |
| `context_window_tokens` | `agent.context_window_tokens` | 上下文窗口大小，默认为 64000 |
| `max_completion_tokens` | `agent.max_tokens` | 最大生成 token 数 |

### 如果配置缺失

如果 `config.json` 不存在或某些字段缺失，`load_config()` 会返回合理的默认值。以下配置完全等效：

```json
{}
```

这等价于：

```python
Config()
# agent.model = "claude-sonnet-4-6"
# agent.provider = "auto"
# tools.enabled = ["*"]
# permission.mode = "default"
```

---

## tools.enabled 的 "*" 和 "none" 语法

`tools.enabled` 支持三种语义：

| 值 | 效果 |
|----|------|
| `["*"]` | **启用所有工具**（默认）。加载全部 28 个内置工具。 |
| `["none"]` | **禁用所有工具**。Agent 只能对话，没有任何工具可用。 |
| `["read_file", "exec", ...]` | **只启用列表中的工具**。未列出的工具不会被加载。 |

`tools.disabled` 在启用列表基础上做减法：

```json
{
    "tools": {
        "enabled": ["*"],
        "disabled": ["exec", "notebook_edit"]
    }
}
```

!!! warning "disabled 优先级高于 enabled"
    即使 `enabled` 包含某个工具，如果它也在 `disabled` 中，该工具不会被加载。

---

## 权限模式配置

三种权限模式：

### default（默认模式）

```json
{
    "permission": {
        "mode": "default"
    }
}
```

- 只读操作自动放行
- 写操作（文件写入、命令执行等）需要用户确认
- **适合：交互式 CLI 使用**

### full_auto（全自动模式）

```json
{
    "permission": {
        "mode": "full_auto"
    }
}
```

- 所有操作自动放行，无需用户确认
- **适合：无人值守、自动化任务、个人助手**

### plan（计划模式）

```json
{
    "permission": {
        "mode": "plan"
    }
}
```

- 工具执行前需要用户审批
- **适合：高风险操作、生产环境**

### 工具级别的权限控制

```json
{
    "permission": {
        "mode": "default",
        "allowed_tools": ["read_file", "web_search"],
        "denied_tools": ["exec", "write_file"]
    }
}
```

- `allowed_tools`：仅允许列表中的工具执行（白名单）
- `denied_tools`：禁止列表中的工具执行（黑名单）

!!! note "allowed_tools 和 denied_tools 适用于所有模式"
    即使在 `full_auto` 模式下，`denied_tools` 中的工具也会被拒绝。这是安全底线。

---

## 观测配置

开启观测追踪可以记录每一次工具调用和 LLM 交互：

```json
{
    "observability": {
        "track_file": "~/.my-agent/track.jsonl"
    }
}
```

- 日志以 JSONL 格式写入指定文件
- 记录 17 种事件类型：消息开始/结束、工具调用开始/结束、错误、流式 delta 等
- 未设置 `track_file` 时观测系统零开销（不启动追踪器）

查看追踪日志：

```bash
# 查看最近的追踪记录
tail -5 ~/.my-agent/track.jsonl | jq .

# 统计工具调用次数
grep '"type":"tool_execution_completed"' ~/.my-agent/track.jsonl | wc -l
```

---

## 多种配置示例

### 开发配置（全部工具 + 全自动模式）

```json title="config.dev.json"
{
    "agent": {
        "model": "gpt-4o",
        "provider": "openai",
        "api_key": "sk-...",
        "workspace": "~/.my-agent-dev",
        "max_tokens": 8192,
        "max_iterations": 50
    },
    "tools": {
        "enabled": ["*"],
        "exec_timeout": 300
    },
    "permission": {
        "mode": "full_auto"
    },
    "observability": {
        "track_file": "~/.my-agent-dev/track.jsonl"
    }
}
```

### 生产配置（受限工具 + 计划模式）

```json title="config.prod.json"
{
    "agent": {
        "model": "claude-sonnet-4-20250514",
        "provider": "anthropic",
        "api_key": "sk-ant-...",
        "workspace": "/var/lib/my-agent",
        "max_tokens": 4096,
        "max_iterations": 20
    },
    "tools": {
        "enabled": ["read_file", "web_search", "web_fetch", "glob", "grep"],
        "disabled": ["exec"],
        "restrict_to_workspace": true,
        "exec_timeout": 30
    },
    "permission": {
        "mode": "plan",
        "allowed_tools": [],
        "denied_tools": ["exec"]
    },
    "observability": {
        "track_file": "/var/log/my-agent/track.jsonl"
    }
}
```

### 只读配置（纯对话 + 只读工具）

```json title="config.readonly.json"
{
    "agent": {
        "model": "gpt-4o-mini",
        "provider": "openai",
        "api_key": "sk-...",
        "max_tokens": 2048
    },
    "tools": {
        "enabled": ["read_file", "web_search", "web_fetch", "glob", "grep"],
        "disabled": ["write_file", "edit_file", "exec"]
    },
    "permission": {
        "mode": "default",
        "denied_tools": ["write_file", "edit_file", "exec"]
    }
}
```

### 切换配置

```python
from agent_harness import load_config
from pathlib import Path

# 加载不同配置
dev_config = load_config(Path("config.dev.json"))
prod_config = load_config(Path("config.prod.json"))

# 也可以用环境变量
# export HARNESS_CONFIG_PATH=config.prod.json
```

---

## 环境变量覆盖

除了配置文件，所有配置也可以通过环境变量覆盖：

```bash
export HARNESS_MODEL="gpt-4o"
export HARNESS_API_KEY="sk-..."
export HARNESS_API_BASE="https://api.openai.com/v1"
export HARNESS_MAX_TOKENS=8192
export HARNESS_CONFIG_PATH="~/.my-agent/config.json"
```

优先级：**CLI 参数 > 环境变量 > 配置文件 > 默认值**

---

## 总结

| 能力 | 配置方式 |
|------|----------|
| 模型/提供商 | `agent.model`, `agent.provider`, `agent.api_key` |
| 工具管理 | `tools.enabled`（`"*"` / `"none"` / 列表） |
| 权限控制 | `permission.mode` + `allowed_tools` / `denied_tools` |
| 观测追踪 | `observability.track_file` |
| 沙箱隔离 | `sandbox.enabled` |
| 环境覆盖 | `HARNESS_*` 环境变量 |

## 下一步

- [API 参考：Config](../api/config.md) — 完整的配置 Schema 文档
- [快速开始](quick-start.md) — 从零跑起第一个 Agent
- [架构设计](../explanation/architecture.md) — 理解整体架构
