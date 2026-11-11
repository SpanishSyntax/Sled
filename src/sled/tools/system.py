"""Sled Pack: `system` — Atomic host, process, disk, memory, and binary inspection tools (`uname`, `uptime`, `ps`, `df`, `free`, `which`, `lsblk`, `zoxide_query`, `notify`, `whoami`)."""

from __future__ import annotations

import json
import logging
import os
import platform
import socket
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sled.tools import ToolSpec
from sled.tools._exec import run_cmd, which_bin

if TYPE_CHECKING:
    from mcp.server import MCPServer

logger = logging.getLogger("sled.tools.system")

PACK = "system"


def _read_os_release() -> dict[str, str]:
    for candidate in (Path("/etc/os-release"), Path("/usr/lib/os-release")):
        if candidate.is_file():
            try:
                info: dict[str, str] = {}
                for line in candidate.read_text(encoding="utf-8").splitlines():
                    if "=" in line and not line.startswith("#"):
                        k, v = line.split("=", 1)
                        info[k.strip()] = v.strip().strip('"').strip("'")
                return {
                    "name": info.get("NAME", ""),
                    "pretty_name": info.get("PRETTY_NAME", ""),
                    "id": info.get("ID", ""),
                    "version_id": info.get("VERSION_ID", ""),
                    "build_id": info.get("BUILD_ID", ""),
                }
            except OSError:
                pass
    return {}


def uname() -> dict[str, Any]:
    """Returns host kernel, architecture, hostname, Python version, and `/etc/os-release` distribution info."""
    return {
        "status": "ok",
        "hostname": socket.gethostname(),
        "system": platform.system(),
        "release": platform.release(),
        "version": platform.version(),
        "machine": platform.machine(),
        "cpu_count": os.cpu_count(),
        "python_version": platform.python_version(),
        "os_release": _read_os_release(),
    }


def uptime() -> dict[str, Any]:
    """Returns system uptime in seconds, human-readable duration, and 1m/5m/15m CPU load averages."""
    uptime_secs: float | None = None
    proc_uptime = Path("/proc/uptime")
    if proc_uptime.is_file():
        try:
            raw = proc_uptime.read_text(encoding="utf-8").strip().split()[0]
            uptime_secs = round(float(raw), 2)
        except (ValueError, IndexError, OSError):
            pass

    if uptime_secs is not None:
        total = int(uptime_secs)
        days, rem = divmod(total, 86400)
        hours, rem = divmod(rem, 3600)
        minutes, secs = divmod(rem, 60)
        parts: list[str] = []
        if days:
            parts.append(f"{days}d")
        if hours or days:
            parts.append(f"{hours}h")
        if minutes or hours or days:
            parts.append(f"{minutes}m")
        parts.append(f"{secs}s")
        human = " ".join(parts)
    else:
        human = "unknown"

    try:
        l1, l5, l15 = os.getloadavg()
        load_avg = {"1m": round(l1, 2), "5m": round(l5, 2), "15m": round(l15, 2)}
    except OSError:
        load_avg = {}

    return {
        "status": "ok",
        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "hostname": socket.gethostname(),
        "uptime_seconds": uptime_secs,
        "uptime_human": human,
        "load_average": load_avg,
    }


def ps(
    limit: int = 20,
    sort_by: str = "memory",
    filter_name: str = "",
    compact: bool = True,
) -> dict[str, Any]:
    """Lists running processes sorted by memory or CPU usage (`ps -eo`).

    Args:
        limit: Maximum number of processes to return (default 20, max 100).
        sort_by: Sort by `memory` (default) or `cpu`.
        filter_name: Optional substring filter on command name.
        compact: Return tabular `columns` and `rows` to minimize token overhead (default True).
    """
    limit = max(1, min(int(limit), 100))
    sort_key = "-%cpu" if sort_by.strip().lower() == "cpu" else "-%mem"
    code, out, err = run_cmd(
        ["ps", "-eo", "pid,user,%cpu,%mem,rss,comm", f"--sort={sort_key}"],
        timeout=5.0,
    )
    if code != 0:
        return {"status": "error", "error": err or out}

    needle = filter_name.strip().lower()
    if compact:
        columns = ["pid", "user", "cpu%", "mem%", "rss_kb", "command"]
        rows: list[list[str]] = []
        for line in out.splitlines()[1:]:
            parts = line.split(None, 5)
            if len(parts) == 6:
                if needle and needle not in parts[5].lower():
                    continue
                rows.append(parts)
                if len(rows) >= limit:
                    break
        return {
            "status": "ok",
            "sort_by": sort_by,
            "count": len(rows),
            "columns": columns,
            "rows": rows,
        }

    processes: list[dict[str, str]] = []
    for line in out.splitlines()[1:]:
        parts = line.split(None, 5)
        if len(parts) == 6:
            if needle and needle not in parts[5].lower():
                continue
            processes.append(
                {
                    "pid": parts[0],
                    "user": parts[1],
                    "cpu_percent": parts[2],
                    "mem_percent": parts[3],
                    "rss_kb": parts[4],
                    "command": parts[5],
                }
            )
            if len(processes) >= limit:
                break

    return {
        "status": "ok",
        "sort_by": sort_by,
        "count": len(processes),
        "processes": processes,
    }


