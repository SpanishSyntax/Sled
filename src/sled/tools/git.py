"""Sled Pack: `git` — Atomic Git repository tools (`git_status`, `git_log`, `git_diff`, `git_branch`, `git_show`, `git_stash_list`, `git_stash_show`, `git_stash_push`, `git_stash_pop`, `git_stash_apply`, `git_remote`, `git_blame`, `git_commit`, `gh_pr_list`, `gh_pr_view`, `gh_pr_create`, `gh_issue_list`, `gh_issue_view`)."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sled.tools import ToolSpec
from sled.tools._exec import run_cmd, which_bin

if TYPE_CHECKING:
    from mcp.server import MCPServer

logger = logging.getLogger("sled.tools.git")

PACK = "git"


def _resolve_repo(
    repo_path: str = ".", path: str | None = None
) -> tuple[Path | None, str | None]:
    p = path if path is not None and path.strip() else repo_path
    target = Path(p).expanduser().resolve()
    if not target.is_dir():
        return None, f"Directory does not exist: {target}"
    code, top, err = run_cmd(["git", "rev-parse", "--show-toplevel"], cwd=target)
    if code != 0:
        return None, err or f"Not a Git repository: {target}"
    return Path(top), None


def git_status(repo_path: str = ".", path: str | None = None) -> dict[str, Any]:
    """Returns Git working tree status, current branch, HEAD commit, and modified/untracked files.

    Args:
        repo_path: Path to the Git repository (default `.`).
        path: Optional alias for `repo_path`.
    """
    root, err = _resolve_repo(repo_path, path=path)
    if not root:
        return {"status": "error", "error": err}

    _, branch, _ = run_cmd(["git", "branch", "--show-current"], cwd=root)
    rc_head, commit, _ = run_cmd(["git", "rev-parse", "--short", "HEAD"], cwd=root)
    _, porcelain, _ = run_cmd(["git", "status", "--porcelain=v1", "-b"], cwd=root)

    lines = [ln for ln in porcelain.splitlines() if ln.strip()]
    branch_header = lines[0][3:] if lines and lines[0].startswith("## ") else ""
    file_lines = lines[1:] if lines and lines[0].startswith("## ") else lines

    staged: list[str] = []
    unstaged: list[str] = []
    untracked: list[str] = []

    for ln in file_lines:
        if len(ln) < 3:
            continue
        xy = ln[:2]
        path_str = ln[3:]
        if xy == "??":
            untracked.append(path_str)
        else:
            if xy[0] not in (" ", "?"):
                staged.append(f"{xy[0]} {path_str}")
            if xy[1] not in (" ", "?"):
                unstaged.append(f"{xy[1]} {path_str}")

    is_clean = len(file_lines) == 0
    res: dict[str, Any] = {
        "status": "ok",
        "branch": branch or ("HEAD (unborn)" if rc_head != 0 else "HEAD (detached)"),
        "clean": is_clean,
    }
    if branch_header:
        res["tracking"] = branch_header
    if rc_head == 0 and commit:
        res["head_commit"] = commit
    if not is_clean:
        if staged:
            res["staged"] = staged
        if unstaged:
            res["unstaged"] = unstaged
        if untracked:
            res["untracked"] = untracked

    return res


def git_log(
    repo_path: str = ".",
    limit: int = 15,
    ref: str = "",
    path: str | None = None,
) -> dict[str, Any]:
    """Returns recent Git commits with short hash, author, ISO date, and commit subject.

    Args:
        repo_path: Path to the Git repository (default `.`).
        limit: Number of commits to return (default 15, max 100).
        ref: Optional branch, tag, or file path to filter history.
        path: Optional alias for `repo_path`.
    """
    root, err = _resolve_repo(repo_path, path=path)
    if not root:
        return {"status": "error", "error": err}

    limit = max(1, min(int(limit), 100))
    cmd = [
        "git",
        "log",
        f"-n{limit}",
        "--date=iso-strict",
        "--pretty=format:%h%x09%an%x09%ad%x09%s",
    ]
    if ref.strip():
        cmd.append(ref.strip())

    code, out, cmd_err = run_cmd(cmd, cwd=root)
    if code != 0:
        return {"status": "error", "root": str(root), "error": cmd_err or out}

    commits: list[dict[str, str]] = []
    for line in out.splitlines():
        parts = line.split("\t", 3)
        if len(parts) == 4:
            commits.append(
                {
                    "commit": parts[0],
                    "author": parts[1],
                    "date": parts[2],
                    "subject": parts[3],
                }
            )

    return {
        "status": "ok",
        "root": str(root),
        "count": len(commits),
        "commits": commits,
    }


def git_diff(
    repo_path: str = ".",
    staged: bool = False,
    target: str = "",
    path: str | None = None,
) -> dict[str, Any]:
    """Returns Git diff output (unstaged or staged changes, or against a target ref/path).

    Args:
        repo_path: Path to the Git repository (default `.`).
        staged: Show staged (`--cached`) changes instead of working tree changes (default False).
        target: Optional file path or commit/branch ref to diff.
        path: Optional alias for `repo_path`.
    """
    root, err = _resolve_repo(repo_path, path=path)
    if not root:
        return {"status": "error", "error": err}

    cmd = ["git", "diff", "--no-color"]
    if staged:
        cmd.append("--cached")
    if target.strip():
        cmd.append(target.strip())

    code, out, cmd_err = run_cmd(cmd, cwd=root, timeout=15.0)
    if code != 0:
        return {"status": "error", "error": cmd_err or out}

    if not out.strip():
        return {"status": "ok", "diff": ""}

    _, stat_out, _ = run_cmd([*cmd, "--stat"], cwd=root, timeout=10.0)
    res: dict[str, Any] = {
        "status": "ok",
        "diff": out[:20000],
    }
    if stat_out.strip():
        res["stat"] = stat_out.strip()
    if staged:
        res["staged"] = True
    if len(out) > 20000:
        res["truncated"] = True
    return res


def git_branch(repo_path: str = ".", path: str | None = None) -> dict[str, Any]:
    """Lists local and remote Git branches along with configured remotes.

    Args:
        repo_path: Path to the Git repository (default `.`).
        path: Optional alias for `repo_path`.
    """
    root, err = _resolve_repo(repo_path, path=path)
    if not root:
        return {"status": "error", "error": err}

    _, current, _ = run_cmd(["git", "branch", "--show-current"], cwd=root)
    _, branches_out, _ = run_cmd(
        [
            "git",
            "branch",
            "-a",
            "--format=%(refname:short)\t%(objectname:short)\t%(upstream:short)",
        ],
        cwd=root,
    )
    _, remotes_out, _ = run_cmd(["git", "remote", "-v"], cwd=root)

    branches: list[dict[str, str]] = []
    for ln in branches_out.splitlines():
        parts = ln.split("\t")
        if parts and parts[0]:
            branches.append(
                {
                    "name": parts[0],
                    "commit": parts[1] if len(parts) > 1 else "",
                    "upstream": parts[2] if len(parts) > 2 else "",
                }
            )

    remotes: dict[str, str] = {}
    for ln in remotes_out.splitlines():
        parts = ln.split()
        if len(parts) >= 2 and parts[0] not in remotes:
            remotes[parts[0]] = parts[1]

    return {
        "status": "ok",
        "root": str(root),
        "current_branch": current,
        "branches": branches,
        "remotes": remotes,
    }


def git_show(
    repo_path: str = ".", rev: str = "HEAD", path: str | None = None
) -> dict[str, Any]:
    """Inspects a specific Git commit's metadata, message, and diffstat.

    Args:
        repo_path: Path to the Git repository (default `.`).
        rev: Commit hash, tag, or ref to inspect (default `HEAD`).
        path: Optional alias for `repo_path`.
    """
    root, err = _resolve_repo(repo_path, path=path)
    if not root:
        return {"status": "error", "error": err}

    code, out, cmd_err = run_cmd(
        ["git", "show", "--stat", "--no-color", rev.strip() or "HEAD"],
        cwd=root,
        timeout=10.0,
    )
    if code != 0:
        return {"status": "error", "root": str(root), "error": cmd_err or out}

    return {
        "status": "ok",
        "root": str(root),
        "rev": rev.strip() or "HEAD",
        "output": out[:15000],
    }


def git_stash_list(
    repo_path: str = ".",
    path: str | None = None,
) -> dict[str, Any]:
    """Lists saved Git stashes with index, branch, and commit message (`git stash list`).

    Args:
        repo_path: Path to the Git repository (default `.`).
        path: Optional alias for `repo_path`.
    """
    root, err = _resolve_repo(repo_path, path=path)
    if not root:
        return {"status": "error", "error": err}

    code, out, cmd_err = run_cmd(["git", "stash", "list"], cwd=root, timeout=5.0)
    if code != 0:
        return {"status": "error", "error": cmd_err or out}

    stashes: list[dict[str, str]] = []
    for line in out.splitlines():
        if ":" in line:
            parts = line.split(":", 2)
            stashes.append(
                {
                    "ref": parts[0].strip(),
                    "branch": parts[1].strip() if len(parts) > 1 else "",
                    "message": parts[2].strip() if len(parts) > 2 else "",
                }
            )

    return {
        "status": "ok",
        "root": str(root),
        "count": len(stashes),
        "stashes": stashes,
    }


def git_stash_show(
    index: int = 0,
    repo_path: str = ".",
    path: str | None = None,
) -> dict[str, Any]:
    """Shows the diff and file statistics of a Git stash entry (`git stash show -p`).

    Args:
        index: Stash index to inspect (default 0 for `stash@{0}`).
        repo_path: Path to the Git repository (default `.`).
        path: Optional alias for `repo_path`.
    """
    root, err = _resolve_repo(repo_path, path=path)
    if not root:
        return {"status": "error", "error": err}

    stash_ref = f"stash@{{{max(0, int(index))}}}"
    code, out, cmd_err = run_cmd(
        ["git", "stash", "show", "-p", "--stat", stash_ref],
        cwd=root,
        timeout=10.0,
    )
    if code != 0:
        return {"status": "error", "error": cmd_err or out}

    return {
        "status": "ok",
        "root": str(root),
        "stash": stash_ref,
        "diff": out[:15000],
    }


def git_stash_push(
    message: str = "",
    include_untracked: bool = False,
    paths: list[str] | None = None,
    repo_path: str = ".",
    path: str | None = None,
) -> dict[str, Any]:
    """Saves local modifications to a new stash entry (`git stash push`).

    Args:
        message: Optional description for the stash entry.
        include_untracked: Include untracked files (`-u`, default False).
        paths: Optional specific file paths to stash.
        repo_path: Path to the Git repository (default `.`).
        path: Optional alias for `repo_path`.
    """
    root, err = _resolve_repo(repo_path, path=path)
    if not root:
        return {"status": "error", "error": err}

    cmd = ["git", "stash", "push"]
    if include_untracked:
        cmd.append("-u")
    if message.strip():
        cmd.extend(["-m", message.strip()])
    if paths:
        clean_paths = [p.strip() for p in paths if p and p.strip()]
        if clean_paths:
            cmd.append("--")
            cmd.extend(clean_paths)

    code, out, cmd_err = run_cmd(cmd, cwd=root, timeout=15.0)
    if code != 0:
        return {"status": "error", "error": cmd_err or out}

    return {
        "status": "ok",
        "root": str(root),
        "message": message.strip() or None,
        "output": out.strip() or "Saved working directory state.",
    }


def git_stash_pop(
    index: int = 0,
    repo_path: str = ".",
    path: str | None = None,
) -> dict[str, Any]:
    """Applies a stash entry and removes it from the stash list (`git stash pop`).

    Args:
        index: Stash index to pop (default 0 for `stash@{0}`).
        repo_path: Path to the Git repository (default `.`).
        path: Optional alias for `repo_path`.
    """
    root, err = _resolve_repo(repo_path, path=path)
    if not root:
        return {"status": "error", "error": err}

    stash_ref = f"stash@{{{max(0, int(index))}}}"
    code, out, cmd_err = run_cmd(
        ["git", "stash", "pop", stash_ref], cwd=root, timeout=15.0
    )
    if code != 0:
        return {"status": "error", "error": cmd_err or out}

    return {
        "status": "ok",
        "root": str(root),
        "stash": stash_ref,
        "output": out.strip(),
    }


def git_stash_apply(
    index: int = 0,
    repo_path: str = ".",
    path: str | None = None,
) -> dict[str, Any]:
    """Applies a stash entry without removing it from the stash list (`git stash apply`).

    Args:
        index: Stash index to apply (default 0 for `stash@{0}`).
        repo_path: Path to the Git repository (default `.`).
        path: Optional alias for `repo_path`.
    """
    root, err = _resolve_repo(repo_path, path=path)
    if not root:
        return {"status": "error", "error": err}

    stash_ref = f"stash@{{{max(0, int(index))}}}"
    code, out, cmd_err = run_cmd(
        ["git", "stash", "apply", stash_ref], cwd=root, timeout=15.0
    )
    if code != 0:
        return {"status": "error", "error": cmd_err or out}

    return {
        "status": "ok",
        "root": str(root),
        "stash": stash_ref,
        "output": out.strip(),
    }


def git_stash(
    action: str = "list",
    repo_path: str = ".",
    index: int = 0,
    message: str = "",
    include_untracked: bool = False,
    path: str | None = None,
) -> dict[str, Any]:
    """Manages Git stashes (list, show, push, pop, apply).

    Args:
        action: `list` (default), `show`, `push`, `pop`, or `apply`.
        repo_path: Path to the Git repository (default `.`).
        index: Stash index for `show`, `pop`, `apply` (default 0 for `stash@{0}`).
        message: Optional stash message when action is `push`.
        include_untracked: Include untracked files when action is `push` (default False).
        path: Optional alias for `repo_path`.
    """
    act = action.strip().lower()
    if act == "show":
        return git_stash_show(index=index, repo_path=repo_path, path=path)
    if act == "push":
        return git_stash_push(
            message=message,
            include_untracked=include_untracked,
            repo_path=repo_path,
            path=path,
        )
    if act == "pop":
        return git_stash_pop(index=index, repo_path=repo_path, path=path)
    if act == "apply":
        return git_stash_apply(index=index, repo_path=repo_path, path=path)
    return git_stash_list(repo_path=repo_path, path=path)


def git_remote(repo_path: str = ".", path: str | None = None) -> dict[str, Any]:
    """Lists configured Git remotes, fetch/push URLs, and commit divergence against upstream.

    Args:
        repo_path: Path to the Git repository (default `.`).
        path: Optional alias for `repo_path`.
    """
    root, err = _resolve_repo(repo_path, path=path)
    if not root:
        return {"status": "error", "error": err}

    _code, out, _ = run_cmd(["git", "remote", "-v"], cwd=root, timeout=5.0)
    remotes: dict[str, dict[str, str]] = {}
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 3:
            name, url, direction = parts[0], parts[1], parts[2].strip("()")
            if name not in remotes:
                remotes[name] = {}
            remotes[name][direction] = url

    ahead = 0
    behind = 0
    tracking_branch = ""
    code_track, track_out, _ = run_cmd(
        ["git", "rev-parse", "--abbrev-ref", "@{u}"], cwd=root, timeout=5.0
    )
    if code_track == 0 and track_out.strip():
        tracking_branch = track_out.strip()
        code_rev, counts, _ = run_cmd(
            ["git", "rev-list", "--left-right", "--count", "HEAD...@{u}"],
            cwd=root,
            timeout=5.0,
        )
        if code_rev == 0 and counts.strip():
            c_parts = counts.strip().split()
            if len(c_parts) == 2:
                try:
                    ahead = int(c_parts[0])
                    behind = int(c_parts[1])
                except ValueError:
                    pass

    res: dict[str, Any] = {
        "status": "ok",
        "remotes": remotes,
    }
    if tracking_branch:
        res["upstream"] = tracking_branch
    if ahead > 0:
        res["ahead"] = ahead
    if behind > 0:
        res["behind"] = behind
    return res


def git_blame(
    file_path: str,
    repo_path: str = ".",
    start_line: int = 1,
    end_line: int = 50,
    path: str | None = None,
) -> dict[str, Any]:
    """Inspects commit author, date, and commit hash for a specific line range of a file.

    Args:
        file_path: Path to the file to blame.
        repo_path: Path to the Git repository (default `.`).
        start_line: 1-based start line number (default 1).
        end_line: 1-based end line number (default 50).
        path: Optional alias for `repo_path`.
    """
    root, err = _resolve_repo(repo_path, path=path)
    if not root:
        return {"status": "error", "error": err}

    target_file = Path(file_path)
    if not target_file.is_absolute():
        target_file = root / target_file

    if not target_file.is_file():
        return {"status": "error", "error": f"File does not exist: {target_file}"}

    rel_path = str(target_file.relative_to(root))
    s = max(1, int(start_line))
    e = max(s, min(int(end_line), s + 200))

    code, out, cmd_err = run_cmd(
        ["git", "blame", f"-L{s},{e}", "--date=short", "-s", "--", rel_path],
        cwd=root,
        timeout=10.0,
    )
    if code != 0:
        return {"status": "error", "error": cmd_err or out}

    lines: list[str] = []
    for line in out.splitlines():
        lines.append(line.strip())

    return {
        "status": "ok",
        "root": str(root),
        "file": rel_path,
        "start_line": s,
        "end_line": e,
        "count": len(lines),
        "lines": lines,
    }


def git_commit(
    message: str,
    paths: list[str] | None = None,
    all_tracked: bool = False,
    repo_path: str = ".",
    path: str | None = None,
) -> dict[str, Any]:
    """Creates a local Git commit with a required message and optional staged files.

    Args:
        message: The commit message (required, non-empty).
        paths: Optional list of specific file paths to stage before committing.
        all_tracked: If True, stages all modified and deleted tracked files (git commit -a).
        repo_path: Path to the Git repository (default `.`).
        path: Optional alias for `repo_path`.
    """
    msg = message.strip() if message else ""
    if not msg:
        return {"status": "error", "error": "Commit message cannot be empty."}

    root, err = _resolve_repo(repo_path, path=path)
    if not root:
        return {"status": "error", "error": err}

    if paths:
        stage_targets = [p.strip() for p in paths if p and p.strip()]
        if stage_targets:
            code, out, cmd_err = run_cmd(["git", "add", "--"] + stage_targets, cwd=root)
            if code != 0:
                return {
                    "status": "error",
                    "error": f"Failed to stage files: {cmd_err or out}",
                }

    cmd = ["git", "commit", "-m", msg]
    if all_tracked and not paths:
        cmd.append("-a")

    code, out, cmd_err = run_cmd(cmd, cwd=root)
    if code != 0:
        return {"status": "error", "error": cmd_err or out}

    _, commit_hash, _ = run_cmd(["git", "rev-parse", "--short", "HEAD"], cwd=root)
    _, branch, _ = run_cmd(["git", "branch", "--show-current"], cwd=root)

    return {
        "status": "ok",
        "root": str(root),
        "commit": commit_hash.strip(),
        "branch": branch.strip(),
        "message": msg,
        "output": out.strip(),
    }


def gh_pr_create(
    title: str,
    body: str = "",
    draft: bool = True,
    base: str = "",
    head: str = "",
    repo_path: str = ".",
    path: str | None = None,
) -> dict[str, Any]:
    """Creates a pull request on GitHub via the GitHub CLI (`gh`).

    Args:
        title: Title of the pull request (required).
        body: Body/description of the pull request (optional).
        draft: Create the PR as a draft (default True for safety).
        base: Target branch to merge into (e.g. `main`).
        head: Branch containing changes (defaults to current branch).
        repo_path: Path to the Git repository (default `.`).
        path: Optional alias for `repo_path`.
    """
    if not which_bin("gh"):
        return {
            "status": "error",
            "error": "`gh` binary not found in PATH; ensure GitHub CLI is installed.",
        }

    root, err = _resolve_repo(repo_path, path=path)
    if not root:
        return {"status": "error", "error": err}

    clean_title = title.strip() if title else ""
    if not clean_title:
        return {"status": "error", "error": "Pull request title cannot be empty."}

    cmd = ["gh", "pr", "create", "--title", clean_title, "--body", body]
    if draft:
        cmd.append("--draft")
    if base.strip():
        cmd.extend(["--base", base.strip()])
    if head.strip():
        cmd.extend(["--head", head.strip()])

    code, out, cmd_err = run_cmd(cmd, cwd=root, timeout=30.0)
    if code != 0:
        return {"status": "error", "error": cmd_err or out}

    return {
        "status": "ok",
        "url": out.strip(),
        "title": clean_title,
        "draft": draft,
        "base": base.strip() if base.strip() else None,
        "head": head.strip() if head.strip() else None,
    }


def gh_pr_list(
    repo_path: str = ".",
    limit: int = 10,
    state: str = "open",
    path: str | None = None,
) -> dict[str, Any]:
    """Lists pull requests in a GitHub repository via `gh pr list`.

    Args:
        repo_path: Path to the Git repository (default `.`).
        limit: Maximum number of PRs to list (default 10, max 50).
        state: Filter by state: `open` (default), `closed`, `merged`, or `all`.
        path: Optional alias for `repo_path`.
    """
    if not which_bin("gh"):
        return {
            "status": "error",
            "error": "`gh` binary not found in PATH; ensure GitHub CLI is installed.",
        }

    root, err = _resolve_repo(repo_path, path=path)
    if not root:
        return {"status": "error", "error": err}

    st = state.strip().lower() if state else "open"
    if st not in ("open", "closed", "merged", "all"):
        st = "open"

    cmd = [
        "gh",
        "pr",
        "list",
        f"--limit={max(1, min(int(limit), 50))}",
        f"--state={st}",
        "--json",
        "number,title,state,author,headRefName,url",
    ]
    code, out, cmd_err = run_cmd(cmd, cwd=root, timeout=15.0)
    if code != 0:
        return {"status": "error", "error": cmd_err or out}

    try:
        prs = json.loads(out)
        return {"status": "ok", "count": len(prs), "state": st, "pull_requests": prs}
    except json.JSONDecodeError:
        return {"status": "ok", "raw": out}


def gh_pr_view(
    pr_number: int,
    repo_path: str = ".",
    path: str | None = None,
) -> dict[str, Any]:
    """Views full details of a specific pull request via `gh pr view`.

    Args:
        pr_number: PR number to view (required, > 0).
        repo_path: Path to the Git repository (default `.`).
        path: Optional alias for `repo_path`.
    """
    if not which_bin("gh"):
        return {
            "status": "error",
            "error": "`gh` binary not found in PATH; ensure GitHub CLI is installed.",
        }

    root, err = _resolve_repo(repo_path, path=path)
    if not root:
        return {"status": "error", "error": err}

    if pr_number <= 0:
        return {
            "status": "error",
            "error": "`pr_number` must be greater than 0.",
        }

    cmd = [
        "gh",
        "pr",
        "view",
        str(pr_number),
        "--json",
        "number,title,state,author,url,body,headRefName,baseRefName",
    ]
    code, out, cmd_err = run_cmd(cmd, cwd=root, timeout=15.0)
    if code != 0:
        return {"status": "error", "error": cmd_err or out}

    try:
        return {"status": "ok", "pr": json.loads(out)}
    except json.JSONDecodeError:
        return {"status": "ok", "raw": out}


def gh_pr(
    action: str = "list",
    repo_path: str = ".",
    limit: int = 10,
    pr_number: int = 0,
    path: str | None = None,
) -> dict[str, Any]:
    """Queries pull requests via the GitHub CLI (`gh`).

    Args:
        action: `list` (default) or `view`.
        repo_path: Path to the Git repository (default `.`).
        limit: Maximum number of PRs to list (default 10).
        pr_number: PR number to view when action is `view`.
        path: Optional alias for `repo_path`.
    """
    if action.strip().lower() == "view":
        return gh_pr_view(pr_number=pr_number, repo_path=repo_path, path=path)
    return gh_pr_list(repo_path=repo_path, limit=limit, path=path)


def gh_issue_list(
    repo_path: str = ".",
    limit: int = 10,
    state: str = "open",
    path: str | None = None,
) -> dict[str, Any]:
    """Lists issues in a GitHub repository via `gh issue list`.

    Args:
        repo_path: Path to the Git repository (default `.`).
        limit: Maximum number of issues to list (default 10, max 50).
        state: Filter by state: `open` (default), `closed`, or `all`.
        path: Optional alias for `repo_path`.
    """
    if not which_bin("gh"):
        return {
            "status": "error",
            "error": "`gh` binary not found in PATH; ensure GitHub CLI is installed.",
        }

    root, err = _resolve_repo(repo_path, path=path)
    if not root:
        return {"status": "error", "error": err}

    st = state.strip().lower() if state else "open"
    if st not in ("open", "closed", "all"):
        st = "open"

    cmd = [
        "gh",
        "issue",
        "list",
        f"--limit={max(1, min(int(limit), 50))}",
        f"--state={st}",
        "--json",
        "number,title,state,author,url,labels",
    ]
    code, out, cmd_err = run_cmd(cmd, cwd=root, timeout=15.0)
    if code != 0:
        return {"status": "error", "error": cmd_err or out}

    try:
        issues = json.loads(out)
        return {"status": "ok", "count": len(issues), "state": st, "issues": issues}
    except json.JSONDecodeError:
        return {"status": "ok", "raw": out}


def gh_issue_view(
    issue_number: int,
    repo_path: str = ".",
    path: str | None = None,
) -> dict[str, Any]:
    """Views full details of a specific issue via `gh issue view`.

    Args:
        issue_number: Issue number to view (required, > 0).
        repo_path: Path to the Git repository (default `.`).
        path: Optional alias for `repo_path`.
    """
    if not which_bin("gh"):
        return {
            "status": "error",
            "error": "`gh` binary not found in PATH; ensure GitHub CLI is installed.",
        }

    root, err = _resolve_repo(repo_path, path=path)
    if not root:
        return {"status": "error", "error": err}

    if issue_number <= 0:
        return {
            "status": "error",
            "error": "`issue_number` must be greater than 0.",
        }

    cmd = [
        "gh",
        "issue",
        "view",
        str(issue_number),
        "--json",
        "number,title,state,author,url,body,labels",
    ]
    code, out, cmd_err = run_cmd(cmd, cwd=root, timeout=15.0)
    if code != 0:
        return {"status": "error", "error": cmd_err or out}

    try:
        return {"status": "ok", "issue": json.loads(out)}
    except json.JSONDecodeError:
        return {"status": "ok", "raw": out}


def gh_issue(
    action: str = "list",
    repo_path: str = ".",
    limit: int = 10,
    issue_number: int = 0,
    path: str | None = None,
) -> dict[str, Any]:
    """Queries issues via the GitHub CLI (`gh`).

    Args:
        action: `list` (default) or `view`.
        repo_path: Path to the Git repository (default `.`).
        limit: Maximum number of issues to list (default 10).
        issue_number: Issue number to view when action is `view`.
        path: Optional alias for `repo_path`.
    """
    if action.strip().lower() == "view":
        return gh_issue_view(issue_number=issue_number, repo_path=repo_path, path=path)
    return gh_issue_list(repo_path=repo_path, limit=limit, path=path)


TOOLS = [
    ToolSpec(
        name="git_status",
        module="git",
        description="Shows Git working tree status, branch, HEAD commit, and staged/unstaged/untracked files.",
        handler=git_status,
        pack="git",
    ),
    ToolSpec(
        name="git_log",
        module="git",
        description="Shows recent Git commit history with hashes, authors, timestamps, and subjects.",
        handler=git_log,
        pack="git",
    ),
    ToolSpec(
        name="git_diff",
        module="git",
        description="Shows unstaged or staged Git diffs and diffstats.",
        handler=git_diff,
        pack="git",
    ),
    ToolSpec(
        name="git_branch",
        module="git",
        description="Lists local and remote Git branches, upstreams, and configured remote URLs.",
        handler=git_branch,
        pack="git",
    ),
    ToolSpec(
        name="git_show",
        module="git",
        description="Shows commit details, message, and changed files for a given revision.",
        handler=git_show,
        pack="git",
    ),
    ToolSpec(
        name="git_stash_list",
        module="git",
        description="Lists saved Git stashes with index, branch, and commit message (git stash list).",
        handler=git_stash_list,
        pack="git",
    ),
    ToolSpec(
        name="git_stash_show",
        module="git",
        description="Shows the diff and file statistics of a Git stash entry (git stash show -p).",
        handler=git_stash_show,
        pack="git",
    ),
    ToolSpec(
        name="git_stash_push",
        module="git",
        description="Saves local modifications to a new stash entry (git stash push).",
        handler=git_stash_push,
        pack="git",
    ),
    ToolSpec(
        name="git_stash_pop",
        module="git",
        description="Applies a stash entry and removes it from the stash list (git stash pop).",
        handler=git_stash_pop,
        pack="git",
    ),
    ToolSpec(
        name="git_stash_apply",
        module="git",
        description="Applies a stash entry without removing it from the stash list (git stash apply).",
        handler=git_stash_apply,
        pack="git",
    ),
    ToolSpec(
        name="git_stash",
        module="git",
        description="Inspects Git stashes (delegates to git_stash_list or git_stash_show).",
        handler=git_stash,
        pack="git",
    ),
    ToolSpec(
        name="git_remote",
        module="git",
        description="Lists configured Git remotes, fetch/push URLs, and commit divergence against upstream.",
        handler=git_remote,
        pack="git",
    ),
    ToolSpec(
        name="git_blame",
        module="git",
        description="Inspects commit author, date, and commit hash for a specific line range of a file.",
        handler=git_blame,
        pack="git",
    ),
    ToolSpec(
        name="git_commit",
        module="git",
        description="Creates a local Git commit with a required message and optional staged files.",
        handler=git_commit,
        pack="git",
    ),
    ToolSpec(
        name="gh_pr_list",
        module="git",
        description="Lists pull requests in a GitHub repository (gh pr list).",
        handler=gh_pr_list,
        pack="git",
    ),
    ToolSpec(
        name="gh_pr_view",
        module="git",
        description="Views full details of a specific pull request (gh pr view).",
        handler=gh_pr_view,
        pack="git",
    ),
    ToolSpec(
        name="gh_pr",
        module="git",
        description="Queries pull requests via the GitHub CLI (delegates to gh_pr_list or gh_pr_view).",
        handler=gh_pr,
        pack="git",
    ),
    ToolSpec(
        name="gh_pr_create",
        module="git",
        description="Creates a pull request on GitHub via the GitHub CLI (gh).",
        handler=gh_pr_create,
        pack="git",
    ),
    ToolSpec(
        name="gh_issue_list",
        module="git",
        description="Lists issues in a GitHub repository (gh issue list).",
        handler=gh_issue_list,
        pack="git",
    ),
    ToolSpec(
        name="gh_issue_view",
        module="git",
        description="Views full details of a specific issue (gh issue view).",
        handler=gh_issue_view,
        pack="git",
    ),
    ToolSpec(
        name="gh_issue",
        module="git",
        description="Queries issues via the GitHub CLI (delegates to gh_issue_list or gh_issue_view).",
        handler=gh_issue,
        pack="git",
    ),
]


def register(mcp: MCPServer) -> None:
    """Register Git tools with MCPServer."""
    for spec in TOOLS:
        mcp.tool(name=spec.name, description=spec.description)(spec.handler)
