# How to Configure Permissions

## Goal

Control which tools the agent may invoke and which filesystem paths it may access, using permission modes and granular allow/deny rules.

## Prerequisites

- Working llm-harness installation
- Understanding of the harness config model (`HarnessConfig` or `PermissionSettings`)

## Step by Step

### 1. Understand the Permission Model

Three layers of permission control operate together, checked in this order:

1. **`SENSITIVE_PATH_PATTERNS`** -- a hard-coded tuple of fnmatch patterns that always deny access to credential files (SSH keys, AWS/GCP/Azure credentials, Docker/Kubernetes configs, etc.). This is a defence-in-depth measure against prompt injection and cannot be overridden.
2. **Permission mode** -- `DEFAULT`, `FULL_AUTO`, or `PLAN`, which controls the default allow/deny behavior for mutating tools.
3. **Explicit rules** -- tool allow/deny lists, path-level rules, and command deny patterns defined in `PermissionSettings`.

Key types:

| Type | Import |
|---|---|
| `PermissionMode` | `from llm_harness.core.permissions.modes import PermissionMode` |
| `PermissionSettings` | `from llm_harness.core.permissions.settings import PermissionSettings, PathRuleConfig` |
| `PermissionChecker` | `from llm_harness.core.permissions.checker import PermissionChecker, SENSITIVE_PATH_PATTERNS` |
| `PermissionDecision` | (same module as `PermissionChecker`) |

### 2. Understand Permission Modes

`PermissionMode` is an enum with three values:

| Mode | Behavior |
|---|---|
| `DEFAULT` (default) | Read-only tools run freely. Mutating tools require user confirmation. |
| `FULL_AUTO` | All tools run without confirmation (use with caution). |
| `PLAN` | All mutating tools are blocked. The agent can read and plan but cannot write, execute, or modify anything. |

```python
from llm_harness.core.permissions.modes import PermissionMode

# The agent may only read files and make plans
settings = PermissionSettings(mode=PermissionMode.PLAN)

# The agent runs without any confirmation prompts
settings = PermissionSettings(mode=PermissionMode.FULL_AUTO)
```

### 3. Configure Tool Allow and Deny Lists

Explicit lists take priority over the mode. If a tool is in `allowed_tools` it is always permitted. If it is in `denied_tools` it is always blocked:

```python
from llm_harness.core.permissions.settings import PermissionSettings

settings = PermissionSettings(
    mode=PermissionMode.DEFAULT,

    # These tools are always denied
    denied_tools=["exec", "web_fetch"],

    # These tools are always allowed (even if mutating)
    allowed_tools=["edit_file", "write_file"],
)
```

The checker evaluates `denied_tools` before `allowed_tools`, so a tool in both lists will be denied.

### 4. Add Path-Level Rules

Use `PathRuleConfig` to allow or deny access to filesystem paths using glob patterns:

```python
from llm_harness.core.permissions.settings import PermissionSettings, PathRuleConfig

settings = PermissionSettings(
    path_rules=[
        # Allow only the /workspace/project directory tree
        PathRuleConfig(pattern="/workspace/project/*", allow=True),
        # Deny access to .env files everywhere
        PathRuleConfig(pattern="**/.env", allow=False),
        # Deny access to the node_modules tree
        PathRuleConfig(pattern="/workspace/project/node_modules/**", allow=False),
    ],
)
```

Path rules are checked only when the tool provides a `file_path` in its arguments. A path matching a deny rule is blocked regardless of the permission mode.

### 5. Deny Commands by Pattern

Prevent dangerous shell commands using `denied_commands` with fnmatch patterns:

```python
settings = PermissionSettings(
    denied_commands=[
        "rm -rf /*",
        "rm -rf /",
        "dd *",
        ":(){ :|:& };:",  # fork bomb
    ],
)
```

Command patterns are matched against the full command string provided by the tool.

### 6. Use PermissionChecker Programmatically

Create a `PermissionChecker` from settings and evaluate tool invocations at runtime:

```python
from pathlib import Path
from llm_harness.core.permissions.checker import PermissionChecker, SENSITIVE_PATH_PATTERNS
from llm_harness.core.permissions.settings import PermissionSettings, PathRuleConfig
from llm_harness.core.permissions.modes import PermissionMode

settings = PermissionSettings(
    mode=PermissionMode.DEFAULT,
    denied_tools=["exec"],
    path_rules=[PathRuleConfig(pattern="**/*.pem", allow=False)],
)
checker = PermissionChecker(settings)

# Check a read-only tool
decision = checker.evaluate("read_file", is_read_only=True, file_path="/workspace/readme.md")
print(decision.allowed)   # True (read-only tools are allowed in DEFAULT mode)

# Check a mutating tool
decision = checker.evaluate("exec", is_read_only=False, command="npm install")
print(decision.allowed)             # False (explicit deny)
print(decision.reason)              # "exec is explicitly denied"

# Check sensitive path access (always denied)
decision = checker.evaluate("read_file", is_read_only=True, file_path="/home/user/.ssh/id_rsa")
print(decision.allowed)   # False (SENSITIVE_PATH_PATTERNS match)
print(decision.reason)    # "Access denied: ... is a sensitive credential path"

# Check path rule deny
decision = checker.evaluate("write_file", is_read_only=False, file_path="/workspace/secrets.pem")
print(decision.allowed)   # False (matches PathRule deny)
```

