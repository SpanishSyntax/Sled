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
import urllib.parse
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx

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


def discover_bridge_manifests(
    explicit_config: str | None = None,
) -> dict[str, dict[str, Any]]:
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
                provider = str(data.get("provider", "stdio")).strip().lower()

                if provider in ("sse", "http"):
                    url = str(data.get("url") or data.get("endpoint", "")).strip()
                    if not url:
                        continue
                    manifests[name] = {
                        "name": name,
                        "provider": "sse",
                        "url": url,
                        "headers": data.get("headers", {}),
                        "pack": str(data.get("pack", name)),
                        "title": str(data.get("title", name.capitalize())),
                        "icon": str(data.get("icon", "⚡")),
                        "description": str(data.get("description", "")),
                        "manifest_path": str(f),
                    }
                    continue

                cmd = data.get("command") or data.get("cmd")
                if not cmd or not isinstance(cmd, (list, tuple)):
                    continue
                binary = str(data.get("binary") or cmd[0])
                manifests[name] = {
                    "name": name,
                    "provider": "stdio",
                    "binary": binary,
                    "cmd": [str(c) for c in cmd],
                    "pack": str(data.get("pack", name)),
                    "title": str(data.get("title", name.capitalize())),
                    "icon": str(data.get("icon", "⚡")),
                    "description": str(data.get("description", "")),
                    "manifest_path": str(f),
                }
            except Exception as exc:
                logger.warning("Failed to parse bridge descriptor %s: %s", f, exc)

    # Also check inline custom pack definitions in `sled.toml` ([packs.custom.<name>])
    try:
        from sled.tools import load_sled_config

        cfg = load_sled_config(explicit_config)
        packs_sec = cfg.get("packs", {}) if isinstance(cfg.get("packs"), dict) else {}
        custom = packs_sec.get("custom", {})
        if isinstance(custom, dict):
            for b_name, b_info in custom.items():
                if not isinstance(b_info, dict):
                    continue
                provider = str(b_info.get("provider", "stdio")).strip().lower()
                clean_n = str(b_name).strip().lower()

                if provider in ("sse", "http"):
                    url = str(b_info.get("url") or b_info.get("endpoint", "")).strip()
                    if url:
                        manifests[clean_n] = {
                            "name": clean_n,
                            "provider": "sse",
                            "url": url,
                            "headers": b_info.get("headers", {}),
                            "pack": str(b_info.get("pack", clean_n)),
                            "title": str(b_info.get("title", clean_n.capitalize())),
                            "icon": str(b_info.get("icon", "⚡")),
                            "description": str(
                                b_info.get(
                                    "description", f"Custom SSE pack for {b_name}"
                                )
                            ),
                            "manifest_path": "sled.toml [packs.custom]",
                        }
                    continue

                if "cmd" in b_info:
                    binary = b_info.get("binary", b_info["cmd"][0])
                    manifests[clean_n] = {
                        "name": clean_n,
                        "provider": "stdio",
                        "binary": binary,
                        "cmd": [str(c) for c in b_info["cmd"]],
                        "pack": str(b_info.get("pack", clean_n)),
                        "title": str(b_info.get("title", clean_n.capitalize())),
                        "icon": str(b_info.get("icon", "⚡")),
                        "description": str(
                            b_info.get(
                                "description", f"Custom inline pack for {b_name}"
                            )
                        ),
                        "manifest_path": "sled.toml [packs.custom]",
                    }
    except Exception:
        pass

    return manifests


