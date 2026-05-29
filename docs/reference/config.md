# Config

Configuration schema and loading. Pydantic models with env-var override support.

Source: `llm_harness.config`

## Config Model

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

## Sub-models

### AgentConfig

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `model` | `str` | `"claude-sonnet-4-6"` | Model identifier |
| `provider` | `str` | `"auto"` | Provider name or "auto" |
| `api_key` | `str` | `""` | API key (prefer env var) |
| `api_base` | `str` | `""` | API base URL |
| `max_tokens` | `int` | `4096` | Max completion tokens |
| `context_window_tokens` | `int` | `64000` | Context window size |

### ToolsConfig

| Field | Type | Description |
|-------|------|-------------|
| `enabled` | `list[str]` | Tools to enable (15 default tools) |
| `disabled` | `list[str]` | Tools to explicitly disable |

### PermissionConfig

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `mode` | `str` | `"default"` | `default` / `plan` / `full_auto` |
| `allowed_tools` | `list[str]` | `[]` | Explicit tool allowlist |
| `denied_tools` | `list[str]` | `[]` | Explicit tool denylist |

### SandboxConfig

| Field | Type | Default |
|-------|------|---------|
| `backend` | `str` | `"srt"` |

### MemoryConfig

| Field | Type | Default |
|-------|------|---------|
| `backend` | `str` | `"tencentdb"` |
| `base_url` | `str` | `"http://localhost:8420"` |

### ObservabilityConfig

| Field | Type | Default |
|-------|------|---------|
| `track_file` | `str` | `""` |

### ChannelConfig

| Field | Type | Default |
|-------|------|---------|
| `type` | `str` | `"cli"` |
| `settings` | `dict` | `{}` |

## Loading

```python
from llm_harness.config import load_config, Config

# From YAML
config = load_config("harness.yaml")

# With overrides
config = load_config("harness.yaml", model="claude-sonnet-4-6", provider="anthropic")

# From env
# LLM_HARNESS_MODEL=deepseek-chat LLM_HARNESS_API_KEY=sk-xxx
config = load_config()
```

### Priority (highest to lowest)

1. CLI arguments (`model=`, `provider=`)
2. Environment variables (`LLM_HARNESS_MODEL`, `LLM_HARNESS_API_KEY`, etc.)
3. YAML config file
4. Pydantic defaults

### Environment Variables

| Variable | Maps To |
|----------|---------|
| `LLM_HARNESS_CONFIG` | Config file path |
| `LLM_HARNESS_MODEL` | `agent.model` |
| `LLM_HARNESS_PROVIDER` | `agent.provider` |
| `LLM_HARNESS_API_KEY` | `agent.api_key` |
| `LLM_HARNESS_API_BASE` | `agent.api_base` |
| `LLM_HARNESS_WORKSPACE` | `workspace` |
