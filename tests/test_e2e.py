"""End-to-end integration tests with a real LLM provider.

Requires environment variables:
  LLM_HARNESS_API_KEY   — API key
  LLM_HARNESS_MODEL     — model name (default: deepseek-v4-flash)
  LLM_HARNESS_API_BASE  — API base URL

Usage:
  LLM_HARNESS_API_KEY=sk-xxx LLM_HARNESS_MODEL=deepseek-v4-flash pytest tests/test_e2e.py -v -s

To skip (CI):
  LLM_HARNESS_E2E_SKIP=1 pytest tests/test_e2e.py
"""

import os
import tempfile
from pathlib import Path

import pytest

from llm_harness.adapters.providers.openai_compat_provider import OpenAICompatProvider
from llm_harness.adapters.sandbox.srt import SRTSandboxBackend
from llm_harness.core.agent import Agent
from llm_harness.core.bus.events import InboundMessage
from llm_harness.core.loop import AgentLoop
from llm_harness.core.session.session import Session
from llm_harness.core.tools.base import ToolRegistry
from llm_harness.core.tools.factory import ToolFactory

pytestmark = pytest.mark.skipif(
    os.environ.get("LLM_HARNESS_E2E_SKIP") == "1" or not os.environ.get("LLM_HARNESS_API_KEY"),
    reason="Set LLM_HARNESS_API_KEY to run E2E tests",
)


def _make_agent(sandbox):
    provider = OpenAICompatProvider(
        api_key=os.environ["LLM_HARNESS_API_KEY"],
        api_base=os.environ.get("LLM_HARNESS_API_BASE", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
    )
    model = os.environ.get("LLM_HARNESS_MODEL", "deepseek-v4-flash")
    factory = ToolFactory(sandbox=sandbox)
    tools = ToolRegistry()
    for name in ["read_file", "write_file", "exec", "glob", "web_search", "web_fetch"]:
        t = factory.build(name)
        if t:
            tools.register(t)
    loop = AgentLoop(
        provider=provider, tools=tools, model=model,
        on_build_context=lambda m, h: [
            {"role": "system", "content": "Reply concisely in Chinese."},
            {"role": "user", "content": m.content},
        ],
        on_tool_check=lambda n, t, a: type("OK", (), {"allowed": True})(),
        on_error=lambda e, c: None,
    )
    return Agent(loop=loop)


@pytest.fixture
def agent():
    sandbox = SRTSandboxBackend(Path(tempfile.mkdtemp()))
    return _make_agent(sandbox)


@pytest.fixture
def session():
    return Session(key="e2e:test")


@pytest.fixture
def cwd(agent):
    d = agent._loop._build_context
    ws = Path(tempfile.mkdtemp())
    p = ws / "e2e" / "sessions" / "test" / "files"
    p.mkdir(parents=True, exist_ok=True)
    return p


class TestE2E:
    @pytest.mark.asyncio
    async def test_simple_qa(self, agent, session, cwd):
        """A basic question gets a coherent response without tool use."""
        msg = InboundMessage("test", "alice", "e2e", "What is 2+2?")
        result = await agent.process(msg, session=session, cwd=cwd, account="alice")
        assert result.final_content is not None
        assert len(result.final_content) > 5
        assert len(session.messages) >= 2  # user + assistant

    @pytest.mark.asyncio
    async def test_file_tools(self, agent, session, cwd):
        """Write a file, then read it back using tools."""
        msg = InboundMessage(
            "test", "alice", "e2e",
            'Create a file named test.txt with content "hello from harness", then read it back with read_file.',
        )
        result = await agent.process(msg, session=session, cwd=cwd, account="alice")
        assert "write_file" in result.tools_used
        assert "read_file" in result.tools_used
        assert "hello from harness" in result.final_content.lower()

    @pytest.mark.asyncio
    async def test_multi_turn_context(self, agent, session, cwd):
        """Agent can maintain conversation across multiple turns."""
        r1 = await agent.process(
            InboundMessage("test", "alice", "e2e", "Count from 1 to 3: one"),
            session=session, cwd=cwd, account="alice",
        )
        r2 = await agent.process(
            InboundMessage("test", "alice", "e2e", "Continue counting from where we left off"),
            session=session, cwd=cwd, account="alice",
        )
        # Session should have messages from both turns
        assert len(session.messages) >= 4  # 2 user + 2 assistant

    @pytest.mark.asyncio
    async def test_agent_tool_isolation(self, agent, session, cwd):
        """File created in one session is NOT visible in another."""
        await agent.process(
            InboundMessage("test", "alice", "c1", "Create alias_file.txt with content secret123"),
            session=session, cwd=cwd, account="alice",
        )
        # Create a fresh sandbox + agent for session 2
        sandbox2 = SRTSandboxBackend(Path(tempfile.mkdtemp()))
        agent2 = _make_agent(sandbox2)
        session2 = Session(key="e2e:test2")
        cwd2 = sandbox2._root / "e2e" / "sessions" / "test2" / "files"
        cwd2.mkdir(parents=True, exist_ok=True)
        result = await agent2.process(
            InboundMessage("test", "bob", "c2", "Use glob to find any files here, then try reading alias_file.txt"),
            session=session2, cwd=cwd2, account="bob",
        )
        assert "secret123" not in result.final_content
