# 如何配置权限

## 目标

控制 agent 可以调用哪些工具，以及可以访问哪些文件系统路径，使用权限模式和细粒度的允许/拒绝规则。

## 前置条件

- 可用的 llm-harness 安装
- 了解 harness 配置模型（`HarnessConfig` 或 `PermissionSettings`）

## 分步指南

### 1. 理解权限模型

三层权限控制协同运作，按以下顺序检查：

1. **`SENSITIVE_PATH_PATTERNS`** —— 一组硬编码的 fnmatch 模式，始终拒绝对凭证文件的访问（SSH 密钥、AWS/GCP/Azure 凭证、Docker/Kubernetes 配置等）。这是针对 prompt 注入的纵深防御措施，不可被覆写。
2. **权限模式** —— `DEFAULT`、`FULL_AUTO` 或 `PLAN`，控制对修改型工具的默认允许/拒绝行为。
3. **显式规则** —— 在 `PermissionSettings` 中定义的工具允许/拒绝列表、路径级规则和命令拒绝模式。

关键类型：

| 类型 | 导入 |
|---|---|
| `PermissionMode` | `from llm_harness.core.permissions.modes import PermissionMode` |
| `PermissionSettings` | `from llm_harness.core.permissions.settings import PermissionSettings, PathRuleConfig` |
| `PermissionChecker` | `from llm_harness.core.permissions.checker import PermissionChecker, SENSITIVE_PATH_PATTERNS` |
| `PermissionDecision` | （与 `PermissionChecker` 同模块） |

### 2. 理解权限模式

`PermissionMode` 是包含三个值的枚举：

| 模式 | 行为 |
|---|---|
| `DEFAULT`（默认） | 只读工具可自由运行。修改型工具需要用户确认。 |
| `FULL_AUTO` | 所有工具无需确认即可运行（请谨慎使用）。 |
| `PLAN` | 所有修改型工具被阻止。agent 可以读取和规划，但无法写入、执行或修改任何内容。 |

```python
from llm_harness.core.permissions.modes import PermissionMode

# agent 只能读取文件和制定计划
settings = PermissionSettings(mode=PermissionMode.PLAN)

# agent 无需任何确认提示即可运行
settings = PermissionSettings(mode=PermissionMode.FULL_AUTO)
```

### 3. 配置工具允许和拒绝列表

显式列表优先级高于模式。工具在 `allowed_tools` 中则始终允许，在 `denied_tools` 中则始终阻止：

```python
from llm_harness.core.permissions.settings import PermissionSettings

settings = PermissionSettings(
    mode=PermissionMode.DEFAULT,

    # 这些工具始终被拒绝
    denied_tools=["exec", "web_fetch"],

    # 这些工具始终允许（即使是修改型）
    allowed_tools=["edit_file", "write_file"],
)
```

检查器先评估 `denied_tools`，后评估 `allowed_tools`，因此同时出现在两个列表中的工具将被拒绝。

### 4. 添加路径级规则

使用 `PathRuleConfig` 通过 glob 模式允许或拒绝对文件系统路径的访问：

```python
from llm_harness.core.permissions.settings import PermissionSettings, PathRuleConfig

settings = PermissionSettings(
    path_rules=[
        # 仅允许 /workspace/project 目录树
        PathRuleConfig(pattern="/workspace/project/*", allow=True),
        # 拒绝访问所有位置的 .env 文件
        PathRuleConfig(pattern="**/.env", allow=False),
        # 拒绝访问 node_modules 目录树
        PathRuleConfig(pattern="/workspace/project/node_modules/**", allow=False),
    ],
)
```

路径规则仅在工具参数中提供了 `file_path` 时才会被检查。匹配拒绝规则的路径无论权限模式如何都会被阻止。

### 5. 按模式拒绝命令

使用 `denied_commands` 配合 fnmatch 模式来阻止危险的 shell 命令：

