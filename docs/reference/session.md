# Session

`Session` is a pure data structure — no I/O, no persistence. It holds the
conversation messages and consolidation offset.

Source: `llm_harness.core.session`

## Fields

```python
@dataclass
class Session:
    key: str                                          # unique session identifier
    messages: list[dict[str, Any]]                    # full message history
    created_at: datetime                              # creation timestamp (UTC)
    updated_at: datetime                              # last update timestamp (UTC)
    metadata: dict[str, Any]                          # arbitrary metadata
    last_consolidated: int = 0                        # index offset for consolidation
```

## Properties

| Property | Type | Description |
|----------|------|-------------|
| `channel` | `str \| None` | First component of `key` when formatted as `channel:chat_id` |
| `chat_id` | `str \| None` | Second component of `key` when formatted as `channel:chat_id` |

## Methods

### add_message(role, content, **kwargs)

```python
def add_message(self, role: str, content: str, **kwargs: Any) -> None
```

Appends a message to `messages` with auto-generated `timestamp` and any
extra kwargs (e.g., `tool_calls`, `tool_call_id`, `name`).

### get_history(max_messages=500) → list[dict[str, Any]]

Returns recent unconsolidated messages, aligned to start at a `user` message.
Skips messages before `last_consolidated`. Returns at most `max_messages`.
Forward-searches to the nearest `role == "user"` message to ensure the LLM
never receives orphaned assistant/tool messages.

### remove_before(idx)

```python
def remove_before(self, idx: int) -> None
```

Removes messages before `idx` and adjusts `last_consolidated` offset.
Called by `MemoryConsolidator` after successful consolidation.

### to_state() → dict[str, Any]

Returns serializable state: `{"messages": ..., "metadata": ..., "last_consolidated": ...}`

## Usage

```python
session = Session(key="alice:chat1")
session.add_message("user", "Hello")
session.add_message("assistant", "Hi there!", tool_calls=[...])
session.add_message("tool", "result", tool_call_id="c1", name="read_file")

history = session.get_history()
# → last two messages starting from nearest user message

state = session.to_state()
# → persist this dict
```
