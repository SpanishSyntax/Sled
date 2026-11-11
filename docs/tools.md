# Atomic Tools Reference

Sled organizes host inspection and execution capabilities into domain packs. This document catalogs each pack, its constituent atomic tools, parameter signatures, and operational behavior.

---

## Filesystem Pack (fs)

High-performance atomic filesystem inspection, search, hashing, and type detection.

| Tool | Signature | Description |
| :--- | :--- | :--- |
| `ls` | `(path='.', all_files=False, long=False)` | Lists directory contents, automatically filtering out noise directories (`.git`, `node_modules`, `result`, `.direnv`). |
| `cat` | `(path, max_lines=200)` | Reads file contents with line limits to prevent context exhaustion. |
| `head` | `(path, lines=50)` | Reads the initial $N$ lines of a text file. |
| `tail` | `(path, lines=50)` | Reads the trailing $N$ lines of a text file. |
| `find` | `(path='.', name='*', max_depth=5)` | Locates files and directories using `fd` (or standard `find` fallback). |
| `grep` | `(path='.', pattern='', case_sensitive=True)` | Fast regex/literal search using `ripgrep` (`rg`). |
| `stat` | `(path)` | Returns POSIX file metadata (size, permissions, timestamps, inode). |
| `tree` | `(path='.', max_depth=3)` | Emits structured directory hierarchy trees. |
| `jq` | `(path, filter='.')` | Executes `jq` queries against JSON files. |
| `checksum` | `(path, algorithm='sha256')` | Computes SRI and cryptographic hashes (`sha256`, `sha512`, `md5`). |
| `detect_type` | `(path)` | Detects MIME types and binary vs text formats using `file` or Magika. |

---

## Git Repository Pack (git)

Hermetic git inspection and GitHub CLI automation without interactive shell prompts.

| Tool | Signature | Description |
| :--- | :--- | :--- |
| `git` | `(subcommand, args=())` | Safe, non-interactive execution of arbitrary Git subcommands. |
| `git_status` | `(path='.')` | Returns parsed repository state, branch tracking, and staged/unstaged changes. |
| `git_log` | `(path='.', max_count=20, oneline=False)` | Returns formatted commit history. |
| `git_diff` | `(path='.', cached=False, revision=None)` | Returns diff patches with hunk formatting. |
| `git_branch` | `(path='.', all=False)` | Lists local and remote tracking branches. |
| `git_show` | `(object='HEAD', path='.')` | Displays commit metadata and file content at specific revisions. |
| `git_stash` | `(action='list', index=None)` | Lists, shows, or inspects git stashes. |
| `git_remote` | `(path='.')` | Inspects remote endpoints (`fetch` and `push` URLs). |
| `git_blame` | `(path, start_line=1, end_line=100)` | Annotates lines with author, commit hash, and timestamp. |
| `gh_pr` | `(action='list', pr_id=None)` | Inspects pull requests via `gh` CLI. |
| `gh_issue` | `(action='list', issue_id=None)` | Inspects repository issues via `gh` CLI. |

---

## System & Host Pack (system)

Host OS inspection, hardware telemetry, process tables, and path resolution.

| Tool | Signature | Description |
| :--- | :--- | :--- |
| `uname` | `()` | Reports kernel version, hardware architecture, and OS release. |
| `uptime` | `()` | Reports system uptime and load averages (1m, 5m, 15m). |
| `ps` | `(filter=None, user=None)` | Inspects the active process table. |
| `df` | `(human_readable=True)` | Reports filesystem mount points, total capacity, and free space. |
| `free` | `(human_readable=True)` | Reports RAM and swap utilization. |
| `which` | `(binary)` | Resolves binary path within the current system `PATH`. |
| `lsblk` | `()` | Lists block devices, partitions, and mount assignments. |
| `zoxide_query` | `(query)` | Queries the Zoxide frecency database for directory jumps. |

---

## Docker & Container Pack (docker)

Container lifecycle monitoring, container logs, and Docker Compose orchestration.

