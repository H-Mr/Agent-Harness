"""File system tools: read, write, edit, list.

Ported from nanobot with interface adapted to agent-harness BaseTool.
"""

from __future__ import annotations

import base64
import difflib
import json
import logging
import mimetypes
from pathlib import Path
from typing import Any, ClassVar

from pydantic import BaseModel, Field

from agent_harness.tools.base import BaseTool, ToolExecutionContext, ToolResult

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Pydantic input models
# ---------------------------------------------------------------------------


class ReadFileInput(BaseModel):
    path: str = Field(description="The file path to read")
    offset: int = Field(default=1, ge=1, description="Line number to start reading from (1-indexed)")
    limit: int = Field(default=2000, ge=1, description="Maximum number of lines to read")


class WriteFileInput(BaseModel):
    path: str = Field(description="The file path to write to")
    content: str = Field(description="The content to write")


class EditFileInput(BaseModel):
    path: str = Field(description="The file path to edit")
    old_text: str = Field(description="The text to find and replace")
    new_text: str = Field(description="The text to replace with")
    replace_all: bool = Field(default=False, description="Replace all occurrences")


class ListDirInput(BaseModel):
    path: str = Field(description="The directory path to list")
    recursive: bool = Field(default=False, description="Recursively list all files")
    max_entries: int = Field(default=200, ge=1, description="Maximum entries to return")


# ---------------------------------------------------------------------------
# Helpers inlined from nanobot.utils.helpers
# ---------------------------------------------------------------------------


def detect_image_mime(data: bytes) -> str | None:
    """Detect image MIME type from magic bytes, ignoring file extension."""
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def build_image_content_blocks(raw: bytes, mime: str, path: str, label: str) -> list[dict[str, Any]]:
    """Build native image blocks plus a short text label."""
    b64 = base64.b64encode(raw).decode()
    return [
        {
            "type": "image_url",
            "image_url": {"url": f"data:{mime};base64,{b64}"},
            "_meta": {"path": path},
        },
        {"type": "text", "text": label},
    ]


# ---------------------------------------------------------------------------
# Path resolution helpers (inlined from nanobot)
# ---------------------------------------------------------------------------


def _is_under(path: Path, directory: Path) -> bool:
    """Return True if *path* is under *directory*."""
    try:
        path.relative_to(directory.resolve())
        return True
    except ValueError:
        return False


def _resolve_path(
    path: str,
    workspace: Path | None = None,
    allowed_dir: Path | None = None,
    extra_allowed_dirs: list[Path] | None = None,
) -> Path:
    """Resolve path against workspace (if relative) and enforce directory restriction."""
    p = Path(path).expanduser()
    if not p.is_absolute() and workspace:
        p = workspace / p
    resolved = p.resolve()
    if allowed_dir:
        all_dirs = [allowed_dir] + (extra_allowed_dirs or [])
        if not any(_is_under(resolved, d) for d in all_dirs):
            raise PermissionError(f"Path {path} is outside allowed directory {allowed_dir}")
    return resolved


# ---------------------------------------------------------------------------
# Edit-file helper
# ---------------------------------------------------------------------------


def _find_match(content: str, old_text: str) -> tuple[str | None, int]:
    """Locate old_text in content: exact first, then line-trimmed sliding window.

    Both inputs should use LF line endings (caller normalises CRLF).
    Returns (matched_fragment, count) or (None, 0).
    """
    if old_text in content:
        return old_text, content.count(old_text)

    old_lines = old_text.splitlines()
    if not old_lines:
        return None, 0
    stripped_old = [l.strip() for l in old_lines]
    content_lines = content.splitlines()

    candidates = []
    for i in range(len(content_lines) - len(stripped_old) + 1):
        window = content_lines[i : i + len(stripped_old)]
        if [l.strip() for l in window] == stripped_old:
            candidates.append("\n".join(window))

    if candidates:
        return candidates[0], len(candidates)
    return None, 0


# ---------------------------------------------------------------------------
# FsTool base
# ---------------------------------------------------------------------------


class _FsTool(BaseTool):
    """Shared base for filesystem tools -- common init and path resolution."""

    def __init__(
        self,
        workspace: Path | None = None,
        allowed_dir: Path | None = None,
        extra_allowed_dirs: list[Path] | None = None,
    ):
        self._workspace = workspace
        self._allowed_dir = allowed_dir
        self._extra_allowed_dirs = extra_allowed_dirs

    def _resolve(self, path: str) -> Path:
        return _resolve_path(path, self._workspace, self._allowed_dir, self._extra_allowed_dirs)


