# llm-harness Bug 修复报告

> 修复日期：2026-05-28 | 审查范围：架构审查中发现 13 个 bug，全部修复

---

## 根本原因链

审查发现所有 bug 归根结底来自 3 个设计疏忽，它们的连锁效应导致了其余问题：

```
设计疏忽 #1: 没有把 session_key 注入到 ToolExecutionContext
  → 导致所有文件/沙盒/子代理工具拿到的 session_key 为空字符串

设计疏忽 #2: 回调签名没有统一（sync vs async）
  → 权限检查同步返回，但 loop 里硬编码了 await → 每次工具调用崩溃

设计疏忽 #3: on_build_context 漏掉了 history
  → LLM 每轮只看当前消息，没有任何上下文
```

---

## 逐 Bug 修复详情

### Bug 1（崩溃）— `await` 同步权限检查

**文件：** `src/llm_harness/core/loop.py`

**原因：** `AgentLoop.run()` 中 `perm = await self._check_tool(...)` 硬编码了 await，但 `Harness` 注入的默认 `on_tool_check` 是同步 lambda，返回非可等待的 `PermissionDecision`。每次工具调用抛出 `TypeError`。

**修复：**
```python
# Before
perm = await self._check_tool(tc.name, tool, parsed)

# After
perm = self._check_tool(tc.name, tool, parsed)
if asyncio.iscoroutine(perm):
    perm = await perm
```

---

### Bug 2（全废）— ToolExecutionContext metadata 为空

**文件：** `src/llm_harness/core/loop.py`

**原因：** `ToolExecutionContext(cwd=Path("/workspace"), metadata={})` 把 metadata 硬编码为空字典。所有工具通过 `context.metadata.get("session_key", "")` 读取 session_key 时拿到空字符串。影响 9 个工具。

**修复：** 从 `msg` 读取 session_key 注入 metadata：
```python
session_key = getattr(msg, 'session_key', '')
ctx = ToolExecutionContext(cwd=Path("/workspace"), metadata={"session_key": session_key})
```

---

### Bug 3（静默）— 合并器令牌预算参数被丢弃

**文件：** `src/llm_harness/core/harness.py`

**原因：** `Harness.__init__` 接受 `context_window_tokens` 和 `max_completion_tokens`，但未存储。`_build_consolidator()` 使用硬编码 64000/4096。用户传入任意值都被忽略。

**修复：**
```python
# __init__ 中
self.context_window_tokens = context_window_tokens
self.max_completion_tokens = max_completion_tokens

# _build_consolidator 中
MemoryConsolidator(
    context_window_tokens=self.context_window_tokens,
    max_completion_tokens=self.max_completion_tokens,
    ...
)
```

---

### Bug 4（崩溃）— 同步权限 lambda

**文件：** `src/llm_harness/core/harness.py`

**原因：** `on_tool_check` lambda 返回同步 `PermissionDecision`，被 loop 里 `await` 触发崩溃。与 Bug 1 同根。

**修复：** 由 Bug 1 的修复覆盖（loop 中改为 `iscoroutine` 检查）。

---

### Bug 5（全废）— on_build_context 忽略 history

**文件：** `src/llm_harness/core/harness.py`

**原因：** `create_agent()` 中 `on_build_context` 构建消息列表时完全未使用 `history` 参数。返回的消息只包含 system prompt + 当前用户消息，无对话上下文。

**修复：**
```python
messages = [{"role": "system", "content": system}]
messages.extend(history)
messages.append({"role": "user", "content": msg.content})
return messages
```

---

### Bug 6（静默）— _save_turn 过度保存

**文件：** `src/llm_harness/core/agent.py`

**原因：** `_save_turn` 遍历 `result.messages` 全部内容（含 system prompt、用户消息），将其全部写入 Session。用户消息已被 `process()` 单独保存，导致重复；system prompt 不应进入持久化历史。

**修复：** 只保存 assistant 和 tool 角色的消息：
```python
if role not in ("assistant", "tool"):
    continue
```

---

### Bug 7（静默）— AgentTool 获取不到工具名列表

**文件：** `src/llm_harness/core/tools/agent.py`、`harness.py`

**原因：** `AgentTool.execute()` 通过 `context.metadata.get("harness_tools", [])` 获取主 Agent 工具列表，但 metadata 为空。

**修复：** 改为构造函数注入：
```python
# AgentTool
def __init__(self, backend, bus, harness_tool_names=None):
    self._harness_tool_names = harness_tool_names or []

# harness.py
"agent": lambda: AgentTool(self.swarm, self.bus, self._harness_tool_names)
```

---

### Bug 8-11（静默）— 所有工具 session_key 为空

**文件：** `read_file.py`, `write_file.py`, `exec.py`, `glob.py`, `grep.py`, `memory_read.py`, `memory_write.py`

**原因：** 与 Bug 2 同根。修复 Bug 2 后全部解决。

---

### Bug 12（静默）— history.jsonl 格式错误

**文件：** `src/llm_harness/adapters/memory/file.py`

**原因：** `add_history` 写入双换行纯文本到 `.jsonl` 文件。文件名暗示 JSON Lines 格式，但内容不匹配。

**修复：** 写入标准 JSON Lines 格式，每条记录一行 JSON：
```python
record = {"timestamp": datetime.now().isoformat(), "entry": entry}
f.write(json.dumps(record, ensure_ascii=False) + "\n")
```

---

### Bug 13（静默）— get_history 可能返回非用户开头

**文件：** `src/llm_harness/core/session/session.py`

**原因：** 如果切片窗口内没有任何 user-role 消息，`get_history` 返回以 assistant/tool 开头的列表，导致 LLM 收到格式错误的消息序列。

**修复：** 未找到 user 消息时返回空列表：
```python
found = False
for i, m in enumerate(sliced):
    if m.get("role") == "user":
        sliced = sliced[i:]
        found = True
        break
if not found:
    return []
```

---

## 测试结果

所有修复后 11/11 集成测试通过。

## 经验教训

1. **回调签名要统一** — 同时支持 sync/async 的回调需要用 `iscoroutine` 判断，或用 Protocol 约束
2. **上下文传播要显式** — session_key 等运行时信息要在调用链上逐级传递，不能靠隐式的 metadata 兜底
3. **历史管理的边界** — 哪些消息进 Session（原始对话），哪些不进（system prompt），要在 _save_turn 层面显式控制
