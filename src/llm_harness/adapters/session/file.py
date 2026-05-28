"""JSONL file-based session backend."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from llm_harness.adapters.session.backend import SessionBackend
from llm_harness.adapters._path_utils import resolve_safe_path

logger = logging.getLogger(__name__)


class FileSessionBackend:
    def __init__(self, base_dir: Path):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, session_key: str) -> Path:
        if ":" in session_key:
            account, _, session = session_key.partition(":")
        else:
            account, session = session_key, "default"
        account_dir = resolve_safe_path(self.base_dir, account)
        safe_session = resolve_safe_path(self.base_dir, session).name
        d = account_dir / "sessions" / safe_session
        d.mkdir(parents=True, exist_ok=True)
        return d / "session.jsonl"

    async def load(self, session_key: str) -> dict[str, Any] | None:
        path = self._path(session_key)
        if not path.exists():
            return None
        try:
            messages = []
            metadata = {}
            last_consolidated = 0
            with open(path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    data = json.loads(line)
                    if data.get("_type") == "metadata":
                        metadata = data.get("metadata", {})
                        last_consolidated = data.get("last_consolidated", 0)
                    else:
                        messages.append(data)
            return {"messages": messages, "metadata": metadata, "last_consolidated": last_consolidated}
        except Exception:
            logger.warning("Failed to load session %s", session_key, exc_info=True)
            return None

    async def save(self, session_key: str, state: dict[str, Any]) -> None:
        import os
        path = self._path(session_key)
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        meta = {"_type": "metadata", "key": session_key,
                "last_consolidated": state.get("last_consolidated", 0),
                "metadata": state.get("metadata", {})}
        lines = [json.dumps(meta, ensure_ascii=False)]
        for msg in state.get("messages", []):
            lines.append(json.dumps(msg, ensure_ascii=False))
        content = "\n".join(lines) + "\n"
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)

    async def list_keys(self) -> list[str]:
        keys = []
        for jsonl in self.base_dir.glob("*/sessions/*/session.jsonl"):
            try:
                with open(jsonl, encoding="utf-8") as f:
                    first = json.loads(f.readline().strip())
                if first.get("_type") == "metadata":
                    keys.append(first.get("key", jsonl.parent.name))
            except Exception:
                continue
        return keys