```python
settings = PermissionSettings(
    denied_commands=[
        "rm -rf /*",
        "rm -rf /",
        "dd *",
        ":(){ :|:& };:",  # fork 炸弹
    ],
)
```

命令模式会与工具提供的完整命令字符串进行匹配。

### 6. 以编程方式使用 PermissionChecker

从设置创建 `PermissionChecker`，在运行时评估工具调用：

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

# 检查只读工具
decision = checker.evaluate("read_file", is_read_only=True, file_path="/workspace/readme.md")
print(decision.allowed)   # True（DEFAULT 模式下只读工具允许）

# 检查修改型工具
decision = checker.evaluate("exec", is_read_only=False, command="npm install")
print(decision.allowed)             # False（显式拒绝）
print(decision.reason)              # "exec is explicitly denied"

# 检查敏感路径访问（总是拒绝）
decision = checker.evaluate("read_file", is_read_only=True, file_path="/home/user/.ssh/id_rsa")
print(decision.allowed)   # False（SENSITIVE_PATH_PATTERNS 匹配）
print(decision.reason)    # "Access denied: ... is a sensitive credential path"

# 检查路径规则拒绝
decision = checker.evaluate("write_file", is_read_only=False, file_path="/workspace/secrets.pem")
print(decision.allowed)   # False（匹配 PathRule 拒绝规则）
```

### 7. 敏感路径保护

`SENSITIVE_PATH_PATTERNS` 元组在任何其他规则之前被检查。这些模式匹配凭证文件且不可被覆写：

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

任何带有 `file_path` 且匹配这些模式之一的工具调用，会立即返回 `allowed=False`，无论模式或显式允许规则如何。

### 8. 解读 PermissionDecision

`evaluate` 方法返回一个包含三个字段的 `PermissionDecision` dataclass：

```python
from llm_harness.core.permissions.checker import PermissionDecision

decision: PermissionDecision = checker.evaluate(...)

if decision.allowed:
    # 工具可以立即运行
    pass
elif decision.requires_confirmation:
    # DEFAULT 模式：修改型工具——请求用户批准
    pass
else:
    # 被阻止——显示原因
    print(f"被阻止: {decision.reason}")
```

## 完整示例

```python
from llm_harness.core.permissions.checker import PermissionChecker
from llm_harness.core.permissions.settings import PermissionSettings, PathRuleConfig
from llm_harness.core.permissions.modes import PermissionMode

# 构建设置
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

# 创建检查器
checker = PermissionChecker(settings)

# 测试场景
tests = [
    ("read_file", True, "/workspace/safe/readme.md", None),       # 允许（只读）
    ("exec", False, None, "npm install"),                          # 拒绝（denied_tools）
    ("write_file", False, "/workspace/safe/output.txt", None),     # 需要确认（DEFAULT 模式）
    ("write_file", False, "/workspace/safe/.env", None),           # 拒绝（路径规则）
    ("read_file", True, "/home/user/.ssh/id_ed25519", None),       # 拒绝（敏感路径）
    ("write_file", False, "/etc/passwd", None),                    # 需要确认
]

for tool_name, is_ro, file_path, command in tests:
    d = checker.evaluate(tool_name, is_read_only=is_ro, file_path=file_path, command=command)
    status = "ALLOW" if d.allowed else "DENY" if not d.requires_confirmation else "CONFIRM"
    print(f"{status:7s} | {tool_name:20s} | {d.reason}")
```

## 测试

```python
from llm_harness.core.permissions.checker import PermissionChecker, PermissionDecision
from llm_harness.core.permissions.settings import PermissionSettings, PathRuleConfig
from llm_harness.core.permissions.modes import PermissionMode


def test_default_mode_blocks_mutating_tools():
    settings = PermissionSettings(mode=PermissionMode.DEFAULT)
    checker = PermissionChecker(settings)

    # 只读工具允许
    d = checker.evaluate("read_file", is_read_only=True, file_path="/tmp/test.txt")
    assert d.allowed is True

    # 修改型工具需要确认
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
