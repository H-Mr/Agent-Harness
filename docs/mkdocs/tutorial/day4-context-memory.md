# Day 4：上下文、记忆与会话

> **目标读者**：已理解工具系统的 BaseTool 契约和 ToolRegistry 调度，想深入了解系统提示组装、记忆持久化和会话管理的架构设计。
> **学完本节后，你应该能回答**：SectionProvider 的 priority 如何决定 prompt 顺序？MemoryStore 为什么坚持只追加不修改？Session._find_legal_start 解决了什么问题？MemoryConsolidator 在什么条件下触发压缩？

---

## 一、深度解释

### 1.1 ContextBuilder 的 SectionProvider 插件机制

当 AgentLoop 需要调用 LLM 时，它必须先将当前状态组装成一段 system prompt。在 `agent-harness` 中，这段 system prompt 不是手写的固定文本，而是由多个**互不感知对方的 SectionProvider 插件**动态拼装而成。

看 `src/agent_harness/context/base.py` 中的定义：

```python
class SectionProvider(ABC):
    @property
    @abstractmethod
    def section_name(self) -> str:
        """Unique name for dedup and ordering."""

    @abstractmethod
    async def get_section(self) -> str:
        """Return the markdown section content."""

    @property
    def priority(self) -> int:
        """Lower = earlier in the prompt. Default 100."""
        return 100
```

三个约定：
1. **`section_name`** — 唯一的 section 标识符。也正是基于 `section_name` 的字典去重：ContextBuilder 内部使用 `dict[str, SectionProvider]` 存储，同名的后注册者会覆盖先注册者。这让应用层可以替换内置的 section。
2. **`get_section`** — 返回 markdown 格式的 section 内容。如果返回空字符串或纯空白，该 section 不会出现在最终 prompt 中。
3. **`priority`** — 决定了 section 在 prompt 中的排列顺序。值越小越靠前。默认 100。

ContextBuilder 的 `build_system_prompt` 方法负责组装：

```python
async def build_system_prompt(self) -> str:
    sorted_providers = sorted(
        self._providers.values(), key=lambda p: p.priority
    )
    parts: list[str] = []
    for provider in sorted_providers:
        section = await provider.get_section()
        if section.strip():
            parts.append(section)
    return "\n\n---\n\n".join(parts)
```

所有 section 按 priority 排序，去空白、用 `---` 分隔拼装成一个完整的 system prompt。

**为什么不用模板字符串拼接？**

模板字符串方案（如 Jinja2）的问题在于：每一段 prompt 之间有隐式的依赖关系，修改一个段可能破坏整个模板。SectionProvider 方案让每段 prompt 拥有独立的生命周期——`EnvironmentSection` 不知道 `SkillsSection` 的存在，`IdentitySection` 不知道 `MemorySection` 的优先级。组件之间通过 `priority` 在 prompt 空间中排序，而不是通过硬编码的模板位置。

这也让第三方扩展变得极其简单：实现 `SectionProvider`，调用 `context_builder.add_provider(MySection())`，你的内容就会自动出现在系统提示中。

### 1.2 内置 SectionProvider 的优先级谱系

看看 `src/agent_harness/prompts/sections.py` 中五个内置 provider 的 priority：

| Provider | priority | section_name | 内容 |
|----------|----------|--------------|------|
| EnvironmentSection | 5 | environment | OS、平台、Shell、工作目录、Git 分支 |
| IdentitySection | 10 | identity | Agent 身份定义文本 |
| AgentsMDSection | 20 | project_instructions | 项目 AGENTS.md 指令 |
| SkillsSection | 30 | skills | 可用 Skill 列表 |
| MemorySection | 40 | memory | 长期记忆摘要 |

优先级的层次设计遵循了**从不变到多变**的原则：

