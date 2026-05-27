# 配置动态记忆压缩

llm-harness 支持两种记忆压缩策略，通过 `consolidation_policy` 参数注入 Agent。

## 按消息数压缩

保留最新 N 条消息在会话窗口中，旧消息自动压缩归档：

```python
from agent_harness import Agent, Harness
from agent_harness.memory.policy import MessageCountPolicy

agent = Agent(
    harness,
    model="gpt-4o",
    consolidation_policy=MessageCountPolicy(max_messages=50),
)
```

## 按 Token 预算压缩（默认）

当 prompt token 数接近上下文窗口上限时触发：

```python
from agent_harness.memory.policy import TokenBudgetPolicy

agent = Agent(
    harness,
    model="gpt-4o",
    consolidation_policy=TokenBudgetPolicy(
        context_window_tokens=200000,
        max_completion_tokens=4096,
    ),
)
```

不传 `consolidation_policy` 时默认使用 `TokenBudgetPolicy`，与之前版本行为完全一致。

## 压缩机制

每次 `Agent.process(msg)` 调用前，调度策略会自动检查是否需要压缩。压缩过程：

1. 策略判断触发条件（消息数超限 / token 预算不足）
2. LLM 一次调用分类提取记忆，输出 5 个字段
3. 分别写入 MEMORY.md、AGENTS.md、SOUL.md、USER.md
4. 原始消息追加到 history.jsonl（可 grep 回溯）
5. 已压缩的消息从 session 窗口移除

## 记忆文件结构

每个会话独立管理记忆：

```
memory/{session_key}/
  MEMORY.md      ← 事实、知识、决策（LLM 覆盖写）
  AGENTS.md      ← 项目规则、工作流约定（LLM 覆盖写）
  SOUL.md        ← 人格、语气、行为模式（LLM 覆盖写）
  USER.md        ← 用户画像、偏好（LLM 覆盖写）
  history.jsonl  ← 归档聊天记录 + 摘要（追加写）
```

压缩时 LLM 一次调用输出 5 个字段，分别写入对应文件。无变化的文件跳过不写。
