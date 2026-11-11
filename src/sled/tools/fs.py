"""Sled Pack: `fs` — Atomic filesystem and text inspection tools (`ls`, `cat`, `head`, `tail`, `find`, `grep`, `stat`, `tree`, `jq`, `checksum`, `detect_type`, `wc`, `du`, `realpath`, `mkdir`, `trash_put`)."""

from __future__ import annotations

import base64
import fnmatch
import grp
import hashlib
import json
import logging
import mimetypes
import os
import pwd
import re
import shutil
import stat as stat_mod
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sled.tools import ToolSpec
from sled.tools._exec import run_cmd, which_bin

if TYPE_CHECKING:
    from mcp.server import MCPServer

logger = logging.getLogger("sled.tools.fs")

PACK = "fs"

IGNORED_DIRS = {
    ".git",
    ".direnv",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "node_modules",
    "result",
    "target",
    "dist",
    "build",
    ".venv",
    "venv",
}


def _format_mode(mode: int) -> str:
    return stat_mod.filemode(mode)


def _entry_type(st_mode: int) -> str:
    if stat_mod.S_ISDIR(st_mode):
        return "dir"
    if stat_mod.S_ISLNK(st_mode):
        return "symlink"
    if stat_mod.S_ISREG(st_mode):
        return "file"
    if stat_mod.S_ISSOCK(st_mode):
        return "socket"
    if stat_mod.S_ISFIFO(st_mode):
        return "fifo"
    return "other"


def ls(path: str = ".", all_files: bool = False, long: bool = False) -> dict[str, Any]:
    """Lists directory entries (files, directories, symlinks) with optional permissions, sizes, and timestamps.

    Args:
        path: Directory or file path to list (default `.`).
        all_files: Include hidden dotfiles starting with `.` (like `ls -a`, default False).
        long: Include mode, size, and modification time details (like `ls -l`, default False).
    """
    target = Path(path).expanduser().resolve()
    if not target.exists():
        return {"status": "error", "error": f"Path does not exist: {target}"}

    if not target.is_dir():
        if not long:
            return {
                "status": "ok",
                "path": str(target),
                "count": 1,
                "entries": [target.name],
            }
        st = target.lstat()
        return {
            "status": "ok",
            "path": str(target),
            "count": 1,
            "entries": [
                {
                    "name": target.name,
                    "type": _entry_type(st.st_mode),
                    "size_bytes": st.st_size,
                    "mode": _format_mode(st.st_mode),
                }
            ],
        }

    try:
        children = sorted(
            target.iterdir(),
            key=lambda p: (not p.is_dir(), p.name.lower()),
        )
    except PermissionError:
        return {"status": "error", "error": f"Permission denied: {target}"}

    if not long:
        simple_entries: list[str] = []
        for child in children:
            if not all_files and child.name.startswith("."):
                continue
            try:
                is_d = child.is_dir()
                simple_entries.append(child.name + ("/" if is_d else ""))
            except OSError:
                simple_entries.append(child.name)
        return {
            "status": "ok",
            "path": str(target),
            "count": len(simple_entries),
            "entries": simple_entries[:500],
        }

    entries: list[dict[str, Any]] = []
    for child in children:
        if not all_files and child.name.startswith("."):
            continue
        try:
            st = child.lstat()
            item: dict[str, Any] = {
                "name": child.name + ("/" if stat_mod.S_ISDIR(st.st_mode) else ""),
                "type": _entry_type(st.st_mode),
                "mode": _format_mode(st.st_mode),
                "size_bytes": st.st_size,
                "modified": time.strftime(
                    "%Y-%m-%d %H:%M:%S", time.localtime(st.st_mtime)
                ),
            }
            if stat_mod.S_ISLNK(st.st_mode):
                try:
                    item["target"] = os.readlink(child)
                except OSError:
                    pass
            entries.append(item)
        except OSError as exc:
            entries.append({"name": child.name, "error": str(exc)})

    return {
        "status": "ok",
        "path": str(target),
        "count": len(entries),
        "entries": entries[:500],
    }


