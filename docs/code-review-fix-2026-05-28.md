# 代码审查修复报告

**修复日期**: 2026-05-28
**审查报告**: `docs/code-review-2026-05-28.md`
**修复范围**: 5 个 bug（3 个来自审查报告，2 个新发现）

---

## 修复验证

审查报告中的 25 个问题，经逐项验证：22 个已在当前源码中修复，剩余 3 个（#12, #21, #25）需要修复。此外新发现 2 个问题（N1, N2），一并修复。

---

## 修复清单

### 1. Bug #12 — Session 缓存内存泄漏

**文件**: `src/llm_harness/core/session/manager.py`

**问题**: `SessionManager._cache` 是普通 dict，无最大容量限制。长期运行造成内存无限增长。

**修复**:
- 添加 `_cache_max_size` 参数（默认 1000）
- `get_or_create` 中，当缓存超过上限时，按插入顺序驱逐最旧条目

```python
if len(self._cache) >= self._cache_max_size:
    overflow = len(self._cache) - self._cache_max_size + 1
    for stale_key in list(self._cache)[:overflow]:
        if stale_key != key:
            self._cache.pop(stale_key, None)
```

**测试**（`tests/core/test_session_manager.py`）:
| 测试 | 目的 |
|------|------|
| `test_cache_max_size_default` | 默认 `_cache_max_size` 为正数 |
| `test_evicts_oldest_on_overflow` | 溢出时按插入顺序驱逐 |
| `test_oldest_evicted_by_insertion_order` | 精确验证插入顺序驱逐 |
| `test_cache_hit_does_not_reload` | 缓存命中不触发 backend.load |
| `test_overflow_does_not_lose_all` | 50 条写入后缓存仍在限制内 |

---

### 2. Bug N1 — Consolidator WeakValueDictionary 并发风险

**文件**: `src/llm_harness/adapters/memory/consolidator.py`

**问题**: `_locks` 使用 `weakref.WeakValueDictionary`，锁对象在无外部引用时被 GC 回收。两个协程可能同时获取"同一个" key 的不同锁实例，破坏互斥保证。

**修复**:
- 替换为普通 `dict`
- 添加 `_lock_max_size = 10_000`，超出时驱逐
- 删除 `import weakref`

**测试**（`tests/adapters/test_memory_consolidator.py`）:
| 测试 | 目的 |
|------|------|
| `test_get_lock_returns_same_object` | 同 key 返回同一个 asyncio.Lock |
| `test_get_lock_different_keys_different_locks` | 不同 key 返回不同锁 |
| `test_locks_is_plain_dict` | `_locks` 是 dict 而非 WeakValueDictionary |

---

### 3. Bug #21 — Channel 任务生命周期管理

**文件**: `src/llm_harness/extensions/channels/manager.py`

**问题**: `start_all` 创建 channel 协程但未存储引用，`stop_all` 无法 cancel 它们，只能依赖 channel 自身检查 `_running` 标志。

**修复**:
- 添加 `_channel_tasks: dict[str, asyncio.Task]` 存储 channel 任务
- `start_all` 中将每个 channel 的 `asyncio.Task` 存入 `_channel_tasks`
- `stop_all` 中先 cancel 所有 channel 任务，再调用 `channel.stop()` 做清理

**测试**（`tests/extensions/test_channels_extra.py`）:
| 测试 | 目的 |
|------|------|
| `test_stop_all_cancels_stored_channel_tasks` | stop_all cancel `_channel_tasks` 中的任务 |
| `test_channel_tasks_dict_exists` | `_channel_tasks` 属性存在且为 dict |

---

### 4. Bug #25 — 热路径中的模块级 import

**文件**: `src/llm_harness/core/harness.py`

**问题**: `list_definitions` 在 `on_build_context` 闭包内导入，每条消息触发一次不必要的 import 查找。

**修复**: 将 import 移至模块顶部，闭包内直接调用。

**覆盖**: 现有测试已覆盖，无需新增。

---

### 5. Bug N2 — AgentTool 错误消息硬编码 agent 名称

**文件**: `src/llm_harness/core/tools/agent.py`

**问题**: 未知 agent 时的错误消息写死了 `"general-purpose"` 等名称，不反映动态注册的自定义 agent。

**修复**: 使用 `list_definitions()` 动态获取可用 agent 名称列表。

```python
available = [d.name for d in list_definitions()]
return ToolResult(
    output=f"Error: Unknown agent definition '{arguments.name}'. "
           f"Available: {', '.join(available)}",
    is_error=True,
)
```

**测试**（`tests/core/tools/test_agent_tools.py`）:
| 测试 | 目的 |
|------|------|
| `test_error_message_includes_custom_agent_names` | 注册自定义 agent 后验证错误消息包含其名称 |

---

## 未修复

| 问题 | 决定 | 原因 |
|------|------|------|
| N3 — O(n) 缓存驱逐 | 不做修改 | 遍历 dict keys 的效率在实际场景中可接受，不值得引入额外数据结构 |

---

## 测试结果

```
422 passed, 0 failed in 48.35s
```

| 模块 | 新增测试 | 状态 |
|------|----------|------|
| `tests/core/test_session_manager.py` | 5 | pass |
| `tests/adapters/test_memory_consolidator.py` | 3 | pass |
| `tests/extensions/test_channels_extra.py` | 2 | pass |
| `tests/core/tools/test_agent_tools.py` | 1 | pass |
| 全套件 | 422 total | pass |

---

## 方法论

采用严格 TDD（RED → GREEN → REFACTOR）：每个 bug 先编写失败的测试，再实施最小修复使其通过。无新引入回归。
