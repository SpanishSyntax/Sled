"""Atomic tool and capability pack registry for Sled.

Sled organizes all built-in MCP primitives into two granularities:
1. **Packs** (`fs`, `git`, `system`, `docker`, `systemd`, `nixos`, `network`) — group related tools and display their member tools directly in the pack description.
2. **Atomic Tools** (`ls`, `cat`, `grep`, `git_status`, `ps`, `docker_ps`, `journalctl`, etc.) — every single tool can be searched, inspected, and enabled/disabled individually.
"""

from __future__ import annotations

import importlib
import inspect
import logging
import os
import pkgutil
import tomllib
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mcp.server import MCPServer

logger = logging.getLogger("sled.tools")


@dataclass(frozen=True)
class ToolSpec:
    name: str
    module: str
    description: str
    handler: Callable[..., Any]
    pack: str

    @property
    def signature_display(self) -> str:
        """Concise parameter signature string, e.g. `(path='.', all_files=False)`."""
        try:
            sig = inspect.signature(self.handler)
            parts: list[str] = []
            for p_name, param in sig.parameters.items():
                if param.default is inspect.Parameter.empty:
                    parts.append(p_name)
                else:
                    default_repr = repr(param.default)
                    parts.append(f"{p_name}={default_repr}")
            return f"({', '.join(parts)})"
        except (ValueError, TypeError):
            return "()"

    @property
    def param_names(self) -> tuple[str, ...]:
        try:
            return tuple(inspect.signature(self.handler).parameters.keys())
        except (ValueError, TypeError):
            return ()


@dataclass(frozen=True)
class PackSpec:
    id: str
    title: str
    icon: str
    description: str
    module: str
    tools: list[ToolSpec] = field(default_factory=list)


PACK_CATALOG: dict[str, dict[str, Any]] = {
    "fs": {
        "title": "Filesystem & Text",
        "icon": "📁",
        "description": "Atomic file and directory primitives",
    },
    "git": {
        "title": "Git Repository",
        "icon": "🌿",
        "description": "Repository status, commit log, diffs, branches, and revisions",
    },
    "system": {
        "title": "Host & Processes",
        "icon": "🖥️",
        "description": "Kernel/OS info, uptime, running processes, disk space, memory, and PATH lookup",
    },
    "docker": {
        "title": "Docker & Podman",
        "icon": "🐳",
        "description": "Container listing, logs, stats, images, volumes, networks, lifecycle, and compose",
    },
    "systemd": {
        "title": "Systemd & Journald",
        "icon": "🔧",
        "description": "System and user service units, status properties, lifecycle actions, and journalctl logs",
    },
    "nixos": {
        "title": "Nix, NixOS & Home Manager",
        "icon": "❄️",
        "description": "System/HM generations, flake metadata & outputs, nixpkgs search, nix eval, and store info",
    },
    "network": {
        "title": "Network & Sockets",
        "icon": "🌐",
        "description": "Network interfaces, routing table, listening TCP/UDP ports, ICMP ping, and Tailscale",
    },
    "dev": {
        "title": "Development & Languages",
        "icon": "🛠️",
        "description": "Code formatters, linters, static diagnostics, and language tooling from Frost",
    },
}


def get_all_pack_catalog(
    explicit_config: str | None = None,
) -> dict[str, dict[str, Any]]:
    """Return unified catalog of all packs: built-ins plus external manifest packs."""
    catalog: dict[str, dict[str, Any]] = {k: dict(v) for k, v in PACK_CATALOG.items()}
    for v in catalog.values():
        v.setdefault("provider", "builtin")

    try:
        from sled.tools.bridge import discover_bridge_manifests

        manifests = discover_bridge_manifests(explicit_config)
        for name, m in manifests.items():
            pack_id = m.get("pack", name)
            if pack_id not in catalog:
                title = name.capitalize()
                catalog[pack_id] = {
                    "title": title,
                    "icon": "⚡",
                    "description": m.get("description", f"Bridged pack for {title}"),
                    "provider": "stdio",
                    "binary": m.get("binary", name),
                }
    except Exception:
        pass

    return catalog


def get_config_path(explicit_path: str | None = None) -> Path:
    """Resolve the path to `sled.toml` (honoring explicit arg, SLED_CONFIG, or XDG_CONFIG_HOME)."""
    if explicit_path:
        return Path(explicit_path).expanduser()
    env_cfg = os.environ.get("SLED_CONFIG")
    if env_cfg:
        return Path(env_cfg).expanduser()
    xdg_config = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg_config) if xdg_config else Path.home() / ".config"
    return base / "sled" / "sled.toml"