def cat(path: str, start_line: int = 1, end_line: int = 500) -> dict[str, Any]:
    """Reads text contents of a file, optionally sliced by 1-indexed line range.

    Args:
        path: Path to the file to read.
        start_line: Starting line number, 1-indexed (default 1).
        end_line: Ending line number, inclusive (default 500, max 2000).
    """
    target = Path(path).expanduser().resolve()
    if not target.exists():
        return {"status": "error", "error": f"File does not exist: {target}"}
    if not target.is_file():
        return {"status": "error", "error": f"Not a regular file: {target}"}

    start_line = max(1, int(start_line))
    end_line = max(start_line, min(int(end_line), start_line + 2000))

    try:
        raw = target.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return {"status": "error", "error": str(exc)}

    all_lines = raw.splitlines()
    selected = all_lines[start_line - 1 : end_line]

    return {
        "status": "ok",
        "path": str(target),
        "total_lines": len(all_lines),
        "start_line": start_line,
        "end_line": min(end_line, len(all_lines)),
        "content": "\n".join(selected),
    }


def head(path: str, lines: int = 20) -> dict[str, Any]:
    """Returns the first N lines of a file.

    Args:
        path: Path to the file.
        lines: Number of lines from the start of the file (default 20, max 500).
    """
    n = max(1, min(int(lines), 500))
    return cat(path=path, start_line=1, end_line=n)


def tail(path: str, lines: int = 20) -> dict[str, Any]:
    """Returns the last N lines of a file.

    Args:
        path: Path to the file.
        lines: Number of lines from the end of the file (default 20, max 500).
    """
    target = Path(path).expanduser().resolve()
    if not target.exists():
        return {"status": "error", "error": f"File does not exist: {target}"}
    if not target.is_file():
        return {"status": "error", "error": f"Not a regular file: {target}"}

    n = max(1, min(int(lines), 500))
    try:
        all_lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        return {"status": "error", "error": str(exc)}

    selected = all_lines[-n:] if all_lines else []
    start = max(1, len(all_lines) - len(selected) + 1)
    return {
        "status": "ok",
        "path": str(target),
        "total_lines": len(all_lines),
        "start_line": start,
        "end_line": len(all_lines),
        "content": "\n".join(selected),
    }


def find(
    path: str = ".",
    pattern: str = "*",
    file_type: str = "all",
    max_depth: int = 4,
    include_hidden: bool = False,
    use_fd: bool = True,
) -> dict[str, Any]:
    """Finds files or directories matching a glob pattern under a root directory.

    Args:
        path: Root directory to search from (default `.`).
        pattern: Glob pattern to match filenames against (e.g. `*.nix`, `*.py`, `*config*`, default `*`).
        file_type: Filter by `all` (default), `file`, or `dir`.
        max_depth: Maximum directory traversal depth (default 4, max 10).
        include_hidden: Include hidden files and directories (default False).
        use_fd: Use `fd` accelerator if available for fast .gitignore-aware searches (default True).
    """
    root = Path(path).expanduser().resolve()
    if not root.is_dir():
        return {"status": "error", "error": f"Not a directory: {root}"}

    max_depth = max(1, min(int(max_depth), 10))
    ft = file_type.strip().lower()

    if use_fd and which_bin("fd"):
        cmd = ["fd", "--max-depth", str(max_depth)]
        if ft in ("f", "file"):
            cmd.extend(["-t", "f"])
        elif ft in ("d", "dir", "directory"):
            cmd.extend(["-t", "d"])
        if include_hidden:
            cmd.append("-H")
        if pattern != "*":
            cmd.extend(["--glob", pattern, str(root)])
        else:
            cmd.extend([".", str(root)])
        code, stdout, _ = run_cmd(cmd, timeout=15.0)
        if code == 0:
            lines = [line.strip() for line in stdout.splitlines() if line.strip()]
            fd_matches: list[str] = []
            for line in lines[:500]:
                p = Path(line)
                try:
                    rel = str(p.relative_to(root)) + ("/" if p.is_dir() else "")
                except ValueError:
                    rel = line
                fd_matches.append(rel)
            return {
                "status": "ok",
                "engine": "fd",
                "root": str(root),
                "pattern": pattern,
                "file_type": ft,
                "count": len(fd_matches),
                "matches": fd_matches,
            }

    matches: list[str] = []

    def _walk(current: Path, depth: int) -> None:
        if depth > max_depth or len(matches) >= 500:
            return
        try:
            entries = sorted(current.iterdir(), key=lambda p: p.name.lower())
        except OSError:
            return

        for entry in entries:
            if not include_hidden and entry.name.startswith("."):
                continue
            if entry.name in IGNORED_DIRS and not include_hidden:
                continue

            is_dir = entry.is_dir()
            type_ok = (
                ft == "all"
                or (ft in ("f", "file") and entry.is_file())
                or (ft in ("d", "dir", "directory") and is_dir)
            )
            if type_ok and fnmatch.fnmatch(entry.name.lower(), pattern.lower()):
                rel = str(entry.relative_to(root)) + ("/" if is_dir else "")
                matches.append(rel)
                if len(matches) >= 500:
                    return

            if is_dir and not entry.is_symlink():
                _walk(entry, depth + 1)

    _walk(root, 1)
    return {
        "status": "ok",
        "engine": "python",
        "root": str(root),
        "pattern": pattern,
        "count": len(matches),
        "matches": matches,
    }


