# Protocol Design

All backend adapters in llm-harness use Python `Protocol` classes from
`typing.Protocol`. This is a deliberate architectural choice.

## Structural vs Nominal Subtyping

```python
# Protocol (structural) — matches any object with these methods
class SandboxBackend(Protocol):
    async def read_file(self, session_key: str, path: str) -> str: ...
    async def write_file(self, session_key: str, path: str, content: str) -> None: ...

# ABC (nominal) — requires explicit inheritance
class SandboxBackend(ABC):
    @abstractmethod
    async def read_file(self, session_key: str, path: str) -> str: ...
```

With `Protocol`, you can implement `SRTSandboxBackend` without importing or
inheriting from `SandboxBackend`. The type checker validates compatibility
at the usage site, not the definition site.

## Why Protocol?

1. **Zero coupling.** Your backend implementation has no import dependency
   on llm-harness. You can put it in a separate package.
2. **Minimal interface.** Each Protocol only declares the methods the
   framework actually calls. No `close()`, `connect()`, or `configure()`
   unless the framework needs them.
3. **Easy mocking.** In tests, `AsyncMock()` satisfies any Protocol.

## All Core Protocols

### SandboxBackend (8 methods)

```
create_session(session_key) → SandboxSession
destroy_session(session_key)
read_file(session_key, path) → str
write_file(session_key, path, content)
list_dir(session_key, path) → list[str]
glob(session_key, pattern) → list[str]
grep(session_key, pattern, path) → list[str]
execute(session_key, command, *, cwd, env, timeout) → ExecResult
```

### MemoryBackend (5 methods)

```
get_context(namespace) → str
read_section(namespace, section) → str
append_section(namespace, section, entry)
add_history(namespace, entry)
consolidate(namespace, messages, provider, model) → bool
```

### AgentBackend (3 methods)

```
spawn(config, origin_session_key, origin_account) → SpawnResult
send_message(agent_id, message) → bool
stop(agent_id) → bool
```

### SessionBackend (3 methods)

```
load(session_key) → dict | None
save(session_key, state)
list_keys() → list[str]
```

### ObservabilityBackend (3 methods)

```
emit(event_type, payload)
subscribe(event_type, handler)
unsubscribe(event_type, handler)
```

## Adding a New Backend

Implement the Protocol methods. No imports from llm-harness needed:

```python
class MySandbox:
    async def create_session(self, session_key: str) -> SandboxSession:
        return SandboxSession(session_key=session_key, volume_path="/tmp", sandbox_id="my")
    # ... implement remaining 7 methods

# Usage
harness = Harness(..., sandbox=MySandbox())
```

The type checker verifies `MySandbox` satisfies `SandboxBackend` at the
`Harness(...)` call site.
