"""Sled Pack: `docker` — Atomic Docker & Podman tools (`docker_ps`, `docker_logs`, `docker_inspect`, `docker_stats`, `docker_images`, `docker_volumes`, `docker_networks`, `docker_start`, `docker_stop`, `docker_restart`, `docker_pause`, `docker_unpause`, `docker_compose_ps`, `docker_compose_logs`, `docker_compose_config`, `docker_compose_up`, `docker_compose_down`, `docker_compose_restart`)."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sled.tools import ToolSpec
from sled.tools._exec import run_cmd, which_bin

if TYPE_CHECKING:
    from mcp.server import MCPServer

logger = logging.getLogger("sled.tools.docker")

PACK = "docker"


def _detect_engine() -> str | None:
    """Detect available container runtime (`docker` or `podman`)."""
    for candidate in ("docker", "podman"):
        if which_bin(candidate):
            return candidate
    return None


def _parse_json_lines(raw: str) -> list[Any]:
    """Parse newline-delimited JSON objects or a JSON array emitted by docker/podman CLI."""
    raw = raw.strip()
    if not raw:
        return []
    if raw.startswith("["):
        try:
            data = json.loads(raw)
            return data if isinstance(data, list) else [data]
        except json.JSONDecodeError:
            pass
    items: list[Any] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            items.append(json.loads(line))
        except json.JSONDecodeError:
            items.append({"raw": line})
    return items


def docker_ps(all_containers: bool = True, compact: bool = True) -> dict[str, Any]:
    """Lists Docker/Podman containers with status, image, ports, and names.

    Args:
        all_containers: Include stopped/exited containers as well as running ones (default True).
        compact: Return tabular `columns` and `rows` to minimize token overhead (default True).
    """
    engine = _detect_engine()
    if not engine:
        return {
            "status": "error",
            "error": "Neither `docker` nor `podman` found in PATH.",
        }

    cmd = [engine, "ps", "--format", "json"]
    if all_containers:
        cmd.insert(2, "-a")

    code, out, err = run_cmd(cmd, timeout=10.0)
    if code != 0:
        return {"status": "error", "engine": engine, "error": err or out}

    containers = _parse_json_lines(out)
    if not containers:
        return {"status": "ok", "engine": engine, "count": 0, "containers": []}

    if compact:
        columns = ["id", "image", "status", "names", "ports"]
        rows: list[list[str]] = []
        for c in containers:
            if isinstance(c, dict):
                c_id = str(c.get("ID", c.get("Id", "")))[:12]
                img = str(c.get("Image", ""))
                st = str(c.get("Status", c.get("State", "")))
                names = str(c.get("Names", ""))
                ports = str(c.get("Ports", ""))
                rows.append([c_id, img, st, names, ports])
        return {
            "status": "ok",
            "engine": engine,
            "count": len(rows),
            "columns": columns,
            "rows": rows,
        }

    return {
        "status": "ok",
        "engine": engine,
        "count": len(containers),
        "containers": containers,
    }


def docker_logs(container: str, tail: int = 100, since: str = "") -> dict[str, Any]:
    """Fetches recent stdout/stderr logs from a Docker/Podman container.

    Args:
        container: Container name or ID.
        tail: Number of lines from the end of the logs to return (default 100, max 1000).
        since: Optional relative duration (e.g. `10m`, `1h`) or ISO timestamp.
    """
    engine = _detect_engine()
    if not engine:
        return {
            "status": "error",
            "error": "Neither `docker` nor `podman` found in PATH.",
        }

    tail = max(1, min(int(tail), 1000))
    cmd = [engine, "logs", "--tail", str(tail)]
    if since.strip():
        cmd.extend(["--since", since.strip()])
    cmd.append(container)

    code, out, err = run_cmd(cmd, timeout=10.0)
    if code != 0:
        return {"status": "error", "container": container, "error": err or out}

    combined = "\n".join(part for part in (out, err) if part)
    return {
        "status": "ok",
        "engine": engine,
        "container": container,
        "lines_requested": tail,
        "logs": combined,
    }


def docker_inspect(target: str) -> dict[str, Any]:
    """Inspects low-level configuration and state of a Docker container, image, volume, or network.

    Args:
        target: Name or ID of the container, image, volume, or network.
    """
    engine = _detect_engine()
    if not engine:
        return {
            "status": "error",
            "error": "Neither `docker` nor `podman` found in PATH.",
        }

    code, out, err = run_cmd([engine, "inspect", target], timeout=10.0)
    if code != 0:
        return {"status": "error", "target": target, "error": err or out}

    try:
        parsed = json.loads(out)
    except json.JSONDecodeError:
        parsed = out

    return {
        "status": "ok",
        "engine": engine,
        "target": target,
        "inspect": parsed,
    }


def docker_stats() -> dict[str, Any]:
    """Returns a one-shot snapshot of CPU, memory, network, and block I/O usage for running containers."""
    engine = _detect_engine()
    if not engine:
        return {
            "status": "error",
            "error": "Neither `docker` nor `podman` found in PATH.",
        }

    code, out, err = run_cmd(
        [engine, "stats", "--no-stream", "--format", "json"], timeout=12.0
    )
    if code != 0:
        return {"status": "error", "engine": engine, "error": err or out}

    return {
        "status": "ok",
        "engine": engine,
        "stats": _parse_json_lines(out),
    }


def docker_images() -> dict[str, Any]:
    """Lists local Docker/Podman container images with repository, tag, ID, and size."""
    engine = _detect_engine()
    if not engine:
        return {
            "status": "error",
            "error": "Neither `docker` nor `podman` found in PATH.",
        }

    code, out, err = run_cmd([engine, "images", "--format", "json"], timeout=10.0)
    if code != 0:
        return {"status": "error", "engine": engine, "error": err or out}

    images = _parse_json_lines(out)
    return {
        "status": "ok",
        "engine": engine,
        "count": len(images),
        "images": images,
    }


def docker_volumes() -> dict[str, Any]:
    """Lists Docker/Podman volumes."""
    engine = _detect_engine()
    if not engine:
        return {
            "status": "error",
            "error": "Neither `docker` nor `podman` found in PATH.",
        }

    code, out, err = run_cmd([engine, "volume", "ls", "--format", "json"], timeout=10.0)
    if code != 0:
        return {"status": "error", "engine": engine, "error": err or out}

    volumes = _parse_json_lines(out)
    return {
        "status": "ok",
        "engine": engine,
        "count": len(volumes),
        "volumes": volumes,
    }


def docker_networks() -> dict[str, Any]:
    """Lists Docker/Podman networks."""
    engine = _detect_engine()
    if not engine:
        return {
            "status": "error",
            "error": "Neither `docker` nor `podman` found in PATH.",
        }

    code, out, err = run_cmd(
        [engine, "network", "ls", "--format", "json"], timeout=10.0
    )
    if code != 0:
        return {"status": "error", "engine": engine, "error": err or out}

    networks = _parse_json_lines(out)
    return {
        "status": "ok",
        "engine": engine,
        "count": len(networks),
        "networks": networks,
    }


def docker_start(container: str) -> dict[str, Any]:
    """Starts one or more stopped Docker/Podman containers.

    Args:
        container: Container name or ID.
    """
    engine = _detect_engine()
    if not engine:
        return {
            "status": "error",
            "error": "Neither `docker` nor `podman` found in PATH.",
        }
    if not container.strip():
        return {"status": "error", "error": "`container` name or ID is required."}

    code, out, err = run_cmd([engine, "start", container.strip()], timeout=20.0)
    return {
        "status": "ok" if code == 0 else "error",
        "engine": engine,
        "container": container.strip(),
        "output": out.strip(),
        "error": err if code != 0 else None,
    }


def docker_stop(container: str, timeout: int = 10) -> dict[str, Any]:
    """Stops a running Docker/Podman container.

    Args:
        container: Container name or ID.
        timeout: Seconds to wait for stop before killing (default 10).
    """
    engine = _detect_engine()
    if not engine:
        return {
            "status": "error",
            "error": "Neither `docker` nor `podman` found in PATH.",
        }
    if not container.strip():
        return {"status": "error", "error": "`container` name or ID is required."}

    code, out, err = run_cmd(
        [engine, "stop", "-t", str(max(1, int(timeout))), container.strip()],
        timeout=float(timeout) + 10.0,
    )
    return {
        "status": "ok" if code == 0 else "error",
        "engine": engine,
        "container": container.strip(),
        "output": out.strip(),
        "error": err if code != 0 else None,
    }


def docker_restart(container: str, timeout: int = 10) -> dict[str, Any]:
    """Restarts a running or stopped Docker/Podman container.

    Args:
        container: Container name or ID.
        timeout: Seconds to wait for stop before killing (default 10).
    """
    engine = _detect_engine()
    if not engine:
        return {
            "status": "error",
            "error": "Neither `docker` nor `podman` found in PATH.",
        }
    if not container.strip():
        return {"status": "error", "error": "`container` name or ID is required."}

    code, out, err = run_cmd(
        [engine, "restart", "-t", str(max(1, int(timeout))), container.strip()],
        timeout=float(timeout) + 10.0,
    )
    return {
        "status": "ok" if code == 0 else "error",
        "engine": engine,
        "container": container.strip(),
        "output": out.strip(),
        "error": err if code != 0 else None,
    }


def docker_pause(container: str) -> dict[str, Any]:
    """Pauses all processes within one or more containers.

    Args:
        container: Container name or ID.
    """
    engine = _detect_engine()
    if not engine:
        return {
            "status": "error",
            "error": "Neither `docker` nor `podman` found in PATH.",
        }
    if not container.strip():
        return {"status": "error", "error": "`container` name or ID is required."}

    code, out, err = run_cmd([engine, "pause", container.strip()], timeout=15.0)
    return {
        "status": "ok" if code == 0 else "error",
        "engine": engine,
        "container": container.strip(),
        "output": out.strip(),
        "error": err if code != 0 else None,
    }


def docker_unpause(container: str) -> dict[str, Any]:
    """Unpauses all processes within one or more paused containers.

    Args:
        container: Container name or ID.
    """
    engine = _detect_engine()
    if not engine:
        return {
            "status": "error",
            "error": "Neither `docker` nor `podman` found in PATH.",
        }
    if not container.strip():
        return {"status": "error", "error": "`container` name or ID is required."}

    code, out, err = run_cmd([engine, "unpause", container.strip()], timeout=15.0)
    return {
        "status": "ok" if code == 0 else "error",
        "engine": engine,
        "container": container.strip(),
        "output": out.strip(),
        "error": err if code != 0 else None,
    }


def docker_action(container: str, action: str = "restart") -> dict[str, Any]:
    """Starts, stops, restarts, pauses, or unpauses a Docker/Podman container."""
    act = action.strip().lower()
    if act == "start":
        return docker_start(container=container)
    if act == "stop":
        return docker_stop(container=container)
    if act == "restart":
        return docker_restart(container=container)
    if act == "pause":
        return docker_pause(container=container)
    if act == "unpause":
        return docker_unpause(container=container)
    return {"status": "error", "error": f"Unsupported action '{action}'."}


def docker_compose_ps(project_dir: str = ".", service: str = "") -> dict[str, Any]:
    """Lists containers for a Docker Compose project in JSON format (`docker compose ps`).

    Args:
        project_dir: Directory containing `compose.yaml` or `docker-compose.yml` (default `.`).
        service: Optional specific service name to filter.
    """
    engine = _detect_engine()
    if not engine:
        return {
            "status": "error",
            "error": "Neither `docker` nor `podman` found in PATH.",
        }

    cwd = Path(project_dir).expanduser().resolve()
    if not cwd.is_dir():
        return {"status": "error", "error": f"Directory does not exist: {cwd}"}

    cmd = [engine, "compose", "ps", "--format", "json"]
    if service.strip():
        cmd.append(service.strip())

    code, out, err = run_cmd(cmd, cwd=cwd, timeout=15.0)
    if code != 0:
        return {"status": "error", "project_dir": str(cwd), "error": err or out}

    containers = _parse_json_lines(out)
    return {
        "status": "ok",
        "engine": engine,
        "project_dir": str(cwd),
        "count": len(containers),
        "containers": containers,
    }


def docker_compose_logs(
    project_dir: str = ".",
    service: str = "",
    tail: int = 100,
) -> dict[str, Any]:
    """Fetches output logs for Docker Compose services (`docker compose logs`).

    Args:
        project_dir: Directory containing `compose.yaml` or `docker-compose.yml` (default `.`).
        service: Optional specific service name to filter logs.
        tail: Number of lines to show from the end of the logs (default 100, max 1000).
    """
    engine = _detect_engine()
    if not engine:
        return {
            "status": "error",
            "error": "Neither `docker` nor `podman` found in PATH.",
        }

    cwd = Path(project_dir).expanduser().resolve()
    if not cwd.is_dir():
        return {"status": "error", "error": f"Directory does not exist: {cwd}"}

    tail = max(1, min(int(tail), 1000))
    cmd = [engine, "compose", "logs", "--tail", str(tail), "--no-color"]
    if service.strip():
        cmd.append(service.strip())

    code, out, err = run_cmd(cmd, cwd=cwd, timeout=20.0)
    return {
        "status": "ok" if code == 0 else "error",
        "engine": engine,
        "project_dir": str(cwd),
        "service": service.strip() or None,
        "logs": out or err,
        "error": err if code != 0 else None,
    }


def docker_compose_config(project_dir: str = ".") -> dict[str, Any]:
    """Validates and lists configured services in a compose file (`docker compose config --services`).

    Args:
        project_dir: Directory containing `compose.yaml` or `docker-compose.yml` (default `.`).
    """
    engine = _detect_engine()
    if not engine:
        return {
            "status": "error",
            "error": "Neither `docker` nor `podman` found in PATH.",
        }

    cwd = Path(project_dir).expanduser().resolve()
    if not cwd.is_dir():
        return {"status": "error", "error": f"Directory does not exist: {cwd}"}

    code, out, err = run_cmd(
        [engine, "compose", "config", "--services"], cwd=cwd, timeout=15.0
    )
    if code != 0:
        return {"status": "error", "project_dir": str(cwd), "error": err or out}

    services = [s.strip() for s in out.splitlines() if s.strip()]
    return {
        "status": "ok",
        "engine": engine,
        "project_dir": str(cwd),
        "services": services,
    }


def docker_compose_up(
    project_dir: str = ".",
    detach: bool = True,
    service: str = "",
) -> dict[str, Any]:
    """Builds, (re)creates, and starts containers for a compose project (`docker compose up -d`).

    Args:
        project_dir: Directory containing `compose.yaml` or `docker-compose.yml` (default `.`).
        detach: Run containers in the background (default True).
        service: Optional specific service to start.
    """
    engine = _detect_engine()
    if not engine:
        return {
            "status": "error",
            "error": "Neither `docker` nor `podman` found in PATH.",
        }

    cwd = Path(project_dir).expanduser().resolve()
    if not cwd.is_dir():
        return {"status": "error", "error": f"Directory does not exist: {cwd}"}

    cmd = [engine, "compose", "up"]
    if detach:
        cmd.append("-d")
    if service.strip():
        cmd.append(service.strip())

    code, out, err = run_cmd(cmd, cwd=cwd, timeout=120.0)
    return {
        "status": "ok" if code == 0 else "error",
        "engine": engine,
        "project_dir": str(cwd),
        "stdout": out,
        "stderr": err if err else None,
    }


def docker_compose_down(
    project_dir: str = ".",
    remove_volumes: bool = False,
) -> dict[str, Any]:
    """Stops containers and removes containers, networks created by `up` (`docker compose down`).

    Args:
        project_dir: Directory containing `compose.yaml` or `docker-compose.yml` (default `.`).
        remove_volumes: Remove named volumes declared in `volumes` section (`-v`, default False).
    """
    engine = _detect_engine()
    if not engine:
        return {
            "status": "error",
            "error": "Neither `docker` nor `podman` found in PATH.",
        }

    cwd = Path(project_dir).expanduser().resolve()
    if not cwd.is_dir():
        return {"status": "error", "error": f"Directory does not exist: {cwd}"}

    cmd = [engine, "compose", "down"]
    if remove_volumes:
        cmd.append("-v")

    code, out, err = run_cmd(cmd, cwd=cwd, timeout=60.0)
    return {
        "status": "ok" if code == 0 else "error",
        "engine": engine,
        "project_dir": str(cwd),
        "stdout": out,
        "stderr": err if err else None,
    }


def docker_compose_restart(
    project_dir: str = ".",
    service: str = "",
) -> dict[str, Any]:
    """Restarts running compose containers (`docker compose restart`).

    Args:
        project_dir: Directory containing `compose.yaml` or `docker-compose.yml` (default `.`).
        service: Optional specific service to restart.
    """
    engine = _detect_engine()
    if not engine:
        return {
            "status": "error",
            "error": "Neither `docker` nor `podman` found in PATH.",
        }

    cwd = Path(project_dir).expanduser().resolve()
    if not cwd.is_dir():
        return {"status": "error", "error": f"Directory does not exist: {cwd}"}

    cmd = [engine, "compose", "restart"]
    if service.strip():
        cmd.append(service.strip())

    code, out, err = run_cmd(cmd, cwd=cwd, timeout=60.0)
    return {
        "status": "ok" if code == 0 else "error",
        "engine": engine,
        "project_dir": str(cwd),
        "stdout": out,
        "stderr": err if err else None,
    }


def docker_compose(
    project_dir: str = ".", action: str = "ps", service: str = ""
) -> dict[str, Any]:
    """Runs Docker Compose operations in a directory."""
    act = action.strip().lower()
    if act == "ps":
        return docker_compose_ps(project_dir=project_dir, service=service)
    if act == "logs":
        return docker_compose_logs(project_dir=project_dir, service=service)
    if act == "config":
        return docker_compose_config(project_dir=project_dir)
    if act == "up":
        return docker_compose_up(project_dir=project_dir, service=service)
    if act == "down":
        return docker_compose_down(project_dir=project_dir)
    if act == "restart":
        return docker_compose_restart(project_dir=project_dir, service=service)
    return {"status": "error", "error": f"Unsupported compose action '{action}'."}


TOOLS = [
    ToolSpec(
        name="docker_ps",
        module="docker",
        description="Lists Docker/Podman containers with status, image, ports, and names.",
        handler=docker_ps,
        pack="docker",
    ),
    ToolSpec(
        name="docker_logs",
        module="docker",
        description="Fetches recent stdout/stderr logs from a Docker/Podman container.",
        handler=docker_logs,
        pack="docker",
    ),
    ToolSpec(
        name="docker_inspect",
        module="docker",
        description="Inspects low-level JSON configuration and state of a container, image, volume, or network.",
        handler=docker_inspect,
        pack="docker",
    ),
    ToolSpec(
        name="docker_stats",
        module="docker",
        description="Returns a one-shot snapshot of CPU, memory, and I/O usage for running containers.",
        handler=docker_stats,
        pack="docker",
    ),
    ToolSpec(
        name="docker_images",
        module="docker",
        description="Lists local Docker/Podman container images with repository, tag, and size.",
        handler=docker_images,
        pack="docker",
    ),
    ToolSpec(
        name="docker_volumes",
        module="docker",
        description="Lists Docker/Podman container volumes.",
        handler=docker_volumes,
        pack="docker",
    ),
    ToolSpec(
        name="docker_networks",
        module="docker",
        description="Lists Docker/Podman container networks.",
        handler=docker_networks,
        pack="docker",
    ),
    ToolSpec(
        name="docker_start",
        module="docker",
        description="Starts one or more stopped Docker/Podman containers.",
        handler=docker_start,
        pack="docker",
    ),
    ToolSpec(
        name="docker_stop",
        module="docker",
        description="Stops a running Docker/Podman container.",
        handler=docker_stop,
        pack="docker",
    ),
    ToolSpec(
        name="docker_restart",
        module="docker",
        description="Restarts a running or stopped Docker/Podman container.",
        handler=docker_restart,
        pack="docker",
    ),
    ToolSpec(
        name="docker_pause",
        module="docker",
        description="Pauses all processes within one or more containers.",
        handler=docker_pause,
        pack="docker",
    ),
    ToolSpec(
        name="docker_unpause",
        module="docker",
        description="Unpauses all processes within one or more paused containers.",
        handler=docker_unpause,
        pack="docker",
    ),
    ToolSpec(
        name="docker_compose_ps",
        module="docker",
        description="Lists containers for a Docker Compose project in JSON format (docker compose ps).",
        handler=docker_compose_ps,
        pack="docker",
    ),
    ToolSpec(
        name="docker_compose_logs",
        module="docker",
        description="Fetches output logs for Docker Compose services (docker compose logs).",
        handler=docker_compose_logs,
        pack="docker",
    ),
    ToolSpec(
        name="docker_compose_config",
        module="docker",
        description="Validates and lists configured services in a compose file (docker compose config).",
        handler=docker_compose_config,
        pack="docker",
    ),
    ToolSpec(
        name="docker_compose_up",
        module="docker",
        description="Builds, (re)creates, and starts containers for a compose project (docker compose up -d).",
        handler=docker_compose_up,
        pack="docker",
    ),
    ToolSpec(
        name="docker_compose_down",
        module="docker",
        description="Stops containers and removes containers, networks created by up (docker compose down).",
        handler=docker_compose_down,
        pack="docker",
    ),
    ToolSpec(
        name="docker_compose_restart",
        module="docker",
        description="Restarts running compose containers (docker compose restart).",
        handler=docker_compose_restart,
        pack="docker",
    ),
    ToolSpec(
        name="docker_action",
        module="docker",
        description="Starts, stops, restarts, pauses, or unpauses a Docker/Podman container (delegates to atomic tools).",
        handler=docker_action,
        pack="docker",
    ),
    ToolSpec(
        name="docker_compose",
        module="docker",
        description="Runs Docker Compose operations in a directory (delegates to atomic tools).",
        handler=docker_compose,
        pack="docker",
    ),
]


def register(mcp: MCPServer) -> None:
    """Register Docker tools with MCPServer."""
    for spec in TOOLS:
        mcp.tool(name=spec.name, description=spec.description)(spec.handler)