def _get_context(file_path: Path, match_line: int, n_ctx: int) -> list[dict[str, Any]]:
    if n_ctx <= 0:
        return []
    try:
        lines = file_path.read_text(encoding="utf-8", errors="replace").splitlines()
        start = max(1, match_line - n_ctx)
        end = min(len(lines), match_line + n_ctx)
        return [
            {
                "line": lno,
                "text": lines[lno - 1][:300],
                "is_match": lno == match_line,
            }
            for lno in range(start, end + 1)
        ]
    except OSError:
        return []


def grep(
    pattern: str,
    path: str = ".",
    glob: str = "*",
    ignore_case: bool = False,
    max_results: int = 100,
    context_lines: int = 0,
    use_ripgrep: bool = True,
    compact: bool = True,
) -> dict[str, Any]:
    """Searches file contents for a regular expression or substring pattern with optional context lines.

    Args:
        pattern: Regular expression or literal text to search for.
        path: File or directory path to search within (default `.`).
        glob: Optional filename glob filter when searching a directory (e.g. `*.py`, `*.nix`).
        ignore_case: Case-insensitive matching (default False).
        max_results: Maximum matching lines to return (default 100, max 500).
        context_lines: Number of surrounding context lines to include before and after each match (default 0, max 10).
        use_ripgrep: Use `ripgrep` accelerator if available for fast .gitignore-aware searching (default True).
        compact: Return concise `file:line: text` lines to minimize token usage (default True when context_lines=0).
    """
    if not pattern:
        return {"status": "error", "error": "`pattern` must not be empty."}

    target = Path(path).expanduser().resolve()
    if not target.exists():
        return {"status": "error", "error": f"Path does not exist: {target}"}

    max_results = max(1, min(int(max_results), 500))
    n_ctx = max(0, min(int(context_lines), 10))
    use_compact = compact and n_ctx == 0

    if use_ripgrep and which_bin("rg"):
        cmd = ["rg", "--json", "--max-count", str(max_results)]
        if ignore_case:
            cmd.append("-i")
        if glob != "*":
            cmd.extend(["--glob", glob])
        cmd.extend(["--", pattern, str(target)])

        code, stdout, _ = run_cmd(cmd, timeout=30.0)
        if code in (0, 1):
            rg_results: list[Any] = []
            for raw_line in stdout.splitlines():
                if len(rg_results) >= max_results:
                    break
                try:
                    item = json.loads(raw_line)
                    if item.get("type") == "match":
                        data = item.get("data", {})
                        p = data.get("path", {}).get("text", "")
                        try:
                            rel_p = (
                                str(Path(p).relative_to(target))
                                if target.is_dir()
                                else Path(p).name
                            )
                        except ValueError:
                            rel_p = p
                        l_num = data.get("line_number", 0)
                        match_text = data.get("lines", {}).get("text", "").strip()[:300]
                        if use_compact:
                            rg_results.append(f"{rel_p}:{l_num}: {match_text}")
                        else:
                            entry: dict[str, Any] = {
                                "file": rel_p,
                                "line": l_num,
                                "text": match_text,
                            }
                            if n_ctx > 0:
                                entry["context"] = _get_context(Path(p), l_num, n_ctx)
                            rg_results.append(entry)
                except (json.JSONDecodeError, KeyError, ValueError):
                    continue

            return {
                "status": "ok",
                "engine": "ripgrep",
                "path": str(target),
                "pattern": pattern,
                "count": len(rg_results),
                "matches": rg_results,
            }

    flags = re.IGNORECASE if ignore_case else 0
    try:
        regex = re.compile(pattern, flags)
    except re.error:
        regex = re.compile(re.escape(pattern), flags)

    results: list[dict[str, Any]] = []

    def _search_file(file_path: Path, rel_display: str) -> None:
        if len(results) >= max_results:
            return
        try:
            if file_path.stat().st_size > 2 * 1024 * 1024:
                return
            text = file_path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return

        for lineno, line in enumerate(text.splitlines(), 1):
            if regex.search(line):
                match_text = line.strip()[:300]
                if use_compact:
                    results.append(f"{rel_display}:{lineno}: {match_text}")
                else:
                    py_entry: dict[str, Any] = {
                        "file": rel_display,
                        "line": lineno,
                        "text": match_text,
                    }
                    if n_ctx > 0:
                        py_entry["context"] = _get_context(file_path, lineno, n_ctx)
                    results.append(py_entry)
                if len(results) >= max_results:
                    return

    if target.is_file():
        _search_file(target, target.name)
    else:
        for root_dir, dirs, files in os.walk(target):
            dirs[:] = [
                d
                for d in sorted(dirs)
                if d not in IGNORED_DIRS and not d.startswith(".")
            ]
            for fname in sorted(files):
                if fname.startswith("."):
                    continue
                if glob != "*" and not fnmatch.fnmatch(fname, glob):
                    continue
                fpath = Path(root_dir) / fname
                rel = str(fpath.relative_to(target))
                _search_file(fpath, rel)
                if len(results) >= max_results:
                    break
            if len(results) >= max_results:
                break

    return {
        "status": "ok",
        "engine": "python",
        "path": str(target),
        "pattern": pattern,
        "count": len(results),
        "matches": results,
    }