def load_sled_config(explicit_path: str | None = None) -> dict[str, Any]:
    """Load full configuration dictionary from `sled.toml`."""
    cfg_path = get_config_path(explicit_path)
    if not cfg_path.is_file():
        return {}
    try:
        with cfg_path.open("rb") as f:
            data = tomllib.load(f)
        return data if isinstance(data, dict) else {}
    except (tomllib.TOMLDecodeError, OSError) as exc:
        logger.warning("Failed to parse %s: %s", cfg_path, exc)
        return {}


def discover_tool_modules() -> list[Any]:
    """Import and return all non-private tool submodules in `sled.tools`."""
    modules: list[Any] = []
    # Order modules according to PACK_CATALOG first, then alphabetical
    pack_order = {name: idx for idx, name in enumerate(PACK_CATALOG.keys())}
    iter_mods = [
        m for m in pkgutil.iter_modules(__path__) if not m.name.startswith("_")
    ]
    iter_mods.sort(key=lambda m: (pack_order.get(m.name, 999), m.name))

    for module_info in iter_mods:
        fq_name = f"{__name__}.{module_info.name}"
        try:
            mod = importlib.import_module(fq_name)
            modules.append(mod)
        except Exception:
            logger.exception("Failed to import tool module %s", fq_name)
    return modules


def _discover_all_tool_specs() -> list[ToolSpec]:
    """Return all registered ToolSpec objects across all modules."""
    specs: list[ToolSpec] = []
    for mod in discover_tool_modules():
        if mod.__name__.endswith(".bridge"):
            discover_fn = getattr(mod, "discover_bridged_tools", None)
            if callable(discover_fn):
                specs.extend(discover_fn())
                continue
        mod_specs = getattr(mod, "TOOLS", None)
        if isinstance(mod_specs, (list, tuple)):
            specs.extend(mod_specs)
    return specs


def get_all_tool_map() -> dict[str, ToolSpec]:
    """Return mapping of `tool_name -> ToolSpec` for all built-in tools."""
    return {spec.name: spec for spec in _discover_all_tool_specs()}


def get_enabled_tools(explicit_config: str | None = None) -> list[str]:
    """Return ordered list of enabled atomic tool names.

    Unified resolution in `sled.toml`:
    1. Checks both `[tools].enabled` and legacy `[store].enabled_tools`
    2. Checks both `[packs].enabled`, legacy `[store].enabled_packs`, and `[bridges].enabled`
    3. Respects `disabled` lists in `[tools]`, `[packs]`, and `[store]`
    4. Zero-trust: empty if no whitelist exists.
    """
    all_specs = _discover_all_tool_specs()
    known_names = {s.name for s in all_specs}
    data = load_sled_config(explicit_config)

    # Resolve tools section (unified [tools] or legacy [store])
    tools_sec = data.get("tools", {}) if isinstance(data.get("tools"), dict) else {}
    store_sec = data.get("store", {}) if isinstance(data.get("store"), dict) else {}
    packs_sec = data.get("packs", {}) if isinstance(data.get("packs"), dict) else {}
    bridges_sec = (
        data.get("bridges", {}) if isinstance(data.get("bridges"), dict) else {}
    )

    disabled_raw: list[Any] = []
    for sec, key in [
        (tools_sec, "disabled"),
        (store_sec, "disabled_tools"),
    ]:
        val = sec.get(key)
        if isinstance(val, list):
            disabled_raw.extend(val)

    disabled_tools = {str(t).strip().lower() for t in disabled_raw if str(t).strip()}

    disabled_packs_raw: list[Any] = []
    for sec, key in [
        (packs_sec, "disabled"),
        (store_sec, "disabled_packs"),
        (bridges_sec, "disabled"),
    ]:
        val = sec.get(key)
        if isinstance(val, list):
            disabled_packs_raw.extend(val)

    disabled_packs = {
        str(p).strip().lower() for p in disabled_packs_raw if str(p).strip()
    }

    # Enabled packs whitelist
    enabled_packs_raw: list[Any] = []
    for sec, key in [
        (packs_sec, "enabled"),
        (store_sec, "enabled_packs"),
        (bridges_sec, "enabled"),
    ]:
        val = sec.get(key)
        if isinstance(val, list):
            enabled_packs_raw.extend(val)

    active_packs = {
        str(p).strip().lower() for p in enabled_packs_raw if str(p).strip()
    } - disabled_packs

    # Explicit tools whitelist
    enabled_tools_raw: list[Any] = []
    has_explicit_tools = False
    for sec, key in [
        (tools_sec, "enabled"),
        (store_sec, "enabled_tools"),
    ]:
        val = sec.get(key)
        if isinstance(val, list):
            has_explicit_tools = True
            enabled_tools_raw.extend(val)

    explicit_tools = {
        str(t).strip().lower() for t in enabled_tools_raw if str(t).strip()
    } - disabled_tools

    if has_explicit_tools:
        # Include explicitly whitelisted tools, PLUS all tools belonging to any active pack
        return [
            s.name
            for s in all_specs
            if (s.name in explicit_tools or s.pack in active_packs)
            and s.name not in disabled_tools
        ]

    if active_packs:
        return [
            s.name
            for s in all_specs
            if s.pack in active_packs and s.name not in disabled_tools
        ]

    return []


