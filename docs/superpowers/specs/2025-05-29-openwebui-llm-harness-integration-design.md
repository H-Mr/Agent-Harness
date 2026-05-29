# Open WebUI + llm-harness 集成：SaaS Agent 系统设计

## 1. 概述

将 Open WebUI 作为壳，llm-harness 作为 Agent 内核，构建一个面向内部团队的 AI 工作台。

**目标用户**：内部团队成员（管理员创建账号分发给同事）。

**使用场景**：通用对话、上传数据分析、Web 搜索整理、配置 Skill 和 MCP 做专项分析。

**核心原则**：Open WebUI 管数据（用户、聊天、Skill/MCP 定义），llm-harness 管能力（Agent 执行、工具、记忆压缩、Skill/MCP 加载）。

## 2. 架构

```
┌──────────────────────────────────────────────────────────┐
│                  Open WebUI（壳 — 改动）                    │
│                                                           │
│  Svelte 前端                                               │
│  ├─ 聊天界面（已有，微调 model 选择下拉）                    │
│  ├─ 扩展管理页（新建：Skill + MCP 统一管理）                │
│  └─ API Key 设置（已有，保留）                              │
│                                                           │
│  FastAPI 后端                                              │
│  ├─ /auth/*         登录注册（已有，不动）                   │
│  ├─ /chats/*        聊天记录（已有，不动）                   │
│  ├─ /skills/*       Skill CRUD（新建）                     │
│  ├─ /mcp/*          MCP Server CRUD（新建）                │
│  └─ POST /chat/completions → 调 Agent.process（核心改动）    │
│                                                           │
│  SQLite                                                    │
│  ├─ user        +api_key, +preferred_model                 │
│  ├─ chat        聊天记录（原有）                            │
│  ├─ skill       用户自定义 Skill（新建）                    │
│  └─ mcp_server  用户自定义 MCP Server（新建）               │
└──────────────────┬───────────────────────────────────────┘
                   │ import llm_harness，直接调用
┌──────────────────▼───────────────────────────────────────┐
│                llm-harness（内核）                          │
│                                                           │
│  Agent.process(msg, *, history=None, config=None)         │
│  ├─ history 来源不关心（外部传入 or session backend）      │
│  ├─ MemoryConsolidator → TencentDB（已有）                 │
│  ├─ AgentLoop（ReAct：LLM ↔ 工具循环）                     │
│  ├─ ToolFactory（read_file, exec, web_search...）          │
│  ├─ SkillsLoader（从文件加载）                              │
│  └─ connect_mcp_servers()（已有，不改）                    │
│                                                           │
│  文件系统仅存：工具执行临时文件                               │
│  workspace/{user_id}/sessions/{chat_id}/files/            │
│                                                           │
│  改动：Agent.process() +history 可选参数，+流式 yield        │
│        约 20 行，独立模式行为不变                           │
└──────────────────────────────────────────────────────────┘
```

## 3. 数据所有权

| 数据 | 存储位置 | 归属 |
|------|---------|------|
| 用户信息 + API Key | SQLite user 表 | Open WebUI |
| 聊天记录（全部消息） | SQLite chat 表 | Open WebUI |
| Skill 定义 | SQLite skill 表 | Open WebUI |
| MCP Server 配置 | SQLite mcp_server 表 | Open WebUI |
| 长期记忆（压缩后知识） | TencentDB Memory | llm-harness |
| 工具临时文件 | workspace/{user_id}/.../files/ | llm-harness |
| 全局 providers/key 配置 | config.yaml | 系统管理员 |

**不存的数据**：`session.jsonl`。SaaS 模式下聊天历史以 Open WebUI SQLite 为唯一数据源。

## 4. Agent.process() — 不关心 history 来源

```python
# agent.py — 改动约 20 行

async def process(
    self,
    msg: InboundMessage,
    *,
    history: list[dict] | None = None,   # ← 新增可选参数
) -> AsyncGenerator[str, None]:          # ← 改为流式 yield

    if history is None:
        # standalone 模式：走 session backend
        session = await self._sessions.get_or_create(msg.session_key)
        history = session.get_history()
        session.add_message("user", msg.content)
        await self._sessions.save(session)
    else:
        # SaaS 模式：外部传入，直接使用
        session = None

    # 以下逻辑不变：
    # consolidator.maybe_consolidate → loop.run → yield delta
```

