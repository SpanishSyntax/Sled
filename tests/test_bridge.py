import inspect
import tempfile
from pathlib import Path
from typing import Any
from sled.tools.bridge import (
    KNOWN_BRIDGES,
    _make_bridge_handler,
    discover_bridged_tools,
    get_configured_bridges,
    list_bridge_statuses,
    query_remote_tools,
    toggle_bridge,
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


def test_zero_trust_default_is_empty():
    with tempfile.TemporaryDirectory() as tmpdir:
        fake_cfg = Path(tmpdir) / "sled.toml"
        fake_cfg.write_text("[store]\nenabled_packs = ['fs']\n", encoding="utf-8")

        # Zero-Trust by default: no bridges active unless explicitly enabled
        configured = get_configured_bridges(str(fake_cfg))
        assert configured == []

        discovered = discover_bridged_tools(bridges=configured)
        assert discovered == []


def test_toggle_bridge_activation():
    with tempfile.TemporaryDirectory() as tmpdir:
        fake_cfg = Path(tmpdir) / "sled.toml"
        fake_cfg.write_text("[store]\nenabled_packs = ['fs']\n", encoding="utf-8")

        # Enable skald bridge
        ok, msg = toggle_bridge("skald", enable=True, explicit_config=str(fake_cfg))
        assert ok is True
        assert "Activated bridge `skald`" in msg

        # Verify it is now in configured bridges
        bridges = get_configured_bridges(str(fake_cfg))
        assert len(bridges) == 1
        assert bridges[0]["name"] == "skald"

        # Disable skald bridge
        ok, msg = toggle_bridge("skald", enable=False, explicit_config=str(fake_cfg))
        assert ok is True
        assert "Deactivated bridge `skald`" in msg

        bridges = get_configured_bridges(str(fake_cfg))
        assert len(bridges) == 0


def test_skald_bridge_explicit_live():
    if not which_bin("skald"):
        return

    # Pass skald explicitly
    tools = discover_bridged_tools(bridges=[KNOWN_BRIDGES["skald"]])
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
