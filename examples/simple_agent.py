"""Example: Minimal agent built on agent-harness base.

This demonstrates the pattern:
  Business Agent = Harness Base + Business Tools + Business Skills + LLM

Run: python examples/simple_agent.py
"""

import asyncio
import sys
from pathlib import Path
from typing import Any

# Add the src directory to path (for development without pip install)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from agent_harness import (
    AgentLoop,
    BaseTool,
    ContextBuilder,
    InboundMessage,
    LLMProvider,
    LLMResponse,
    LoopCallbacks,
    MessageBus,
    MemoryStore,
    SectionProvider,
    SkillDefinition,
    SkillRegistry,
    ToolExecutionContext,
    ToolRegistry,
    ToolResult,
    parse_skill_markdown,
)
from pydantic import BaseModel, Field


# ============================================================================
# Step 1: Define business-specific tools
# ============================================================================


class GreetInput(BaseModel):
    name: str = Field(description="Person's name to greet")
    language: str = Field(default="en", description="Language: en, zh, ja")


class GreetTool(BaseTool):
    """Greet someone in their preferred language."""

    name = "greet"
    description = "Generate a greeting for a person in the specified language."
    input_model = GreetInput

    async def execute(self, arguments: GreetInput, context: ToolExecutionContext) -> ToolResult:
        greetings = {"en": "Hello", "zh": "你好", "ja": "こんにちは"}
        greeting = greetings.get(arguments.language, "Hello")
        return ToolResult(output=f"{greeting}, {arguments.name}!")


class CalcInput(BaseModel):
    expression: str = Field(description="Math expression to evaluate, e.g. '2 + 3 * 4'")


class CalcTool(BaseTool):
    """Evaluate a simple math expression. Supports +, -, *, /, //, %, **."""

    name = "calc"
    description = "Evaluate a math expression. Example: calc('2 + 3 * 4')"
    input_model = CalcInput

    async def execute(self, arguments: CalcInput, context: ToolExecutionContext) -> ToolResult:
        try:
            result = eval(
                arguments.expression,
                {"__builtins__": {}},
                {
                    "abs": abs, "round": round, "min": min, "max": max,
                    "sum": sum, "pow": pow, "int": int, "float": float,
                },
            )
            return ToolResult(output=str(result))
        except Exception as e:
            return ToolResult(output=f"Error: {e}", is_error=True)


# ============================================================================
# Step 2: Define business-specific skills (knowledge)
# ============================================================================


class IdentitySection(SectionProvider):
    """Inject the agent's identity into the system prompt."""

    section_name = "identity"
    priority = 10

    async def get_section(self) -> str:
        return """# Identity
You are SimpleBot, a helpful assistant. You can greet people and do calculations.
Keep responses brief and friendly."""


class SkillsSection(SectionProvider):
    """Inject loaded skills into the system prompt."""

    section_name = "skills"
    priority = 50

    def __init__(self, registry: SkillRegistry):
        self._registry = registry

    async def get_section(self) -> str:
        skills = self._registry.list_skills()
        if not skills:
            return ""
        lines = ["# Available Skills"]
        for s in skills:
            lines.append(f"- **{s.name}**: {s.description}")
        return "\n".join(lines)


# ============================================================================
# Step 3: Mock LLM provider (for testing without API keys)
# ============================================================================


class MockProvider(LLMProvider):
    """A mock provider that echoes the last user message for testing."""

    def __init__(self, tool_responses: list[LLMResponse] | None = None):
        super().__init__(api_key="mock", api_base="mock")
        self._responses = tool_responses or []
        self._idx = 0
        self.call_history: list[dict] = []

    def get_default_model(self) -> str:
        return "mock-model"

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        reasoning_effort: str | None = None,
        tool_choice: str | dict[str, Any] | None = None,
    ) -> LLMResponse:
        self.call_history.append({
            "messages": messages,
            "tools": tools,
        })
        if self._idx < len(self._responses):
            resp = self._responses[self._idx]
            self._idx += 1
            return resp
        # Default: echo last user message
        last_user = ""
        for m in reversed(messages):
            if m.get("role") == "user":
                last_user = str(m.get("content", ""))
                break
        return LLMResponse(content=f"Echo: {last_user}", usage={"prompt_tokens": 10, "completion_tokens": 5})


# ============================================================================
# Step 4: Assemble the agent
# ============================================================================


