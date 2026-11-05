"""CLI entrypoint, dual-mode MCP Store (Packs & Atomic Tools), local search, and stdio MCP server bridge for Sled.

Strictly enforces MCP stdio stream discipline:
- In `serve` mode, `sys.stdout` is reserved exclusively for JSON-RPC 2.0 messages.
- All logging, diagnostics, and UI output in `serve` mode are routed to `sys.stderr`.
- When run interactively in a terminal (`sled` or `sled store`), renders the
  SpanishSyntax status dashboard, Pack/Tool store selector, and local tool search (`ui.py`).
"""

from __future__ import annotations

import argparse
import inspect
import json
import logging
import shutil
import sys
from collections.abc import Sequence
from typing import Any

from sled import __app_name__, __version__
from sled.tools import (
    get_all_tool_map,
    get_config_path,
    get_enabled_packs,
    get_enabled_tools,
    list_pack_specs,
    list_tool_specs,
    load_sled_config,
    register_all_tools,
    save_enabled_tools,
    search_catalog,
)
from sled.tools.git import git_status
from sled.tools.system import uname, uptime
from sled.ui import handle_color_args, ui


def configure_stderr_logging(level_name: str = "INFO") -> None:
    """Route all Python and SDK logging exclusively to `sys.stderr` to protect `sys.stdout`."""
    level = getattr(logging, level_name.upper(), logging.INFO)
    handler = logging.StreamHandler(stream=sys.stderr)
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)

    for logger_name in ("mcp", "fastmcp", "anyio", "httpx", "sled"):
        sub_logger = logging.getLogger(logger_name)
        sub_logger.handlers.clear()
        sub_logger.propagate = True


def load_user_config(explicit_path: str | None = None) -> dict[str, Any]:
    """Load optional user defaults from `~/.config/sled/sled.toml`."""
    data = load_sled_config(explicit_path)
    if isinstance(data.get("general"), dict):
        merged = dict(data)
        general = merged.pop("general")
        return {**general, **merged}
    return data


def print_help() -> None:
    """Print usage instructions matching Basecamp, Rime, Snowpack, Borealis, and Goggles."""
    if ui.is_agent:
        print(f"""Sled v{__version__} - NixOS Atomic MCP Store & Server Bridge
Usage: sled [command] [options]

Commands:
  serve [options]        Start MCP JSON-RPC 2.0 server over stdio
  status [--json]        Display live host, category summaries & tool telemetry
  tools [--all] [--json] List atomic MCP tools grouped by capability domain
  search <query>         Search built-in atomic tools locally
  store                  Interactive multiselect store
  run <tool> [k=v...]    Execute any built-in atomic tool directly
  enable <targets...>    Enable atomic tools or packs
  disable <targets...>   Disable atomic tools or packs
  hub-json               Print MCP Hub configuration snippet

Options:
  -A, --agent            Compact machine/agent friendly output mode
  --json                 Structured JSON output mode
  --toon                 Token-Oriented Object Notation (TOON) output mode
  -p, --pack PACK        Filter tools by category pack ID
  -c, --config PATH      Path to sled.toml configuration file
  --color MODE           Color output mode: auto, always, never
  --no-color             Disable colored output
  -v, --verbose          Verbose debug logging
  -V, --version          Show version number
  -h, --help             Show this help message
""")
        return

    print(
        f"""{ui.badge()} {ui.bold("NixOS Atomic MCP Store & Server Bridge")}

{ui.blue("Usage:")}
  sled                               Open interactive status dashboard & store menu
  sled store                         Interactive store (powered by Prism with live '/' search filter)
  sled tools [--all]                 List all atomic MCP tools grouped by capability domain
  sled search <query>                Search built-in atomic tools locally
  sled serve [options]               Start the MCP server over standard I/O (stdio)
  sled <command> [options]

{ui.blue("Store & Search Commands:")}
  store                Interactive multiselect store (powered by Prism with live '/' search filter)
  tools                List atomic MCP tools grouped by capability domain
  search <query>       Search Sled's built-in atomic tools by name, category, args, or description
  enable <target...>   Enable atomic tools or categories (e.g. `ls`, `cat`, `docker`)
  disable <target...>  Disable atomic tools or categories (e.g. `docker_action`)

{ui.blue("Server & Execution Commands:")}
  serve                Start MCP JSON-RPC 2.0 server over stdio (stdout=RPC, stderr=logs)
  status               Display live host, category summaries, and active atomic tool dashboard
  run <tool> [k=v...]  Execute any built-in atomic tool directly from the CLI
  hub-json             Print MCP Hub JSON config snippet for Antigravity, OpenCode & Claude

{ui.blue("Options:")}
  -p, --pack PACK            Filter `sled tools` by a specific category ID
  -i, --interactive          Open interactive store selector
  -s, --search QUERY         Pre-filter `sled store` with an initial search query
  --all                      Include disabled tools when running `sled tools`
  -c, --config PATH          Path to sled.toml configuration file
  --json                     Emit raw JSON output for CLI commands
  --log-level LEVEL          Stderr log verbosity: DEBUG, INFO, WARNING, ERROR (default: INFO)
  -v, --verbose              Shortcut for `--log-level DEBUG`
  --color MODE               Color output mode: auto, always, never (default: auto)
  --no-color                 Disable colored output
  -h, --help                 Show this help message and exit
  -V, --version              Show version and exit

{ui.blue("Examples:")}
  sled store                 # Open interactive tool store with live '/' search
  sled tools                 # View all enabled atomic MCP tools grouped by category
  sled tools --all           # View all 100+ atomic tools including disabled ones
  sled search log            # Search tools matching "log" (git_log, docker_logs, journalctl)
  sled enable ls cat grep    # Enable specific atomic tools via CLI
  sled run ls path=.         # Run the `ls` atomic tool directly in terminal
""",
        file=ui.stream,
    )


