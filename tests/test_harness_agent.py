"""Tests for agent_harness.harness — Harness creation with shorthand forms."""

from __future__ import annotations

from pathlib import Path
from typing import Any, ClassVar

import pytest
from pydantic import BaseModel

from agent_harness.config.schema import Config, ToolsConfig
from agent_harness.context.base import ContextBuilder, SectionProvider
from agent_harness.harness import Harness
from agent_harness.hooks.loader import HookRegistry
from agent_harness.memory.store import MemoryStore
from agent_harness.observability.tracker import Tracker
from agent_harness.permissions.checker import PermissionChecker, PermissionDecision
from agent_harness.permissions.modes import PermissionMode
from agent_harness.permissions.settings import PermissionSettings
from agent_harness.bus.events import InboundMessage
from unittest.mock import patch

from agent_harness.providers.base import LLMProvider, LLMResponse, ToolCallRequest
from agent_harness.agent import Agent
from agent_harness.session.manager import SessionManager
from agent_harness.skills.registry import SkillRegistry
from agent_harness.tools.base import BaseTool, ToolExecutionContext, ToolRegistry, ToolResult


# ---------------------------------------------------------------------------
# Mock provider
# ---------------------------------------------------------------------------


class MockProvider(LLMProvider):
    """Provider that returns scripted responses."""

    def __init__(
        self,
        response_text: str = "Mock response",
        responses: list[LLMResponse] | None = None,
    ) -> None:
        super().__init__()
        self.response_text = response_text
        self._responses = responses
        self.call_count = 0

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
        if self._responses is not None:
            response = self._responses[
                self.call_count % len(self._responses)
            ]
            self.call_count += 1
            return response
        return LLMResponse(content=self.response_text)

    def get_default_model(self) -> str:
        return "mock-model"


# ---------------------------------------------------------------------------
# Echo tool for testing
# ---------------------------------------------------------------------------


class EchoInput(BaseModel):
    """Input model for EchoTool."""

    text: str


class EchoTool(BaseTool):
    """Simple tool that echoes input back."""

    name: ClassVar[str] = "echo"
    description: ClassVar[str] = "Echoes input back"
    input_model: ClassVar[type[BaseModel]] = EchoInput

    async def execute(
        self, arguments: EchoInput, context: ToolExecutionContext
    ) -> ToolResult:
        return ToolResult(output=arguments.text)

    def is_read_only(self, arguments: BaseModel) -> bool:
        return True


class MutatingInput(BaseModel):
    """Input model for a mutating (non-read-only) tool."""

    message: str


class MutatingTool(BaseTool):
    """Tool that is NOT read-only — useful for permission tests."""

    name: ClassVar[str] = "mutate"
    description: ClassVar[str] = "Mutates state (not read-only)"
    input_model: ClassVar[type[BaseModel]] = MutatingInput

    async def execute(
        self, arguments: MutatingInput, context: ToolExecutionContext
    ) -> ToolResult:
        return ToolResult(output=f"Mutated: {arguments.message}")

    def is_read_only(self, arguments: BaseModel) -> bool:
        return False


class FailingProvider(MockProvider):
    """Provider that raises ValueError during chat_with_retry."""

    async def chat_with_retry(self, **kwargs: Any) -> LLMResponse:
        raise ValueError("LLM API call failed")


# ---------------------------------------------------------------------------
# Section provider helper
# ---------------------------------------------------------------------------


class _TestSectionProvider(SectionProvider):
    """Simple section provider for testing."""

    def __init__(self, name: str, content: str, priority: int = 100) -> None:
        self._name = name
        self._content = content
        self._priority = priority

    @property
    def section_name(self) -> str:
        return self._name

    async def get_section(self) -> str:
        return self._content

    @property
    def priority(self) -> int:
        return self._priority


def _make_provider(name: str, content: str, priority: int = 100) -> SectionProvider:
    """Create a SectionProvider for testing."""
    return _TestSectionProvider(name, content, priority)


# ---------------------------------------------------------------------------
# Harness creation tests
# ---------------------------------------------------------------------------


