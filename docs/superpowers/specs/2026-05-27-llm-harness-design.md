# llm-harness 设计文档

## 定位

定制化轻量 AI Agent 基础设施库。Harness 只做编排，不造轮子。

公式：`Harness + 5 Backends + LLM = Agent`

---

## 目录结构

```
llm_harness/
├── core/
│   ├── bus/                         # InboundMessage / OutboundMessage / MessageBus
│   ├── tools/                       # BaseTool, ToolRegistry, 内置工具
│   ├── permissions/                 # PermissionChecker (FULL_AUTO / PLAN / DEFAULT)
│   ├── session/
│   │   ├── session.py               # Session 数据类 (纯结构，无 IO)
│   │   └── manager.py               # SessionManager (包装 SessionBackend, 内存缓存)
│   ├── loop.py                      # AgentLoop 纯骨架 (行为通过回调注入)
│   └── harness.py                   # IoC 容器 (组装后端 + 回调 + 扩展)
│
├── adapters/                        # 5 个后端，全部通过 Protocol 解耦
│   ├── memory/
│   │   ├── backend.py               # MemoryBackend Protocol
│   │   ├── tencentdb.py             # TencentDB Agent Memory 适配器 (默认)
│   │   ├── file.py                  # 本地文件后备
│   │   ├── policy.py                # TokenBudgetPolicy / MessageCountPolicy
│   │   └── consolidator.py          # MemoryConsolidator
│   ├── sandbox/
│   │   ├── backend.py               # SandboxBackend Protocol (文件操作 + exec)
│   │   └── opensandbox.py           # OpenSandbox 适配器 (默认)
│   ├── swarm/
│   │   ├── backend.py               # AgentBackend Protocol
│   │   ├── subprocess.py            # SubprocessBackend (默认, 独立进程)
│   │   ├── in_process.py            # InProcessBackend (轻量, ContextVar 隔离)
│   │   ├── mailbox.py               # 文件消息队列
│   │   └── definitions.py           # AgentDefinition 注册表
│   ├── session/
│   │   ├── backend.py               # SessionBackend Protocol
│   │   └── file.py                  # JSONL 文件后端 (默认)
│   ├── observability/
│   │   ├── backend.py               # ObservabilityBackend Protocol
│   │   ├── default.py               # 内存 EventBus + JSONL Tracker (默认)
│   │   └── events.py                # 17 种事件类型
│   └── providers/
│       ├── base.py                  # LLMProvider (含 api_format 属性)
│       ├── registry.py              # ProviderSpec, detect_provider
│       ├── anthropic_provider.py
│       └── openai_compat_provider.py
│
├── extensions/                      # 可选扩展
│   ├── hooks/                       # PRE/POST 工具钩子
│   ├── skills/                      # Markdown 技能加载
│   ├── mcp/                         # MCP 客户端
│   ├── cron/                        # 定时调度
│   └── channels/                    # CLI / HTTP / WS / 微信 / 飞书
│
├── config/
│   ├── schema.py                    # Config Pydantic 模型
│   └── loader.py                    # 配置加载 (CLI > env > YAML > 默认)
│
└── __main__.py                      # worker 入口 + 正常启动入口
```

---

## 中心总线

Channel → InboundMessage → bus.publish_inbound() → Agent.process() → bus.publish_outbound() → Channel

子 Agent 结果走同一路径：

```
watcher → InboundMessage(channel="system", content=<task-notification>)
       → bus.publish_inbound()
       → Agent.process 消费
```

### InboundMessage / OutboundMessage

```python
@dataclass
class InboundMessage:
    channel: str           # "cli", "websocket", "wechat", "feishu"
    sender_id: str
    chat_id: str
    content: str
    timestamp: datetime
    session_key: str       # channel:chat_id 组合，会话唯一标识

@dataclass
class OutboundMessage:
    channel: str
    chat_id: str
    content: str
    metadata: dict          # _stream_delta, _stream_end, _progress 等
```

### MessageBus

```python
class MessageBus:
    inbound: asyncio.Queue[InboundMessage]
    outbound: asyncio.Queue[OutboundMessage]

    async def publish_inbound(msg: InboundMessage) -> None
    async def consume_inbound() -> InboundMessage
    async def publish_outbound(msg: OutboundMessage) -> None
    async def consume_outbound() -> OutboundMessage
```

---

## 5 个后端协议

### 1. MemoryBackend

记忆是累积的。append_section 不覆盖，只追加。

