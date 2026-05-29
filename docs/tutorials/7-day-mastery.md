# 7-Day Mastery Path

A structured, hands-on journey through the llm-harness framework. By day 7 you will have written a custom backend adapter, deployed a multi-service stack, and understand every layer of the framework.

---

## Day 1: Installation & First Agent (3h)

### Theory (45min)

**Framework positioning.** llm-harness is not a LangChain wrapper, not a Dify replacement, and not an AutoGPT clone. It is a pure async, stateless, dependency-injection-driven agent engine kernel. The table below highlights the key differences:

| Dimension | llm-harness | LangChain | AutoGPT |
|---|---|---|---|
| Architecture | DI container + Protocols | Chain-of-callbacks | Monolithic loop |
| State model | Stateless engine; caller owns Session | Chain carries state | Global state |
| Async | Pure async throughout | Mixed sync/async | Synchronous |
| Tool system | Typed, Pydantic-validated | String-based | Ad-hoc |
| Extension model | Protocols (structural subtyping) | Abstract base classes | Plugin system |
| Sandbox | SRT (kernel-level) + business layer | None built-in | None |

**Three-layer model.** Every llm-harness Agent is built from three layers, each with a precise responsibility boundary:

1. **Harness** (assembler) -- Receives all dependencies via constructor injection (provider, tools, sandbox, memory, permissions, skills, observability). It wires callbacks, builds the consolidator, and returns a ready-to-use Agent. The Harness performs ZERO I/O: no filesystem side-effects, no env-var reads, no network calls. Its `create_agent()` method composes the lower layers.

2. **Agent** (pure stateless engine) -- Has zero internal mutable state. Each `process()` call is self-contained: it receives a Session, a message, and a workspace path; it returns a TurnResult. The caller manages session persistence, concurrency, and workspace lifecycle. The Agent calls `session.get_history()`, invokes the consolidator, delegates to AgentLoop, and saves the turn back to the Session.

3. **AgentLoop** (ReAct skeleton) -- The loop that drives tool-calling decisions. With `max_iterations=40`, it sends messages + tool schemas to the LLM, parses tool calls, executes them via the ToolRegistry, appends results, and repeats until the LLM returns a final text response or the iteration limit is reached. Behavior is injected through callbacks (`on_build_context`, `on_tool_check`, `on_error`, `on_event`).

**Data flow for a single turn:**

```
InboundMessage
  --> Agent.process()
    --> session.get_history()                   # load conversation history
    --> session.add_message("user", content)     # append user message
    --> consolidator.maybe_consolidate()         # archive old messages if over budget
    --> AgentLoop.run()
      --> on_build_context(msg, history)         # build system prompt + history + user msg
      --> provider.chat_with_retry(messages, tools, model)
      --> [tool_calls?]                          # LLM decides to call tools
        --> _execute_tool_call()
          --> tool_registry.get(name)
          --> pydantic_model(**args)
          --> permission_checker.evaluate()
          --> ToolExecutionContext(cwd, metadata)
          --> await tool.execute(parsed_args, ctx)
          --> truncate result to 16_000 chars
        --> append result to messages
        --> loop back to chat_with_retry
      --> [no tool_calls]                        # LLM produces final text
    --> _save_turn(session, result)              # persist assistant + tool messages
    --> return TurnResult
```

### Hands-On (2h)

#### Exercise 1: Install and verify

```bash
pip install llm-harness[openai]
```

Then verify the import works:

```python
# verify_import.py
from llm_harness.core.harness import Harness
from llm_harness.core.agent import Agent
from llm_harness.core.loop import AgentLoop, TurnResult
print("All core imports OK -- framework installed")
```

Run:

```bash
python verify_import.py
# --> All core imports OK -- framework installed
```

#### Exercise 2: Create Provider + AgentLoop directly (no Harness)

This exercises your understanding of the raw layers before Harness abstraction hides them:

```python
# raw_loop.py
import os
import asyncio
from pathlib import Path
from llm_harness.adapters.providers.openai_compat_provider import OpenAICompatProvider
from llm_harness.core.tools.base import ToolRegistry
from llm_harness.core.loop import AgentLoop

async def main():
    provider = OpenAICompatProvider(
        api_key=os.environ["LLM_HARNESS_API_KEY"],
        api_base="https://api.deepseek.com",
    )
    tools = ToolRegistry()

    loop = AgentLoop(
        provider=provider,
        tools=tools,
        model="deepseek-chat",
        on_build_context=lambda msg, history: [
            {"role": "system", "content": "You are a helpful assistant."},
            *history,
            {"role": "user", "content": msg.content},
        ],
        on_tool_check=lambda name, tool, args: type("OK", (), {"allowed": True})(),
        on_error=lambda exc, ctx: print(f"Error in {ctx}: {exc}"),
    )

    result = await loop.run(
        type("Msg", (), {"content": "What is the capital of France?"})(),
        [],
        cwd=Path("."),
    )
    print("Reply:", result.final_content)

asyncio.run(main())
```

#### Exercise 3: Use Harness for assembly and compare

```python
# with_harness.py
import os
import asyncio
from pathlib import Path
from llm_harness.adapters.providers.openai_compat_provider import OpenAICompatProvider
from llm_harness.adapters.sandbox.srt import SRTSandboxBackend
from llm_harness.core.harness import Harness
from llm_harness.core.session.session import Session
from llm_harness.core.bus.events import InboundMessage
from llm_harness.core.tools.base import ToolRegistry
from llm_harness.core.tools.factory import ToolFactory

async def main():
    ws = Path("./workspace")
    ws.mkdir(exist_ok=True)

    provider = OpenAICompatProvider(
        api_key=os.environ["LLM_HARNESS_API_KEY"],
        api_base="https://api.deepseek.com",
    )
    sandbox = SRTSandboxBackend(ws)
    factory = ToolFactory(sandbox=sandbox)
    tools = ToolRegistry()
    for name in ["read_file", "write_file", "web_search"]:
        tool = factory.build(name)
        if tool:
            tools.register(tool)

    # Harness adds permissions callback, system prompt assembly,
    # skills list, sub-agent definitions, and error handling.
    harness = Harness(
        provider=provider,
        model="deepseek-chat",
        tools=tools,
        sandbox=sandbox,
        system_prompt="You are a concise assistant.",
    )
    agent = harness.create_agent()
    session = Session(key="demo:chat1")

    msg = InboundMessage("cli", "alice", "c1", "Write 'hello.txt' with content 'Hello world'")
    result = await agent.process(msg, session=session, cwd=ws)
    print("Final:", result.final_content)
    print("Tools used:", result.tools_used)
    print("Session messages:", len(session.messages))
    print("hello.txt content:", (ws / "hello.txt").read_text())

asyncio.run(main())
```

#### Exercise 4: Debug with wrong API key

```python
# debug_wrong_key.py
import asyncio
from pathlib import Path
from llm_harness.adapters.providers.openai_compat_provider import OpenAICompatProvider
from llm_harness.adapters.sandbox.srt import SRTSandboxBackend
from llm_harness.core.harness import Harness
from llm_harness.core.session.session import Session
from llm_harness.core.bus.events import InboundMessage
from llm_harness.core.tools.base import ToolRegistry
from llm_harness.core.tools.factory import ToolFactory

async def main():
    ws = Path("./workspace")
    ws.mkdir(exist_ok=True)

    # Intentionally wrong key -- observe retry behaviour
    provider = OpenAICompatProvider(
        api_key="sk-invalid-key-for-testing",
        api_base="https://api.deepseek.com",
    )
    sandbox = SRTSandboxBackend(ws)
    factory = ToolFactory(sandbox=sandbox)
    tools = ToolRegistry()
    for name in ["read_file"]:
        tool = factory.build(name)
        if tool:
            tools.register(tool)

    harness = Harness(provider=provider, model="deepseek-chat",
                      tools=tools, sandbox=sandbox)
    agent = harness.create_agent()
    session = Session(key="debug:chat1")
    msg = InboundMessage("cli", "user", "c1", "Hello")
    result = await agent.process(msg, session=session, cwd=ws)
    print("Result:", result.final_content)

asyncio.run(main())
```

Observe: the `chat_with_retry` method logs each transient error attempt, applies 1s/2s/4s backoff, and eventually reports a non-transient error.

### Deliverable (15min)

- `hello_agent.py` -- env-var driven, assembles Harness + Agent, sends one message, prints reply and session message count.
- Verify: `LLM_HARNESS_API_KEY=sk-xxx python hello_agent.py` -- outputs a coherent reply.

### Post-Lesson Reflection

Why does Harness deliberately avoid performing any I/O during construction? What problems would eager initialization cause in a production SaaS application?

---

## Day 2: Tool System (3.5h)

### Theory (45min)

The tool system has five components that work together:

**1. BaseTool (ABC).** Every tool extends `BaseTool` and declares three `ClassVar` fields:

- `name: ClassVar[str]` -- unique identifier used by LLM function-calling
- `description: ClassVar[str]` -- shown to the LLM when it decides which tool to call
- `input_model: ClassVar[type[BaseModel]]` -- a Pydantic model that validates arguments before the tool runs

Each tool implements `async def execute(self, arguments: BaseModel, context: ToolExecutionContext) -> ToolResult`.

**2. ToolRegistry (name to instance mapping).** A simple dict-backed registry. `register(tool)`, `get(name)`, `unregister(name)`. The `to_api_schema(api_format)` method returns schemas in the format the provider expects:

- `to_api_schema("openai")` returns `[{"type": "function", "function": {"name": ..., "description": ..., "parameters": ...}}]`
- `to_api_schema("anthropic")` returns `[{"name": ..., "description": ..., "input_schema": ...}]`

**3. ToolExecutionContext.** A dataclass with `cwd: Path` and `metadata: dict`. Passed to every tool execution. The metadata carries session context like `session_key`, `account`, and `channel`.

**4. ToolResult.** A frozen dataclass: `output: str`, `is_error: bool = False`, `metadata: dict`. Standardised return -- the loop checks `is_error` to decide whether to surface the result or a failure message.

**5. ToolFactory.** A builder registry with a `register(name, builder_fn)` API. It uses `importlib.import_module` for lazy loading (tool modules are only imported when built). The factory injects backend dependencies: sandbox tools get the `SandboxBackend`, memory tools get the `MemoryBackend`, swarm tools get the `AgentBackend`.

**Full execution trace** for a tool call inside `_execute_tool_call`:

```python
tool = tools.get(tc.name)                    # 1. Lookup
parsed = tool.input_model(**tc.arguments)     # 2. Pydantic parse + validate
decision = permission_checker.evaluate(...)   # 3. Permission check (if configured)
ctx = ToolExecutionContext(cwd=cwd, metadata={...})
result = await tool.execute(parsed, ctx)      # 4. Execute
truncated = result.output[:16_000]            # 5. Truncate
```

**Built-in tools (15 total):**

| Tool | Backend dependency | Read-only? |
|---|---|---|
| `read_file` | SandboxBackend | Yes |
| `write_file` | SandboxBackend | No |
| `edit_file` | SandboxBackend | No |
| `exec` | SandboxBackend | No |
| `glob` | SandboxBackend | Yes |
| `grep` | SandboxBackend | Yes |
| `web_search` | None | Yes |
| `web_fetch` | None | Yes |
| `memory_read` | MemoryBackend | Yes |
| `memory_write` | MemoryBackend | No |
| `agent` | AgentBackend | No |
| `send_message` | AgentBackend | No |
| `task_stop` | AgentBackend | No |
| `skill` | SkillRegistry | Yes |
| `ask_user_question` | None | Yes |

### Hands-On (2.5h)

#### Exercise 1: Register read_file + write_file against a local sandbox

```python
# ex1_file_ops.py
import os, asyncio
from pathlib import Path
from llm_harness.adapters.providers.openai_compat_provider import OpenAICompatProvider
from llm_harness.adapters.sandbox.srt import SRTSandboxBackend
from llm_harness.core.harness import Harness
from llm_harness.core.session.session import Session
from llm_harness.core.bus.events import InboundMessage
from llm_harness.core.tools.base import ToolRegistry
from llm_harness.core.tools.factory import ToolFactory

async def main():
    ws = Path("./ws_files")
    ws.mkdir(exist_ok=True)
    (ws / "hello.md").write_text("# Hello\n\nThis is a test file.", encoding="utf-8")

    provider = OpenAICompatProvider(api_key=os.environ["LLM_HARNESS_API_KEY"])
    sandbox = SRTSandboxBackend(ws)
    factory = ToolFactory(sandbox=sandbox)
    tools = ToolRegistry()
    for name in ["read_file", "write_file"]:
        t = factory.build(name)
        if t:
            tools.register(t)

    harness = Harness(provider=provider, model="deepseek-chat",
                      tools=tools, sandbox=sandbox,
                      system_prompt="Use tools to read and write files.")
    agent = harness.create_agent()
    session = Session(key="ex1:chat1")

    msg = InboundMessage("cli", "user", "c1", "Read hello.md, then create a file called summary.md with a 1-line summary.")
    result = await agent.process(msg, session=session, cwd=ws)
    print("Final:", result.final_content)
    print("Tools used:", result.tools_used)
    print("summary.md exists:", (ws / "summary.md").exists())

asyncio.run(main())
```

#### Exercise 2: Register glob + grep

```python
# ex2_glob_grep.py
# Same setup as Exercise 1, add "glob" and "grep" to the tool list.
# Prompt: "Find all .md files, then search for the word 'test' in them."
```

Add `"glob"` and `"grep"` to the list of tool names in the factory loop.

#### Exercise 3: Register exec

```python
# ex3_exec.py
# Same setup, add "exec" to tool list.
# Prompt: "Run 'git status' and tell me the current branch."
```

#### Exercise 4: Register web_search + web_fetch

```python
# ex4_web.py
import os, asyncio
from pathlib import Path
from llm_harness.adapters.providers.openai_compat_provider import OpenAICompatProvider
from llm_harness.adapters.sandbox.srt import SRTSandboxBackend
from llm_harness.core.harness import Harness
from llm_harness.core.session.session import Session
from llm_harness.core.bus.events import InboundMessage
from llm_harness.core.tools.base import ToolRegistry
from llm_harness.core.tools.factory import ToolFactory

async def main():
    ws = Path("./ws_web")
    ws.mkdir(exist_ok=True)
    provider = OpenAICompatProvider(api_key=os.environ["LLM_HARNESS_API_KEY"])
    sandbox = SRTSandboxBackend(ws)
    factory = ToolFactory(sandbox=sandbox)
    tools = ToolRegistry()
    for name in ["web_search", "web_fetch"]:
        t = factory.build(name)
        if t:
            tools.register(t)

    harness = Harness(provider=provider, model="deepseek-chat",
                      tools=tools, sandbox=sandbox,
                      system_prompt="Use web_search then web_fetch to research.")
    agent = harness.create_agent()
    session = Session(key="ex4:chat1")

    msg = InboundMessage("cli", "user", "c1",
        "Search for 'Python 3.13 release date' and fetch the official Python blog result.")
    result = await agent.process(msg, session=session, cwd=ws)
    print("Final:", result.final_content)

asyncio.run(main())
```

#### Exercise 5: Register ask_user_question

```python
# ex5_ask_user.py
# Same setup, add "ask_user_question" to tool list.
# Prompt: "I need to write a Python script. Ask me what it should do."
# Observe the LLM calling the ask_user_question tool to request clarification.
```

#### Exercise 6 (debug): Observe tool calls via on_tool_check callback

```python
# ex6_tool_logging.py
# Add a custom on_tool_check callback that prints every tool invocation:
#
# harness = Harness(
#     ...
#     permissions=PermissionChecker(PermissionSettings(
#         # no restrictions -- just observe
#     )),
# )
# Then monkey-patch or extend; the cleaner way is to use on_event:
# The AgentLoop accepts an on_event callback that fires "tool:executing".
```

The simplest approach is to use a custom `AgentLoop` with `on_event`:

```python
async def event_cb(event_type, payload):
    if event_type == "tool:executing":
        print(f"[TOOL] {payload['name']} args={payload.get('arguments', {})}")

loop = AgentLoop(
    ...
    on_event=event_cb,
)
```

#### Exercise 7 (error): Invalid tool args

```python
# ex7_tool_error.py
# Prompt the agent: "Read file that-does-not-exist.txt"
# Observe the Pydantic validation error or the tool's own error
# reported in the ToolResult.
```

### Deliverable (15min)

- `tool_lab.py` -- registers 8+ tools (read_file, write_file, glob, grep, exec, web_search, web_fetch, ask_user_question) and sends a comprehensive multi-step task that requires chaining at least 3 tools.
- Verify: `LLM_HARNESS_API_KEY=sk-xxx python tool_lab.py` -- 3+ tools invoked in a chain, final output visible.

### Post-Lesson Reflection

Why does the ToolFactory use lazy importlib loading instead of importing all tool modules eagerly at startup? What scenarios does this design help with?

---

## Day 3: Sessions & Memory (3.5h)

### Theory (1h)

**Session dataclass** -- pure structure, no I/O:

```python
@dataclass
class Session:
    key: str                                    # "channel:chat_id"
    messages: list[dict] = field(default_factory=list)
    created_at: datetime = field(...)
    updated_at: datetime = field(...)
    metadata: dict = field(default_factory=dict)
    last_consolidated: int = 0                  # offset into messages
```

Key methods:

