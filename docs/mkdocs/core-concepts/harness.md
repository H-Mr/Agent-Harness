# Harness -- Infrastructure Container

## What Harness Is

`Harness` is a configurable infrastructure container. It owns every subsystem
that an agent needs to operate, wires them together, and provides sensible
defaults so you can go from zero to running in a few lines of code.

```python
from agent_harness import Harness

harness = Harness(
    provider=my_provider,
    tools=["read_file", "write_file", "exec", "web_search"],
    permissions="default",
    workspace=Path("~/.my-agent"),
)
```

The Harness **is not runnable on its own**. It is a container that you pass to
an `Agent`:

```python
from agent_harness import Agent

agent = Agent(harness, model="claude-sonnet-4-20250514")
result = await agent.process(msg)
```

## Simplified Parameter Forms

Every parameter to `Harness.__init__()` accepts multiple types -- from full
instances down to simple strings and paths. The Harness resolves each to the
correct concrete type internally.

| Parameter | Accepted Types | Resolution |
|-----------|---------------|------------|
| `tools` | `ToolRegistry`, `ToolsConfig`, `list[str]`, `None` | `list[str]` creates a registry from built-in tool factories. `"*"` enables all, `"none"` disables all. |
| `permissions` | `PermissionChecker`, `PermissionSettings`, `str`, `None` | `str` maps: `"default"` -> DEFAULT mode, `"plan"` -> PLAN mode, `"full_auto"` / `"auto"` -> FULL_AUTO mode. |
| `memory` | `MemoryStore`, `str`, `Path`, `None` | `str`/`Path` creates a `MemoryStore` at that directory. `None` = no memory. |
| `sessions` | `SessionManager`, `str`, `Path`, `None` | `str`/`Path` creates a `SessionManager` at that directory. `None` = no sessions (stateless mode). |
| `context` | `ContextBuilder`, `list[SectionProvider]`, `None` | `list[SectionProvider]` creates a builder and registers each provider. |
| `skills` | `SkillRegistry`, `list[str | Path]`, `None` | `list[str | Path]` loads skill .md files from those directories. |
| `hooks` | `HookRegistry`, `str`, `Path`, `None` | `str`/`Path` loads `hooks.json` from that file or directory. |
| `tracker` | `str`, `Path`, `None` | Creates a `Tracker` writing JSONL events to that path. |

### Examples of Shorthand Resolution

```python
# All of these are equivalent:
Harness(permissions="default")
Harness(permissions=PermissionSettings(mode=PermissionMode.DEFAULT))
Harness(permissions=PermissionChecker(PermissionSettings(mode=PermissionMode.DEFAULT)))

# All of these are equivalent:
Harness(tools=["read_file", "exec"])
Harness(tools=ToolRegistry() | {...})  # programmatic
```

## All Parts the Harness Holds

```python
class Harness:
    def __init__(self, *, provider, workspace, tools, permissions,
                 memory, sessions, context, skills, hooks, tracker,
                 on_tool_check, on_build_context, on_error,
                 context_window_tokens, max_completion_tokens):
```

| Part | Type | Required | Purpose |
|------|------|----------|---------|
| `provider` | `LLMProvider` | **Yes** | The LLM backend (Anthropic, OpenAI, DeepSeek, etc.) |
| `workspace` | `Path` | No (default: cwd) | Base directory for sessions, memory, and tool execution |
| `tools` | `ToolRegistry` | No (default: empty) | All tools the agent can call |
| `permissions` | `PermissionChecker` | No (default: DEFAULT mode) | Policy engine for tool invocation |
| `memory` | `MemoryStore` | No (default: None) | Long-term + history persistence |
| `sessions` | `SessionManager` | No (default: None) | Conversation session management |
| `context` | `ContextBuilder` | No (default: empty) | System prompt assembly from pluggable section providers |
| `skills` | `SkillRegistry` | No (default: None) | On-demand knowledge files loaded into system prompt |
| `hooks` | `HookRegistry` | No (default: None) | Pre/Post tool-use lifecycle hooks |
| `tracker` | `Tracker` | No (default: None) | JSONL observability tracker |