# ---------------------------------------------------------------------------
# read_file
# ---------------------------------------------------------------------------


class ReadFileTool(_FsTool):
    """Read file contents with optional line-based pagination."""

    name: ClassVar[str] = "read_file"
    description: ClassVar[str] = (
        "Read the contents of a file. Returns numbered lines. "
        "Use offset and limit to paginate through large files."
    )
    input_model: ClassVar[type[BaseModel]] = ReadFileInput

    _MAX_CHARS = 128_000
    _DEFAULT_LIMIT = 2000

    async def execute(self, arguments: ReadFileInput, context: ToolExecutionContext) -> ToolResult:
        try:
            fp = self._resolve(arguments.path)
            if not fp.exists():
                return ToolResult(output=f"Error: File not found: {arguments.path}")
            if not fp.is_file():
                return ToolResult(output=f"Error: Not a file: {arguments.path}")

            raw = fp.read_bytes()
            if not raw:
                return ToolResult(output=f"(Empty file: {arguments.path})")

            mime = detect_image_mime(raw) or mimetypes.guess_type(arguments.path)[0]
            if mime and mime.startswith("image/"):
                blocks = build_image_content_blocks(raw, mime, str(fp), f"(Image file: {arguments.path})")
                return ToolResult(output=json.dumps(blocks))

            try:
                text_content = raw.decode("utf-8")
            except UnicodeDecodeError:
                return ToolResult(
                    output=(
                        f"Error: Cannot read binary file {arguments.path} "
                        f"(MIME: {mime or 'unknown'}). "
                        "Only UTF-8 text and images are supported."
                    ),
                    is_error=True,
                )

            all_lines = text_content.splitlines()
            total = len(all_lines)

            offset = arguments.offset
            limit = arguments.limit

            if offset < 1:
                offset = 1
            if offset > total:
                return ToolResult(output=f"Error: offset {offset} is beyond end of file ({total} lines)", is_error=True)

            start = offset - 1
            end = min(start + limit, total)
            numbered = [f"{start + i + 1}| {line}" for i, line in enumerate(all_lines[start:end])]
            result = "\n".join(numbered)

            if len(result) > self._MAX_CHARS:
                trimmed, chars = [], 0
                for line in numbered:
                    chars += len(line) + 1
                    if chars > self._MAX_CHARS:
                        break
                    trimmed.append(line)
                end = start + len(trimmed)
                result = "\n".join(trimmed)

            if end < total:
                result += f"\n\n(Showing lines {offset}-{end} of {total}. Use offset={end + 1} to continue.)"
            else:
                result += f"\n\n(End of file -- {total} lines total)"
            return ToolResult(output=result)
        except PermissionError as e:
            return ToolResult(output=f"Error: {e}", is_error=True)
        except Exception as e:
            return ToolResult(output=f"Error reading file: {e}", is_error=True)

    def is_read_only(self, arguments: ReadFileInput) -> bool:
        del arguments
        return True


# ---------------------------------------------------------------------------
# write_file
# ---------------------------------------------------------------------------


class WriteFileTool(_FsTool):
    """Write content to a file."""

    name: ClassVar[str] = "write_file"
    description: ClassVar[str] = "Write content to a file at the given path. Creates parent directories if needed."
    input_model: ClassVar[type[BaseModel]] = WriteFileInput

    async def execute(self, arguments: WriteFileInput, context: ToolExecutionContext) -> ToolResult:
        try:
            fp = self._resolve(arguments.path)
            fp.parent.mkdir(parents=True, exist_ok=True)
            fp.write_text(arguments.content, encoding="utf-8")
            return ToolResult(output=f"Successfully wrote {len(arguments.content)} bytes to {fp}")
        except PermissionError as e:
            return ToolResult(output=f"Error: {e}", is_error=True)
        except Exception as e:
            return ToolResult(output=f"Error writing file: {e}", is_error=True)


# ---------------------------------------------------------------------------
# edit_file
# ---------------------------------------------------------------------------


