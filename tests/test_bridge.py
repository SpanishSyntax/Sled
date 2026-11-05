import inspect
from typing import Any
from sled.tools.bridge import (
    _make_bridge_handler,
    discover_bridged_tools,
    query_remote_tools,
)
from sled.tools._exec import which_bin


def test_make_bridge_handler_signature():
    schema = {
        "description": "Test tool description",
        "properties": {
            "path": {"type": "string", "description": "Target path"},
            "count": {"type": "integer", "default": 10},
            "flag": {"type": "boolean", "default": False},
        },
        "required": ["path"],
    }
    handler = _make_bridge_handler(["dummy", "cmd"], "test_tool", schema)
    sig = inspect.signature(handler)
    params = sig.parameters

    assert "path" in params
    assert params["path"].default is inspect.Parameter.empty
    assert params["path"].annotation is str

    assert "count" in params
    assert params["count"].default == 10
    assert params["count"].annotation is int

    assert "flag" in params
    assert params["flag"].default is False
    assert params["flag"].annotation is bool

    assert handler.__name__ == "test_tool"
    assert handler.__doc__ == "Test tool description"


def test_query_remote_tools_missing_binary():
    res = query_remote_tools(["nonexistent_binary_xyz_123", "mcp"])
    assert res == []


def test_skald_bridge_live():
    if not which_bin("skald"):
        return

    tools = discover_bridged_tools()
    tool_names = [t.name for t in tools]

    assert "skald_narrate" in tool_names
    assert "skald_stitch" in tool_names
    assert "skald_voices" in tool_names
    assert "skald_inspect" in tool_names

    # Test executing skald_voices through dynamic bridge
    voices_spec = next(t for t in tools if t.name == "skald_voices")
    result = voices_spec.handler(limit=1)

    assert isinstance(result, dict)
    assert result.get("status") == "ok"
    assert "voices" in result
    assert len(result["voices"]) == 1