class TestHarnessCreation:
    """Tests for Harness.__init__ shorthand resolution."""

    def test_requires_provider(self) -> None:
        """Calling Harness() without the provider keyword should raise TypeError."""
        with pytest.raises(TypeError):
            Harness()

    def test_default_creation(self) -> None:
        """Harness(provider=...) should set sensible defaults for all optional params."""
        harness = Harness(provider=MockProvider())

        assert isinstance(harness.provider, MockProvider)
        assert harness.workspace == Path.cwd().resolve()

        # Tools: None -> empty ToolRegistry
        assert isinstance(harness.tools, ToolRegistry)
        assert len(harness.tools) == 0

        # Permissions: None -> PermissionChecker with default settings
        assert isinstance(harness.permissions, PermissionChecker)

        # Memory/Sessions: None -> disabled
        assert harness.memory is None
        assert harness.sessions is None

        # Context: None -> empty ContextBuilder
        assert isinstance(harness.context, ContextBuilder)

        # Skills/Hooks/Tracker: None -> disabled
        assert harness.skills is None
        assert harness.hooks is None
        assert harness.tracker is None

        # Default generation caps
        assert harness.context_window_tokens == 64_000
        assert harness.max_completion_tokens == 4096

    # ------------------------------------------------------------------
    # Tools
    # ------------------------------------------------------------------

    def test_tools_as_tool_registry(self) -> None:
        """A pre-built ToolRegistry should be passed through as-is."""
        registry = ToolRegistry()
        registry.register(EchoTool())
        harness = Harness(provider=MockProvider(), tools=registry)
        assert harness.tools is registry
        assert harness.tools.has("echo")

    def test_tools_as_config(self) -> None:
        """A ToolsConfig should be resolved via build_tools_from_config."""
        config = ToolsConfig()
        harness = Harness(provider=MockProvider(), tools=config)
        assert isinstance(harness.tools, ToolRegistry)
        # Verify at least one tool was registered
        assert len(harness.tools) > 0

    def test_tools_as_string_list(self) -> None:
        """A list of tool name strings should be resolved into a ToolRegistry."""
        harness = Harness(provider=MockProvider(), tools=["read_file", "write_file"])
        assert isinstance(harness.tools, ToolRegistry)
        assert harness.tools.has("read_file")
        assert harness.tools.has("write_file")

    def test_tools_none_gives_empty_registry(self) -> None:
        """tools=None should produce an empty ToolRegistry."""
        harness = Harness(provider=MockProvider(), tools=None)
        assert isinstance(harness.tools, ToolRegistry)
        assert len(harness.tools) == 0

    # ------------------------------------------------------------------
    # Permissions
    # ------------------------------------------------------------------

    @pytest.mark.parametrize("mode_str", ["default", "plan", "auto", "full_auto"])
    def test_permissions_as_string(self, mode_str: str) -> None:
        """A permission mode string should create a PermissionChecker."""
        harness = Harness(provider=MockProvider(), permissions=mode_str)
        assert isinstance(harness.permissions, PermissionChecker)

    def test_permissions_as_settings(self) -> None:
        """PermissionSettings should be wrapped in a PermissionChecker."""
        settings = PermissionSettings(mode=PermissionMode.PLAN)
        harness = Harness(provider=MockProvider(), permissions=settings)
        assert isinstance(harness.permissions, PermissionChecker)

    def test_permissions_as_checker(self) -> None:
        """A PermissionChecker should be passed through as-is."""
        checker = PermissionChecker(PermissionSettings(mode=PermissionMode.FULL_AUTO))
        harness = Harness(provider=MockProvider(), permissions=checker)
        assert harness.permissions is checker

    # ------------------------------------------------------------------
    # Memory
    # ------------------------------------------------------------------

    def test_memory_as_path_string(self, tmp_path: Path) -> None:
        """A string path should be resolved to a MemoryStore."""
        memory_dir = tmp_path / "mem-store"
        harness = Harness(provider=MockProvider(), memory=str(memory_dir))
        assert isinstance(harness.memory, MemoryStore)
        assert harness.memory.memory_dir == memory_dir.resolve()

    def test_memory_as_path_object(self, tmp_path: Path) -> None:
        """A Path object should be resolved to a MemoryStore."""
        memory_dir = tmp_path / "mem-store"
        harness = Harness(provider=MockProvider(), memory=memory_dir)
        assert isinstance(harness.memory, MemoryStore)
        assert harness.memory.memory_dir == memory_dir.resolve()

    def test_memory_as_store(self, tmp_path: Path) -> None:
        """A MemoryStore should be passed through as-is."""
        store = MemoryStore(tmp_path / "mem")
        harness = Harness(provider=MockProvider(), memory=store)
        assert harness.memory is store

    def test_memory_none_disabled(self) -> None:
        """memory=None should disable memory."""
        harness = Harness(provider=MockProvider(), memory=None)
        assert harness.memory is None

    # ------------------------------------------------------------------
    # Sessions
    # ------------------------------------------------------------------

    def test_sessions_as_path_string(self, tmp_path: Path) -> None:
        """A string path should be resolved to a SessionManager."""
        harness = Harness(provider=MockProvider(), sessions=str(tmp_path))
        assert isinstance(harness.sessions, SessionManager)

    def test_sessions_as_path_object(self, tmp_path: Path) -> None:
        """A Path object should be resolved to a SessionManager."""
        harness = Harness(provider=MockProvider(), sessions=tmp_path)
        assert isinstance(harness.sessions, SessionManager)

    def test_sessions_as_manager(self, tmp_path: Path) -> None:
        """A SessionManager should be passed through as-is."""
        manager = SessionManager(tmp_path)
        harness = Harness(provider=MockProvider(), sessions=manager)
        assert harness.sessions is manager

    def test_sessions_none_disabled(self) -> None:
        """sessions=None should disable sessions."""
        harness = Harness(provider=MockProvider(), sessions=None)
        assert harness.sessions is None

    # ------------------------------------------------------------------
    # Context
    # ------------------------------------------------------------------

    def test_context_as_section_provider_list(self) -> None:
        """A list of SectionProviders should be added to a ContextBuilder."""
        provider = _make_provider("test", "Hello from test")
        harness = Harness(provider=MockProvider(), context=[provider])
        assert isinstance(harness.context, ContextBuilder)

    def test_context_as_builder(self) -> None:
        """A ContextBuilder should be passed through as-is."""
        builder = ContextBuilder()
        builder.add_provider(_make_provider("test", "content"))
        harness = Harness(provider=MockProvider(), context=builder)
        assert harness.context is builder

    # ------------------------------------------------------------------
    # Skills
    # ------------------------------------------------------------------

    def test_skills_as_directory_list(self, tmp_path: Path) -> None:
        """A list of directory paths should be loaded into a SkillRegistry."""
        skill_root = tmp_path / "my-skills"
        skill_dir = skill_root / "test-skill"
        skill_dir.mkdir(parents=True)
        skill_md = skill_dir / "SKILL.md"
        skill_md.write_text(
            "---\nname: test-skill\ndescription: A test skill\n---\n\nSkill content here\n"
        )
        harness = Harness(provider=MockProvider(), skills=[str(skill_root)])
        assert isinstance(harness.skills, SkillRegistry)
        skills = harness.skills.list_skills()
        assert len(skills) == 1
        assert skills[0].name == "test-skill"
        assert skills[0].description == "A test skill"

    def test_skills_as_registry(self) -> None:
        """A SkillRegistry should be passed through as-is."""
        registry = SkillRegistry()
        harness = Harness(provider=MockProvider(), skills=registry)
        assert harness.skills is registry

    def test_skills_none(self) -> None:
        """skills=None should disable skills."""
        harness = Harness(provider=MockProvider(), skills=None)
        assert harness.skills is None

    # ------------------------------------------------------------------
    # Hooks
    # ------------------------------------------------------------------

    def test_hooks_as_registry(self) -> None:
        """A HookRegistry should be passed through as-is."""
        registry = HookRegistry()
        harness = Harness(provider=MockProvider(), hooks=registry)
        assert harness.hooks is registry

    def test_hooks_none(self) -> None:
        """hooks=None should disable hooks."""
        harness = Harness(provider=MockProvider(), hooks=None)
        assert harness.hooks is None

    # ------------------------------------------------------------------
    # Tracker
    # ------------------------------------------------------------------

    def test_tracker_path(self, tmp_path: Path) -> None:
        """A tracker path string should be resolved into a Tracker instance."""
        track_file = tmp_path / "track.jsonl"
        harness = Harness(provider=MockProvider(), tracker=str(track_file))
        assert isinstance(harness.tracker, Tracker)

    def test_tracker_path_object(self, tmp_path: Path) -> None:
        """A Path tracker should be resolved into a Tracker instance."""
        track_file = tmp_path / "track.jsonl"
        harness = Harness(provider=MockProvider(), tracker=track_file)
        assert isinstance(harness.tracker, Tracker)

    def test_tracker_none(self) -> None:
        """tracker=None should disable tracking."""
        harness = Harness(provider=MockProvider(), tracker=None)
        assert harness.tracker is None