def _make_bridge_handler(
    cmd: list[str], tool_name: str, schema: dict[str, Any]
) -> Callable[..., dict[str, Any]]:
    """Synthesize a typed callable handler that proxies tool execution over stdio JSON-RPC."""

    def handler(**kwargs: Any) -> dict[str, Any]:
        req = (
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {"name": tool_name, "arguments": kwargs},
                }
            )
            + "\n"
        )
        code, out, err = run_cmd(cmd, input_text=req, timeout=300.0)
        if code != 0:
            return {
                "status": "error",
                "error": err.strip()
                or f"Process {cmd[0]} failed with exit code {code}",
            }

        try:
            resp = json.loads(out.strip())
            if "result" in resp:
                content = resp["result"].get("content", [])
                if content and isinstance(content, list):
                    text_blocks = [
                        c.get("text", "") for c in content if c.get("type") == "text"
                    ]
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
        raw_type = p_info.get("type", "")
        if isinstance(raw_type, list):
            # Take the first non-null type from union: e.g. ["integer", "null"] -> "integer"
            non_nulls = [t for t in raw_type if t != "null"]
            type_str = non_nulls[0] if non_nulls else "string"
        else:
            type_str = str(raw_type)

        annotation = TYPE_MAP.get(type_str, Any)
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
        logger.warning(
            "Failed to query tools/list from %s: exit=%d, err=%s",
            cmd,
            code,
            err.strip(),
        )
        return []

    try:
        data = json.loads(out.strip())
        tools = data.get("result", {}).get("tools", [])
        if isinstance(tools, list):
            return tools
    except Exception as e:
        logger.warning("Malformed tools/list response from %s: %s", cmd, e)
    return []


def query_sse_tools(
    url: str, headers: dict[str, str] | None = None, timeout: float = 10.0
) -> tuple[str, list[dict[str, Any]]]:
    """Query `tools/list` from an MCP SSE / HTTP endpoint using httpx.

    Follows the MCP HTTP/SSE specification:
    1. First attempts direct JSON-RPC HTTP POST (standard / fast path).
    2. If that fails or requires handshake, performs GET streaming handshake to extract post endpoint.
    3. Issues JSON-RPC `tools/list` and returns `(post_endpoint, tools)`.
    """
    req_headers = {"Accept": "application/json, text/event-stream"}
    if headers:
        req_headers.update(headers)

    post_url = url
    rpc_payload = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}

    # Fast path: attempt direct JSON-RPC POST with httpx
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            resp = client.post(url, json=rpc_payload, headers=req_headers)
            if resp.status_code == 200:
                data = resp.json()
                tools = data.get("result", {}).get("tools", [])
                if isinstance(tools, list):
                    return url, tools
    except Exception:
        pass

    # SSE Handshake path: GET request to read event-stream endpoint declaration
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            with client.stream(
                "GET", url, headers={"Accept": "text/event-stream", **(headers or {})}
            ) as stream:
                line_count = 0
                for line in stream.iter_lines():
                    line_count += 1
                    if line_count > 30:
                        break
                    line = line.strip()
                    if line.startswith("event: endpoint"):
                        # Next line is data: <uri>
                        continue
                    if line.startswith("data:"):
                        endpoint_uri = line[5:].strip()
                        post_url = urllib.parse.urljoin(url, endpoint_uri)
                        break

            # Now issue tools/list to resolved post_url
            resp = client.post(
                post_url,
                json=rpc_payload,
                headers={"Content-Type": "application/json", **(headers or {})},
            )
            if resp.status_code == 200:
                data = resp.json()
                tools = data.get("result", {}).get("tools", [])
                if isinstance(tools, list):
                    return post_url, tools
    except Exception as e:
        logger.warning("Failed to query SSE tools from %s: %s", url, e)

    return post_url, []


