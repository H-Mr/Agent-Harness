# Harness

`Harness` is the **assembler** — it receives all dependencies, creates the
`MemoryConsolidator` (if memory is configured), injects callbacks into
`AgentLoop`, and returns a ready-to-use `Agent`.

Source: `llm_harness.core.harness`

## Constructor

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

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `provider` | `LLMProvider` | Yes | LLM provider instance |
| `model` | `str` | Yes | Model identifier |
| `tools` | `ToolRegistry` | Yes | Tool registry with registered tools |
| `sandbox` | `SandboxBackend` | Yes | Sandbox for file I/O and exec |
| `memory` | `MemoryBackend` | No | Memory backend for consolidation |
| `swarm` | `Any` | No | Sub-agent backend |
| `permissions` | `PermissionChecker` | No | Permission checker |
| `skills` | `SkillRegistry` | No | Skill registry (defaults to empty) |
| `observability` | `ObservabilityBackend` | No | Event backend |
| `system_prompt` | `str` | No | Custom system prompt (default: "You are a helpful AI assistant.") |
| `context_window_tokens` | `int` | No | Context window size for consolidation |
| `max_completion_tokens` | `int` | No | Max completion tokens for consolidation |

## Methods

### create_agent()

```python
def create_agent(self) -> Agent
```

Creates and returns a configured `Agent` instance. The returned Agent has:
- An `AgentLoop` with callbacks wired to `_build_system`, permissions, and error logging
- A `MemoryConsolidator` (if `memory` was provided)
- An `EventEmitter` (if `observability` was provided)

## Internal Methods

### _build_system(msg)

Assembles the system prompt from:
1. `system_prompt` (or default)
2. Current UTC time
3. Available sub-agent definitions (from swarm)
4. Available skills (from skill registry)

Returns `[{"role": "system", "content": "..."}]`

### _build_consolidator()

Creates `MemoryConsolidator` with `context_window_tokens` and
`max_completion_tokens` from the constructor. Called during `__init__`
only if `memory` is provided.

## Usage

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