!!! note "Required vs Optional"
    Only `provider` is truly required. All other parts have defaults or can be
    `None`. If `memory` and `sessions` are both `None`, the `Agent` operates in
    **stateless mode** -- no persistence, no consolidation, just a pure ReAct
    loop.

## `from_config()`: JSON-Driven Setup

The `Harness.from_config()` classmethod builds a fully configured Harness from a
`Config` Pydantic model. This is the primary path for applications that load
settings from `config.json` files.

```python
from agent_harness import load_config
from agent_harness.harness import Harness

# Load from ~/.agent-harness/config.json with env + CLI overrides
config = load_config()

# Build the whole infrastructure from config
harness = Harness.from_config(config)
```

### What `from_config()` Does

```python
@classmethod
def from_config(cls, config: Config, *, extra_tools=None) -> Harness:
```

1. **Resolves the provider** -- Uses `detect_provider()` when `provider="auto"`,
   or `find_by_name()` for explicit provider names.
2. **Builds tools** -- Calls `build_tools_from_config(config.tools)` which
   respects the `enabled`/`disabled` lists, `exec_enable`, `restrict_to_workspace`,
   and `web_search_provider` settings.
3. **Creates permissions** -- Maps `config.permission.mode` to a
   `PermissionChecker` with the configured allowed/denied tool lists.
4. **Auto-creates memory and sessions** -- Always creates `MemoryStore` at
   `{workspace}/memory` and `SessionManager` at `{workspace}`.
5. **Configures tracker** -- Starts JSONL tracking when
   `config.observability.track_file` is set.

### Config File Example

```json
{
  "agent": {
    "model": "claude-sonnet-4-20250514",
    "provider": "auto",
    "api_key": "sk-ant-...",
    "workspace": "~/.my-agent"
  },
  "permission": {
    "mode": "default"
  },
  "tools": {
    "enabled": ["*"],
    "exec_enable": true,
    "exec_timeout": 120,
    "restrict_to_workspace": true
  },
  "observability": {
    "track_file": "~/.my-agent/track.jsonl"
  }
}
```

## Pipeline Callbacks

The Harness exposes three callback hooks that let you customize the agent
pipeline without subclassing.

### `on_tool_check`

```python
on_tool_check: Callable[
    [str, BaseTool, Any],           # (tool_name, tool_instance, parsed_args)
    Awaitable[PermissionDecision],  # -> PermissionDecision
] | None
```

Called **before** every tool execution. The default implementation delegates to
`self.permissions.evaluate()`. Override to add custom approval logic -- for
example, checking a remote authorization service or implementing per-user quotas.

```python
async def my_tool_check(tool_name, tool, args):
    if tool_name == "exec" and "rm -rf" in args.command:
        return PermissionDecision(allowed=False, reason="rm -rf is always blocked")
    return await harness.permissions.evaluate(tool_name, is_read_only=tool.is_read_only(args))
```

### `on_build_context`

```python
on_build_context: Callable[
    [InboundMessage, list[dict[str, Any]]],  # (msg, history)
    Awaitable[list[dict[str, Any]]],          # -> messages
] | None
```

Called **before** the ReAct loop to assemble the initial message list. The
default implementation calls `self.context.build_system_prompt()` to get the
system prompt from all registered `SectionProvider` instances, then builds the
message list as `[system, *history, user_msg]`.

Override this to inject custom message formatting -- for example,
adding a function-call preamble or modifying the system prompt per-request.

```python
async def my_build_context(msg, history):
    system = await harness.context.build_system_prompt()
    return [
        {"role": "system", "content": system},
        *history,
        {"role": "user", "content": f"[{msg.channel}] {msg.content}"},
    ]
```

