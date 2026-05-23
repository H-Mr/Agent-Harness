"""Example: Production-style agent built on agent-harness.

Pattern: Agent = Harness Base + Config + Business Tools + Business Skills + LLM

Demonstrates:
  - Config-driven tool building (build_tools_from_config)
  - Built-in SectionProviders (Environment, Identity, AgentsMD, Skills, Memory)
  - Observability (EventBus + Tracker)
  - ReAct loop with tool calling, permissions, and hooks
  - MockProvider for self-contained testing without API keys

Run: python examples/simple_agent.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from pydantic import BaseModel, Field

from agent_harness import (
    AgentLoop,
    BaseTool,
    Config,
    ContextBuilder,
    LoopCallbacks,
    ObservabilityConfig,
    PermissionChecker,
    PermissionSettings,
    SkillDefinition,
    SkillRegistry,
    ToolsConfig,
    ToolExecutionContext,
    ToolRegistry,
    ToolResult,
    TurnResult,
    build_tools_from_config,
    parse_skill_markdown,
)
from agent_harness.hooks import (
    HookEvent,
    HookExecutionContext,
    HookExecutor,
    HookRegistry,
)
from agent_harness.hooks.schemas import CommandHookDefinition
from agent_harness.observability import get_event_bus, Tracker
from agent_harness.observability.events import (
    AssistantTurnComplete,
    ToolExecutionCompleted,
    ToolExecutionStarted,
)
from agent_harness.permissions.modes import PermissionMode
from agent_harness.prompts.sections import (
    EnvironmentSection,
    IdentitySection,
    MemorySection,
    SkillsSection,
)
from agent_harness.providers.base import LLMProvider, LLMResponse, ToolCallRequest

# ============================================================================
# Business tools
# ============================================================================


class OrderQueryInput(BaseModel):
    order_id: str = Field(description="Order ID to look up")


class OrderQueryTool(BaseTool):
    name = "order_query"
    description = "Look up an order by ID. Returns status and details."
    input_model = OrderQueryInput

    async def execute(self, arguments: OrderQueryInput, context: ToolExecutionContext) -> ToolResult:
        orders = {"001": "Shipped — arriving tomorrow", "002": "Processing — 3 days ETA"}
        info = orders.get(arguments.order_id, f"Order {arguments.order_id} not found")
        return ToolResult(output=info)


class RefundInput(BaseModel):
    order_id: str = Field(description="Order ID to refund")
    reason: str = Field(default="", description="Refund reason")


class RefundTool(BaseTool):
    name = "refund"
    description = "Initiate a refund for an order."
    input_model = RefundInput

    async def execute(self, arguments: RefundInput, context: ToolExecutionContext) -> ToolResult:
        return ToolResult(output=f"Refund initiated for order {arguments.order_id}. 5-7 business days.")


# ============================================================================
# Business skill (on-demand knowledge)
# ============================================================================

RETURN_POLICY_SKILL = """---
name: return-policy
description: How to handle returns and refunds
---

# Return Policy

