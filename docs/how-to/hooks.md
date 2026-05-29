# How to Configure Lifecycle Hooks

## Goal

Attach custom logic to agent lifecycle events -- session start/end, pre-tool-use, and post-tool-use -- using shell commands, HTTP calls, or LLM-based validation.

## Prerequisites

- Working llm-harness installation
- Understanding of the harness config model

## Step by Step

### 1. Understand the Hook Model

Four hook types are available in `llm_harness.extensions.hooks.schemas`:

| Hook Type | Description |
|---|---|
| `CommandHookDefinition` | Runs a shell command. Useful for logging, metrics, or sidecar processes. |
| `HttpHookDefinition` | POSTs the event payload to a URL. Useful for webhook integrations. |
| `PromptHookDefinition` | Asks the LLM to validate a condition. The model must respond with `{"ok": true}` or `{"ok": false, "reason": "..."}`. |
| `AgentHookDefinition` | Like prompt, but with a system instruction encouraging deeper reasoning. Default timeout is 60s instead of 30s. |

Four events are available in `HookEvent`:

- `SESSION_START` -- fires when a session begins
- `SESSION_END` -- fires when a session ends
- `PRE_TOOL_USE` -- fires before a tool executes (can **block** the tool)
- `POST_TOOL_USE` -- fires after a tool executes (informational)

Each hook carries a `matcher` (fnmatch pattern) to filter which tools trigger it, and a `block_on_failure` flag that controls whether a failure stops the pipeline.

### 2. Define Hooks in Config

Hooks live under the `hooks` key in your harness settings:

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

### 3. Load Hooks Programmatically

Use `load_hook_registry` to convert a settings object into a `HookRegistry`:

```python
from llm_harness.extensions.hooks import load_hook_registry, HookRegistry

registry: HookRegistry = load_hook_registry(config)
print(registry.summary())
# Example output:
#   pre_tool_use:
#     - prompt matcher=exec*: ...
#     - http matcher=*: ...
```

### 4. Execute Hooks with HookExecutor

Create a `HookExecutor` with a `HookExecutionContext` and fire events:

```python
from pathlib import Path
from llm_harness.extensions.hooks.executor import HookExecutor, HookExecutionContext
from llm_harness.extensions.hooks.events import HookEvent

context = HookExecutionContext(
    cwd=Path("/workspace"),
    provider=provider,       # required for prompt/agent hooks
    default_model="deepseek-chat",
)

executor = HookExecutor(registry, context)

# Fire pre-tool-use for an exec call
result = await executor.execute(
    HookEvent.PRE_TOOL_USE,
    payload={
        "tool_name": "exec",
        "arguments": {"command": "rm -rf /data"},
        "session_key": "demo:test",
    },
)

if result.blocked:
    print(f"Blocked: {result.reason}")
else:
    print("All hooks passed, tool may proceed")
```

The `payload` dict is serialized as JSON and injected into command and prompt templates via the `$ARGUMENTS` placeholder.

### 5. Example: PreToolUse Validation

A common pattern is to validate dangerous tool calls before they execute. Here is a self-contained example using a prompt hook:

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

    # Build registry
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

    # Should be blocked
    result = await executor.execute(
        HookEvent.PRE_TOOL_USE,
        payload={
            "tool_name": "exec",
            "arguments": {"command": "rm -rf /"},
        },
    )
    print("Blocked?", result.blocked)   # True

    # Should pass
    result = await executor.execute(
        HookEvent.PRE_TOOL_USE,
        payload={
            "tool_name": "exec",
            "arguments": {"command": "ls -la"},
        },
    )
    print("Blocked?", result.blocked)   # False

asyncio.run(validate_tool_use())
```

### 6. Control Matcher and Blocking Behavior

The `matcher` field uses fnmatch syntax against the `tool_name` in the payload. `block_on_failure` determines whether a hook failure stops subsequent hooks and blocks the event:

```python
# Block any rm command (catches exec, glob rm, etc.)
CommandHookDefinition(
    command="python /scripts/audit_rm.py $ARGUMENTS",
    matcher="*rm*",
    block_on_failure=True,
)

# Non-blocking audit trail
HttpHookDefinition(
    url="http://audit:8080/event",
    block_on_failure=False,  # fire-and-forget
)
```

## Complete Example

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

    # Log session start
    registry.register(
        HookEvent.SESSION_START,
        CommandHookDefinition(
            command="echo 'session started' >> ./logs/sessions.log",
            timeout_seconds=5,
        ),
    )

    # Block dangerous exec calls
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

    # Audit log via HTTP
    registry.register(
        HookEvent.POST_TOOL_USE,
        HttpHookDefinition(
            url="http://localhost:9090/audit",
            headers={"Content-Type": "application/json"},
        ),
    )

    # Run hooks
    context = HookExecutionContext(cwd=Path("."))
    executor = HookExecutor(registry, context)

    await executor.execute(HookEvent.SESSION_START, payload={"session_key": "demo"})
    result = await executor.execute(
        HookEvent.PRE_TOOL_USE,
        payload={"tool_name": "exec", "arguments": {"command": "rm -rf /data"}},
    )
    print("Blocked?" if result.blocked else "Allowed")
    await executor.execute(
        HookEvent.POST_TOOL_USE,
        payload={"tool_name": "exec", "result": "ok"},
    )

asyncio.run(main())
```

## Testing

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

    # Non-matching tool should not trigger the hook
    result = await executor.execute(
        HookEvent.PRE_TOOL_USE,
        payload={"tool_name": "safe_tool"},
    )
    assert result.blocked is False
```
