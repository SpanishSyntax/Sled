"""Sled Pack: `dev` — Polyglot language formatters, linters, diagnostics, and toolchain inspection."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sled.tools import ToolSpec
from sled.tools._exec import run_cmd, which_bin

if TYPE_CHECKING:
    from mcp.server import MCPServer

logger = logging.getLogger("sled.tools.dev")

PACK = "dev"


FORMATTER_MAP: dict[str, tuple[str, list[str]]] = {
    ".py": ("ruff", ["ruff", "format"]),
    ".pyi": ("ruff", ["ruff", "format"]),
    ".rs": ("rustfmt", ["rustfmt"]),
    ".nix": ("alejandra", ["alejandra", "-q"]),
    ".sh": ("shfmt", ["shfmt", "-w"]),
    ".bash": ("shfmt", ["shfmt", "-w"]),
    ".c": ("clang-format", ["clang-format", "-i"]),
    ".cpp": ("clang-format", ["clang-format", "-i"]),
    ".cc": ("clang-format", ["clang-format", "-i"]),
    ".h": ("clang-format", ["clang-format", "-i"]),
    ".hpp": ("clang-format", ["clang-format", "-i"]),
    ".typ": ("typstyle", ["typstyle", "-i"]),
    ".toml": ("taplo", ["taplo", "fmt"]),
    ".lua": ("stylua", ["stylua"]),
    ".js": ("prettierd", ["prettierd"]),
    ".jsx": ("prettierd", ["prettierd"]),
    ".ts": ("prettierd", ["prettierd"]),
    ".tsx": ("prettierd", ["prettierd"]),
    ".json": ("prettierd", ["prettierd"]),
    ".yaml": ("prettierd", ["prettierd"]),
    ".yml": ("prettierd", ["prettierd"]),
    ".md": ("prettierd", ["prettierd"]),
    ".go": ("gofmt", ["gofmt", "-w"]),
    ".java": ("google-java-format", ["google-java-format", "-i"]),
}


def code_format(file_path: str, check_only: bool = False) -> dict[str, Any]:
    """Formats code or checks formatting for any supported language in Frost.

    Supports Python (ruff), Rust (rustfmt), Nix (alejandra), Shell (shfmt),
    C/C++ (clang-format), Typst (typstyle), TOML (taplo), Lua (stylua),
    JS/TS/JSON/YAML/Markdown (prettierd), and Go (gofmt). Gracefully fails if the
    formatter is not installed.

    Args:
        file_path: Path to the source file to format.
        check_only: If True, only check if formatting is required without writing (default False).
    """
    target = Path(file_path).expanduser().resolve()
    if not target.is_file():
        return {"status": "error", "error": f"File does not exist: {target}"}

    ext = target.suffix.lower()
    mapping = FORMATTER_MAP.get(ext)
    if not mapping:
        return {
            "status": "error",
            "file": str(target),
            "error": f"No registered formatter for extension `{ext}`.",
        }

    tool_bin, base_cmd = mapping
    if not which_bin(tool_bin):
        return {
            "status": "error",
            "file": str(target),
            "formatter": tool_bin,
            "error": f"Formatter `{tool_bin}` not found in PATH. Enable language support in Frost or install `{tool_bin}`.",
        }

    cmd = list(base_cmd)
    if check_only:
        if tool_bin == "ruff":
            cmd = ["ruff", "format", "--check"]
        elif tool_bin == "rustfmt":
            cmd = ["rustfmt", "--check"]
        elif tool_bin == "alejandra":
            cmd = ["alejandra", "--check"]
        elif tool_bin == "shfmt":
            cmd = ["shfmt", "-d"]
        elif tool_bin == "taplo":
            cmd = ["taplo", "fmt", "--check"]
        elif tool_bin == "stylua":
            cmd = ["stylua", "--check"]
        elif tool_bin == "typstyle":
            cmd = ["typstyle", "--check"]

    cmd.append(str(target))
    code, stdout, stderr = run_cmd(cmd, cwd=target.parent, timeout=15.0)

    return {
        "status": "ok" if code == 0 else "error",
        "file": str(target),
        "formatter": tool_bin,
        "check_only": check_only,
        "exit_code": code,
        "stdout": stdout,
        "stderr": stderr,
    }


def code_lint(file_path: str) -> dict[str, Any]:
    """Runs language-specific linters and diagnostics on a file.

    Supports Python (ruff check), Shell (shellcheck), Nix (statix check),
    and TOML (taplo lint). Gracefully fails if the linter is not installed.

    Args:
        file_path: Path to the source file to lint.
    """
    target = Path(file_path).expanduser().resolve()
    if not target.is_file():
        return {"status": "error", "error": f"File does not exist: {target}"}

    ext = target.suffix.lower()

    if ext in (".py", ".pyi"):
        if not which_bin("ruff"):
            return {
                "status": "error",
                "file": str(target),
                "error": "`ruff` not found in PATH; enable Python support in Frost.",
            }
        code, stdout, stderr = run_cmd(
            ["ruff", "check", "--output-format=json", str(target)],
            cwd=target.parent,
            timeout=15.0,
        )
        try:
            issues = json.loads(stdout) if stdout else []
            return {
                "status": "ok",
                "file": str(target),
                "linter": "ruff",
                "issue_count": len(issues),
                "issues": issues,
            }
        except json.JSONDecodeError:
            return {
                "status": "ok" if code == 0 else "lint_errors",
                "file": str(target),
                "linter": "ruff",
                "raw_output": stdout or stderr,
            }

    if ext in (".sh", ".bash"):
        if not which_bin("shellcheck"):
            return {
                "status": "error",
                "file": str(target),
                "error": "`shellcheck` not found in PATH; enable Bash support in Frost.",
            }
        code, stdout, stderr = run_cmd(
            ["shellcheck", "-f", "json", str(target)],
            cwd=target.parent,
            timeout=15.0,
        )
        try:
            issues = json.loads(stdout) if stdout else []
            return {
                "status": "ok",
                "file": str(target),
                "linter": "shellcheck",
                "issue_count": len(issues),
                "issues": issues,
            }
        except json.JSONDecodeError:
            return {
                "status": "ok" if code == 0 else "lint_errors",
                "file": str(target),
                "linter": "shellcheck",
                "raw_output": stdout or stderr,
            }

    if ext == ".nix":
        if not which_bin("statix"):
            return {
                "status": "error",
                "file": str(target),
                "error": "`statix` not found in PATH; enable Nix support in Frost.",
            }
        code, stdout, stderr = run_cmd(
            ["statix", "check", "-o", "json", str(target)],
            cwd=target.parent,
            timeout=15.0,
        )
        try:
            issues = json.loads(stdout) if stdout else []
            return {
                "status": "ok",
                "file": str(target),
                "linter": "statix",
                "issue_count": len(issues),
                "issues": issues,
            }
        except json.JSONDecodeError:
            return {
                "status": "ok" if code == 0 else "lint_errors",
                "file": str(target),
                "linter": "statix",
                "raw_output": stdout or stderr,
            }

    if ext == ".toml":
        if not which_bin("taplo"):
            return {
                "status": "error",
                "file": str(target),
                "error": "`taplo` not found in PATH; enable TOML support in Frost.",
            }
        code, stdout, stderr = run_cmd(
            ["taplo", "lint", str(target)],
            cwd=target.parent,
            timeout=15.0,
        )
        return {
            "status": "ok" if code == 0 else "lint_errors",
            "file": str(target),
            "linter": "taplo",
            "clean": code == 0,
            "output": stdout or stderr,
        }

    return {
        "status": "error",
        "file": str(target),
        "error": f"No registered linter for file extension `{ext}`.",
    }


def code_check(file_path: str) -> dict[str, Any]:
    """Runs static type analysis or compiler checks for a source file.

    Supports Python (ty check), Rust (cargo check), and Nix (nix flake check).
    Gracefully reports missing tools.

    Args:
        file_path: Path to the target source file or project directory.
    """
    target = Path(file_path).expanduser().resolve()
    ext = target.suffix.lower() if target.is_file() else ""

    if ext in (".py", ".pyi") or (
        target.is_dir() and (target / "pyproject.toml").exists()
    ):
        if not which_bin("ty"):
            return {
                "status": "error",
                "error": "`ty` static analyzer not found in PATH; enable Python support in Frost.",
            }
        code, stdout, stderr = run_cmd(
            ["ty", "check", str(target)],
            cwd=target.parent if target.is_file() else target,
            timeout=20.0,
        )
        return {
            "status": "ok" if code == 0 else "type_errors",
            "checker": "ty",
            "exit_code": code,
            "stdout": stdout,
            "stderr": stderr,
        }

    if ext == ".rs" or (target.is_dir() and (target / "Cargo.toml").exists()):
        if not which_bin("cargo"):
            return {
                "status": "error",
                "error": "`cargo` not found in PATH; enable Rust support in Frost.",
            }
        code, stdout, stderr = run_cmd(
            ["cargo", "check", "--message-format=short"],
            cwd=target.parent if target.is_file() else target,
            timeout=30.0,
        )
        return {
            "status": "ok" if code == 0 else "compiler_errors",
            "checker": "cargo",
            "exit_code": code,
            "stdout": stdout,
            "stderr": stderr,
        }

    if ext == ".nix" or (target.is_dir() and (target / "flake.nix").exists()):
        code, stdout, stderr = run_cmd(
            ["nix", "flake", "check", "--no-build"],
            cwd=target.parent if target.is_file() else target,
            timeout=60.0,
        )
        return {
            "status": "ok" if code == 0 else "flake_errors",
            "checker": "nix-flake-check",
            "exit_code": code,
            "stdout": stdout,
            "stderr": stderr,
        }

    return {
        "status": "error",
        "error": f"No static checker mapped for `{target.name}`.",
    }


def dev_env() -> dict[str, Any]:
    """Inspects the availability, binary locations, and versions of language toolchains and linters from Frost."""
    tools_to_check = [
        ("python", "python3"),
        ("python_linter", "ruff"),
        ("python_typecheck", "ty"),
        ("rust_compiler", "rustc"),
        ("rust_cargo", "cargo"),
        ("rust_formatter", "rustfmt"),
        ("rust_lsp", "rust-analyzer"),
        ("go_compiler", "go"),
        ("go_lsp", "gopls"),
        ("c_formatter", "clang-format"),
        ("shell_linter", "shellcheck"),
        ("shell_formatter", "shfmt"),
        ("nix_tool", "nix"),
        ("nix_formatter", "alejandra"),
        ("nix_linter", "statix"),
        ("typst_compiler", "typst"),
        ("typst_formatter", "typstyle"),
        ("toml_formatter", "taplo"),
        ("lua_formatter", "stylua"),
        ("js_formatter", "prettierd"),
        ("github_cli", "gh"),
        ("git_tui", "lazygit"),
    ]

    report: dict[str, dict[str, Any]] = {}
    available_count = 0

    for label, binary in tools_to_check:
        resolved = which_bin(binary)
        if resolved:
            available_count += 1
            code, out, err = run_cmd([resolved, "--version"], timeout=4.0)
            ver = (out or err).splitlines()[0].strip() if (out or err) else "installed"
            report[label] = {
                "binary": binary,
                "installed": True,
                "path": resolved,
                "version": ver if code == 0 else f"installed ({ver})",
            }
        else:
            report[label] = {
                "binary": binary,
                "installed": False,
                "path": None,
                "version": None,
            }

    return {
        "status": "ok",
        "installed_count": available_count,
        "total_checked": len(tools_to_check),
        "tools": report,
    }


TOOLS = [
    ToolSpec(
        name="code_format",
        module="dev",
        description="Formats code or checks formatting for any supported language in Frost (ruff, rustfmt, alejandra, shfmt, etc.).",
        handler=code_format,
        pack="dev",
    ),
    ToolSpec(
        name="code_lint",
        module="dev",
        description="Runs language-specific linters and diagnostics (ruff check, shellcheck, statix, taplo) returning structured issues.",
        handler=code_lint,
        pack="dev",
    ),
    ToolSpec(
        name="code_check",
        module="dev",
        description="Runs static type analysis or compiler checks (ty check, cargo check, nix flake check).",
        handler=code_check,
        pack="dev",
    ),
    ToolSpec(
        name="dev_env",
        module="dev",
        description="Inspects the availability, binary locations, and versions of language toolchains and linters from Frost.",
        handler=dev_env,
        pack="dev",
    ),
]


def register(mcp: MCPServer) -> None:
    """Register development and language tools with MCPServer."""
    for spec in TOOLS:
        mcp.tool(name=spec.name, description=spec.description)(spec.handler)