def jq(
    query: str = ".",
    path: str = "",
    raw_json: str = "",
) -> dict[str, Any]:
    """Filters, queries, or transforms JSON data using a jq filter expression.

    Args:
        query: jq expression (default `.`).
        path: Optional path to a JSON file.
        raw_json: Optional raw JSON string (used if path is not specified).
    """
    if not query.strip():
        query = "."

    target_file = None
    input_content = None

    if path:
        target = Path(path).expanduser().resolve()
        if not target.is_file():
            return {"status": "error", "error": f"JSON file does not exist: {target}"}
        target_file = str(target)
    elif raw_json:
        input_content = raw_json
    else:
        return {
            "status": "error",
            "error": "Either `path` or `raw_json` must be provided.",
        }

    if which_bin("jq"):
        cmd = ["jq", query]
        if target_file:
            cmd.append(target_file)
            code, stdout, stderr = run_cmd(cmd, timeout=15.0)
        else:
            code, stdout, stderr = run_cmd(cmd, input_text=input_content, timeout=15.0)

        if code != 0:
            return {
                "status": "error",
                "error": stderr or "jq command failed",
                "query": query,
            }

        try:
            parsed = json.loads(stdout)
            return {
                "status": "ok",
                "engine": "jq",
                "query": query,
                "result": parsed,
            }
        except json.JSONDecodeError:
            return {
                "status": "ok",
                "engine": "jq",
                "query": query,
                "raw_output": stdout,
            }

    try:
        source_text = (
            Path(target_file).read_text(encoding="utf-8")
            if target_file
            else input_content
        )
        data = json.loads(source_text)
        if query == ".":
            return {
                "status": "ok",
                "engine": "python-json",
                "query": query,
                "result": data,
            }
        return {
            "status": "error",
            "error": f"jq binary not found; complex query '{query}' requires jq installed",
        }
    except (json.JSONDecodeError, OSError) as exc:
        return {"status": "error", "error": str(exc)}


def checksum(
    path: str,
    algorithm: str = "sha256",
) -> dict[str, Any]:
    """Calculates cryptographic hashes and Nix SRI hash for a file.

    Args:
        path: Path to the target file.
        algorithm: Hash algorithm: `sha256` (default), `sha512`, `sha1`, `md5`, or `all`.
    """
    target = Path(path).expanduser().resolve()
    if not target.is_file():
        return {"status": "error", "error": f"File does not exist: {target}"}

    algo = algorithm.strip().lower()
    h_sha256 = hashlib.sha256()
    h_sha512 = hashlib.sha512() if algo in ("sha512", "all") else None
    h_sha1 = hashlib.sha1() if algo in ("sha1", "all") else None
    h_md5 = hashlib.md5() if algo in ("md5", "all") else None

    total_bytes = 0
    try:
        with target.open("rb") as f:
            while chunk := f.read(65536):
                total_bytes += len(chunk)
                h_sha256.update(chunk)
                if h_sha512:
                    h_sha512.update(chunk)
                if h_sha1:
                    h_sha1.update(chunk)
                if h_md5:
                    h_md5.update(chunk)
    except OSError as exc:
        return {"status": "error", "error": str(exc)}

    sha256_hex = h_sha256.hexdigest()
    sri_hash = f"sha256-{base64.b64encode(h_sha256.digest()).decode('ascii')}"

    result: dict[str, Any] = {
        "status": "ok",
        "path": str(target),
        "size_bytes": total_bytes,
        "sha256": sha256_hex,
        "nix_sri": sri_hash,
    }
    if h_sha512:
        result["sha512"] = h_sha512.hexdigest()
    if h_sha1:
        result["sha1"] = h_sha1.hexdigest()
    if h_md5:
        result["md5"] = h_md5.hexdigest()
    return result