def _make_sse_handler(
    post_url: str,
    tool_name: str,
    schema: dict[str, Any],
    headers: dict[str, str] | None = None,
) -> Callable[..., dict[str, Any]]:
    """Synthesize a typed callable handler that proxies tool execution to an HTTP/SSE endpoint via httpx."""

    def handler(**kwargs: Any) -> dict[str, Any]:
        rpc_body = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": kwargs},
        }
        post_headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if headers:
            post_headers.update(headers)

        try:
            with httpx.Client(timeout=60.0, follow_redirects=True) as client:
                resp = client.post(post_url, json=rpc_body, headers=post_headers)

                if resp.status_code != 200:
                    return {
                        "status": "error",
                        "error": f"HTTP {resp.status_code} from {post_url}: {resp.text[:500]}",
                    }

                data = resp.json()

                if "result" in data:
                    content = data["result"].get("content", [])
                    if content and isinstance(content, list):
                        text_blocks = [
                            c.get("text", "")
                            for c in content
                            if c.get("type") == "text"
                        ]
                        if text_blocks:
                            combined = "\n".join(text_blocks)
                            try:
                                parsed = json.loads(combined)
                                if isinstance(parsed, dict):
                                    return parsed
                            except Exception:
                                return {"status": "ok", "output": combined}
                    return data["result"]

                if "error" in data:
                    err_msg = data["error"].get("message", "Unknown error")
                    return {"status": "error", "error": err_msg}

                return {"status": "ok", "raw": resp.text}
        except httpx.HTTPStatusError as e:
            return {
                "status": "error",
                "error": f"HTTP {e.response.status_code} error from {post_url}: {e.response.text[:500]}",
            }
        except Exception as e:
            return {
                "status": "error",
                "error": f"Network error communicating with {post_url}: {e}",
            }

    # Construct dynamic function signature matching tool schema parameters
    properties: dict[str, Any] = schema.get("properties", {})
    required: set[str] = set(schema.get("required", []))
    params: list[inspect.Parameter] = []

    for p_name, p_info in properties.items():
        raw_type = p_info.get("type", "")
        if isinstance(raw_type, list):
            non_nulls = [t for t in raw_type if t != "null"]
            type_str = non_nulls[0] if non_nulls else "string"
        else:
            type_str = str(raw_type)

        annotation = TYPE_MAP.get(type_str, Any)
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
    handler.__doc__ = schema.get("description", f"SSE bridged tool from {post_url}")
    handler.__name__ = tool_name
    return handler


def get_configured_bridges(explicit_config: str | None = None) -> list[dict[str, Any]]:
    """Resolve active external bridges/packs from `[packs].enabled`."""
    try:
        from sled.tools import load_sled_config

        cfg = load_sled_config(explicit_config)
        packs_sec = cfg.get("packs", {}) if isinstance(cfg.get("packs"), dict) else {}
    except Exception:
        packs_sec = {}

    enabled_whitelist = set(packs_sec.get("enabled", []))
    disabled_blacklist = set(packs_sec.get("disabled", []))

    if not enabled_whitelist:
        return []

    manifests = discover_bridge_manifests(explicit_config)
    active: list[dict[str, Any]] = []

    for name, bridge_info in manifests.items():
        pack_name = bridge_info.get("pack", name)
        # Enabled if either bridge name or pack name is in the enabled packs list
        if (name in enabled_whitelist or pack_name in enabled_whitelist) and (
            name not in disabled_blacklist and pack_name not in disabled_blacklist
        ):
            active.append(bridge_info)

    return active


def list_bridge_statuses(explicit_config: str | None = None) -> list[dict[str, Any]]:
    """Return all discovered bridge descriptors with live installation & activation status."""
    try:
        from sled.tools import load_sled_config

        cfg = load_sled_config(explicit_config)
        packs_sec = cfg.get("packs", {}) if isinstance(cfg.get("packs"), dict) else {}
    except Exception:
        packs_sec = {}

    enabled_whitelist = set(packs_sec.get("enabled", []))
    disabled_blacklist = set(packs_sec.get("disabled", []))

    manifests = discover_bridge_manifests(explicit_config)
    records: list[dict[str, Any]] = []

    for name in sorted(manifests.keys()):
        info = manifests[name]
        pack_name = info.get("pack", name)
        provider = info.get("provider", "stdio")
        is_enabled = (name in enabled_whitelist or pack_name in enabled_whitelist) and (
            name not in disabled_blacklist and pack_name not in disabled_blacklist
        )

        if provider == "sse":
            is_installed = True
            status = "active" if is_enabled else "disabled"
            cmd_display = info.get("url", "SSE endpoint")
            bin_display = "http/sse"
        else:
            bin_path = which_bin(info.get("binary", ""))
            is_installed = bin_path is not None
            status = (
                "active"
                if (is_installed and is_enabled)
                else ("disabled" if is_installed else "not_installed")
            )
            cmd_display = " ".join(info.get("cmd", []))
            bin_display = info.get("binary", "")

        records.append(
            {
                "name": name,
                "provider": provider,
                "binary": bin_display,
                "command": cmd_display,
                "status": status,
                "installed": is_installed,
                "enabled": is_enabled,
                "pack": pack_name,
                "description": info.get("description", ""),
                "manifest_path": info.get("manifest_path", ""),
            }
        )

    return records


