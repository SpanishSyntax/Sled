import inspect
import tempfile
from pathlib import Path

from sled.tools._exec import which_bin
from sled.tools.bridge import (
    _make_bridge_handler,
    discover_bridge_manifests,
    discover_bridged_tools,
    get_configured_bridges,
    query_remote_tools,
    toggle_bridge,
)


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


def test_manifest_discovery_and_toggle(monkeypatch):
    with tempfile.TemporaryDirectory() as tmpdir:
        work_dir = Path(tmpdir)
        bridges_dir = work_dir / "bridges"
        bridges_dir.mkdir()

        desc_file = bridges_dir / "my_app.toml"
        desc_file.write_text(
            'name = "my_app"\ncommand = ["my_app_bin", "mcp"]\ndescription = "Custom app"\n',
            encoding="utf-8",
        )

        fake_cfg = work_dir / "sled.toml"
        fake_cfg.write_text("[store]\nenabled_packs = ['fs']\n", encoding="utf-8")

        # Monkeypatch search paths to point to temp bridges directory
        monkeypatch.setattr(
            "sled.tools.bridge.get_bridge_search_paths",
            lambda: [bridges_dir],
        )

        manifests = discover_bridge_manifests(str(fake_cfg))
        assert "my_app" in manifests
        assert manifests["my_app"]["binary"] == "my_app_bin"
        assert manifests["my_app"]["cmd"] == ["my_app_bin", "mcp"]

        # Initially inactive (Zero-Trust)
        configured = get_configured_bridges(str(fake_cfg))
        assert len(configured) == 0

        # Activate via toggle_bridge
        ok, msg = toggle_bridge("my_app", enable=True, explicit_config=str(fake_cfg))
        assert ok is True
        assert "Activated pack `my_app`" in msg

        configured_after = get_configured_bridges(str(fake_cfg))
        assert len(configured_after) == 1
        assert configured_after[0]["name"] == "my_app"

        # Deactivate
        ok, msg = toggle_bridge("my_app", enable=False, explicit_config=str(fake_cfg))
        assert ok is True
        assert "Deactivated pack `my_app`" in msg
        assert len(get_configured_bridges(str(fake_cfg))) == 0


def test_skald_bridge_explicit_live():
    if not which_bin("skald"):
        return

    bridge_def = {
        "name": "skald",
        "binary": "skald",
        "cmd": ["skald", "mcp"],
        "pack": "icebergs",
    }
    tools = discover_bridged_tools(bridges=[bridge_def])
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


def test_sse_bridge_mock_server():
    import http.server
    import json
    import threading

    class MockMCPHandler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length).decode("utf-8"))
            method = body.get("method")
            if method == "tools/list":
                resp = {
                    "jsonrpc": "2.0",
                    "id": body.get("id"),
                    "result": {
                        "tools": [
                            {
                                "name": "mock_sse_tool",
                                "description": "Mock tool from SSE HTTP endpoint",
                                "inputSchema": {
                                    "type": "object",
                                    "properties": {
                                        "param": {
                                            "type": "string",
                                            "description": "A param",
                                        }
                                    },
                                    "required": ["param"],
                                },
                            }
                        ]
                    },
                }
            elif method == "tools/call":
                params = body.get("params", {})
                args = params.get("arguments", {})
                resp = {
                    "jsonrpc": "2.0",
                    "id": body.get("id"),
                    "result": {
                        "content": [
                            {
                                "type": "text",
                                "text": json.dumps(
                                    {
                                        "status": "ok",
                                        "echo": args.get("param"),
                                    }
                                ),
                            }
                        ]
                    },
                }
            else:
                resp = {
                    "jsonrpc": "2.0",
                    "id": body.get("id"),
                    "error": {"message": "unknown"},
                }

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(resp).encode("utf-8"))

        def log_message(self, format, *args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), MockMCPHandler)
    port = server.server_port
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()

    try:
        bridge_def = {
            "name": "remote_service",
            "provider": "sse",
            "url": f"http://127.0.0.1:{port}/mcp",
            "pack": "remote",
        }
        tools = discover_bridged_tools(bridges=[bridge_def])
        assert len(tools) == 1
        spec = tools[0]
        assert spec.name == "mock_sse_tool"
        assert spec.pack == "remote"

        # Execute mock SSE tool
        res = spec.handler(param="hello_sse")
        assert res.get("status") == "ok"
        assert res.get("echo") == "hello_sse"
    finally:
        server.shutdown()
        server.server_close()
