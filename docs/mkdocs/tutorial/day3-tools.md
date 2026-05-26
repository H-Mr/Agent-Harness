# Day 3：工具系统 — BaseTool 契约与 ToolRegistry 调度

> **目标读者**：已理解 AgentLoop 的 ReAct 循环和 Provider 抽象层，想深入了解工具系统的设计哲学与实现细节。
> **学完本节后，你应该能回答**：BaseTool 为什么用 ClassVar 定义 name/description/input_model？ToolRegistry 不依赖任何基类是怎么做到的？`build_tools_from_config` 如何过滤不需要的工具？沙箱执行和非沙箱执行在哪个分叉点分开？

---

## 一、深度解释

### 1.1 BaseTool 最小契约：一个工具类的全部职责

先看 `src/agent_harness/tools/base.py` 中的 `BaseTool` 定义。它是一个 ABC（抽象基类），但只强制要求一个抽象方法：`execute`。其余所有成员要么是 ClassVar，要么有默认实现。

```python
class BaseTool(ABC):
    name: ClassVar[str]
    description: ClassVar[str]
    input_model: ClassVar[type[BaseModel]]

    @abstractmethod
    async def execute(self, arguments: BaseModel, context: ToolExecutionContext) -> ToolResult:
        """Execute the tool."""

    def is_read_only(self, arguments: BaseModel) -> bool:
        """Return whether the invocation is read-only."""
        del arguments
        return False

    def to_api_schema(self, api_format: str = "anthropic") -> dict[str, Any]:
        ...
```

最小契约只有三要素 + 一个方法：

1. **`name`** — 工具名称，也是 ToolRegistry 中的查找键。用 `ClassVar[str]` 声明表示这是类级别的常量，所有实例共享。语言模型通过这个名字来调用工具。
2. **`description`** — 工具的自然语言描述，直接嵌入 LLM 的 system prompt 中的 tools 字段。描述质量决定了 LLM 是否会在合适的场景调用该工具。
3. **`input_model`** — 一个 Pydantic `BaseModel` 子类，这是整个设计中最关键的选择。为什么用 Pydantic？一是 `model_json_schema()` 可以直接输出 JSON Schema 送给 LLM 的 tool_use / tool_calls API；二是在 `execute` 方法中，`arguments` 参数已经被 Pydantic 校验过类型、默认值、约束（比如 `ge=1`），execute 内部完全无需再处理脏数据。
4. **`execute`** — 唯一抽象方法，接收 `arguments: BaseModel` 和 `context: ToolExecutionContext`，返回 `ToolResult`。

`is_read_only` 和 `to_api_schema` 是可选的扩展点。`is_read_only` 让调度器可以在只读模式下跳过所有写工具的权限审批；`to_api_schema` 支持 `anthropic` 和 `openai` 两种格式，让同一套工具定义可以无痛切换 LLM Provider。

**核心设计决策：为什么把 input_model 定义为 ClassVar 而非实例属性？**

对比两种方案：
- 实例属性：每个工具实例都可以有自己独立的 input_model 类型，灵活性更高但运行时类型检查复杂。
- ClassVar：一个工具类绑定一个固定的 input_model，代码更简单、Schema 生成可以缓存、序列化更直接。

agent-harness 选择了 ClassVar 方案。这意味着一类工具只有一个 input_model，不可在运行时替换。如果你需要不同的参数结构，你需要定义一个新的工具类。这个取舍换来的是 `to_api_schema()` 可以在不实例化工具的情况下工作——虽然当前实现是通过实例调用，但 ClassVar 的设计保留了类级别调用的可能性。

### 1.2 ToolRegistry 的注册表模式

`ToolRegistry` 是一个轻量级容器，本质就是 `dict[str, BaseTool]` 的封装：

```python
class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> BaseTool | None:
        return self._tools.get(name)

    def list_tools(self) -> list[BaseTool]:
        return list(self._tools.values())

    def to_api_schema(self, api_format: str = "anthropic") -> list[dict[str, Any]]:
        return [tool.to_api_schema(api_format=api_format) for tool in self._tools.values()]
```

**为什么不需要接口或基类？**

注意看 `register` 方法——它接受 `BaseTool` 类型提示，但实际上 Python 的 duck typing 在这里也能工作。一个对象只需要有 `name`、`description`、`input_model`、`execute`、`is_read_only`、`to_api_schema` 这些属性和方法就能被注册。ToolRegistry 不调用任何 `BaseTool` 特有的方法，它只是存储和转发。

