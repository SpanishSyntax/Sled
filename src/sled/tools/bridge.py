"""Dynamic Decentralized MCP Tool Bridge & Subprocess Proxy for Sled.

Discovers bridge descriptor files (*.toml) across standard XDG / config locations
and bridges standalone MCP-capable CLI tools into Sled's atomic tool catalog without
hardcoding domain-specific execution logic or tool registries.

Zero-Trust Security Principle:
All discovered bridges are INACTIVE by default upon install.
A bridge is ONLY executed when explicitly activated by user action:
1. Listed in `[bridges].enabled` in `sled.toml`
2. Activated via CLI: `sled bridge enable <name>` or `sled enable <name>`
"""

from __future__ import annotations

import inspect
import json
import logging
import os
import tomllib
from collections.abc import Callable
from pathlib import Path
from typing import Any

from sled.tools import ToolSpec
from sled.tools._exec import run_cmd, which_bin

logger = logging.getLogger("sled.tools.bridge")

TYPE_MAP: dict[str, type] = {
    "string": str,
    "integer": int,
    "number": float,
    "boolean": bool,
    "array": list,
    "object": dict,
}


def get_bridge_search_paths() -> list[Path]:
    """Return standard search directory locations where bridge descriptors (*.toml) reside."""
    paths: list[Path] = []

    # 1. User config: ~/.config/sled/bridges/
    xdg_config = os.environ.get("XDG_CONFIG_HOME")
    base_config = Path(xdg_config) if xdg_config else Path.home() / ".config"
    paths.append(base_config / "sled" / "bridges")

    # 2. User data: ~/.local/share/sled/bridges/
    xdg_data = os.environ.get("XDG_DATA_HOME")
    base_data = Path(xdg_data) if xdg_data else Path.home() / ".local" / "share"
    paths.append(base_data / "sled" / "bridges")

    # 3. System & profile data: $XDG_DATA_DIRS/sled/bridges/
    raw_dirs = os.environ.get(
        "XDG_DATA_DIRS",
        "/run/current-system/sw/share:/etc/profiles/per-user/current/share:/usr/local/share:/usr/share",
    )
    for d in raw_dirs.split(":"):
        if d.strip():
            paths.append(Path(d.strip()) / "sled" / "bridges")

    # 4. Optional workspace-local overrides: .sled/bridges/
    cwd_bridges = Path.cwd() / ".sled" / "bridges"
    if cwd_bridges.is_dir():
        paths.append(cwd_bridges)

    return paths


def discover_bridge_manifests(explicit_config: str | None = None) -> dict[str, dict[str, Any]]:
    """Scan search paths for `*.toml` bridge descriptors without executing anything."""
    manifests: dict[str, dict[str, Any]] = {}

    # Scan directory paths
    for dir_path in get_bridge_search_paths():
        if not dir_path.is_dir():
            continue
        for f in sorted(dir_path.glob("*.toml")):
            try:
                with f.open("rb") as fp:
                    data = tomllib.load(fp)
                name = str(data.get("name") or f.stem).strip().lower()
                cmd = data.get("command") or data.get("cmd")
                if not cmd or not isinstance(cmd, (list, tuple)):
                    continue
                binary = str(data.get("binary") or cmd[0])
                manifests[name] = {
                    "name": name,
                    "binary": binary,
                    "cmd": [str(c) for c in cmd],
                    "pack": str(data.get("pack", "icebergs")),
                    "description": str(data.get("description", "")),
                    "manifest_path": str(f),
                }
            except Exception as exc:
                logger.warning("Failed to parse bridge descriptor %s: %s", f, exc)

    # Also check inline custom bridge definitions in `sled.toml` ([bridges.custom.<name>])
    try:
        from sled.tools import load_sled_config

        cfg = load_sled_config(explicit_config)
        bridges_sec = cfg.get("bridges", {}) if isinstance(cfg.get("bridges"), dict) else {}
        custom = bridges_sec.get("custom", {})
        if isinstance(custom, dict):
            for b_name, b_info in custom.items():
                if isinstance(b_info, dict) and "cmd" in b_info:
                    binary = b_info.get("binary", b_info["cmd"][0])
                    manifests[str(b_name).strip().lower()] = {
                        "name": str(b_name).strip().lower(),
                        "binary": binary,
                        "cmd": [str(c) for c in b_info["cmd"]],
                        "pack": str(b_info.get("pack", "icebergs")),
                        "description": str(b_info.get("description", f"Custom inline bridge for {b_name}")),
                        "manifest_path": "sled.toml [bridges.custom]",
                    }
    except Exception:
        pass

    return manifests


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
    """
    try:
        from sled.tools import load_sled_config

        cfg = load_sled_config(explicit_config)
        bridges_sec = cfg.get("bridges", {}) if isinstance(cfg.get("bridges"), dict) else {}
    except Exception:
        bridges_sec = {}

    enabled_whitelist = set(bridges_sec.get("enabled", []))
    disabled_blacklist = set(bridges_sec.get("disabled", []))

    if not enabled_whitelist:
        return []

    manifests = discover_bridge_manifests(explicit_config)
    active: list[dict[str, Any]] = []

    for name, bridge_info in manifests.items():
        if name in enabled_whitelist and name not in disabled_blacklist:
            active.append(bridge_info)

    return active


def list_bridge_statuses(explicit_config: str | None = None) -> list[dict[str, Any]]:
    """Return all discovered bridge descriptors with live installation & activation status."""
    try:
        from sled.tools import load_sled_config

        cfg = load_sled_config(explicit_config)
        bridges_sec = cfg.get("bridges", {}) if isinstance(cfg.get("bridges"), dict) else {}
    except Exception:
        bridges_sec = {}

    enabled_whitelist = set(bridges_sec.get("enabled", []))
    disabled_blacklist = set(bridges_sec.get("disabled", []))

    manifests = discover_bridge_manifests(explicit_config)
    records: list[dict[str, Any]] = []

    for name in sorted(manifests.keys()):
        info = manifests[name]
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
            "manifest_path": info.get("manifest_path", ""),
        })

    return records


def toggle_bridge(
    name: str, enable: bool = True, explicit_config: str | None = None
) -> tuple[bool, str]:
    """Explicitly activate or deactivate a discovered external bridge in `sled.toml`."""
    try:
        from sled.tools import get_config_path, load_sled_config

        cfg_path = get_config_path(explicit_config)
        cfg = load_sled_config(explicit_config)
    except Exception as e:
        return False, f"Failed to load config: {e}"

    clean_name = name.strip().lower()
    manifests = discover_bridge_manifests(explicit_config)

    if clean_name not in manifests:
        search_dirs = [str(p) for p in get_bridge_search_paths() if p.is_dir()]
        available = ", ".join(sorted(manifests.keys())) or "none found"
        return (
            False,
            (
                f"Bridge `{name}` not discovered. Available descriptors: [{available}].\n"
                f"Drop a `{clean_name}.toml` into ~/.config/sled/bridges/ to make it discoverable.\n"
                f"Active search paths: {', '.join(search_dirs) or 'none created yet'}"
            ),
        )

    bridges_sec = dict(cfg.get("bridges", {})) if isinstance(cfg.get("bridges"), dict) else {}
    enabled_set = set(bridges_sec.get("enabled", []))
    disabled_set = set(bridges_sec.get("disabled", []))

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
    from sled.tools import get_enabled_tools, save_enabled_tools

    current_tools = get_enabled_tools(explicit_config)
    save_enabled_tools(current_tools, explicit_config=explicit_config)

    # Persist [bridges] block
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
