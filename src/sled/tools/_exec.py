"""Shared subprocess execution and NixOS PATH resolution helpers for Sled tools.

Ensures all subprocesses run with `stdin=subprocess.DEVNULL` so MCP `stdio` transport
streams are never polluted or blocked, and resolves binaries across NixOS system,
Home Manager per-user, and Nix profile paths.
"""

from __future__ import annotations

import getpass
import os
import shutil
import subprocess
from pathlib import Path

from prism import get_agent_env

NIXOS_EXTRA_PATHS: tuple[str, ...] = (
    "/run/wrappers/bin",
    f"/etc/profiles/per-user/{getpass.getuser()}/bin",
    str(Path.home() / ".nix-profile" / "bin"),
    str(Path.home() / ".local" / "state" / "nix" / "profile" / "bin"),
    "/nix/var/nix/profiles/default/bin",
    "/run/current-system/sw/bin",
    "/usr/bin",
    "/bin",
)


def build_search_path() -> str:
    """Construct a comprehensive PATH including NixOS system and user profile bins."""
    current = os.environ.get("PATH", "")
    parts = [p for p in current.split(":") if p]
    for extra in NIXOS_EXTRA_PATHS:
        if extra not in parts and Path(extra).is_dir():
            parts.append(extra)
    return ":".join(parts)


def which_bin(binary: str) -> str | None:
    """Resolve a binary across current PATH and standard NixOS profile directories."""
    return shutil.which(binary, path=build_search_path())


def run_cmd(
    cmd: list[str],
    cwd: Path | str | None = None,
    timeout: float = 15.0,
    extra_env: dict[str, str] | None = None,
    input_text: str | None = None,
) -> tuple[int, str, str]:
    """Run a command hermetically with stdin=/dev/null (or input_text) and NixOS PATH."""
    env = dict(os.environ)
    env["PATH"] = build_search_path()
    env.update(get_agent_env())
    if extra_env:
        env.update(extra_env)

    resolved_cmd = list(cmd)
    if resolved_cmd and "/" not in resolved_cmd[0]:
        found = which_bin(resolved_cmd[0])
        if found:
            resolved_cmd[0] = found

    try:
        proc = subprocess.run(
            resolved_cmd,
            cwd=cwd,
            env=env,
            stdin=None if input_text is not None else subprocess.DEVNULL,
            input=input_text,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return proc.returncode, proc.stdout.strip(), proc.stderr.strip()
    except subprocess.TimeoutExpired as exc:
        out = (
            (exc.stdout or b"").decode("utf-8", errors="replace")
            if isinstance(exc.stdout, bytes)
            else (exc.stdout or "")
        )
        return -1, out.strip(), f"Command timed out after {timeout}s"
    except (OSError, subprocess.SubprocessError) as exc:
        return -1, "", str(exc)