- `add_message(role, content, **kwargs)` -- appends a message dict with an auto-generated ISO timestamp.
- `get_history(max_messages=500)` -- the core slicing logic:
  1. Start from `last_consolidated` (skip archived messages)
  2. Take the last `max_messages` entries from that window
  3. Forward-search to the first `"user"` role message (aligns cut point)
  4. Extract only `role`, `content`, `tool_calls`, `tool_call_id`, `name` keys
- `remove_before(idx)` -- removes messages before `idx` from the in-memory list and adjusts `last_consolidated`.

**MemoryConsolidator** orchestrates archival of old messages when the context window budget is approached:

1. `estimate_session_prompt_tokens(session)` -- builds a probe context (system + tools + history), estimates token counts via `len(content) // 4`.
2. `pick_consolidation_boundary(session, tokens_to_remove)` -- scans messages forward from `last_consolidated`, accumulating token counts, and returns the index of the last `"user"` message before the budget is met.
3. `maybe_consolidate(session)` -- acquires a per-session `asyncio.Lock` with 30s timeout, runs up to `MAX_CONSOLIDATION_ROUNDS=5` rounds. Each round asks the policy whether to consolidate, calls `backend.consolidate()`, then `session.remove_before()`.

**TokenBudgetPolicy** (the default policy):

```
budget = context_window_tokens - max_completion_tokens - safety_buffer(1024)
if estimated < budget: return None  # no consolidation needed
boundary = pick_consolidation_boundary(session, (estimated - budget) // 2)
```

**MessageCountPolicy** is an alternative: consolidate when active messages exceed `max_messages`.

**MemoryBackend Protocol** (5 methods):

```python
class MemoryBackend(Protocol):
    async def get_context(self, namespace: str) -> str: ...
    async def read_section(self, namespace: str, section: str) -> str: ...
    async def append_section(self, namespace: str, section: str, entry: str) -> None: ...
    async def add_history(self, namespace: str, entry: str) -> None: ...
    async def consolidate(self, namespace, messages, provider=None, model="") -> bool: ...
```

### Hands-On (2h)

#### Exercise 1: Observe message growth across turns

```python
# ex1_session_growth.py
import os, asyncio
from pathlib import Path
from llm_harness.adapters.providers.openai_compat_provider import OpenAICompatProvider
from llm_harness.adapters.sandbox.srt import SRTSandboxBackend
from llm_harness.core.harness import Harness
from llm_harness.core.session.session import Session
from llm_harness.core.bus.events import InboundMessage
from llm_harness.core.tools.base import ToolRegistry
from llm_harness.core.tools.factory import ToolFactory

async def main():
    ws = Path("./ws_session")
    ws.mkdir(exist_ok=True)
    provider = OpenAICompatProvider(api_key=os.environ["LLM_HARNESS_API_KEY"])
    sandbox = SRTSandboxBackend(ws)
    factory = ToolFactory(sandbox=sandbox)
    tools = ToolRegistry()
    for name in ["write_file", "read_file"]:
        t = factory.build(name)
        if t:
            tools.register(t)

    harness = Harness(provider=provider, model="deepseek-chat",
                      tools=tools, sandbox=sandbox)
    agent = harness.create_agent()
    session = Session(key="growth:chat1")

    prompts = [
        "Create a file called log.txt with content 'step 1'",
        "Append 'step 2' to log.txt",
        "Append 'step 3' to log.txt",
        "Append 'step 4' to log.txt",
        "Read log.txt and tell me all steps",
    ]
    for i, prompt in enumerate(prompts):
        msg = InboundMessage("cli", "user", "c1", prompt)
        result = await agent.process(msg, session=session, cwd=ws)
        print(f"Turn {i+1}: final_content={result.final_content[:60] if result.final_content else '(tool)'}  "
              f"messages={len(session.messages)}  "
              f"tools_used={result.tools_used}")

asyncio.run(main())
```

#### Exercise 2: Print get_history() and verify the forward-search behaviour

```python
# ex2_history.py
from llm_harness.core.session.session import Session

session = Session(key="test:demo")
session.add_message("system", "You are a bot")
session.add_message("user", "Hello")
session.add_message("assistant", "Hi there")
session.add_message("user", "How are you?")
session.add_message("assistant", "I'm great!")
session.add_message("tool", "some_result", tool_call_id="call_1", name="read_file")

print("Full history:")
for m in session.get_history(max_messages=500):
    print(f"  {m['role']}: {str(m.get('content', ''))[:60]}")

# Verify: the "system" message is NOT in get_history() output
# because get_history() starts from last_consolidated (0) but
# forward-searches to the first "user" role message.
print("\nNotice: system message is excluded by the forward-search to first 'user'.")
```

#### Exercise 3: Manual remove_before

```python
# ex3_remove_before.py
from llm_harness.core.session.session import Session

s = Session(key="test:demo")
s.add_message("user", "msg1")
s.add_message("assistant", "resp1")
s.add_message("user", "msg2")
s.add_message("assistant", "resp2")
s.add_message("user", "msg3")

print(f"Before remove: {len(s.messages)} messages, last_consolidated={s.last_consolidated}")

# Remove first 3 messages
s.remove_before(3)
print(f"After remove:  {len(s.messages)} messages, last_consolidated={s.last_consolidated}")

history = s.get_history()
print(f"History contains {len(history)} messages")
for m in history:
    print(f"  {m['role']}: {m.get('content', '')}")
```

#### Exercise 4: Memory consolidation with a mock backend

```python
# ex4_consolidation.py
import asyncio
from unittest.mock import AsyncMock
from llm_harness.core.session.session import Session
from llm_harness.adapters.memory.consolidator import MemoryConsolidator
from llm_harness.adapters.memory.policy import TokenBudgetPolicy

async def main():
    backend = AsyncMock()
    backend.consolidate = AsyncMock(return_value=True)

    consolidator = MemoryConsolidator(
        backend=backend,
        context_window_tokens=128_000,
        max_completion_tokens=4096,
        build_messages=lambda **kw: [
            {"role": "system", "content": "test system"},
            {"role": "user", "content": kw.get("current_message", "")},
        ],
        get_tool_definitions=lambda: [],
        policy=TokenBudgetPolicy(
            context_window_tokens=128_000,
            max_completion_tokens=4096,
        ),
    )

    session = Session(key="consolidation:test")
    # Add many messages to trigger consolidation
    for i in range(20):
        session.add_message("user", "hello " * 100)   # ~250 tokens each
        session.add_message("assistant", "world " * 100)

    print(f"Messages before: {len(session.messages)}")
    print(f"last_consolidated before: {session.last_consolidated}")

    await consolidator.maybe_consolidate(session)

    print(f"Messages after:  {len(session.messages)}")
    print(f"last_consolidated after: {session.last_consolidated}")
    print(f"Backend.consolidate called: {backend.consolidate.called}")

asyncio.run(main())
```

#### Exercise 5: Estimate message tokens

```python
# ex5_token_estimate.py
from llm_harness.adapters.memory.consolidator import estimate_message_tokens

messages = [
    {"role": "user", "content": "Hello, how are you?"},            # ~5 tokens
    {"role": "assistant", "content": "I'm doing well, thank you!"}, # ~7 tokens
    {"role": "user", "content": "What is the meaning of life?" * 10},  # ~90 tokens
]

for m in messages:
    tokens = estimate_message_tokens(m)
    print(f"[{m['role']}] ~{tokens} tokens  content_len={len(m['content'])}")
```

### Deliverable (15min)

- `session_lab.py` -- a 10-turn simulation that prints: turn number, session.messages count, token estimate, and whether consolidation was triggered per turn.
- Verify: `python session_lab.py` -- shows token count growing and consolidation trigger point (by round 8 or earlier depending on message length).

### Post-Lesson Reflection

The `get_history()` forward-search to the first `"user"` message means system messages are excluded from history. What is the rationale for this design? When would it cause a problem?

---

## Day 4: Providers & Configuration (3.5h)

### Theory (1h)

**LLMProvider ABC.** The abstract base defines:

- `chat()` -- abstract method each provider must implement
- `chat_with_retry()` -- template method wrapping `chat()` with exponential backoff (1s, 2s, 4s), transient error detection, and an image-fallback mechanism

The `_TRANSIENT_ERROR_MARKERS` tuple contains 14 keyword patterns that identify retryable errors:

```python
_TRANSIENT_ERROR_MARKERS = (
    "429", "rate limit", "rate_limit", "too many requests",
    "503", "502", "500", "504", "service unavailable",
    "overloaded", "internal server error", "bad gateway",
    "timeout", "temporarily",
)
```

If a non-transient error occurs and the request contained `image_url` content blocks, the provider strips images and retries once (the image-fallback path).

The `_SENTINEL` sentinel-value pattern is used throughout to distinguish "not provided" from `None`:

```python
_SENTINEL = object()
```

**Message sanitization pipeline** runs on every request:

