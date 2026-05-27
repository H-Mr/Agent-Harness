# 动态记忆压缩调度 + 会话隔离 + 多文件记忆

## 概述

将当前全局、token-budget-only 的记忆压缩机制改造为：会话级隔离、多文件结构化记忆、可插拔调度策略。每次 `Agent.process(msg)` 自动触发调度检查，压缩旧消息 → 分类写入记忆文件 → 归档原始消息 → 从 session 窗口移除。

## 目标

1. **会话隔离**：每个 session 在 `memory/{session_key}/` 下独立管理记忆文件
2. **多文件记忆**：LLM 一次压缩输出 5 个字段，分别写入 AGENTS.md / SOUL.md / MEMORY.md / USER.md / history.jsonl
3. **可插拔策略**：`TokenBudgetPolicy`（默认）和 `MessageCountPolicy` 两种触发方式，通过回调注入
4. **窗口保持**：压缩后旧消息从 session.jsonl 物理移除，`last_consolidated` 归零

## 数据流

```
Agent.process(msg)
  → Session.add_message(msg)
  → policy.should_consolidate(session) → list[dict] | None
  → [如果有消息需要压缩]
      → MemoryStore.consolidate(messages):
          1. LLM 压缩（一次调用，5 字段输出）
          2. 写入 AGENTS.md / SOUL.md / MEMORY.md / USER.md
          3. history_entry → history.jsonl（追加）
          4. 原始消息 → history.jsonl（追加，可 grep）
      → Session.remove_before(end_idx)
      → Session.last_consolidated = 0
      → 重写 session.jsonl
  → ReAct loop
```

## 文件结构

```
workspace/
  sessions/
    {session_key}.jsonl                 ← 窗口内活跃消息
  memory/
    {session_key}/
      MEMORY.md                         ← 事实、知识、决策（覆盖写）
      AGENTS.md                         ← 项目规则、工作流约定（覆盖写）
      SOUL.md                           ← 人格、语气、行为偏好（覆盖写）
      USER.md                           ← 用户画像、偏好（覆盖写）
      history.jsonl                     ← 归档聊天记录 + 摘要（追加写）
      _meta.json                        ← 压缩元数据
```

## 模块变更

### 1. `memory/store.py` — 多文件记忆

- 重命名/重构 `MemoryStore` → 支持 `memory/{session_key}/` 目录
- 新增方法：`read_file(name)`, `write_file(name, text)`, `append_history(entry)`, `append_raw_messages(msgs)`, `get_all_files()`, `get_context()`
- `save_memory` 工具定义改为 5 字段：
  - `agents_update: str | None` → AGENTS.md
  - `soul_update: str | None` → SOUL.md
  - `memory_update: str` → MEMORY.md（必填）
  - `user_update: str | None` → USER.md
  - `history_entry: str` → history.jsonl

### 2. `memory/policy.py` — 新增调度策略

```python
class TokenBudgetPolicy:
    context_window_tokens: int
    max_completion_tokens: int = 4096
    async def should_consolidate(session, consolidator) → list[dict] | None

class MessageCountPolicy:
    max_messages: int = 50
    async def should_consolidate(session, consolidator) → list[dict] | None
```

### 3. `memory/consolidator.py` — 核心改造

- 持有 `SessionMemoryStore` 实例（init 时创建或传入）
- 新增 `maybe_consolidate(session)` — 调度入口
- 压缩流程：策略判断 → LLM 压缩 → 写文件 → 归档 → 移除消息
- 移除旧的 `maybe_consolidate_by_tokens`（行为并入 `TokenBudgetPolicy`）
- `pick_consolidation_boundary` 保留，在 user 边界切分
- `estimate_session_prompt_tokens` 保留

### 4. `session/manager.py` — 消息移除

```python
Session.remove_before(idx: int):
    """移除 idx 之前的所有消息，重写 JSONL，last_consolidated 归零"""
```

### 5. `agent.py` — 策略注入

```python
Agent.__init__ 新增参数:
    consolidation_policy: ConsolidationPolicy | None = None
    # None → TokenBudgetPolicy(context_window=harness.context_window_tokens)
```

### 6. `harness.py` — 透传

```python
Harness 透传 consolidation_policy 到 Agent
```

## 压缩 Prompt 模板

```
你是记忆压缩代理。分析以下对话，提取结构化记忆。

## 各文件职责
- AGENTS.md: 项目规则、工作流约定、技术栈偏好（无变化返回 null）
- SOUL.md: 沟通风格、语气、回复习惯、行为模式（无变化返回 null）
- MEMORY.md: 事实知识、决策记录、关键发现（必须返回完整更新版本）
- USER.md: 用户角色、偏好、目标（无变化返回 null）
- history_entry: 一句可 grep 的摘要，格式 [YYYY-MM-DD HH:MM] 关键事件

## 当前记忆
[读入各文件当前内容]

## 待压缩对话
[format_messages(chunk)]

调用 save_memory 工具输出压缩结果。
```

LLM 返回 `save_memory({"agents_update": null, "soul_update": "...", "memory_update": "...", "user_update": null, "history_entry": "[2026-05-27 14:30] ..."})`。

只有非 null 的字段才触发覆盖写对应的 .md 文件。

## 向后兼容

- 未传 `consolidation_policy` → 默认 `TokenBudgetPolicy`，行为完全不变
- 现有 `MemoryStore` 的全局 API 保持可用（`read_long_term`, `write_long_term`, `append_history`, `get_memory_context`），内部映射到 `memory/{default_session}/` 目录
- `_SAVE_MEMORY_TOOL` 常量位置不变，值改变（2→5 字段）
- `MemoryConsolidator.__init__` 签名新增参数但向后兼容（旧代码不传 policy → 自动 TokenBudgetPolicy）

## 测试策略

1. `test_memory_store.py` — 多文件读写、history.jsonl 追加、get_all_files 完整性
2. `test_policy.py` — TokenBudgetPolicy / MessageCountPolicy 触发与不触发边界
3. `test_consolidator.py` — maybe_consolidate 完整流程（Mock provider）
4. `test_session_remove.py` — remove_before + JSONL 重写 + 指针归零
5. `test_agent_integration.py` — Agent 透传 policy 并触发压缩