def toggle_bridge(
    name: str, enable: bool = True, explicit_config: str | None = None
) -> tuple[bool, str]:
    """Explicitly activate or deactivate a discovered pack/bridge in `sled.toml`."""
    try:
        from sled.tools import get_all_pack_catalog, get_config_path, load_sled_config

        cfg_path = get_config_path(explicit_config)
        cfg = load_sled_config(explicit_config)
        catalog = get_all_pack_catalog(explicit_config)
    except Exception as e:
        return False, f"Failed to load config: {e}"

    clean_name = name.strip().lower()
    manifests = discover_bridge_manifests(explicit_config)

    if clean_name not in manifests and clean_name not in catalog:
        search_dirs = [str(p) for p in get_bridge_search_paths() if p.is_dir()]
        available = ", ".join(
            sorted(set(list(manifests.keys()) + list(catalog.keys())))
        )
        return (
            False,
            (
                f"Pack `{name}` not discovered. Available: [{available}].\n"
                f"Drop a descriptor into ~/.config/sled/bridges/ to make it discoverable.\n"
                f"Active search paths: {', '.join(search_dirs) or 'none created yet'}"
            ),
        )

    # Use unified [packs] table
    packs_sec = dict(cfg.get("packs", {})) if isinstance(cfg.get("packs"), dict) else {}
    enabled_set = set(packs_sec.get("enabled", []))
    disabled_set = set(packs_sec.get("disabled", []))

    if enable:
        enabled_set.add(clean_name)
        disabled_set.discard(clean_name)
    else:
        enabled_set.discard(clean_name)
        disabled_set.add(clean_name)

    # Persist via save_enabled_tools keeping packs updated
    from sled.tools import get_enabled_tools, save_enabled_tools

    current_tools = get_enabled_tools(explicit_config)
    save_enabled_tools(current_tools, explicit_config=explicit_config)

    # Ensure packs.enabled has the newly toggled pack
    try:
        updated_cfg = load_sled_config(explicit_config)
        u_packs = dict(updated_cfg.get("packs", {}))
        u_enabled = set(u_packs.get("enabled", []))
        if enable:
            u_enabled.add(clean_name)
        else:
            u_enabled.discard(clean_name)
        u_packs["enabled"] = sorted(u_enabled)
        updated_cfg["packs"] = u_packs

        # Write clean TOML
        from sled.tools import _format_toml_value

        lines: list[str] = [
            "# Sled MCP Unified Pack & Tool Configuration",
            "# Managed via `sled store`, `sled enable/disable`, or Home Manager",
            "",
            "[packs]",
            "enabled = [",
        ]
        for p in sorted(u_enabled):
            lines.append(f'  "{p}",')
        lines.append("]")
        lines.append("")
        lines.append("[tools]")
        lines.append("enabled = [")
        for t in updated_cfg.get("tools", {}).get("enabled", []):
            lines.append(f'  "{t}",')
        lines.append("]")

        for sec_name, sec_val in updated_cfg.items():
            if sec_name in ("packs", "tools"):
                continue
            if isinstance(sec_val, dict) and sec_val:
                lines.append("")
                lines.append(f"[{sec_name}]")
                for k, v in sec_val.items():
                    lines.append(f"{k} = {_format_toml_value(v)}")

        cfg_path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")
    except Exception as exc:
        return False, f"Failed to persist pack update to {cfg_path}: {exc}"

    verb = "Activated" if enable else "Deactivated"
    return True, f"{verb} pack `{clean_name}` in {cfg_path}"


def get_bridge_cache_path() -> Path:
    """Return path to persistent local bridge tool definition cache."""
    xdg_cache = os.environ.get("XDG_CACHE_HOME")
    base_cache = Path(xdg_cache) if xdg_cache else Path.home() / ".cache"
    return base_cache / "sled" / "bridges_cache.json"