def detect_type(path: str) -> dict[str, Any]:
    """Detects MIME type, content category, and language of a file using Magika or libmagic.

    Args:
        path: Path to the target file.
    """
    target = Path(path).expanduser().resolve()
    if not target.exists():
        return {"status": "error", "error": f"Path does not exist: {target}"}
    if not target.is_file():
        return {"status": "error", "error": f"Path is not a regular file: {target}"}

    if which_bin("magika"):
        code, stdout, _ = run_cmd(["magika", "--json", str(target)])
        if code == 0 and stdout:
            try:
                data = json.loads(stdout)
                entry = data[0] if isinstance(data, list) and data else data
                if isinstance(entry, dict):
                    val = (
                        entry.get("result", {}).get("value", {})
                        if "result" in entry
                        else entry
                    )
                    out_info = val.get("output", val) if isinstance(val, dict) else {}
                    dl_info = val.get("dl", out_info) if isinstance(val, dict) else {}
                    label = (
                        out_info.get("label")
                        or dl_info.get("label")
                        or entry.get("ct_label")
                    )
                    mime = (
                        out_info.get("mime_type")
                        or dl_info.get("mime_type")
                        or entry.get("mime_type")
                    )
                    desc = (
                        out_info.get("description")
                        or dl_info.get("description")
                        or entry.get("description")
                    )
                    score = (
                        val.get("score")
                        if isinstance(val, dict)
                        else entry.get("score")
                    )
                    group = out_info.get("group") or dl_info.get("group")
                    return {
                        "status": "ok",
                        "engine": "magika",
                        "path": str(target),
                        "label": label,
                        "mime_type": mime,
                        "description": desc,
                        "group": group,
                        "score": score,
                    }
            except (json.JSONDecodeError, KeyError, IndexError, ValueError):
                logger.debug("Failed to parse magika output: %s", stdout)

    if which_bin("file"):
        code, stdout, _ = run_cmd(["file", "-b", "--mime-type", str(target)])
        if code == 0 and stdout:
            return {
                "status": "ok",
                "engine": "file",
                "path": str(target),
                "mime_type": stdout.strip(),
            }

    guessed, _ = mimetypes.guess_type(target)
    return {
        "status": "ok",
        "engine": "mimetypes",
        "path": str(target),
        "mime_type": guessed or "application/octet-stream",
    }


def stat(path: str) -> dict[str, Any]:
    """Returns detailed file or directory metadata (permissions, owner, group, size, inode, timestamps).

    Args:
        path: Path to the file, directory, or symlink.
    """
    target = Path(path).expanduser()
    if not target.exists() and not target.is_symlink():
        return {"status": "error", "error": f"Path does not exist: {target}"}

    try:
        st = target.lstat()
        owner = pwd.getpwuid(st.st_uid).pw_name
    except (KeyError, OSError):
        st = target.lstat()
        owner = str(st.st_uid)

    try:
        group = grp.getgrgid(st.st_gid).gr_name
    except KeyError:
        group = str(st.st_gid)

    info: dict[str, Any] = {
        "status": "ok",
        "path": str(target.resolve()) if target.exists() else str(target),
        "name": target.name,
        "type": _entry_type(st.st_mode),
        "mode": _format_mode(st.st_mode),
        "octal_permissions": oct(stat_mod.S_IMODE(st.st_mode)),
        "owner": owner,
        "group": group,
        "size_bytes": st.st_size,
        "inode": st.st_ino,
        "links": st.st_nlink,
        "modified": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(st.st_mtime)),
        "accessed": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(st.st_atime)),
        "changed": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(st.st_ctime)),
    }
    if stat_mod.S_ISLNK(st.st_mode):
        try:
            info["symlink_target"] = os.readlink(target)
        except OSError:
            pass
    return info


