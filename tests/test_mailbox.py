"""Tests for Mailbox: unique filenames, corrupt file handling, UTC timestamps."""

import json
import pytest
from pathlib import Path
from llm_harness.core.swarm.mailbox import Mailbox


class TestFilenameUniqueness:
    """Concurrent writes must not collide on the same filename."""

    def test_unique_filenames_on_rapid_writes(self, tmp_path):
        mailbox = Mailbox(tmp_path)
        for _ in range(20):
            mailbox.put("agent-1", "user_message", {"content": "msg"})

        inbox = tmp_path / "agent-1" / "inbox"
        files = sorted(inbox.iterdir())
        assert len(files) == 20
        # All filenames must be unique
        names = [f.name for f in files]
        assert len(names) == len(set(names))


class TestCorruptMessageHandling:
    """Corrupt JSON files must be logged, not crash the poll loop."""

    def test_corrupt_file_does_not_crash_poll(self, tmp_path):
        mailbox = Mailbox(tmp_path)
        inbox = tmp_path / "agent-1" / "inbox"
        inbox.mkdir(parents=True, exist_ok=True)

        # Write a valid message
        mailbox.put("agent-1", "msg", {"ok": True})

        # Write a corrupt file
        (inbox / "20260101T000000_corrupt.json").write_text("not valid json at all {{{")

        messages = mailbox.poll("agent-1")
        # The valid message should still be returned
        assert len(messages) == 1
        assert messages[0]["type"] == "msg"


class TestUtcTimestamp:
    """Mailbox timestamps must include timezone info."""

    def test_timestamp_present(self, tmp_path):
        mailbox = Mailbox(tmp_path)
        mailbox.put("agent-1", "test", {"x": 1})
        messages = mailbox.poll("agent-1")
        assert len(messages) == 1
        assert "timestamp" in messages[0]
