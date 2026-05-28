# llm-harness 架构文档

**日期**: 2026-05-29
**分支**: dev

---

## 一、目录结构

```
src/llm_harness/
├── core/
│   ├── agent.py                     # Agent — 编排 session/memory/loop
│   ├── harness.py                   # Harness — IoC 容器
│   ├── loop.py                      # AgentLoop — ReAct 骨架（Pipeline 模式）
│   ├── bus/
│   │   ├── events.py                # InboundMessage / OutboundMessage
│   │   └── queue.py                 # MessageBus (asyncio.Queue)
│   ├── session/
│   │   ├── session.py               # Session 数据类 (含 channel/chat_id 属性)
│   │   └── manager.py               # SessionManager (内存缓存 + LRU 驱逐)
│   ├── tools/
│   │   ├── base.py                  # BaseTool, ToolRegistry, ToolExecutionContext
│   │   ├── factory.py               # ToolFactory — 统一工具创建
│   │   ├── read_file.py             # 文件读取
│   │   ├── write_file.py            # 文件写入
│   │   ├── edit_file.py             # 文件编辑
│   │   ├── exec.py                  # 命令执行
│   │   ├── glob.py / grep.py        # 文件搜索
│   │   ├── web_search.py / web_fetch.py  # 网络工具
│   │   ├── memory_read.py / memory_write.py  # 长期记忆
│   │   ├── agent.py                 # 子 Agent 启动
│   │   ├── send_message.py / task_stop.py  # 子 Agent 通信
│   │   └── ask_user.py              # 用户交互
│   ├── permissions/
│   │   ├── checker.py               # PermissionChecker (敏感路径 + 命令拒绝)
│   │   ├── settings.py              # PermissionSettings
│   │   └── modes.py                 # PermissionMode (DEFAULT/PLAN/FULL_AUTO)
│   └── swarm/
│       ├── backend.py               # AgentBackend Protocol + SpawnConfig/SpawnResult
│       ├── subprocess.py            # SubprocessBackend (默认，srt 包装)
│       ├── in_process.py            # InProcessBackend (ContextVar 隔离)
│       ├── mailbox.py               # 文件消息队列 (poll/ack 模式)
│       └── definitions.py           # AgentDefinition 注册表
│
├── adapters/
│   ├── sandbox/
│   │   ├── backend.py               # SandboxBackend Protocol
│   │   └── srt.py                   # SRTSandboxBackend (默认，双层防御)
│   ├── memory/
│   │   ├── backend.py               # MemoryBackend Protocol
│   │   ├── file.py                  # FileMemoryBackend
│   │   ├── tencentdb.py             # TencentDBMemoryBackend
│   │   ├── consolidator.py          # MemoryConsolidator
│   │   └── policy.py                # TokenBudgetPolicy / MessageCountPolicy
│   ├── session/
│   │   ├── backend.py               # SessionBackend Protocol
│   │   └── file.py                  # FileSessionBackend (JSONL)
│   ├── observability/
│   │   ├── backend.py               # ObservabilityBackend Protocol
│   │   └── default.py               # DefaultObservabilityBackend
│   ├── providers/
│   │   ├── base.py                  # LLMProvider (chat_with_retry)
│   │   ├── registry.py              # ProviderSpec + detect_provider
│   │   ├── anthropic_provider.py    # Anthropic SDK
│   │   └── openai_compat_provider.py  # OpenAI 兼容
│   └── _path_utils.py               # resolve_safe_path 共享工具
│
├── extensions/
│   ├── channels/                    # Channel 系统 (BaseChannel + ChannelManager)
│   ├── hooks/                       # PRE/POST Hook 执行器
│   ├── mcp/                         # MCP 客户端
│   ├── skills/                      # 技能加载器
│   └── cron/                        # 定时调度
│
├── config/
│   ├── schema.py                    # Config Pydantic 模型
│   └── loader.py                    # CLI > env > YAML > 默认
│
└── __main__.py                      # 统一入口 (--worker 模式 + 普通启动)
```

---

## 二、多租户隔离架构

### 目录结构

```
{base}/                             ← Harness.workspace
├── alice/                          ← Alice 的 workspace（srt --read/--write 边界）
│   ├── memory/                     ← 跨会话共享记忆（namespace=alice）
│   │   ├── MEMORY.md
│   │   ├── AGENTS.md
│   │   └── history.jsonl
│   └── sessions/
│       ├── telegram/
│       │   └── chat_001/
│       │       ├── files/          ← LLM 工作目录
│       │       └── session.jsonl   ← 对话历史
│       └── cli/
│           └── chat_002/
│               ├── files/
│               └── session.jsonl
├── bob/
│   └── ...
└── sessions/                       ← FileSessionBackend (自动管理)
```

### 映射关系

| 概念 | 来源 | 示例 |
|------|------|------|
| 账号 workspace | `InboundMessage.sender_id` | `{base}/alice/` |
| 会话 workspace | `sender_id + channel + chat_id` | `{base}/alice/sessions/telegram/chat_001/files/` |
| session_key | `channel:chat_id` | `telegram:chat_001` |
| memory namespace | `sender_id` | `alice` |
| 会话存储路径 | `FileSessionBackend._path(session_key)` | `{base}/sessions/telegram/sessions/chat_001/session.jsonl` |

