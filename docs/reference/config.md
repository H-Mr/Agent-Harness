# Config

配置模式和加载。支持环境变量覆盖的 Pydantic 模型。

源码位置：`llm_harness.config`

## Config 模型

```python
class Config(BaseModel):
    agent: AgentConfig
    tools: ToolsConfig
    permission: PermissionConfig
    sandbox: SandboxConfig
    memory: MemoryConfig
    observability: ObservabilityConfig
    channels: list[ChannelConfig]
    workspace: str = "."

    @property
    def workspace_path(self) -> Path: ...
```

## 子模型

### AgentConfig

| 字段 | 类型 | 默认值 | 说明 |
|-------|------|---------|-------------|
| `model` | `str` | `"claude-sonnet-4-6"` | 模型标识符 |
| `provider` | `str` | `"auto"` | Provider 名称或 "auto" |
| `api_key` | `str` | `""` | API 密钥（优先使用环境变量） |
| `api_base` | `str` | `""` | API 基础 URL |
| `max_tokens` | `int` | `4096` | 最大补全令牌数 |
| `context_window_tokens` | `int` | `64000` | 上下文窗口大小 |

### ToolsConfig

| 字段 | 类型 | 说明 |
|-------|------|-------------|
| `enabled` | `list[str]` | 启用的工具（15 个默认工具） |
| `disabled` | `list[str]` | 显式禁用的工具 |

### PermissionConfig

| 字段 | 类型 | 默认值 | 说明 |
|-------|------|---------|-------------|
| `mode` | `str` | `"default"` | `default` / `plan` / `full_auto` |
| `allowed_tools` | `list[str]` | `[]` | 显式工具允许列表 |
| `denied_tools` | `list[str]` | `[]` | 显式工具拒绝列表 |

### SandboxConfig

| 字段 | 类型 | 默认值 |
|-------|------|---------|
| `backend` | `str` | `"srt"` |

### MemoryConfig

| 字段 | 类型 | 默认值 |
|-------|------|---------|
| `backend` | `str` | `"tencentdb"` |
| `base_url` | `str` | `"http://localhost:8420"` |

### ObservabilityConfig

| 字段 | 类型 | 默认值 |
|-------|------|---------|
| `track_file` | `str` | `""` |

### ChannelConfig

| 字段 | 类型 | 默认值 |
|-------|------|---------|
| `type` | `str` | `"cli"` |
| `settings` | `dict` | `{}` |

## 加载

```python
from llm_harness.config import load_config, Config

# 从 YAML
config = load_config("harness.yaml")

# 带覆盖参数
config = load_config("harness.yaml", model="claude-sonnet-4-6", provider="anthropic")

# 从环境变量
# LLM_HARNESS_MODEL=deepseek-chat LLM_HARNESS_API_KEY=sk-xxx
config = load_config()
```

### 优先级（从高到低）

1. CLI 参数（`model=`、`provider=`）
2. 环境变量（`LLM_HARNESS_MODEL`、`LLM_HARNESS_API_KEY` 等）
3. YAML 配置文件
4. Pydantic 默认值

### 环境变量

| 变量 | 映射到 |
|----------|---------|
| `LLM_HARNESS_CONFIG` | 配置文件路径 |
| `LLM_HARNESS_MODEL` | `agent.model` |
| `LLM_HARNESS_PROVIDER` | `agent.provider` |
| `LLM_HARNESS_API_KEY` | `agent.api_key` |
| `LLM_HARNESS_API_BASE` | `agent.api_base` |
| `LLM_HARNESS_WORKSPACE` | `workspace` |
