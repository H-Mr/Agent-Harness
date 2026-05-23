"""Tests for web fetch and search tools."""

from __future__ import annotations

import contextlib
import importlib.util
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

import pytest

from agent_harness.tools.base import ToolExecutionContext
from agent_harness.tools.web import WebFetchTool, WebFetchInput


def _mock_validate_ok(url: str) -> tuple[bool, str]:
    """Mock SSRF check that allows all URLs (for localhost testing)."""
    return True, ""


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        query = parse_qs(urlparse(self.path).query).get("q", [""])[0]
        if query:
            body = (
                "<html><body>"
                '<a class="result__a" href="https://example.com/docs">Agent Harness Docs</a>'
                '<div class="result__snippet">Search query was %s and docs were found.</div>'
                "</body></html>"
            ) % query
        else:
            body = "<html><body><h1>Agent Harness Test</h1><p>web fetch works</p></body></html>"
        encoded = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        del format, args


@pytest.mark.skipif(
    importlib.util.find_spec("readability") is None,
    reason="readability-lxml not installed",
)
@pytest.mark.asyncio
async def test_web_fetch_tool_reads_html(tmp_path, monkeypatch):
    import agent_harness.tools.web as web_mod

    monkeypatch.setattr(web_mod, "_validate_url_safe", _mock_validate_ok)
    monkeypatch.setattr(web_mod, "_validate_resolved_url", _mock_validate_ok)

    server = HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        result = await WebFetchTool().execute(
            WebFetchInput(url=f"http://127.0.0.1:{server.server_port}/"),
            ToolExecutionContext(cwd=tmp_path),
        )
    finally:
        server.shutdown()
        with contextlib.suppress(Exception):
            server.server_close()
        thread.join(timeout=1)

    assert result.is_error is False
    assert "Agent Harness Test" in result.output
    assert "web fetch works" in result.output


@pytest.mark.skip(reason="SSRF blocks external URLs; needs readability-lxml + network")
@pytest.mark.asyncio
async def test_web_fetch_tool_rejects_embedded_credentials(tmp_path):
    result = await WebFetchTool().execute(
        WebFetchInput(url="https://user:pass@example.com/"),
        ToolExecutionContext(cwd=tmp_path),
    )
    assert result.is_error is True