### 隔离双层防御

1. **业务层**：`Agent.process()` 解析 session_key → `sender_id` + `channel` + `chat_id`，计算 workspace，写入 `ToolExecutionContext.cwd`
2. **OS 层（srt）**：worker 子进程被 `srt --read {account_ws} --write {account_ws}` 包装。Seatbelt (macOS) / bubblewrap (Linux) 在内核级拒绝越权访问

---

## 三、核心流程

### Agent.process() 流程

```
1. 解析 session_key / account / channel / chat_id
2. 解析会话 workspace: {base}/{account}/sessions/{channel}/{chat_id}/files/
3. 获取 per-session asyncio.Lock（同会话串行）
4. 加载/创建 Session
5. get_history() → 添加上下文
6. add_message("user", content)
7. save(session)
8. maybe_consolidate(session, account=account)  # namespace = account
9. loop.run(msg, history, cwd=session_ws)
10. _save_turn(session, result)  # 只保存本轮新消息
11. save(session)
12. 返回 OutboundMessage
```

### 工具执行管线 (loop.py)

```
LLM tool_call
  → _execute_tool_call(tc, msg, workspace)
      → lookup: tools.get(name) → 不存在？返回错误
      → validate: Pydantic input_model → 失败？返回错误
      → permission: _check_tool(name, tool, parsed) → 拒绝？返回错误
      → execute: tool.execute(parsed, ctx) → 异常？返回错误
  → 截断 (16K 上限)
  → 追加到 messages
```

### 子 Agent 生命周期

```
1. LLM 调用 agent(name="researcher", prompt="...")
2. AgentTool: 查定义 → 计算工具集 → spawn(config, origin_session_key, origin_account)
3. SubprocessBackend:
   → 推导 account workspace
   → 构建 srt 命令
   → srt --read={ws} --write={ws} -- python -m llm_harness --worker ...
   → _watch task 启动
4. Worker: 读 stdin → 跑 ReAct → stdout 出结果
5. _watch: proc.communicate() → InboundMessage(session_key_override=origin_key) → bus.publish_inbound
6. 主 Agent 下一轮看到 task-notification → 读取结果
```

### Memory Consolidation

```
1. maybe_consolidate(session, account="alice")
2. estimate_session_prompt_tokens:
   → probe tokens + tool tokens + history tokens (active messages)
3. should_consolidate: if estimated >= budget → 触发
4. pick_consolidation_boundary: 找到 user 消息边界
5. backend.consolidate(namespace="alice", chunk)
6. remove_before(boundary): 删除已合并消息
7. save(session)
```

---

## 四、设计模式

| 模式 | 位置 | 说明 |
|------|------|------|
| Adapter | `adapters/` 全部 | 后端适配到统一 Protocol |
| Strategy | 5 个 Protocol + Harness URL | 运行时切换后端 |
| Template Method | `LLMProvider.chat_with_retry()` | 重试逻辑基类，调用子类 chat() |
| Observer | `EventBus` + `ObservabilityBackend` | Pub-sub 17 种事件 |
| Facade | `Agent.process()` | 编排 session/consolidator/loop/observability |
| Factory | `ToolFactory` | 统一工具创建，依赖注入 |
| Pipeline | `loop._execute_tool_call()` | 验证→权限→执行，early return |
| Composite | `resolve_safe_path()` | 路径 sanitization + 遍历检查 |

---

## 五、修复历史

### 第一轮审查修复（25 项 → 全部修复）
见 `docs/code-review-2026-05-28.md` 和 `docs/code-review-fix-2026-05-28.md`

### 第二轮修复（本轮会话）
- Bug B: TencentDB close() 竞态 → 加 `_client_lock`
- Bug C: Mailbox poll() 消息丢失 → `poll()` 只读 + `ack()` 删除
- Bug D: Worker api_key 未传递 → `_instantiate_provider` 读环境变量
- Bug E: Worker 工具不全 → ToolFactory + SRTSandboxBackend
- Bug F: SystemExit 在库代码 → 改为 ValueError
- 改进 G: 回调类型 Any → Protocol
- 改进 H: 路径清理重复 → `_path_utils.py`
- 改进 I: session_key 契约 → Session.channel/chat_id 属性

### 第三轮修复（多租户 + srt 沙箱）
- 删除 OpenSandboxBackend + LocalSandboxBackend
- 新增 SRTSandboxBackend（双层防御）
- 多租户 workspace 隔离
- 子 Agent spawn 修复（account 传递 + session_key_override）
- srt glob 遍历修复
- Memory namespace 一致性修复
- TokenBudgetPolicy 修复（计入 history tokens）
- srt execute env 传递 + timeout kill
- SubprocessBackend config.model 传递 + stderr 日志

---

## 六、当前状态

- **测试**: 422 passed, 0 failed
- **沙箱**: SRTSandboxBackend（默认）
- **多租户**: 基于 sender_id 的完整隔离
- **权限**: PermissionChecker 含敏感路径保护 + 可配置 deny 列表
- **记忆**: TokenBudgetPolicy + MessageCountPolicy 可用
- **子 Agent**: SubprocessBackend (srt 包装) + InProcessBackend
