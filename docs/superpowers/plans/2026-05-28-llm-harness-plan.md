# llm-harness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build llm-harness — a lightweight AI agent infrastructure library where harness only orchestrates, delegating memory/sandbox/session/observability to pluggable backends.

**Architecture:** 5 Protocol-based backends (Memory, Sandbox, Agent, Session, Observability) + pure ReAct loop with callback injection + Channel lifecycle hooks + volume-based session isolation.

**Tech Stack:** Python >= 3.10, Pydantic >= 2.0, httpx, asyncio, hatchling

---

### Task 1: Project Skeleton

**Files:**
- Create: `E:\work-space\llm-harness\pyproject.toml`
- Create: `E:\work-space\llm-harness\src\llm_harness\__init__.py`

- [ ] **Step 1: Create directory structure**

```bash
cd E:/work-space/llm-harness && mkdir -p src/llm_harness/{core/{bus,tools,permissions,session},adapters/{memory,sandbox,swarm,session,observability,providers},extensions/{hooks,skills,mcp,cron,channels},config} && mkdir -p tests
```

- [ ] **Step 2: Create pyproject.toml**

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "llm-harness"
version = "0.1.0"
description = "Lightweight AI agent infrastructure — harness orchestrates, backends execute"
license = {text = "MIT"}
readme = "README.md"
requires-python = ">=3.10"

dependencies = [
    "pydantic>=2.0.0",
    "httpx>=0.27.0",
    "mcp>=1.0.0",
    "croniter>=2.0.0",
    "pyyaml>=6.0",
    "json-repair>=0.57.0",
    "tzdata>=2024.1",
]

[project.optional-dependencies]
anthropic = ["anthropic>=0.45.0"]
openai = ["openai>=2.8.0"]
tools = ["ddgs>=9.5.5", "readability-lxml>=0.8.4", "chardet>=3.0.2"]
opensandbox = ["opensandbox"]
all = ["anthropic>=0.45.0", "openai>=2.8.0", "ddgs>=9.5.5", "readability-lxml>=0.8.4", "chardet>=3.0.2", "opensandbox"]
dev = ["pytest>=8.0.0", "pytest-asyncio>=0.23.0", "ruff>=0.5.0"]

[tool.hatch.build.targets.wheel]
packages = ["src/llm_harness"]

