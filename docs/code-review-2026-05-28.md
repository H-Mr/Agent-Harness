# llm-harness 框架代码审查报告

**审查日期**: 2026-05-28  
**审查范围**: 全部源码（~50 个文件），涵盖 core、adapters、extensions、config 四大子系统  
**审查方法**: 三个独立 agent 并行审查，交叉验证关键发现  
**审查标准**: 无 CLAUDE.md 文件，基于通用代码质量标准

---

## 总览

| 严重程度 | 数量 | 说明 |
|----------|------|------|
| CRITICAL | 8 | 功能完全失效或数据丢失 |
| HIGH | 10 | 严重 bug、安全漏洞、可靠性问题 |
| MEDIUM | 7 | 影响较小的 bug |

---

## CRITICAL（8 个）

### 1. PermissionChecker 敏感路径保护完全失效

**文件**: `src/llm_harness/core/permissions/checker.py:88-124`, `src/llm_harness/core/harness.py:243-246`

`PermissionChecker.evaluate()` 定义了 `SENSITIVE_PATH_PATTERNS`，用于拦截对 SSH 密钥、AWS/GCP/Azure 凭证、Docker/K8s 配置等敏感文件的访问。此外还支持用户自定义的 `path_rules` 和 `denied_commands`。

但 `harness.py:243` 中的 `on_tool_check` 回调只传递了 `name` 和 `is_read_only` 两个参数，**从未传递 `file_path` 和 `command`**。因此所有敏感路径保护逻辑都是死代码。

```python
# harness.py:243-246 — 只传递了 name 和 is_read_only
on_tool_check=lambda name, tool, args: self._permissions.evaluate(
    name,
    is_read_only=tool.is_read_only(args) if hasattr(tool, 'is_read_only') else False,
),
# file_path 和 command 从未被传入，始终为 None
```

**影响**: LLM 可以通过文件操作工具自由读取 `~/.ssh/id_rsa`、`.aws/credentials`、`kubeconfig` 等任意敏感文件，敏感路径保护形同虚设。

**修复建议**: 在 `loop.py:84` 已解析出 Pydantic model `parsed`，回调链中需要从 `parsed` 提取 `file_path` 和 `command` 字段传递给 `evaluate()`。

---

### 2. 子进程 stdout 死锁 — 输出超过管道缓冲区时代理永久挂起

**文件**: `src/llm_harness/core/swarm/subprocess.py:60-61`

```python
await proc.wait()                                           # (1) 等待子进程退出
stdout = await proc.stdout.read() if proc.stdout else b""   # (2) 然后才读 stdout
```

父进程先等待子进程退出，**然后**才读取 stdout。OS 管道缓冲区有限（Linux ~64KB，Windows ~4KB）。如果子进程写入超过缓冲区大小：
- 子进程的 `write()` 在内核层面阻塞，无法退出
- 父进程的 `wait()` 在等子进程退出，不会去读管道
- **经典死锁**

**影响**: 任何输出超过管道缓冲区的子代理都会永久挂起。

**修复建议**: 使用 `proc.communicate()` 替代，它会在等待时同时读取管道：

```python
stdout, stderr = await proc.communicate()
```

---

### 3. Session 消息重复存储 — 每轮 O(N^2) 增长

**文件**: `src/llm_harness/core/agent.py:73-85`, `src/llm_harness/core/loop.py:54-58`

`loop.py` 构建的 `messages` 列表包含 `[system + 完整历史 + user + 新回复]`。`agent.py:_save_turn()` 遍历 `result.messages` 中的**全部**消息，将所有 assistant/tool 角色的消息重新添加到 session 中——包括已经存在于历史中的那些。

**每轮对话都会重复添加整个历史中的 assistant/tool 消息**，消息量呈 O(N^2) 增长。

**影响**: 与 #4（get_history 丢失字段）叠加，导致多轮对话完全不可用。Session 文件急速膨胀，内存无限增长。

**修复建议**: `_save_turn()` 应只保存**本轮新产生**的消息。需要在 loop 结果中标记本轮边界或只返回增量消息。

---

### 4. `get_history()` 丢失 `tool_call_id`、`tool_calls`、`name` 字段

**文件**: `src/llm_harness/core/session/session.py:24-35`

```python
return [{"role": m["role"], "content": m.get("content", "")} for m in sliced]
```