1. **EnvironmentSection（5）** — 运行时环境信息，每次请求都可能变化。放在最前面，让 LLM 第一时间知道"你在哪里"。
2. **IdentitySection（10）** — Agent 身份定义，通常在项目启动时固定。告诉 LLM "你是谁"。
3. **AgentsMDSection（20）** — 项目提供的 AGENTS.md 指令，可能在 git pull 时变化。告诉 LLM "项目规则是什么"。
4. **SkillsSection（30）** — 可用技能列表，随 `skill_registry` 变化。
5. **MemorySection（40）** — 长期记忆，随会话进展而积累。放在最后，因为它通常最长且最具体。

EnvironmentSection 的数据来源是 `get_environment_info`（`prompts/environment.py`）。它运行 `git rev-parse` 检测当前 git 分支、读取环境变量检测 shell、调用 `platform` 模块获取 OS 和 Python 版本。

### 1.3 MemoryStore 的两层设计

`src/agent_harness/memory/store.py` 实现了最简单的两层记忆架构：

```
memory/
  MEMORY.md    — 长期记忆，可覆盖写入
  HISTORY.md   — 追加日志，只增不减
```

**为什么 MEMORY.md 是可覆盖的？**

长期记忆是一个"快照"。当 MemoryConsolidator 对一段对话执行压缩时，它调用 LLM 生成新的 memory_update，然后用 `write_long_term` 完全覆盖旧的 MEMORY.md 内容。这是有意为之——长期记忆应该反映"截止当前时刻你所知道的事实摘要"，而不是历史版本的累积。如果 LLM 认为某个旧事实已经不相关了，它可以被直接删除。

**为什么 HISTORY.md 只追加不修改？**

历史日志的用途不同。它设计为可 grep 搜索的日志文件，每当 Agent 决策或发现重要信息时，都会追加一行 `[timestamp] 描述`。HISTORY.md 的消费者不是 LLM（太长了），而是人类开发者或调试工具。追加日志保证：
- 写操作是原子的（open with `"a"` mode）
- 不需要加锁
- 永远不会破坏已有数据
- 可以用 `grep` / `tail` 等标准 Unix 工具读取

```python
def append_history(self, entry: str) -> None:
    with open(self.history_file, "a", encoding="utf-8") as f:
        f.write(entry.rstrip() + "\n\n")

def write_long_term(self, content: str) -> None:
    self.memory_file.write_text(content, encoding="utf-8")
```

注意 `write_long_term` 是覆盖写入，`append_history` 是追加写入。它们的文件操作语义与它们的数据语义完全一致。

### 1.4 MemoryConsolidator 的触发条件

`src/agent_harness/memory/consolidator.py` 中的 `MemoryConsolidator` 负责判断"什么时候该压缩"。

核心方法是 `maybe_consolidate_by_tokens`：

```python
async def maybe_consolidate_by_tokens(self, session: Session) -> None:
    budget = self.context_window_tokens - self.max_completion_tokens - self._SAFETY_BUFFER
    target = budget // 2
    estimated, source = await self.estimate_session_prompt_tokens(session)
    if estimated < budget:
        return  # 没有超出预算，跳过

    for round_num in range(self._MAX_CONSOLIDATION_ROUNDS):
        if estimated <= target:
            return
        boundary = self.pick_consolidation_boundary(session, max(1, estimated - target))
        ...
```

触发条件不是固定的消息数，而是**估算 token 数**。当当前 session 的 prompt 总 token 数逼近上下文窗口时，consolidator 会：

1. 计算"安全预算"：`context_window - max_completion_tokens - 1024`（安全缓冲区）
2. 计算"目标值"：`预算 / 2`（至少腾出一半空间）
3. 调用 `estimate_session_prompt_tokens` 估算当前 prompt 大小
4. 如果 `estimated > budget`，开始压缩循环

`pick_consolidation_boundary` 选择一个**用户消息边界**作为分段点。这保证压缩的是完整的一轮对话，而不是截断在中间。

