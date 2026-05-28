"""File-based memory backend."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from llm_harness.adapters.memory.backend import (
    MEMORY_SECTION_MEMORY,
    MEMORY_SECTION_PERSONA,
    MEMORY_SECTION_RULES,
    MEMORY_SECTION_USER,
    MemoryBackend,
)

logger = logging.getLogger(__name__)

_SECTION_FILE_MAP = {
    MEMORY_SECTION_MEMORY: "MEMORY.md",
    MEMORY_SECTION_RULES: "AGENTS.md",
    MEMORY_SECTION_PERSONA: "SOUL.md",
    MEMORY_SECTION_USER: "USER.md",
}


class FileMemoryBackend:
    def __init__(self, base_dir: Path):
        self.base_dir = Path(base_dir)

    def _dir(self, namespace: str) -> Path:
        safe = namespace.replace(":", "_").replace("\\", "_").replace("/", "_")
        d = self.base_dir / safe
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _path(self, namespace: str, section: str) -> Path:
        name = _SECTION_FILE_MAP.get(section, f"{section}.md")
        return self._dir(namespace) / name

    async def get_context(self, namespace: str) -> str:
        blocks = []
        for section, filename in _SECTION_FILE_MAP.items():
            p = self._dir(namespace) / filename
            content = p.read_text(encoding="utf-8") if p.exists() else ""
            blocks.append(f"## {filename}\n{content}" if content else f"## {filename}\n(empty)")
        return "\n\n".join(blocks)

    async def read_section(self, namespace: str, section: str) -> str:
        p = self._path(namespace, section)
        return p.read_text(encoding="utf-8") if p.exists() else ""

    async def append_section(self, namespace: str, section: str, entry: str) -> None:
        p = self._path(namespace, section)
        with open(p, "a", encoding="utf-8") as f:
            f.write(entry.rstrip() + "\n\n")

    async def add_history(self, namespace: str, entry: str) -> None:
        p = self._dir(namespace) / "history.jsonl"
        import json as _json
        from datetime import datetime
        record = {"timestamp": datetime.now().isoformat(), "entry": entry}
        with open(p, "a", encoding="utf-8") as f:
            f.write(_json.dumps(record, ensure_ascii=False) + "\n")

    async def consolidate(
        self,
        namespace: str,
        messages: list[dict[str, Any]],
        provider: Any = None,
        model: str = "",
    ) -> bool:
        if not messages:
            return True
        if provider is None:
            return await self._raw_archive(namespace, messages)
        try:
            formatted = "\n".join(
                f"[{m.get('timestamp', '?')[:16]}] {m.get('role', '?').upper()}: {m.get('content', '')}"
                for m in messages
                if m.get("content")
            )
            prompt = f"""Process this conversation into structured memory.

## Current Memory State
### AGENTS.md
{await self.read_section(namespace, MEMORY_SECTION_RULES)}
### SOUL.md
{await self.read_section(namespace, MEMORY_SECTION_PERSONA)}
### MEMORY.md
{await self.read_section(namespace, MEMORY_SECTION_MEMORY)}
### USER.md
{await self.read_section(namespace, MEMORY_SECTION_USER)}

## Conversation
{formatted}"""
            chat = [
                {"role": "system", "content": "You are a memory consolidation agent."},
                {"role": "user", "content": prompt},
            ]
            tool = [
                {
                    "type": "function",
                    "function": {
                        "name": "save_memory",
                        "description": "Save structured memory.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "agents_update": {"type": ["string", "null"]},
                                "soul_update": {"type": ["string", "null"]},
                                "memory_update": {"type": "string"},
                                "user_update": {"type": ["string", "null"]},
                                "history_entry": {"type": "string"},
                            },
                            "required": ["memory_update", "history_entry"],
                        },
                    },
                }
            ]
            resp = await provider.chat_with_retry(
                messages=chat,
                tools=tool,
                model=model,
                tool_choice={"type": "function", "function": {"name": "save_memory"}},
            )
            if not resp.has_tool_calls:
                return await self._raw_archive(namespace, messages)
            args = resp.tool_calls[0].arguments
            if isinstance(args, str):
                args = json.loads(args)
            field_map = {
                "agents_update": MEMORY_SECTION_RULES,
                "soul_update": MEMORY_SECTION_PERSONA,
                "memory_update": MEMORY_SECTION_MEMORY,
                "user_update": MEMORY_SECTION_USER,
            }
            for field, section in field_map.items():
                val = args.get(field)
                if val and str(val).strip():
                    await self._write_section_content(namespace, section, str(val))
            hist = args.get("history_entry", "")
            if hist:
                await self.add_history(namespace, str(hist))
            return True
        except Exception:
            logger.exception("LLM consolidation failed")
            return await self._raw_archive(namespace, messages)

    async def _raw_archive(self, namespace: str, messages: list[dict]) -> bool:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M")
        content = "\n".join(
            f"[{ts}] [RAW] {m.get('role', '?')}: {m.get('content', '')}"
            for m in messages
            if m.get("content")
        )
        await self.add_history(namespace, content)
        return True

    async def _write_section_content(self, namespace: str, section: str, content: str) -> None:
        p = self._path(namespace, section)
        p.write_text(content, encoding="utf-8")