def create_mcp_server(explicit_config: str | None = None):
    """Instantiate MCPServer and register all enabled atomic tools under `src/sled/tools/`."""
    try:
        from mcp.server import MCPServer
    except ImportError:
        try:
            from mcp.server.fastmcp import FastMCP as MCPServer
        except ImportError:
            from mcp.server.mcpserver import MCPServer

    enabled_packs = get_enabled_packs(explicit_config)
    enabled_tools = get_enabled_tools(explicit_config)
    mcp = MCPServer(
        name="Sled",
        instructions=(
            "Sled is the NixOS Model Context Protocol (MCP) Server Bridge providing atomic Unix, "
            "Git, System, Docker, Systemd, NixOS, and Network primitives. "
            f"Active packs: {', '.join(enabled_packs)}. "
            f"Active atomic tools ({len(enabled_tools)}): {', '.join(enabled_tools)}."
        ),
    )
    registered = register_all_tools(mcp, explicit_config=explicit_config)
    logging.getLogger("sled.main").info(
        "Registered %d atomic MCP tools across packs [%s]: %s",
        len(registered),
        ", ".join(enabled_packs),
        ", ".join(registered),
    )
    return mcp


def run_stdio_server(
    log_level: str = "INFO", explicit_config: str | None = None
) -> int:
    """Start the MCP server over stdio with strict stdout/stderr separation."""
    ui.set_stream(sys.stderr)
    configure_stderr_logging(log_level)
    logger = logging.getLogger("sled.main")

    logger.info("Starting Sled MCP bridge v%s over stdio", __version__)
    try:
        mcp = create_mcp_server(explicit_config=explicit_config)
        mcp.run(transport="stdio")
        return 0
    except KeyboardInterrupt:
        logger.info("Sled MCP server stopped via SIGINT")
        return 0
    except Exception:
        logger.exception("Fatal error in Sled stdio server")
        return 1


def render_store_interactive(
    initial_mode: str = "tools",
    initial_query: str = "",
    explicit_config: str | None = None,
) -> int:
    """Launch interactive tool store selector powered by Prism multiselect."""
    all_tools = list_tool_specs(only_enabled=False, explicit_config=explicit_config)
    enabled_tools = get_enabled_tools(explicit_config)

    from sled.tools import get_all_pack_catalog

    catalog = get_all_pack_catalog(explicit_config)

    options = [
        (
            t.name,
            f"{catalog.get(t.pack, {}).get('icon', '⚡')} {t.name:<22} [{t.pack}]",
            t.description,
        )
        for t in all_tools
    ]

    chosen_tools = ui.multiselect(
        "Sled Atomic MCP Tools Store",
        options=options,
        preselected=enabled_tools,
        searchable=True,
    )

    saved_path = save_enabled_tools(chosen_tools, explicit_config=explicit_config)
    active_packs = get_enabled_packs(explicit_config)

    ui.success(
        f"Saved {len(chosen_tools)}/{len(all_tools)} atomic tool(s) across {len(active_packs)} pack(s) -> {saved_path}"
    )
    return 0