### `on_error`

```python
on_error: Callable[
    [Exception, str],       # (exception, context_label)
    Awaitable[str | None],  # -> user-facing message
] | None
```

Called when an exception escapes `Agent.process()`. The default handler logs the
exception and returns a generic apology. Override to return custom error
messages, trigger alerts, or attempt recovery.

```python
async def my_error_handler(exc, ctx):
    if isinstance(exc, RateLimitError):
        return "I'm rate-limited. Please wait a moment and try again."
    log.error("Unhandled error in %s: %s", ctx, exc)
    return None  # Agent will use its default message
```

## Skills Auto-Injection

When skills are configured, the Harness automatically injects a `SkillsSection`
into the `ContextBuilder`. This means skill definitions from `*.md` files in
configured skill directories are included in the system prompt without any
manual wiring.

```python
harness = Harness(
    provider=provider,
    skills=["~/.agent-harness/skills", "./project-skills"],
    # SkillsSection is auto-injected into context
)
```

!!! tip "Skills are on-demand"
    Skills are loaded into the system prompt when the agent starts. They act as
    extended knowledge that the model can reference during the conversation.

## How Defaults Work

The Harness resolves `None` parameters to sensible defaults:

- **tools=None** -> empty `ToolRegistry` (agent has no tools)
- **permissions=None** -> `PermissionChecker` in DEFAULT mode
- **context=None** -> empty `ContextBuilder`
- **memory=None** -> no memory system (skipped in Agent pipeline)
- **sessions=None** -> no session management (Agent runs stateless)

!!! warning "Provider is always required"
    The `provider` parameter has no default. If you try to create a Harness
    without a provider, you get a `TypeError` at construction time. Use
    `from_config()` if you want auto-detection from config values.

## Code Examples

### Minimal Harness (stateless, no tools)

```python
from agent_harness import Harness, Agent
from agent_harness.providers.anthropic_provider import AnthropicProvider

harness = Harness(
    provider=AnthropicProvider(api_key="sk-ant-..."),
)

agent = Agent(harness, model="claude-sonnet-4-20250514")
```

### Development Harness (read-only, filesystem tools)

```python
harness = Harness(
    provider=AnthropicProvider(api_key="sk-ant-..."),
    tools=["read_file", "glob", "grep", "list_dir", "web_search", "web_fetch"],
    permissions="plan",    # read-only mode
    workspace=Path("./dev-workspace"),
)
```

### Production Harness (sessions, memory, tracking)

```python
harness = Harness(
    provider=AnthropicProvider(api_key="sk-ant-..."),
    tools=ToolRegistry() | [my_custom_tool, another_tool],
    permissions="default",
    memory=Path("~/.my-agent/memory"),
    sessions=Path("~/.my-agent/sessions"),
    tracker=Path("~/.my-agent/track.jsonl"),
    context_window_tokens=200_000,
    max_completion_tokens=8192,
)
```

### Fully Loaded Harness with Custom Callbacks

```python
harness = Harness(
    provider=provider,
    tools=ToolRegistry() | [my_tool],
    permissions=PermissionChecker(PermissionSettings(mode=PermissionMode.FULL_AUTO)),
    memory=MemoryStore(Path("~/.agent/memory")),
    sessions=SessionManager(Path("~/.agent")),
    context=ContextBuilder() | [MyCustomSectionProvider()],
    skills=["~/.agent/skills"],
    hooks=Path("~/.agent/hooks.json"),
    tracker=Path("~/.agent/track.jsonl"),
    on_tool_check=my_custom_tool_check,
    on_build_context=my_custom_context_builder,
    on_error=my_error_handler,
    context_window_tokens=200_000,
    max_completion_tokens=8192,
)
```

---

**Next:** [Agent Deep Dive](agent.md) | **Prev:** [Conceptual Overview](overview.md)