### 7. Sensitive Path Protection

The `SENSITIVE_PATH_PATTERNS` tuple is checked before any other rule. These patterns match credential files and cannot be overridden:

```python
from llm_harness.core.permissions.checker import SENSITIVE_PATH_PATTERNS

for pattern in SENSITIVE_PATH_PATTERNS:
    print(pattern)
# */.ssh/*
# */.aws/credentials
# */.aws/config
# */.config/gcloud/*
# */.azure/*
# */.gnupg/*
# */.docker/config.json
# */.kube/config
# */.agent-harness/credentials.json
# */.agent-harness/copilot_auth.json
```

Any tool invocation with a `file_path` matching one of these patterns returns `allowed=False` immediately, regardless of mode or explicit allow rules.

### 8. Interpret PermissionDecision

The `evaluate` method returns a `PermissionDecision` dataclass with three fields:

```python
from llm_harness.core.permissions.checker import PermissionDecision

decision: PermissionDecision = checker.evaluate(...)

if decision.allowed:
    # Tool may run immediately
    pass
elif decision.requires_confirmation:
    # DEFAULT mode: mutating tool -- ask the user for approval
    pass
else:
    # Blocked -- show the reason
    print(f"Blocked: {decision.reason}")
```

## Complete Example

```python
from llm_harness.core.permissions.checker import PermissionChecker
from llm_harness.core.permissions.settings import PermissionSettings, PathRuleConfig
from llm_harness.core.permissions.modes import PermissionMode

# Build settings
settings = PermissionSettings(
    mode=PermissionMode.DEFAULT,
    allowed_tools=["read_file", "glob", "grep"],
    denied_tools=["exec", "web_fetch"],
    path_rules=[
        PathRuleConfig(pattern="/workspace/safe/**", allow=True),
        PathRuleConfig(pattern="/workspace/safe/.env", allow=False),
    ],
    denied_commands=["rm -rf *", "shutdown *"],
)

# Create checker
checker = PermissionChecker(settings)

# Test scenarios
tests = [
    ("read_file", True, "/workspace/safe/readme.md", None),       # allowed (read-only)
    ("exec", False, None, "npm install"),                          # denied (denied_tools)
    ("write_file", False, "/workspace/safe/output.txt", None),     # requires confirmation (DEFAULT mode)
    ("write_file", False, "/workspace/safe/.env", None),           # denied (path rule)
    ("read_file", True, "/home/user/.ssh/id_ed25519", None),       # denied (sensitive path)
    ("write_file", False, "/etc/passwd", None),                    # requires confirmation
]

for tool_name, is_ro, file_path, command in tests:
    d = checker.evaluate(tool_name, is_read_only=is_ro, file_path=file_path, command=command)
    status = "ALLOW" if d.allowed else "DENY" if not d.requires_confirmation else "CONFIRM"
    print(f"{status:7s} | {tool_name:20s} | {d.reason}")
```

## Testing

```python
from llm_harness.core.permissions.checker import PermissionChecker, PermissionDecision
from llm_harness.core.permissions.settings import PermissionSettings, PathRuleConfig
from llm_harness.core.permissions.modes import PermissionMode


def test_default_mode_blocks_mutating_tools():
    settings = PermissionSettings(mode=PermissionMode.DEFAULT)
    checker = PermissionChecker(settings)

    # Read-only tools allowed
    d = checker.evaluate("read_file", is_read_only=True, file_path="/tmp/test.txt")
    assert d.allowed is True

    # Mutating tools require confirmation
    d = checker.evaluate("exec", is_read_only=False, command="echo hello")
    assert d.allowed is False
    assert d.requires_confirmation is True


def test_full_auto_allows_all():
    settings = PermissionSettings(mode=PermissionMode.FULL_AUTO)
    checker = PermissionChecker(settings)

    d = checker.evaluate("exec", is_read_only=False)
    assert d.allowed is True


def test_plan_blocks_mutating():
    settings = PermissionSettings(mode=PermissionMode.PLAN)
    checker = PermissionChecker(settings)

    d = checker.evaluate("write_file", is_read_only=False)
    assert d.allowed is False
    assert "Plan mode" in d.reason


def test_denied_tools():
    settings = PermissionSettings(mode=PermissionMode.FULL_AUTO, denied_tools=["exec"])
    checker = PermissionChecker(settings)

    d = checker.evaluate("exec", is_read_only=False)
    assert d.allowed is False
    assert "explicitly denied" in d.reason


def test_sensitive_path_patterns():
    settings = PermissionSettings(mode=PermissionMode.FULL_AUTO)
    checker = PermissionChecker(settings)

    d = checker.evaluate("read_file", is_read_only=True, file_path="/home/user/.ssh/authorized_keys")
    assert d.allowed is False
    assert "sensitive credential path" in d.reason


def test_path_rules():
    settings = PermissionSettings(
        mode=PermissionMode.FULL_AUTO,
        path_rules=[PathRuleConfig(pattern="**/secrets/*", allow=False)],
    )
    checker = PermissionChecker(settings)

    d = checker.evaluate("read_file", is_read_only=True, file_path="/workspace/secrets/key.txt")
    assert d.allowed is False
    assert "matches deny rule" in d.reason

    d = checker.evaluate("read_file", is_read_only=True, file_path="/workspace/public/readme.md")
    assert d.allowed is True
```
