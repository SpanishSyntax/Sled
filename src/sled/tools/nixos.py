"""Sled Pack: `nixos` — Atomic Nix, NixOS & Home Manager tools (`nixos_generations`, `nix_flake_metadata`, `nix_flake_show`, `nix_search`, `nix_eval`, `nix_store_info`, `nix_locate`)."""

from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sled.tools import ToolSpec
from sled.tools._exec import run_cmd, which_bin

if TYPE_CHECKING:
    from mcp.server import MCPServer

logger = logging.getLogger("sled.tools.nixos")

PACK = "nixos"


def _list_profile_generations(profile_dir: Path, prefix: str) -> list[dict[str, Any]]:
    """Inspect `/nix/var/nix/profiles/<prefix>-<N>-link` symlinks directly."""
    if not profile_dir.is_dir():
        return []
    current_link = profile_dir / prefix
    current_target = current_link.resolve() if current_link.exists() else None

    pattern = re.compile(rf"^{re.escape(prefix)}-(\d+)-link$")
    gens: list[dict[str, Any]] = []

    for entry in profile_dir.iterdir():
        m = pattern.match(entry.name)
        if not m:
            continue
        gen_num = int(m.group(1))
        try:
            stat = entry.lstat()
            created = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(stat.st_mtime))
            resolved = entry.resolve()
        except OSError:
            created = "unknown"
            resolved = Path()

        nixos_ver_file = resolved / "nixos-version"
        kernel_link = resolved / "kernel"
        nixos_ver = (
            nixos_ver_file.read_text(encoding="utf-8").strip()
            if nixos_ver_file.is_file()
            else None
        )
        kernel_ver = None
        if kernel_link.exists():
            try:
                k_name = kernel_link.resolve().parent.name
                kernel_ver = k_name
            except OSError:
                pass

        gens.append(
            {
                "generation": gen_num,
                "current": bool(current_target and resolved == current_target),
                "created_at": created,
                "store_path": str(resolved),
                "nixos_version": nixos_ver,
                "kernel": kernel_ver,
            }
        )

    gens.sort(key=lambda g: g["generation"], reverse=True)
    return gens


def nixos_generations(limit: int = 15) -> dict[str, Any]:
    """Lists NixOS system generations and Home Manager generations with kernel/NixOS versions.

    Args:
        limit: Maximum number of recent generations to return (default 15).
    """
    limit = max(1, min(int(limit), 50))
    sys_gens = _list_profile_generations(Path("/nix/var/nix/profiles"), "system")[
        :limit
    ]

    hm_gens: list[dict[str, Any]] = []
    hm_dirs = [
        Path.home() / ".local" / "state" / "nix" / "profiles",
        Path("/nix/var/nix/profiles/per-user") / Path.home().name,
    ]
    for d in hm_dirs:
        found = _list_profile_generations(d, "home-manager")
        if found:
            hm_gens = found[:limit]
            break

    current_sys = (
        Path("/run/current-system").resolve()
        if Path("/run/current-system").exists()
        else None
    )

    return {
        "status": "ok",
        "current_system_store_path": str(current_sys) if current_sys else None,
        "system_generations": sys_gens,
        "home_manager_generations": hm_gens,
    }


def nix_flake_metadata(flake_ref: str = ".") -> dict[str, Any]:
    """Inspects a Nix flake's metadata, revision, and locked inputs (`nix flake metadata --json`).

    Args:
        flake_ref: Path or flake URI (e.g. `.`, `/home/usurper/Glacier`, `/home/usurper/Frost`).
    """
    target = (
        str(Path(flake_ref).expanduser().resolve())
        if ":" not in flake_ref
        else flake_ref
    )
    code_meta, out_meta, err_meta = run_cmd(
        ["nix", "flake", "metadata", target, "--json"], timeout=20.0
    )
    if code_meta != 0:
        return {"status": "error", "flake_ref": target, "error": err_meta or out_meta}

    try:
        meta = json.loads(out_meta)
    except json.JSONDecodeError:
        meta = {"raw": out_meta}

    return {
        "status": "ok",
        "flake_ref": target,
        "description": meta.get("description") if isinstance(meta, dict) else None,
        "revision": meta.get("revision") if isinstance(meta, dict) else None,
        "last_modified": meta.get("lastModified") if isinstance(meta, dict) else None,
        "locks": meta.get("locks", {}).get("nodes", {})
        if isinstance(meta, dict)
        else None,
    }


