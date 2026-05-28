"""Tests for MCP client: dict config access, Optional types for params."""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from llm_harness.extensions.mcp.client import (
    _cfg_get,
    _create_model_from_schema,
    _normalize_schema_for_openai,
)


class TestCfgGet:
    """_cfg_get must extract values from both dict and object configs."""

    def test_dict_access(self):
        cfg = {"type": "stdio", "command": "python", "enabled_tools": ["a", "b"]}
        assert _cfg_get(cfg, "type") == "stdio"
        assert _cfg_get(cfg, "command") == "python"
        assert _cfg_get(cfg, "enabled_tools") == ["a", "b"]

    def test_dict_default_value(self):
        cfg = {"type": "stdio"}
        assert _cfg_get(cfg, "command") is None
        assert _cfg_get(cfg, "missing", "fallback") == "fallback"

    def test_object_access(self):
        class Cfg:
            type = "sse"
            url = "http://localhost:8080"

        cfg = Cfg()
        assert _cfg_get(cfg, "type") == "sse"
        assert _cfg_get(cfg, "url") == "http://localhost:8080"

    def test_object_default_value(self):
        class Cfg:
            type = "stdio"

        cfg = Cfg()
        assert _cfg_get(cfg, "missing", "fallback") == "fallback"


class TestOptionalParams:
    """Optional MCP params must use Optional[type], not raw type with None default."""

    def test_optional_param_is_optional_type(self):
        schema = {
            "type": "object",
            "properties": {
                "required_arg": {"type": "string"},
                "optional_arg": {"type": "string"},
            },
            "required": ["required_arg"],
        }
        normalized = _normalize_schema_for_openai(schema)
        model = _create_model_from_schema("test_tool", normalized)

        # Optional arg should accept None
        instance = model(required_arg="hello")
        assert instance.required_arg == "hello"
        assert instance.optional_arg is None

        # model_dump should NOT include None for unset optional fields by default
        dumped = instance.model_dump()
        assert dumped.get("required_arg") == "hello"

    def test_all_required_params(self):
        schema = {
            "type": "object",
            "properties": {
                "a": {"type": "string"},
                "b": {"type": "integer"},
            },
            "required": ["a", "b"],
        }
        normalized = _normalize_schema_for_openai(schema)
        model = _create_model_from_schema("test", normalized)

        instance = model(a="x", b=42)
        assert instance.a == "x"
        assert instance.b == 42