1. `_sanitize_empty_content()` -- replaces empty strings with `"(empty)"` (or `None` for assistant messages with tool_calls), removes empty content blocks, converts dict-type content to list.
2. `_sanitize_request_messages(messages, allowed_keys)` -- filters each message dict to only include keys the provider supports (e.g., Anthropic uses different keys than OpenAI).
3. `_apply_cache_control()` -- adds Anthropic `cache_control` markers on the system message, the last non-final user message, and the last tool result.

**AnthropicProvider vs OpenAICompatProvider:**

| Aspect | AnthropicProvider | OpenAICompatProvider |
|---|---|---|
| SDK | `anthropic` | `openai` |
| Message format | Converts OpenAI chat format to Anthropic Messages API | Native OpenAI format |
| System message | Extracted from messages list, sent as `system` param | Kept as `role: "system"` in messages |
| Tool format | `{"name": ..., "input_schema": ...}` | `{"type": "function", "function": {...}}` |
| Prompt caching | Supported via `cache_control` markers | Not supported |
| Thinking mode | Supported with budget map | Not supported |
| API format string | `"anthropic"` | `"openai"` |

**ProviderSpec registry** contains 29 provider definitions. The `detect_provider()` function uses a 3-step matching process:

1. Match by API key prefix (e.g., `sk-or-` for OpenRouter)
2. Match by base URL keyword (e.g., `openrouter` in the URL)
3. Match by model name keyword (e.g., `gpt` in the model name)

```python
def detect_provider(model, api_key=None, api_base=None) -> ProviderSpec | None:
    # 1. API key prefix
    # 2. Base URL keyword
    # 3. Model name keyword
```

**Config loading chain** (CLI args > env vars > YAML > defaults):

```
CLI args (--model, --provider)
  > LLM_HARNESS_MODEL, LLM_HARNESS_API_KEY env vars
    > harness.yaml (YAML file)
      > Pydantic defaults in Config()
```

The `Config` Pydantic model has sections: `agent`, `tools`, `permission`, `sandbox`, `memory`, `observability`, `channels`, `workspace`.

```yaml
# harness.yaml
agent:
  model: deepseek-chat
  provider: auto
  api_key: ""           # prefer env var LLM_HARNESS_API_KEY
  api_base: https://api.deepseek.com
  max_tokens: 4096
  context_window_tokens: 64000
tools:
  enabled:
    - read_file
    - write_file
    - web_search
    - web_fetch
permission:
  mode: full_auto      # default | plan | full_auto
sandbox:
  backend: srt
workspace: .
```

### Hands-On (2h)

#### Exercise 1: Create harness.yaml with full configuration

Create `harness.yaml`:

```yaml
agent:
  model: deepseek-chat
  provider: auto
  api_base: https://api.deepseek.com
  max_tokens: 4096
  context_window_tokens: 64000
tools:
  enabled:
    - read_file
    - write_file
    - exec
    - glob
    - grep
    - web_search
    - web_fetch
permission:
  mode: full_auto
sandbox:
  backend: srt
workspace: .
```

#### Exercise 2: Load config with CLI override

```python
# ex2_load_config.py
from llm_harness.config.loader import load_config

cfg = load_config(model="claude-sonnet-4-6")
print(f"Model: {cfg.agent.model}")
print(f"Provider: {cfg.agent.provider}")
print(f"Workspace: {cfg.workspace}")
print(f"Tools enabled: {cfg.tools.enabled}")
print(f"Permission mode: {cfg.permission.mode}")
```

Run:

```bash
python ex2_load_config.py
# --> Model: claude-sonnet-4-6
# --> Provider: auto
```

#### Exercise 3: Compare Anthropic and OpenAI providers

```python
# ex3_compare_providers.py
import os, asyncio
from llm_harness.adapters.providers.openai_compat_provider import OpenAICompatProvider
from llm_harness.adapters.providers.anthropic_provider import AnthropicProvider

async def main():
    messages = [
        {"role": "user", "content": "What is 2+2? Answer in one word."}
    ]

    # OpenAI-compatible (DeepSeek)
    oai = OpenAICompatProvider(
        api_key=os.environ["LLM_HARNESS_API_KEY"],
        api_base="https://api.deepseek.com",
    )
    resp = await oai.chat_with_retry(messages, model="deepseek-chat")
    print(f"OpenAICompat: {resp.content}  finish={resp.finish_reason}")

    # Anthropic (Claude)
    anth = AnthropicProvider(
        api_key=os.environ["ANTHROPIC_API_KEY"],
    )
    resp2 = await anth.chat_with_retry(messages, model="claude-sonnet-4-20250514")
    print(f"Anthropic:    {resp2.content}  finish={resp2.finish_reason}")

asyncio.run(main())
```

#### Exercise 4: Mock transient errors and observe retry

```python
# ex4_retry.py
import os, asyncio
from unittest.mock import AsyncMock, patch
from llm_harness.adapters.providers.openai_compat_provider import OpenAICompatProvider

async def main():
    provider = OpenAICompatProvider(
        api_key=os.environ["LLM_HARNESS_API_KEY"],
        api_base="https://api.deepseek.com",
    )

    # Patch _safe_chat to fail twice with a transient error, then succeed
    original = provider._safe_chat
    call_count = 0

    async def flaky_chat(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count <= 2:
            from llm_harness.adapters.providers.base import LLMResponse
            return LLMResponse(
                content="", finish_reason="error",
                error="429 Too Many Requests",
            )
        return await original(*args, **kwargs)

    with patch.object(provider, "_safe_chat", flaky_chat):
        resp = await provider.chat_with_retry(
            [{"role": "user", "content": "Hello"}],
            model="deepseek-chat",
        )
        print(f"Attempts needed: {call_count}")
        print(f"Final response: {resp.content}")

asyncio.run(main())
```

#### Exercise 5: Test detect_provider

```python
# ex5_detect.py
from llm_harness.adapters.providers.registry import detect_provider

tests = [
    ("gpt-4", "sk-...", ""),                          # OpenAI
    ("claude-sonnet-4-6", "", ""),                    # Anthropic
    ("deepseek-chat", "", ""),                        # DeepSeek
    ("gemini-pro", "", ""),                           # Google
    ("qwen-max", "", ""),                             # Qwen (DashScope)
    ("", "sk-or-v1-abc", ""),                         # OpenRouter (key prefix)
    ("", "", "https://openrouter.ai/api/v1"),         # OpenRouter (base URL)
]

for model, key, base in tests:
    spec = detect_provider(model, key if key else None, base if base else None)
    name = spec.name if spec else "None"
    print(f"model={model:<25} key={key:<15} base={base:<35} -> {name}")
```

#### Exercise 6: Create a custom ProviderSpec

```python
# ex6_custom_provider.py
from llm_harness.adapters.providers.registry import ProviderSpec, PROVIDERS

# Create a custom spec for a private LLM gateway
custom = ProviderSpec(
    name="my-gateway",
    keywords=("my-gpt", "my-model"),
    env_key="MY_GATEWAY_API_KEY",
    display_name="My Private Gateway",
    backend="openai_compat",
    is_gateway=True,
    default_api_base="https://my-gateway.internal.company.com/v1",
)

# Check it's not already in PROVIDERS
existing_names = [s.name for s in PROVIDERS]
if custom.name not in existing_names:
    print(f"Custom spec '{custom.name}' ready for registration")
    print(f"  keywords: {custom.keywords}")
    print(f"  env_key: {custom.env_key}")
    print(f"  api_base: {custom.default_api_base}")
else:
    print(f"Spec '{custom.name}' already exists")
```

### Deliverable (15min)

- `config_lab.py` -- uses `load_config()` with `harness.yaml`, constructs all components from the config values, creates an Agent, sends a message.
- `provider_test.py` -- runs the same message through 3 different provider configurations and prints comparison of responses.
- Verify: `LLM_HARNESS_API_KEY=sk-xxx python config_lab.py` -- Agent loaded from YAML config and returns a coherent reply.

### Post-Lesson Reflection

The config loading chain gives CLI args highest priority. In a multi-tenant SaaS deployment, what additional precedence levels would you add (e.g., per-account, per-session, per-request)?

---

## Day 5: Extension System (3.5h)

### Theory (1h)

The extension system has four distinct extension points:

**1. MCP (Model Context Protocol).** External tool servers that expose tools over stdio, SSE, or streamable HTTP transports.

- `MCPServerConnection` -- quick single-server connection. Usage: `async with MCPServerConnection(command=[...]) as srv: registry.register(tool)`.
- Dynamic Pydantic model creation from JSON Schema (tools define their input schema via the MCP protocol).
- Tool filtering with `enabled_tools` list and `*` wildcard support.

**2. Skills.** Progressive-disclosure knowledge system:

- `SkillDefinition` dataclass: `name`, `description`, `content`, `source`, `path`.
- The system prompt lists skill names and descriptions only (keeps context small).
- When the LLM calls the `skill` tool, the full skill content is loaded into context.
- `DirectorySkillLoader._scan()` walks directories looking for `<name>/SKILL.md` files with YAML frontmatter:

```markdown
---
name: my-skill
description: What my skill does
---
Full skill content here...
```

**3. Hooks.** Lifecycle hooks with 4 types and `fnmatch` pattern matching:

- `CommandHookDefinition` -- runs a shell command
- `HttpHookDefinition` -- sends an HTTP request
- `PromptHookDefinition` -- sends a prompt to the LLM
- `AgentHookDefinition` -- spawns a sub-agent

`HookEvent` enum covers the lifecycle: `PreToolUse`, `PostToolUse`, `PreMessage`, `PostMessage`, `PreProcess`, `PostProcess`, `PreSessionCreate`, `PostSessionCreate`, `PreAgentSpawn`, `PostAgentSpawn`, `PreShutdown`.

`HookExecutor.execute(event, payload)` matches hooks by event type + fnmatch pattern on the payload, runs them, and supports `block_on_failure` to abort the pipeline.

**4. Channels.** Inbound/outbound communication adapters:

- `BaseChannel` ABC: `start()`, `stop()`, `send()`, `send_delta()`, `is_allowed()`.
- `WebSocketChannel` -- JSON-over-WebSocket with optional `auth_callback`, streaming deltas, ping/pong.
- `CLIChannel` -- stdin/stdout for terminal usage.
- `ChannelManager` orchestrates lifecycle (`start_all()` / `stop_all()`), outbound dispatch with retry (`send_max_retries=3`), and `allow_from` validation.

### Hands-On (2h)

#### Exercise 1: Connect an MCP server

```python
# ex1_mcp.py
import os, asyncio
from pathlib import Path
from llm_harness.adapters.providers.openai_compat_provider import OpenAICompatProvider
from llm_harness.adapters.sandbox.srt import SRTSandboxBackend
from llm_harness.core.harness import Harness
from llm_harness.core.session.session import Session
from llm_harness.core.bus.events import InboundMessage
from llm_harness.core.tools.base import ToolRegistry
from llm_harness.core.tools.factory import ToolFactory
from llm_harness.extensions.mcp.client import MCPServerConnection

async def main():
    ws = Path("./ws_mcp")
    ws.mkdir(exist_ok=True)

    provider = OpenAICompatProvider(api_key=os.environ["LLM_HARNESS_API_KEY"])
    sandbox = SRTSandboxBackend(ws)

    # Build local sandbox tools
    factory = ToolFactory(sandbox=sandbox)
    tools = ToolRegistry()
    for name in ["read_file", "write_file", "exec"]:
        t = factory.build(name)
        if t:
            tools.register(t)

    # Connect MCP server (example: a filesystem MCP server)
    async with MCPServerConnection(command=["npx", "-y", "@modelcontextprotocol/server-filesystem", str(ws)]) as mcp:
        for mcp_tool in mcp.tools:
            print(f"MCP tool: {mcp_tool.name} -- {mcp_tool.description[:60]}")
            tools.register(mcp_tool)

        harness = Harness(provider=provider, model="deepseek-chat",
                          tools=tools, sandbox=sandbox)
        agent = harness.create_agent()
        session = Session(key="mcp:chat1")

        msg = InboundMessage("cli", "user", "c1", "List files in the workspace and create a new file called mcp_demo.txt")
        result = await agent.process(msg, session=session, cwd=ws)
        print("Final:", result.final_content)

asyncio.run(main())
```

#### Exercise 2: Create a skill and load it

Create `skills/hello-skill/SKILL.md`:

```markdown
---
name: hello-skill
description: A demo skill that explains the llm-harness greeting protocol
---

# Hello Skill

When a user greets the assistant, respond with a friendly welcome message
that includes the current UTC time. Always ask if they would like a tour
of available skills and tools.
```

Then load and use it:

```python
# ex2_skills.py
import os, asyncio
from pathlib import Path
from llm_harness.adapters.providers.openai_compat_provider import OpenAICompatProvider
from llm_harness.adapters.sandbox.srt import SRTSandboxBackend
from llm_harness.core.harness import Harness
from llm_harness.core.session.session import Session
from llm_harness.core.bus.events import InboundMessage
from llm_harness.core.tools.base import ToolRegistry
from llm_harness.core.tools.factory import ToolFactory
from llm_harness.extensions.skills.loader import load_skills_from_dirs
from llm_harness.extensions.skills.registry import SkillRegistry

async def main():
    ws = Path("./ws_skills")
    ws.mkdir(exist_ok=True)

    provider = OpenAICompatProvider(api_key=os.environ["LLM_HARNESS_API_KEY"])
    sandbox = SRTSandboxBackend(ws)
    factory = ToolFactory(sandbox=sandbox)
    tools = ToolRegistry()
    for name in ["write_file", "read_file"]:
        t = factory.build(name)
        if t:
            tools.register(t)

    # Load skills from directory
    skill_defs = load_skills_from_dirs(["./skills"])
    skill_registry = SkillRegistry()
    for sd in skill_defs:
        skill_registry.register(sd)
        print(f"Loaded skill: {sd.name} -- {sd.description}")

    harness = Harness(provider=provider, model="deepseek-chat",
                      tools=tools, sandbox=sandbox,
                      skills=skill_registry)
    agent = harness.create_agent()
    session = Session(key="skills:chat1")

    msg = InboundMessage("cli", "user", "c1", "Hello! What skills do you have?")
    result = await agent.process(msg, session=session, cwd=ws)
    print("Final:", result.final_content)

asyncio.run(main())
```

#### Exercise 3: Configure and run hooks

```python
# ex3_hooks.py
import asyncio
from pathlib import Path
from llm_harness.extensions.hooks.events import HookEvent
from llm_harness.extensions.hooks.schemas import CommandHookDefinition, HttpHookDefinition
from llm_harness.extensions.hooks.executor import HookExecutor, HookExecutionContext
from llm_harness.extensions.hooks.loader import HookRegistry

async def main():
    registry = HookRegistry()
    registry.register(
        HookEvent.PRE_TOOL_USE,
        CommandHookDefinition(
            command="echo 'PreToolUse: {tool_name}' >> hooks_log.txt",
            block_on_failure=False,
            timeout_seconds=10,
        ),
    )
    registry.register(
        HookEvent.POST_TOOL_USE,
        HttpHookDefinition(
            url="https://httpbin.org/post",
            method="POST",
            headers={"Content-Type": "application/json"},
            body='{"tool": "{tool_name}", "status": "{success}"}',
            block_on_failure=False,
            timeout_seconds=10,
        ),
    )

    context = HookExecutionContext(cwd=Path("."))
    executor = HookExecutor(registry, context)

    result = await executor.execute(
        HookEvent.PRE_TOOL_USE,
        {"tool_name": "read_file", "file_path": "test.txt"},
    )
    print(f"PreToolUse hooks: {len(result.results)} executed, blocked={result.blocked}")

    result2 = await executor.execute(
        HookEvent.POST_TOOL_USE,
        {"tool_name": "read_file", "success": "true"},
    )
    print(f"PostToolUse hooks: {len(result2.results)} executed, blocked={result2.blocked}")

    log = Path("hooks_log.txt")
    if log.exists():
        print(f"Hook log:\n{log.read_text()}")

asyncio.run(main())
```

#### Exercise 4: WebSocket channel

```python
# ex4_websocket.py
# Terminal 1: Start the agent
import os, asyncio
from pathlib import Path
from llm_harness.adapters.providers.openai_compat_provider import OpenAICompatProvider
from llm_harness.adapters.sandbox.srt import SRTSandboxBackend
from llm_harness.core.harness import Harness
from llm_harness.core.session.session import Session
from llm_harness.core.bus.events import InboundMessage, OutboundMessage
from llm_harness.core.bus.queue import MessageBus
from llm_harness.core.tools.base import ToolRegistry
from llm_harness.core.tools.factory import ToolFactory
from llm_harness.extensions.channels.websocket import WebSocketChannel

async def main():
    ws = Path("./ws_wss")
    ws.mkdir(exist_ok=True)

    bus = MessageBus(maxsize=10_000)
    provider = OpenAICompatProvider(api_key=os.environ["LLM_HARNESS_API_KEY"])
    sandbox = SRTSandboxBackend(ws)
    factory = ToolFactory(sandbox=sandbox)
    tools = ToolRegistry()
    for name in ["read_file", "write_file"]:
        t = factory.build(name)
        if t:
            tools.register(t)

    harness = Harness(provider=provider, model="deepseek-chat",
                      tools=tools, sandbox=sandbox)
    agent = harness.create_agent()

    # Configure WebSocket channel
    config = {
        "enabled": True,
        "host": "127.0.0.1",
        "port": 8082,
        "allow_from": ["*"],
        "streaming": True,
    }
    ws_channel = WebSocketChannel(config, bus)

    # Start the channel in background
    import asyncio
    channel_task = asyncio.create_task(ws_channel.start())

    # Process inbound messages from bus
    async for msg in bus.inbound_messages():
        print(f"Received: {msg.content[:50]}...")
        session = Session(key=f"websocket:{msg.chat_id}")
        result = await agent.process(msg, session=session, cwd=ws)
        outbound = OutboundMessage(channel="websocket", chat_id=msg.chat_id,
                                    content=result.final_content or "")
        await bus.publish_outbound(outbound)

    ws_channel.stop()

asyncio.run(main())
```