def df(compact: bool = True) -> dict[str, Any]:
    """Returns mounted filesystem disk usage (`df -h`).

    Args:
        compact: Return tabular `columns` and `rows` to minimize token overhead (default True).
    """
    code, out, err = run_cmd(
        [
            "df",
            "-h",
            "--output=source,fstype,size,used,avail,pcent,target",
            "-x",
            "tmpfs",
            "-x",
            "devtmpfs",
        ],
        timeout=5.0,
    )
    if code != 0:
        return {"status": "error", "error": err or out}

    if compact:
        columns = ["filesystem", "type", "size", "used", "avail", "use%", "mount"]
        rows: list[list[str]] = []
        for line in out.splitlines()[1:]:
            parts = line.split(None, 6)
            if len(parts) == 7:
                rows.append(parts)
        return {
            "status": "ok",
            "count": len(rows),
            "columns": columns,
            "rows": rows,
        }

    filesystems: list[dict[str, str]] = []
    for line in out.splitlines()[1:]:
        parts = line.split(None, 6)
        if len(parts) == 7:
            filesystems.append(
                {
                    "filesystem": parts[0],
                    "type": parts[1],
                    "size": parts[2],
                    "used": parts[3],
                    "avail": parts[4],
                    "use_percent": parts[5],
                    "mountpoint": parts[6],
                }
            )

    return {
        "status": "ok",
        "count": len(filesystems),
        "filesystems": filesystems,
    }


def free() -> dict[str, Any]:
    """Returns system RAM and swap memory breakdown from `/proc/meminfo`."""
    meminfo: dict[str, str] = {}
    proc_mem = Path("/proc/meminfo")
    if proc_mem.is_file():
        for line in proc_mem.read_text(encoding="utf-8", errors="replace").splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                if k in (
                    "MemTotal",
                    "MemFree",
                    "MemAvailable",
                    "Buffers",
                    "Cached",
                    "SwapTotal",
                    "SwapFree",
                ):
                    meminfo[k] = v.strip()

    return {
        "status": "ok",
        "memory": meminfo,
    }


def which(binaries: str = "git,nix,python3,uv,direnv") -> dict[str, Any]:
    """Locates one or more comma/space-separated binaries on PATH and queries their `--version`.

    Args:
        binaries: Comma- or space-separated list of binary names to check (e.g. `git,nix,docker,rg`).
    """
    names = [b.strip() for b in binaries.replace(",", " ").split() if b.strip()]
    results: dict[str, dict[str, Any]] = {}
    for name in names:
        resolved = which_bin(name)
        if not resolved:
            results[name] = {"available": False, "path": None, "version": None}
            continue
        code, out, err = run_cmd([resolved, "--version"], timeout=4.0)
        first_line = (
            (out or err).splitlines()[0].strip() if (out or err) else "installed"
        )
        results[name] = {
            "available": True,
            "path": resolved,
            "version": first_line if code == 0 else f"installed ({first_line})",
        }

    return {
        "status": "ok",
        "results": results,
    }


