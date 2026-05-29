# llm-harness Framework Documentation Design

## Scope

Complete documentation for the llm-harness Agent development framework, following the Diátaxis framework (tutorials / how-to guides / reference / explanation) plus a structured 7-day mastery learning path.

## Document Toolchain

- **Format**: Markdown
- **Builder**: MkDocs + Material theme
- **Structure**: `docs/` root with four Diátaxis quadrants as subdirectories
- **Language**: Chinese narrative, English docstrings and API names
- **Docstrings**: Supplement all public classes/methods with English docstrings during implementation

## Structure

```
docs/
├── index.md                          # Landing page
├── tutorials/
│   ├── 7-day-mastery.md              # Structured 7-day learning path
│   ├── quickstart.md                 # 5-minute quickstart (extracted from Day 1)
│   └── first-agent.md                # Full example: Harness → Agent → message
├── how-to/
│   ├── custom-tool.md               # Implementing custom tools
│   ├── custom-provider.md           # Adding new LLM providers
│   ├── custom-sandbox.md            # Custom sandbox backends
│   ├── custom-memory.md             # Custom memory backends
│   ├── channels.md                  # WebSocket / CLI channel setup
│   ├── mcp-integration.md           # MCP server integration
│   ├── hooks.md                     # Lifecycle hook configuration
│   ├── skills.md                    # Loading custom skills
│   └── permissions.md              # Permission policy configuration
├── reference/
│   ├── harness.md                   # Harness API
│   ├── agent.md                     # Agent API
│   ├── loop.md                      # AgentLoop API
│   ├── session.md                   # Session data model
│   ├── tools.md                     # ToolRegistry / BaseTool / built-in tool catalog
│   ├── providers.md                 # LLMProvider / ProviderSpec registry
│   ├── config.md                    # Config schema — all fields
│   └── events.md                    # Observability event types
└── explanation/
    ├── architecture.md              # Overall architecture & data flow
    ├── dependency-injection.md      # Why all-params-required, no defaults
    ├── protocol-design.md           # Protocol-driven adapter philosophy
    └── async-model.md              # Async model & concurrency strategy
```

## 7-Day Mastery Module (Detailed)

### Day 1 — Installation & First Agent (3h)

**Theory (45min):**
- Framework positioning: not a LangChain wrapper, not a Dify replacement. A pure async, stateless, DI-driven Agent engine kernel.
- Three-layer model deep-dive: Harness (assembler) → Agent (pure engine) → AgentLoop (ReAct skeleton)
- Data flow diagram: InboundMessage → Agent.process() → build_context → LLM API → tool_call or text → messages list → TurnResult → _save_turn → Session

**Hands-on (2h):**
- Install and verify
- Create Provider + AgentLoop directly (no Harness), understand the raw layer
- Then use Harness for assembly, observe what Harness adds (permissions, memory, skills, system prompt assembly)
- Debug exercise: wrong API key → observe retry behavior

**Deliverable (45min):**
- `hello_agent.py`: env-var driven, Harness + Agent, single message, print reply
- Bonus: print `session.messages` to observe full message history

**Post-lesson reflection:**
- What happens if two coroutines call `process()` on the same Agent instance simultaneously?

### Day 2 — Tool System (3.5h)

**Theory (45min):**
- Tool system quintuple: BaseTool → ToolRegistry → ToolExecutionContext → ToolResult → ToolFactory
- Schema dual format: `to_api_schema("openai")` vs `to_api_schema("anthropic")`
- Full execution trace through `_execute_tool_call`: lookup → parse → permission → context → execute → truncate
- Built-in tool catalog: 15 tools with name / dependencies / readonly / class

**Hands-on (2.5h):**
- Exercise 1: read_file + write_file → create and read a Markdown file
- Exercise 2: glob + grep → search directories
- Exercise 3: exec → run `git status`
- Exercise 4: web_search + web_fetch → research workflow
- Exercise 5: ask_user_question → observe when LLM invokes it
- Debug: log every tool call with name+args in `on_tool_check`
- Error: pass invalid args, observe Pydantic error messages

**Deliverable (15min):**
- `tool_lab.py`: 8+ tools registered, comprehensive task with multi-tool chain

### Day 3 — Sessions & Memory (3.5h)

**Theory (1h):**
- Session dataclass field-by-field: key / messages / last_consolidated / metadata
- `get_history()` slicing: skip consolidated → take last N → forward-search to nearest user message
- `remove_before()` for consolidation cleanup
- MemoryConsolidator: TokenBudgetPolicy → estimation → boundary picking → lock → consolidate → remove → save
- MemoryBackend Protocol: 5 method signatures
- TencentDB backend: HTTP API interaction
- Two policies: TokenBudgetPolicy vs MessageCountPolicy

**Hands-on (2h):**
- Exercise 1: 5-turn conversation, observe message accumulation
- Exercise 2: Print `get_history()` output, verify forward-search behavior
- Exercise 3: Manual `remove_before()` and observe `get_history()` change
- Exercise 4: Integrate TencentDBMemoryBackend, mock HTTP to verify `consolidate()` calls
- Exercise 5: Estimate token consumption, compare with `should_consolidate` decisions
- Debug: add logging at `maybe_consolidate` entry

**Deliverable (30min):**
- `session_lab.py`: 10-turn simulation tracking messages, tokens, consolidation decisions
- Consolidation timeline diagram

### Day 4 — Providers & Configuration (3.5h)