def nix_flake_show(flake_ref: str = ".") -> dict[str, Any]:
    """Enumerates a Nix flake's output schema (`nix flake show --json`).

    Args:
        flake_ref: Path or flake URI (default `.`).
    """
    target = (
        str(Path(flake_ref).expanduser().resolve())
        if ":" not in flake_ref
        else flake_ref
    )
    code, out, err = run_cmd(["nix", "flake", "show", target, "--json"], timeout=25.0)
    if code != 0:
        return {"status": "error", "flake_ref": target, "error": err or out}

    try:
        outputs = json.loads(out) if out else {}
    except json.JSONDecodeError:
        outputs = {"raw": out}

    return {
        "status": "ok",
        "flake_ref": target,
        "outputs": outputs,
    }


def nix_search(
    query: str,
    flake_ref: str = "nixpkgs",
    max_results: int = 20,
    timeout: float = 60.0,
) -> dict[str, Any]:
    """Searches Nixpkgs (or any flake) for packages matching a query (`nix search --json`).

    Args:
        query: Search term or regex (e.g. `ripgrep`, `python3Packages.mcp`).
        flake_ref: Flake reference to search (default `nixpkgs`).
        max_results: Maximum packages to return (default 20, max 50).
        timeout: Evaluation timeout in seconds (default 60.0, max 300.0).
    """
    if not query.strip():
        return {"status": "error", "error": "`query` must not be empty."}

    max_results = max(1, min(int(max_results), 50))
    t_out = max(5.0, min(float(timeout), 300.0))
    code, out, err = run_cmd(
        ["nix", "search", flake_ref.strip(), query.strip(), "--json"],
        timeout=t_out,
    )
    if code != 0:
        return {"status": "error", "query": query, "error": err or out}

    try:
        raw_results = json.loads(out) if out else {}
    except json.JSONDecodeError:
        return {"status": "error", "error": "Failed to parse nix search JSON output."}

    packages: list[dict[str, Any]] = []
    for attr_path, info in list(raw_results.items())[:max_results]:
        short_attr = (
            attr_path.split(".", 2)[-1]
            if attr_path.startswith("legacyPackages.")
            else attr_path
        )
        packages.append(
            {
                "attr": short_attr,
                "pname": info.get("pname"),
                "version": info.get("version"),
                "description": info.get("description"),
            }
        )

    return {
        "status": "ok",
        "query": query,
        "flake_ref": flake_ref,
        "total_matches": len(raw_results),
        "returned": len(packages),
        "packages": packages,
    }


def nix_eval(
    installable_or_expr: str, is_expr: bool = False, apply_fn: str = ""
) -> dict[str, Any]:
    """Evaluates a Nix flake installable attribute or inline Nix expression and returns JSON (`nix eval --json`).

    Args:
        installable_or_expr: Flake installable (e.g. `/home/usurper/Glacier#nixosConfigurations.laptop.config.networking.hostName`) or Nix expression if `is_expr=True`.
        is_expr: Treat `installable_or_expr` as a raw `--expr` string instead of a flake installable (default False).
        apply_fn: Optional Nix function to apply before serializing (e.g. `builtins.attrNames`).
    """
    cmd = ["nix", "eval", "--json"]
    if is_expr:
        cmd.extend(["--impure", "--expr", installable_or_expr])
    else:
        cmd.append(installable_or_expr)
    if apply_fn.strip():
        cmd.extend(["--apply", apply_fn.strip()])

    code, out, err = run_cmd(cmd, timeout=25.0)
    if code != 0:
        return {
            "status": "error",
            "target": installable_or_expr,
            "error": err or out,
        }

    try:
        val = json.loads(out)
    except json.JSONDecodeError:
        val = out

    return {
        "status": "ok",
        "target": installable_or_expr,
        "value": val,
    }


def nix_store_info(
    target_path: str = "/run/current-system", include_closure_size: bool = True
) -> dict[str, Any]:
    """Inspects a Nix store path (`nix path-info --json`), including NAR size and total closure size.

    Args:
        target_path: Path or symlink pointing into `/nix/store` (defaults to `/run/current-system`).
        include_closure_size: Compute full closure size (`-S`, default True).
    """
    cmd = ["nix", "path-info", "--json"]
    if include_closure_size:
        cmd.append("-S")
    cmd.append(target_path.strip())

    code, out, err = run_cmd(cmd, timeout=15.0)
    if code != 0:
        return {"status": "error", "target_path": target_path, "error": err or out}

    try:
        info = json.loads(out)
    except json.JSONDecodeError:
        info = out

    return {
        "status": "ok",
        "target_path": target_path,
        "path_info": info,
    }


