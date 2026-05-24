"""Tests for agent_harness.harness — Harness creation with shorthand forms."""

from __future__ import annotations

from pathlib import Path
from typing import Any, ClassVar

import pytest
from pydantic import BaseModel

from agent_harness.config.schema import ToolsConfig
from agent_harness.context.base import ContextBuilder, SectionProvider
from agent_harness.harness import Harness
from agent_harness.hooks.loader import HookRegistry
from agent_harness.memory.store import MemoryStore
from agent_harness.observability.tracker import Tracker
from agent_harness.permissions.checker import PermissionChecker
from agent_harness.permissions.modes import PermissionMode
from agent_harness.permissions.settings import PermissionSettings
from agent_harness.providers.base import LLMProvider, LLMResponse
from agent_harness.session.manager import SessionManager
from agent_harness.skills.registry import SkillRegistry
from agent_harness.tools.base import BaseTool, ToolExecutionContext, ToolRegistry, ToolResult


# ---------------------------------------------------------------------------
# Mock provider
# ---------------------------------------------------------------------------


class MockProvider(LLMProvider):
    """Provider that returns scripted responses."""

    def __init__(self, response_text: str = "Mock response") -> None:
        super().__init__()
        self.response_text = response_text

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