```python
def pick_consolidation_boundary(self, session, tokens_to_remove):
    start = session.last_consolidated
    for idx in range(start, len(session.messages)):
        message = session.messages[idx]
        if idx > start and message.get("role") == "user":
            last_boundary = (idx, removed_tokens)
            if removed_tokens >= tokens_to_remove:
                return last_boundary
        removed_tokens += estimate_message_tokens(message)
    return last_boundary
```

**为什么是 token 阈值而不是消息数阈值？**

token 阈值是唯一能确保障上下文窗口不被撑爆的方法。消息数量只是一个间接指标。一个消息可能包含几 KB 的工具结果（如 `read_file` 的大文件），也可能只包含 "Hello" 两个字。基于 token 的决策更精确，虽然也更昂贵（需要遍历所有消息估算）。

### 1.5 SessionManager 的 JSONL 持久化

`src/agent_harness/session/manager.py` 定义了 `Session` 和 `SessionManager`。

Session 使用 JSONL 格式存储。JSONL 的每一行是一个 JSON 对象，每一行独立可解析。

```
{"_type": "metadata", "key": "channel:chat_id", "created_at": "...", "last_consolidated": 123}
{"role": "user", "content": "Hello", "timestamp": "..."}
{"role": "assistant", "content": "Hi!", "tool_calls": [...], "timestamp": "..."}
{"role": "tool", "tool_call_id": "call_xxx", "content": "...", "timestamp": "..."}
```

为什么是 JSONL 而不是 SQLite 或别的格式？

- **可读性强**：每行一个 JSON，可以用 `tail`、`grep`、`jq` 直接查看和操作。
- **追加高效**：写操作是 `file.write(line + '\n')`，没有索引维护成本。
- **零依赖**：不需要 SQLite 库或 schema migration。
- **缓存友好**：LLM 的 prompt caching 在 append-only 模式下效果最好（追加不会使缓存失效）。

第一行是 metadata 行（标记 `_type: "metadata"`），存储会话的 key、创建时间、更新时间、last_consolidated 指针。后续行是消息数据。

```python
def save(self, session: Session) -> None:
    with open(path, "w", encoding="utf-8") as f:
        metadata_line = {
            "_type": "metadata",
            "key": session.key,
            "created_at": session.created_at.isoformat(),
            "last_consolidated": session.last_consolidated,
            ...
        }
        f.write(json.dumps(metadata_line, ensure_ascii=False) + "\n")
        for msg in session.messages:
            f.write(json.dumps(msg, ensure_ascii=False) + "\n")
```

SessionManager 还维护了一个 `_cache: dict[str, Session]` 作为 LRU 风格的缓存（实际上没有淘汰策略，完全在内存中），避免频繁读盘。`invalidate` 方法可以清除缓存，让下次 `get_or_create` 从磁盘重新加载。

`safe_filename` 函数将 session key 中的非法字符替换为下划线，避免文件系统错误：

```python
def safe_filename(name: str) -> str:
    return re.sub(r'[<>:"/\\|?*]', "_", name)
```

### 1.6 Session.get_history 的对齐逻辑

`get_history` 方法不是简单地从 `self.messages` 切出一段。它需要处理一个关键问题：**防止孤立的 tool 结果**。

```python
@staticmethod
def _find_legal_start(messages: list[dict[str, Any]]) -> int:
    declared: set[str] = set()
    start = 0
    for i, msg in enumerate(messages):
        role = msg.get("role")
        if role == "assistant":
            for tc in msg.get("tool_calls") or []:
                if isinstance(tc, dict) and tc.get("id"):
                    declared.add(str(tc["id"]))
        elif role == "tool":
            tid = msg.get("tool_call_id")
            if tid and str(tid) not in declared:
                start = i + 1
                declared.clear()
                ...
    return start
```

当 `get_history` 因为 `max_messages` 限制截断历史时，截断点可能落在 assistant 的 tool_calls 消息和后续的 tool 结果消息之间。如果只返回后半段（tool 结果而没有前导的 tool_calls），某些 LLM Provider 会报错——它们无法处理"无主的"tool result。