这也意味着你可以为一个已有的类加上 `name`/`input_model`/`execute` 就能让它成为"工具"，而不需要继承 BaseTool。这是一个极简主义的设计：契约由约定定义，而不是由继承树强制。

### 1.3 ToolResult 不可变设计与 ToolExecutionContext

```python
@dataclass(frozen=True)
class ToolResult:
    output: str
    is_error: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)
```

`frozen=True` 意味着一旦创建就不能修改。这个设计决策的原因有二：

- **保证确定性**：工具执行的输出在生成后不应被篡改。AgentLoop、权限系统、Trackers 都会读取 ToolResult，但它们都不应该修改它。
- **线程安全**：即使工具执行是异步的（asyncio），frozen 实例天然不可变，不会被并发访问破坏。

注意 `output` 是 `str` 类型——所有工具输出最终都被序列化为字符串。即使是图片，也以 JSON 格式编码在字符串中。

`ToolExecutionContext` 是另外一个 dataclass：

```python
@dataclass
class ToolExecutionContext:
    cwd: Path
    metadata: dict[str, Any] = field(default_factory=dict)
```

这个对象的职责是**携带执行时的上下文信息**，而不是工具本身的配置。最重要的字段是 `cwd`——当前工作目录。GlobTool 和 GrepTool 依赖 `context.cwd` 来解析相对路径（它们不像文件系统工具那样持有 workspace 引用）。`metadata` 是一个灵活的信息通道，可以用来传递 session_id、request_id 等追踪信息。

**为什么需要 `ToolExecutionContext` 而不是直接用全局变量？**

考虑一个场景：同一个 Agent 在处理两个用户的请求，两个请求分别在 `/project-a` 和 `/project-b` 工作。如果没有 context 注入，GlobTool 只能使用其构造函数中固定的工作目录。通过每次 execute 调用传入 `ToolExecutionContext(cwd=...)`，工具执行的上下文和执行逻辑被解耦。

### 1.4 工具分类体系

agent-harness 内置了五类工具，每一类对应不同的安全粒度：

| 类别 | 代表工具 | 安全机制 | 是否只读 |
|------|----------|----------|----------|
| 文件操作 | ReadFileTool, WriteFileTool, EditFileTool, ListDirTool | workspace 限制 + `_resolve_path` | 读写/只读 |
| 搜索 | GlobTool, GrepTool | cwd 限制 | 只读 |
| 执行 | ExecTool | deny/allow 模式 + 沙箱 | 读写 |
| 网络 | WebSearchTool, WebFetchTool | SSRF 防护 | 只读 |
| Agent | SpawnTool | SubagentManager | 读写 |

**文件操作工具**通过 `_FsTool` 基类共享 `_resolve_path` 逻辑：如果 `allowed_dir` 设置了（即 `restrict_to_workspace=True`），任何试图读取该目录外的文件都会抛出 `PermissionError`。

**搜索工具**（Glob/Grep）不持有 workspace 引用，而是依赖 `context.cwd`。这意味着它们的"根"由调用者通过 ToolExecutionContext 决定，更加灵活。

**执行工具**（ExecTool）是最敏感的工具。它的安全模型是三层：deny 模式列表（阻止已知的危险命令如 `rm -rf`）、allow 模式列表（只在白名单内的命令被允许）、以及可选的沙箱隔离（通过 `srt` 提供 OS 级网络/文件系统隔离）。

**网络工具** 的 SSRF 防护在 WebFetchTool 中，通过 `_validate_url_safe` 检查目标 URL 的域名是否指向私有 IP。

**Agent 工具**（SpawnTool）允许 Agent 在后台派生子 Agent。它需要一个 `SubagentManager` 实例来管理生命周期，因此在 builder 中默认返回 None，由应用层注册。

### 1.5 build_tools_from_config 工厂模式

`src/agent_harness/tools/builder.py` 中的 `build_tools_from_config` 是整个工具系统的装配入口。核心结构是一个**工厂注册表** `_TOOL_REGISTRY`：

