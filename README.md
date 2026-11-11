<p align="center">
  <img src="assets/banner.png" alt="Alaskan dog sled team and driver hauling cargo across the arctic snow in 1914" width="100%" />
</p>

# 🛷 Sled

> **NixOS Atomic Model Context Protocol (MCP) Store & Server Bridge for the SpanishSyntax & Frost Ecosystem**

`Sled` is a pure, hermetic Model Context Protocol (MCP) Store and Server Bridge built for the **Frost** NixOS ecosystem alongside [`Basecamp`](https://github.com/SpanishSyntax/Basecamp), [`Rime`](https://github.com/SpanishSyntax/Rime), [`Snowpack`](https://github.com/SpanishSyntax/Snowpack), [`Borealis`](https://github.com/SpanishSyntax/Borealis), [`Barograph`](https://github.com/SpanishSyntax/Barograph), [`Goggles`](https://github.com/SpanishSyntax/Goggles), `Searchlight`, and `Tundra`.

Instead of monolithic macro-tools or abstract bundles, **Sled atomizes every capability into focused Unix, Git, System, Docker, Systemd, NixOS, and Network primitives** (`ls`, `cat`, `grep`, `git_status`, `ps`, `df`, `docker_ps`, `journalctl`, `nix_search`, etc.).

---

## Why "Sled"? (The Lore)

> **sled** (`/slɛd/`) — *noun:* The rugged, low-friction wooden vehicle built to haul essential survival cargo, precision scientific instruments, and heavy supplies across trackless snow without bogging down.

You cannot traverse polar glaciers in heavy wheeled trucks; only a flexible, low-friction sled distributes weight evenly across the crust and keeps cargo moving forward through the deepest drifts.

**Sled carries atomic tools to AI coding agents:**
- **Low-Friction Hauling**: Bridges Model Context Protocol (MCP) clients with lightweight, atomic Unix, Git, Docker, Systemd, and NixOS inspection tools.
- **Zero-Drag Hermeticity**: Bypasses heavy shell overhead and monolithic macro-bundles, delivering deterministic execution and pure command responses directly into agent contexts.

---

## 🏪 Dual-Mode Store & Local Tool Search

Sled operates at two synchronized granularities:
1. **Pack Mode** (`sled store` / `sled packs`): Group-level toggling with live preview of member tools right in the pack description.
2. **Atomic Tool Mode** (`sled store tools` / `sled tools`): Toggle every single tool on or off independently.
3. **Local Search** (`sled search <query>` / `/` in TUI): Search across all built-in tools and packs locally by name, pack, description, and arguments—with zero external network requests.

Press **`Tab`** in `sled store` at any time to switch instantly between **Pack Mode** and **Tool Mode**, and press **`/`** to live-filter matching tools.

---

## 📦 Capability Packs & 72 Atomic Tools

| Pack | Icon | Atomic Tools | Description |
| :--- | :---: | :--- | :--- |
| **`fs`** | 📁 | `ls`, `cat`, `head`, `tail`, `find`, `grep`, `stat`, `tree`, `jq`, `checksum`, `detect_type` | Atomic filesystem inspection, ripgrep/fd-accelerated search, jq filters, Nix SRI hashes, and Magika file typing |
| **`git`** | 🌿 | `git`, `git_status`, `git_log`, `git_diff`, `git_branch`, `git_show`, `git_stash`, `git_remote`, `git_blame`, `gh_pr`, `gh_issue` | Non-interactive Git execution, status, history, diffs, branches, commits, stashes, divergence, blame, and GitHub CLI PRs/issues |
| **`system`** | 🖥️ | `uname`, `uptime`, `ps`, `df`, `free`, `which`, `lsblk`, `zoxide_query` | Host OS/kernel info, uptime, process table, disk usage, memory, PATH binaries, block devices, and Zoxide path queries |
| **`docker`** | 🐳 | `docker_ps`, `docker_logs`, `docker_inspect`, `docker_stats`, `docker_images`, `docker_volumes`, `docker_networks`, `docker_action`, `docker_compose` | Containers, logs, stats, images, volumes, networks, lifecycle, and Compose |
| **`systemd`** | 🔧 | `systemctl_list`, `systemctl_status`, `journalctl`, `systemctl_action` | System & user service units, properties, lifecycle actions, and journal logs |
| **`nixos`** | ❄️ | `nixos_generations`, `nix_flake_metadata`, `nix_flake_show`, `nix_search`, `nix_eval`, `nix_store_info`, `nix_flake_check`, `nix_diff_generations`, `nix_build`, `nix_run`, `nix_develop` | System/HM generations, flake inspection, nixpkgs search, evaluation, store size, flake check, generation diffs, package builds, app runs, and hermetic DevShell execution |
| **`network`** | 🌐 | `ip_addr`, `ip_route`, `ss_ports`, `ping`, `tailscale_status`, `dns_lookup`, `http_probe` | IP interfaces, routing table, listening ports (`ss`), ICMP ping, Tailscale mesh, DNS queries (`dig`), and HTTP latency probes |
| **`icebergs`** | 🏔️ | Bridged dynamically via `sled bridge` | Decentralized micro-MCP servers hosted inside Frost ecosystem applications (`basecamp`, `snowpack`, `lantern`, `barograph`, `rime`, `borealis`, `goggles`, `searchlight`, `skald`), reverse-proxied over zero-trust stdio bridges |
| **`dev`** | 🛠️ | `code_format`, `code_lint`, `code_check`, `dev_env` | Polyglot formatters (ruff, rustfmt, alejandra, shfmt), linters (shellcheck, statix, taplo), static checks (ty, cargo), and Frost toolchain diagnostics |

---

## 🚀 Quick Start

```bash
# Open interactive dashboard
sled

# Launch interactive Store (Pack Mode; press Tab for Tool Mode, / for live search)
sled store

# Launch directly in Atomic Tool Mode
sled store tools

# Search built-in tools locally (e.g. matching "log")
sled search log

# Search and interactively toggle matching tools
sled search log -i

# Enable or disable whole packs OR individual atomic tools
sled enable fs git
sled disable docker_action systemctl_action

# Inspect registered atomic tools with parameter signatures
sled tools

# Execute any atomic tool directly from your terminal
sled run ls path=.
sled run ping host=1.1.1.1 count=1
sled run uname

# Start the MCP stdio server (used by Antigravity, OpenCode, Claude)
sled serve
```

---

## ❄️ Frost Integration (`home/applications/icebergs/sled.nix`)

By default in **Frost**, `sled` uses `mkOutOfStoreSymlink` pointing `~/.config/sled/sled.toml` -> `~/Frost/home/configs/sled/sled.toml` so changes made via `sled store` or `sled enable/disable` take effect immediately without a NixOS rebuild while staying tracked in Git.

```nix
frost.home.apps.icebergs.sled = {
  enable = true;

  # Declarative packs or atomic tools (optional):
  # packs = [ "fs" "git" "system" "docker" "systemd" "nixos" "network" ];
  # tools = [ "ls" "cat" "grep" "git_status" "docker_ps" "journalctl" ];
};
```

---

## 📜 License

MIT © SpanishSyntax