def tree(
    path: str = ".",
    max_depth: int = 2,
    visual: bool = False,
) -> dict[str, Any]:
    """Renders a hierarchical directory tree up to `max_depth` (supports visual ASCII diagram via `eza -T`).

    Args:
        path: Root directory path (default `.`).
        max_depth: Maximum depth to traverse (1 to 5, default 2).
        visual: Include a formatted visual tree diagram (using `eza -T` if available, default False).
    """
    root = Path(path).expanduser().resolve()
    if not root.is_dir():
        return {"status": "error", "error": f"Not a directory: {root}"}

    max_depth = max(1, min(int(max_depth), 5))
    entries: list[str] = []

    def _walk(current: Path, depth: int) -> None:
        if depth > max_depth or len(entries) >= 400:
            return
        try:
            children = sorted(
                current.iterdir(),
                key=lambda p: (not p.is_dir(), p.name.lower()),
            )
        except PermissionError:
            return

        for child in children:
            if child.name in IGNORED_DIRS or (
                child.name.startswith(".")
                and child.name not in (".envrc", ".gitignore")
            ):
                continue
            rel = str(child.relative_to(root))
            if child.is_dir():
                entries.append(f"{rel}/")
                if not child.is_symlink():
                    _walk(child, depth + 1)
            else:
                entries.append(rel)
            if len(entries) >= 400:
                return

    _walk(root, 1)

    result: dict[str, Any] = {
        "status": "ok",
        "path": str(root),
        "max_depth": max_depth,
        "count": len(entries),
        "tree": entries,
    }

    if visual and which_bin("eza"):
        ignore_pat = "|".join(IGNORED_DIRS)
        code, out, _ = run_cmd(
            [
                "eza",
                "-T",
                f"--level={max_depth}",
                "--color=never",
                "-I",
                ignore_pat,
                str(root),
            ],
            timeout=8.0,
        )
        if code == 0:
            result["visual"] = out

    return result


def mkdir(
    path: str,
    parents: bool = True,
    exist_ok: bool = True,
) -> dict[str, Any]:
    """Creates a directory at the specified path, optionally creating parent directories.

    Args:
        path: Path of the directory to create.
        parents: Create parent directories as needed (like `mkdir -p`, default True).
        exist_ok: Do not fail if the directory already exists (default True).
    """
    target = Path(path).expanduser().resolve()
    try:
        created = not target.exists()
        target.mkdir(parents=parents, exist_ok=exist_ok)
        st = target.stat()
        return {
            "status": "ok",
            "path": str(target),
            "created": created,
            "exists": target.exists(),
            "mode": _format_mode(st.st_mode),
        }
    except FileExistsError:
        return {
            "status": "error",
            "error": f"Path already exists and is not a directory or exist_ok=False: {target}",
        }
    except PermissionError:
        return {
            "status": "error",
            "error": f"Permission denied creating directory: {target}",
        }
    except OSError as exc:
        return {
            "status": "error",
            "error": f"Failed to create directory '{target}': {exc}",
        }


def _format_size(size_bytes: float) -> str:
    """Format bytes into human-readable string (B, KiB, MiB, GiB, TiB)."""
    s = float(size_bytes)
    if s < 1024:
        return f"{int(s)} B"
    for unit in ("KiB", "MiB", "GiB", "TiB"):
        s /= 1024.0
        if s < 1024.0:
            return f"{s:.1f} {unit}"
    return f"{s:.1f} PiB"


def wc(
    path: str = "",
    content: str = "",
) -> dict[str, Any]:
    """Counts lines, words, characters, and bytes in a file or string (like GNU wc).

    Args:
        path: Path to the target file.
        content: Optional raw text to inspect directly if `path` is omitted.
    """
    if path.strip():
        target = Path(path).expanduser().resolve()
        if not target.is_file():
            return {"status": "error", "error": f"File does not exist: {target}"}
        try:
            raw_bytes = target.read_bytes()
            text = raw_bytes.decode("utf-8", errors="replace")
            display_path = str(target)
            byte_count = len(raw_bytes)
        except OSError as exc:
            return {
                "status": "error",
                "error": f"Failed to read file '{target}': {exc}",
            }
    elif content:
        text = content
        display_path = None
        byte_count = len(content.encode("utf-8"))
    else:
        return {
            "status": "error",
            "error": "Either `path` or `content` must be provided.",
        }

    lines = text.count("\n")
    words = len(text.split())
    chars = len(text)

    return {
        "status": "ok",
        "path": display_path,
        "lines": lines,
        "words": words,
        "characters": chars,
        "bytes": byte_count,
        "human_size": _format_size(byte_count),
    }