def _emit_toon(data: Any) -> None:
    if hasattr(ui, "toon"):
        ui.toon(data)
    else:
        try:
            from prism.toon import encode_toon

            print(encode_toon(data))
        except ImportError:
            print(json.dumps(data, indent=2))


def render_tools_panel(
    as_json: bool = False,
    as_toon: bool = False,
    include_disabled: bool = False,
    pack_filter: str | None = None,
    explicit_config: str | None = None,
) -> int:
    """Render all atomic MCP tools in a clean, spacious tabular layout grouped by category."""
    pack_specs = list_pack_specs(explicit_config)
    all_specs = list_tool_specs(only_enabled=False, explicit_config=explicit_config)
    enabled_set = set(get_enabled_tools(explicit_config))

    if pack_filter:
        pf = pack_filter.strip().lower()
        pack_specs = [p for p in pack_specs if p[0].id == pf]

    if as_toon or getattr(ui, "is_toon", False):
        tools_to_emit = [
            s
            for s in all_specs
            if (include_disabled or s.name in enabled_set)
            and (not pack_filter or s.pack == pack_filter.strip().lower())
        ]
        _emit_toon(
            [
                {
                    "name": s.name,
                    "pack": s.pack,
                    "enabled": s.name in enabled_set,
                    "signature": f"{s.name}{s.signature_display}",
                    "description": s.description,
                }
                for s in tools_to_emit
            ]
        )
        return 0

    if as_json:
        tools_to_emit = [
            s
            for s in all_specs
            if (include_disabled or s.name in enabled_set)
            and (not pack_filter or s.pack == pack_filter.strip().lower())
        ]
        print(
            json.dumps(
                [
                    {
                        "name": s.name,
                        "pack": s.pack,
                        "enabled": s.name in enabled_set,
                        "signature": f"{s.name}{s.signature_display}",
                        "description": s.description,
                    }
                    for s in tools_to_emit
                ],
                indent=2,
            )
        )
        return 0

    cfg_path = get_config_path(explicit_config)
    cfg_display = str(cfg_path)
    if cfg_path.is_symlink() and cfg_path.exists():
        cfg_display = f"{cfg_path} -> {cfg_path.resolve()}"

    active_count = len(enabled_set)
    total_count = len(all_specs)
    pct = int((active_count / total_count) * 100) if total_count else 0

    term_w = shutil.get_terminal_size(fallback=(80, 24)).columns
    max_w = max(76, min(term_w - 2, 140))

    summary_lines = [
        f"{ui.bold('Store Config:')}   {ui.dim(cfg_display)}",
        f"{ui.bold('Active State:')}   {ui.bold_green(str(active_count))}/{total_count} tools enabled ({ui.bold_cyan(f'{pct}%')}) across {len(pack_specs)} categories",
    ]
    ui.panel("SLED MCP TOOLS", summary_lines, width=max_w)
    print(file=ui.stream)

    tool_w = 20
    desc_w = max(30, max_w - (tool_w + 10))

    for spec, en_cnt, tot_cnt in pack_specs:
        category_tools = [
            s for s in spec.tools if include_disabled or s.name in enabled_set
        ]
        if not category_tools and not include_disabled:
            continue

        if en_cnt == tot_cnt and tot_cnt > 0:
            badge = ui.bold_green("[✔] ALL ACTIVE")
        elif en_cnt > 0:
            badge = ui.yellow("[◐] PARTIAL   ")
        else:
            badge = ui.dim("[ ] INACTIVE  ")

        print(
            f" {spec.icon} {ui.bold(spec.title)}  {badge}  {ui.dim(f'({en_cnt}/{tot_cnt} enabled)')}",
            file=ui.stream,
        )
        print(f"   {ui.dim(spec.description)}", file=ui.stream)

        sep_tool = "─" * (tool_w - 2)
        sep_desc = "─" * min(desc_w, 48)

        hdr_tool = f"{'TOOL':<{tool_w}}"
        hdr_sep = f"{sep_tool:<{tool_w}}"
        print(
            f"       {ui.dim(hdr_tool)}  {ui.dim('DESCRIPTION')}",
            file=ui.stream,
        )
        print(
            f"       {ui.dim(hdr_sep)}  {ui.dim(sep_desc)}",
            file=ui.stream,
        )

        for t in spec.tools if include_disabled else category_tools:
            is_en = t.name in enabled_set
            mark = ui.bold_green("✔") if is_en else ui.dim("·")
            name_str = (
                ui.bold_cyan(f"{t.name:<{tool_w}}")
                if is_en
                else ui.dim(f"{t.name:<{tool_w}}")
            )

            raw_desc = t.description
            if len(raw_desc) > desc_w:
                disp_desc = raw_desc[: desc_w - 3] + "..."
            else:
                disp_desc = raw_desc
            desc_styled = disp_desc if is_en else ui.dim(disp_desc)

            print(
                f"   {mark}   {name_str}  {desc_styled}",
                file=ui.stream,
            )
        print(file=ui.stream)

    print(
        f"{ui.badge()} {ui.dim('Tip: Run `sled store` to interactively toggle tools with live search, or `sled search <query>`.')}\n",
        file=ui.stream,
    )
    return 0