# ---------------------------------------------------------------------------
# Harness callback tests
# ---------------------------------------------------------------------------


class TestHarnessCallbacks:
    """Tests for Harness pipeline callbacks."""

    async def test_default_tool_check_delegates_to_permissions(self) -> None:
        """Default mode allows read-only tools."""
        harness = Harness(provider=MockProvider())
        tool = EchoTool()
        decision = await harness.on_tool_check("echo", tool, EchoInput(text="test"))
        assert isinstance(decision, PermissionDecision)
        # Default mode allows read-only tools
        assert decision.allowed is True

    async def test_custom_tool_check_overrides_default(self) -> None:
        """Custom callback replaces default."""
        async def custom_check(
            name: str, tool: BaseTool, parsed_args: Any,
        ) -> PermissionDecision:
            return PermissionDecision(allowed=False, reason="blocked by custom")

        harness = Harness(provider=MockProvider(), on_tool_check=custom_check)
        tool = EchoTool()
        decision = await harness.on_tool_check("echo", tool, EchoInput(text="test"))
        assert decision.allowed is False
        assert "custom" in decision.reason

    async def test_default_build_context(self) -> None:
        """Builds system prompt + history + user message."""
        harness = Harness(
            provider=MockProvider(),
            context=[_make_provider("test", "System prompt content")],
        )
        msg = InboundMessage(
            channel="cli",
            sender_id="user",
            chat_id="test-chat",
            content="Hello world",
        )
        messages = await harness.on_build_context(msg, [])
        assert isinstance(messages, list)
        assert len(messages) >= 2
        assert messages[0]["role"] == "system"
        assert "System prompt content" in messages[0]["content"]
        assert messages[-1]["role"] == "user"
        assert "Hello world" in messages[-1]["content"]

    async def test_default_on_error(self) -> None:
        """Returns user-facing error string."""
        harness = Harness(provider=MockProvider())
        result = await harness.on_error(ValueError("test error"), "test_context")
        assert result == "Sorry, I encountered an error processing your request."

    async def test_custom_on_error(self) -> None:
        """Custom callback overrides default."""
        async def custom_error(exc: Exception, ctx: str) -> str | None:
            return f"Custom error handler: {exc}"

        harness = Harness(provider=MockProvider(), on_error=custom_error)
        result = await harness.on_error(ValueError("something broke"), "ctx")
        assert result == "Custom error handler: something broke"