| 模式 | history 来源 | 谁调 |
|------|-------------|------|
| standalone | FileSessionBackend 从 JSONL 读 | `launcher.py` |
| SaaS | Open WebUI 从 SQLite 读，传进来 | FastAPI 后端 |

## 5. 配置分层

```
系统管理员（部署时写 config.yaml）
├─ providers（支持哪些 LLM：Anthropic/OpenAI/DeepSeek/...）
├─ 全局 API keys（默认 key，用户可选覆盖）
├─ 默认工具集（read_file, exec, web_search, ...）
├─ 全局 skills（所有用户共享）
├─ 沙箱配置
└─ Memory 配置（TencentDB URL）

普通用户（前端可配置）
├─ 自己的 API Key（可选覆盖全局 key）
├─ 偏好的 model（下拉选）
├─ 自定义 skills（CRUD）
├─ 自定义 MCP servers（CRUD）
└─ 自定义 system prompt

每次对话（前端临时切换）
├─ 本次用哪个 model（下拉切换）
└─ 本次启用/禁用哪些 MCP
```

## 6. 一次对话的完整流程

```
1. 用户输入消息 → 前端 POST /chat/completions
   请求体：{ model: "claude-sonnet", message: "...", chat_id: "xxx" }

2. FastAPI 后端：
   a. 验 JWT → user
   b. 从 SQLite 加载：
      - user.api_key / user.preferred_model
      - chat.messages（历史，全量 list[dict]）
      - user 的 skills + 全局 skills → 同步到文件
      - user 的 mcp_servers → 构建连接配置
   c. 拼 agent_config

3. 调用 agent.process(msg, history=history)：
   - history 由 Open WebUI 传入，agent 不关心来源
   - agent 负责：consolidation → ReAct loop → 流式 yield

4. 前端 SSE 接收 → 渲染

5. 结束：后端将新一轮消息写入 SQLite chat 表
```

## 7. Skill 管理

### 数据模型

```sql
CREATE TABLE skill (
    id          TEXT PRIMARY KEY DEFAULT (uuid()),
    user_id     TEXT NOT NULL,
    name        TEXT NOT NULL,
    description TEXT DEFAULT '',
    content     TEXT NOT NULL,    -- YAML frontmatter + Markdown body
    created_at  INTEGER NOT NULL,
    updated_at  INTEGER NOT NULL,
    FOREIGN KEY (user_id) REFERENCES user(id),
    UNIQUE(user_id, name)
);
```

Skill content 格式：
```markdown
---
name: 销售数据分析
description: 分析销售CSV，生成趋势图和总结报告
---

你是一个销售数据分析专家。当用户上传销售数据时：
1. 先检查数据质量和完整性
2. 用 Python 做统计分析
3. 生成趋势图
4. 给出业务建议
```

### API

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /api/v1/skills | 列出当前用户的 skills |
| POST | /api/v1/skills | 新建 skill |
| GET | /api/v1/skills/{id} | 查看单个 skill |
| PUT | /api/v1/skills/{id} | 编辑 skill |
| DELETE | /api/v1/skills/{id} | 删除 skill |

## 8. MCP Server 管理

MCP 和 Skill 本质相同——用户配置的扩展能力。存储方式一致，前端共用一个管理入口。

### 数据模型

```sql
CREATE TABLE mcp_server (
    id          TEXT PRIMARY KEY DEFAULT (uuid()),
    user_id     TEXT NOT NULL,
    name        TEXT NOT NULL,           -- 显示名，如 "公司数据库"
    transport   TEXT NOT NULL,           -- "stdio" | "sse" | "streamableHttp"
    command     TEXT,                    -- stdio: 命令
    args        TEXT,                    -- stdio: 参数 (JSON array)
    url         TEXT,                    -- sse/http: URL
    headers     TEXT,                    -- http: headers (JSON object)
    enabled     INTEGER DEFAULT 1,
    created_at  INTEGER NOT NULL,
    updated_at  INTEGER NOT NULL,
    FOREIGN KEY (user_id) REFERENCES user(id),
    UNIQUE(user_id, name)
);
```