def render_packs_panel(
    as_json: bool = False, explicit_config: str | None = None
) -> int:
    """Alias for backwards compatibility: renders atomic tools grouped by capability domain."""
    return render_tools_panel(
        as_json=as_json, include_disabled=True, explicit_config=explicit_config
    )


def render_bridges_panel(
    as_json: bool = False, explicit_config: str | None = None
) -> int:
    """Render external MCP application bridges and their status (Zero-Trust by default)."""
    from sled.tools.bridge import list_bridge_statuses

    statuses = list_bridge_statuses(explicit_config)
    if as_json:
        print(json.dumps(statuses, indent=2))
        return 0

    cfg_path = get_config_path(explicit_config)
    print(file=ui.stream)
    print(
        f"{ui.bold('🏔️  External MCP Bridges & Subprocess Proxies')} {ui.dim(f'({cfg_path})')}",
        file=ui.stream,
    )
    print(
        f"   {ui.dim('Zero-Trust Policy: External application bridges are deactivated by default upon install.')}",
        file=ui.stream,
    )
    print(file=ui.stream)

    name_w = 16
    stat_w = 16
    cmd_w = 20

    hdr_b = f"{'BRIDGE':<{name_w}}"
    hdr_s = f"{'STATUS':<{stat_w}}"
    hdr_c = f"{'COMMAND':<{cmd_w}}"

    print(
        f"       {ui.dim(hdr_b)}  {ui.dim(hdr_s)}  {ui.dim(hdr_c)}  {ui.dim('DESCRIPTION')}",
        file=ui.stream,
    )
    print(
        f"       {ui.dim('─' * (name_w - 2))}  {ui.dim('─' * (stat_w - 2))}  {ui.dim('─' * (cmd_w - 2))}  {ui.dim('─' * 30)}",
        file=ui.stream,
    )

    for b in statuses:
        st = b["status"]
        if st == "active":
            mark = ui.bold_green("✔")
            raw_badge = f"{'ACTIVE':<{stat_w}}"
            status_badge = ui.bold_green(raw_badge)
            name_str = ui.bold_cyan(f"{b['name']:<{name_w}}")
        elif st == "disabled":
            mark = ui.dim("·")
            raw_badge = f"{'DISABLED':<{stat_w}}"
            status_badge = ui.dim(raw_badge)
            name_str = ui.dim(f"{b['name']:<{name_w}}")
        else:
            mark = ui.bold_red("✗")
            raw_badge = f"{'NOT IN PATH':<{stat_w}}"
            status_badge = ui.bold_red(raw_badge)
            name_str = ui.dim(f"{b['name']:<{name_w}}")

        cmd_str = f"{b['command']:<{cmd_w}}"
        desc_str = b.get("description", "")
        print(
            f"   {mark}   {name_str}  {status_badge}  {ui.dim(cmd_str)}  {desc_str}",
            file=ui.stream,
        )

    print(file=ui.stream)
    print(
        f"{ui.badge()} {ui.dim('To activate:   `sled enable <name>`')}",
        file=ui.stream,
    )
    print(
        f"{ui.badge()} {ui.dim('To deactivate: `sled disable <name>`')}\n",
        file=ui.stream,
    )
    return 0