def build_agent() -> AgentLoop:
    """Compose a SimpleBot agent from the harness base + business components."""

    # Provider
    provider = MockProvider()

    # Tools
    tools = ToolRegistry()
    tools.register(GreetTool())
    tools.register(CalcTool())

    # Skills
    skills = SkillRegistry()
    skill_content = """---
name: small-talk
description: How to handle casual conversation and small talk
---

# Small Talk Skill

When the user makes small talk:
1. Be warm and engaging
2. Ask a follow-up question
3. Keep it brief
"""
    name, desc = parse_skill_markdown("small-talk", skill_content)
    skills.register(SkillDefinition(
        name=name, description=desc, content=skill_content, source="inline"
    ))

    # Context
    context = ContextBuilder()
    context.add_provider(IdentitySection())
    context.add_provider(SkillsSection(skills))

    # Memory
    memory = MemoryStore(Path.home() / ".agent-harness" / "workspace" / "memory")
    memory_context = memory.get_memory_context()

    # Callbacks — wire everything together
    callbacks = LoopCallbacks(
        build_messages=lambda msg: _build_messages(context, memory_context, msg),
        execute_tool=lambda name, args: _execute_tool(tools, name, args),
        get_tool_definitions=lambda: tools.to_api_schema("openai"),
    )

    return AgentLoop(provider, callbacks)


async def _execute_tool(tools: ToolRegistry, name: str, args: dict) -> str:
    tool = tools.get(name)
    if tool is None:
        return f"Error: tool '{name}' not found"
    try:
        parsed = tool.input_model.model_validate(args)
        result = await tool.execute(parsed, ToolExecutionContext(cwd=Path.cwd()))
        return result.output
    except Exception as e:
        return f"Error: {e}"


def _build_messages(context: ContextBuilder, memory: str, msg: InboundMessage) -> list[dict]:
    system = f"You are a helpful assistant.\n\n{memory}" if memory else "You are a helpful assistant."
    runtime = f"Current time: 2026-05-24"
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": f"{runtime}\n\n{msg.content}"},
    ]


# ============================================================================
# Step 5: Run
# ============================================================================


async def demo():
    print("=" * 50)
    print("SimpleBot Demo — Built on Agent Harness")
    print("=" * 50)

    agent = build_agent()

    # Demo 1: Direct processing
    print("\n--- Demo 1: process_direct() ---")
    result = await agent.process_direct("Hello! My name is Alice.")
    print(f"Response: {result.final_content}")
    print(f"Tools used: {result.tools_used}")

    # Demo 2: With tool calling (mock provider returns a tool call first)
    print("\n--- Demo 2: Tool calling via ReAct loop ---")

    from agent_harness import ToolCallRequest

    provider2 = MockProvider([
        LLMResponse(
            content=None,
            tool_calls=[ToolCallRequest(
                id="call_1", name="greet",
                arguments={"name": "Bob", "language": "zh"},
            )],
            finish_reason="tool_calls",
            usage={"prompt_tokens": 10, "completion_tokens": 5},
        ),
        LLMResponse(
            content="I just greeted Bob in Chinese! How can I help further?",
            usage={"prompt_tokens": 15, "completion_tokens": 10},
        ),
    ])

    tools = ToolRegistry()
    tools.register(GreetTool())
    tools.register(CalcTool())

    callbacks = LoopCallbacks(
        build_messages=lambda msg: [{"role": "system", "content": "helpful assistant"}, {"role": "user", "content": msg.content}],
        execute_tool=lambda name, args: _execute_tool(tools, name, args),
        get_tool_definitions=lambda: tools.to_api_schema("openai"),
    )

    agent2 = AgentLoop(provider2, callbacks)
    result2 = await agent2.process_direct("Greet Bob in Chinese")
    print(f"Response: {result2.final_content}")
    print(f"Tools used: {result2.tools_used}")  # Should include "greet"

    # Demo 3: Message bus pattern
    print("\n--- Demo 3: MessageBus pattern ---")
    bus = MessageBus()
    await bus.publish_inbound(InboundMessage(
        channel="cli", sender_id="user", chat_id="demo", content="What's 10 + 20?"
    ))
    msg = await bus.consume_inbound()
    print(f"Consumed: {msg.content} (session_key={msg.session_key})")

    print("\nAll demos complete!")
    print("=" * 50)


if __name__ == "__main__":
    asyncio.run(demo())