### 数据流

```
用户前端配置 MCP ──→ SQLite mcp_server 表
                          │
POST /chat 时：            │
  1. 从 SQLite 读 user 的 mcp_server 列表
  2. 格式化为 llm-harness connect_mcp_servers() 需要的 dict
  3. connect_mcp_servers(mcp_configs, tool_registry)
  4. MCP 工具注册到本次 ToolRegistry
  5. AgentLoop 执行，LLM 可调用 MCP 工具
  6. 请求结束 → 断开连接（AsyncExitStack 回收）
```

### API

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /api/v1/mcp | 列出当前用户的 MCP servers |
| POST | /api/v1/mcp | 新建 MCP server |
| GET | /api/v1/mcp/{id} | 查看单个 MCP server |
| PUT | /api/v1/mcp/{id} | 编辑 MCP server |
| DELETE | /api/v1/mcp/{id} | 删除 MCP server |

### 请求时连接生命周期

```python
# agent_bridge.py — 每次请求临时连接，用完释放

async def run_agent_with_mcp(user_id, history, msg, mcp_configs):
    stack = AsyncExitStack()
    try:
        registry = ToolRegistry()
        # 注册默认工具
        # 连接 MCP → 注册工具
        await connect_mcp_servers(mcp_configs, registry, stack)
        # 执行 agent
        async for delta in agent.process(msg, history=history):
            yield delta
    finally:
        await stack.aclose()  # 断开所有 MCP 连接
```

MCP 建立连接一般是毫秒级（本地 stdio）到秒级（远程 HTTP），对对话延迟可接受。

### 前端管理页

Skill 和 MCP 共用一个管理入口，Tab 切换：

```
┌─ 扩展能力 ────────────────────────────────────┐
│  [Skills]  [MCP 服务器]                        │
│                                                │
│  ┌─ Skills ──────────────────── [+] 新建 ────┐ │
│  │ 📝 销售数据分析    [编辑] [删除]            │ │
│  │ 📝 SQL 查询助手    [编辑] [删除]            │ │
│  │ 📝 图表生成器      [编辑] [删除]            │ │
│  └────────────────────────────────────────────┘ │
│                                                │
│  ┌─ MCP 服务器 ───────────────── [+] 添加 ────┐ │
│  │ 📡 公司数据库 (stdio)     [编辑] [删除]     │ │
│  │ 📡 文件搜索 (sse)         [编辑] [删除]     │ │
│  │ 📡 Git 工具 (streamableHttp) [编辑] [删除]  │ │
│  └────────────────────────────────────────────┘ │
└────────────────────────────────────────────────┘
```

## 9. 核心代码改动

### 9.1 Open WebUI 改动清单

| 文件 | 改动 | 说明 |
|------|------|------|
| `models/users.py` | +api_key, +preferred_model | User 表加列 |
| `models/skills.py` | 新建 | Skill ORM |
| `models/mcp.py` | 新建 | MCP Server ORM |
| `routers/openai.py` | 重写 generate_chat_completion | HTTP→LLM 换 agent.process() |
| `routers/skills.py` | 新建 | Skill CRUD |
| `routers/mcp.py` | 新建 | MCP Server CRUD |
| `agent_bridge.py` | 新建 | 请求时组装 agent → 调 process → SSE 流式 |
| `main.py` | 注册路由, import agent | ~5 行 |
| `config.yaml` | 新建 | 全局配置 |

### 9.2 llm-harness

`Agent.process()` 两个小改动，约 20 行：

1. **+history 可选参数**：`history=None` 时走原 session backend，非 None 时直接使用
2. **改为 async generator**：`yield delta` 替代 `return result`，支持流式

独立模式（`launcher.py`）行为完全不变——不传 history 参数，走原有 session 加载逻辑。

### 9.3 前端改动清单

| 位置 | 改动 | 说明 |
|------|------|------|
| `routes/extensions/` | 新建 | Skill + MCP 统一管理页 |
| `components/chat/Chat.svelte` | 微调 | model 下拉选择绑定 |
| 删除 | — | Admin 面板、RAG、Functions、Evaluations、Model 管理 |

### 9.4 删除的 Open WebUI 功能

