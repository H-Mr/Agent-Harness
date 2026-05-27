"""Test Session.remove_before()."""

from agent_harness.session.manager import Session


def test_remove_before_removes_messages():
    s = Session(key="test:1")
    for i in range(10):
        s.add_message("user", f"msg {i}")
    assert len(s.messages) == 10

    removed = s.remove_before(6)
    assert removed == 6
    assert len(s.messages) == 4
    assert s.messages[0]["content"] == "msg 6"
    assert s.last_consolidated == 0


def test_remove_before_zero_does_nothing():
    s = Session(key="test:2")
    s.add_message("user", "hello")
    removed = s.remove_before(0)
    assert removed == 0
    assert len(s.messages) == 1


def test_remove_before_out_of_bounds_does_nothing():
    s = Session(key="test:3")
    s.add_message("user", "hello")
    removed = s.remove_before(10)
    assert removed == 0
    assert len(s.messages) == 1


def test_remove_before_with_last_consolidated():
    s = Session(key="test:4")
    s.add_message("user", "msg 0")
    s.add_message("user", "msg 1")
    s.last_consolidated = 1
    s.remove_before(1)
    assert s.last_consolidated == 0
