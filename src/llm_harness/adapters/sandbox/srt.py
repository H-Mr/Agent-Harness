"""SRT-based sandbox — filesystem validation + OS-level enforcement via srt CLI.

Two-layer defence:
  1. Business logic: all file paths are resolved relative to workspace root
     and validated before any I/O.
  2. OS kernel: ``srt`` wraps subprocess execution with Seatbelt (macOS) or
     bubblewrap (Linux) so even a compromised process cannot escape.
"""

from __future__ import annotations

import asyncio
import logging
import re
from pathlib import Path

from llm_harness.adapters.sandbox.backend import ExecResult, SandboxSession

logger = logging.getLogger(__name__)

_SRT_DEFAULT_TIMEOUT = 60


class SRTSandboxBackend:
    """Sandbox that confines every file operation and subprocess to a workspace root.

    Parameters
    ----------
    workspace_root:
        Absolute path the backend is locked to.  All ``read_file`` / ``write_file`` /
        ``glob`` / ``grep`` paths are resolved relative to this root and rejected if
        they escape it.  Subprocesses are additionally wrapped with ``srt`` so the OS
        enforces the same boundary.
    """

    def __init__(self, workspace_root: str | Path) -> None:
        self._root = Path(workspace_root).expanduser().resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # session stubs — srt has no persistent session concept
    # ------------------------------------------------------------------

    async def create_session(self, session_key: str) -> SandboxSession:
        return SandboxSession(
            session_key=session_key,
            volume_path=str(self._root),
            sandbox_id="srt",
        )

    async def destroy_session(self, session_key: str) -> None:
        pass

    # ------------------------------------------------------------------
    # file operations — business-layer path enforcement
    # ------------------------------------------------------------------

    async def read_file(self, session_key: str, path: str) -> str:
        p = self._resolve(path)
        return p.read_text(encoding="utf-8") if p.is_file() else ""

    async def write_file(self, session_key: str, path: str, content: str) -> None:
        p = self._resolve(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")

    async def list_dir(self, session_key: str, path: str) -> list[str]:
        p = self._resolve(path)
        return [str(x.relative_to(p)) for x in p.iterdir()] if p.is_dir() else []

    async def glob(self, session_key: str, pattern: str) -> list[str]:
        if ".." in pattern:
            raise PermissionError(f"Path traversal in glob pattern: {pattern!r}")
        results = list(self._root.glob(pattern))
        return [str(r.relative_to(self._root)) for r in results]

    async def grep(self, session_key: str, pattern: str, path: str) -> list[str]:
        p = self._resolve(path)
        if p.is_file():
            return self._grep_file(p, pattern)
        if p.is_dir():
            results: list[str] = []
            for f in p.rglob("*"):
                if f.is_file():
                    results.extend(self._grep_file(f, pattern))
            return results
        return []

    @staticmethod
    def _grep_file(p: Path, pattern: str) -> list[str]:
        results: list[str] = []
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines()):
            if re.search(pattern, line):
                results.append(f"{i + 1}:{line}")
        return results

    # ------------------------------------------------------------------
    # subprocess — OS-layer enforcement via srt CLI
    # ------------------------------------------------------------------

    async def execute(
        self,
        session_key: str,
        command: str,
        *,
        cwd: str = "/workspace",
        env: dict | None = None,
        timeout: int = _SRT_DEFAULT_TIMEOUT,
    ) -> ExecResult:
        """Run *command* under ``srt`` so the OS enforces the workspace boundary."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "srt",
                f"--read={self._root}",
                f"--write={self._root}",
                "--",
                "sh",
                "-c",
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=cwd,
                env=env,
            )
            stdout, _ = await asyncio.wait_for(
                proc.communicate(), timeout=timeout,
            )
            return ExecResult(
                output=stdout.decode("utf-8", errors="replace") if stdout else "",
                exit_code=proc.returncode or 0,
                is_error=proc.returncode != 0,
            )
        except asyncio.TimeoutError:
            try:
                proc.kill()
                await proc.wait()
            except Exception:
                pass
            return ExecResult(output="Command timed out", exit_code=-1, is_error=True)
        except Exception as exc:
            return ExecResult(output=str(exc), exit_code=-1, is_error=True)

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    def _resolve(self, path: str) -> Path:
        p = (self._root / path).resolve()
        if not str(p).startswith(str(self._root)):
            raise PermissionError(f"Path traversal denied: {path!r}")
        return p