```python
_TOOL_REGISTRY: dict[str, Any] = {}

def _register_all() -> None:
    _TOOL_REGISTRY.update({
        "read_file":     _fs_tool(ReadFileTool),
        "write_file":    _fs_tool(WriteFileTool),
        "exec":          lambda ws, cfg: _exec(cfg, ws),
        "web_search":    lambda ws, cfg: _web_search(cfg),
        "skill":         _no_args(lambda: ...),
        "spawn":         lambda ws, cfg: None,  # 需要运行时注入
        ...
    })
```

每个工厂是一个 `(workspace, config) -> BaseTool | None` 的函数。有些工具需要从 config 中读取参数（如 `exec_timeout`），有些需要 `workspace` 路径（如文件工具），有些运行时才能决定是否启用（如 spawn 需要 SubagentManager）。

`_is_enabled` 函数执行配置过滤。ToolsConfig 的 `enabled`/`disabled` 列表支持三种模式：
- `"*"` — 启用所有工具（默认）
- `"none"` — 禁用所有工具
- 具体名称列表 — 只启用/禁用指定的工具

禁用优先于启用：如果一个工具同时出现在 `enabled` 和 `disabled` 列表中，它将被禁用。

工厂返回 `None` 的工具（如 spawn、cron 系列）不会注册到 registry 中。这些工具需要应用层在构建完成后手动创建并注册。这种设计让工具系统对核心库来说是自包含的，而不必依赖 `SubagentManager`、`CronService` 等上层组件。

---

## 二、源码导读

### 2.1 `tools/base.py` — 完整契约（60 行）

整个文件只有 111 行，是所有工具的基石。核心流程：

1. `ToolExecutionContext` — 每次 execute 调用时携带的 mutable 上下文。最重要的字段是 `cwd: Path`，让工具可以知道"当前在哪里"。
2. `ToolResult` — `frozen=True` 的 immutable dataclass。`output: str` 是唯一必填字段。`is_error: bool` 告诉调用者执行是否失败。`metadata` 存储附加数据。
3. `BaseTool` — 四个 ClassVar 声明（`name`, `description`, `input_model`），一个抽象方法 `execute`，一个可选方法 `is_read_only`（默认返回 False），两个 Schema 输出方法 `to_api_schema` 和 `to_openai_schema`。
4. `ToolRegistry` — `_tools: dict[str, BaseTool]` 的封装，提供 `register`/`get`/`has`/`list_tools`/`to_api_schema` 接口。

注意 `to_api_schema` 的默认实现直接调用了 `self.input_model.model_json_schema()`——这是 Pydantic v2 的方法，将 Pydantic 模型转换成 JSON Schema。

### 2.2 `tools/filesystem.py` — ReadFileTool 的图片检测

ReadFileTool 在读取文件时做了两项超越"读文件"本身的工作：

1. **图片检测**：`detect_image_mime` 通过检查文件的 magic bytes 来判断是否是 PNG/JPEG/GIF/WebP。如果是图片，不会返回文本，而是返回一个 JSON 数组，其中包含 `image_url` 格式的图像块。这允许 LLM 直接"看到"图片内容，而不是看到乱码的二进制数据。
2. **Workspace 限制**：`_resolve_path` 函数检查解析后的路径是否在 `allowed_dir` 下。这是文件系统安全的基石。

```python
def _resolve_path(path, workspace=None, allowed_dir=None, extra_allowed_dirs=None) -> Path:
    p = Path(path).expanduser()
    if not p.is_absolute() and workspace:
        p = workspace / p
    resolved = p.resolve()
    if allowed_dir:
        all_dirs = [allowed_dir] + (extra_allowed_dirs or [])
        if not any(_is_under(resolved, d) for d in all_dirs):
            raise PermissionError(f"Path {path} is outside allowed directory {allowed_dir}")
    return resolved
```

`_is_under` 使用了 `Path.relative_to` 的异常捕获模式——如果能计算出相对路径，说明目标路径在 permitted 目录下。

EditFileTool 有一个巧妙的设计：`_find_match` 方法不只是做简单的字符串替换。如果精确匹配失败，它会尝试 trimmed（去除前后空白的）行匹配和滑动窗口匹配，这使得即使缩进不一致也能定位到目标文本。

### 2.3 `tools/shell.py` — ExecTool 的沙箱分支

ExecTool 的 execute 方法在安全检查和超时之后，进入一个关键的分叉点：