def get_enabled_packs(explicit_config: str | None = None) -> list[str]:
    """Return list of pack IDs that currently have at least one enabled tool."""
    enabled_tools = set(get_enabled_tools(explicit_config))
    all_specs = _discover_all_tool_specs()
    catalog = get_all_pack_catalog(explicit_config)
    active_packs: list[str] = []
    for pack_id in catalog:
        pack_tools = [s.name for s in all_specs if s.pack == pack_id]
        if any(t in enabled_tools for t in pack_tools):
            active_packs.append(pack_id)
    return active_packs


def _format_toml_value(val: Any) -> str:
    if isinstance(val, bool):
        return "true" if val else "false"
    if isinstance(val, (int, float)):
        return str(val)
    if isinstance(val, str):
        escaped = val.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    if isinstance(val, (list, tuple)):
        if not val:
            return "[]"
        items = ", ".join(_format_toml_value(x) for x in val)
        return f"[{items}]"
    return f'"{val}"'


def save_enabled_tools(
    enabled_tools: Sequence[str], explicit_config: str | None = None
) -> Path:
    """Persist the exact list of enabled atomic tools and packs to `sled.toml`."""
    cfg_path = get_config_path(explicit_config)
    existing = load_sled_config(explicit_config)
    all_specs = _discover_all_tool_specs()
    known_names = {s.name for s in all_specs}
    catalog = get_all_pack_catalog(explicit_config)

    chosen_set = {
        str(t).strip().lower()
        for t in enabled_tools
        if str(t).strip().lower() in known_names
    }
    ordered_tools = [s.name for s in all_specs if s.name in chosen_set]

    active_packs: list[str] = []
    for pack_id in catalog:
        if any(s.name in chosen_set for s in all_specs if s.pack == pack_id):
            active_packs.append(pack_id)

    # Clean legacy [store] or preserve [general]
    existing.pop("store", None)
    existing.pop("bridges", None)

    existing["packs"] = {"enabled": active_packs}
    existing["tools"] = {"enabled": ordered_tools}

    lines: list[str] = [
        "# Sled MCP Unified Pack & Tool Configuration",
        "# Managed via `sled store`, `sled enable/disable`, or Home Manager",
        "",
        "[packs]",
        "enabled = [",
    ]
    for pack_id in active_packs:
        lines.append(f'  "{pack_id}",')
    lines.append("]")
    lines.append("")
    lines.append("[tools]")
    lines.append("enabled = [")
    for tool_name in ordered_tools:
        lines.append(f'  "{tool_name}",')
    lines.append("]")

    general_sec = existing.get("general")
    if isinstance(general_sec, dict) and general_sec:
        lines.append("")
        lines.append("[general]")
        for k, v in general_sec.items():
            lines.append(f"{k} = {_format_toml_value(v)}")

    for sec_name, sec_val in existing.items():
        if sec_name in ("packs", "tools", "general"):
            continue
        if isinstance(sec_val, dict) and sec_val:
            lines.append("")
            lines.append(f"[{sec_name}]")
            for k, v in sec_val.items():
                lines.append(f"{k} = {_format_toml_value(v)}")

    content = "\n".join(lines) + "\n"

    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    if cfg_path.is_symlink():
        try:
            resolved = cfg_path.resolve()
            if str(resolved).startswith("/nix/store/"):
                cfg_path.unlink()
        except OSError:
            cfg_path.unlink(missing_ok=True)

    cfg_path.write_text(content, encoding="utf-8")
    return cfg_path