`_find_legal_start` 扫描消息列表，找到第一个满足"所有 tool 结果的 tool_call_id 都有对应的 assistant 消息"的起始位置。如果发现一个 tool 结果的 tool_call_id 不在已声明的集合中，就跳过这条记录，从下一条开始。

同理，`get_history` 开头还会跳过非 user 消息，避免以 assistant 或 tool 消息开头的对话：

```python
for i, message in enumerate(sliced):
    if message.get("role") == "user":
        sliced = sliced[i:]
        break
```

---

## 二、源码导读

### 2.1 `context/base.py` — ContextBuilder 的实现（115 行）

整个 context 模块只有 115 行。`ContextBuilder` 是核心：

- **`_providers: dict[str, SectionProvider]`** — 用字典去重，同名的 provider 自动覆盖
- **`add_provider` / `remove_provider`** — 动态增删 section
- **`build_system_prompt()`** — 排序 -> 调用每个 provider -> 拼接
- **`build_messages(system_prompt, history, current_message)`** — 组装完整的 LLM 消息列表（system + history + 带运行时上下文的 user 消息）

`build_messages` 中的 `_build_runtime_context` 方法在每条 user 消息前注入当前时间和频道信息：

```python
@staticmethod
def _build_runtime_context(channel, chat_id) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    parts = [f"Current time: {now}"]
    if channel and chat_id:
        parts.append(f"Channel: {channel} | Chat ID: {chat_id}")
    return "\n".join(parts)
```

这保证了 LLM 能够感知当前时间——一个常被忽视但对 Agent 行为影响巨大的信息。

### 2.2 `prompts/sections.py` — 内置 SectionProvider

五个 provider 各司其职：

- **EnvironmentSection(priority=5)**：调用 `get_environment_info()` 采集环境信息。数据源是 `prompts/environment.py`，执行 `platform.uname()`、`shutil.which("bash")`、`git rev-parse` 等命令。
- **IdentitySection(priority=10)**：最简单的 provider，直接返回一段预设文本。如果身份文本为空字符串，get_section 返回空，不会出现在 system prompt 中。
- **AgentsMDSection(priority=20)**：读取项目根目录下的 AGENTS.md 文件（如果存在）。这是项目级的指令注入点。
- **SkillsSection(priority=30)**：读取 skill_registry 中的技能列表。注意它具有兼容性处理：支持 `list_skills()` 和 `get_all()` 两种接口。
- **MemorySection(priority=40)**：通过 memory_store 读取长期记忆内容。

五个 provider 中，只有 MemorySection 需要异步获取数据（`get_section` 是 `async`），其余都是同步的。但由于 SectionProvider 接口要求 `async def`，所有 provider 的签名一致，ContextBuilder 不需要区分同步/异步。

### 2.3 `memory/store.py` — MemoryStore 核心

MemoryStore 的真正实现位于 `consolidator.py`（因为 consolidator 需要引用 store），但 `store.py` 是纯数据层的定义。核心方法只有四个：

1. `read_long_term()` — 读 MEMORY.md，如果文件不存在返回空字符串
2. `write_long_term(content)` — 覆盖写入 MEMORY.md
3. `append_history(entry)` — 追加写入 HISTORY.md，自动补一个空行做分隔
4. `get_memory_context()` — 格式化长期记忆为 System Prompt 可用的 markdown 块

这个版本有意保持简单——没有版本控制、没有冲突检测、没有 diff。复杂逻辑全部在 consolidator 中。

### 2.4 `memory/consolidator.py` — MemoryConsolidator 完整流程

`consolidate` 方法是记忆系统的"大脑"。它接收一段消息列表，调用 LLM 进行压缩：