Then in another terminal: `websocat ws://127.0.0.1:8082` and send `{"type":"message","content":"Hello!"}`.

#### Exercise 5: Dual channels (CLI + WebSocket)

The `ChannelManager` handles multiple channels. Wire both `CLIChannel` and `WebSocketChannel` to demonstrate dual-channel message routing.

```python
# ex5_dual_channels.py
# Uses ChannelManager with channel_types={"cli": CLIChannel, "websocket": WebSocketChannel}
# and channels_config containing both.
```

### Deliverable (15min)

- `extended_agent.py` -- Agent with MCP + Skills + Hooks + WebSocket all active simultaneously. Logs show each extension initialising.
- `skills/hello-skill/SKILL.md` -- a skill definition with YAML frontmatter.
- Verify: `python extended_agent.py` -- startup logs show all extensions active.

### Post-Lesson Reflection

Skills use progressive disclosure (names only in system prompt, content loaded on demand). What are the trade-offs of this approach compared to including all skill content in every system prompt?

---

## Day 6: Observability, Permissions & Sub-agents (3h)

### Theory (1h)

**Event system.** 11 event types across two categories:

Loop events (emitted inside `AgentLoop.run`):
- `AssistantTextDelta` -- streaming text chunk
- `AssistantTurnComplete` -- finished response with usage stats
- `ToolExecutionStarted` -- before a tool executes
- `ToolExecutionCompleted` -- after a tool completes (with output and duration)
- `ErrorEvent` -- error (recoverable by default)
- `StatusEvent` -- status message

System events (emitted by infrastructure):
- `SessionOpened` / `SessionClosed` -- session lifecycle
- `SubagentSpawned` / `SubagentCompleted` -- sub-agent lifecycle
- `MemoryConsolidated` -- messages archived

`EventEmitter` wraps an `ObservabilityBackend` with typed `send()` methods.

`DefaultObservabilityBackend` is an in-memory pub-sub with an `on_emit` callback:

```python
backend = DefaultObservabilityBackend(
    on_emit=lambda event_type, payload: print(f"{event_type}: {payload}")
)
```

**Permission system.** Three modes defined in `PermissionMode`:

- `DEFAULT` -- read-only tools allowed, mutating tools require user confirmation
- `PLAN` -- all mutating tools blocked
- `FULL_AUTO` -- all tools allowed

`PermissionChecker.evaluate()` implements a 9-step check order:

1. Sensitive path denylist (SSH/AWS/GCP/Azure/GPG/Docker/K8s keys) -- always active, cannot be overridden
2. Check `denied_tools` -- explicit deny list
3. Check `allowed_tools` -- explicit allow list
4. Check `path_rules` -- fnmatch-based path permissions
5. Check `denied_commands` -- command pattern denylist
6. `FULL_AUTO` mode -- allow everything
7. Read-only check -- allow read-only tools
8. `PLAN` mode -- block mutating tools
9. `DEFAULT` mode -- require confirmation for mutating tools

**Swarm subsystem.** `AgentDefinition` specifies a named agent profile:

```python
@dataclass
class AgentDefinition:
    name: str
    description: str
    system_prompt: str
    tools_allow: list[str] | None = None
    tools_deny: list[str] | None = None
    tools_extra: list[str] | None = None
    model: str = ""
```

There are 5 built-in definitions: `general-purpose`, `researcher`, `planner`, `executor`, `reviewer`.

`AgentBackend` Protocol has 3 methods: `spawn(config)`, `send_message(agent_id, message)`, `stop(agent_id)`.

`SubprocessBackend` -- spawns each sub-agent as an independent OS process. Uses `Mailbox` (file-based, atomic writes with `os.replace`, cursor-based polling) for cross-process messages. The sub-agent lifecycle:

```
AgentTool.execute() 
  -> SubprocessBackend.spawn(config) 
    -> create_subprocess_exec(python -m llm_harness --worker ...)
    -> send prompt via stdin
    -> _watch() awaits process completion
    -> SubagentSpawned event
    -> process runs
    -> stdout captured
    -> SubagentCompleted event
    -> InboundMessage(task-notification) published to MessageBus
```

Tool set for each sub-agent: `(harness_tools ∩ allow) - deny + extra`.

### Hands-On (1.5h)

#### Exercise 1: Record all events to JSONL

```python
# ex1_events_jsonl.py
import os, json, asyncio
from pathlib import Path
from llm_harness.adapters.providers.openai_compat_provider import OpenAICompatProvider
from llm_harness.adapters.sandbox.srt import SRTSandboxBackend
from llm_harness.adapters.observability.default import DefaultObservabilityBackend
from llm_harness.core.harness import Harness
from llm_harness.core.session.session import Session
from llm_harness.core.bus.events import InboundMessage
from llm_harness.core.tools.base import ToolRegistry
from llm_harness.core.tools.factory import ToolFactory

async def main():
    ws = Path("./ws_events")
    ws.mkdir(exist_ok=True)
    events_file = Path("./events.jsonl")

    # Observability backend with on_emit that writes to JSONL
    async def write_event(event_type: str, payload: dict):
        line = json.dumps({"type": event_type, **payload}, ensure_ascii=False)
        events_file.open("a", encoding="utf-8").write(line + "\n")
        print(f"[EVENT] {event_type}")

    obs = DefaultObservabilityBackend(on_emit=write_event)

    provider = OpenAICompatProvider(api_key=os.environ["LLM_HARNESS_API_KEY"])
    sandbox = SRTSandboxBackend(ws)
    factory = ToolFactory(sandbox=sandbox)
    tools = ToolRegistry()
    for name in ["write_file", "read_file", "web_search"]:
        t = factory.build(name)
        if t:
            tools.register(t)

    harness = Harness(provider=provider, model="deepseek-chat",
                      tools=tools, sandbox=sandbox,
                      observability=obs)
    agent = harness.create_agent()
    session = Session(key="events:chat1")

    msg = InboundMessage("cli", "user", "c1", "Search for 'Python asyncio' and write a summary to summary.txt")
    result = await agent.process(msg, session=session, cwd=ws)
    print(f"Final: {result.final_content}")

    # Parse and count events
    events = [json.loads(l) for l in events_file.read_text().strip().split("\n") if l]
    print(f"\nTotal events recorded: {len(events)}")
    from collections import Counter
    types = Counter(e["type"] for e in events)
    for t, count in types.most_common():
        print(f"  {t}: {count}")

asyncio.run(main())
```

#### Exercise 2: Permission denied for exec

```python
# ex2_permission_deny.py
import os, asyncio
from pathlib import Path
from llm_harness.adapters.providers.openai_compat_provider import OpenAICompatProvider
from llm_harness.adapters.sandbox.srt import SRTSandboxBackend
from llm_harness.core.harness import Harness
from llm_harness.core.session.session import Session
from llm_harness.core.bus.events import InboundMessage
from llm_harness.core.tools.base import ToolRegistry
from llm_harness.core.tools.factory import ToolFactory
from llm_harness.core.permissions.checker import PermissionChecker
from llm_harness.core.permissions.settings import PermissionSettings
from llm_harness.core.permissions.modes import PermissionMode

async def main():
    ws = Path("./ws_perm")
    ws.mkdir(exist_ok=True)

    provider = OpenAICompatProvider(api_key=os.environ["LLM_HARNESS_API_KEY"])
    sandbox = SRTSandboxBackend(ws)
    factory = ToolFactory(sandbox=sandbox)
    tools = ToolRegistry()
    for name in ["exec", "read_file", "write_file"]:
        t = factory.build(name)
        if t:
            tools.register(t)

    # Deny exec tool explicitly
    settings = PermissionSettings(
        mode=PermissionMode.FULL_AUTO,
        denied_tools=["exec"],
    )
    checker = PermissionChecker(settings)

    harness = Harness(provider=provider, model="deepseek-chat",
                      tools=tools, sandbox=sandbox,
                      permissions=checker)
    agent = harness.create_agent()
    session = Session(key="perm:chat1")

    # The agent will try to use exec, but it will be rejected
    msg = InboundMessage("cli", "user", "c1", "Run 'echo hello' on the command line")
    result = await agent.process(msg, session=session, cwd=ws)
    print("Final:", result.final_content)
    print("Tools used:", result.tools_used)

asyncio.run(main())
```

#### Exercise 3: Path-based permission deny

