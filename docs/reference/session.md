# Session

`Session` 是纯数据结构 — 无 I/O，无持久化。它保存对话消息和整合偏移量。

源码位置：`llm_harness.core.session`

## 字段

```python
@dataclass
class Session:
    key: str                                          # 唯一会话标识符
    messages: list[dict[str, Any]]                    # 完整消息历史
    created_at: datetime                              # 创建时间戳（UTC）
    updated_at: datetime                              # 最后更新时间戳（UTC）
    metadata: dict[str, Any]                          # 任意元数据
    last_consolidated: int = 0                        # 整合的索引偏移量
```

## 属性

| 属性 | 类型 | 说明 |
|----------|------|-------------|
| `channel` | `str \| None` | 当 `key` 格式为 `channel:chat_id` 时的第一个组成部分 |
| `chat_id` | `str \| None` | 当 `key` 格式为 `channel:chat_id` 时的第二个组成部分 |

## 方法

### add_message(role, content, **kwargs)

```python
def add_message(self, role: str, content: str, **kwargs: Any) -> None
```

向 `messages` 追加一条消息，自动生成 `timestamp` 并包含任何额外的 kwargs（例如 `tool_calls`、`tool_call_id`、`name`）。

### get_history(max_messages=500) → list[dict[str, Any]]

返回最近未整合的消息，并对齐到以 `user` 消息开始的位置。跳过 `last_consolidated` 之前的消息。最多返回 `max_messages` 条。向前搜索最近的 `role == "user"` 消息，确保 LLM 永远不会收到孤立的 assistant/tool 消息。

### remove_before(idx)

```python
def remove_before(self, idx: int) -> None
```

移除 `idx` 之前的消息并调整 `last_consolidated` 偏移量。由 `MemoryConsolidator` 在成功整合后调用。

### to_state() → dict[str, Any]

返回可序列化的状态：`{"messages": ..., "metadata": ..., "last_consolidated": ...}`

## 用法

```python
session = Session(key="alice:chat1")
session.add_message("user", "Hello")
session.add_message("assistant", "Hi there!", tool_calls=[...])
session.add_message("tool", "result", tool_call_id="c1", name="read_file")

history = session.get_history()
# → 从最近的 user 消息开始的后两条消息

state = session.to_state()
# → 持久化此字典
```
