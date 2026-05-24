# Permissions -- The Permission System

## Overview

The permission system protects the host system from unintended or malicious
tool invocations. It operates at multiple layers:

1. **Mode-based policy** -- DEFAULT (read-only auto, mutating asks), PLAN
   (read-only only), FULL_AUTO (everything allowed)
2. **Built-in sensitive path protection** -- always-on credential guards
3. **Tool allow/deny lists** -- explicit per-tool policy
4. **Path-level glob rules** -- filesystem access controls
5. **Command deny patterns** -- shell command safety

## Three Modes

```python
from agent_harness.permissions.modes import PermissionMode
```

| Mode | Value | Behavior |
|------|-------|----------|
| DEFAULT | `"default"` | Read-only tools auto-approved. Mutating tools require confirmation. |
| PLAN | `"plan"` | Read-only tools auto-approved. **All** mutating tools denied. |
| FULL_AUTO | `"full_auto"` / `"auto"` | All tools auto-approved (no confirmation prompts). |

```python
from agent_harness.harness import Harness

# Default mode
Harness(permissions="default")

# Plan mode (read-only exploration)
Harness(permissions="plan")

# Full auto (no guardrails)
Harness(permissions="full_auto")
```

## The Permission Decision

Every permission check returns a `PermissionDecision`:

```python
@dataclass(frozen=True)
class PermissionDecision:
    allowed: bool                  # May the tool run?
    requires_confirmation: bool    # Should we ask the user first?
    reason: str                    # Why this decision was made
```

### Decision Matrix

| Mode | Read-Only Tool | Mutating Tool | Denied Tool |
|------|---------------|---------------|-------------|
| DEFAULT | Allowed | Requires confirmation | Denied |
| PLAN | Allowed | Denied | Denied |
| FULL_AUTO | Allowed | Allowed | Denied |

## Built-In Sensitive Path Patterns

Certain paths are always denied regardless of permission mode. This is a
defence-in-depth measure against LLM-directed or prompt-injection-driven access
to credential files.

```python
SENSITIVE_PATH_PATTERNS: tuple[str, ...] = (
    # SSH keys and config
    "*/.ssh/*",
    # AWS credentials
    "*/.aws/credentials",
    "*/.aws/config",
    # GCP credentials
    "*/.config/gcloud/*",
    # Azure credentials
    "*/.azure/*",
    # GPG keys
    "*/.gnupg/*",
    # Docker credentials
    "*/.docker/config.json",
    # Kubernetes credentials
    "*/.kube/config",
    # Agent Harness own credential stores
    "*/.agent-harness/credentials.json",
    "*/.agent-harness/copilot_auth.json",
)
```

!!! warning "Always active"
    These patterns use `fnmatch` syntax and are matched against the
    fully-resolved absolute path. They **cannot** be overridden by user settings
    or permission mode. They apply to any tool that takes a `file_path`
    parameter.

## Path-Level Glob Rules

Beyond built-in patterns, you can define custom path rules in `PermissionSettings`:

```python
from agent_harness.permissions.settings import PermissionSettings, PathRuleConfig

settings = PermissionSettings(
    path_rules=[
        PathRuleConfig(pattern="/etc/*", allow=False),
        PathRuleConfig(pattern="/home/*/public/*", allow=True),
    ]
)
```

Path rules are evaluated in order and are checked only when the tool invocation
includes a `file_path` parameter.

## Command Deny Patterns

For shell execution tools (`exec`), you can define deny patterns using `fnmatch`:

```python
settings = PermissionSettings(
    denied_commands=[
        "rm -rf /",
        "rm -rf /*",
        "dd *",
        "mkfs.*",
        ":(){ :|:& };:",  # Fork bomb
    ]
)
```

These are matched against the full command string using `fnmatch`.

## Tool Allow/Deny Lists

Fine-grained control over individual tools:

```python
settings = PermissionSettings(
    allowed_tools=["read_file", "web_search"],   # Only these tools
    denied_tools=["exec"],                       # Never allow exec
)
```

- `denied_tools` is checked first -- if a tool is denied, it always fails
- `allowed_tools` is checked next -- if a tool is allowed, it bypasses mode checks
- If neither list contains the tool, mode-based policy applies

## How Permissions Integrate into the Tool Execution Pipeline

Permissions are checked as the second stage of the tool lifecycle in
`Agent._build_loop()`:

```python
async def execute_tool(tool_name, args_dict):
    tool = harness.tools.get(tool_name)
    parsed = tool.input_model.model_validate(args_dict)

    # Permission check
    permission = await harness.on_tool_check(tool_name, tool, parsed)
    if not permission.allowed:
        return f"Error: Permission denied: {permission.reason}"

    # Execute (only if allowed)
    result = await tool.execute(parsed, context)
    return result.output
```

### The `on_tool_check` Callback

The `Harness.on_tool_check` callback wraps the `PermissionChecker`. The default
implementation:

