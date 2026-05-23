"""Tests for multi-provider web search.

Adapted for agent-harness: WebSearchTool now uses individual constructor params
instead of a config object, and execute() takes a Pydantic input model.
"""

import importlib
from pathlib import Path

import httpx
import pytest

from agent_harness.tools.base import ToolExecutionContext
from agent_harness.tools.web import WebSearchInput, WebSearchTool


def _tool(provider: str = "brave", api_key: str = "", base_url: str = "") -> WebSearchTool:
    return WebSearchTool(provider=provider, api_key=api_key, base_url=base_url)


def _ctx() -> ToolExecutionContext:
    return ToolExecutionContext(cwd=Path.cwd())


def _response(status: int = 200, json: dict | None = None) -> httpx.Response:
    """Build a mock httpx.Response with a dummy request attached."""
    r = httpx.Response(status, json=json)
    r._request = httpx.Request("GET", "https://mock")
    return r


@pytest.mark.asyncio
async def test_brave_search(monkeypatch):
    async def mock_get(self, url, **kw):
        assert "brave" in url
        assert kw["headers"]["X-Subscription-Token"] == "brave-key"
        return _response(json={
            "web": {"results": [{"title": "NanoBot", "url": "https://example.com", "description": "AI assistant"}]}
        })

    monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)
    tool = _tool(provider="brave", api_key="brave-key")
    result = await tool.execute(WebSearchInput(query="nanobot", count=1), _ctx())
    assert "NanoBot" in result.output
    assert "https://example.com" in result.output


@pytest.mark.asyncio
async def test_tavily_search(monkeypatch):
    async def mock_post(self, url, **kw):
        assert "tavily" in url
        assert kw["headers"]["Authorization"] == "Bearer tavily-key"
        return _response(json={
            "results": [{"title": "OpenClaw", "url": "https://openclaw.io", "content": "Framework"}]
        })

    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)
    tool = _tool(provider="tavily", api_key="tavily-key")
    result = await tool.execute(WebSearchInput(query="openclaw"), _ctx())
    assert "OpenClaw" in result.output
    assert "https://openclaw.io" in result.output


@pytest.mark.asyncio
async def test_searxng_search(monkeypatch):
    async def mock_get(self, url, **kw):
        assert "searx.example" in url
        return _response(json={
            "results": [{"title": "Result", "url": "https://example.com", "content": "SearXNG result"}]
        })

    monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)
    tool = _tool(provider="searxng", base_url="https://searx.example")
    result = await tool.execute(WebSearchInput(query="test"), _ctx())
    assert "Result" in result.output


@pytest.mark.skipif(importlib.util.find_spec("ddgs") is None, reason="ddgs not installed")
@pytest.mark.asyncio
async def test_duckduckgo_search(monkeypatch):
    class MockDDGS:
        def __init__(self, **kw):
            pass

        def text(self, query, max_results=5):
            return [{"title": "DDG Result", "href": "https://ddg.example", "body": "From DuckDuckGo"}]

    import agent_harness.tools.web as web_mod

    monkeypatch.setattr(web_mod, "DDGS", MockDDGS, raising=False)

    tool = _tool(provider="duckduckgo")
    result = await tool.execute(WebSearchInput(query="hello"), _ctx())
    assert "DDG Result" in result.output


@pytest.mark.skipif(importlib.util.find_spec("ddgs") is None, reason="ddgs not installed")
@pytest.mark.asyncio
async def test_brave_fallback_to_duckduckgo_when_no_key(monkeypatch):
    class MockDDGS:
        def __init__(self, **kw):
            pass

        def text(self, query, max_results=5):
            return [{"title": "Fallback", "href": "https://ddg.example", "body": "DuckDuckGo fallback"}]

    import agent_harness.tools.web as web_mod
    monkeypatch.setattr(web_mod, "DDGS", MockDDGS, raising=False)
    monkeypatch.delenv("BRAVE_API_KEY", raising=False)

    tool = _tool(provider="brave", api_key="")
    result = await tool.execute(WebSearchInput(query="test"), _ctx())
    assert "Fallback" in result.output


@pytest.mark.asyncio
async def test_jina_search(monkeypatch):
    async def mock_get(self, url, **kw):
        assert "s.jina.ai" in str(url)
        assert kw["headers"]["Authorization"] == "Bearer jina-key"
        return _response(json={
            "data": [{"title": "Jina Result", "url": "https://jina.ai", "content": "AI search"}]
        })

    monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)
    tool = _tool(provider="jina", api_key="jina-key")
    result = await tool.execute(WebSearchInput(query="test"), _ctx())
    assert "Jina Result" in result.output
    assert "https://jina.ai" in result.output


@pytest.mark.asyncio
async def test_unknown_provider():
    tool = _tool(provider="unknown")
    result = await tool.execute(WebSearchInput(query="test"), _ctx())
    assert "unknown" in result.output
    assert "Error" in result.output


@pytest.mark.asyncio
async def test_default_provider_is_brave(monkeypatch):
    async def mock_get(self, url, **kw):
        assert "brave" in url
        return _response(json={"web": {"results": []}})

    monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)
    tool = _tool(provider="", api_key="test-key")
    result = await tool.execute(WebSearchInput(query="test"), _ctx())
    assert "No results" in result.output


@pytest.mark.skipif(importlib.util.find_spec("ddgs") is None, reason="ddgs not installed")
@pytest.mark.asyncio
async def test_searxng_no_base_url_falls_back(monkeypatch):
    class MockDDGS:
        def __init__(self, **kw):
            pass

        def text(self, query, max_results=5):
            return [{"title": "Fallback", "href": "https://ddg.example", "body": "fallback"}]

    import agent_harness.tools.web as web_mod
    monkeypatch.setattr(web_mod, "DDGS", MockDDGS, raising=False)
    monkeypatch.delenv("SEARXNG_BASE_URL", raising=False)

    tool = _tool(provider="searxng", base_url="")
    result = await tool.execute(WebSearchInput(query="test"), _ctx())
    assert "Fallback" in result.output


@pytest.mark.asyncio
async def test_searxng_invalid_url():
    tool = _tool(provider="searxng", base_url="not-a-url")
    result = await tool.execute(WebSearchInput(query="test"), _ctx())
    assert "Error" in result.output
