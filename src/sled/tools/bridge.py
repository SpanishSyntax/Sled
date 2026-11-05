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
# NOTE: Zero-Trust Security Policy: none of these are active by default upon install.
# Users must explicitly activate them via `sled.toml` ([bridges].enabled) or `sled bridge enable <name>`.
KNOWN_BRIDGES: dict[str, dict[str, Any]] = {
    "skald": {
        "name": "skald",
        "binary": "skald",
        "cmd": ["skald", "mcp"],
        "pack": "icebergs",
        "description": "Arctic oral companion & multi-chapter M4B audiobook compiler",
    },
}

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


def get_configured_bridges(explicit_config: str | None = None) -> list[dict[str, Any]]:
    """Resolve active external bridges.

    Zero-Trust Security Default:
    By default, NO external bridges are active out-of-the-box upon install.
    Bridges are ONLY activated when explicitly opted into by user action:
    1. Listed in `[bridges].enabled = [...]` in `sled.toml`
    2. Activated via CLI: `sled bridge enable <name>` or `sled enable <name>`
    3. Declared as a custom user bridge in `[bridges.custom.<name>]`
    """
    try:
        from sled.tools import load_sled_config

        cfg = load_sled_config(explicit_config)
        bridges_sec = cfg.get("bridges", {}) if isinstance(cfg.get("bridges"), dict) else {}
    except Exception:
        bridges_sec = {}

    enabled_whitelist = set(bridges_sec.get("enabled", []))
    disabled_blacklist = set(bridges_sec.get("disabled", []))

    active: list[dict[str, Any]] = []

    # 1. Known trusted Iceberg bridges - strictly opt-in via enabled_whitelist
    for name, bridge_info in KNOWN_BRIDGES.items():
        if name in enabled_whitelist and name not in disabled_blacklist:
            active.append(bridge_info)

    # 2. User-declared custom bridges in `sled.toml` ([bridges.custom.<name>])
    custom = bridges_sec.get("custom", {})
    if isinstance(custom, dict):
        for b_name, b_info in custom.items():
            if b_name in disabled_blacklist:
                continue
            if isinstance(b_info, dict) and "cmd" in b_info:
                active.append({
                    "name": b_name,
                    "binary": b_info.get("binary", b_info["cmd"][0]),
                    "cmd": b_info["cmd"],
                    "pack": b_info.get("pack", "icebergs"),
                    "description": b_info.get("description", f"Custom user bridge for {b_name}"),
                })

    return active


def list_bridge_statuses(explicit_config: str | None = None) -> list[dict[str, Any]]:
    """Return all known and custom bridge configurations with live runtime status."""
    try:
        from sled.tools import load_sled_config

        cfg = load_sled_config(explicit_config)
        bridges_sec = cfg.get("bridges", {}) if isinstance(cfg.get("bridges"), dict) else {}
    except Exception:
        bridges_sec = {}

    enabled_whitelist = set(bridges_sec.get("enabled", []))
    disabled_blacklist = set(bridges_sec.get("disabled", []))

    records: list[dict[str, Any]] = []

    # Known bridges
    for name, info in KNOWN_BRIDGES.items():
        bin_path = which_bin(info["binary"])
        is_installed = bin_path is not None
        is_enabled = name in enabled_whitelist and name not in disabled_blacklist

        status = "active" if (is_installed and is_enabled) else ("disabled" if is_installed else "not_installed")
        records.append({
            "name": name,
            "binary": info["binary"],
            "command": " ".join(info["cmd"]),
            "status": status,
            "installed": is_installed,
            "enabled": is_enabled,
            "pack": info.get("pack", "icebergs"),
            "description": info.get("description", ""),
        })

    # Custom bridges in sled.toml
    custom = bridges_sec.get("custom", {})
    if isinstance(custom, dict):
        for b_name, b_info in custom.items():
            if not isinstance(b_info, dict) or "cmd" not in b_info:
                continue
            binary = b_info.get("binary", b_info["cmd"][0])
            bin_path = which_bin(binary)
            is_installed = bin_path is not None
            is_enabled = b_name not in disabled_blacklist
            status = "active" if (is_installed and is_enabled) else ("disabled" if is_installed else "not_installed")

            records.append({
                "name": b_name,
                "binary": binary,
                "command": " ".join(b_info["cmd"]),
                "status": status,
                "installed": is_installed,
                "enabled": is_enabled,
                "pack": b_info.get("pack", "icebergs"),
                "description": b_info.get("description", "Custom user bridge"),
            })

    return records


def toggle_bridge(
    name: str, enable: bool = True, explicit_config: str | None = None
) -> tuple[bool, str]:
    """Explicitly activate or deactivate an external bridge in `sled.toml`."""
    try:
        from sled.tools import get_config_path, load_sled_config

        cfg_path = get_config_path(explicit_config)
        cfg = load_sled_config(explicit_config)
    except Exception as e:
        return False, f"Failed to load config: {e}"

    clean_name = name.strip().lower()
    bridges_sec = dict(cfg.get("bridges", {})) if isinstance(cfg.get("bridges"), dict) else {}
    custom_bridges = bridges_sec.get("custom", {})

    if clean_name not in KNOWN_BRIDGES and clean_name not in custom_bridges:
        available = ", ".join(list(KNOWN_BRIDGES.keys()) + list(custom_bridges.keys()))
        return False, f"Unknown bridge `{name}`. Available bridges: {available or 'none'}"

    enabled_list = [str(x).strip().lower() for x in bridges_sec.get("enabled", []) if str(x).strip()]
    disabled_list = [str(x).strip().lower() for x in bridges_sec.get("disabled", []) if str(x).strip()]

    enabled_set = set(enabled_list)
    disabled_set = set(disabled_list)

    if enable:
        enabled_set.add(clean_name)
        disabled_set.discard(clean_name)
    else:
        enabled_set.discard(clean_name)
        disabled_set.add(clean_name)

    bridges_sec["enabled"] = sorted(enabled_set)
    bridges_sec["disabled"] = sorted(disabled_set)
    cfg["bridges"] = bridges_sec

    # Save to sled.toml preserving other sections
    from sled.tools import save_enabled_tools, get_enabled_tools

    current_tools = get_enabled_tools(explicit_config)
    save_enabled_tools(current_tools, explicit_config=explicit_config)

    # Re-read and rewrite with updated bridges
    try:
        from sled.tools import _format_toml_value
        content = cfg_path.read_text(encoding="utf-8") if cfg_path.is_file() else ""
        lines: list[str] = []
        in_bridges = False
        for line in content.splitlines():
            if line.strip() == "[bridges]":
                in_bridges = True
                continue
            if in_bridges and line.startswith("["):
                in_bridges = False
            if not in_bridges:
                lines.append(line)

        # Append new [bridges] section
        lines.append("")
        lines.append("[bridges]")
        lines.append("enabled = [")
        for b in sorted(enabled_set):
            lines.append(f'  "{b}",')
        lines.append("]")
        if disabled_set:
            lines.append("disabled = [")
            for b in sorted(disabled_set):
                lines.append(f'  "{b}",')
            lines.append("]")
        for k, v in bridges_sec.items():
            if k not in ("enabled", "disabled"):
                lines.append(f"{k} = {_format_toml_value(v)}")

        cfg_path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")
    except Exception as exc:
        return False, f"Failed to persist bridge update to {cfg_path}: {exc}"

    verb = "Activated" if enable else "Deactivated"
    return True, f"{verb} bridge `{clean_name}` in {cfg_path}"


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