def render_search_panel(
    query: str,
    as_json: bool = False,
    interactive: bool = False,
    explicit_config: str | None = None,
) -> int:
    """Search Sled's local packs and atomic tools (no external servers)."""
    if interactive:
        return render_store_interactive(
            initial_mode="tools",
            initial_query=query,
            explicit_config=explicit_config,
        )

    results = search_catalog(query, explicit_config=explicit_config)
    if as_json:
        print(json.dumps(results, indent=2))
        return 0

    pack_matches = results["pack_matches"]
    tool_matches = results["tool_matches"]

    lines: list[str] = [
        f"{ui.bold('Query:')}   {ui.bold_cyan(query or '(all)')}",
        f"{ui.bold('Matches:')} {ui.bold_green(str(len(tool_matches)))} atomic tool(s), {ui.bold_cyan(str(len(pack_matches)))} pack(s)",
        "",
    ]

    if pack_matches:
        lines.append(ui.bold_cyan("Matching Packs:"))
        for pm in pack_matches:
            en_c = pm["enabled_tools"]
            tot_c = pm["total_tools"]
            mark = (
                ui.bold_green("✔")
                if en_c == tot_c
                else (ui.yellow("◐") if en_c > 0 else ui.dim("·"))
            )
            tools_csv = ", ".join(pm["tools"])
            lines.append(
                f"  {mark} {pm['icon']} {ui.bold(pm['id'])} ({en_c}/{tot_c}) — {pm['title']}: {ui.dim(tools_csv)}"
            )
        lines.append("")

    if tool_matches:
        lines.append(ui.bold_cyan("Matching Atomic Tools:"))
        for tm in tool_matches:
            is_en = tm["enabled"]
            mark = ui.bold_green("✔") if is_en else ui.dim("·")
            badge = (
                ui.bold_cyan(f"[{tm['pack']}]")
                if is_en
                else ui.dim(f"[{tm['pack']}:off]")
            )
            lines.append(f"  {mark} {ui.bold(tm['signature'])} {badge}")
            lines.append(f"    {ui.dim(tm['description'])}")
    else:
        lines.append(ui.yellow(f"  No built-in tools matched '{query}'."))

    lines.append("")
    lines.append(
        ui.dim(
            f"Tip: Run `sled search {query} -i` to toggle these matches interactively, or `sled enable <tool>`."
        )
    )
    ui.panel("SLED LOCAL TOOL SEARCH", lines)
    return 0


def handle_enable_disable(
    targets: Sequence[str], enable: bool, explicit_config: str | None = None
) -> int:
    """Enable or disable one or more packs OR individual atomic tools via CLI."""
    if not targets:
        ui.error(
            "Specify at least one pack name (e.g. `fs`, `skald`) or atomic tool name (e.g. `ls`)."
        )
        return 1

    from sled.tools import get_all_pack_catalog

    catalog = get_all_pack_catalog(explicit_config)
    tool_map = get_all_tool_map()
    all_specs = list_tool_specs(only_enabled=False, explicit_config=explicit_config)
    unknown: list[str] = []
    affected_tools: list[str] = []
    affected_packs: list[str] = []

    for raw_t in targets:
        t = raw_t.strip().lower()
        if t in ("all", "*"):
            affected_tools.extend(s.name for s in all_specs)
            affected_packs.extend(catalog.keys())
        elif t in catalog:
            affected_packs.append(t)
            affected_tools.extend(s.name for s in all_specs if s.pack == t)
        elif t in tool_map:
            affected_tools.append(t)
        else:
            unknown.append(raw_t)

    if unknown:
        ui.error(
            f"Unknown pack or tool: {', '.join(unknown)}. Run `sled packs`, `sled tools --all`, or `sled search <query>`."
        )
        return 1

    current_set = set(get_enabled_tools(explicit_config))
    if enable:
        current_set.update(affected_tools)
    else:
        current_set.difference_update(affected_tools)

    saved_path = save_enabled_tools(list(current_set), explicit_config=explicit_config)
    final_tools = get_enabled_tools(explicit_config)
    verb = "Enabled" if enable else "Disabled"
    ui.success(
        f"{verb} {', '.join(targets)} ({len(affected_tools)} tool(s)) -> {len(final_tools)}/{len(all_specs)} active tools ({saved_path})"
    )
    return 0