| Tool | Signature | Description |
| :--- | :--- | :--- |
| `docker_ps` | `(all=False)` | Lists running or stopped containers. |
| `docker_logs` | `(container, tail=100)` | Retrieves stdout/stderr logs from a container. |
| `docker_inspect` | `(target)` | Returns structured configuration for a container, image, or volume. |
| `docker_stats` | `(no_stream=True)` | Reports live CPU, memory, and network I/O per container. |
| `docker_images` | `()` | Lists locally stored container images and tags. |
| `docker_volumes` | `()` | Lists persistent Docker volumes. |
| `docker_networks` | `()` | Lists bridge, host, and overlay container networks. |
| `docker_action` | `(action, container)` | Performs lifecycle transitions (`start`, `stop`, `restart`, `pause`, `unpause`). |
| `docker_compose` | `(action, compose_file='docker-compose.yml')` | Manages multi-container stacks (`ps`, `logs`, `up`, `down`). |

---

## Systemd & Journald Pack (systemd)

Init system service inspection and systemd journal log streaming.

| Tool | Signature | Description |
| :--- | :--- | :--- |
| `systemctl_list` | `(user=False, type='service')` | Lists systemd units and their active/sub states. |
| `systemctl_status` | `(unit, user=False)` | Queries detailed properties, PID, and recent logs for a unit. |
| `journalctl` | `(unit=None, lines=50, user=False)` | Streams journal logs with unit and priority filtering. |
| `systemctl_action` | `(action, unit, user=False)` | Executes lifecycle actions (`start`, `stop`, `restart`, `reload`). |

---

## NixOS & Flake Pack (nixos)

Hermetic NixOS generation tracking, flake evaluation, store size queries, and build triggers.

| Tool | Signature | Description |
| :--- | :--- | :--- |
| `nixos_generations` | `()` | Lists bootable system and Home Manager generations. |
| `nix_flake_metadata` | `(flake_path='.')` | Reads lockfile inputs, revisions, and commit dates. |
| `nix_flake_show` | `(flake_path='.')` | Inspects exposed flake outputs (packages, apps, devShells). |
| `nix_search` | `(query, channel='nixpkgs')` | Queries nixpkgs packages and descriptions. |
| `nix_eval` | `(expr, flake=True)` | Evaluates Nix expressions safely. |
| `nix_store_info` | `(path)` | Queries Nix store closure size and derivation paths. |
| `nix_flake_check` | `(flake_path='.')` | Validates flake structure and evaluates checks. |
| `nix_diff_generations`| `(profile='/nix/var/nix/profiles/system')` | Computes package version diffs between system generations. |
| `nix_build` | `(attribute, flake_path='.')` | Builds a Nix derivation and creates a result symlink. |
| `nix_run` | `(app, args=())` | Executes an app defined inside a Nix flake. |
| `nix_develop` | `(command, flake_path='.')` | Executes commands inside a hermetic Nix development shell. |

---

## Network & Sockets Pack (network)

Socket inspection, interface telemetry, ICMP reachability, and Tailscale integration.

| Tool | Signature | Description |
| :--- | :--- | :--- |
| `ip_addr` | `()` | Reports local network interfaces and assigned IPv4/IPv6 addresses. |
| `ip_route` | `()` | Displays host routing table and default gateways. |
| `ss_ports` | `(listening=True, tcp=True, udp=True)` | Lists active sockets and binding addresses using `ss`. |
| `ping` | `(host, count=3)` | Measures ICMP latency and packet loss. |
| `tailscale_status` | `()` | Reports Tailscale mesh peers, connection status, and IP addresses. |
| `dns_lookup` | `(domain, record_type='A')` | Resolves DNS records using `dig` or standard resolver. |
| `http_probe` | `(url, timeout=5)` | Evaluates HTTP status code, latency, and response headers. |

---

## Development Toolchain Pack (dev)

Polyglot code formatters, static linters, and Frost environment diagnostics.

| Tool | Signature | Description |
| :--- | :--- | :--- |
| `code_format` | `(path, check_only=False)` | Formats code with detected tool (`ruff`, `rustfmt`, `alejandra`, `shfmt`). |
| `code_lint` | `(path)` | Lints code using `statix`, `shellcheck`, `ruff`, or `clippy`. |
| `code_check` | `(path)` | Executes type checking and compiler checks (`mypy`, `cargo check`). |
| `dev_env` | `()` | Diagnoses available Frost toolchains and compilers in current shell. |

---

## External Application Bridges

Sled supports dynamic reverse-proxied MCP connections to standalone Frost iceberg applications (`Basecamp`, `Snowpack`, `Lantern`, `Barograph`, `Rime`, `Borealis`, `Goggles`, `Searchlight`).

When activated via `sled enable <bridge_name>`, Sled spawns the target application's stdio bridge and routes tool invocations through a zero-trust sub-channel.