```python
# ex3_path_deny.py
# Same setup as Exercise 2, but add path_rules to deny *.env:
# settings = PermissionSettings(
#     mode=PermissionMode.FULL_AUTO,
#     path_rules=[{"pattern": "*.env", "allow": False}],
# )
# Prompt: "Read the .env file and tell me its contents"
# Expect: Permission denied with reason about path rule match.
```

#### Exercise 4: Spawn a researcher sub-agent

```python
# ex4_swarm.py
import os, asyncio
from pathlib import Path
from llm_harness.adapters.providers.openai_compat_provider import OpenAICompatProvider
from llm_harness.adapters.sandbox.srt import SRTSandboxBackend
from llm_harness.core.harness import Harness
from llm_harness.core.session.session import Session
from llm_harness.core.bus.events import InboundMessage
from llm_harness.core.tools.base import ToolRegistry
from llm_harness.core.tools.factory import ToolFactory
from llm_harness.core.bus.queue import MessageBus
from llm_harness.core.swarm.subprocess import SubprocessBackend

async def main():
    ws = Path("./ws_swarm")
    ws.mkdir(exist_ok=True)

    bus = MessageBus(maxsize=10_000)
    swarm_backend = SubprocessBackend(bus=bus, workspace_root=ws)

    provider = OpenAICompatProvider(api_key=os.environ["LLM_HARNESS_API_KEY"])
    sandbox = SRTSandboxBackend(ws)
    factory = ToolFactory(sandbox=sandbox, swarm=swarm_backend, bus=bus,
                          harness_tool_names=["read_file", "write_file", "web_search"])
    tools = ToolRegistry()
    for name in ["read_file", "write_file", "web_search", "agent"]:
        t = factory.build(name)
        if t:
            tools.register(t)

    harness = Harness(provider=provider, model="deepseek-chat",
                      tools=tools, sandbox=sandbox,
                      swarm=swarm_backend)
    agent = harness.create_agent()
    session = Session(key="swarm:chat1")

    msg = InboundMessage("cli", "user", "c1",
        "Use the researcher sub-agent to search for 'Python 3.13 new features' and summarize them.")
    result = await agent.process(msg, session=session, cwd=ws)
    print("Final:", result.final_content)

    # Cleanup
    await swarm_backend.stop()

asyncio.run(main())
```

#### Exercise 5: Observe sub-agent lifecycle events

```python
# ex5_subagent_lifecycle.py
# Add DefaultObservabilityBackend with on_emit that prints:
#   agent:spawned, agent:completed
# Observe the sequence:
#   session:opened -> agent:spawned -> agent:completed -> task-notification -> session:closed
```

### Deliverable (15min)

- `observability_lab.py` -- JSONL event recording with event type counter.
- `permission_lab.py` -- demonstrates all three permission modes plus path-based deny.
- `swarm_lab.py` -- main agent spawns a researcher sub-agent and returns the result.
- Verify: `python swarm_lab.py` -- sub-agent spawned, output returned to main agent.

### Post-Lesson Reflection

The permission system has a hardcoded sensitive-path denylist that cannot be overridden. Is this a design flaw or a necessary safety measure? How would you add per-tenant overrides while keeping the built-in protection?

---

## Day 7: Custom Adapters & Production Deployment (3.5h)

### Theory (1h)

**Four core Protocol signatures.** The framework uses structural subtyping (PEP 544) -- no inheritance needed, the type checker validates at usage site:

```python
# SandboxBackend Protocol (8 methods)
@runtime_checkable
class SandboxBackend(Protocol):
    async def create_session(self, session_key: str) -> SandboxSession: ...
    async def destroy_session(self, session_key: str) -> None: ...
    async def read_file(self, session_key: str, path: str) -> str: ...
    async def write_file(self, session_key: str, path: str, content: str) -> None: ...
    async def list_dir(self, session_key: str, path: str) -> list[str]: ...
    async def glob(self, session_key: str, pattern: str) -> list[str]: ...
    async def grep(self, session_key: str, pattern: str, path: str) -> list[str]: ...
    async def execute(self, session_key, command, *, cwd="/workspace", env=None, timeout=60) -> ExecResult: ...

# MemoryBackend Protocol (5 methods)
@runtime_checkable
class MemoryBackend(Protocol):
    async def get_context(self, namespace: str) -> str: ...
    async def read_section(self, namespace: str, section: str) -> str: ...
    async def append_section(self, namespace: str, section: str, entry: str) -> None: ...
    async def add_history(self, namespace: str, entry: str) -> None: ...
    async def consolidate(self, namespace, messages, provider=None, model="") -> bool: ...

# AgentBackend Protocol (3 methods)
class AgentBackend(Protocol):
    async def spawn(self, config: SpawnConfig, **kw) -> SpawnResult: ...
    async def send_message(self, agent_id: str, message: str) -> bool: ...
    async def stop(self, agent_id: str) -> bool: ...

# SessionBackend Protocol (3 methods)
class SessionBackend(Protocol):
    async def load(self, session_key: str) -> dict | None: ...
    async def save(self, session_key: str, state: dict) -> None: ...
    async def list_keys(self) -> list[str]: ...
```

**Protocol design philosophy:**
- Structural subtyping: any object with matching method signatures satisfies the Protocol -- no need to import or inherit from framework code.
- Zero coupling: backend implementations don't need an `import llm_harness`.
- Minimal interface: only the methods the framework actually calls.

**Production checklist:**

| Concern | Configuration |
|---|---|
| Message bus capacity | `MessageBus(maxsize=10_000)` |
| Consolidation lock timeout | `asyncio.wait_for(lock.acquire(), timeout=30)` |
| Max consolidation rounds | `MAX_CONSOLIDATION_ROUNDS=5` |
| Max ReAct iterations | `AgentLoop(max_iterations=40)` |
| Tool result truncation | `TOOL_RESULT_MAX_CHARS=16_000` |
| Logging | `logging.getLogger(__name__)` (each module) |
| Graceful shutdown | `Agent.close()` / `ChannelManager.stop_all()` / `SubprocessBackend.stop()` |
| Sandbox isolation | `SRTSandboxBackend` with per-account workspace |
| Permission routing | `PermissionChecker` per session routing |

**Performance characteristics:**
- Pure async: no synchronous blocking anywhere in the hot path
- Lazy imports: `ToolFactory` uses lambda + `importlib.import_module`
- Prompt caching: supported for both Anthropic and OpenAI-compatible providers
- HTTP client reuse: `httpx.AsyncClient` is shared across requests

### Hands-On (2h)

#### Exercise 1: Implement RedisMemoryBackend

```python
# redis_memory.py
"""Redis-backed MemoryBackend implementation.

Satisfies the MemoryBackend Protocol with zero imports from llm-harness.
Uses fakeredis for testing, redis-py for production.
"""
from __future__ import annotations

import json
from typing import Any


class RedisMemoryBackend:
    """Memory backend storing context and history in Redis.

    Namespace -> Redis key prefix.
    Context stored as a plain string key.
    Sections stored as hash fields.
    History stored as a sorted set (timestamp-based ordering).
    """

    def __init__(self, redis_client: Any, key_prefix: str = "memory"):
        self._redis = redis_client
        self._prefix = key_prefix

    def _key(self, namespace: str) -> str:
        return f"{self._prefix}:{namespace}"

    def _section_key(self, namespace: str, section: str) -> str:
        return f"{self._prefix}:{namespace}:section:{section}"

    def _history_key(self, namespace: str) -> str:
        return f"{self._prefix}:{namespace}:history"

    async def get_context(self, namespace: str) -> str:
        val = await self._redis.get(self._key(namespace))
        return val or ""

    async def read_section(self, namespace: str, section: str) -> str:
        val = await self._redis.hget(self._section_key(namespace, section), "content")
        return val or ""

    async def append_section(self, namespace: str, section: str, entry: str) -> None:
        key = self._section_key(namespace, section)
        existing = await self._redis.hget(key, "content") or ""
        await self._redis.hset(key, "content", existing + "\n" + entry)

    async def add_history(self, namespace: str, entry: str) -> None:
        import time
        key = self._history_key(namespace)
        await self._redis.zadd(key, {entry: time.time()})

    async def consolidate(self, namespace: str, messages: list[dict[str, Any]],
                          provider: Any = None, model: str = "") -> bool:
        key = self._history_key(namespace)
        serialized = json.dumps(messages, ensure_ascii=False)
        import time
        await self._redis.zadd(key, {serialized: time.time()})
        return True
```

#### Exercise 2: Unit tests for RedisMemoryBackend