def handle_run_tool(tool_name: str, kv_args: Sequence[str]) -> int:
    """Execute any built-in atomic tool directly from the CLI (`sled run <tool> [k=v ...]`)."""
    tool_map = get_all_tool_map()
    spec = tool_map.get(tool_name.strip().lower())
    if not spec:
        ui.error(
            f"Unknown atomic tool '{tool_name}'. Run `sled search {tool_name}` or `sled tools --all`."
        )
        return 1

    sig = inspect.signature(spec.handler)
    kwargs: dict[str, Any] = {}
    for item in kv_args:
        if "=" in item:
            k, v = item.split("=", 1)
            k = k.strip()
            param = sig.parameters.get(k)
            if param and param.default is not inspect.Parameter.empty:
                if isinstance(param.default, bool):
                    kwargs[k] = v.lower() in ("1", "true", "yes", "on")
                elif isinstance(param.default, int):
                    kwargs[k] = int(v)
                elif isinstance(param.default, float):
                    kwargs[k] = float(v)
                elif v.startswith(("[", "{")) and v.endswith(("]", "}")):
                    try:
                        kwargs[k] = json.loads(v)
                    except (json.JSONDecodeError, ValueError):
                        kwargs[k] = v
                else:
                    kwargs[k] = v
            elif v.startswith(("[", "{")) and v.endswith(("]", "}")):
                try:
                    kwargs[k] = json.loads(v)
                except (json.JSONDecodeError, ValueError):
                    kwargs[k] = v
            else:
                kwargs[k] = v
        else:
            # First positional parameter
            first_param = next(iter(sig.parameters.keys()), None)
            if first_param and first_param not in kwargs:
                kwargs[first_param] = item

    res = spec.handler(**kwargs)
    if getattr(ui, "is_toon", False):
        _emit_toon(res)
    else:
        print(json.dumps(res, indent=2))
    return 0 if res.get("status") != "error" else 1


def render_hub_json() -> int:
    sled_bin = shutil.which("sled") or "sled"
    snippet = {
        "command": sled_bin,
        "args": ["serve"],
    }
    print(json.dumps(snippet, indent=2))
    return 0


def print_status_dashboard(explicit_config: str | None = None) -> None:
    """Display an interactive overview dashboard matching Borealis/Basecamp."""
    uname_data = uname()
    uptime_data = uptime()
    git_data = git_status(".")
    pack_specs = list_pack_specs(explicit_config)
    active_tools = list_tool_specs(only_enabled=True, explicit_config=explicit_config)
    all_tools = list_tool_specs(only_enabled=False, explicit_config=explicit_config)

    os_rel = uname_data.get("os_release", {})
    distro = (
        os_rel.get("pretty_name")
        or f"{uname_data.get('system')} {uname_data.get('release')}"
    )
    git_summary = (
        f"{git_data.get('branch')} ({'clean' if git_data.get('clean') else 'dirty'})"
        if git_data.get("status") == "ok"
        else "not a git repo"
    )

    category_badges: list[str] = []
    for spec, en_cnt, tot_cnt in pack_specs:
        if en_cnt == tot_cnt and tot_cnt > 0:
            category_badges.append(
                f"{ui.bold_green('✔')} {spec.icon}{spec.id}({en_cnt})"
            )
        elif en_cnt > 0:
            category_badges.append(
                f"{ui.yellow('◐')} {spec.icon}{spec.id}({en_cnt}/{tot_cnt})"
            )
        else:
            category_badges.append(f"{ui.dim('·')} {ui.dim(f'{spec.icon}{spec.id}')}")

    cfg_path = get_config_path(explicit_config)
    cfg_display = str(cfg_path)
    if cfg_path.is_symlink() and cfg_path.exists():
        cfg_display = f"{cfg_path} -> {cfg_path.resolve()}"

    if getattr(ui, "is_toon", False):
        data = {
            "status": "ok",
            "app": "sled",
            "version": __version__,
            "host": uname_data.get("hostname"),
            "os": distro,
            "uptime": uptime_data.get("uptime_human"),
            "load": uptime_data.get("load_average"),
            "workspace_git": git_summary,
            "config_path": str(cfg_path.resolve() if cfg_path.exists() else cfg_path),
            "active_tools_count": len(active_tools),
            "total_tools_count": len(all_tools),
            "categories": [
                {
                    "id": spec.id,
                    "title": spec.title,
                    "enabled": en_cnt,
                    "total": tot_cnt,
                }
                for spec, en_cnt, tot_cnt in pack_specs
            ],
        }
        _emit_toon(data)
        return

    if ui.is_json:
        data = {
            "status": "ok",
            "app": "sled",
            "version": __version__,
            "host": uname_data.get("hostname"),
            "os": distro,
            "uptime": uptime_data.get("uptime_human"),
            "load": uptime_data.get("load_average"),
            "workspace_git": git_summary,
            "config_path": str(cfg_path.resolve() if cfg_path.exists() else cfg_path),
            "active_tools_count": len(active_tools),
            "total_tools_count": len(all_tools),
            "categories": {
                spec.id: {
                    "title": spec.title,
                    "enabled_count": en_cnt,
                    "total_count": tot_cnt,
                }
                for spec, en_cnt, tot_cnt in pack_specs
            },
        }
        ui.json(data)
        return

    lines = [
        f"{ui.bold('Bridge Version:')}  {ui.bold_cyan(f'v{__version__}')} (Transport: {ui.green('stdio / JSON-RPC 2.0')})",
        f"{ui.bold('Host System:')}     {uname_data.get('hostname')} — {distro}",
        f"{ui.bold('Uptime / Load:')}   {uptime_data.get('uptime_human')} (1m load: {uptime_data.get('load_average', {}).get('1m', 'n/a')})",
        f"{ui.bold('Workspace Git:')}   {git_summary}",
        f"{ui.bold('Store Config:')}    {ui.dim(cfg_display)}",
        f"{ui.bold('Categories:')}      {'  '.join(category_badges)}",
        f"{ui.bold('Active Tools:')}    {ui.bold_green(str(len(active_tools)))}/{len(all_tools)} enabled",
    ]
    ui.panel("SLED MCP STORE & SERVER BRIDGE", lines)