# ---------------------------------------------------------------------------
# Harness from_config tests
# ---------------------------------------------------------------------------


class TestHarnessFromConfig:
    """Tests for Harness.from_config factory."""

    def test_from_config_with_minimal_config(self, tmp_path: Path) -> None:
        """Creates a working Harness from a minimal Config with MockProvider."""
        config = Config()
        config.agent.workspace = str(tmp_path)
        with patch(
            "agent_harness.harness.Harness._provider_from_config",
            return_value=MockProvider(),
        ):
            harness = Harness.from_config(config)

        assert isinstance(harness, Harness)
        assert isinstance(harness.provider, MockProvider)
        assert isinstance(harness.tools, ToolRegistry)
        assert len(harness.tools) > 0  # default ToolsConfig enables all tools
        assert isinstance(harness.permissions, PermissionChecker)
        assert isinstance(harness.memory, MemoryStore)
        assert isinstance(harness.sessions, SessionManager)
        assert harness.tracker is None
        assert harness.context_window_tokens == 64_000
        assert harness.max_completion_tokens == 8192

    def test_from_config_raises_on_unknown_provider(self) -> None:
        """Raises ValueError when provider cannot be resolved."""
        config = Config()
        config.agent.provider = "nonexistent_provider"
        with pytest.raises(ValueError, match="Unknown provider"):
            Harness.from_config(config)


