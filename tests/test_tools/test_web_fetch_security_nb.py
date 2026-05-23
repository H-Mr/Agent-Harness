"""Tests for web_fetch SSRF protection.

Adapted for agent-harness: uses regex-based URL validation instead of DNS resolution.
Private IPs in URLs are blocked directly by the URL validator.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_harness.tools.base import ToolExecutionContext
from agent_harness.tools.web import WebFetchInput, WebFetchTool


@pytest.mark.asyncio
async def test_web_fetch_blocks_private_ip():
    """Private IP URLs are blocked by the regex-based validator."""
    tool = WebFetchTool()
    result = await tool.execute(
        WebFetchInput(url="http://169.254.169.254/computeMetadata/v1/"),
        ToolExecutionContext(cwd=Path.cwd()),
    )
    assert result.is_error
    data = json.loads(result.output)
    assert "error" in data
    assert "private" in data["error"].lower() or "blocked" in data["error"].lower()


@pytest.mark.asyncio
async def test_web_fetch_blocks_localhost():
    """Localhost URLs are blocked."""
    tool = WebFetchTool()
    result = await tool.execute(
        WebFetchInput(url="http://localhost/admin"),
        ToolExecutionContext(cwd=Path.cwd()),
    )
    assert result.is_error
    data = json.loads(result.output)
    assert "error" in data