只保留了 `role` 和 `content`，丢弃了 `tool_call_id`、`tool_calls`、`name`。OpenAI API 要求：
- assistant 消息携带 `tool_calls` 表示调用了哪些工具
- tool 消息携带 `tool_call_id` 关联到对应的调用

**影响**: 任何涉及工具调用的多轮对话，第二轮开始 API 会收到格式错误的消息序列。

**修复建议**: 保留所有工具相关字段：

```python
result = {"role": m["role"], "content": m.get("content", "")}
for k in ("tool_calls", "tool_call_id", "name"):
    if k in m:
        result[k] = m[k]
```

---

### 5. `BaseChannel.is_allowed` 对 dict 配置使用 `getattr` — 所有消息被静默拒绝

**文件**: `src/llm_harness/extensions/channels/base.py:101`

```python
allow_list = getattr(self.config, "allow_from", [])
```

当 `self.config` 是普通 dict（正常的 YAML 配置路径）时，`getattr(dict_instance, "allow_from", [])` **永远返回 `[]`**，因为 dict 对象没有 `allow_from` 属性。紧接着 `not []` → `True` → **所有消息被拒绝**。

**影响**: 所有通过 YAML dict 配置的 channel 完全无法接收任何用户消息，但不会报错，表现为"channel 运行但无响应"。

**修复建议**: 统一访问方式，兼容 dict 和对象：

```python
if isinstance(self.config, dict):
    allow_list = self.config.get("allow_from", [])
else:
    allow_list = getattr(self.config, "allow_from", [])
```

---

### 6. MCP 客户端对 dict 配置使用属性访问 — 所有 MCP 连接崩溃

**文件**: `src/llm_harness/extensions/mcp/client.py:190-238`

`connect_mcp_servers()` 整个循环体使用 `cfg.type`、`cfg.command`、`cfg.args`、`cfg.url`、`cfg.headers` 等属性访问方式。当配置值是 dict（来自 YAML）时，每次访问都抛出 `AttributeError`，被外层 `except Exception` 捕获后跳过该 server。

**影响**: MCP 集成完全不可用，零个 MCP 工具被注册。所有 MCP server 连接静默失败。

**修复建议**: 改用 dict 键访问（如 `cfg.get("type")`）或在调用前定义 Pydantic model 进行验证和转换。

---

### 7. FileMemoryBackend 路径穿越漏洞 — `..` 未过滤

**文件**: `src/llm_harness/adapters/memory/file.py:33-36`

```python
def _dir(self, namespace: str) -> Path:
    safe = namespace.replace(":", "_").replace("\\", "_").replace("/", "_")
    d = self.base_dir / safe
```

只替换了 `:`、`\`、`/`，**未处理 `..`**。namespace 为 `".."` 时直接穿越到 `base_dir` 的父目录。所有文件操作（get_context、read_section、append_section、add_history、consolidate）都受影响。

**影响**: 能控制 namespace 值的攻击者可以读写 `base_dir` 之外的任意文件。

**修复建议**: 验证 `d.resolve()` 仍在 `self.base_dir` 之下，或在替换逻辑中增加 `..` 的处理。

---

### 8. FileSessionBackend 路径穿越漏洞 — `..` 未过滤

**文件**: `src/llm_harness/adapters/session/file.py:22-23`

```python
safe = re.sub(r'[<>:"/\\|?*]', "_", session_key)
```

正则表达式未覆盖 `..`。session_key 为 `".."` 时穿越到 `base_dir` 的父目录。`load()` 和 `save()` 均受影响。

**影响**: 能控制 session_key 的攻击者可以读写任意 JSONL 文件。

**修复建议**: 同 #7，验证解析后路径在允许范围内。

---

## HIGH（10 个）

### 9. `LLM_HARNESS_WORKSPACE` 环境变量设置到了错误的对象上

**文件**: `src/llm_harness/config/loader.py:23-29`

```python
for env_key, field in [
    ("LLM_HARNESS_MODEL", "model"), ("LLM_HARNESS_PROVIDER", "provider"),
    ("LLM_HARNESS_API_KEY", "api_key"), ("LLM_HARNESS_API_BASE", "api_base"),
    ("LLM_HARNESS_WORKSPACE", "workspace"),  # workspace 不在 AgentConfig 上!
]:
    if os.environ.get(env_key):
        setattr(config.agent, field, os.environ[env_key])  # 设置到 agent，而非 config