**Theory (1h):**
- LLMProvider class hierarchy: ABC → chat / chat_stream + retry template methods
- Retry strategy: delays (1, 2, 4) → transient keyword match → image fallback → final attempt
- Sentinel value pattern: `_SENTINEL = object()` for default-vs-None disambiguation
- Message sanitization pipeline: empty content → allowlist filter → cache control
- AnthropicProvider vs OpenAICompatProvider: message conversion, prompt caching, thinking mode
- ProviderSpec registry: 29 providers, `detect_provider()` 3-step matching
- Config loading chain: CLI args > env vars > YAML > defaults

**Hands-on (2h):**
- Exercise 1: Create `harness.yaml` with full configuration
- Exercise 2: `load_config()` with CLI override
- Exercise 3: Run same message through Anthropic + OpenAI providers, compare parameters
- Exercise 4: Mock transient errors (429 → retry → success)
- Exercise 5: Mock image fallback (non-transient error + images → strip → retry)
- Exercise 6: Test `detect_provider` matching logic
- Exercise 7: Implement a custom ProviderSpec for a private gateway

**Deliverable (30min):**
- `config_lab.py` + `harness.yaml`: config-driven Agent
- `provider_test.py`: 3 providers side-by-side comparison

### Day 5 — Extension System (3.5h)

**Theory (1h):**
- Four extension systems overview: MCP / Skills / Hooks / Channels
- MCP: schema normalization, dynamic Pydantic model creation, tool filtering
- Skills: progressive disclosure, `DirectorySkillLoader._scan()`, SkillTool
- Channels: WebSocket auth flow, ChannelManager dispatch, streaming deltas

**Hands-on (2h):**
- Exercise 1: Connect real MCP server, register tools
- Exercise 2: Create custom SKILL.md, load and verify
- Exercise 3: Configure PreToolUse + PostToolUse hooks
- Exercise 4: WebSocketChannel with websocat
- Exercise 5: Dual channels (CLI + WebSocket)

**Deliverable (30min):**
- `extended_agent.py`: MCP + Skills + WebSocket integration
- `skills/hello-skill/SKILL.md`: custom skill

### Day 6 — Observability, Permissions & Sub-agents (3h)

**Theory (1h):**
- Event system: 11 event types, EventEmitter, DefaultObservabilityBackend, emission points
- Permission system: 3-layer architecture, `evaluate()` 9-step check order, PermissionDecision
- Swarm: AgentDefinition, AgentBackend Protocol, SubprocessBackend, Mailbox, tool set computation

**Hands-on (1.5h):**
- Exercise 1: Custom `on_emit` → JSONL file, verify event sequence
- Exercise 2: `denied_tools=["exec"]` → verify rejection
- Exercise 3: `path_rules` deny `*.env` → verify rejection
- Exercise 4: AgentTool spawn researcher sub-agent
- Exercise 5: Observe sub-agent lifecycle end-to-end

**Deliverable (30min):**
- `observability_lab.py`: JSONL event recording
- `permission_lab.py`: permission mode demonstrations
- `swarm_lab.py`: main agent → spawn researcher → await result

### Day 7 — Custom Adapters & Production Deployment (3.5h)

**Theory (1h):**
- Four core Protocol signatures: SandboxBackend (8), MemoryBackend (5), AgentBackend (3), SessionBackend (3)
- Protocol design philosophy: structural subtyping, DI injection, minimal method set
- Production deployment checklist: queue limits, lock timeouts, max iterations, truncation, logging, graceful shutdown, tenant isolation
- Performance characteristics: pure async, lazy imports, prompt caching, connection reuse

**Hands-on (2h):**
- Exercise 1: Implement RedisMemoryBackend (all 5 methods)
- Exercise 2: Write unit tests for RedisMemoryBackend
- Exercise 3: Implement DockerSandboxBackend
- Exercise 4: Implement custom SessionBackend (PostgreSQL/SQLite)
- Exercise 5: docker-compose.yml for production deployment

**Deliverable (30min):**
- `redis_memory.py`: complete RedisMemoryBackend
- `test_redis_memory.py`: unit tests
- `docker_sandbox.py`: DockerSandboxBackend
- `deploy/docker-compose.yml`: production config

### Daily Checkpoints

```
Day 1 ✅ python hello_agent.py → outputs coherent reply
Day 2 ✅ python tool_lab.py → 3+ tools invoked in chain
Day 3 ✅ python session_lab.py → consolidation triggered by round 8
Day 4 ✅ python config_lab.py → Agent loaded from YAML
Day 5 ✅ python extended_agent.py → MCP + Skills + WebSocket all active
Day 6 ✅ python swarm_lab.py → sub-agent spawned and result returned
Day 7 ✅ python test_redis_memory.py → all tests pass
```

## Implementation Phases

### Phase 1: Foundation
- mkdocs.yml config
- index.md landing page
- `explanation/architecture.md`
- `explanation/dependency-injection.md`

### Phase 2: Reference (generated + written)
- Supplement all public class/method docstrings
- `reference/` — all API reference pages

### Phase 3: Tutorials
- `tutorials/7-day-mastery.md` (longest single doc)
- `tutorials/quickstart.md`
- `tutorials/first-agent.md`

### Phase 4: How-To Guides
- All 9 how-to guides

### Phase 5: Remaining Explanation
- `explanation/protocol-design.md`
- `explanation/async-model.md`

## Success Criteria

- [ ] mkdocs build succeeds with zero warnings
- [ ] All public classes/methods have docstrings
- [ ] 7-day mastery: each day has runnable deliverable with verification command
- [ ] Reference docs cover all public API surfaces
- [ ] How-to guides each solve one concrete task with copy-pasteable code
- [ ] Explanation docs answer "why" not "what"