def load_bridge_cache() -> dict[str, Any]:
    """Load cached tool definitions for discovered bridges."""
    cache_file = get_bridge_cache_path()
    if not cache_file.is_file():
        return {}
    try:
        with cache_file.open("r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_bridge_cache(cache: dict[str, Any]) -> None:
    """Persist tool definitions cache to disk."""
    cache_file = get_bridge_cache_path()
    try:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        with cache_file.open("w", encoding="utf-8") as f:
            json.dump(cache, f, indent=2)
    except Exception as exc:
        logger.debug("Failed to write bridge cache to %s: %s", cache_file, exc)


def get_installed_bridges(explicit_config: str | None = None) -> list[dict[str, Any]]:
    """Return all discovered bridges whose binary is installed in PATH (or SSE endpoints)."""
    manifests = discover_bridge_manifests(explicit_config)
    installed: list[dict[str, Any]] = []
    for _name, bridge_info in manifests.items():
        provider = bridge_info.get("provider", "stdio")
        if provider == "sse":
            installed.append(bridge_info)
        else:
            binary = bridge_info.get("binary")
            if binary and which_bin(binary):
                installed.append(bridge_info)
    return installed


def get_bridge_tool_defs(
    bridge: dict[str, Any], cache: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    """Query or retrieve cached tool definitions for a single bridge."""
    name = bridge.get("name", "")
    provider = bridge.get("provider", "stdio")
    if provider == "sse":
        url = bridge.get("url")
        if not url:
            return []
        headers = bridge.get("headers", {})
        _, tool_defs = query_sse_tools(url, headers=headers)
        return tool_defs

    binary = bridge.get("binary")
    cmd = bridge.get("cmd", [])
    if not binary or not cmd:
        return []

    bin_path = which_bin(binary)
    if not bin_path:
        return []

    bin_mtime = 0.0
    try:
        bin_mtime = os.path.getmtime(bin_path)
    except OSError:
        pass

    manifest_path = bridge.get("manifest_path", "")
    man_mtime = 0.0
    if manifest_path and os.path.isfile(manifest_path):
        try:
            man_mtime = os.path.getmtime(manifest_path)
        except OSError:
            pass

    if cache is not None:
        cached_entry = cache.get(name)
        if (
            isinstance(cached_entry, dict)
            and cached_entry.get("bin_mtime") == bin_mtime
            and cached_entry.get("man_mtime") == man_mtime
            and isinstance(cached_entry.get("tools"), list)
        ):
            return cached_entry["tools"]

    tool_defs = query_remote_tools(cmd)
    if tool_defs and cache is not None:
        cache[name] = {
            "bin_path": bin_path,
            "bin_mtime": bin_mtime,
            "man_mtime": man_mtime,
            "tools": tool_defs,
        }
    return tool_defs


def discover_bridged_tools(
    bridges: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None = None,
) -> list[ToolSpec]:
    """Inspect and bridge tools from all installed external MCP CLI or SSE applications."""
    resolved_bridges = get_installed_bridges() if bridges is None else list(bridges)
    if not resolved_bridges:
        return []

    cache = load_bridge_cache()
    initial_cache_len = len(cache)
    cache_updated = False

    specs: list[ToolSpec] = []
    for bridge in resolved_bridges:
        pack = bridge.get("pack", bridge.get("name", "bridge"))
        provider = bridge.get("provider", "stdio")

        if provider == "sse":
            url = bridge.get("url")
            if not url:
                continue
            headers = bridge.get("headers", {})
            post_url, tool_defs = query_sse_tools(url, headers=headers)
            for t_def in tool_defs:
                name = t_def.get("name")
                desc = t_def.get("description", "")
                schema = t_def.get("inputSchema", {})
                if not name:
                    continue
                handler = _make_sse_handler(post_url, name, schema, headers=headers)
                specs.append(
                    ToolSpec(
                        name=name,
                        module="bridge",
                        description=desc,
                        handler=handler,
                        pack=pack,
                    )
                )
            continue

        cmd = bridge.get("cmd", [])
        if not cmd:
            continue

        before_entry = cache.get(bridge.get("name", ""))
        tool_defs = get_bridge_tool_defs(bridge, cache=cache)
        after_entry = cache.get(bridge.get("name", ""))
        if before_entry != after_entry:
            cache_updated = True

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

    if cache_updated or len(cache) != initial_cache_len:
        save_bridge_cache(cache)

    return specs


TOOLS: list[ToolSpec] = discover_bridged_tools()
