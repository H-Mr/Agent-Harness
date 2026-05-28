"""Tests for channel is_allowed with dict config and validate_allow_from."""

import pytest
from unittest.mock import MagicMock
from llm_harness.extensions.channels.manager import ChannelManager


class TestIsAllowedDictConfig:
    """is_allowed must work with both dict and object configs."""

    def test_dict_config_allow_all(self):
        ch = _make_channel({"allow_from": ["*"]})
        assert ch.is_allowed("any_user") is True

    def test_dict_config_specific_user(self):
        ch = _make_channel({"allow_from": ["alice", "bob"]})
        assert ch.is_allowed("alice") is True
        assert ch.is_allowed("eve") is False

    def test_dict_config_empty_denies_all(self):
        ch = _make_channel({"allow_from": []})
        assert ch.is_allowed("any_user") is False

    def test_dict_config_missing_allow_from_denies_all(self):
        ch = _make_channel({})
        assert ch.is_allowed("any_user") is False

    def test_object_config_still_works(self):
        class ConfigObj:
            allow_from = ["*"]

        ch = _make_channel(ConfigObj())
        assert ch.is_allowed("any_user") is True


class TestValidateAllowFrom:
    """_validate_allow_from must detect empty allow_from in dict configs."""

    def test_empty_allow_from_raises_value_error(self):
        with pytest.raises(ValueError):
            ChannelManager(
                channel_types={"test": _make_test_channel_cls()},
                channels_config={"test": {"enabled": True, "allow_from": []}},
                bus=MagicMock(),
            )

    def test_missing_allow_from_raises_value_error(self):
        with pytest.raises(ValueError):
            ChannelManager(
                channel_types={"test": _make_test_channel_cls()},
                channels_config={"test": {"enabled": True}},
                bus=MagicMock(),
            )

    def test_allow_from_star_passes_validation(self):
        mgr = ChannelManager(
            channel_types={"test": _make_test_channel_cls()},
            channels_config={"test": {"enabled": True, "allow_from": ["*"]}},
            bus=MagicMock(),
        )
        assert "test" in mgr.channels


def _make_test_channel_cls():
    from llm_harness.extensions.channels.base import BaseChannel

    class TestChannel(BaseChannel):
        name = "test"
        display_name = "Test"

        async def start(self):
            self._running = True

        async def stop(self):
            self._running = False

        async def send(self, msg):
            pass

    return TestChannel


def _make_channel(config):
    cls = _make_test_channel_cls()
    return cls(config, MagicMock())