```python
async def _default_tool_check(self, tool_name, tool, parsed_args):
    return self.permissions.evaluate(
        tool_name,
        is_read_only=tool.is_read_only(parsed_args),
    )
```

You can override this to add custom logic:

```python
async def my_tool_check(tool_name, tool, parsed_args):
    # Always allow read_file for .md files
    if tool_name == "read_file" and parsed_args.file_path.endswith(".md"):
        return PermissionDecision(allowed=True, reason="Markdown files always allowed")

    # Check a remote permission service
    if not await remote_auth.check(tool_name, getattr(parsed_args, 'file_path', None)):
        return PermissionDecision(allowed=False, reason="Denied by remote policy")

    # Fall through to default
    return harness.permissions.evaluate(tool_name, is_read_only=tool.is_read_only(parsed_args))
```

### The `PermissionChecker.evaluate()` Method

```python
def evaluate(
    self,
    tool_name: str,
    *,
    is_read_only: bool,
    file_path: str | None = None,
    command: str | None = None,
) -> PermissionDecision:
```

The evaluation order is:

1. **Sensitive path check** -- If `file_path` matches any built-in pattern, deny
   immediately.
2. **Tool deny list** -- If `tool_name` in `denied_tools`, deny.
3. **Tool allow list** -- If `tool_name` in `allowed_tools`, allow.
4. **Path rules** -- If `file_path` matches a deny rule, deny. (Allow rules
   effectively bypass later checks.)
5. **Command deny patterns** -- If `command` matches a deny pattern, deny.
6. **Mode check**:
   - `FULL_AUTO` -> allow
   - Read-only -> allow
   - `PLAN` -> deny (mutating tools blocked)
   - `DEFAULT` -> require confirmation (mutating tools prompt user)

### Read-Only Detection

Tools declare read-only status via the `is_read_only()` method on `BaseTool`:

```python
class ReadFileTool(BaseTool):
    def is_read_only(self, arguments: BaseModel) -> bool:
        return True  # Always read-only

class ExecTool(BaseTool):
    def is_read_only(self, arguments: ExecInput) -> bool:
        return arguments.command.startswith(("ls", "cat", "head", "tail", "grep"))
```

## PermissionSettings Schema

```python
from pydantic import BaseModel, Field
from agent_harness.permissions.modes import PermissionMode

class PathRuleConfig(BaseModel):
    pattern: str     # fnmatch glob pattern
    allow: bool = True  # True = allow, False = deny

class PermissionSettings(BaseModel):
    mode: PermissionMode = PermissionMode.DEFAULT
    allowed_tools: list[str] = Field(default_factory=list)
    denied_tools: list[str] = Field(default_factory=list)
    path_rules: list[PathRuleConfig] = Field(default_factory=list)
    denied_commands: list[str] = Field(default_factory=list)
```

## Code Examples

### Default Mode with Denied Tools

```python
from agent_harness import Harness
from agent_harness.permissions.settings import PermissionSettings
from agent_harness.permissions.modes import PermissionMode

harness = Harness(
    provider=provider,
    tools=["read_file", "write_file", "exec", "web_search"],
    permissions=PermissionSettings(
        mode=PermissionMode.DEFAULT,
        denied_tools=["exec"],
    ),
)
# write_file requires confirmation in DEFAULT mode
# exec is always denied
# read_file and web_search are auto-approved
```

### Plan Mode (Exploration Only)

```python
harness = Harness(
    provider=provider,
    tools=["read_file", "glob", "grep", "list_dir", "web_search"],
    permissions="plan",
)
# All tools auto-approved because they're all read-only
# Adding exec or write_file would silently deny them
```

### Full Auto (CI/Automation)

```python
harness = Harness(
    provider=provider,
    tools=["read_file", "write_file", "exec", "web_search"],
    permissions="full_auto",
    on_error=my_error_handler,
)
# No confirmation prompts -- use only in trusted environments
```

### Custom Tool Check with Remote Auth

```python
async def remote_authorize(tool_name, file_path):
    # Call an external auth service
    async with aiohttp.ClientSession() as session:
        async with session.post(
            "https://auth.internal/check",
            json={"tool": tool_name, "path": file_path},
        ) as resp:
            data = await resp.json()
            return data["allowed"]

async def my_tool_check(tool_name, tool, parsed_args):
    # Built-in sensitive path check still applies
    file_path = getattr(parsed_args, "file_path", None)
    if file_path:
        allowed = await remote_authorize(tool_name, file_path)
        if not allowed:
            return PermissionDecision(allowed=False, reason="Not authorized by remote policy")
    return harness.permissions.evaluate(tool_name, is_read_only=tool.is_read_only(parsed_args))

harness = Harness(
    provider=provider,
    permissions=PermissionSettings(mode=PermissionMode.FULL_AUTO),
    on_tool_check=my_tool_check,
)
```

---

**Prev:** [Memory & Sessions](memory-session.md) | **Next:** [Observability](observability.md)