def save_enabled_packs(
    enabled_packs: Sequence[str], explicit_config: str | None = None
) -> Path:
    """Enable all atomic tools belonging to `enabled_packs` and persist to `sled.toml`."""
    catalog = get_all_pack_catalog(explicit_config)
    pack_set = {
        str(p).strip().lower()
        for p in enabled_packs
        if str(p).strip().lower() in catalog
    }
    all_specs = _discover_all_tool_specs()
    tools_in_packs = [s.name for s in all_specs if s.pack in pack_set]
    return save_enabled_tools(tools_in_packs, explicit_config=explicit_config)


def list_tool_specs(
    only_enabled: bool = False, explicit_config: str | None = None
) -> list[ToolSpec]:
    """Return metadata for discovered atomic tools across `src/sled/tools/`."""
    all_specs = _discover_all_tool_specs()
    if not only_enabled:
        return all_specs
    enabled_set = set(get_enabled_tools(explicit_config))
    return [s for s in all_specs if s.name in enabled_set]


def list_pack_specs(
    explicit_config: str | None = None,
) -> list[tuple[PackSpec, int, int]]:
    """Return all store packs along with `(PackSpec, enabled_tool_count, total_tool_count)`."""
    enabled_tools = set(get_enabled_tools(explicit_config))
    all_tools = _discover_all_tool_specs()
    catalog = get_all_pack_catalog(explicit_config)

    tools_by_pack: dict[str, list[ToolSpec]] = {k: [] for k in catalog}
    for t in all_tools:
        tools_by_pack.setdefault(t.pack, []).append(t)

    result: list[tuple[PackSpec, int, int]] = []
    for pack_id, meta in catalog.items():
        p_tools = tools_by_pack.get(pack_id, [])
        en_count = sum(1 for t in p_tools if t.name in enabled_tools)
        spec = PackSpec(
            id=pack_id,
            title=meta["title"],
            icon=meta["icon"],
            description=meta["description"],
            module=pack_id,
            tools=p_tools,
        )
        result.append((spec, en_count, len(p_tools)))
    return result


def search_catalog(query: str, explicit_config: str | None = None) -> dict[str, Any]:
    """Search Sled's local packs and atomic tools by name, pack, parameters, or description."""
    q = query.strip().lower()
    tokens = [tok for tok in q.split() if tok]
    enabled_tools = set(get_enabled_tools(explicit_config))
    catalog = get_all_pack_catalog(explicit_config)

    matched_packs: list[dict[str, Any]] = []
    for spec, en_count, total_count in list_pack_specs(explicit_config):
        tool_names = [t.name for t in spec.tools]
        haystack = (
            f"{spec.id} {spec.title} {spec.description} {' '.join(tool_names)}".lower()
        )
        if not tokens or all(tok in haystack for tok in tokens):
            matched_packs.append(
                {
                    "id": spec.id,
                    "title": spec.title,
                    "icon": spec.icon,
                    "description": spec.description,
                    "enabled_tools": en_count,
                    "total_tools": total_count,
                    "tools": tool_names,
                }
            )

    scored_tools: list[tuple[int, ToolSpec]] = []
    for t in _discover_all_tool_specs():
        pack_meta = catalog.get(t.pack, {})
        pack_title = str(pack_meta.get("title", ""))
        params_str = " ".join(t.param_names)
        haystack = (
            f"{t.name} {t.pack} {pack_title} {t.description} {params_str}".lower()
        )
        if not tokens or all(tok in haystack for tok in tokens):
            score = 0
            if q == t.name.lower():
                score += 100
            elif t.name.lower().startswith(q):
                score += 60
            elif q in t.name.lower():
                score += 40
            if q == t.pack.lower():
                score += 30
            scored_tools.append((score, t))

    scored_tools.sort(key=lambda item: (-item[0], item[1].pack, item[1].name))
    matched_tools = [
        {
            "name": t.name,
            "pack": t.pack,
            "enabled": t.name in enabled_tools,
            "signature": f"{t.name}{t.signature_display}",
            "description": t.description,
        }
        for _, t in scored_tools
    ]

    return {
        "query": query,
        "pack_matches": matched_packs,
        "tool_matches": matched_tools,
    }


def register_all_tools(mcp: MCPServer, explicit_config: str | None = None) -> list[str]:
    """Register all enabled atomic tools with MCPServer."""
    enabled_set = set(get_enabled_tools(explicit_config))
    registered: list[str] = []
    for spec in _discover_all_tool_specs():
        if spec.name not in enabled_set:
            continue
        mcp.tool(name=spec.name, description=spec.description)(spec.handler)
        registered.append(spec.name)
    return registered