```python
async def consolidate(self, messages, provider, model):
    current_memory = self.read_long_term()
    prompt = f"""Process this conversation and call the save_memory tool with your consolidation.

## Current Long-term Memory
{current_memory or "(empty)"}

## Conversation to Process
{self._format_messages(messages)}"""

    chat_messages = [
        {"role": "system", "content": "You are a memory consolidation agent. ..."},
        {"role": "user", "content": prompt},
    ]
    response = await provider.chat_with_retry(
        messages=chat_messages,
        tools=_SAVE_MEMORY_TOOL,
        model=model,
        tool_choice={"type": "function", "function": {"name": "save_memory"}},
    )
```

关键设计点：

1. **强制 tool_choice**：consolidator 使用 `tool_choice={"type": "function", "function": {"name": "save_memory"}}` 强制 LLM 调用 `save_memory` 工具，而不是让 LLM 自由聊天。这保证了输出是结构化数据。

2. **容错回退**：如果 provider 不支持强制 tool_choice（比如某些 OpenAI 兼容 API），consolidator 会捕获异常并自动回退到 `tool_choice="auto"`。

3. **失败链**：`_fail_or_raw_archive` 方法追踪连续失败次数。如果连续失败 3 次，consolidator 会切换到"原始归档"模式——不再要求 LLM 压缩，直接原样追加到 HISTORY.md。

4. **去重**：在写入 MEMORY.md 前，consolidator 会比较 `update != current_memory`，避免无意义的覆写。

### 2.5 `session/manager.py` — Session 和 SessionManager

Session 的注释非常关键：

```python
@dataclass
class Session:
    """
    Important: Messages are append-only for LLM cache efficiency.
    The consolidation process writes summaries to MEMORY.md/HISTORY.md
    but does NOT modify the messages list or get_history() output.
    """
```

这解释了为什么 `last_consolidated` 指针始终向前移动，而不是删除已压缩的消息。对于 LLM API 的 prompt caching（如 Anthropic 的 Prompt Caching），append-only 模式至关重要——每次追加新消息不会使之前缓存的 system prompt 和历史失效。

`get_history` 的执行流程：

```
self.messages → 从 last_consolidated 开始切割
     ↓
取最后 max_messages 条
     ↓
跳过前导的非 user 消息
     ↓
_find_legal_start 保证没有孤立的 tool 结果
     ↓
只拷贝需要的字段（role, content, tool_calls, tool_call_id, name）
```

`retain_recent_legal_suffix` 是 `get_history` 的"反向操作"——它从当前 messages 中截断不必要的旧消息，保留最近的一个合法后缀。这是释放内存的手段。

---

## 三、动手练习：实现 GitInfoSection

让我们实现一个自定义 SectionProvider，读取当前 Git 仓库信息，注入到系统提示中。

### 3.1 实现 SectionProvider

在 `src/agent_harness/prompts/` 下新建 `git_info_section.py`：

```python
"""Custom SectionProvider: injects git repo info into system prompt."""

from __future__ import annotations

import subprocess
from pathlib import Path

from agent_harness.context.base import SectionProvider


class GitInfoSection(SectionProvider):
    """Provide git repository information as a system prompt section."""

    section_name = "git_info"
    priority = 15  # 放在 EnvironmentSection(5) 和 IdentitySection(10) 之后

    def __init__(self, repo_path: str | Path | None = None):
        self.repo_path = Path(repo_path).resolve() if repo_path else Path.cwd()

    def _run_git(self, *args: str) -> str | None:
        """Run a git command and return stdout, or None on failure."""
        try:
            result = subprocess.run(
                ["git", *args],
                capture_output=True,
                text=True,
                cwd=str(self.repo_path),
                timeout=5,
            )
            return result.stdout.strip() if result.returncode == 0 else None
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return None

    async def get_section(self) -> str:
        branch = self._run_git("rev-parse", "--abbrev-ref", "HEAD")
        sha = self._run_git("rev-parse", "--short", "HEAD")
        commit_msg = self._run_git("log", "-1", "--format=%s")
        author = self._run_git("log", "-1", "--format=%an")
        status = self._run_git("status", "--short")

        if not branch and not sha:
            return ""  # 不在 git 仓库中，不输出任何内容

        lines = ["# Git Repository Info"]
        if branch:
            lines.append(f"- Branch: {branch}")
        if sha:
            lines.append(f"- Commit: {sha}")
        if author:
            lines.append(f"- Author: {author}")
        if commit_msg:
            lines.append(f"- Message: {commit_msg}")
        if status is not None:
            dirty_count = len([l for l in status.splitlines() if l.strip()])
            lines.append(f"- Uncommitted changes: {dirty_count} file(s)")
            if dirty_count > 0:
                lines.append("```")
                lines.append(status[:2000])
                lines.append("```")

        return "\n".join(lines)