```python
class MemoryBackend(Protocol):
    async def get_context(self, namespace: str) -> str:
        """所有 section 组装为 system prompt 块"""
    async def read_section(self, namespace: str, section: str) -> str:
        """读一个 section (memory/rules/persona/user)"""
    async def append_section(self, namespace: str, section: str, entry: str) -> None:
        """追加写入一个 section"""
    async def add_history(self, namespace: str, entry: str) -> None:
        """追加历史记录"""
    async def consolidate(self, namespace: str, messages: list[dict],
                          provider=None, model="") -> bool:
        """合并消息。TencentDB 忽略 provider/model。"""
```

**默认：TencentDBMemoryBackend** — HTTP 调 localhost:8420，内部 L0→L1→L2→L3 流水线。

**后备：FileMemoryBackend** — 每 namespace 一个目录，MEMORY.md / AGENTS.md / SOUL.md / USER.md / history.jsonl。consolidate 用 provider 调 LLM 总结。provider 为空或 LLM 失败 → raw archive 降级。

**HTTP 客户端**：双重检查锁保护 `_ensure_client()`。

### 2. SandboxBackend

所有文件操作和命令执行都通过沙箱。LLM 只看到容器内路径。

```python
class SandboxBackend(Protocol):
    async def create_session(self, session_key: str) -> SandboxSession
    async def destroy_session(self, session_key: str) -> None
    # 文件操作
    async def read_file(self, session_key: str, path: str) -> str
    async def write_file(self, session_key: str, path: str, content: str) -> None
    async def list_dir(self, session_key: str, path: str) -> list[str]
    async def glob(self, session_key: str, pattern: str) -> list[str]
    async def grep(self, session_key: str, pattern: str, path: str) -> list[str]
    # 命令执行
    async def execute(self, session_key: str, command: str, *,
                      cwd="/workspace", env=None, timeout=60) -> ExecResult

@dataclass
class SandboxSession:
    session_key: str
    volume_path: str     # 容器内挂载路径 (LLM 看到的)
    sandbox_id: str      # 后端内部标识

@dataclass
class ExecResult:
    output: str
    exit_code: int
    is_error: bool
```

**create_session 和 destroy_session 的语义：**

```
首次 create_session("key"):
  → 创建 volume + 容器 → 返回 SandboxSession
destroy_session("key"):
  → 销毁容器 → volume 保留
再次 create_session("key"):
  → 检测到已有 volume → 创建新容器 → 挂载已有 volume → 返回
purge_session("key"):
  → 销毁容器 + 删除 volume (显式清理)
```

**Session 文件**（代码改动、安装的包、中间产物）由 volume 跨会话保留。只有 SessionBackend 负责消息历史。MemoryBackend 负责长期记忆。三者互补。

**默认：OpenSandboxBackend** — volume 独立于容器生命周期。

**路径**：LLM 始终看到容器路径（如 `/workspace/project/`）。SandboxBackend 内部翻译为宿主机路径或调 API。LLM 不知道宿主机存在。

### 3. AgentBackend

```python
class AgentBackend(Protocol):
    async def spawn(self, config: SpawnConfig) -> SpawnResult:
        """非阻塞，返回 agent_id 后立即返回"""
    async def send_message(self, agent_id: str, message: str) -> bool:
        """向运行中子 agent 发消息。不存在返回 False"""
    async def stop(self, agent_id: str) -> bool

@dataclass
class SpawnConfig:
    agent_name: str      # AgentDefinition.name
    prompt: str          # 自包含任务描述
    tool_names: list[str]  # 已计算好的工具列表
    model: str = ""

@dataclass
class SpawnResult:
    agent_id: str
    success: bool
    error: str | None = None
```

**默认：SubprocessBackend** — 独立 OS 进程。spawn 后启动 watcher，进程退出时读 stdout → 构造 InboundMessage(channel="system", content=<task-notification>) → bus.publish_inbound。

**子 Agent 有自己的 Session（内存中）**。死即弃。

### 4. SessionBackend

Session 数据类在 core，后端只管持久化。

```python
class SessionBackend(Protocol):
    async def load(self, session_key: str) -> dict | None:
        """返回 session state dict，或 None"""
    async def save(self, session_key: str, state: dict) -> None:
        """持久化 session state"""
    async def list_keys(self) -> list[str]:
        """列出所有已保存的 session key"""
```

**默认：FileSessionBackend** — JSONL 文件存储。

### 5. ObservabilityBackend