```python
if self.sandbox_enabled:
    return await self._execute_sandboxed(arguments.command, cwd, effective_timeout, env)

return await self._execute_plain(arguments.command, cwd, effective_timeout, env)
```

非沙箱路径：直接调用 `asyncio.create_subprocess_shell(command, ...)`。这是普通的子进程执行。

沙箱路径：通过 `wrap_command_for_sandbox` 将命令包装成 `srt`（sandbox-runtime）命令。`srt` 是一个 OS 级别的隔离工具，可以限制网络访问和文件系统读写。`wrap_command_for_sandbox` 会生成一个临时的配置文件（包含 `sandbox_config` 中的网络和文件系统规则），然后返回包装后的 argv 列表和配置文件路径。

安全层汇总：
- 第 1 层：deny 模式列表。硬编码的危险命令，不可绕过。
- 第 2 层：allow 模式列表。若设置了，只允许匹配的命令。
- 第 3 层：内部 URL 检测。`contains_internal_url` 通过正则检查命令中是否包含指向 `localhost` 或私有 IP 的 URL。
- 第 4 层：workspace 路径限制。如果设置了 `restrict_to_workspace`，提取命令中的所有绝对路径，检查它们是否在 workspace 下。
- 第 5 层（可选）：沙箱。如果启用了 `srt`，所有命令都在 OS 级别的隔离环境中运行。

`_wait_process` 方法还有一个细节：输出采用 head+tail 截断策略（保留开头和结尾，截断中间），这比简单地截掉尾部更友好，因为错误信息通常在输出的末尾。

### 2.4 `tools/builder.py` — 工厂注册表

`_TOOL_REGISTRY` 是一个 lazy 初始化（`_register_all` 在第一次调用 `build_tools_from_config` 时填充）的 dict。每个工具对应一个 factory 函数 `(workspace, config) -> BaseTool | None`。

三种工厂模式：
- `_no_args(cls)` — 工具不需要任何参数，直接实例化：`GlobTool()`
- `_fs_tool(cls)` — 文件系统工具需要 workspace 和 allowed_dir
- 匿名 lambda — 需要从 config 中提取参数，如 `_exec(cfg, ws)` 需要读取 `cfg.exec_enable` 来决定是否返回 None

需要运行时注入的工具（spawn、message、cron 系列）直接返回 None，由应用层手动注册。

### 2.5 `tools/web.py` — SSRF 防护

WebFetchTool 的 SSRF 防护分三层：

1. **预检**：`_validate_url_safe` 在发起 HTTP 请求前检查 URL 的 scheme（仅 http/https）和 hostname（不能是私有 IP 或 localhost）。
2. **重定向检查**：`_validate_resolved_url` 在每次重定向后检查目标 URL。如果中间人攻击将请求重定向到内部地址，这个检查会拦截。
3. **IP 校验**：`_check_private_ip` 不做 DNS 解析（避免 SSRF 攻击面本身），只对 IP 字面量进行模式匹配。

---

## 三、动手练习：实现 WordCountTool

让我们实现一个自定义工具，统计文件中行数、字数、字符数，并注册到 builder。

### 3.1 实现工具类

在 `src/agent_harness/tools/` 下新建 `word_count_tool.py`：