def lsblk(all_devices: bool = False) -> dict[str, Any]:
    """Lists block storage devices, partitions, mountpoints, and filesystem types (`lsblk -J`).

    Args:
        all_devices: If True, include empty devices and RAM disks (default False).
    """
    cmd = [
        "lsblk",
        "-J",
        "-o",
        "NAME,KNAME,FSTYPE,FSVER,LABEL,UUID,FSAVAIL,FSUSE%,MOUNTPOINTS,SIZE,TYPE,MODEL",
    ]
    if all_devices:
        cmd.append("-a")

    code, stdout, stderr = run_cmd(cmd)
    if code != 0:
        return {"status": "error", "error": stderr or "Failed to run lsblk"}

    try:
        data = json.loads(stdout)
        devices = data.get("blockdevices", [])
        return {
            "status": "ok",
            "count": len(devices),
            "blockdevices": devices,
        }
    except json.JSONDecodeError as exc:
        return {
            "status": "error",
            "error": f"Failed to parse lsblk output: {exc}",
            "raw": stdout,
        }


def zoxide_query(query: str) -> dict[str, Any]:
    """Queries Zoxide frecency database to resolve a directory shortcut or project name.

    Args:
        query: Directory keyword or substring to resolve.
    """
    q = query.strip()
    if not q:
        return {"status": "error", "error": "Query cannot be empty"}

    code, stdout, stderr = run_cmd(["zoxide", "query", q])
    if code != 0:
        return {
            "status": "error",
            "error": stderr or f"No match found for '{q}' in zoxide database",
        }

    matched = Path(stdout.strip())
    return {
        "status": "ok",
        "query": q,
        "path": str(matched),
        "exists": matched.exists(),
        "is_dir": matched.is_dir(),
    }


def notify(
    title: str = "Sled",
    body: str = "",
    urgency: str = "normal",
    timeout_ms: int = 5000,
    app_name: str = "Sled",
    icon: str = "nix-snowflake",
    image_path: str = "",
) -> dict[str, Any]:
    """Sends a desktop notification over D-Bus via notify-send, gdbus, or busctl.

    Supports Caelestia Shell, Hyprland, Dunst, Mako, SwayNC, and standard FreeDesktop notification servers.

    Args:
        title: Notification summary/title text.
        body: Notification body text or markdown/HTML if supported.
        urgency: Urgency level ('low', 'normal', or 'critical').
        timeout_ms: Display expiration timeout in milliseconds (default: 5000).
        app_name: Application name reported to the notification daemon.
        icon: Named icon from icon theme or .desktop entry, or path to icon (default: 'nix-snowflake').
        image_path: Optional path to an image file or picture to display inside the notification.
    """
    clean_urgency = urgency.strip().lower()
    if clean_urgency not in ("low", "normal", "critical"):
        clean_urgency = "normal"

    # 1. Try notify-send if installed
    if which_bin("notify-send"):
        cmd = [
            "notify-send",
            "-a",
            app_name,
            "-u",
            clean_urgency,
            "-t",
            str(timeout_ms),
        ]
        if icon:
            cmd.extend(["-i", icon])
        if image_path:
            cmd.extend(["-h", f"string:image-path:{image_path}"])
        cmd.extend([title, body])
        ret, stdout, _stderr = run_cmd(cmd)
        if ret == 0:
            return {
                "status": "ok",
                "backend": "notify-send",
                "title": title,
                "body": body,
                "urgency": clean_urgency,
                "icon": icon,
                "image_path": image_path or None,
            }

    # 2. Try gdbus (standard with glib / NixOS base)
    if which_bin("gdbus"):
        urgency_byte = {"low": 0, "normal": 1, "critical": 2}.get(clean_urgency, 1)
        hints: list[str] = [f"'urgency': <byte {urgency_byte}>"]
        if image_path:
            hints.append(f"'image-path': <'{image_path}'>")
        hints_arg = "{" + ", ".join(hints) + "}"

        cmd = [
            "gdbus",
            "call",
            "--session",
            "--dest",
            "org.freedesktop.Notifications",
            "--object-path",
            "/org/freedesktop/Notifications",
            "--method",
            "org.freedesktop.Notifications.Notify",
            app_name,
            "0",
            icon or "",
            title,
            body,
            "[]",
            hints_arg,
            str(timeout_ms),
        ]
        ret, stdout, _stderr = run_cmd(cmd)
        if ret == 0:
            nid = stdout.strip("(), ").replace("uint32 ", "")
            return {
                "status": "ok",
                "backend": "gdbus",
                "notification_id": int(nid) if nid.isdigit() else nid,
                "title": title,
                "body": body,
                "urgency": clean_urgency,
                "icon": icon,
                "image_path": image_path or None,
            }

    # 3. Try busctl (standard systemd utility)
    if which_bin("busctl"):
        urgency_byte = {"low": 0, "normal": 1, "critical": 2}.get(clean_urgency, 1)
        cmd = [
            "busctl",
            "--user",
            "call",
            "org.freedesktop.Notifications",
            "/org/freedesktop/Notifications",
            "org.freedesktop.Notifications",
            "Notify",
            "susssasa{sv}i",
            app_name,
            "0",
            icon or "",
            title,
            body,
            "0",
        ]
        if image_path:
            cmd.extend(
                ["2", "urgency", "y", str(urgency_byte), "image-path", "s", image_path]
            )
        else:
            cmd.extend(["1", "urgency", "y", str(urgency_byte)])
        cmd.append(str(timeout_ms))

        ret, stdout, _stderr = run_cmd(cmd)
        if ret == 0:
            parts = stdout.split()
            nid = parts[-1] if parts else ""
            return {
                "status": "ok",
                "backend": "busctl",
                "notification_id": int(nid) if nid.isdigit() else nid,
                "title": title,
                "body": body,
                "urgency": clean_urgency,
                "icon": icon,
                "image_path": image_path or None,
            }

    return {
        "status": "error",
        "error": "No notification backend available. Ensure notify-send, gdbus, or busctl is available.",
    }