```

`workspace` 是 `Config` 的顶层字段，不是 `AgentConfig` 的字段。Pydantic v2 默认忽略额外属性，因此该环境变量**完全无效**。

**修复建议**: 将 `LLM_HARNESS_WORKSPACE` 的处理移到循环外，设置 `config.workspace`。

---

### 10. TokenBudgetPolicy 运算符优先级错误 — 删除约 10 倍过多的消息

**文件**: `src/llm_harness/adapters/memory/policy.py:26`

```python
boundary = consolidator.pick_consolidation_boundary(
    session, max(1, estimated - budget // 2)
)
```

Python 运算符优先级：`estimated - budget // 2` 等价于 `estimated - (budget // 2)`，而非预期的 `(estimated - budget) // 2`。

以 128K 上下文窗口为例，当超出预算 ~7K tokens 时，实际计算为 `130000 - 61440 = 68560`，即删除了约 10 倍于预期的消息量。

**修复建议**: 加括号明确优先级 `(estimated - budget) // 2`。

---

### 11. `_session_locks` 字典无限增长 — 内存泄漏

**文件**: `src/llm_harness/core/agent.py:33`

```python
self._session_locks: dict[str, asyncio.Lock] = {}
```

每遇到一个新的 `session_key` 就创建一个 `asyncio.Lock` 存入字典，**永不删除**。长期运行的服务中，历史 session 的锁对象持续占用内存。

**修复建议**: 使用 LRU 淘汰策略或弱引用字典。注意 `asyncio.Lock` 在某些 Python 版本中不直接支持弱引用，需要包装。

---

### 12. Session 缓存无限增长 — 内存泄漏

**文件**: `src/llm_harness/core/session/manager.py:16`

```python
self._cache: dict[str, Session] = {}
```

与 #11 相同模式。没有驱逐策略、没有最大容量限制。每个缓存的 `Session` 包含完整消息列表，随时间增长。叠加 #3（消息重复）时增长更快。

**修复建议**: 添加 LRU 驱逐策略或 TTL 过期机制。

---

### 13. Mailbox 损坏消息被静默丢弃 — 无任何日志

**文件**: `src/llm_harness/core/swarm/mailbox.py:29`

```python
except Exception:
    pass
```

读取 mailbox 文件时，如果 JSON 损坏（写入不完整、并发写入冲突、磁盘错误），异常被静默吞掉。消息永久丢失且无从诊断。

**修复建议**: 至少记录警告日志：

```python
except Exception as e:
    logger.warning("Failed to read mailbox message %s: %s", f, e)
```

---

### 14. Session 文件非原子写入 — 崩溃时数据丢失

**文件**: `src/llm_harness/adapters/session/file.py:49-57`

`save()` 方法以 `"w"` 模式打开文件直接写入。如果在写入过程中进程崩溃或磁盘出错，JSONL 文件处于截断/损坏状态。下次 `load()` 时 `except Exception` 捕获 JSON 解析错误返回 `None`，**所有 session 数据永久丢失**。

**修复建议**: 先写入临时文件，然后 `os.replace()`（原子重命名）替换原文件。

---

### 15. 全局使用无时区的 datetime

**文件**: `bus/events.py:14`, `session/session.py:14-15`, `swarm/mailbox.py:13`

所有时间戳使用 `datetime.now()`（无时区本地时间）。在 DST 切换、容器时区变更时，消息排序和 session 时序不可靠。Mailbox 文件名排序（`mailbox.py:24`）在时区变化时出错。

**修复建议**: 全局替换为 `datetime.now(timezone.utc)`。

---

### 16. Prompt/Agent hook 的 `timeout_seconds` 声明但未执行

**文件**: `src/llm_harness/extensions/hooks/schemas.py:20-28,42-50`, `executor.py:166-209`

`PromptHookDefinition` 和 `AgentHookDefinition` 定义了 `timeout_seconds` 字段（默认 30s/60s），但 `executor.py` 从未用 `asyncio.wait_for` 包裹 `chat_with_retry` 调用。对比 `_run_command_hook` 正确使用了 `asyncio.wait_for`。

**影响**: LLM 提供商挂起时（网络故障、服务端过载、无限生成），hook 永久阻塞。

**修复建议**: 给 `chat_with_retry` 调用加 `asyncio.wait_for(..., timeout=hook.timeout_seconds)`。

---

### 17. MCP 可选参数 Pydantic 类型错误

**文件**: `src/llm_harness/extensions/mcp/client.py:103-106`

```python
fields[prop_name] = (python_type, None)  # 例如 (str, None)
```

`(str, None)` 创建了类型为 `str`、默认值为 `None` 的字段。`None` 不是合法的 `str` 值。`model_dump()` 对未设置的可选字段输出 `null`，可能导致 MCP server 拒绝请求。

**修复建议**: 使用 `Optional[python_type]`：

```python
from typing import Optional
fields[prop_name] = (Optional[python_type], None)
```

---

### 18. `OpenSandboxBackend.write_file` 未检查 HTTP 响应状态

**文件**: `src/llm_harness/adapters/sandbox/opensandbox.py:70-75`

```python
await client.post(f"{self.base_url}/sandboxes/{session.sandbox_id}/files",
                  json={"path": path, "content": content})
# 未调用 raise_for_status()
```

所有其他 sandbox 方法（read_file、execute、list_dir 等）都正确调用了 `raise_for_status()` 或检查了 status_code，唯独 write_file 遗漏。4xx/5xx 错误被静默忽略。

---

## MEDIUM（7 个）

19. **`max_messages=0` 返回全部消息而非零条** — `session.py:26`：`list[-0:]` = `list[0:]` = 全部元素。`consolidator.py:80` 调用 `get_history(max_messages=0)` 意图获取空历史用于 token 估算，实际返回了完整历史。

20. **Mailbox 文件名微妙时间戳冲突** — `mailbox.py:17`：同一微妙内写两条消息时文件名相同，后一条静默覆盖前一条。

21. **Channel 任务未存储用于生命周期管理** — `manager.py:96-128`：`start_all` 创建的 channel 协程未被存储，`stop_all` 无法 cancel 它们，只能依赖 channel 自己检查 `_running` 标志。

22. **`_validate_allow_from` 对 dict 配置无效果** — `manager.py:81-87`：与 #5 相同的 `getattr` 问题。对于 dict 配置该验证永远不触发。

23. **Hook 执行器未在阻塞时短路** — `executor.py:61-75`：当某个 hook 设置了 `block_on_failure=True` 且失败时，后续 hook（可能涉及昂贵的 LLM 调用）仍被执行。

24. **Skills 加载器 `mkdir` 静默创建不存在的目录** — `loader.py:29`：配置了错误的 skill 路径时，不会报错而是创建空目录。

25. **模块级 import 在每条消息的热路径中** — `harness.py:225-227`：`from llm_harness.core.swarm.definitions import list_definitions` 在 `on_build_context` 闭包内，每消息执行一次不必要的 import 查找。

---

## 根因分析

两类架构模式导致了多数 bug：

1. **Dict 与 Pydantic model 的混淆**（#5, #6, #22）。Channel 和 MCP 配置从 YAML 以纯 dict 形式流入，但代码中广泛使用 `getattr` / 属性访问。代码假设接收的是 Pydantic model 实例，实际接收的是 dict。**在 Harness 边界处增加统一的配置验证层**，将 YAML dict 转换为类型化 model，可以从根源上消除这类 bug。

2. **AgentLoop 与 Harness 回调之间的紧耦合**（#1, #3）。`on_tool_check` 回调签名丢弃了 `loop.py:84` 已解析出的 `parsed` 模型信息；`_save_turn` 无法区分哪些消息是"本轮新增的"、哪些是"来自历史的"。loop 实际上已经拥有这些信息但没有暴露出来。

---

## Karpathy 准则评估

| 准则 | 评分 | 说明 |
|------|------|------|
| 先思考再编码 | 不通过 | 多处 bug 表明假设未被验证（管道缓冲区、dict vs Pydantic、运算符优先级） |
| 简洁优先 | 通过 | 架构合理——六边形架构、协议清晰、无过度抽象 |
| 精准修改 | 不适用 | 无现有代码库可修改 |
| 目标驱动执行 | 部分通过 | 存在集成测试但仅覆盖基本路径；缺少多轮对话、子进程、权限流程的测试 |

---

## 修复优先级建议

1. **立即修复**（CRITICAL #1-#8）：权限保护死代码、子进程死锁、session 消息重复、get_history 丢失字段、channel 消息拒绝、MCP 崩溃、两个路径穿越漏洞
2. **尽快修复**（HIGH #9-#18）：环境变量失效、TokenBudgetPolicy 错误、内存泄漏、静默丢弃消息、数据丢失风险、时区问题
3. **计划修复**（MEDIUM #19-#25）：运算符边缘情况、生命周期管理、诊断能力改进
