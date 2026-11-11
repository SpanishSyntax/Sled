# Architecture & Design

Sled serves as the atomic host inspection and execution layer for AI coding agents operating within the SpanishSyntax Frost and NixOS ecosystem.

---

## System Philosophy

Traditional agent integrations rely heavily on two flawed paradigms:
1. **Unrestricted shell execution**: Arbitrary `bash -c` execution introduces quoting errors, command injection vectors, non-deterministic shell rc loading, and unbounded token output.
2. **Monolithic macro-tools**: Mega-tools bundle multiple operations together, masking low-level failure points and increasing model hallucination.

Sled replaces both paradigms with **atomic, hermetic MCP primitives**:
- Each capability is an isolated Python function with a strongly typed signature, docstring parameter schema, and explicit return envelope.
- Commands execute through Python's `subprocess.run` with discrete argument vectors, bypassing shell interpolation entirely.
- Large output buffers are automatically truncated and summarized to conserve context tokens.

```
┌────────────────────────────────────────────────────────┐
│                   MCP Client Engine                    │
│             (Antigravity / OpenCode / Claude)          │
└───────────────────────────┬────────────────────────────┘
                            │ JSON-RPC 2.0 (stdio)
                            ▼
┌────────────────────────────────────────────────────────┐
│                       Sled Core                        │
│ ┌──────────────────────┐      ┌──────────────────────┐ │
│ │  Zero-Trust Filter   │◄────►│   sled.toml Config   │ │
│ └──────────┬───────────┘      └──────────────────────┘ │
│            │ Whitelisted tools only                    │
│            ▼                                           │
│ ┌────────────────────────────────────────────────────┐ │
│ │             Atomic Capability Registry             │ │
│ │  [fs] [git] [system] [docker] [systemd] [nixos]    │ │
│ └──────────────────────┬─────────────────────────────┘ │
└────────────────────────┼───────────────────────────────┘
                         │ Direct POSIX sub-calls
                         ▼
┌────────────────────────────────────────────────────────┐
│           Host OS / Kernel / Nix Store Layers          │
└────────────────────────────────────────────────────────┘
```

---

## Why "Sled"? (The Lore)

> **sled** (`/slɛd/`) — *noun:* The rugged, low-friction wooden vehicle built to haul essential survival cargo, precision scientific instruments, and heavy supplies across trackless snow without bogging down.

When navigating polar pack ice, heavy wheeled vehicles sink into deep snow and pressure ridges. Only a lightweight, low-friction sled distributes weight evenly across the crust and keeps vital cargo mobile.

In agentic computing, Sled is that low-friction vehicle. It strips out runtime drag, transporting focused tools directly into the context window without the overhead of heavy terminal wrappers or slow virtualization boundaries.

---

## Stdio Stream Discipline

The Model Context Protocol specification requires standard input and standard output to exchange strict JSON-RPC 2.0 frames:

$$\text{Stream Protocol} = \begin{cases}
\texttt{sys.stdout} & \longrightarrow \text{Strict JSON-RPC 2.0 messages only} \\
\texttt{sys.stderr} & \longrightarrow \text{Logs, diagnostics, Prism badges, and warnings} \\
\texttt{sys.stdin}  & \longleftarrow \text{Incoming client RPC requests}
\end{cases}$$

If any Python library writes non-RPC text or warning messages to `sys.stdout`, the client's JSON parser crashes, terminating the session.

To enforce this discipline:
1. `run_stdio_server()` rebinds the global UI stream: `ui.set_stream(sys.stderr)`.
2. Python logging handlers are explicitly reconfigured to direct all root and child loggers (`mcp`, `fastmcp`, `httpx`, `sled`) exclusively to `sys.stderr`.
3. Tool execution helpers (`_exec.py`) capture stdout and stderr from child processes independently.

---

## Zero-Trust Security & Whitelisting

Sled implements a strict **Zero-Trust Policy**:
- Discovered tools are **inactive by default**.
- A tool is registered with the MCP server if and only if it is explicitly enabled in `~/.config/sled/sled.toml`.

### Resolution Algorithm

The active tool list is resolved according to the following precedence rules:

1. **Explicit Tool Exclusion**: If tool $t \in \text{tools.disabled}$, it is excluded regardless of pack settings.
2. **Explicit Pack Exclusion**: If pack $p \in \text{packs.disabled}$, no tools from pack $p$ are included unless individually specified in $\text{tools.enabled}$.
3. **Explicit Tool Inclusion**: If tool $t \in \text{tools.enabled}$, it is included.
4. **Pack Expansion**: If pack $p \in \text{packs.enabled}$, all constituent tools of $p$ are included (subject to rule 1).
5. **Default State**: If neither pack nor tool is whitelisted, the tool is suppressed.

---

## Dual-Mode Store Engine

Sled operates at two synchronized granularities:

### Pack Mode (`sled store` / `sled packs`)
Groups tools by functional domain (`fs`, `git`, `system`, `docker`, `systemd`, `nixos`, `network`, `dev`). Toggling a pack toggles all member tools simultaneously while maintaining explicit visibility of which tools are active.

### Atomic Tool Mode (`sled store tools` / `sled tools`)
Permits individual activation or deactivation of any single tool. Developers can enable read-only git tools (`git_status`, `git_log`, `git_diff`) while disabling mutating tools (`docker_action`, `systemctl_action`).

### In-Memory Local Search (`sled search <query>`)
Queries the in-memory catalog across tool names, pack IDs, parameter names, and docstring descriptions using tokenized matching. Search executes locally in sub-millisecond time with zero external network dependencies.