[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
```

- [ ] **Step 3: Create src/llm_harness/__init__.py**

```python
"""llm-harness: Lightweight AI agent infrastructure library.

Harness + Memory Backend + Sandbox Backend + LLM = Agent
"""

__version__ = "0.1.0"
```

- [ ] **Step 4: Install and verify**

```bash
cd E:/work-space/llm-harness && uv sync --dev && uv run python -c "import llm_harness; print(llm_harness.__version__)"
```
Expected: `0.1.0`

- [ ] **Step 5: Initialize git and commit**

```bash
cd E:/work-space/llm-harness && git init && git add -A && git commit -m "chore: project skeleton" -m "Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 2: Message Bus

**Files:**
- Create: `src/llm_harness/core/bus/__init__.py`
- Create: `src/llm_harness/core/bus/events.py`
- Create: `src/llm_harness/core/bus/queue.py`

- [ ] **Step 1: Create bus/events.py — InboundMessage + OutboundMessage**

Copy from `E:\work-space\agent-harness\src\agent_harness\bus\events.py`, replacing the package import path:

```python
"""Bus event types — InboundMessage and OutboundMessage."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class InboundMessage:
    channel: str
    sender_id: str
    chat_id: str
    content: str
    timestamp: datetime = field(default_factory=datetime.now)
    media: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    session_key_override: str | None = None

    @property
    def session_key(self) -> str:
        return self.session_key_override or f"{self.channel}:{self.chat_id}"


@dataclass
class OutboundMessage:
    channel: str
    chat_id: str
    content: str
    reply_to: str | None = None
    media: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
```

- [ ] **Step 2: Create bus/queue.py — MessageBus**

Copy from `E:\work-space\agent-harness\src\agent_harness\bus\queue.py`, replacing imports:

```python
"""Async message queue for decoupled channel-agent communication."""

import asyncio

from llm_harness.core.bus.events import InboundMessage, OutboundMessage


class MessageBus:
    def __init__(self):
        self.inbound: asyncio.Queue[InboundMessage] = asyncio.Queue()
        self.outbound: asyncio.Queue[OutboundMessage] = asyncio.Queue()

    async def publish_inbound(self, msg: InboundMessage) -> None:
        await self.inbound.put(msg)

    async def consume_inbound(self) -> InboundMessage:
        return await self.inbound.get()

    async def publish_outbound(self, msg: OutboundMessage) -> None:
        await self.outbound.put(msg)

    async def consume_outbound(self) -> OutboundMessage:
        return await self.outbound.get()
```

- [ ] **Step 3: Create bus/__init__.py**

```python
from llm_harness.core.bus.events import InboundMessage, OutboundMessage
from llm_harness.core.bus.queue import MessageBus

__all__ = ["InboundMessage", "OutboundMessage", "MessageBus"]
```

- [ ] **Step 4: Verify and commit**

```bash
cd E:/work-space/llm-harness && uv run python -c "from llm_harness.core.bus import InboundMessage, OutboundMessage, MessageBus; m=InboundMessage('cli','u','c','hi'); assert m.session_key=='cli:c'; print('OK')" && git add -A && git commit -m "feat: add message bus (InboundMessage, OutboundMessage, MessageBus)" -m "Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 3: Config System

**Files:**
- Create: `src/llm_harness/config/__init__.py`
- Create: `src/llm_harness/config/schema.py`
- Create: `src/llm_harness/config/loader.py`

- [ ] **Step 1: Create config/schema.py**

```python
"""Configuration schema via Pydantic."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class AgentConfig(BaseModel):
    model: str = "claude-sonnet-4-6"
    provider: str = "auto"
    api_key: str = ""
    api_base: str = ""
    max_tokens: int = 4096
    context_window_tokens: int = 64_000


class ToolsConfig(BaseModel):
    enabled: list[str] = Field(default_factory=lambda: [
        "read_file", "write_file", "edit_file", "exec",
        "web_search", "web_fetch", "glob", "grep",
        "memory_read", "memory_write",
        "agent", "send_message", "task_stop",
        "task_create", "task_list", "task_update",
        "cron_create", "cron_list", "cron_delete",
        "ask_user_question",
    ])
    disabled: list[str] = Field(default_factory=list)


class PermissionConfig(BaseModel):
    mode: str = "default"
    allowed_tools: list[str] = Field(default_factory=list)
    denied_tools: list[str] = Field(default_factory=list)


class SandboxConfig(BaseModel):
    backend: str = "opensandbox"
    base_url: str = "http://localhost:8080"


class MemoryConfig(BaseModel):
    backend: str = "tencentdb"
    base_url: str = "http://localhost:8420"


class ObservabilityConfig(BaseModel):
    track_file: str = ""


class ChannelConfig(BaseModel):
    type: str = "cli"
    settings: dict[str, Any] = Field(default_factory=dict)


class Config(BaseModel):
    agent: AgentConfig = Field(default_factory=AgentConfig)
    tools: ToolsConfig = Field(default_factory=ToolsConfig)
    permission: PermissionConfig = Field(default_factory=PermissionConfig)
    sandbox: SandboxConfig = Field(default_factory=SandboxConfig)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    observability: ObservabilityConfig = Field(default_factory=ObservabilityConfig)
    channels: list[ChannelConfig] = Field(default_factory=list)
    workspace: str = "."

    @property
    def workspace_path(self) -> Path:
        return Path(self.workspace).expanduser().resolve()
```

- [ ] **Step 2: Create config/loader.py**

```python
"""Config loader: CLI args > env vars > YAML file > defaults."""

from __future__ import annotations

import os
from pathlib import Path

import yaml

from llm_harness.config.schema import Config


def load_config(
    config_path: str | Path | None = None,
    *, model: str | None = None, provider: str | None = None,
) -> Config:
    config = Config()
    path = config_path or os.environ.get("LLM_HARNESS_CONFIG")
    if path and Path(path).exists():
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        if data:
            config = Config(**data)
    for env_key, field in [
        ("LLM_HARNESS_MODEL", "model"), ("LLM_HARNESS_PROVIDER", "provider"),
        ("LLM_HARNESS_API_KEY", "api_key"), ("LLM_HARNESS_API_BASE", "api_base"),
        ("LLM_HARNESS_WORKSPACE", "workspace"),
    ]:
        if os.environ.get(env_key):
            setattr(config.agent, field, os.environ[env_key])
    if model:
        config.agent.model = model
    if provider:
        config.agent.provider = provider
    return config
```

- [ ] **Step 3: Create config/__init__.py**

```python
from llm_harness.config.schema import Config
from llm_harness.config.loader import load_config

__all__ = ["Config", "load_config"]
```

- [ ] **Step 4: Verify and commit**

```bash
cd E:/work-space/llm-harness && uv run python -c "from llm_harness.config import Config, load_config; c=load_config(); assert c.agent.model=='claude-sonnet-4-6'; print('OK')" && git add -A && git commit -m "feat: add config system (schema + loader)" -m "Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 4: SessionBackend Protocol + File Backend

**Files:**
- Create: `src/llm_harness/adapters/session/__init__.py`
- Create: `src/llm_harness/adapters/session/backend.py`
- Create: `src/llm_harness/adapters/session/file.py`

- [ ] **Step 1: Create session/backend.py**

```python
"""SessionBackend Protocol — harness owns Session model, backend owns persistence."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class SessionBackend(Protocol):
    async def load(self, session_key: str) -> dict[str, Any] | None:
        """Load session state dict. Returns None if not found."""
        ...

    async def save(self, session_key: str, state: dict[str, Any]) -> None:
        """Persist session state."""
        ...

    async def list_keys(self) -> list[str]:
        """List all persisted session keys."""
        ...
```

- [ ] **Step 2: Create session/file.py**

```python
"""JSONL file-based session backend."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from llm_harness.adapters.session.backend import SessionBackend

logger = logging.getLogger(__name__)


class FileSessionBackend:
    def __init__(self, base_dir: Path):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self._lock = None  # asyncio lock, created lazily

    def _path(self, session_key: str) -> Path:
        import re
        safe = re.sub(r'[<>:"/\\|?*]', "_", session_key)
        return self.base_dir / f"{safe}.jsonl"

    async def load(self, session_key: str) -> dict[str, Any] | None:
        path = self._path(session_key)
        if not path.exists():
            return None
        try:
            messages = []
            metadata = {}
            last_consolidated = 0
            with open(path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    data = json.loads(line)
                    if data.get("_type") == "metadata":
                        metadata = data.get("metadata", {})
                        last_consolidated = data.get("last_consolidated", 0)
                    else:
                        messages.append(data)
            return {"messages": messages, "metadata": metadata, "last_consolidated": last_consolidated}
        except Exception:
            logger.warning("Failed to load session %s", session_key, exc_info=True)
            return None

    async def save(self, session_key: str, state: dict[str, Any]) -> None:
        path = self._path(session_key)
        with open(path, "w", encoding="utf-8") as f:
            meta = {"_type": "metadata", "key": session_key,
                    "last_consolidated": state.get("last_consolidated", 0),
                    "metadata": state.get("metadata", {})}
            f.write(json.dumps(meta, ensure_ascii=False) + "\n")
            for msg in state.get("messages", []):
                f.write(json.dumps(msg, ensure_ascii=False) + "\n")

    async def list_keys(self) -> list[str]:
        keys = []
        for p in self.base_dir.glob("*.jsonl"):
            try:
                with open(p, encoding="utf-8") as f:
                    first = json.loads(f.readline().strip())
                if first.get("_type") == "metadata":
                    keys.append(first.get("key", p.stem))
            except Exception:
                continue
        return keys
```

- [ ] **Step 3: Create session/__init__.py**

```python
from llm_harness.adapters.session.backend import SessionBackend
from llm_harness.adapters.session.file import FileSessionBackend

__all__ = ["SessionBackend", "FileSessionBackend"]
```

- [ ] **Step 4: Verify with a quick test**

```bash
cd E:/work-space/llm-harness && uv run python -c "
import asyncio, tempfile
from pathlib import Path
from llm_harness.adapters.session import FileSessionBackend

async def test():
    d = tempfile.mkdtemp()
    b = FileSessionBackend(Path(d))
    await b.save('test:1', {'messages': [{'role':'user','content':'hi'}], 'metadata':{}, 'last_consolidated':0})
    state = await b.load('test:1')
    assert len(state['messages']) == 1
    assert state['messages'][0]['content'] == 'hi'
    keys = await b.list_keys()
    assert 'test:1' in keys
    print('OK')
asyncio.run(test())
" && git add -A && git commit -m "feat: add SessionBackend protocol + JSONL file backend" -m "Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 5: Session Data Class + SessionManager

**Files:**
- Create: `src/llm_harness/core/session/__init__.py`
- Create: `src/llm_harness/core/session/session.py`
- Create: `src/llm_harness/core/session/manager.py`

- [ ] **Step 1: Create session/session.py**

```python
"""Session data class — pure structure, no IO."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class Session:
    key: str
    messages: list[dict[str, Any]] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    metadata: dict[str, Any] = field(default_factory=dict)
    last_consolidated: int = 0

    def add_message(self, role: str, content: str, **kwargs: Any) -> None:
        msg = {"role": role, "content": content, "timestamp": datetime.now().isoformat(), **kwargs}
        self.messages.append(msg)
        self.updated_at = datetime.now()

    def get_history(self, max_messages: int = 500) -> list[dict[str, Any]]:
        unconsolidated = self.messages[self.last_consolidated:]
        sliced = unconsolidated[-max_messages:]
        for i, m in enumerate(sliced):
            if m.get("role") == "user":
                sliced = sliced[i:]
                break
        return [{"role": m["role"], "content": m.get("content", "")} for m in sliced]

    def remove_before(self, idx: int) -> None:
        if idx <= 0:
            return
        self.messages = self.messages[idx:]
        self.last_consolidated = max(0, self.last_consolidated - idx)
        self.updated_at = datetime.now()

    def to_state(self) -> dict[str, Any]:
        return {"messages": self.messages, "metadata": self.metadata,
                "last_consolidated": self.last_consolidated}
```

- [ ] **Step 2: Create session/manager.py**

```python
"""SessionManager — wraps SessionBackend with in-memory caching."""

from __future__ import annotations

import logging
from datetime import datetime

from llm_harness.adapters.session.backend import SessionBackend
from llm_harness.core.session.session import Session

logger = logging.getLogger(__name__)


class SessionManager:
    def __init__(self, backend: SessionBackend):
        self.backend = backend
        self._cache: dict[str, Session] = {}

    async def get_or_create(self, key: str) -> Session:
        if key in self._cache:
            return self._cache[key]
        state = await self.backend.load(key)
        if state:
            session = Session(
                key=key, messages=state.get("messages", []),
                metadata=state.get("metadata", {}),
                last_consolidated=state.get("last_consolidated", 0),
            )
        else:
            session = Session(key=key)
        self._cache[key] = session
        return session

    async def save(self, session: Session) -> None:
        await self.backend.save(session.key, session.to_state())

    def invalidate(self, key: str) -> None:
        self._cache.pop(key, None)

    async def list_keys(self) -> list[str]:
        return await self.backend.list_keys()
```

- [ ] **Step 3: Create session/__init__.py**

```python
from llm_harness.core.session.session import Session
from llm_harness.core.session.manager import SessionManager

__all__ = ["Session", "SessionManager"]
```

- [ ] **Step 4: Verify and commit**

```bash
cd E:/work-space/llm-harness && uv run python -c "
import asyncio, tempfile
from pathlib import Path
from llm_harness.adapters.session import FileSessionBackend
from llm_harness.core.session import SessionManager

async def test():
    d = tempfile.mkdtemp()
    backend = FileSessionBackend(Path(d))
    sm = SessionManager(backend)
    s = await sm.get_or_create('cli:user-a')
    s.add_message('user', 'hello')
    await sm.save(s)
    sm.invalidate('cli:user-a')
    s2 = await sm.get_or_create('cli:user-a')
    assert len(s2.messages) == 1
    assert s2.messages[0]['content'] == 'hello'
    print('OK')
asyncio.run(test())
" && git add -A && git commit -m "feat: add Session data class + SessionManager" -m "Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 6: Tool System Base

**Files:**
- Create: `src/llm_harness/core/tools/__init__.py`
- Create: `src/llm_harness/core/tools/base.py`

- [ ] **Step 1: Create tools/base.py**

Copy `E:\work-space\agent-harness\src\agent_harness\tools\base.py` in full. Replace `from agent_harness.` with `from llm_harness.`. This file provides `ToolExecutionContext`, `ToolResult`, `BaseTool`, `ToolRegistry`.

- [ ] **Step 2: Verify ToolRegistry knows register, lookup, to_api_schema**

```bash
cd E:/work-space/llm-harness && uv run python -c "
from llm_harness.core.tools.base import ToolRegistry, BaseTool, ToolResult, ToolExecutionContext
from pydantic import BaseModel
class FakeTool(BaseTool):
    name='test'; description='test tool'; input_model=BaseModel
    async def execute(self, args, ctx): return ToolResult(output='ok')
r = ToolRegistry()
r.register(FakeTool())
schema = r.to_api_schema('anthropic')
assert len(schema) == 1
print('OK')
" && git add -A && git commit -m "feat: add tool system base (BaseTool, ToolRegistry, ToolResult)" -m "Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 7: Permissions

**Files:**
- Create: `src/llm_harness/core/permissions/__init__.py`
- Create: `src/llm_harness/core/permissions/modes.py`
- Create: `src/llm_harness/core/permissions/settings.py`
- Create: `src/llm_harness/core/permissions/checker.py`

- [ ] **Step 1–3: Copy permission modules from agent-harness**

Copy `modes.py`, `settings.py`, `checker.py` from `E:\work-space\agent-harness\src\agent_harness\permissions\`. Replace all `from agent_harness.` with `from llm_harness.`.

- [ ] **Step 4: Create permissions/__init__.py**

```python
from llm_harness.core.permissions.checker import PermissionChecker, PermissionDecision
from llm_harness.core.permissions.modes import PermissionMode
from llm_harness.core.permissions.settings import PermissionSettings

__all__ = ["PermissionChecker", "PermissionDecision", "PermissionMode", "PermissionSettings"]
```

- [ ] **Step 5: Verify and commit**

```bash
cd E:/work-space/llm-harness && uv run python -c "from llm_harness.core.permissions import PermissionChecker, PermissionMode; print('OK')" && git add -A && git commit -m "feat: add permissions system" -m "Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 8: ObservabilityBackend Protocol + Default Implementation

**Files:**
- Create: `src/llm_harness/adapters/observability/__init__.py`
- Create: `src/llm_harness/adapters/observability/backend.py`
- Create: `src/llm_harness/adapters/observability/events.py`
- Create: `src/llm_harness/adapters/observability/default.py`

- [ ] **Step 1: Create observability/backend.py**

```python
"""ObservabilityBackend Protocol."""

from __future__ import annotations

from typing import Any, Awaitable, Callable, Protocol, runtime_checkable

EventPayload = dict[str, Any]
EventHandler = Callable[[str, EventPayload], Awaitable[None]]


@runtime_checkable
class ObservabilityBackend(Protocol):
    async def emit(self, event_type: str, payload: EventPayload) -> None: ...
    async def subscribe(self, event_type: str, handler: EventHandler) -> None: ...
    async def unsubscribe(self, event_type: str, handler: EventHandler) -> None: ...
```

- [ ] **Step 2: Create observability/events.py — 17 event types from agent-harness**

Copy from `E:\work-space\agent-harness\src\agent_harness\observability\events.py`, replacing package imports. Contains: `MessageReceived`, `AssistantTextDelta`, `AssistantTurnComplete`, `ToolExecutionStarted`, `ToolExecutionCompleted`, `LoopIteration`, `SessionOpened`, `SessionClosed`, `SubagentSpawned`, `SubagentCompleted`, `ErrorEvent`, etc.

- [ ] **Step 3: Create observability/default.py**

```python
"""Default observability backend: in-memory EventBus + JSONL Tracker."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from llm_harness.adapters.observability.backend import EventHandler, ObservabilityBackend

logger = logging.getLogger(__name__)


class DefaultObservabilityBackend:
    def __init__(self, track_dir: Path | None = None):
        self._subscribers: dict[str, list[EventHandler]] = {}
        self._track_dir = Path(track_dir) if track_dir else None
        if self._track_dir:
            self._track_dir.mkdir(parents=True, exist_ok=True)
        self._track_lock = asyncio.Lock()

    async def emit(self, event_type: str, payload: dict[str, Any]) -> None:
        try:
            for handler in self._subscribers.get(event_type, []):
                try:
                    await handler(event_type, payload)
                except Exception:
                    logger.debug("Event handler failed", exc_info=True)
            if self._track_dir:
                async with self._track_lock:
                    with open(self._track_dir / "events.jsonl", "a", encoding="utf-8") as f:
                        f.write(json.dumps({"type": event_type, "payload": payload, "ts": __import__("datetime").datetime.now().isoformat()}, ensure_ascii=False, default=str) + "\n")
        except Exception:
            logger.debug("emit failed", exc_info=True)

    async def subscribe(self, event_type: str, handler: EventHandler) -> None:
        self._subscribers.setdefault(event_type, []).append(handler)

    async def unsubscribe(self, event_type: str, handler: EventHandler) -> None:
        handlers = self._subscribers.get(event_type, [])
        if handler in handlers:
            handlers.remove(handler)
```

- [ ] **Step 4: Create observability/__init__.py**

```python
from llm_harness.adapters.observability.backend import ObservabilityBackend, EventHandler, EventPayload
from llm_harness.adapters.observability.default import DefaultObservabilityBackend

__all__ = ["ObservabilityBackend", "DefaultObservabilityBackend", "EventHandler", "EventPayload"]
```

- [ ] **Step 5: Verify and commit**

```bash
cd E:/work-space/llm-harness && uv run python -c "
import asyncio
from llm_harness.adapters.observability import DefaultObservabilityBackend

async def test():
    events = []
    async def handler(t, p): events.append((t, p))
    b = DefaultObservabilityBackend()
    await b.subscribe('test', handler)
    await b.emit('test', {'msg': 'hello'})
    assert len(events) == 1
    assert events[0][1]['msg'] == 'hello'
    print('OK')
asyncio.run(test())
" && git add -A && git commit -m "feat: add ObservabilityBackend protocol + default EventBus+JSONL implementation" -m "Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 9: LLM Provider Base + Registry

**Files:**
- Create: `src/llm_harness/adapters/providers/__init__.py`
- Create: `src/llm_harness/adapters/providers/base.py`
- Create: `src/llm_harness/adapters/providers/registry.py`
- Create: `src/llm_harness/adapters/providers/anthropic_provider.py`
- Create: `src/llm_harness/adapters/providers/openai_compat_provider.py`

- [ ] **Step 1: Copy provider modules**

Copy `base.py`, `registry.py` from `E:\work-space\agent-harness\src\agent_harness\providers\`. Replace all `from agent_harness.` with `from llm_harness.`.

In `base.py`, add `api_format` property:
```python
class LLMProvider(ABC):
    @property
    def api_format(self) -> str:
        return "anthropic"
```

In `openai_compat_provider.py`, override:
```python
class OpenAICompatProvider(LLMProvider):
    @property
    def api_format(self) -> str:
        return "openai"
```

- [ ] **Step 2: Copy Anthropic + OpenAI-compat providers**

Copy `anthropic_provider.py`, `openai_compat_provider.py` from agent-harness. Replace imports.

- [ ] **Step 3: Create providers/__init__.py**

```python
from llm_harness.adapters.providers.base import LLMProvider, ChatResponse, ToolCall
from llm_harness.adapters.providers.registry import detect_provider, find_by_name, ProviderSpec

__all__ = ["LLMProvider", "ChatResponse", "ToolCall", "detect_provider", "find_by_name", "ProviderSpec"]
```

- [ ] **Step 4: Verify api_format and commit**

```bash
cd E:/work-space/llm-harness && uv run python -c "from llm_harness.adapters.providers.base import LLMProvider; p=LLMProvider(); assert p.api_format=='anthropic'; print('OK')" && git add -A && git commit -m "feat: add LLM providers with api_format property" -m "Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 10: Memory System — Backend Protocol + File Backend + Policies + Consolidator

**Files:**
- Create: `src/llm_harness/adapters/memory/__init__.py`
- Create: `src/llm_harness/adapters/memory/backend.py`
- Create: `src/llm_harness/adapters/memory/file.py`
- Create: `src/llm_harness/adapters/memory/policy.py`
- Create: `src/llm_harness/adapters/memory/consolidator.py`

- [ ] **Step 1: Create memory/backend.py — MemoryBackend Protocol**

```python
"""MemoryBackend Protocol."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

MEMORY_SECTION_MEMORY = "memory"
MEMORY_SECTION_RULES = "rules"
MEMORY_SECTION_PERSONA = "persona"
MEMORY_SECTION_USER = "user"


@runtime_checkable
class MemoryBackend(Protocol):
    async def get_context(self, namespace: str) -> str: ...
    async def read_section(self, namespace: str, section: str) -> str: ...
    async def append_section(self, namespace: str, section: str, entry: str) -> None: ...
    async def add_history(self, namespace: str, entry: str) -> None: ...
    async def consolidate(self, namespace: str, messages: list[dict[str, Any]], provider: Any = None, model: str = "") -> bool: ...
```

- [ ] **Step 2: Create memory/file.py — FileMemoryBackend**

```python
"""File-based memory backend."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from llm_harness.adapters.memory.backend import (
    MEMORY_SECTION_MEMORY, MEMORY_SECTION_PERSONA,
    MEMORY_SECTION_RULES, MEMORY_SECTION_USER, MemoryBackend,
)

logger = logging.getLogger(__name__)

_SECTION_FILE_MAP = {
    MEMORY_SECTION_MEMORY: "MEMORY.md",
    MEMORY_SECTION_RULES: "AGENTS.md",
    MEMORY_SECTION_PERSONA: "SOUL.md",
    MEMORY_SECTION_USER: "USER.md",
}


class FileMemoryBackend:
    def __init__(self, base_dir: Path):
        self.base_dir = Path(base_dir)

    def _dir(self, namespace: str) -> Path:
        safe = namespace.replace(":", "_").replace("\\", "_").replace("/", "_")
        d = self.base_dir / safe
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _path(self, namespace: str, section: str) -> Path:
        name = _SECTION_FILE_MAP.get(section, f"{section}.md")
        return self._dir(namespace) / name

    async def get_context(self, namespace: str) -> str:
        blocks = []
        for section, filename in _SECTION_FILE_MAP.items():
            p = self._dir(namespace) / filename
            content = p.read_text(encoding="utf-8") if p.exists() else ""
            blocks.append(f"## {filename}\n{content}" if content else f"## {filename}\n(empty)")
        return "\n\n".join(blocks)

    async def read_section(self, namespace: str, section: str) -> str:
        p = self._path(namespace, section)
        return p.read_text(encoding="utf-8") if p.exists() else ""

    async def append_section(self, namespace: str, section: str, entry: str) -> None:
        p = self._path(namespace, section)
        with open(p, "a", encoding="utf-8") as f:
            f.write(entry.rstrip() + "\n\n")

    async def add_history(self, namespace: str, entry: str) -> None:
        p = self._dir(namespace) / "history.jsonl"
        with open(p, "a", encoding="utf-8") as f:
            f.write(entry.rstrip() + "\n\n")

    async def consolidate(self, namespace: str, messages: list[dict[str, Any]], provider: Any = None, model: str = "") -> bool:
        if not messages:
            return True
        if provider is None:
            return await self._raw_archive(namespace, messages)
        try:
            formatted = "\n".join(
                f"[{m.get('timestamp', '?')[:16]}] {m.get('role', '?').upper()}: {m.get('content', '')}"
                for m in messages if m.get("content")
            )
            prompt = f"""Process this conversation into structured memory.

## Current Memory State
### AGENTS.md
{await self.read_section(namespace, MEMORY_SECTION_RULES)}
### SOUL.md
{await self.read_section(namespace, MEMORY_SECTION_PERSONA)}
### MEMORY.md
{await self.read_section(namespace, MEMORY_SECTION_MEMORY)}
### USER.md
{await self.read_section(namespace, MEMORY_SECTION_USER)}

## Conversation
{formatted}"""
            chat = [{"role": "system", "content": "You are a memory consolidation agent."},
                    {"role": "user", "content": prompt}]
            tool = [{"type": "function", "function": {"name": "save_memory", "description": "Save structured memory.",
                "parameters": {"type": "object", "properties": {
                    "agents_update": {"type": ["string", "null"]},
                    "soul_update": {"type": ["string", "null"]},
                    "memory_update": {"type": "string"},
                    "user_update": {"type": ["string", "null"]},
                    "history_entry": {"type": "string"},
                }, "required": ["memory_update", "history_entry"]}}}]]
            resp = await provider.chat_with_retry(messages=chat, tools=tool, model=model,
                tool_choice={"type": "function", "function": {"name": "save_memory"}})
            if not resp.has_tool_calls:
                return await self._raw_archive(namespace, messages)
            args = resp.tool_calls[0].arguments
            if isinstance(args, str):
                args = json.loads(args)
            field_map = {"agents_update": MEMORY_SECTION_RULES, "soul_update": MEMORY_SECTION_PERSONA,
                         "memory_update": MEMORY_SECTION_MEMORY, "user_update": MEMORY_SECTION_USER}
            for field, section in field_map.items():
                val = args.get(field)
                if val and str(val).strip():
                    await self._write_section_content(namespace, section, str(val))
            hist = args.get("history_entry", "")
            if hist:
                await self.add_history(namespace, str(hist))
            return True
        except Exception:
            logger.exception("LLM consolidation failed")
            return await self._raw_archive(namespace, messages)

    async def _raw_archive(self, namespace: str, messages: list[dict]) -> bool:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M")
        content = "\n".join(f"[{ts}] [RAW] {m.get('role', '?')}: {m.get('content', '')}" for m in messages if m.get('content'))
        await self.add_history(namespace, content)
        return True

    async def _write_section_content(self, namespace: str, section: str, content: str) -> None:
        p = self._path(namespace, section)
        p.write_text(content, encoding="utf-8")  # Overwrite with LLM-composed full version
```

- [ ] **Step 3: Create memory/policy.py**

```python
"""Consolidation policies."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from llm_harness.core.session.session import Session


@dataclass
class TokenBudgetPolicy:
    context_window_tokens: int
    max_completion_tokens: int = 4096
    safety_buffer: int = 1024

    async def should_consolidate(self, session: Session, consolidator: Any) -> list[dict[str, Any]] | None:
        budget = self.context_window_tokens - self.max_completion_tokens - self.safety_buffer
        estimated, _ = await consolidator.estimate_session_prompt_tokens(session)
        if estimated < budget:
            return None
        boundary = consolidator.pick_consolidation_boundary(session, max(1, estimated - budget // 2))
        if boundary is None:
            return None
        chunk = session.messages[session.last_consolidated:boundary[0]]
        return chunk if chunk else None


@dataclass
class MessageCountPolicy:
    max_messages: int = 50

    async def should_consolidate(self, session: Session, consolidator: Any) -> list[dict[str, Any]] | None:
        active = session.messages[session.last_consolidated:]
        if len(active) <= self.max_messages:
            return None
        target = len(session.messages) - self.max_messages
        cut = session.last_consolidated
        for i in range(target, len(session.messages)):
            if session.messages[i].get("role") == "user":
                cut = i
                break
        if cut <= session.last_consolidated:
            return None
        return session.messages[session.last_consolidated:cut]
```

- [ ] **Step 4: Create memory/consolidator.py — MemoryConsolidator**

```python
"""MemoryConsolidator — owns consolidation policy and session offset management."""

from __future__ import annotations

import asyncio
import logging
import weakref
from collections.abc import Awaitable
from typing import Any, Callable

from llm_harness.adapters.memory.backend import MemoryBackend
from llm_harness.adapters.memory.policy import TokenBudgetPolicy
from llm_harness.core.session.session import Session
from llm_harness.core.session.manager import SessionManager

logger = logging.getLogger(__name__)


def estimate_message_tokens(message: dict) -> int:
    content = message.get("content", "")
    if isinstance(content, str):
        return len(content) // 4
    if isinstance(content, list):
        return sum(len(str(item)) // 4 for item in content)
    return 0


class MemoryConsolidator:
    MAX_CONSOLIDATION_ROUNDS = 5

    def __init__(
        self,
        backend: MemoryBackend,
        sessions: SessionManager,
        context_window_tokens: int,
        build_messages: Callable[..., list[dict[str, Any]] | Awaitable[list[dict[str, Any]]]],
        get_tool_definitions: Callable[[], list[dict[str, Any]]],
        max_completion_tokens: int = 4096,
        policy: object = None,
    ):
        self.backend = backend
        self.sessions = sessions
        self.context_window_tokens = context_window_tokens
        self.max_completion_tokens = max_completion_tokens
        self._build_messages = build_messages
        self._get_tool_definitions = get_tool_definitions
        self._policy = policy or TokenBudgetPolicy(context_window_tokens=context_window_tokens, max_completion_tokens=max_completion_tokens)
        self._locks: weakref.WeakValueDictionary[str, asyncio.Lock] = weakref.WeakValueDictionary()

    def get_lock(self, session_key: str) -> asyncio.Lock:
        return self._locks.setdefault(session_key, asyncio.Lock())

    def pick_consolidation_boundary(self, session: Session, tokens_to_remove: int) -> tuple[int, int] | None:
        start = session.last_consolidated
        if start >= len(session.messages) or tokens_to_remove <= 0:
            return None
        removed = 0
        last = None
        for idx in range(start, len(session.messages)):
            msg = session.messages[idx]
            if idx > start and msg.get("role") == "user":
                last = (idx, removed)
                if removed >= tokens_to_remove:
                    return last
            removed += estimate_message_tokens(msg)
        return last

    async def estimate_session_prompt_tokens(self, session: Session) -> tuple[int, str]:
        history = session.get_history(max_messages=0)
        channel, chat_id = (session.key.split(":", 1) if ":" in session.key else (None, None))
        probe = self._build_messages(history=history, current_message="[token-probe]", channel=channel, chat_id=chat_id)
        if asyncio.iscoroutine(probe):
            probe = await probe
        msg_tokens = sum(estimate_message_tokens(m) for m in probe)
        tool_tokens = sum(len(str(t)) // 4 for t in self._get_tool_definitions())
        return msg_tokens + tool_tokens, "estimate"

    async def maybe_consolidate(self, session: Session) -> None:
        """Try to consolidate old messages. Called between user messages, NOT during ReAct loop."""
        if not session.messages or self.context_window_tokens <= 0:
            return
        lock = self.get_lock(session.key)
        async with lock:
            for _ in range(self.MAX_CONSOLIDATION_ROUNDS):
                chunk = await self._policy.should_consolidate(session, self)
                if chunk is None or not chunk:
                    return
                logger.info("Consolidating %s messages for %s", len(chunk), session.key)
                ok = await self.backend.consolidate(session.key, chunk)
                if not ok:
                    return
                session.remove_before(session.last_consolidated + len(chunk))
                await self.sessions.save(session)
```

- [ ] **Step 5: Create memory/__init__.py**

```python
from llm_harness.adapters.memory.backend import MemoryBackend, MEMORY_SECTION_MEMORY, MEMORY_SECTION_RULES, MEMORY_SECTION_PERSONA, MEMORY_SECTION_USER
from llm_harness.adapters.memory.file import FileMemoryBackend
from llm_harness.adapters.memory.policy import TokenBudgetPolicy, MessageCountPolicy
from llm_harness.adapters.memory.consolidator import MemoryConsolidator

__all__ = ["MemoryBackend", "FileMemoryBackend", "TokenBudgetPolicy", "MessageCountPolicy", "MemoryConsolidator",
           "MEMORY_SECTION_MEMORY", "MEMORY_SECTION_RULES", "MEMORY_SECTION_PERSONA", "MEMORY_SECTION_USER"]
```

- [ ] **Step 6: Verify and commit**

```bash
cd E:/work-space/llm-harness && uv run python -c "
import asyncio, tempfile
from pathlib import Path
from llm_harness.adapters.memory import FileMemoryBackend

async def test():
    d = tempfile.mkdtemp()
    b = FileMemoryBackend(Path(d))
    await b.append_section('test:1', 'memory', 'fact 1')
    await b.append_section('test:1', 'memory', 'fact 2')
    ctx = await b.get_context('test:1')
    assert 'fact 1' in ctx and 'fact 2' in ctx
    ok = await b.consolidate('test:1', [{'role':'user','content':'hello'}])
    assert ok
    print('OK')
asyncio.run(test())
" && git add -A && git commit -m "feat: add memory system (protocol + file backend + policies + consolidator)" -m "Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 11: Memory — TencentDB Adapter

**Files:**
- Create: `src/llm_harness/adapters/memory/tencentdb.py`

- [ ] **Step 1: Create TencentDBMemoryBackend with double-check locking**

```python
"""TencentDB Agent Memory adapter — HTTP to localhost:8420."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from llm_harness.adapters.memory.backend import MemoryBackend

logger = logging.getLogger(__name__)


class TencentDBMemoryBackend:
    def __init__(self, base_url: str = "http://localhost:8420", timeout: float = 30.0):
        self.base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._client: httpx.AsyncClient | None = None
        self._client_lock = asyncio.Lock()

    async def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is not None:
            return self._client
        async with self._client_lock:
            if self._client is not None:
                return self._client
            self._client = httpx.AsyncClient(timeout=self._timeout)
            return self._client

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    async def get_context(self, namespace: str) -> str:
        client = await self._ensure_client()
        try:
            resp = await client.get(f"{self.base_url}/memory/{namespace}/context")
            resp.raise_for_status()
            data = resp.json()
            return data.get("context", data.get("content", str(data)))
        except Exception:
            logger.debug("TencentDB get_context failed", exc_info=True)
            return ""

    async def read_section(self, namespace: str, section: str) -> str:
        client = await self._ensure_client()
        try:
            resp = await client.get(f"{self.base_url}/memory/{namespace}/{section}")
            resp.raise_for_status()
            return resp.json().get("content", "")
        except Exception:
            logger.debug("TencentDB read_section failed", exc_info=True)
            return ""

    async def append_section(self, namespace: str, section: str, entry: str) -> None:
        client = await self._ensure_client()
        try:
            await client.post(f"{self.base_url}/memory/{namespace}/{section}", json={"entry": entry})
        except Exception:
            logger.warning("TencentDB append_section failed", exc_info=True)

    async def add_history(self, namespace: str, entry: str) -> None:
        client = await self._ensure_client()
        try:
            await client.post(f"{self.base_url}/memory/{namespace}/history", json={"entry": entry})
        except Exception:
            logger.warning("TencentDB add_history failed", exc_info=True)

    async def consolidate(self, namespace: str, messages: list[dict[str, Any]], provider: Any = None, model: str = "") -> bool:
        client = await self._ensure_client()
        try:
            resp = await client.post(f"{self.base_url}/memory/{namespace}/ingest", json={"messages": messages})
            resp.raise_for_status()
            return True
        except Exception:
            logger.exception("TencentDB consolidation failed")
            return False
```

- [ ] **Step 2: Update memory/__init__.py**

Add import: `from llm_harness.adapters.memory.tencentdb import TencentDBMemoryBackend`

Add to `__all__`: `"TencentDBMemoryBackend"`

- [ ] **Step 3: Verify and commit**

```bash
cd E:/work-space/llm-harness && uv run python -c "from llm_harness.adapters.memory import TencentDBMemoryBackend; print('OK')" && git add -A && git commit -m "feat: add TencentDB Agent Memory adapter" -m "Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 12: SandboxBackend Protocol + OpenSandbox Adapter

**Files:**
- Create: `src/llm_harness/adapters/sandbox/__init__.py`
- Create: `src/llm_harness/adapters/sandbox/backend.py`
- Create: `src/llm_harness/adapters/sandbox/opensandbox.py`

- [ ] **Step 1: Create sandbox/backend.py**

```python
"""SandboxBackend Protocol — file operations + exec, all via sandbox."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass
class SandboxSession:
    session_key: str
    volume_path: str     # Container mount path (what LLM sees)
    sandbox_id: str      # Backend-internal identifier


@dataclass
class ExecResult:
    output: str
    exit_code: int = 0
    is_error: bool = False


@runtime_checkable
class SandboxBackend(Protocol):
    async def create_session(self, session_key: str) -> SandboxSession: ...
    async def destroy_session(self, session_key: str) -> None: ...
    async def read_file(self, session_key: str, path: str) -> str: ...
    async def write_file(self, session_key: str, path: str, content: str) -> None: ...
    async def list_dir(self, session_key: str, path: str) -> list[str]: ...
    async def glob(self, session_key: str, pattern: str) -> list[str]: ...
    async def grep(self, session_key: str, pattern: str, path: str) -> list[str]: ...
    async def execute(self, session_key: str, command: str, *, cwd: str = "/workspace", env: dict | None = None, timeout: int = 60) -> ExecResult: ...
```

- [ ] **Step 2: Create sandbox/opensandbox.py — OpenSandbox adapter with double-check locking**

```python
"""OpenSandbox adapter — container + volume isolation."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from llm_harness.adapters.sandbox.backend import ExecResult, SandboxBackend, SandboxSession

logger = logging.getLogger(__name__)


class OpenSandboxBackend:
    def __init__(self, base_url: str = "http://localhost:8080", timeout: float = 30.0):
        self.base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._client: httpx.AsyncClient | None = None
        self._client_lock = asyncio.Lock()
        self._sessions: dict[str, SandboxSession] = {}

    async def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is not None:
            return self._client
        async with self._client_lock:
            if self._client is not None:
                return self._client
            self._client = httpx.AsyncClient(timeout=self._timeout)
            return self._client

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    async def create_session(self, session_key: str) -> SandboxSession:
        client = await self._ensure_client()
        resp = await client.post(f"{self.base_url}/sandboxes", json={"name": session_key.replace(":", "-")})
        resp.raise_for_status()
        data = resp.json()
        session = SandboxSession(
            session_key=session_key,
            volume_path=data.get("mount_path", "/workspace"),
            sandbox_id=data.get("sandbox_id", session_key),
        )
        self._sessions[session_key] = session
        return session

    async def destroy_session(self, session_key: str) -> None:
        session = self._sessions.pop(session_key, None)
        if session is None:
            return
        client = await self._ensure_client()
        try:
            await client.delete(f"{self.base_url}/sandboxes/{session.sandbox_id}")
        except Exception:
            logger.warning("Failed to destroy sandbox", exc_info=True)

    async def read_file(self, session_key: str, path: str) -> str:
        session = self._sessions.get(session_key)
        if not session:
            return f"Error: session {session_key} not found"
        client = await self._ensure_client()
        resp = await client.get(f"{self.base_url}/sandboxes/{session.sandbox_id}/files", params={"path": path})
        resp.raise_for_status()
        return resp.text

    async def write_file(self, session_key: str, path: str, content: str) -> None:
        session = self._sessions.get(session_key)
        if not session:
            return
        client = await self._ensure_client()
        await client.post(f"{self.base_url}/sandboxes/{session.sandbox_id}/files", json={"path": path, "content": content})

    async def list_dir(self, session_key: str, path: str) -> list[str]:
        session = self._sessions.get(session_key)
        if not session:
            return []
        client = await self._ensure_client()
        resp = await client.get(f"{self.base_url}/sandboxes/{session.sandbox_id}/files/list", params={"path": path})
        return resp.json() if resp.status_code == 200 else []

    async def glob(self, session_key: str, pattern: str) -> list[str]:
        session = self._sessions.get(session_key)
        if not session:
            return []
        client = await self._ensure_client()
        resp = await client.get(f"{self.base_url}/sandboxes/{session.sandbox_id}/files/glob", params={"pattern": pattern})
        return resp.json() if resp.status_code == 200 else []

    async def grep(self, session_key: str, pattern: str, path: str) -> list[str]:
        session = self._sessions.get(session_key)
        if not session:
            return []
        client = await self._ensure_client()
        resp = await client.get(f"{self.base_url}/sandboxes/{session.sandbox_id}/files/grep", params={"pattern": pattern, "path": path})
        return resp.json() if resp.status_code == 200 else []

    async def execute(self, session_key: str, command: str, *, cwd: str = "/workspace", env: dict[str, str] | None = None, timeout: int = 60) -> ExecResult:
        session = self._sessions.get(session_key)
        if not session:
            return ExecResult(output=f"Error: session {session_key} not found", exit_code=1, is_error=True)
        client = await self._ensure_client()
        try:
            resp = await client.post(
                f"{self.base_url}/sandboxes/{session.sandbox_id}/exec",
                json={"command": command, "cwd": cwd, "env": env or {}, "timeout": timeout},
            )
            resp.raise_for_status()
            data = resp.json()
            return ExecResult(output=data.get("output", ""), exit_code=data.get("exit_code", 0))
        except httpx.HTTPError as e:
            return ExecResult(output=f"Sandbox error: {e}", exit_code=1, is_error=True)
```

- [ ] **Step 3: Create sandbox/__init__.py**

```python
from llm_harness.adapters.sandbox.backend import SandboxBackend, SandboxSession, ExecResult
from llm_harness.adapters.sandbox.opensandbox import OpenSandboxBackend

__all__ = ["SandboxBackend", "SandboxSession", "ExecResult", "OpenSandboxBackend"]
```

- [ ] **Step 4: Verify and commit**

```bash
cd E:/work-space/llm-harness && uv run python -c "from llm_harness.adapters.sandbox import SandboxBackend, OpenSandboxBackend; print('OK')" && git add -A && git commit -m "feat: add sandbox system (protocol + OpenSandbox adapter)" -m "Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 13: Swarm Sub-Agent System

**Files (6 files):**

- [ ] **Step 1: Create swarm/backend.py — AgentBackend Protocol**

```python
"""AgentBackend Protocol for sub-agent execution."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass
class SpawnConfig:
    agent_name: str
    prompt: str
    tool_names: list[str]
    model: str = ""


@dataclass
class SpawnResult:
    agent_id: str
    success: bool = True
    error: str | None = None


@runtime_checkable
class AgentBackend(Protocol):
    async def spawn(self, config: SpawnConfig) -> SpawnResult: ...
    async def send_message(self, agent_id: str, message: str) -> bool: ...
    async def stop(self, agent_id: str) -> bool: ...
```

- [ ] **Step 2: Create swarm/mailbox.py — File-based leader-worker queue**

```python
"""File-based mailbox for leader-worker message passing."""

import json
from pathlib import Path


class Mailbox:
    def __init__(self, base_dir: Path):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def put(self, agent_id: str, msg_type: str, payload: dict) -> None:
        from datetime import datetime
        ts = datetime.now().strftime("%Y%m%dT%H%M%S%f")
        inbox = self.base_dir / agent_id / "inbox"
        inbox.mkdir(parents=True, exist_ok=True)
        (inbox / f"{ts}_{msg_type}.json").write_text(json.dumps({"type": msg_type, "payload": payload, "timestamp": ts}))

    def poll(self, agent_id: str) -> list[dict]:
        inbox = self.base_dir / agent_id / "inbox"
        if not inbox.exists():
            return []
        messages = []
        for f in sorted(inbox.iterdir()):
            if f.suffix == ".json":
                try:
                    messages.append(json.loads(f.read_text()))
                    f.unlink()
                except Exception:
                    pass
        return messages
```

- [ ] **Step 3: Create swarm/definitions.py — AgentDefinition registry**

```python
"""Agent definitions — built-in sub-agent types."""

from dataclasses import dataclass, field

@dataclass
class AgentDefinition:
    name: str
    description: str
    system_prompt: str
    tools_allow: list[str] = field(default_factory=list)  # empty = inherit all
    tools_deny: list[str] = field(default_factory=list)
    tools_extra: list[str] = field(default_factory=list)
    model: str = ""


_BUILTIN: dict[str, AgentDefinition] = {
    "general-purpose": AgentDefinition(
        name="general-purpose", description="处理任何通用任务",
        system_prompt="You are a helpful AI assistant. Complete the task described in the prompt."),
    "researcher": AgentDefinition(
        name="researcher", description="搜索、收集、分析信息",
        system_prompt="You are a research agent. Gather information, analyze data, and report findings concisely."),
    "planner": AgentDefinition(
        name="planner", description="拆解复杂任务、设计方案",
        system_prompt="You are a planning agent. Decompose complex tasks into steps, identify dependencies, and design approaches."),
    "executor": AgentDefinition(
        name="executor", description="执行具体操作步骤",
        system_prompt="You are an execution agent. Follow the specified steps precisely and report results."),
    "reviewer": AgentDefinition(
        name="reviewer", description="验证、检查、对比结果",
        system_prompt="You are a review agent. Verify outputs against requirements, check for errors, report pass/fail with evidence."),
}


def get_definition(name: str) -> AgentDefinition | None:
    return _BUILTIN.get(name)

def list_definitions() -> list[AgentDefinition]:
    return list(_BUILTIN.values())

def register_definition(defn: AgentDefinition) -> None:
    _BUILTIN[defn.name] = defn
```

- [ ] **Step 4: Create swarm/subprocess.py — SubprocessBackend**

```python
"""Subprocess-based agent backend — each agent as an independent OS process."""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

from llm_harness.core.bus.events import InboundMessage
from llm_harness.core.bus.queue import MessageBus
from llm_harness.core.swarm.backend import AgentBackend, SpawnConfig, SpawnResult
from llm_harness.core.swarm.mailbox import Mailbox

logger = logging.getLogger(__name__)


class SubprocessBackend:
    def __init__(self, bus: MessageBus, skills_path: str = "", mailbox: Mailbox | None = None):
        self.bus = bus
        self.skills_path = skills_path
        self.mailbox = mailbox or Mailbox(Path.home() / ".llm-harness" / "mail")
        self._processes: dict[str, asyncio.subprocess.Process] = {}
        self._session_keys: dict[str, str] = {}  # agent_id -> origin session_key

    async def spawn(self, config: SpawnConfig, origin_session_key: str = "") -> SpawnResult:
        agent_id = f"{config.agent_name}-{os.urandom(4).hex()}"
        env = os.environ.copy()
        env["LLM_HARNESS_WORKER"] = "1"
        env["LLM_HARNESS_AGENT_NAME"] = config.agent_name

        cmd = [sys.executable, "-m", "llm_harness", "--worker",
               "--agent-def", config.agent_name,
               "--tools", ",".join(config.tool_names)]
        if self.skills_path:
            cmd.extend(["--skills-path", self.skills_path])

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd, stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
            self._processes[agent_id] = proc
            self._session_keys[agent_id] = origin_session_key
            if proc.stdin:
                proc.stdin.write(config.prompt.encode() + b"\n")
                await proc.stdin.drain()
                proc.stdin.close()

            asyncio.create_task(self._watch(agent_id, proc))
            return SpawnResult(agent_id=agent_id)
        except Exception as e:
            return SpawnResult(agent_id=agent_id, success=False, error=str(e))

    async def _watch(self, agent_id: str, proc: asyncio.subprocess.Process) -> None:
        try:
            await proc.wait()
            stdout = await proc.stdout.read() if proc.stdout else b""
            result = stdout.decode("utf-8", errors="replace")
            origin_key = self._session_keys.get(agent_id, "")
            if origin_key:
                channel, chat_id = origin_key.split(":", 1) if ":" in origin_key else ("system", origin_key)
            else:
                channel, chat_id = "system", agent_id
            msg = InboundMessage(
                channel="system", sender_id=agent_id,
                chat_id=f"{channel}:{chat_id}" if channel != "system" else chat_id,
                content=f"<task-notification><task_id>{agent_id}</task_id><status>{'completed' if proc.returncode==0 else 'failed'}</status><result>{result}</result></task-notification>",
            )
            await self.bus.publish_inbound(msg)
        except Exception:
            logger.exception("Watcher failed for %s", agent_id)
        finally:
            self._processes.pop(agent_id, None)

    async def send_message(self, agent_id: str, message: str) -> bool:
        if agent_id not in self._processes:
            return False
        self.mailbox.put(agent_id, "user_message", {"content": message})
        return True

    async def stop(self, agent_id: str) -> bool:
        proc = self._processes.pop(agent_id, None)
        if proc is None:
            return False
        if proc.returncode is None:
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
        return True
```

- [ ] **Step 5: Create swarm/in_process.py — InProcessBackend**

```python
"""In-process agent backend — asyncio Task with ContextVar isolation."""

from __future__ import annotations

import asyncio
import contextvars
import logging
import os
from pathlib import Path

from llm_harness.core.swarm.backend import AgentBackend, SpawnConfig, SpawnResult
from llm_harness.core.swarm.mailbox import Mailbox

logger = logging.getLogger(__name__)


class InProcessBackend:
    def __init__(self, mailbox: Mailbox | None = None):
        self.mailbox = mailbox or Mailbox(Path.home() / ".llm-harness" / "mail")
        self._tasks: dict[str, asyncio.Task] = {}
        self._loop_fn: callable | None = None

    def set_loop_fn(self, fn: callable) -> None:
        self._loop_fn = fn

    async def spawn(self, config: SpawnConfig, origin_session_key: str = "") -> SpawnResult:
        if self._loop_fn is None:
            return SpawnResult(agent_id="", success=False, error="No loop_fn configured")
        agent_id = f"{config.agent_name}-{os.urandom(4).hex()}"
        task = asyncio.create_task(self._loop_fn(config.prompt, agent_id, config.agent_name, config.tool_names))
        self._tasks[agent_id] = task
        return SpawnResult(agent_id=agent_id)

    async def send_message(self, agent_id: str, message: str) -> bool:
        if agent_id not in self._tasks or self._tasks[agent_id].done():
            return False
        self.mailbox.put(agent_id, "user_message", {"content": message})
        return True

    async def stop(self, agent_id: str) -> bool:
        task = self._tasks.pop(agent_id, None)
        if task and not task.done():
            task.cancel()
        return task is not None
```

- [ ] **Step 6: Create swarm/__init__.py**

```python
from llm_harness.core.swarm.backend import AgentBackend, SpawnConfig, SpawnResult
from llm_harness.core.swarm.definitions import AgentDefinition, get_definition, list_definitions, register_definition
from llm_harness.core.swarm.mailbox import Mailbox
from llm_harness.core.swarm.subprocess import SubprocessBackend
from llm_harness.core.swarm.in_process import InProcessBackend

__all__ = ["AgentBackend", "SpawnConfig", "SpawnResult", "AgentDefinition",
           "get_definition", "list_definitions", "register_definition",
           "Mailbox", "SubprocessBackend", "InProcessBackend"]
```

- [ ] **Step 7: Verify and commit**

```bash
cd E:/work-space/llm-harness && uv run python -c "from llm_harness.core.swarm import SubprocessBackend, InProcessBackend, AgentDefinition, get_definition; d=get_definition('researcher'); assert d.name=='researcher'; print('OK')" && git add -A && git commit -m "feat: add swarm sub-agent system (dual backend + mailbox + agent definitions)" -m "Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 14: Built-in Tools (Extracted from agent-harness)

**Files:** Copy and adapt from `E:\work-space\agent-harness\src\agent_harness\tools\`.

All file tools now go through SandboxBackend. Batch this into 4 groups:

- [ ] **Step 1: File tools via SandboxBackend**

Create `read_file.py`, `write_file.py`, `edit_file.py`, `glob.py`, `grep.py`, `shell.py`. Each `__init__` takes `sandbox: SandboxBackend`. Execute calls corresponding sandbox method. Replace all `from agent_harness.` with `from llm_harness.`.

- [ ] **Step 2: Memory tools via MemoryBackend**

Create `memory_read.py`, `memory_write.py`. Each `__init__` takes `memory: MemoryBackend`.

- [ ] **Step 3: Agent tools via AgentBackend + bus**

Create `agent.py` (takes `swarm: AgentBackend, bus: MessageBus`), `send_message.py` (takes `swarm: AgentBackend`), reuse `task_stop_tool.py`.

- [ ] **Step 4: Independent tools (no backend dependency)**

Create `web_search.py`, `web_fetch.py`, `ask_user.py`, `notebook_edit.py`, `skill.py`, `tool_search.py`, `task_create.py`, `task_list.py`, `task_update.py`, `cron_create.py`, `cron_list.py`, `cron_delete.py`. Replace imports.

- [ ] **Step 5: Verify all tools import**

```bash
cd E:/work-space/llm-harness && uv run python -c "
from llm_harness.core.tools.base import ToolRegistry
from llm_harness.core.tools.read_file import ReadFileTool
from llm_harness.core.tools.memory_read import MemoryReadTool
from llm_harness.core.tools.agent import AgentTool
print('All tools OK')
" && git add -A && git commit -m "feat: add 20 built-in tools with backend dependency injection" -m "Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 15: AgentLoop — Pure ReAct Skeleton

**Files:**
- Create: `src/llm_harness/core/loop.py`

- [ ] **Step 1: Create loop.py — AgentLoop with callback injection**

```python
"""AgentLoop — pure ReAct skeleton. Behavior injected via callbacks."""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from llm_harness.adapters.providers.base import LLMProvider
from llm_harness.core.tools.base import ToolRegistry

logger = logging.getLogger(__name__)


@dataclass
class TurnResult:
    final_content: str | None = None
    tools_used: list[str] = field(default_factory=list)
    messages: list[dict[str, Any]] = field(default_factory=list)


class AgentLoop:
    TOOL_RESULT_MAX_CHARS = 16_000

    def __init__(
        self,
        provider: LLMProvider,
        tools: ToolRegistry,
        model: str,
        *,
        on_build_context: Callable[..., Any],
        on_tool_check: Callable[[str, Any, Any], Any],
        on_error: Callable[[Exception, str], Any],
        on_event: Callable[[str, dict], Any] | None = None,
        max_iterations: int = 40,
    ):
        self.provider = provider
        self.tools = tools
        self.model = model
        self._build_context = on_build_context
        self._check_tool = on_tool_check
        self._on_error = on_error
        self._on_event = on_event
        self.max_iterations = max_iterations

    async def run(self, msg: Any, history: list[dict[str, Any]]) -> TurnResult:
        result = TurnResult()
        messages = await self._build_context(msg, history)
        if asyncio.iscoroutine(messages):
            messages = await messages

        for _ in range(self.max_iterations):
            response = await self.provider.chat_with_retry(
                messages=messages,
                tools=self.tools.to_api_schema(self.provider.api_format),
                model=self.model,
            )

            if not response.has_tool_calls:
                result.final_content = response.content or ""
                result.messages = messages
                return result

            tool_call_dicts = [tc.to_openai_tool_call() for tc in response.tool_calls]
            messages.append({"role": "assistant", "content": response.content or "",
                             "tool_calls": tool_call_dicts})

            for tc in response.tool_calls:
                if self._on_event:
                    await self._on_event("tool:executing", {"name": tc.name})
                tool = self.tools.lookup(tc.name)
                if tool is None:
                    tool_result = f"Error: unknown tool '{tc.name}'"
                else:
                    args = tc.arguments
                    if isinstance(args, str):
                        args = json.loads(args)
                    try:
                        parsed = tool.input_model(**args)
                    except Exception as e:
                        tool_result = f"Error: invalid args for '{tc.name}': {e}"
                    else:
                        perm = await self._check_tool(tc.name, tool, parsed)
                        if hasattr(perm, 'allowed') and not perm.allowed:
                            tool_result = f"Error: Permission denied: {perm.reason}"
                        else:
                            try:
                                from llm_harness.core.tools.base import ToolExecutionContext
                                ctx = ToolExecutionContext(cwd="/workspace", metadata={})
                                r = await tool.execute(parsed, ctx)
                                tool_result = r.output
                            except Exception as e:
                                tool_result = f"Error executing '{tc.name}': {e}"

                if len(tool_result) > self.TOOL_RESULT_MAX_CHARS:
                    tool_result = tool_result[:self.TOOL_RESULT_MAX_CHARS] + f"\n... truncated"

                messages.append({"role": "tool", "tool_call_id": tc.id, "name": tc.name, "content": tool_result})
                result.tools_used.append(tc.name)

        result.final_content = "Max iterations reached."
        result.messages = messages
        return result
```

- [ ] **Step 2: Verify and commit**

```bash
cd E:/work-space/llm-harness && uv run python -c "from llm_harness.core.loop import AgentLoop, TurnResult; print('OK')" && git add -A && git commit -m "feat: add AgentLoop pure ReAct skeleton with callback injection" -m "Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 16: Agent — Session/Memory Orchestration

**Files:**
- Create: `src/llm_harness/core/agent.py`

- [ ] **Step 1: Create agent.py — orchestrates session, memory, loop**

```python
"""Agent — harness + model = runnable agent. Orchestrates session, memory, loop."""

from __future__ import annotations

import asyncio
import logging
from contextlib import nullcontext
from typing import Any

from llm_harness.core.bus.events import InboundMessage, OutboundMessage
from llm_harness.core.loop import AgentLoop
from llm_harness.core.session.manager import SessionManager
from llm_harness.adapters.memory.consolidator import MemoryConsolidator
from llm_harness.adapters.memory.backend import MemoryBackend
from llm_harness.adapters.observability.backend import ObservabilityBackend

logger = logging.getLogger(__name__)


class Agent:
    def __init__(
        self,
        loop: AgentLoop,
        sessions: SessionManager | None = None,
        consolidator: MemoryConsolidator | None = None,
        observability: ObservabilityBackend | None = None,
    ):
        self._loop = loop
        self._sessions = sessions
        self._consolidator = consolidator
        self._observability = observability
        self._session_locks: dict[str, asyncio.Lock] = {}

    async def process(self, msg: InboundMessage) -> OutboundMessage | None:
        session_key = msg.session_key
        lock = self._session_locks.setdefault(session_key, asyncio.Lock())

        async with lock:
            try:
                if self._observability:
                    await self._observability.emit("message:received", {"session_key": session_key, "content": msg.content[:200]})

                session = None
                history: list[dict[str, Any]] = []
                if self._sessions:
                    session = await self._sessions.get_or_create(session_key)
                    history = session.get_history()
                    session.add_message("user", msg.content)
                    await self._sessions.save(session)

                if self._consolidator and session:
                    await self._consolidator.maybe_consolidate(session)

                result = await self._loop.run(msg, history)

                if session:
                    self._save_turn(session, result)
                    await self._sessions.save(session)

                if self._observability:
                    await self._observability.emit("message:sent", {"session_key": session_key})

                return OutboundMessage(channel=msg.channel, chat_id=msg.chat_id, content=result.final_content or "")

            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.exception("Error processing message for %s", session_key)
                return OutboundMessage(channel=msg.channel, chat_id=msg.chat_id,
                                       content=f"Sorry, I encountered an error: {exc}")

    def _save_turn(self, session, result) -> None:
        for msg in result.messages:
            role = msg.get("role", "")
            content = msg.get("content", "")
            if role == "assistant" and not content and not msg.get("tool_calls"):
                continue
            extra = {}
            for k in ("tool_calls", "tool_call_id", "name"):
                if k in msg:
                    extra[k] = msg[k]
            session.add_message(role, content, **extra)
```

- [ ] **Step 2: Verify and commit**

```bash
cd E:/work-space/llm-harness && uv run python -c "from llm_harness.core.agent import Agent; print('OK')" && git add -A && git commit -m "feat: add Agent orchestrating session, memory consolidation, and ReAct loop" -m "Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 17: Harness — IoC Container

**Files:**
- Create: `src/llm_harness/core/harness.py`

- [ ] **Step 1: Create harness.py — URL-based resolution for all backends + tool injection**

```python
"""Harness — IoC container. Resolves backends, assembles Agent."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from llm_harness.adapters.memory.backend import MemoryBackend
from llm_harness.adapters.memory.file import FileMemoryBackend
from llm_harness.adapters.memory.tencentdb import TencentDBMemoryBackend
from llm_harness.adapters.memory.policy import TokenBudgetPolicy
from llm_harness.adapters.memory.consolidator import MemoryConsolidator
from llm_harness.adapters.sandbox.backend import SandboxBackend
from llm_harness.adapters.sandbox.opensandbox import OpenSandboxBackend
from llm_harness.adapters.session.backend import SessionBackend
from llm_harness.adapters.session.file import FileSessionBackend
from llm_harness.adapters.observability.backend import ObservabilityBackend
from llm_harness.adapters.observability.default import DefaultObservabilityBackend
from llm_harness.core.session.manager import SessionManager
from llm_harness.core.swarm.backend import AgentBackend
from llm_harness.core.swarm.subprocess import SubprocessBackend
from llm_harness.core.swarm.in_process import InProcessBackend
from llm_harness.core.bus.queue import MessageBus
from llm_harness.core.permissions.checker import PermissionChecker
from llm_harness.core.permissions.settings import PermissionSettings
from llm_harness.core.tools.base import ToolRegistry
from llm_harness.core.loop import AgentLoop
from llm_harness.core.agent import Agent

log = logging.getLogger(__name__)


class Harness:
    def __init__(
        self, *, provider: Any = None, model: str = "",
        workspace: str | Path = Path.cwd(),
        tools: list[str] | None = None,
        permissions: str = "default",
        memory: str | MemoryBackend | None = None,
        sandbox: str | SandboxBackend | None = None,
        swarm: str | AgentBackend | None = None,
        sessions: str | SessionBackend | None = None,
        observability: str | ObservabilityBackend | None = None,
        context_window_tokens: int = 64_000,
        max_completion_tokens: int = 4096,
    ):
        self.workspace = Path(workspace).expanduser().resolve()
        self.provider = provider
        self.model = model
        self.bus = MessageBus()

        self.memory = self._resolve_memory(memory)
        self.sandbox = self._resolve_sandbox(sandbox)
        self.swarm = self._resolve_swarm(swarm)
        self._session_backend = self._resolve_sessions_backend(sessions)
        self._session_manager = SessionManager(self._session_backend)
        self._observability = self._resolve_observability(observability)
        self._permissions = self._resolve_permissions(permissions)
        self._tools = self._resolve_tools(tools)
        self._consolidator = self._build_consolidator() if self.memory else None
        self._context_builder = self._build_context_builder()

    # -- Resolvers -------------------------------------------------------

    def _resolve_memory(self, memory):
        if memory is None: return None
        if isinstance(memory, MemoryBackend): return memory
        if isinstance(memory, str):
            if memory.startswith("tencentdb://"): return TencentDBMemoryBackend(memory.replace("tencentdb://", "http://"))
            if memory.startswith("file://"): return FileMemoryBackend(Path(memory.replace("file://", "")))
            return FileMemoryBackend(Path(memory))
        return FileMemoryBackend(Path(memory))

    def _resolve_sandbox(self, sandbox):
        if sandbox is None: return None
        if isinstance(sandbox, SandboxBackend): return sandbox
        if isinstance(sandbox, str):
            if sandbox == "none": return None
            if sandbox.startswith("opensandbox://"): return OpenSandboxBackend(sandbox.replace("opensandbox://", "http://"))
            if sandbox == "opensandbox": return OpenSandboxBackend()
        raise TypeError(f"Unsupported sandbox: {sandbox}")

    def _resolve_swarm(self, swarm):
        if swarm is None: return SubprocessBackend(bus=self.bus)
        if isinstance(swarm, AgentBackend): return swarm
        if isinstance(swarm, str):
            if swarm == "subprocess": return SubprocessBackend(bus=self.bus)
            if swarm == "in_process": return InProcessBackend()
        raise TypeError(f"Unsupported swarm: {swarm}")

    def _resolve_sessions_backend(self, sessions):
        if sessions is None: return FileSessionBackend(self.workspace / "sessions")
        if isinstance(sessions, SessionBackend): return sessions
        if isinstance(sessions, str): return FileSessionBackend(Path(sessions))
        raise TypeError(f"Unsupported sessions: {sessions}")

    def _resolve_observability(self, obs):
        if obs is None: return DefaultObservabilityBackend()
        if isinstance(obs, ObservabilityBackend): return obs
        if isinstance(obs, str): return DefaultObservabilityBackend(Path(obs))
        raise TypeError(f"Unsupported observability: {obs}")

    def _resolve_permissions(self, permissions):
        if isinstance(permissions, PermissionChecker): return permissions
        if isinstance(permissions, str):
            from llm_harness.core.permissions.modes import PermissionMode
            mode_map = {"default": PermissionMode.DEFAULT, "plan": PermissionMode.PLAN,
                        "auto": PermissionMode.FULL_AUTO, "full_auto": PermissionMode.FULL_AUTO}
            mode = mode_map.get(permissions.lower(), PermissionMode.DEFAULT)
            return PermissionChecker(PermissionSettings(mode=mode))
        return PermissionChecker(PermissionSettings())

    def _resolve_tools(self, tool_names):
        registry = ToolRegistry()
        if not tool_names:
            tool_names = ["read_file", "write_file", "edit_file", "exec", "web_search", "web_fetch", "glob", "grep",
                          "memory_read", "memory_write", "agent", "send_message", "task_stop",
                          "ask_user_question"]
        for name in tool_names:
            tool = self._build_tool(name)
            if tool:
                registry.register(tool)
        return registry

    def _build_tool(self, name: str):
        from llm_harness.core.tools.read_file import ReadFileTool
        from llm_harness.core.tools.write_file import WriteFileTool
        from llm_harness.core.tools.edit_file import EditFileTool
        from llm_harness.core.tools.shell import ExecTool
        from llm_harness.core.tools.glob import GlobTool
        from llm_harness.core.tools.grep import GrepTool
        from llm_harness.core.tools.web_search import WebSearchTool
        from llm_harness.core.tools.web_fetch import WebFetchTool
        from llm_harness.core.tools.memory_read import MemoryReadTool
        from llm_harness.core.tools.memory_write import MemoryWriteTool
        from llm_harness.core.tools.agent import AgentTool
        from llm_harness.core.tools.send_message import SendMessageTool
        from llm_harness.core.tools.task_stop import TaskStopTool
        from llm_harness.core.tools.ask_user import AskUserQuestionTool

        DEP_MAP = {
            "read_file": lambda: ReadFileTool(self.sandbox), "write_file": lambda: WriteFileTool(self.sandbox),
            "edit_file": lambda: EditFileTool(self.sandbox), "exec": lambda: ExecTool(self.sandbox),
            "glob": lambda: GlobTool(self.sandbox), "grep": lambda: GrepTool(self.sandbox),
            "memory_read": lambda: MemoryReadTool(self.memory), "memory_write": lambda: MemoryWriteTool(self.memory),
            "agent": lambda: AgentTool(self.swarm, self.bus), "send_message": lambda: SendMessageTool(self.swarm),
            "task_stop": lambda: TaskStopTool(self.swarm),
        }
        INDEP_MAP = {
            "web_search": WebSearchTool, "web_fetch": WebFetchTool, "ask_user_question": AskUserQuestionTool,
        }
        factory = DEP_MAP.get(name)
        if factory:
            return factory()
        factory = INDEP_MAP.get(name)
        if factory:
            return factory()
        log.warning("Unknown tool: %s", name)
        return None

    def _build_consolidator(self):
        return MemoryConsolidator(
            backend=self.memory, sessions=self._session_manager,
            context_window_tokens=64_000, max_completion_tokens=4096,
            build_messages=lambda **kw: [],  # placeholder, replaced in _build_context_builder
            get_tool_definitions=lambda: [],
        )

    def create_agent(self) -> Agent:
        async def on_build_context(msg: InboundMessage, history: list[dict]):
            parts = ["You are a helpful AI assistant.", f"Current time: {__import__('datetime').datetime.now().isoformat()}"]
            if self.memory:
                ctx = await self.memory.get_context(msg.session_key)
                if ctx:
                    parts.append(ctx)
            from llm_harness.core.swarm.definitions import list_definitions as ld
            defs = ld()
            if defs:
                agent_list = "\n".join(f"- **{d.name}**: {d.description}" for d in defs)
                parts.append(f"## Available Sub-Agents\n{agent_list}")
            system = "\n\n".join(parts)
            return [{"role": "system", "content": system}, {"role": "user", "content": msg.content}]

        loop = AgentLoop(
            provider=self.provider, tools=self._tools, model=self.model,
            on_build_context=on_build_context,
            on_tool_check=lambda name, tool, args: self._permissions.evaluate(name, tool.is_read_only(args) if hasattr(tool, 'is_read_only') else False),
            on_error=lambda exc, ctx: log.exception("Error in %s", ctx),
        )
        return Agent(loop=loop, sessions=self._session_manager,
                     consolidator=self._consolidator, observability=self._observability)
```

- [ ] **Step 2: Verify and commit**

```bash
cd E:/work-space/llm-harness && uv run python -c "from llm_harness.core.harness import Harness; h=Harness(memory='file:///tmp/test'); print('Harness OK')" && git add -A && git commit -m "feat: add Harness IoC container with URL-based backend resolution" -m "Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 18: Extensions — Channels, Skills, Hooks, MCP, Cron

- [ ] **Step 1: Copy channel modules from agent-harness**

Copy `channels/base.py`, `channels/manager.py`, `channels/wechat.py`, `channels/feishu.py` from `E:\work-space\agent-harness\src\agent_harness\channels\`. Add lifecycle hooks (`on_connect`/`on_disconnect`) to `BaseChannel`. Create simple `cli.py`, `http.py`, `websocket.py`.

- [ ] **Step 2: Copy hooks, skills, MCP, cron**

Copy from agent-harness `extensions/` directories. Replace imports. For skills, load from sandbox volume path: `SkillRegistry.load(volume_path / "skills")`.

- [ ] **Step 3: Verify and commit**

```bash
cd E:/work-space/llm-harness && uv run python -c "
from llm_harness.extensions.channels.base import BaseChannel
from llm_harness.extensions.hooks import HookRegistry
from llm_harness.extensions.skills import SkillRegistry
from llm_harness.extensions.mcp import MCPClient
from llm_harness.extensions.cron import CronService
print('All extensions OK')
" && git add -A && git commit -m "feat: add extensions (channels with lifecycle, hooks, skills, MCP, cron)" -m "Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 19: `__main__.py` — Unified Entry Point

**Files:**
- Create: `src/llm_harness/__main__.py`

- [ ] **Step 1: Create __main__.py**

```python
"""llm-harness entry point — worker mode or normal startup."""

import sys
import asyncio


def main():
    if "--worker" in sys.argv:
        asyncio.run(worker_main())
    else:
        asyncio.run(normal_main())


async def worker_main():
    """Worker process: read prompt from stdin, run ReAct loop, write result to stdout."""
    import argparse, json
    from llm_harness.adapters.providers.registry import detect_provider
    from llm_harness.core.tools.base import ToolRegistry
    from llm_harness.core.loop import AgentLoop

    parser = argparse.ArgumentParser()
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--agent-def", type=str, required=True)
    parser.add_argument("--tools", type=str, default="read_file,glob,grep,web_search")
    parser.add_argument("--skills-path", type=str, default="")
    parser.add_argument("--model", type=str, default="")
    args = parser.parse_args()

    prompt = sys.stdin.read().strip()
    if not prompt:
        print("Error: no prompt on stdin")
        return

    spec = detect_provider(args.model or "claude-sonnet-4-6")
    if spec is None:
        print("Error: cannot detect provider")
        return
    provider = _instantiate_provider(spec)

    from llm_harness.core.swarm.definitions import get_definition as gd

    agent_def = gd(args.agent_def)
    if agent_def is None:
        print(f"Error: unknown agent definition '{args.agent_def}'")
        return
    model = args.model or spec.default_model or "claude-sonnet-4-6"
    tool_names = args.tools.split(",")
    tool_registry = ToolRegistry()
    builder = _WorkerToolBuilder(tool_registry)
    for name in tool_names:
        builder.build(name)
    from llm_harness.core.session import SessionManager

    from llm_harness.adapters.session.file import FileSessionBackend
    sm = SessionManager(FileSessionBackend(__import__("pathlib").Path.home() / ".llm-harness" / "worker-sessions"))

    async def build_ctx(msg, history):
        return [{"role": "system", "content": agent_def.system_prompt}]

    loop = AgentLoop(provider=provider, tools=tool_registry, model=model,
                     on_build_context=build_ctx,
                     on_tool_check=lambda n, t, a: type("OK", (), {"allowed": True})(),
                     on_error=lambda e, c: None)

    class FakeMsg:
        channel = "worker"; sender_id = "worker"; chat_id = "task"; content = prompt
        @property
        def session_key(self): return f"{self.channel}:{self.chat_id}"

    result = await loop.run(FakeMsg(), [])
    print(result.final_content or "")


async def normal_main():
    """Normal startup — load config, create harness and channel."""
    from llm_harness.config import load_config
    config = load_config()
    print(f"llm-harness v0.1.0 — model={config.agent.model}")
    # Channel startup based on config.channels


def _instantiate_provider(spec):
    if spec.backend == "anthropic":
        from llm_harness.adapters.providers.anthropic_provider import AnthropicProvider
        return AnthropicProvider()
    from llm_harness.adapters.providers.openai_compat_provider import OpenAICompatProvider
    return OpenAICompatProvider(model=spec.default_model or "", api_base=spec.default_api_base or "")


class _WorkerToolBuilder:
    INDEPENDENT = {"web_search", "web_fetch", "ask_user_question"}
    def __init__(self, registry): self.registry = registry
    def build(self, name):
        if name in self.INDEPENDENT:
            if name == "web_search":
                from llm_harness.core.tools.web_search import WebSearchTool
                self.registry.register(WebSearchTool())
        # Worker tools are limited to independent tools (no sandbox/memory in worker context)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Verify and commit**

```bash
cd E:/work-space/llm-harness && uv run python -c "from llm_harness.__main__ import main; print('Main OK')" && git add -A && git commit -m "feat: add __main__.py unified entry point" -m "Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 20: Integration Test & Top-level API

**Files:**
- Update: `src/llm_harness/__init__.py`
- Create: `tests/test_integration.py`

- [ ] **Step 1: Update __init__.py**

```python
"""llm-harness: Lightweight AI agent infrastructure library."""

__version__ = "0.1.0"

from llm_harness.core.harness import Harness
from llm_harness.config import Config, load_config

__all__ = ["Harness", "Config", "load_config"]
```

- [ ] **Step 2: Create integration test**

```python
"""Integration tests for llm-harness."""

import asyncio, tempfile
from pathlib import Path

import pytest
from llm_harness.core.bus.events import InboundMessage
from llm_harness.adapters.session import FileSessionBackend
from llm_harness.adapters.memory import FileMemoryBackend
from llm_harness.adapters.observability import DefaultObservabilityBackend
from llm_harness.core.session import SessionManager
from llm_harness.core.harness import Harness


class TestHarness:
    def test_create_minimal(self):
        h = Harness(memory="file:///tmp/test", sandbox="none")
        assert h.memory is not None
        assert h.sandbox is None

    def test_url_resolution(self):
        h = Harness(memory="tencentdb://localhost:8420", sandbox="opensandbox://localhost:8080")
        from llm_harness.adapters.memory.tencentdb import TencentDBMemoryBackend
        from llm_harness.adapters.sandbox.opensandbox import OpenSandboxBackend
        assert isinstance(h.memory, TencentDBMemoryBackend)
        assert isinstance(h.sandbox, OpenSandboxBackend)


class TestSessionBackend:
    @pytest.mark.asyncio
    async def test_save_and_load(self):
        d = tempfile.mkdtemp()
        b = FileSessionBackend(Path(d))
        await b.save("test:1", {"messages": [{"role": "user", "content": "hi"}], "metadata": {}, "last_consolidated": 0})
        state = await b.load("test:1")
        assert len(state["messages"]) == 1
        assert state["messages"][0]["content"] == "hi"

    @pytest.mark.asyncio
    async def test_list_keys(self):
        d = tempfile.mkdtemp()
        b = FileSessionBackend(Path(d))
        await b.save("a:1", {"messages": [], "metadata": {}, "last_consolidated": 0})
        await b.save("b:2", {"messages": [], "metadata": {}, "last_consolidated": 0})
        keys = await b.list_keys()
        assert "a:1" in keys and "b:2" in keys


class TestSessionManager:
    @pytest.mark.asyncio
    async def test_cache_and_persist(self):
        d = tempfile.mkdtemp()
        backend = FileSessionBackend(Path(d))
        sm = SessionManager(backend)
        s = await sm.get_or_create("cli:u")
        s.add_message("user", "hello")
        await sm.save(s)
        sm.invalidate("cli:u")
        s2 = await sm.get_or_create("cli:u")
        assert len(s2.messages) == 1
        assert s2.messages[0]["content"] == "hello"


class TestMemoryBackend:
    @pytest.mark.asyncio
    async def test_append_and_read(self):
        d = tempfile.mkdtemp()
        b = FileMemoryBackend(Path(d))
        await b.append_section("ns:1", "memory", "fact 1")
        await b.append_section("ns:1", "memory", "fact 2")
        ctx = await b.get_context("ns:1")
        assert "fact 1" in ctx and "fact 2" in ctx

    @pytest.mark.asyncio
    async def test_namespace_isolation(self):
        d = tempfile.mkdtemp()
        b = FileMemoryBackend(Path(d))
        await b.append_section("ns-a", "memory", "a")
        await b.append_section("ns-b", "memory", "b")
        assert "a" in await b.get_context("ns-a")
        assert "b" not in await b.get_context("ns-a")

    @pytest.mark.asyncio
    async def test_consolidate_no_provider_raw_archive(self):
        d = tempfile.mkdtemp()
        b = FileMemoryBackend(Path(d))
        ok = await b.consolidate("ns:1", [{"role": "user", "content": "test"}])
        assert ok is True


class TestObservability:
    @pytest.mark.asyncio
    async def test_emit_and_subscribe(self):
        events = []
        async def h(t, p): events.append((t, p))
        b = DefaultObservabilityBackend()
        await b.subscribe("test", h)
        await b.emit("test", {"msg": "hello"})
        assert len(events) == 1
        assert events[0][1]["msg"] == "hello"


class TestInboundMessage:
    def test_session_key(self):
        msg = InboundMessage("cli", "user", "chat", "hello")
        assert msg.session_key == "cli:chat"

    def test_session_key_override(self):
        msg = InboundMessage("cli", "user", "chat", "hello", session_key_override="custom:1")
        assert msg.session_key == "custom:1"
```

- [ ] **Step 3: Run tests**

```bash
cd E:/work-space/llm-harness && uv run pytest tests/ -v
```
Expected: all tests PASS.

- [ ] **Step 4: Commit**

```bash
cd E:/work-space/llm-harness && git add -A && git commit -m "feat: add integration tests and top-level API" -m "Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Implementation Order

1. Task 1: Project skeleton
2. Task 2: Message bus
3. Task 3: Config system
4. Task 4: SessionBackend Protocol + File backend
5. Task 5: Session data class + SessionManager
6. Task 6: Tool system base
7. Task 7: Permissions
8. Task 8: ObservabilityBackend Protocol + Default
9. Task 9: LLM Provider base + registry
10. Task 10: Memory system
11. Task 11: TencentDB adapter
12. Task 12: Sandbox system
13. Task 13: Swarm sub-agent system
14. Task 14: Built-in tools
15. Task 15: AgentLoop
16. Task 16: Agent
17. Task 17: Harness
18. Task 18: Extensions
19. Task 19: `__main__.py`
20. Task 20: Integration test + top-level API
