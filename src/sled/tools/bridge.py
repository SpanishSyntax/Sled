"""Dynamic MCP Tool Bridge & Subprocess Proxy for Sled.

Discovers and bridges standalone MCP-capable Frost/Iceberg CLI tools (e.g. `skald mcp`)
into Sled's atomic tool catalog without hardcoding domain-specific execution logic.
Adheres to the MCP JSON-RPC 2.0 stdio specification over single-turn subprocess execution.
"""

from __future__ import annotations

import inspect
import json
import logging
from typing import Any, Callable

from sled.tools import ToolSpec
from sled.tools._exec import run_cmd, which_bin

logger = logging.getLogger("sled.tools.bridge")

# Known external Iceberg applications supporting the standard `mcp` subcommand
DEFAULT_BRIDGED_COMMANDS: tuple[dict[str, Any], ...] = (
    {
        "binary": "skald",
        "cmd": ["skald", "mcp"],
        "pack": "icebergs",
    },
)

TYPE_MAP: dict[str, type] = {
    "string": str,
    "integer": int,
    "number": float,
    "boolean": bool,
    "array": list,
    "object": dict,
}


def _make_bridge_handler(cmd: list[str], tool_name: str, schema: dict[str, Any]) -> Callable[..., dict[str, Any]]:
    """Synthesize a typed callable handler that proxies tool execution over stdio JSON-RPC."""

    def handler(**kwargs: Any) -> dict[str, Any]:
        req = (
            json.dumps({
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": tool_name, "arguments": kwargs},
            })
            + "\n"
        )
        code, out, err = run_cmd(cmd, input_text=req, timeout=300.0)
        if code != 0:
            return {
                "status": "error",
                "error": err.strip() or f"Process {cmd[0]} failed with exit code {code}",
            }

        try:
            resp = json.loads(out.strip())
            if "result" in resp:
                content = resp["result"].get("content", [])
                if content and isinstance(content, list):
                    text_blocks = [c.get("text", "") for c in content if c.get("type") == "text"]
                    if text_blocks:
                        combined = "\n".join(text_blocks)
                        try:
                            parsed = json.loads(combined)
                            if isinstance(parsed, dict):
                                return parsed
                        except Exception:
                            return {"status": "ok", "output": combined}
                return resp["result"]
            if "error" in resp:
                err_msg = resp["error"].get("message", "Unknown error")
                return {"status": "error", "error": err_msg}
        except Exception as e:
            return {
                "status": "error",
                "error": f"Failed to parse JSON-RPC response from {cmd[0]}: {e}\nRaw output: {out[:500]}",
            }

        return {"status": "ok", "raw": out.strip()}

    # Construct dynamic function signature matching tool schema parameters
    properties: dict[str, Any] = schema.get("properties", {})
    required: set[str] = set(schema.get("required", []))
    params: list[inspect.Parameter] = []

    for p_name, p_info in properties.items():
        annotation = TYPE_MAP.get(p_info.get("type", ""), Any)
        default = p_info.get(
            "default",
            inspect.Parameter.empty if p_name in required else None,
        )
        params.append(
            inspect.Parameter(
                name=p_name,
                kind=inspect.Parameter.KEYWORD_ONLY,
                default=default,
                annotation=annotation,
            )
        )

    handler.__signature__ = inspect.Signature(parameters=params)
    handler.__doc__ = schema.get("description", f"Bridged tool from {cmd[0]}")
    handler.__name__ = tool_name
    return handler


def query_remote_tools(cmd: list[str]) -> list[dict[str, Any]]:
    """Query `tools/list` from an external MCP CLI command via stdio JSON-RPC."""
    req = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}) + "\n"
    code, out, err = run_cmd(cmd, input_text=req, timeout=15.0)
    if code != 0 or not out.strip():
        logger.warning("Failed to query tools/list from %s: exit=%d, err=%s", cmd, code, err.strip())
        return []

    try:
        data = json.loads(out.strip())
        tools = data.get("result", {}).get("tools", [])
        if isinstance(tools, list):
            return tools
    except Exception as e:
        logger.warning("Malformed tools/list response from %s: %s", cmd, e)
    return []


def get_configured_bridges() -> list[dict[str, Any]]:
    """Resolve bridge declarations filtered by user configuration in `sled.toml`."""
    try:
        from sled.tools import load_sled_config

        cfg = load_sled_config()
        bridges_sec = cfg.get("bridges", {}) if isinstance(cfg.get("bridges"), dict) else {}
    except Exception:
        bridges_sec = {}

    disabled = set(bridges_sec.get("disabled", []))
    enabled_whitelist = bridges_sec.get("enabled", None)

    active: list[dict[str, Any]] = []

    # 1. Built-in trusted iceberg bridges
    for b in DEFAULT_BRIDGED_COMMANDS:
        b_name = str(b.get("binary", ""))
        if b_name in disabled:
            continue
        if enabled_whitelist is not None and b_name not in enabled_whitelist:
            continue
        active.append(b)

    # 2. User-declared custom bridges in `sled.toml` ([bridges.custom.<name>])
    custom = bridges_sec.get("custom", {})
    if isinstance(custom, dict):
        for b_name, b_info in custom.items():
            if b_name in disabled:
                continue
            if enabled_whitelist is not None and b_name not in enabled_whitelist:
                continue
            if isinstance(b_info, dict) and "cmd" in b_info:
                active.append({
                    "binary": b_info.get("binary", b_info["cmd"][0]),
                    "cmd": b_info["cmd"],
                    "pack": b_info.get("pack", "icebergs"),
                })

    return active


def discover_bridged_tools(
    bridges: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None = None,
) -> list[ToolSpec]:
    """Inspect and bridge tools from all active external MCP CLI applications."""
    resolved_bridges = get_configured_bridges() if bridges is None else bridges
    specs: list[ToolSpec] = []
    for bridge in resolved_bridges:
        binary = bridge.get("binary")
        cmd = bridge.get("cmd", [])
        pack = bridge.get("pack", "icebergs")
        if not binary or not cmd:
            continue

        if not which_bin(binary):
            logger.debug("Bridge binary %s not found in PATH; skipping.", binary)
            continue

        tool_defs = query_remote_tools(cmd)
        for t_def in tool_defs:
            name = t_def.get("name")
            desc = t_def.get("description", "")
            schema = t_def.get("inputSchema", {})
            if not name:
                continue

            handler = _make_bridge_handler(cmd, name, schema)
            specs.append(
                ToolSpec(
                    name=name,
                    module="bridge",
                    description=desc,
                    handler=handler,
                    pack=pack,
                )
            )

    return specs


TOOLS: list[ToolSpec] = discover_bridged_tools()