```python
EventPayload = dict[str, Any]
EventHandler = Callable[[str, EventPayload], Awaitable[None]]

class ObservabilityBackend(Protocol):
    async def emit(self, event_type: str, payload: EventPayload) -> None:
        """发布事件（内部 try-catch，失败不抛异常）"""
    async def subscribe(self, event_type: str, handler: EventHandler) -> None
    async def unsubscribe(self, event_type: str, handler: EventHandler) -> None
```

**默认：DefaultObservabilityBackend** — 内存 EventBus (pub-sub) + JSONL 文件写入。

**17 种事件类型**：message:received、tool:executing、tool:completed、assistant:delta、assistant:complete、loop:iteration、session:opened、session:closed、agent:spawned、agent:completed、error、 等。

---

## Agent 循环

纯骨架，行为通过回调注入：

```python
class Agent:
    def __init__(
        self,
        provider: LLMProvider,
        model: str,
        tools: ToolRegistry,
        # 三个回调
        on_build_context: Callable,   # (msg, history) → messages
        on_tool_check: Callable,      # (name, tool, args) → PermissionDecision
        on_error: Callable,           # (exc, ctx) → user_msg | None
        # 后端
        memory: MemoryBackend | None,
        sandbox: SandboxBackend | None,
        sessions: SessionManager | None,
        observability: ObservabilityBackend | None,
        swarm: AgentBackend | None,
        # 配置
        max_iterations: int = 40,
    ):
        self._session_locks: dict[str, asyncio.Lock] = {}
        # 删除全局信号量，不同 session 完全并行
```

### process(msg) 流程

```
1. 获取 per-session Lock (同会话串行)
2. session = sessions.get_or_create(msg.session_key)
3. session.add_message("user", msg.content)
4. consolidator.maybe_consolidate(session)
   → 策略判断 → 超限则 backend.consolidate(namespace, messages) → 清理已合并消息
5. messages = on_build_context(msg, history)
   → identity + environment + memory context + sub-agent 列表 + skills
6. ReAct 循环 (max_iterations):
   a. response = provider.chat(messages, tools=tools.to_api_schema(provider.api_format))
   b. 无 tool_calls → 结束
   c. 有 tool_calls → 并行执行:
      → on_tool_check(name, tool, args) → PermissionChecker + Hooks
      → 通过 → tool.execute(args, ctx) → 结果追加到 messages
7. session.add_message("assistant", final_response)
8. sessions.save(session)
9. 返回 OutboundMessage
```

### 工具管线

```
LLM 决定调工具 → Lookup (Registry) → Validate (Pydantic)
→ Permission (on_tool_check 回调) → Hook PRE
→ Execute → Hook POST → 截断 (16K) → 返回 LLM
```

错误不终止循环，作为错误字符串返回 LLM。

---

## 上下文组装 (on_build_context)

固定流程，按 SectionProvider 优先级排列：

```
identity (You are a helpful AI assistant...)
environment (当前时间、平台、工作目录)
memory (MemoryBackend.get_context(session_key))
sub-agents (AgentDefinition 注册表列表)
skills (已加载的技能)
rules (AGENTS.md 项目规则)
```

---

## 工具系统

### 工具依赖注入

Harness 构造工具时根据依赖分类：

无依赖 — 直接实例化：web_search, web_fetch, ask_user_question, notebook_edit, skill, tool_search

依赖 SandboxBackend — 注入实例：read_file, write_file, edit_file, glob, grep, exec

依赖 MemoryBackend — 注入实例：memory_read, memory_write

依赖 AgentBackend + bus — 注入实例：agent, send_message, task_stop

### 子 Agent 工具集组装

```python
result = set(harness_tools) if not tools_allow else set(tools_allow)
result -= set(tools_deny or [])
result |= set(tools_extra or [])
```

---

## Channel 生命周期

每个 Channel 都有两个生命周期钩子：

```python
class BaseChannel(ABC):
    async def on_connect(self, session_key: str):
        await self.sandbox.create_session(session_key)
        await self.sessions.load(session_key)

    async def on_disconnect(self, session_key: str):
        # 获取 session lock 确保没有正在处理的请求
        await self.sessions.save(session_key)
        await self.sandbox.destroy_session(session_key)  # 销毁容器, volume 保留
        self.sessions.invalidate(session_key)
```

触发方式：

| Channel | on_connect | on_disconnect |
|---------|-----------|---------------|
| CLI | 进程启动 | 进程退出 |
| WebSocket | 连接建立 | 连接关闭 |
| HTTP | 请求到达 | 响应返回 |

