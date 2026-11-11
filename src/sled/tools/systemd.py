"""Sled Pack: `systemd` — Atomic systemd & journalctl tools (`systemctl_list`, `systemctl_status`, `journalctl`, `systemd_analyze`)."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from sled.tools import ToolSpec
from sled.tools._exec import run_cmd, which_bin

if TYPE_CHECKING:
    from mcp.server import MCPServer

logger = logging.getLogger("sled.tools.systemd")

PACK = "systemd"


def _scope_flag(scope: str) -> list[str]:
    return ["--user"] if scope.strip().lower() == "user" else []


def systemctl_list(
    scope: str = "system",
    state: str = "",
    unit_type: str = "service",
    pattern: str = "",
    compact: bool = True,
) -> dict[str, Any]:
    """Lists systemd units (`system` or `user` scope) filtered by state, type, or name pattern.

    Args:
        scope: `system` (default) or `user`.
        state: Optional filter such as `failed`, `running`, `active`, `inactive` (empty for all active/failed).
        unit_type: Unit type such as `service`, `timer`, `socket`, `target`, or `all` (default `service`).
        pattern: Optional glob or substring filter (e.g. `*docker*`, `syncthing*`).
        compact: Return tabular `columns` and `rows` to minimize token overhead (default True).
    """
    cmd = [
        "systemctl",
        *_scope_flag(scope),
        "list-units",
        "--no-pager",
        "--output=json",
    ]
    if unit_type and unit_type.strip().lower() != "all":
        cmd.append(f"--type={unit_type.strip().lower()}")
    if state.strip():
        cmd.append(f"--state={state.strip().lower()}")
    if pattern.strip():
        cmd.append(pattern.strip())

    code, out, err = run_cmd(cmd, timeout=10.0)
    if code != 0:
        return {"status": "error", "scope": scope, "error": err or out}

    try:
        units = json.loads(out) if out else []
    except json.JSONDecodeError:
        units = []

    if compact:
        columns = ["unit", "load", "active", "sub", "description"]
        rows = [
            [
                str(u.get("unit", "")),
                str(u.get("load", "")),
                str(u.get("active", "")),
                str(u.get("sub", "")),
                str(u.get("description", ""))[:60],
            ]
            for u in units[:150]
            if isinstance(u, dict)
        ]
        return {
            "status": "ok",
            "scope": scope,
            "count": len(rows),
            "columns": columns,
            "rows": rows,
        }

    return {
        "status": "ok",
        "scope": scope,
        "count": len(units),
        "units": units[:150],
    }


def systemctl_status(unit: str, scope: str = "system") -> dict[str, Any]:
    """Inspects detailed status and key properties of a systemd unit.

    Args:
        unit: Unit name (e.g. `docker.service`, `syncthing.service`, `pipewire.service`).
        scope: `system` (default) or `user`.
    """
    flags = _scope_flag(scope)
    props = (
        "Id,Description,LoadState,ActiveState,SubState,UnitFileState,"
        "MainPID,ExecMainStatus,Result,FragmentPath,ActiveEnterTimestamp"
    )
    _, show_out, _ = run_cmd(
        ["systemctl", *flags, "show", unit.strip(), f"--property={props}"],
        timeout=8.0,
    )
    properties: dict[str, str] = {}
    for line in show_out.splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            properties[k.strip()] = v.strip()

    code, status_out, status_err = run_cmd(
        ["systemctl", *flags, "status", "--no-pager", "-n", "25", unit.strip()],
        timeout=8.0,
    )

    return {
        "status": "ok",
        "unit": unit.strip(),
        "scope": scope,
        "active": properties.get("ActiveState") == "active",
        "properties": properties,
        "status_text": status_out or status_err,
        "exit_code": code,
    }


def journalctl(
    unit: str = "",
    scope: str = "system",
    lines: int = 100,
    since: str = "",
    priority: str = "",
    grep: str = "",
    current_boot: bool = True,
) -> dict[str, Any]:
    """Queries `journalctl` logs for a specific systemd unit or the system journal.

    Args:
        unit: Optional systemd unit name (e.g. `nginx.service`). Leave empty for general logs.
        scope: `system` (default) or `user`.
        lines: Number of recent log lines to fetch (default 100, max 500).
        since: Optional time filter (e.g. `1 hour ago`, `today`, `2026-10-18 18:00:00`).
        priority: Optional max priority level (`emerg`, `alert`, `crit`, `err`, `warning`, `notice`, `info`, `debug`).
        grep: Optional regex pattern to filter log messages.
        current_boot: Restrict logs to current boot (`-b`, default True).
    """
    lines = max(1, min(int(lines), 500))
    cmd = ["journalctl", "--no-pager", "-n", str(lines), "--output=short-iso"]
    if scope.strip().lower() == "user":
        cmd.append("--user")
        if unit.strip():
            cmd.extend(["--user-unit", unit.strip()])
    elif unit.strip():
        cmd.extend(["-u", unit.strip()])

    if current_boot:
        cmd.append("-b")
    if since.strip():
        cmd.extend(["--since", since.strip()])
    if priority.strip():
        cmd.extend(["-p", priority.strip()])
    if grep.strip():
        cmd.extend(["-g", grep.strip()])

    code, out, err = run_cmd(cmd, timeout=12.0)
    if code != 0:
        return {
            "status": "error",
            "unit": unit or "(all)",
            "scope": scope,
            "error": err or out,
        }

    return {
        "status": "ok",
        "unit": unit or "(all)",
        "scope": scope,
        "logs": out,
    }


def systemd_analyze(
    mode: str = "blame",
    limit: int = 25,
    user_scope: bool = False,
) -> dict[str, Any]:
    """Analyzes systemd boot performance and unit dependency critical chains (systemd-analyze blame / critical-chain / time).

    Args:
        mode: Analysis mode: `blame` (default), `critical-chain`, or `time`.
        limit: Maximum units to return for `blame` (default 25, max 100).
        user_scope: Inspect user manager instead of system manager (`--user`, default False).
    """
    if not which_bin("systemd-analyze"):
        return {
            "status": "error",
            "error": "`systemd-analyze` binary not found in PATH.",
        }

    m = mode.strip().lower()
    allowed = ("blame", "critical-chain", "time")
    if m not in allowed:
        return {
            "status": "error",
            "error": f"Invalid mode '{mode}'. Allowed: {', '.join(allowed)}",
        }

    flags = ["--user"] if user_scope else []
    cmd = ["systemd-analyze", *flags, "--no-pager", m]

    code, out, err = run_cmd(cmd, timeout=15.0)
    if code != 0:
        return {"status": "error", "mode": m, "error": err or out}

    if m == "blame":
        limit = max(1, min(int(limit), 100))
        lines = [ln.strip() for ln in out.splitlines() if ln.strip()][:limit]
        units: list[dict[str, str]] = []
        for ln in lines:
            parts = ln.split(None, 1)
            if len(parts) == 2:
                units.append({"time": parts[0], "unit": parts[1]})
        return {
            "status": "ok",
            "mode": m,
            "user_scope": user_scope,
            "count": len(units),
            "units": units,
        }

    return {
        "status": "ok",
        "mode": m,
        "user_scope": user_scope,
        "output": out,
    }


TOOLS = [
    ToolSpec(
        name="systemctl_list",
        module="systemd",
        description="Lists systemd units (system or user) filtered by state (failed, running), type, or pattern.",
        handler=systemctl_list,
        pack="systemd",
    ),
    ToolSpec(
        name="systemctl_status",
        module="systemd",
        description="Inspects detailed status, PID, and properties of a system or user systemd unit.",
        handler=systemctl_status,
        pack="systemd",
    ),
    ToolSpec(
        name="journalctl",
        module="systemd",
        description="Queries journalctl logs for a systemd unit or boot with priority, time, and grep filters.",
        handler=journalctl,
        pack="systemd",
    ),
    ToolSpec(
        name="systemd_analyze",
        module="systemd",
        description="Analyzes boot timing, service blame, and critical-chain dependencies via systemd-analyze.",
        handler=systemd_analyze,
        pack="systemd",
    ),
]


def register(mcp: MCPServer) -> None:
    """Register systemd tools with MCPServer."""
    for spec in TOOLS:
        mcp.tool(name=spec.name, description=spec.description)(spec.handler)
