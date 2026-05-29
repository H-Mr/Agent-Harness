# How to Implement a Custom Memory Backend

## Goal

Replace the default TencentDBMemoryBackend with your own — Redis, PostgreSQL, or a custom service.

## Prerequisites

- Understanding of MemoryBackend Protocol (5 methods)

## Step by Step

### 1. Understand the Protocol

```python
class MemoryBackend(Protocol):
    async def get_context(self, namespace: str) -> str: ...
    async def read_section(self, namespace: str, section: str) -> str: ...
    async def append_section(self, namespace: str, section: str, entry: str) -> None: ...
    async def add_history(self, namespace: str, entry: str) -> None: ...
    async def consolidate(self, namespace: str, messages: list[dict[str, Any]],
                          provider: Any = None, model: str = "") -> bool: ...
```

### 2. Implement RedisMemoryBackend

```python
import json
from typing import Any
import redis.asyncio as redis

class RedisMemoryBackend:
    def __init__(self, redis_url: str = "redis://localhost:6379"):
        self._redis = redis.from_url(redis_url)

    async def get_context(self, namespace: str) -> str:
        data = await self._redis.get(f"llm:ctx:{namespace}")
        return data.decode() if data else ""

    async def read_section(self, namespace: str, section: str) -> str:
        data = await self._redis.get(f"llm:sec:{namespace}:{section}")
        return data.decode() if data else ""

    async def append_section(self, namespace: str, section: str, entry: str) -> None:
        await self._redis.append(f"llm:sec:{namespace}:{section}", entry + "\n")

    async def add_history(self, namespace: str, entry: str) -> None:
        await self._redis.rpush(f"llm:hist:{namespace}", entry)

    async def consolidate(self, namespace: str, messages: list[dict[str, Any]],
                          provider: Any = None, model: str = "") -> bool:
        payload = json.dumps(messages, ensure_ascii=False)
        await self._redis.set(f"llm:consolidated:{namespace}", payload)
        return True

    async def close(self) -> None:
        await self._redis.close()
```

### 3. Inject into Harness

```python
memory = RedisMemoryBackend("redis://localhost:6379")
harness = Harness(provider=..., model=..., tools=..., sandbox=..., memory=memory)
```

## Testing

```python
import fakeredis.aioredis
import pytest

@pytest.mark.asyncio
async def test_redis_memory_context():
    backend = RedisMemoryBackend()
    backend._redis = await fakeredis.aioredis.create_redis_connection()
    await backend.append_section("test", "rules", "Be concise")
    content = await backend.read_section("test", "rules")
    assert "Be concise" in content
```