def du(
    path: str = ".",
    max_depth: int = 1,
    limit: int = 25,
) -> dict[str, Any]:
    """Summarizes disk usage of a directory and its immediate subdirectories (like GNU du -h).

    Args:
        path: Target directory or file path (default `.`).
        max_depth: Depth of child directory size reporting (default 1).
        limit: Maximum number of entries to return in the breakdown (default 25).
    """
    target = Path(path).expanduser().resolve()
    if not target.exists():
        return {"status": "error", "error": f"Path does not exist: {target}"}

    if target.is_file():
        st = target.stat()
        return {
            "status": "ok",
            "path": str(target),
            "is_file": True,
            "total_bytes": st.st_size,
            "total_human": _format_size(st.st_size),
            "entries": [],
        }

    max_depth = max(0, min(int(max_depth), 5))
    limit = max(1, min(int(limit), 100))

    def _calc_dir_size(d: Path) -> int:
        total = 0
        try:
            for entry in d.rglob("*"):
                try:
                    if entry.is_file() and not entry.is_symlink():
                        total += entry.stat().st_size
                except (OSError, PermissionError):
                    continue
        except (OSError, PermissionError):
            pass
        return total

    breakdown: list[dict[str, Any]] = []
    total_dir_size = 0

    try:
        children = sorted(target.iterdir(), key=lambda p: p.name.lower())
    except PermissionError:
        return {"status": "error", "error": f"Permission denied: {target}"}

    for child in children:
        if child.name in IGNORED_DIRS or child.name.startswith(".git"):
            continue
        try:
            if child.is_dir() and not child.is_symlink():
                sz = _calc_dir_size(child)
                total_dir_size += sz
                breakdown.append(
                    {
                        "name": f"{child.name}/",
                        "path": str(child),
                        "type": "dir",
                        "size_bytes": sz,
                        "size_human": _format_size(sz),
                    }
                )
            elif child.is_file():
                sz = child.stat().st_size
                total_dir_size += sz
                breakdown.append(
                    {
                        "name": child.name,
                        "path": str(child),
                        "type": "file",
                        "size_bytes": sz,
                        "size_human": _format_size(sz),
                    }
                )
        except (OSError, PermissionError):
            continue

    breakdown.sort(key=lambda item: item["size_bytes"], reverse=True)

    return {
        "status": "ok",
        "path": str(target),
        "total_bytes": total_dir_size,
        "total_human": _format_size(total_dir_size),
        "count": len(breakdown),
        "entries": breakdown[:limit],
    }


def realpath(
    path: str = ".",
    strict: bool = False,
) -> dict[str, Any]:
    """Resolves canonical absolute path, expanding symlinks and normalizing path components (like GNU realpath).

    Args:
        path: Path to resolve (default `.`).
        strict: If True, fails if path does not exist (default False).
    """
    raw_path = Path(path).expanduser()
    try:
        resolved = raw_path.resolve(strict=strict)
        is_sym = raw_path.is_symlink()
        symlink_target = str(os.readlink(raw_path)) if is_sym else None
        return {
            "status": "ok",
            "input_path": path,
            "real_path": str(resolved),
            "exists": resolved.exists(),
            "is_symlink": is_sym,
            "symlink_target": symlink_target,
            "parent": str(resolved.parent),
            "name": resolved.name,
        }
    except (FileNotFoundError, OSError) as exc:
        return {
            "status": "error",
            "input_path": path,
            "error": str(exc),
        }


