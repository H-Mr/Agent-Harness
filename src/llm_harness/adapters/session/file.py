"""JSONL file-based session backend."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from llm_harness.adapters.session.backend import SessionBackend

logger = logging.getLogger(__name__)


class FileSessionBackend:
    def __init__(self, base_dir: Path):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, session_key: str) -> Path:
        import re
        safe = re.sub(r'[<>:"/\\|?*]', "_", session_key)
        return self.base_dir / f"{safe}.jsonl"

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
        path = self._path(session_key)
        with open(path, "w", encoding="utf-8") as f:
            meta = {"_type": "metadata", "key": session_key,
                    "last_consolidated": state.get("last_consolidated", 0),
                    "metadata": state.get("metadata", {})}
            f.write(json.dumps(meta, ensure_ascii=False) + "\n")
            for msg in state.get("messages", []):
                f.write(json.dumps(msg, ensure_ascii=False) + "\n")

    async def list_keys(self) -> list[str]:
        keys = []
        for p in self.base_dir.glob("*.jsonl"):
            try:
                with open(p, encoding="utf-8") as f:
                    first = json.loads(f.readline().strip())
                if first.get("_type") == "metadata":
                    keys.append(first.get("key", p.stem))
            except Exception:
                continue
        return keys