def nix_flake_check(
    flake_ref: str = ".",
    no_build: bool = True,
    timeout: float = 120.0,
) -> dict[str, Any]:
    """Validates and evaluates flake checks without requiring a full system build.

    Args:
        flake_ref: Flake URI or local path (default `.`).
        no_build: If True (default), check flake evaluation and lockfile without building outputs.
        timeout: Evaluation timeout in seconds (default 120.0, max 300.0).
    """
    args = ["nix", "flake", "check"]
    if no_build:
        args.append("--no-build")
    args.append(flake_ref)
    t_out = max(10.0, min(float(timeout), 300.0))
    code, stdout, stderr = run_cmd(args, timeout=t_out)
    return {
        "status": "ok" if code == 0 else "error",
        "exit_code": code,
        "flake_ref": flake_ref,
        "stdout": stdout,
        "stderr": stderr,
    }


def nix_diff_generations(
    profile: str = "system",
    gen1: int | None = None,
    gen2: int | None = None,
) -> dict[str, Any]:
    """Compares package differences and closure changes between two NixOS or Home Manager generations.

    Args:
        profile: Profile type: `system` (default) or `home-manager`.
        gen1: Earlier generation number (defaults to previous generation).
        gen2: Later generation number (defaults to latest/current generation).
    """
    prof_type = profile.strip().lower()
    if prof_type in ("system", "nixos"):
        prof_dir = Path("/nix/var/nix/profiles")
        prefix = "system"
    else:
        prefix = "home-manager"
        prof_dir = Path.home() / ".local" / "state" / "nix" / "profiles"
        if not prof_dir.is_dir():
            prof_dir = Path("/nix/var/nix/profiles/per-user") / Path.home().name

    gens = _list_profile_generations(prof_dir, prefix)
    if not gens:
        return {
            "status": "error",
            "error": f"No generations found for profile `{profile}` in {prof_dir}",
        }

    g2_entry = (
        gens[0]
        if gen2 is None
        else next((g for g in gens if g["generation"] == int(gen2)), None)
    )
    if not g2_entry:
        return {"status": "error", "error": f"Target generation {gen2} not found."}

    if gen1 is None:
        idx = gens.index(g2_entry)
        if idx + 1 < len(gens):
            g1_entry = gens[idx + 1]
        else:
            return {
                "status": "error",
                "error": "Only one generation exists in this profile; cannot compare.",
            }
    else:
        g1_entry = next((g for g in gens if g["generation"] == int(gen1)), None)
        if not g1_entry:
            return {"status": "error", "error": f"Base generation {gen1} not found."}

    p1 = g1_entry["store_path"]
    p2 = g2_entry["store_path"]

    if which_bin("nvd"):
        code, out, err = run_cmd(["nvd", "diff", p1, p2], timeout=30.0)
        tool_used = "nvd"
    else:
        code, out, err = run_cmd(
            ["nix", "store", "diff-closures", p1, p2], timeout=30.0
        )
        tool_used = "nix-store"

    return {
        "status": "ok" if code == 0 else "error",
        "profile": prefix,
        "from_generation": g1_entry["generation"],
        "to_generation": g2_entry["generation"],
        "from_path": p1,
        "to_path": p2,
        "tool": tool_used,
        "diff": out or err,
    }


def nix_build(
    installable: str = ".",
    out_link: str | None = None,
    no_link: bool = False,
    dry_run: bool = False,
    rebuild: bool = False,
    timeout: float = 300.0,
) -> dict[str, Any]:
    """Builds a Nix flake package, derivation, or installable and returns the store paths.

    Args:
        installable: Target installable, e.g. `.`, `.#pkg`, `nixpkgs#hello`, or a store path.
        out_link: Path to symlink the build output to.
        no_link: If True and out_link is None, passes `--no-link` (avoids creating `./result`).
        dry_run: If True, evaluates what would be built without building (--dry-run).
        rebuild: If True, passes `--rebuild` to rebuild derivations even if already cached.
        timeout: Maximum execution time in seconds (default 300.0s).
    """
    if not which_bin("nix"):
        return {"status": "error", "error": "nix binary not found in PATH."}

    cmd = ["nix", "build", "--print-out-paths"]
    if dry_run:
        cmd.append("--dry-run")
    elif out_link:
        cmd.extend(["--out-link", out_link])
    elif no_link:
        cmd.append("--no-link")

    if rebuild:
        cmd.append("--rebuild")

    cmd.append(installable)
    code, stdout, stderr = run_cmd(cmd, timeout=timeout)
    paths = [
        p.strip() for p in stdout.splitlines() if p.strip().startswith("/nix/store/")
    ]
    return {
        "status": "ok" if code == 0 else "error",
        "exit_code": code,
        "installable": installable,
        "paths": paths,
        "stdout": stdout,
        "stderr": stderr,
    }