---

## Skills 加载与隔离

Skills 绑定到 session volume，通过沙箱天然隔离。不同 session 互不可见对方的技能。

```
session "cli:user-a"
  volume: /volumes/user-a/
    ├── workspace/
    └── skills/                    ← 用户 A 的技能
        └── my-skill/SKILL.md

session "cli:user-b"
  volume: /volumes/user-b/
    └── skills/                    ← 用户 B 的技能，物理隔离
```

```
Channel.on_connect(session_key):
  1. sandbox.create_session(session_key) → volume_path
  2. skills = SkillRegistry.load(volume_path / "skills")
  3. sessions.load(session_key)
```

不设全局共享 skills。

---

## Worker 入口

SubprocessBackend 启动 worker 进程：

```
python -m llm_harness --worker --agent-def researcher \
    --tools read_file,glob,grep,exec,skill \
    --skills-path /workspace/skills
```

Worker 进程：读 stdin 拿 prompt → 创建最小 Session → 加载 skills → 建工具实例 → 跑 ReAct 循环 → stdout 输出结果 → 退出。子 agent 和主 agent 使用同一 session volume 下的同一套 skills。

`__main__.py` 作为统一入口，`--worker` 标识 worker 模式。

---

## 子 Agent 生命周期

```
1. LLM 调用 agent(name="researcher", prompt="找出所有 API")
2. AgentTool:
   → 查 AgentDefinition → 计算工具集 → 构造 SpawnConfig
   → backend.spawn(config) → 非阻塞, 返回 agent_id
3. SubprocessBackend:
   → 启动子进程 → watcher 监听
4. 子进程跑完 → watcher 读 stdout
   → InboundMessage(channel="system", content=<task-notification>)
   → bus.publish_inbound()
5. 主 agent 下一轮看到通知 → LLM 读取结果
```

---

## 并发模型

- 同一 session_key → asyncio.Lock 串行
- 不同 session_key → 完全并行
- 不做全局并发限制

---

## 存储全景

| 消息历史 | SessionBackend (JSONL) | 永久 | harness |
|------|------|---------|--------|
| 数据 | 存放 | 生命周期 | 谁管理 |
| 长期记忆 | MemoryBackend (TencentDB) | 永久 | TencentDB 自动 |
| 会话文件 | SandboxBackend volume | 永久 (显式 purge 才删) | OpenSandbox |
| 观测事件 | ObservabilityBackend (JSONL) | 按配置保留 | 后端自动 |

---

## 工具列表

| 工具 | 作用 | 后端依赖 |
|------|------|---------|
| read_file | 读文件 | SandboxBackend |
| write_file | 写文件 | SandboxBackend |
| edit_file | 编辑文件 | SandboxBackend |
| glob | 文件名模式匹配 | SandboxBackend |
| grep | 内容搜索 | SandboxBackend |
| exec | 执行命令 | SandboxBackend |
| web_search | 网络搜索 | 无 |
| web_fetch | 获取网页 | 无 |
| memory_read | 读长期记忆 | MemoryBackend |
| memory_write | 写长期记忆 | MemoryBackend |
| agent | 启动子 agent | AgentBackend + bus |
| send_message | 向子 agent 发消息 | AgentBackend |
| task_stop | 终止子 agent | AgentBackend |
| ask_user_question | 向用户提问 | 无 |
| notebook_edit | 编辑 Jupyter notebook | 无 |
| skill | 调用技能 | 无 |
| tool_search | 搜索可用工具 | 无 |
| task_create/list/update | 任务管理 | 无 |
| cron_create/list/delete | 定时任务 | 无 |

---

## 配置系统

三层优先级：CLI 参数 > 环境变量 > YAML 文件 > 默认值

```python
class Config:
    agent: AgentConfig
    tools: ToolsConfig
    permission: PermissionConfig
    sandbox: SandboxConfig       # backend + base_url
    memory: MemoryConfig         # backend + base_url
    observability: ObservabilityConfig
    channels: list[ChannelConfig]
    workspace: str
```

### Harness URL 简写

```python
harness = Harness(memory="tencentdb://localhost:8420")    # 默认
harness = Harness(memory="file://./workspace")             # 文件后备
harness = Harness(sandbox="opensandbox://localhost:8080")  # 默认
harness = Harness(sandbox="none")                          # 无沙箱
harness = Harness(swarm="subprocess")                      # 默认
harness = Harness(swarm="in_process")                      # 轻量
```