def trash_put(
    path: str,
) -> dict[str, Any]:
    """Safely moves a file or directory to the FreeDesktop user Trash (~/.local/share/Trash) instead of permanent deletion.

    Args:
        path: Path of the file or directory to move to Trash.
    """
    target = Path(path).expanduser().resolve()
    if not target.exists():
        return {"status": "error", "error": f"Path does not exist: {target}"}

    # 1. Try gio trash if available (standard GNOME / FreeDesktop CLI)
    if which_bin("gio"):
        code, _, _ = run_cmd(["gio", "trash", str(target)])
        if code == 0:
            return {
                "status": "ok",
                "backend": "gio",
                "path": str(target),
                "trashed": True,
                "restorable": True,
            }

    # 2. Try trash-put (trash-cli) if available
    if which_bin("trash-put"):
        code, _, _ = run_cmd(["trash-put", str(target)])
        if code == 0:
            return {
                "status": "ok",
                "backend": "trash-cli",
                "path": str(target),
                "trashed": True,
                "restorable": True,
            }

    # 3. Pure Python FreeDesktop Trash implementation
    try:
        trash_dir = Path.home() / ".local" / "share" / "Trash"
        files_dir = trash_dir / "files"
        info_dir = trash_dir / "info"
        files_dir.mkdir(parents=True, exist_ok=True)
        info_dir.mkdir(parents=True, exist_ok=True)

        base_name = target.name
        dest = files_dir / base_name
        counter = 1
        while dest.exists():
            dest = files_dir / f"{base_name}.{counter}"
            counter += 1

        info_file = info_dir / f"{dest.name}.trashinfo"
        now_str = time.strftime("%Y-%m-%dT%H:%M:%S")
        trashinfo_content = f"[Trash Info]\nPath={target}\nDeletionDate={now_str}\n"
        info_file.write_text(trashinfo_content, encoding="utf-8")
        shutil.move(str(target), str(dest))

        return {
            "status": "ok",
            "backend": "python-freedesktop",
            "path": str(target),
            "trash_destination": str(dest),
            "trashed": True,
            "restorable": True,
        }
    except OSError as exc:
        return {"status": "error", "error": f"Failed to trash '{target}': {exc}"}


TOOLS = [
    ToolSpec(
        name="ls",
        module="fs",
        description="Lists directory contents with file types, permissions, sizes, and modification times.",
        handler=ls,
        pack="fs",
    ),
    ToolSpec(
        name="cat",
        module="fs",
        description="Reads file text contents with optional start_line and end_line slicing.",
        handler=cat,
        pack="fs",
    ),
    ToolSpec(
        name="head",
        module="fs",
        description="Reads the first N lines of a file.",
        handler=head,
        pack="fs",
    ),
    ToolSpec(
        name="tail",
        module="fs",
        description="Reads the last N lines of a file.",
        handler=tail,
        pack="fs",
    ),
    ToolSpec(
        name="find",
        module="fs",
        description="Finds files or directories matching a glob pattern within a directory tree.",
        handler=find,
        pack="fs",
    ),
    ToolSpec(
        name="grep",
        module="fs",
        description="Searches file contents for a regular expression or substring pattern.",
        handler=grep,
        pack="fs",
    ),
    ToolSpec(
        name="stat",
        module="fs",
        description="Returns detailed file, directory, or symlink permissions, owner, size, and timestamps.",
        handler=stat,
        pack="fs",
    ),
    ToolSpec(
        name="tree",
        module="fs",
        description="Renders a directory structure tree up to a configurable depth.",
        handler=tree,
        pack="fs",
    ),
    ToolSpec(
        name="jq",
        module="fs",
        description="Filters, queries, or transforms JSON data using a jq filter expression.",
        handler=jq,
        pack="fs",
    ),
    ToolSpec(
        name="checksum",
        module="fs",
        description="Calculates cryptographic hashes (SHA-256, SHA-512, MD5) and Nix SRI hash for a file.",
        handler=checksum,
        pack="fs",
    ),
    ToolSpec(
        name="detect_type",
        module="fs",
        description="Detects MIME type, content category, and language of a file using Magika or libmagic.",
        handler=detect_type,
        pack="fs",
    ),
    ToolSpec(
        name="mkdir",
        module="fs",
        description="Creates a directory at the specified path, optionally creating parent directories (mkdir -p).",
        handler=mkdir,
        pack="fs",
    ),
    ToolSpec(
        name="wc",
        module="fs",
        description="Counts lines, words, characters, and bytes in a file or string (like GNU wc).",
        handler=wc,
        pack="fs",
    ),
    ToolSpec(
        name="du",
        module="fs",
        description="Summarizes disk usage of a directory and child entries sorted by size (like GNU du -h).",
        handler=du,
        pack="fs",
    ),
    ToolSpec(
        name="realpath",
        module="fs",
        description="Resolves canonical absolute path, following and reporting symlinks (like GNU realpath).",
        handler=realpath,
        pack="fs",
    ),
    ToolSpec(
        name="trash_put",
        module="fs",
        description="Safely moves a file or directory to FreeDesktop user Trash instead of permanent deletion.",
        handler=trash_put,
        pack="fs",
    ),
]


def register(mcp: MCPServer) -> None:
    """Register filesystem tools with MCPServer."""
    for spec in TOOLS:
        mcp.tool(name=spec.name, description=spec.description)(spec.handler)