```python
# test_redis_memory.py
"""Tests for RedisMemoryBackend using fakeredis."""
import pytest
from redis_memory import RedisMemoryBackend


@pytest.fixture
async def backend():
    import fakeredis
    r = fakeredis.FakeAsyncRedis()
    b = RedisMemoryBackend(r)
    yield b
    await r.flushall()


class TestRedisMemoryBackend:
    @pytest.mark.asyncio
    async def test_get_context_returns_empty_for_new_namespace(self, backend):
        ctx = await backend.get_context("test:ns1")
        assert ctx == ""

    @pytest.mark.asyncio
    async def test_append_and_read_section(self, backend):
        await backend.append_section("test:ns1", "memory", "first entry")
        await backend.append_section("test:ns1", "memory", "second entry")
        content = await backend.read_section("test:ns1", "memory")
        assert "first entry" in content
        assert "second entry" in content

    @pytest.mark.asyncio
    async def test_add_history(self, backend):
        await backend.add_history("test:ns1", "user hello")
        await backend.add_history("test:ns1", "assistant hi")
        key = backend._history_key("test:ns1")
        count = await backend._redis.zcard(key)
        assert count == 2

    @pytest.mark.asyncio
    async def test_consolidate(self, backend):
        messages = [{"role": "user", "content": "hello"}]
        ok = await backend.consolidate("test:ns1", messages)
        assert ok is True

    @pytest.mark.asyncio
    async def test_read_section_empty_for_new_section(self, backend):
        content = await backend.read_section("test:ns1", "rules")
        assert content == ""

    @pytest.mark.asyncio
    async def test_multiple_namespaces_isolated(self, backend):
        await backend.append_section("ns1", "memory", "data1")
        await backend.append_section("ns2", "memory", "data2")
        c1 = await backend.read_section("ns1", "memory")
        c2 = await backend.read_section("ns2", "memory")
        assert c1 == "\ndata1"
        assert c2 == "\ndata2"
        assert c1 != c2
```

#### Exercise 3: Implement DockerSandboxBackend

```python
# docker_sandbox.py
"""Docker-based SandboxBackend -- one container per session."""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class SandboxSession:
    session_key: str
    volume_path: str
    sandbox_id: str


@dataclass
class ExecResult:
    output: str
    exit_code: int = 0
    is_error: bool = False


class DockerSandboxBackend:
    """One Docker container per session, auto-removed on destroy."""

    def __init__(self, image: str = "python:3.12-slim", workspace_root: str | Path = "./workspace"):
        self._image = image
        self._root = Path(workspace_root).resolve()
        self._root.mkdir(parents=True, exist_ok=True)
        self._containers: dict[str, str] = {}  # session_key -> container_id

    async def create_session(self, session_key: str) -> SandboxSession:
        vol = str(self._root / session_key.replace(":", "_"))
        Path(vol).mkdir(parents=True, exist_ok=True)
        proc = await asyncio.create_subprocess_exec(
            "docker", "run", "-d", "--rm",
            "-v", f"{vol}:/workspace",
            "-w", "/workspace",
            self._image,
            "sleep", "infinity",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        container_id = stdout.decode().strip()
        self._containers[session_key] = container_id
        return SandboxSession(
            session_key=session_key,
            volume_path="/workspace",
            sandbox_id=container_id,
        )

    async def destroy_session(self, session_key: str) -> None:
        cid = self._containers.pop(session_key, None)
        if cid:
            proc = await asyncio.create_subprocess_exec(
                "docker", "rm", "-f", cid,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await proc.wait()

    async def read_file(self, session_key: str, path: str) -> str:
        cid = self._containers.get(session_key)
        if not cid:
            return ""
        proc = await asyncio.create_subprocess_exec(
            "docker", "exec", cid, "cat", path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        return stdout.decode(errors="replace")

    async def write_file(self, session_key: str, path: str, content: str) -> None:
        cid = self._containers.get(session_key)
        if not cid:
            raise RuntimeError(f"No container for session {session_key}")
        proc = await asyncio.create_subprocess_exec(
            "docker", "exec", "-i", cid, "sh", "-c", f"mkdir -p $(dirname {path}) && cat > {path}",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.communicate(input=content.encode())

    async def execute(self, session_key: str, command: str, *,
                      cwd: str = "/workspace", env: dict | None = None,
                      timeout: int = 60) -> ExecResult:
        cid = self._containers.get(session_key)
        if not cid:
            return ExecResult(output="No container", exit_code=-1, is_error=True)
        cmd = ["docker", "exec", "-w", cwd]
        if env:
            for k, v in env.items():
                cmd.extend(["-e", f"{k}={v}"])
        cmd.extend([cid, "sh", "-c", command])
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            return ExecResult(
                output=stdout.decode(errors="replace"),
                exit_code=proc.returncode or 0,
                is_error=proc.returncode != 0,
            )
        except asyncio.TimeoutError:
            return ExecResult(output="Command timed out", exit_code=-1, is_error=True)
```

#### Exercise 4: Implement SQLiteSessionBackend

```python
# sqlite_session.py
"""SQLite-backed SessionBackend -- satisfies the SessionBackend Protocol."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any


class SQLiteSessionBackend:
    """Persists session state in a local SQLite database."""

    def __init__(self, db_path: str | Path = "./sessions.db"):
        self._db_path = Path(db_path)
        self._conn = sqlite3.connect(str(self._db_path))
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS sessions ("
            "  key TEXT PRIMARY KEY,"
            "  state TEXT NOT NULL,"
            "  updated_at TEXT NOT NULL"
            ")"
        )
        self._conn.commit()

    async def load(self, session_key: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT state FROM sessions WHERE key = ?", (session_key,)
        ).fetchone()
        if row is None:
            return None
        return json.loads(row[0])

    async def save(self, session_key: str, state: dict[str, Any]) -> None:
        from datetime import datetime, timezone
        self._conn.execute(
            "INSERT OR REPLACE INTO sessions (key, state, updated_at) VALUES (?, ?, ?)",
            (session_key, json.dumps(state), datetime.now(timezone.utc).isoformat()),
        )
        self._conn.commit()

    async def list_keys(self) -> list[str]:
        rows = self._conn.execute("SELECT key FROM sessions ORDER BY updated_at DESC").fetchall()
        return [row[0] for row in rows]

    def close(self):
        self._conn.close()
```

#### Exercise 5: Production docker-compose.yml

Create `deploy/docker-compose.yml`:

```yaml
version: "3.9"

services:
  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    volumes:
      - redis_data:/data
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 3s

  tencentdb:
    image: tencentdb/memory:latest
    ports:
      - "8420:8420"
    environment:
      DB_PATH: /data/tencentdb
    volumes:
      - tencentdb_data:/data

  postgres:
    image: postgres:16-alpine
    ports:
      - "5432:5432"
    environment:
      POSTGRES_DB: sessions
      POSTGRES_USER: agent
      POSTGRES_PASSWORD: changeme
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U agent -d sessions"]
      interval: 5s

  agent:
    build:
      context: .
      dockerfile: Dockerfile
    ports:
      - "8080:8080"
    environment:
      LLM_HARNESS_REDIS_URL: redis://redis:6379/0
      LLM_HARNESS_MEMORY_URL: http://tencentdb:8420
      LLM_HARNESS_DB_URL: postgresql://agent:changeme@postgres:5432/sessions
      LLM_HARNESS_API_KEY: ${LLM_HARNESS_API_KEY}
      LLM_HARNESS_MODEL: ${LLM_HARNESS_MODEL:-deepseek-chat}
    depends_on:
      redis:
        condition: service_healthy
      postgres:
        condition: service_healthy
    volumes:
      - agent_workspace:/workspace

volumes:
  redis_data:
  tencentdb_data:
  postgres_data:
  agent_workspace:
```

### Deliverable (15min)

- `redis_memory.py` -- full RedisMemoryBackend implementation with all 5 MemoryBackend methods.
- `test_redis_memory.py` -- 6+ tests using fakeredis.
- `docker_sandbox.py` -- full DockerSandboxBackend implementation with all 8 SandboxBackend methods.
- `deploy/docker-compose.yml` -- multi-service production stack.
- Verify: `pytest test_redis_memory.py -v` -- all tests pass.

### Post-Lesson Reflection

The framework uses structural subtyping (Protocols) instead of abstract base classes for its backend interfaces. What are the practical implications for a team that wants to contribute a new backend? How does this affect IDE autocompletion and type checking?

---

## Daily Checkpoints

```
Day 1 -- LLM_HARNESS_API_KEY=sk-xxx python hello_agent.py       -> outputs coherent reply
Day 2 -- LLM_HARNESS_API_KEY=sk-xxx python tool_lab.py           -> 3+ tools invoked in chain
Day 3 -- python session_lab.py                                   -> consolidation triggered by round 8
Day 4 -- LLM_HARNESS_API_KEY=sk-xxx python config_lab.py         -> Agent loaded from YAML
Day 5 -- python extended_agent.py                                -> MCP + Skills + WebSocket all active
Day 6 -- python swarm_lab.py                                     -> sub-agent spawned and result returned
Day 7 -- pytest test_redis_memory.py -v                          -> all tests pass
```

Each checkpoint is a go/no-go gate. If a day's deliverable does not pass, revisit the exercises before moving on.
