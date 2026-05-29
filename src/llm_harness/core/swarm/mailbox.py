"""File-based mailbox for leader-worker message passing."""

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)


class Mailbox:
    def __init__(self, base_dir: Path):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self._cursors: dict[str, str] = {}  # agent_id → last-read filename

    def put(self, agent_id: str, msg_type: str, payload: dict) -> None:
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
        rand_suffix = os.urandom(2).hex()
        inbox = self.base_dir / agent_id / "inbox"
        inbox.mkdir(parents=True, exist_ok=True)
        target = inbox / f"{ts}_{rand_suffix}_{msg_type}.json"
        tmp = inbox / f".tmp_{ts}_{rand_suffix}_{msg_type}.json"
        content = json.dumps({"type": msg_type, "payload": payload, "timestamp": ts})
        tmp.write_text(content)
        os.replace(tmp, target)  # atomic on POSIX, near-atomic on Windows

    def poll(self, agent_id: str) -> list[dict]:
        inbox = self.base_dir / agent_id / "inbox"
        if not inbox.exists():
            return []
        messages = []
        cursor = self._cursors.get(agent_id, "")
        for f in sorted(inbox.iterdir()):
            if f.suffix == ".json" and f.name > cursor:
                try:
                    messages.append(json.loads(f.read_text()))
                    self._cursors[agent_id] = f.name
                except Exception:
                    logger.warning("Failed to read mailbox message %s", f)
        return messages

    def ack(self, agent_id: str, count: int) -> None:
        """Delete the first *count* messages after the caller has processed them."""
        inbox = self.base_dir / agent_id / "inbox"
        if not inbox.exists():
            return
        for f in sorted(inbox.iterdir())[:count]:
            if f.suffix == ".json":
                try:
                    f.unlink()
                except Exception:
                    logger.warning("Failed to ack mailbox message %s", f)