| 功能 | 原因 |
|------|------|
| Workspace/Admin 面板 | 用户管理由管理员命令行操作 |
| RAG/Knowledge | llm-harness memory 替代 |
| Model 管理后台 | config.yaml 管理 |
| Ollama 直连 | llm-harness 统一路由 |
| Evaluations | 不需要 |
| Functions/Tools 配置 | llm-harness ToolFactory 统一管理 |

## 10. 配置文件 (config.yaml)

```yaml
# 系统管理员配置 — 部署时填写

providers:
  anthropic:
    api_key: "sk-ant-..."
    default_model: "claude-sonnet-4-6"
  openai:
    api_key: "sk-..."
    default_model: "gpt-4o"
  deepseek:
    api_key: "sk-..."
    default_model: "deepseek-chat"
    api_base: "https://api.deepseek.com"

default_tools:
  - read_file
  - write_file
  - exec
  - web_search
  - web_fetch
  - glob
  - grep

permissions: "default"

workspace_root: "/data/llm-harness/workspace"

global_skills_dir: "/data/llm-harness/skills"

memory:
  backend: "tencentdb"
  base_url: "http://localhost:8420"

sandbox:
  backend: "srt"

server:
  host: "0.0.0.0"
  port: 8080
```

## 11. 不改的 llm-harness 组件

| 组件 | 原因 |
|------|------|
| `core/agent.py` — Agent.process | 核心入口，+20 行不改架构 |
| `core/loop.py` — AgentLoop | ReAct 引擎，原样用 |
| `core/tools/` — 所有工具 | 工具能力，原样用 |
| `core/tools/factory.py` | 工具创建，原样用 |
| `adapters/memory/` — Memory 系统 | 长期记忆，原样用 |
| `adapters/sandbox/` — Sandbox | 安全沙箱，原样用 |
| `extensions/skills/` — SkillsLoader | Skill 加载，原样用 |
| `extensions/mcp/` — connect_mcp_servers | MCP 连接，原样用 |
| `core/permissions/` — PermissionChecker | 权限检查，原样用 |
| `adapters/providers/` — LLM Provider | 多 Provider 适配，原样用 |
| `core/launcher.py` | standalone 模式用，SaaS 不用 |
| `extensions/channels/` | standalone 模式用，SaaS 不用 |
| `core/bus/` — MessageBus | standalone 模式用，SaaS 不用 |

## 12. 项目结构

```
llm-harness/
├── src/llm_harness/            ← llm-harness 框架
├── tests/                      ← 测试
├── web-ui/                     ← Open WebUI（改造）
│   └── open-webui/
│       ├── backend/
│       │   ├── open_webui/
│       │   │   ├── main.py              ← 注册 routes
│       │   │   ├── config.yaml          ← 全局配置
│       │   │   ├── agent_bridge.py      ← llm-harness 桥接层
│       │   │   ├── routers/
│       │   │   │   ├── openai.py        ← 重写：POST /chat
│       │   │   │   ├── skills.py        ← Skill CRUD
│       │   │   │   └── mcp.py           ← MCP Server CRUD
│       │   │   └── models/
│       │   │       ├── users.py         ← +api_key, +preferred_model
│       │   │       ├── skills.py        ← Skill ORM
│       │   │       └── mcp.py           ← MCP Server ORM
│       │   └── requirements.txt         ← +llm-harness
│       └── src/                         ← Svelte 前端
│           └── lib/
│               ├── components/chat/     ← 微调
│               └── routes/extensions/   ← Skill + MCP 管理页
├── docs/
│   └── superpowers/specs/
│       └── 2025-05-29-openwebui-llm-harness-integration-design.md
└── CLAUDE.md
```

## 13. 风险与约束

- **SkillsLoader 文件依赖**：每次请求前将 SQLite 中 skill 同步到文件。读取频繁、写入少，无性能问题。
- **MCP 连接生命周期**：每次请求临时建立、用完释放。本地 stdio 毫秒级，远程 HTTP 秒级，可接受。
- **Agent 复用**：`Agent` 对象在 FastAPI 启动时创建，内部无请求级状态，线程安全。
- **SSE 流式**：`agent.process()` 改为 async generator，FastAPI `StreamingResponse` 包装。