class EditFileTool(_FsTool):
    """Edit a file by replacing text with fallback matching."""

    name: ClassVar[str] = "edit_file"
    description: ClassVar[str] = (
        "Edit a file by replacing old_text with new_text. "
        "Supports minor whitespace/line-ending differences. "
        "Set replace_all=true to replace every occurrence."
    )
    input_model: ClassVar[type[BaseModel]] = EditFileInput

    async def execute(self, arguments: EditFileInput, context: ToolExecutionContext) -> ToolResult:
        try:
            fp = self._resolve(arguments.path)
            if not fp.exists():
                return ToolResult(output=f"Error: File not found: {arguments.path}", is_error=True)

            raw = fp.read_bytes()
            uses_crlf = b"\r\n" in raw
            content = raw.decode("utf-8").replace("\r\n", "\n")
            match, count = _find_match(content, arguments.old_text.replace("\r\n", "\n"))

            if match is None:
                return ToolResult(output=self._not_found_msg(arguments.old_text, content, arguments.path), is_error=True)
            if count > 1 and not arguments.replace_all:
                return ToolResult(
                    output=(
                        f"Warning: old_text appears {count} times. "
                        "Provide more context to make it unique, or set replace_all=true."
                    ),
                    is_error=True,
                )

            norm_new = arguments.new_text.replace("\r\n", "\n")
            new_content = content.replace(match, norm_new) if arguments.replace_all else content.replace(match, norm_new, 1)
            if uses_crlf:
                new_content = new_content.replace("\n", "\r\n")

            fp.write_bytes(new_content.encode("utf-8"))
            return ToolResult(output=f"Successfully edited {fp}")
        except PermissionError as e:
            return ToolResult(output=f"Error: {e}", is_error=True)
        except Exception as e:
            return ToolResult(output=f"Error editing file: {e}", is_error=True)

    @staticmethod
    def _not_found_msg(old_text: str, content: str, path: str) -> str:
        lines = content.splitlines(keepends=True)
        old_lines = old_text.splitlines(keepends=True)
        window = len(old_lines)

        best_ratio, best_start = 0.0, 0
        for i in range(max(1, len(lines) - window + 1)):
            ratio = difflib.SequenceMatcher(None, old_lines, lines[i : i + window]).ratio()
            if ratio > best_ratio:
                best_ratio, best_start = ratio, i

        if best_ratio > 0.5:
            diff = "\n".join(difflib.unified_diff(
                old_lines, lines[best_start : best_start + window],
                fromfile="old_text (provided)",
                tofile=f"{path} (actual, line {best_start + 1})",
                lineterm="",
            ))
            return f"Error: old_text not found in {path}.\nBest match ({best_ratio:.0%} similar) at line {best_start + 1}:\n{diff}"
        return f"Error: old_text not found in {path}. No similar text found. Verify the file content."


# ---------------------------------------------------------------------------
# list_dir
# ---------------------------------------------------------------------------


class ListDirTool(_FsTool):
    """List directory contents with optional recursion."""

    name: ClassVar[str] = "list_dir"
    description: ClassVar[str] = (
        "List the contents of a directory. "
        "Set recursive=true to explore nested structure. "
        "Common noise directories (.git, node_modules, __pycache__, etc.) are auto-ignored."
    )
    input_model: ClassVar[type[BaseModel]] = ListDirInput

    _DEFAULT_MAX = 200
    _IGNORE_DIRS = {
        ".git", "node_modules", "__pycache__", ".venv", "venv",
        "dist", "build", ".tox", ".mypy_cache", ".pytest_cache",
        ".ruff_cache", ".coverage", "htmlcov",
    }

    async def execute(self, arguments: ListDirInput, context: ToolExecutionContext) -> ToolResult:
        try:
            dp = self._resolve(arguments.path)
            if not dp.exists():
                return ToolResult(output=f"Error: Directory not found: {arguments.path}", is_error=True)
            if not dp.is_dir():
                return ToolResult(output=f"Error: Not a directory: {arguments.path}", is_error=True)

            cap = arguments.max_entries
            items: list[str] = []
            total = 0

            if arguments.recursive:
                for item in sorted(dp.rglob("*")):
                    if any(p in self._IGNORE_DIRS for p in item.parts):
                        continue
                    total += 1
                    if len(items) < cap:
                        rel = item.relative_to(dp)
                        items.append(f"{rel}/" if item.is_dir() else str(rel))
            else:
                for item in sorted(dp.iterdir()):
                    if item.name in self._IGNORE_DIRS:
                        continue
                    total += 1
                    if len(items) < cap:
                        pfx = "DIR " if item.is_dir() else "    "
                        items.append(f"{pfx}{item.name}")

            if not items and total == 0:
                return ToolResult(output=f"Directory {arguments.path} is empty")

            result = "\n".join(items)
            if total > cap:
                result += f"\n\n(truncated, showing first {cap} of {total} entries)"
            return ToolResult(output=result)
        except PermissionError as e:
            return ToolResult(output=f"Error: {e}", is_error=True)
        except Exception as e:
            return ToolResult(output=f"Error listing directory: {e}", is_error=True)

    def is_read_only(self, arguments: ListDirInput) -> bool:
        del arguments
        return True
