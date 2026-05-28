"""Tool: WebSearchTool — search the web using configured provider."""

from __future__ import annotations

import asyncio
import html
import logging
import os
import re
from typing import Any, ClassVar

import httpx
from pydantic import BaseModel, Field

from llm_harness.core.tools.base import BaseTool, ToolExecutionContext, ToolResult

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Input model
# ---------------------------------------------------------------------------


class WebSearchInput(BaseModel):
    query: str = Field(description="Search query")
    count: int = Field(default=5, ge=1, le=10, description="Number of results")


# ---------------------------------------------------------------------------
# Constants & helpers inlined from agent-harness
# ---------------------------------------------------------------------------

USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_7_2) AppleWebKit/537.36"


def _strip_tags(text: str) -> str:
    """Remove HTML tags and decode entities."""
    text = re.sub(r"<script[\s\S]*?</script>", "", text, flags=re.I)
    text = re.sub(r"<style[\s\S]*?</style>", "", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    return html.unescape(text).strip()


def _normalize(text: str) -> str:
    """Normalize whitespace."""
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _format_results(query: str, items: list[dict[str, Any]], n: int) -> str:
    """Format provider results into shared plaintext output."""
    if not items:
        return f"No results for: {query}"
    lines = [f"Results for: {query}\n"]
    for i, item in enumerate(items[:n], 1):
        title = _normalize(_strip_tags(item.get("title", "")))
        snippet = _normalize(_strip_tags(item.get("content", "")))
        lines.append(f"{i}. {title}\n   {item.get('url', '')}")
        if snippet:
            lines.append(f"   {snippet}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# WebSearchTool
# ---------------------------------------------------------------------------


class WebSearchTool(BaseTool):
    """Search the web using configured provider."""

    name: ClassVar[str] = "web_search"
    description: ClassVar[str] = "Search the web. Returns titles, URLs, and snippets."
    input_model: ClassVar[type[BaseModel]] = WebSearchInput

    def __init__(
        self,
        provider: str = "brave",
        api_key: str | None = None,
        max_results: int = 5,
        base_url: str | None = None,
        proxy: str | None = None,
    ):
        self._provider = provider
        self._api_key = api_key
        self._max_results = max_results
        self._base_url = base_url
        self.proxy = proxy

    async def execute(self, arguments: WebSearchInput, context: ToolExecutionContext) -> ToolResult:
        provider = self._provider.strip().lower() or "brave"
        n = min(max(arguments.count, 1), 10)

        try:
            if provider == "duckduckgo":
                result = await self._search_duckduckgo(arguments.query, n)
            elif provider == "tavily":
                result = await self._search_tavily(arguments.query, n)
            elif provider == "searxng":
                result = await self._search_searxng(arguments.query, n)
            elif provider == "jina":
                result = await self._search_jina(arguments.query, n)
            elif provider == "brave":
                result = await self._search_brave(arguments.query, n)
            else:
                return ToolResult(output=f"Error: unknown search provider '{provider}'", is_error=True)
            return ToolResult(output=result)
        except Exception as e:
            return ToolResult(output=f"Error: {e}", is_error=True)

    async def _search_brave(self, query: str, n: int) -> str:
        api_key = self._api_key or os.environ.get("BRAVE_API_KEY", "")
        if not api_key:
            logger.warning("BRAVE_API_KEY not set, falling back to DuckDuckGo")
            return await self._search_duckduckgo(query, n)
        try:
            async with httpx.AsyncClient(proxy=self.proxy) as client:
                r = await client.get(
                    "https://api.search.brave.com/res/v1/web/search",
                    params={"q": query, "count": n},
                    headers={"Accept": "application/json", "X-Subscription-Token": api_key},
                    timeout=10.0,
                )
                r.raise_for_status()
            items = [
                {"title": x.get("title", ""), "url": x.get("url", ""), "content": x.get("description", "")}
                for x in r.json().get("web", {}).get("results", [])
            ]
            return _format_results(query, items, n)
        except Exception as e:
            return f"Error: {e}"

    async def _search_tavily(self, query: str, n: int) -> str:
        api_key = self._api_key or os.environ.get("TAVILY_API_KEY", "")
        if not api_key:
            logger.warning("TAVILY_API_KEY not set, falling back to DuckDuckGo")
            return await self._search_duckduckgo(query, n)
        try:
            async with httpx.AsyncClient(proxy=self.proxy) as client:
                r = await client.post(
                    "https://api.tavily.com/search",
                    headers={"Authorization": f"Bearer {api_key}"},
                    json={"query": query, "max_results": n},
                    timeout=15.0,
                )
                r.raise_for_status()
            return _format_results(query, r.json().get("results", []), n)
        except Exception as e:
            return f"Error: {e}"

    async def _search_searxng(self, query: str, n: int) -> str:
        base_url = (self._base_url or os.environ.get("SEARXNG_BASE_URL", "")).strip()
        if not base_url:
            logger.warning("SEARXNG_BASE_URL not set, falling back to DuckDuckGo")
            return await self._search_duckduckgo(query, n)
        endpoint = f"{base_url.rstrip('/')}/search"
        try:
            async with httpx.AsyncClient(proxy=self.proxy) as client:
                r = await client.get(
                    endpoint,
                    params={"q": query, "format": "json"},
                    headers={"User-Agent": USER_AGENT},
                    timeout=10.0,
                )
                r.raise_for_status()
            return _format_results(query, r.json().get("results", []), n)
        except Exception as e:
            return f"Error: {e}"

    async def _search_jina(self, query: str, n: int) -> str:
        api_key = self._api_key or os.environ.get("JINA_API_KEY", "")
        if not api_key:
            logger.warning("JINA_API_KEY not set, falling back to DuckDuckGo")
            return await self._search_duckduckgo(query, n)
        try:
            headers = {"Accept": "application/json", "Authorization": f"Bearer {api_key}"}
            async with httpx.AsyncClient(proxy=self.proxy) as client:
                r = await client.get(
                    "https://s.jina.ai/",
                    params={"q": query},
                    headers=headers,
                    timeout=15.0,
                )
                r.raise_for_status()
            data = r.json().get("data", [])[:n]
            items = [
                {"title": d.get("title", ""), "url": d.get("url", ""), "content": d.get("content", "")[:500]}
                for d in data
            ]
            return _format_results(query, items, n)
        except Exception as e:
            return f"Error: {e}"

    async def _search_duckduckgo(self, query: str, n: int) -> str:
        try:
            from ddgs import DDGS  # type: ignore[import-untyped]

            ddgs = DDGS(timeout=10)
            raw = await asyncio.to_thread(ddgs.text, query, max_results=n)
            if not raw:
                return f"No results for: {query}"
            items = [
                {"title": r.get("title", ""), "url": r.get("href", ""), "content": r.get("body", "")}
                for r in raw
            ]
            return _format_results(query, items, n)
        except Exception as e:
            logger.warning("DuckDuckGo search failed: %s", e)
            return f"Error: DuckDuckGo search failed ({e})"

    def is_read_only(self, arguments: WebSearchInput) -> bool:
        del arguments
        return True