```

### 3.2 注入到 ContextBuilder

在创建 Agent 或运行循环的地方注入：

```python
from agent_harness.context.base import ContextBuilder
from agent_harness.prompts.git_info_section import GitInfoSection

builder = ContextBuilder()
builder.add_provider(GitInfoSection(repo_path="/path/to/your/repo"))

# 构建系统提示，git 信息会自动嵌入
system_prompt = await builder.build_system_prompt()
print(system_prompt)
# 输出将包含类似：
# # Git Repository Info
# - Branch: main
# - Commit: a1b2c3d
# - Author: Alice
# - Message: fix: resolve null pointer in parser
# - Uncommitted changes: 2 file(s)
```

如果要替换已有项目中的 builder：

```python
# 在 Agent 初始化时注入
from agent_harness import Harness

harness = Harness(provider=provider, tools=tools)
harness.context_builder.add_provider(GitInfoSection())

# 现在 agent.process() 构建的 system prompt 会自动包含 Git 信息
```

`priority=15` 的设计原因：环境信息（priority=5）在最前面，然后是身份定义（priority=10），之后就是 Git 信息（priority=15），然后是项目指令（priority=20）。这样 LLM 读到的是：你在哪 -> 你是谁 -> 你代码当前状态 -> 项目规则是什么。

### 3.3 编写测试

```python
"""Tests for GitInfoSection."""

import tempfile
from pathlib import Path

import pytest

from agent_harness.prompts.git_info_section import GitInfoSection


@pytest.mark.asyncio
async def test_git_info_in_repo():
    """GitInfoSection should detect branch and commit in a git repo."""
    # 利用 agent-harness 自己的仓库
    section = GitInfoSection(repo_path=Path(__file__).resolve().parent.parent)
    content = await section.get_section()
    assert "# Git Repository Info" in content
    assert "Branch:" in content
    assert "Commit:" in content


@pytest.mark.asyncio
async def test_git_info_not_in_repo():
    """GitInfoSection should return empty string outside a git repo."""
    with tempfile.TemporaryDirectory() as tmpdir:
        section = GitInfoSection(repo_path=tmpdir)
        content = await section.get_section()
        assert content == ""  # 不在 git 仓库中，安静退出


@pytest.mark.asyncio
async def test_git_info_section_name():
    section = GitInfoSection()
    assert section.section_name == "git_info"


@pytest.mark.asyncio
async def test_git_info_priority():
    section = GitInfoSection()
    assert section.priority == 15


@pytest.mark.asyncio
async def test_integration_with_context_builder():
    from agent_harness.context.base import ContextBuilder

    builder = ContextBuilder()
    section = GitInfoSection(repo_path=Path(__file__).resolve().parent.parent)
    builder.add_provider(section)

    prompt = await builder.build_system_prompt()
    assert "Git Repository" in prompt
```

运行测试：

```bash
cd E:/work-space/agent-harness
python -m pytest tests/test_git_info_section.py -v
```

通过这个练习，你体验了：
1. 实现 `SectionProvider` 接口的完整过程
2. 同步方法（`_run_git`）如何在 async 接口中工作
3. 通过 `ContextBuilder.add_provider` 动态注入系统提示内容
4. `priority` 如何影响 prompt 中 section 的排列顺序
5. Graceful degradation：不在 git 仓库中时安静退出而非抛异常
