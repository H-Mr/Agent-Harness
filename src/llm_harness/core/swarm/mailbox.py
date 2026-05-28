"""File-based mailbox for leader-worker message passing."""

import json
from pathlib import Path


class Mailbox:
    def __init__(self, base_dir: Path):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def put(self, agent_id: str, msg_type: str, payload: dict) -> None:
        from datetime import datetime
        ts = datetime.now().strftime("%Y%m%dT%H%M%S%f")
        inbox = self.base_dir / agent_id / "inbox"
        inbox.mkdir(parents=True, exist_ok=True)
        (inbox / f"{ts}_{msg_type}.json").write_text(json.dumps({"type": msg_type, "payload": payload, "timestamp": ts}))

    def poll(self, agent_id: str) -> list[dict]:
        inbox = self.base_dir / agent_id / "inbox"
        if not inbox.exists():
            return []
        messages = []
        for f in sorted(inbox.iterdir()):
            if f.suffix == ".json":
                try:
                    messages.append(json.loads(f.read_text()))
                    f.unlink()
                except Exception:
                    pass
        return messages
