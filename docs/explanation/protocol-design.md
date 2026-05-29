# 协议设计

llm-harness 中的所有后端适配器都使用 Python 的 `Protocol` 类（来自 `typing.Protocol`）。这是一个经过深思熟虑的架构选择。

## 结构子类型 vs 名义子类型

```python
# Protocol（结构型）— 匹配任何拥有这些方法的对象
class SandboxBackend(Protocol):
    async def read_file(self, session_key: str, path: str) -> str: ...
    async def write_file(self, session_key: str, path: str, content: str) -> None: ...

# ABC（名义型）— 需要显式继承
class SandboxBackend(ABC):
    @abstractmethod
    async def read_file(self, session_key: str, path: str) -> str: ...
```

使用 `Protocol`，你可以在不导入或不继承 `SandboxBackend` 的情况下实现 `SRTSandboxBackend`。类型检查器在使用处验证兼容性，而非在定义处。

## 为什么选择 Protocol？

1. **零耦合。** 你的后端实现对 llm-harness 没有导入依赖。你可以将其放在一个独立的包中。
2. **最小化接口。** 每个 Protocol 只声明框架实际调用的方法。除非框架需要，否则没有 `close()`、`connect()` 或 `configure()`。
3. **易于模拟。** 在测试中，`AsyncMock()` 可以满足任何 Protocol。

## 所有核心协议

### SandboxBackend（8 个方法）

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

### MemoryBackend（4 个方法）

```
get_context(namespace) → str
read_section(namespace, section) → str
append_section(namespace, section, entry)
consolidate(namespace, messages, provider, model) → bool
```

### AgentBackend（3 个方法）

```
spawn(config, origin_session_key, origin_account) → SpawnResult
send_message(agent_id, message) → bool
stop(agent_id) → bool
```

### SessionBackend（3 个方法）

```
load(session_key) → dict | None
save(session_key, state)
list_keys() → list[str]
```

### ObservabilityBackend（3 个方法）

```
emit(event_type, payload)
subscribe(event_type, handler)
unsubscribe(event_type, handler)
```

## 添加新后端

实现 Protocol 方法即可。无需从 llm-harness 导入：

```python
class MySandbox:
    async def create_session(self, session_key: str) -> SandboxSession:
        return SandboxSession(session_key=session_key, volume_path="/tmp", sandbox_id="my")
    # ... 实现其余 7 个方法

# 使用
harness = Harness(..., sandbox=MySandbox())
```

类型检查器会在 `Harness(...)` 调用处验证 `MySandbox` 是否满足 `SandboxBackend`。