def whoami(detailed: bool = True) -> dict[str, Any]:
    """Returns the current user identity, UID, GID, groups, and home directory (like GNU whoami / id).

    Args:
        detailed: Return UID, GID, and supplementary groups alongside username (default True).
    """
    import getpass
    import grp

    username = getpass.getuser()
    if not detailed:
        return {
            "status": "ok",
            "username": username,
        }

    uid = os.getuid()
    gid = os.getgid()
    home = str(Path.home())

    groups: list[dict[str, Any]] = []
    try:
        for g_id in os.getgroups():
            try:
                g_entry = grp.getgrgid(g_id)
                groups.append({"gid": g_id, "name": g_entry.gr_name})
            except KeyError:
                groups.append({"gid": g_id, "name": str(g_id)})
    except OSError:
        pass

    shell = os.environ.get("SHELL", "")
    return {
        "status": "ok",
        "username": username,
        "uid": uid,
        "gid": gid,
        "groups": groups,
        "home_directory": home,
        "shell": shell,
    }


TOOLS = [
    ToolSpec(
        name="uname",
        module="system",
        description="Returns hostname, kernel version, CPU architecture, and NixOS/OS release details.",
        handler=uname,
        pack="system",
    ),
    ToolSpec(
        name="uptime",
        module="system",
        description="Returns system uptime duration and 1m/5m/15m CPU load averages.",
        handler=uptime,
        pack="system",
    ),
    ToolSpec(
        name="ps",
        module="system",
        description="Lists running processes sorted by memory or CPU usage with optional name filtering.",
        handler=ps,
        pack="system",
    ),
    ToolSpec(
        name="df",
        module="system",
        description="Returns mounted filesystem disk space usage and mountpoints.",
        handler=df,
        pack="system",
    ),
    ToolSpec(
        name="free",
        module="system",
        description="Returns system RAM and swap memory breakdown from /proc/meminfo.",
        handler=free,
        pack="system",
    ),
    ToolSpec(
        name="which",
        module="system",
        description="Locates binaries in PATH and reports their resolved paths and version strings.",
        handler=which,
        pack="system",
    ),
    ToolSpec(
        name="lsblk",
        module="system",
        description="Lists block storage devices, partitions, mountpoints, and filesystem types (lsblk -J).",
        handler=lsblk,
        pack="system",
    ),
    ToolSpec(
        name="zoxide_query",
        module="system",
        description="Queries Zoxide frecency database to resolve a directory shortcut or project name.",
        handler=zoxide_query,
        pack="system",
    ),
    ToolSpec(
        name="notify",
        module="system",
        description="Sends a desktop notification over D-Bus via notify-send, gdbus, or busctl to Caelestia/Hyprland.",
        handler=notify,
        pack="system",
    ),
    ToolSpec(
        name="whoami",
        module="system",
        description="Returns current user identity, UID, GID, groups, and home directory (like GNU whoami/id).",
        handler=whoami,
        pack="system",
    ),
]


def register(mcp: MCPServer) -> None:
    """Register system tools with MCPServer."""
    for spec in TOOLS:
        mcp.tool(name=spec.name, description=spec.description)(spec.handler)