# ---------------------------------------------------------------------------
# Agent process() tests
# ---------------------------------------------------------------------------


class TestAgentProcess:
    """Tests for Agent.process() pipeline."""

    async def test_process_text_only(self) -> None:
        """Simple text response — no tools, no session, no memory."""
        harness = Harness(
            provider=MockProvider(
                responses=[LLMResponse(content="Hello!")]
            ),
            context=[_make_provider("identity", "You are a helpful assistant.")],
        )
        agent = Agent(harness)
        msg = InboundMessage(
            channel="cli", sender_id="u1", chat_id="c1", content="hi"
        )
        result = await agent.process(msg)
        assert result is not None
        assert result.content == "Hello!"
        assert result.channel == "cli"

    async def test_process_with_tool_call(self) -> None:
        """LLM calls a tool, then responds."""
        harness = Harness(
            provider=MockProvider(
                responses=[
                    LLMResponse(
                        content=None,
                        tool_calls=[
                            ToolCallRequest(
                                id="c1",
                                name="echo",
                                arguments={"text": "ping"},
                            )
                        ],
                    ),
                    LLMResponse(content="Tool said: ping"),
                ],
            ),
        )
        # Register EchoTool manually AFTER creating the harness
        harness.tools.register(EchoTool())
        agent = Agent(harness)

        msg = InboundMessage(
            channel="cli", sender_id="u1", chat_id="c1", content="say ping"
        )
        result = await agent.process(msg)
        assert result is not None
        assert "ping" in result.content

    async def test_process_with_session_persistence(self, tmp_path: Path) -> None:
        """With sessions configured, messages are persisted between turns."""
        session_dir = tmp_path / "sessions"
        provider = MockProvider(
            responses=[LLMResponse(content="First reply")]
        )
        harness = Harness(provider=provider, sessions=session_dir)
        agent = Agent(harness)

        msg1 = InboundMessage(
            channel="cli", sender_id="u1", chat_id="c1", content="hello"
        )
        result1 = await agent.process(msg1)
        assert result1 is not None
        assert result1.content == "First reply"

        # Verify session has messages after first turn
        session = harness.sessions.get_or_create("cli:c1")
        assert len(session.messages) == 2
        assert session.messages[0]["role"] == "user"
        assert "hello" in session.messages[0]["content"]
        assert session.messages[1]["role"] == "assistant"

        # Second turn
        provider._responses = [LLMResponse(content="Second reply")]
        provider.call_count = 0

        msg2 = InboundMessage(
            channel="cli", sender_id="u1", chat_id="c1", content="again"
        )
        result2 = await agent.process(msg2)
        assert result2 is not None
        assert result2.content == "Second reply"

        # Session now has four messages
        assert len(session.messages) == 4
        assert session.messages[2]["role"] == "user"
        assert "again" in session.messages[2]["content"]
        assert session.messages[3]["role"] == "assistant"
        assert session.messages[3]["content"] == "Second reply"

    async def test_process_permission_denies_tool(self) -> None:
        """Plan mode blocks mutating tools."""
        harness = Harness(
            provider=MockProvider(
                responses=[
                    LLMResponse(
                        content=None,
                        tool_calls=[
                            ToolCallRequest(
                                id="c1",
                                name="mutate",
                                arguments={"message": "change"},
                            )
                        ],
                    ),
                    LLMResponse(content="Cannot mutate in plan mode."),
                ],
            ),
            permissions="plan",
        )
        harness.tools.register(MutatingTool())
        agent = Agent(harness)

        msg = InboundMessage(
            channel="cli",
            sender_id="u1",
            chat_id="c1",
            content="change something",
        )
        result = await agent.process(msg)
        assert result is not None
        # The tool was blocked and the LLM handled it gracefully
        assert "Cannot mutate in plan mode" in result.content

    async def test_process_tool_not_found(self) -> None:
        """LLM calls a non-existent tool — error returned."""
        harness = Harness(
            provider=MockProvider(
                responses=[
                    LLMResponse(
                        content=None,
                        tool_calls=[
                            ToolCallRequest(
                                id="c1",
                                name="nonexistent",
                                arguments={},
                            )
                        ],
                    ),
                    LLMResponse(content="Tool not found."),
                ],
            ),
        )
        agent = Agent(harness)

        msg = InboundMessage(
            channel="cli",
            sender_id="u1",
            chat_id="c1",
            content="do something",
        )
        result = await agent.process(msg)
        assert result is not None
        assert "Tool not found" in result.content

    async def test_process_error_recovery(self) -> None:
        """Custom on_error handles exceptions gracefully."""
        async def custom_on_error(exc: Exception, ctx: str) -> str | None:
            return f"Recovered from error: {exc}"

        harness = Harness(
            provider=FailingProvider(),
            on_error=custom_on_error,
        )
        agent = Agent(harness)

        msg = InboundMessage(
            channel="cli", sender_id="u1", chat_id="c1", content="hi"
        )
        result = await agent.process(msg)
        assert result is not None
        assert "Recovered from error" in result.content
        assert "LLM API call failed" in result.content

    async def test_process_different_sessions_isolated(self, tmp_path: Path) -> None:
        """Different session keys have isolated history."""
        session_dir = tmp_path / "sessions"
        harness = Harness(
            provider=MockProvider(
                responses=[LLMResponse(content="Reply")]
            ),
            sessions=session_dir,
        )
        agent = Agent(harness)

        msg1 = InboundMessage(
            channel="cli", sender_id="u1", chat_id="c1", content="hello"
        )
        result1 = await agent.process(msg1)
        assert result1 is not None

        msg2 = InboundMessage(
            channel="cli", sender_id="u2", chat_id="c2", content="secret"
        )
        result2 = await agent.process(msg2)
        assert result2 is not None

        session1 = harness.sessions.get_or_create("cli:c1")
        session2 = harness.sessions.get_or_create("cli:c2")
        assert session1 is not session2

        # Each session should contain only its own user message
        user_msgs_1 = [m for m in session1.messages if m["role"] == "user"]
        user_msgs_2 = [m for m in session2.messages if m["role"] == "user"]
        assert any("hello" in m["content"] for m in user_msgs_1)
        assert any("secret" in m["content"] for m in user_msgs_2)
        assert not any("hello" in m["content"] for m in user_msgs_2)

    async def test_process_without_sessions(self) -> None:
        """Without sessions, process() still works — stateless."""
        harness = Harness(
            provider=MockProvider(
                responses=[LLMResponse(content="Stateless OK")]
            ),
        )
        agent = Agent(harness)

        msg = InboundMessage(
            channel="cli", sender_id="u1", chat_id="c1", content="hi"
        )
        result = await agent.process(msg)
        assert result is not None
        assert result.content == "Stateless OK"

    async def test_process_null_response(self) -> None:
        """When LLM returns None content, process returns None."""
        harness = Harness(
            provider=MockProvider(
                responses=[LLMResponse(content=None)]
            ),
        )
        agent = Agent(harness)

        msg = InboundMessage(
            channel="cli", sender_id="u1", chat_id="c1", content="hi"
        )
        result = await agent.process(msg)
        assert result is None