- 30-day return window from delivery date
- Refunds processed within 5-7 business days
- Return shipping is free for defective items
- Customer pays return shipping for change-of-mind returns
"""

# ============================================================================
# Mock provider (for self-contained testing)
# ============================================================================


class MockProvider(LLMProvider):
    """Scripted LLM — returns pre-defined responses for testing."""

    def __init__(self, responses: list[LLMResponse] | None = None):
        super().__init__(api_key="mock")
        self._responses = responses or []
        self._idx = 0
        self.calls: list[dict] = []

    def get_default_model(self) -> str:
        return "mock"

    async def chat(self, messages, tools=None, model=None, max_tokens=4096,
                   temperature=0.7, reasoning_effort=None, tool_choice=None):
        self.calls.append({"messages": messages, "tools": tools})
        if self._idx < len(self._responses):
            r = self._responses[self._idx]
            self._idx += 1
            return r
        last = ""
        for m in reversed(messages):
            if m.get("role") == "user":
                last = str(m.get("content", ""))
                break
        return LLMResponse(content=f"Echo: {last}",
                           usage={"prompt_tokens": 10, "completion_tokens": 5})


# ============================================================================
# Agent assembly
# ============================================================================


def build_agent(*, enable_observability: bool = True) -> AgentLoop:
    """Compose a customer-service agent from harness base + config + business components."""

    # ── Config ──────────────────────────────────────────────────────────
    config = Config(
        tools=ToolsConfig(enabled=["*"], disabled=["exec", "notebook_edit", "spawn"]),
        observability=ObservabilityConfig(
            track_file="~/.agent-harness/track.jsonl" if enable_observability else None
        ),
    )

    # ── Provider ────────────────────────────────────────────────────────
    provider = MockProvider()

    # ── Tools ───────────────────────────────────────────────────────────
    tools = build_tools_from_config(config.tools)
    tools.register(OrderQueryTool())
    tools.register(RefundTool())

    async def execute_tool(name: str, args: dict) -> str:
        tool = tools.get(name)
        if tool is None:
            return f"Error: tool '{name}' not found"
        parsed = tool.input_model.model_validate(args)
        result = await tool.execute(parsed, ToolExecutionContext(cwd=Path.cwd()))
        return result.output

    # ── Permissions ─────────────────────────────────────────────────────
    permission = PermissionChecker(PermissionSettings(mode=PermissionMode.DEFAULT))

    async def execute_with_permission(name: str, args: dict) -> str:
        tool = tools.get(name)
        is_read_only = tool.is_read_only(tool.input_model.model_validate(args)) if tool else False
        decision = permission.evaluate(name, is_read_only=is_read_only)
        if not decision.allowed:
            return f"Permission denied: {decision.reason}"
        return await execute_tool(name, args)

    # ── Hooks ───────────────────────────────────────────────────────────
    hooks = HookRegistry()
    hooks.register(HookEvent.PRE_TOOL_USE, CommandHookDefinition(
        command="echo observed-refund", matcher="refund",
    ))

    async def execute_with_hooks(name: str, args: dict) -> str:
        executor = HookExecutor(hooks, HookExecutionContext(
            cwd=Path.cwd(), provider=provider, default_model="mock",
        ))
        hook_result = await executor.execute(HookEvent.PRE_TOOL_USE, {
            "tool_name": name, "tool_input": args,
        })
        if hook_result.blocked:
            return f"Blocked by hook: {hook_result.reason}"
        return await execute_with_permission(name, args)

    # ── Context ─────────────────────────────────────────────────────────
    skills = SkillRegistry()
    name, desc = parse_skill_markdown("return-policy", RETURN_POLICY_SKILL)
    skills.register(SkillDefinition(name=name, description=desc,
                     content=RETURN_POLICY_SKILL, source="inline"))

    context = ContextBuilder()
    context.add_provider(EnvironmentSection())
    context.add_provider(IdentitySection("# Identity\nYou are a customer service agent. Be helpful and concise."))
    context.add_provider(SkillsSection(skills))
    context.add_provider(MemorySection(None))

    def build_messages(msg):
        return [
            {"role": "system", "content": "You are a helpful customer service agent."},
            {"role": "user", "content": msg.content},
        ]

    # ── Observability ───────────────────────────────────────────────────
    if enable_observability:
        bus = get_event_bus()
        bus.subscribe(_print_event)

    # ── Callbacks ───────────────────────────────────────────────────────
    callbacks = LoopCallbacks(
        build_messages=build_messages,
        execute_tool=execute_with_hooks,
        get_tool_definitions=lambda: tools.to_api_schema("openai"),
    )

    return AgentLoop(provider, callbacks)


async def _print_event(event: object) -> None:
    """Print structured events as they happen (observability demo)."""
    if isinstance(event, ToolExecutionStarted):
        print(f"  [obs] ▶ {event.tool_name}({json.dumps(event.tool_input)})")
    elif isinstance(event, ToolExecutionCompleted):
        status = "✗" if event.is_error else "✓"
        print(f"  [obs] ◀ {event.tool_name} {status} ({event.duration_ms:.1f}ms)")
    elif isinstance(event, AssistantTurnComplete):
        print(f"  [obs] 📊 turn complete — tokens: {event.usage}")


# ============================================================================
# Demo
# ============================================================================


async def demo():
    print("=" * 55)
    print("  Customer Service Agent — Built on Agent Harness")
    print("=" * 55)

    agent = build_agent(enable_observability=True)

    # ── Demo 1: Pure text (no tool call) ────────────────────────────────
    print("\n── Demo 1: Pure text response ──")
    result = await agent.process_direct("Hello! I need help with an order.")
    print(f"  Response: {result.final_content}")
    print(f"  Tools used: {result.tools_used}")

    # ── Demo 2: Tool calling via ReAct ─────────────────────────────────
    print("\n── Demo 2: Tool call (order_query) ──")
    provider = MockProvider([
        LLMResponse(
            content=None,
            tool_calls=[ToolCallRequest(id="c1", name="order_query", arguments={"order_id": "001"})],
            finish_reason="tool_calls",
            usage={"prompt_tokens": 15, "completion_tokens": 8},
        ),
        LLMResponse(
            content="Your order #001 has been shipped and will arrive tomorrow!",
            usage={"prompt_tokens": 20, "completion_tokens": 12},
        ),
    ])

    tools = ToolRegistry()
    tools.register(OrderQueryTool())
    tools.register(RefundTool())

    callbacks = LoopCallbacks(
        build_messages=lambda msg: [{"role": "system", "content": "cs agent"}, {"role": "user", "content": msg.content}],
        execute_tool=lambda name, args: _exec(tools, name, args),
        get_tool_definitions=lambda: tools.to_api_schema("openai"),
    )

    agent2 = AgentLoop(provider, callbacks)
    result = await agent2.process_direct("Where is my order #001?")
    print(f"  Response: {result.final_content}")
    print(f"  Tools used: {result.tools_used}")

    # ── Demo 3: Config-driven tools ────────────────────────────────────
    print("\n── Demo 3: Config-driven tool set ──")
    config = ToolsConfig(enabled=["order_query", "refund"])
    tools3 = build_tools_from_config(config)
    tools3.register(OrderQueryTool())
    tools3.register(RefundTool())
    print(f"  Registered: {[t.name for t in tools3.list_tools()]}")

    # ── Demo 4: Tracker output (JSONL) ─────────────────────────────────
    print("\n── Demo 4: Observability tracker (last 10 lines) ──")
    track_path = Path("~/.agent-harness/track.jsonl").expanduser()
    if track_path.exists():
        lines = track_path.read_text().strip().split("\n")[-10:]
        for line in lines:
            rec = json.loads(line)
            print(f"  [{rec['type']}] {json.dumps(rec.get('data', {}), ensure_ascii=False)[:80]}")
    else:
        print("  (no events — tracker not started or no events emitted)")

    print("\n" + "=" * 55)
    print("  All demos complete.")
    print("=" * 55)


async def _exec(tools: ToolRegistry, name: str, args: dict) -> str:
    tool = tools.get(name)
    if tool is None:
        return f"Error: tool '{name}' not found"
    parsed = tool.input_model.model_validate(args)
    result = await tool.execute(parsed, ToolExecutionContext(cwd=Path.cwd()))
    return result.output


if __name__ == "__main__":
    asyncio.run(demo())