def main(argv: Sequence[str] | None = None) -> int:
    raw_args = list(argv) if argv is not None else sys.argv[1:]
    handle_color_args(raw_args, ui=ui)

    # In CLI mode (not serve), ensure ui logs/json/version go to stdout
    if raw_args and raw_args[0] != "serve":
        ui.set_stream(sys.stdout)

    if any(a in ("-h", "--help", "help") for a in raw_args):
        print_help()
        return 0

    if ui.handle_version_arg(raw_args, __version__):
        return 0

    if not raw_args:
        if not ui.is_interactive:
            return run_stdio_server("INFO")

        print_status_dashboard()
        action = ui.select(
            "Quick Actions:",
            [
                (
                    "store",
                    "Open Store — Tool Selector",
                    "Toggle individual tools (with live '/' search filter)",
                ),
                (
                    "tools",
                    "Inspect Active Tools",
                    "Browse all tools, categories, and descriptions",
                ),
                (
                    "serve",
                    "Start MCP Server (stdio)",
                    "Launch JSON-RPC 2.0 server over standard I/O",
                ),
                (
                    "hub-json",
                    "Display MCP Hub Config",
                    "Print JSON snippet for Antigravity / Claude / OpenCode",
                ),
                ("exit", "Exit", "Close dashboard"),
            ],
        )
        if action == "exit":
            return 0
        if action in ("store", "store-packs", "store-tools"):
            return render_store_interactive()
        raw_args = [action]

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "-c", "--config", type=str, default=argparse.SUPPRESS, help="Path to sled.toml"
    )
    common.add_argument(
        "-t",
        "--tools",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Open store in Atomic Tool Mode",
    )
    common.add_argument(
        "-p",
        "--pack",
        type=str,
        default=argparse.SUPPRESS,
        help="Filter tools by pack ID",
    )
    common.add_argument(
        "-i",
        "--interactive",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Interactive mode",
    )
    common.add_argument(
        "-s",
        "--search",
        type=str,
        default=argparse.SUPPRESS,
        help="Initial search query filter",
    )
    common.add_argument(
        "--all",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Include disabled tools in `sled tools`",
    )
    common.add_argument(
        "-A",
        "--agent",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Compact agent-friendly output mode",
    )
    common.add_argument(
        "--json",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Output raw JSON for CLI subcommands",
    )
    common.add_argument(
        "--toon",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Output compact Token-Oriented Object Notation (TOON)",
    )
    common.add_argument(
        "--log-level",
        default=argparse.SUPPRESS,
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
    )
    common.add_argument(
        "-v", "--verbose", action="store_true", default=argparse.SUPPRESS
    )
    common.add_argument(
        "--color", choices=["auto", "always", "never"], default=argparse.SUPPRESS
    )
    common.add_argument("--no-color", action="store_true", default=argparse.SUPPRESS)

    parser = argparse.ArgumentParser(
        prog=__app_name__, add_help=False, parents=[common]
    )

    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("serve", parents=[common], help="Start MCP server over stdio")
    subparsers.add_parser("status", parents=[common], help="Display status dashboard")

    store_p = subparsers.add_parser(
        "store",
        parents=[common],
        help="Interactive MCP Store (Pack Mode or Tool Mode)",
    )
    store_p.add_argument(
        "mode",
        nargs="?",
        choices=["packs", "tools", "pack", "tool"],
        default="packs",
        help="Start in `packs` mode (default) or `tools` mode",
    )

    subparsers.add_parser("packs", parents=[common], help="List all capability packs")
    subparsers.add_parser("tools", parents=[common], help="List atomic MCP tools")

    search_p = subparsers.add_parser(
        "search", parents=[common], help="Search local packs and atomic tools"
    )
    search_p.add_argument("query", nargs="*", help="Search keywords")

    enable_p = subparsers.add_parser(
        "enable", parents=[common], help="Enable packs or atomic tools"
    )
    enable_p.add_argument("targets", nargs="+", help="Pack IDs or atomic tool names")

    disable_p = subparsers.add_parser(
        "disable", parents=[common], help="Disable packs or atomic tools"
    )
    disable_p.add_argument("targets", nargs="+", help="Pack IDs or atomic tool names")

    run_p = subparsers.add_parser(
        "run", parents=[common], help="Execute an atomic tool directly"
    )
    run_p.add_argument("tool_name", help="Atomic tool name (e.g. ls, cat, uptime)")
    run_p.add_argument("kv_args", nargs="*", help="key=value arguments")

    subparsers.add_parser(
        "hub-json", parents=[common], help="Print MCP Hub JSON config snippet"
    )

    bridge_p = subparsers.add_parser(
        "bridge",
        parents=[common],
        help="Manage external MCP application bridges (Zero-Trust)",
    )
    bridge_p.add_argument(
        "action",
        nargs="?",
        choices=["list", "enable", "disable"],
        default="list",
        help="Action: list (default), enable, disable",
    )
    bridge_p.add_argument("bridge_name", nargs="?", help="Bridge name (e.g. skald)")

    args = parser.parse_args(raw_args)
    cfg_arg = getattr(args, "config", None)
    tools_flag = getattr(args, "tools", False)
    pack_arg = getattr(args, "pack", None)
    interactive_flag = getattr(args, "interactive", False)
    search_arg = getattr(args, "search", "")
    all_arg = getattr(args, "all", False)
    json_arg = getattr(args, "json", False)
    verbose_arg = getattr(args, "verbose", False)
    log_level_arg = getattr(args, "log_level", None)

    user_cfg = load_user_config(cfg_arg)

    log_level = (
        "DEBUG"
        if verbose_arg
        else (log_level_arg or str(user_cfg.get("log_level", "INFO")))
    )
    configure_stderr_logging(log_level)

    cmd = args.command or "serve"

    if cmd == "serve":
        return run_stdio_server(log_level, explicit_config=cfg_arg)
    if cmd == "status":
        print_status_dashboard(explicit_config=cfg_arg)
        return 0
    if cmd == "store":
        initial_mode = "tools" if tools_flag else getattr(args, "mode", "packs")
        return render_store_interactive(
            initial_mode=initial_mode,
            initial_query=search_arg,
            explicit_config=cfg_arg,
        )
    if cmd == "packs":
        return render_packs_panel(as_json=json_arg, explicit_config=cfg_arg)
    if cmd == "tools":
        if interactive_flag:
            return render_store_interactive(
                initial_mode="tools",
                initial_query=pack_arg or search_arg,
                explicit_config=cfg_arg,
            )
        return render_tools_panel(
            as_json=json_arg,
            as_toon=getattr(args, "toon", False) or getattr(ui, "is_toon", False),
            include_disabled=all_arg,
            pack_filter=pack_arg,
            explicit_config=cfg_arg,
        )
    if cmd == "search":
        q_str = " ".join(getattr(args, "query", [])) or search_arg
        return render_search_panel(
            query=q_str,
            as_json=json_arg,
            interactive=interactive_flag,
            explicit_config=cfg_arg,
        )
    if cmd == "enable":
        return handle_enable_disable(args.targets, enable=True, explicit_config=cfg_arg)
    if cmd == "disable":
        return handle_enable_disable(
            args.targets, enable=False, explicit_config=cfg_arg
        )
    if cmd == "run":
        return handle_run_tool(args.tool_name, args.kv_args)
    if cmd in ("bridge", "bridges"):
        action = getattr(args, "action", "list") or "list"
        b_name = getattr(args, "bridge_name", None)
        if action == "list" or not b_name:
            return render_bridges_panel(as_json=json_arg, explicit_config=cfg_arg)
        return handle_enable_disable(
            [b_name], enable=(action == "enable"), explicit_config=cfg_arg
        )
    if cmd == "hub-json":
        return render_hub_json()

    print_help()
    return 1


# Alias for compatibility
cli = main

if __name__ == "__main__":
    sys.exit(main())
