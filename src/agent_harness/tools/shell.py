"""Shell execution tool.

Ported from nanobot with interface adapted to agent-harness BaseTool.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import sys
from pathlib import Path
from typing import ClassVar
from urllib.parse import urlparse

from pydantic import BaseModel, Field

from agent_harness.tools.base import BaseTool, ToolExecutionContext, ToolResult

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Pydantic input model
# ---------------------------------------------------------------------------


class ExecInput(BaseModel):
    command: str = Field(description="The shell command to execute")
    working_dir: str | None = Field(default=None, description="Optional working directory")
    timeout: int = Field(default=60, ge=1, le=600, description="Timeout in seconds")


# ---------------------------------------------------------------------------
# Security stubs (inlined from nanobot.security.network)
# ---------------------------------------------------------------------------

_PRIVATE_IP_RE = re.compile(
    r"\b("
    r"10\.\d{1,3}\.\d{1,3}\.\d{1,3}"
    r"|172\.(1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}"
    r"|192\.168\.\d{1,3}\.\d{1,3}"
    r"|127\.\d{1,3}\.\d{1,3}\.\d{1,3}"
    r"|169\.254\.\d{1,3}\.\d{1,3}"
    r"|0\.0\.0\.0"
    r")\b"
)
_URL_RE = re.compile(r"https?://[^\s\"'`;|<>]+", re.IGNORECASE)


def contains_internal_url(command: str) -> bool:
    """Return True if the command string contains a URL targeting an internal/private address.

    Inlined stub performing basic private-IP and localhost detection on URL literals
    rather than full DNS resolution.
    """
    for m in _URL_RE.finditer(command):
        url = m.group(0)
        if _PRIVATE_IP_RE.search(url):
            return True
        hostname = urlparse(url).hostname
        if hostname and hostname.lower() in ("localhost", "127.0.0.1", "::1"):
            return True
    return False


# ---------------------------------------------------------------------------
# ExecTool
# ---------------------------------------------------------------------------


class ExecTool(BaseTool):
    """Tool to execute shell commands."""

    name: ClassVar[str] = "exec"
    description: ClassVar[str] = "Execute a shell command and return its output. Use with caution."
    input_model: ClassVar[type[BaseModel]] = ExecInput

    _MAX_TIMEOUT = 600
    _MAX_OUTPUT = 10_000

    def __init__(
        self,
        timeout: int = 60,
        working_dir: str | None = None,
        deny_patterns: list[str] | None = None,
        allow_patterns: list[str] | None = None,
        restrict_to_workspace: bool = False,
        path_append: str = "",
    ):
        self.timeout = timeout
        self.working_dir = working_dir
        self.deny_patterns = deny_patterns or [
            r"\brm\s+-[rf]{1,2}\b",          # rm -r, rm -rf, rm -fr
            r"\bdel\s+/[fq]\b",              # del /f, del /q
            r"\brmdir\s+/s\b",               # rmdir /s
            r"(?:^|[;&|]\s*)format\b",       # format (as standalone command only)
            r"\b(mkfs|diskpart)\b",          # disk operations
            r"\bdd\s+if=",                   # dd
            r">\s*/dev/sd",                  # write to disk
            r"\b(shutdown|reboot|poweroff)\b",  # system power
            r":\(\)\s*\{.*\};\s*:",          # fork bomb
        ]
        self.allow_patterns = allow_patterns or []
        self.restrict_to_workspace = restrict_to_workspace
        self.path_append = path_append

    async def execute(self, arguments: ExecInput, context: ToolExecutionContext) -> ToolResult:
        cwd = arguments.working_dir or self.working_dir or os.getcwd()
        guard_error = self._guard_command(arguments.command, cwd)
        if guard_error:
            return ToolResult(output=guard_error, is_error=True)

        effective_timeout = min(arguments.timeout, self._MAX_TIMEOUT)

        env = os.environ.copy()
        if self.path_append:
            env["PATH"] = env.get("PATH", "") + os.pathsep + self.path_append

        try:
            process = await asyncio.create_subprocess_shell(
                arguments.command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
                env=env,
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=effective_timeout,
                )
            except asyncio.TimeoutError:
                process.kill()
                try:
                    await asyncio.wait_for(process.wait(), timeout=5.0)
                except asyncio.TimeoutError:
                    pass
                finally:
                    if sys.platform != "win32":
                        try:
                            os.waitpid(process.pid, os.WNOHANG)
                        except (ProcessLookupError, ChildProcessError) as e:
                            logger.debug("Process already reaped or not found: %s", e)
                return ToolResult(output=f"Error: Command timed out after {effective_timeout} seconds", is_error=True)

            output_parts = []

            if stdout:
                output_parts.append(stdout.decode("utf-8", errors="replace"))

            if stderr:
                stderr_text = stderr.decode("utf-8", errors="replace")
                if stderr_text.strip():
                    output_parts.append(f"STDERR:\n{stderr_text}")

            output_parts.append(f"\nExit code: {process.returncode}")

            result = "\n".join(output_parts) if output_parts else "(no output)"

            # Head + tail truncation to preserve both start and end of output
            max_len = self._MAX_OUTPUT
            if len(result) > max_len:
                half = max_len // 2
                result = (
                    result[:half]
                    + f"\n\n... ({len(result) - max_len:,} chars truncated) ...\n\n"
                    + result[-half:]
                )

            return ToolResult(output=result)

        except Exception as e:
            return ToolResult(output=f"Error executing command: {str(e)}", is_error=True)

    def _guard_command(self, command: str, cwd: str) -> str | None:
        """Best-effort safety guard for potentially destructive commands."""
        cmd = command.strip()
        lower = cmd.lower()

        for pattern in self.deny_patterns:
            if re.search(pattern, lower):
                return "Error: Command blocked by safety guard (dangerous pattern detected)"

        if self.allow_patterns:
            if not any(re.search(p, lower) for p in self.allow_patterns):
                return "Error: Command blocked by safety guard (not in allowlist)"

        if contains_internal_url(cmd):
            return "Error: Command blocked by safety guard (internal/private URL detected)"

        if self.restrict_to_workspace:
            if "..\\" in cmd or "../" in cmd:
                return "Error: Command blocked by safety guard (path traversal detected)"

            cwd_path = Path(cwd).resolve()

            for raw in self._extract_absolute_paths(cmd):
                try:
                    expanded = os.path.expandvars(raw.strip())
                    p = Path(expanded).expanduser().resolve()
                except Exception:
                    continue
                if p.is_absolute() and cwd_path not in p.parents and p != cwd_path:
                    return "Error: Command blocked by safety guard (path outside working dir)"

        return None

    @staticmethod
    def _extract_absolute_paths(command: str) -> list[str]:
        win_paths = re.findall(r"[A-Za-z]:\\[^\s\"'|><;]+", command)   # Windows: C:\...
        posix_paths = re.findall(r"(?:^|[\s|>'\"])(/[^\s\"'>;|<]+)", command)  # POSIX: /absolute only
        home_paths = re.findall(r"(?:^|[\s|>'\"])(~[^\s\"'>;|<]*)", command)  # POSIX/Windows home shortcut: ~
        return win_paths + posix_paths + home_paths