```python
"""Word count tool: count lines, words, and characters in a file."""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

from pydantic import BaseModel, Field

from agent_harness.tools.base import BaseTool, ToolExecutionContext, ToolResult


class WordCountInput(BaseModel):
    path: str = Field(description="The file path to count")
    encoding: str = Field(default="utf-8", description="File encoding")


class WordCountTool(BaseTool):
    """Count lines, words, and characters in a file."""

    name: ClassVar[str] = "word_count"
    description: ClassVar[str] = (
        "Count the number of lines, words, characters, and bytes in a file. "
        "Returns a structured breakdown."
    )
    input_model: ClassVar[type[BaseModel]] = WordCountInput

    def __init__(self, workspace: Path | None = None, allowed_dir: Path | None = None):
        self._workspace = workspace
        self._allowed_dir = allowed_dir

    def _resolve(self, path: str) -> Path:
        p = Path(path).expanduser()
        if not p.is_absolute() and self._workspace:
            p = self._workspace / p
        resolved = p.resolve()
        if self._allowed_dir:
            try:
                resolved.relative_to(self._allowed_dir)
            except ValueError:
                return Path("")  # 标记越界
        return resolved

    def is_read_only(self, arguments: WordCountInput) -> bool:
        return True

    async def execute(self, arguments: WordCountInput, context: ToolExecutionContext) -> ToolResult:
        fp = self._resolve(arguments.path)
        if not fp or not fp.exists():
            return ToolResult(output=f"Error: File not found: {arguments.path}", is_error=True)
        if not fp.is_file():
            return ToolResult(output=f"Error: Not a file: {arguments.path}", is_error=True)

        try:
            text = fp.read_text(encoding=arguments.encoding)
        except UnicodeDecodeError as e:
            return ToolResult(output=f"Error: Cannot decode file: {e}", is_error=True)
        except Exception as e:
            return ToolResult(output=f"Error reading file: {e}", is_error=True)

        lines = text.splitlines()
        line_count = len(lines)
        word_count = sum(len(line.split()) for line in lines)
        char_count = len(text)
        byte_count = fp.stat().st_size

        result = (
            f"File: {arguments.path}\n"
            f"  Lines:      {line_count}\n"
            f"  Words:      {word_count}\n"
            f"  Characters: {char_count}\n"
            f"  Bytes:      {byte_count}"
        )
        return ToolResult(output=result)
```

### 3.2 注册到 Builder

在 `src/agent_harness/tools/builder.py` 中添加注册：

```python
# 在 _register_all 函数的 _TOOL_REGISTRY.update 调用中加入：
_TOOL_REGISTRY.update({
    # ... 已有工具 ...
    "word_count": _fs_tool(WordCountTool),
})
```

并在文件顶部加入 import：

```python
from agent_harness.tools.word_count_tool import WordCountTool
```

注意 `word_count` 使用的是 `_fs_tool` 工厂，因为它和文件系统工具一样需要 workspace 和 allowed_dir 参数。

### 3.3 编写测试

新建 `tests/test_word_count_tool.py`：

```python
"""Tests for WordCountTool."""

import tempfile
from pathlib import Path

import pytest

from agent_harness.tools.base import ToolExecutionContext, ToolResult
from agent_harness.tools.word_count_tool import WordCountTool, WordCountInput


@pytest.fixture
def sample_file():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8") as f:
        f.write("Hello world\nThis is line two\nLine three\n")
        path = f.name
    yield Path(path)
    Path(path).unlink(missing_ok=True)


@pytest.fixture
def tool():
    return WordCountTool(allowed_dir=Path("/"))


@pytest.mark.asyncio
async def test_word_count_basic(tool, sample_file):
    ctx = ToolExecutionContext(cwd=Path("/"))
    result = await tool.execute(WordCountInput(path=str(sample_file)), ctx)
    assert not result.is_error
    assert "Lines:      3" in result.output
    assert "Words:      7" in result.output  # "Hello world"(2) + "This is line two"(4) + "Line three"(1) = 7


@pytest.mark.asyncio
async def test_word_count_file_not_found(tool):
    ctx = ToolExecutionContext(cwd=Path("/"))
    result = await tool.execute(WordCountInput(path="/nonexistent/file.txt"), ctx)
    assert result.is_error
    assert "not found" in result.output


@pytest.mark.asyncio
async def test_word_count_empty_file(tool):
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8") as f:
        path = f.name
    try:
        ctx = ToolExecutionContext(cwd=Path("/"))
        result = await tool.execute(WordCountInput(path=path), ctx)
        assert not result.is_error
        assert "Lines:      0" in result.output
        assert "Words:      0" in result.output
    finally:
        Path(path).unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_word_count_is_read_only(tool):
    assert tool.is_read_only(WordCountInput(path="dummy"))
```

运行测试：

```bash
cd E:/work-space/agent-harness
python -m pytest tests/test_word_count_tool.py -v
```

通过 `build_tools_from_config` 使用的验证：

```python
from agent_harness.config.schema import ToolsConfig
from agent_harness.tools.builder import build_tools_from_config

config = ToolsConfig()
registry = build_tools_from_config(config, workspace="/tmp/test")
assert registry.has("word_count"), "word_count should be registered"

wc_tool = registry.get("word_count")
assert wc_tool is not None
assert wc_tool.name == "word_count"
```

通过这个练习，你经历了一个工具从定义到注册到使用的完整生命周期，这也是所有内置工具创建时走过的相同路径。