def nix_locate(
    query: str,
    whole_name: bool = False,
    top_level: bool = True,
    limit: int = 25,
) -> dict[str, Any]:
    """Finds which Nixpkgs package provides a given binary, library, or file using `nix-locate` (nix-index).

    Args:
        query: Filename, binary, or path substring to locate (e.g. `bin/ripgrep`, `libssl.so`, `magika`).
        whole_name: Match full path name rather than substring (`--whole-name`, default False).
        top_level: Match only packages at the top-level of nixpkgs (`--top-level`, default True).
        limit: Maximum results to return (default 25, max 100).
    """
    q = query.strip()
    if not q:
        return {"status": "error", "error": "`query` must not be empty."}

    if not which_bin("nix-locate"):
        return {
            "status": "error",
            "error": "`nix-locate` binary not found in PATH. Enable `programs.nix-index.enable = true` in Frost.",
        }

    limit = max(1, min(int(limit), 100))
    cmd = ["nix-locate"]
    if top_level:
        cmd.append("--top-level")
    if whole_name:
        cmd.append("--whole-name")
    cmd.append(q)

    code, out, err = run_cmd(cmd, timeout=20.0)
    if code != 0:
        return {"status": "error", "query": q, "error": err or out}

    matches: list[dict[str, str]] = []
    for line in out.splitlines()[:limit]:
        parts = line.split(None, 2)
        if len(parts) >= 2:
            pkg_attr = parts[0]
            rest = parts[1:]
            matches.append(
                {
                    "package": pkg_attr,
                    "path": rest[-1] if rest else "",
                    "raw": line.strip(),
                }
            )

    return {
        "status": "ok",
        "query": q,
        "count": len(matches),
        "matches": matches,
    }


TOOLS = [
    ToolSpec(
        name="nixos_generations",
        module="nixos",
        description="Lists NixOS system generations and Home Manager generations with kernel and version info.",
        handler=nixos_generations,
        pack="nixos",
    ),
    ToolSpec(
        name="nix_flake_metadata",
        module="nixos",
        description="Inspects a Nix flake's description, revision, and locked inputs (nix flake metadata --json).",
        handler=nix_flake_metadata,
        pack="nixos",
    ),
    ToolSpec(
        name="nix_flake_show",
        module="nixos",
        description="Enumerates a Nix flake's output schema (nix flake show --json).",
        handler=nix_flake_show,
        pack="nixos",
    ),
    ToolSpec(
        name="nix_search",
        module="nixos",
        description="Searches nixpkgs (or a target flake) for packages matching a query and returns JSON metadata.",
        handler=nix_search,
        pack="nixos",
    ),
    ToolSpec(
        name="nix_eval",
        module="nixos",
        description="Evaluates a Nix flake attribute or inline Nix expression and returns JSON (nix eval --json).",
        handler=nix_eval,
        pack="nixos",
    ),
    ToolSpec(
        name="nix_store_info",
        module="nixos",
        description="Inspects Nix store path metadata, NAR size, closure size, and derivers (nix path-info).",
        handler=nix_store_info,
        pack="nixos",
    ),
    ToolSpec(
        name="nix_flake_check",
        module="nixos",
        description="Validates and evaluates flake checks without requiring a full system build.",
        handler=nix_flake_check,
        pack="nixos",
    ),
    ToolSpec(
        name="nix_diff_generations",
        module="nixos",
        description="Compares package differences and closure changes between two NixOS or Home Manager generations.",
        handler=nix_diff_generations,
        pack="nixos",
    ),
    ToolSpec(
        name="nix_locate",
        module="nixos",
        description="Finds which Nixpkgs package provides a binary, library, or file via nix-locate (nix-index).",
        handler=nix_locate,
        pack="nixos",
    ),
    ToolSpec(
        name="nix_build",
        module="nixos",
        description="Builds a Nix flake package, derivation, or installable and returns the store paths.",
        handler=nix_build,
        pack="nixos",
    ),
]


def register(mcp: MCPServer) -> None:
    """Register Nix/NixOS tools with MCPServer."""
    for spec in TOOLS:
        mcp.tool(name=spec.name, description=spec.description)(spec.handler)
