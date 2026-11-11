# Integration & Usage Guide

This guide describes operational workflows, configuration recipes, and integration patterns for Sled.

---

## Interactive Store & TUI

Sled includes a terminal interface built with Prism for browsing, searching, and configuring MCP tools without manual TOML editing.

### Launching the Store

```bash
# Launch in Pack Mode (group-level toggling)
sled store

# Launch directly in Atomic Tool Mode (per-tool toggling)
sled store tools
```

### Store Keybindings

| Key | Action |
| :--- | :--- |
| `Up` / `Down` (or `k` / `j`) | Navigate highlighted item |
| `Space` | Toggle enablement of the highlighted pack or tool |
| `a` | Select or deselect all items |
| `/` | Enter live fuzzy search filter mode |
| `Tab` | Switch between Pack Mode and Atomic Tool Mode |
| `Enter` | Save selection to `~/.config/sled/sled.toml` and exit |
| `q` / `Esc` | Abort without saving changes |

---

## CLI Management Recipes

For automated provisioning or scripted setup, Sled exposes direct command-line verbs.

### Searching Tools & Packs

Search the built-in catalog locally without starting an MCP session:

```bash
# Search for logging tools across all packs
sled search log

# Search for network tools
sled search network

# Interactive search: filter and toggle directly
sled search docker -i
```

### Enabling and Disabling Capabilities

```bash
# Enable whole packs
sled enable fs git system

# Enable individual atomic tools
sled enable docker_ps docker_logs journalctl

# Disable mutating tools for safe agent execution
sled disable docker_action systemctl_action

# Disable an entire pack
sled disable network
```

### Emitting JSON and TOON Summaries

```bash
# Dump active tools as JSON
sled tools --json

# Dump active tools as Token-Oriented Object Notation (TOON) for LLMs
sled tools --toon

# Dump full tool catalog including disabled entries
sled tools --all --json
```

---

## Direct Tool Execution

You can run any registered atomic tool directly from your shell. This enables testing arguments and inspecting output schemas before deploying with an AI agent.

### Syntax

```bash
sled run <tool_name> [parameter=value ...]
```

### Examples

```bash
# Inspect directory structure
sled run ls path=/etc/nixos all_files=false

# Search for patterns in source files
sled run grep path=src pattern="class ToolSpec"

# Run non-interactive git status
sled run git_status path=.

# Check host memory utilization
sled run free human_readable=true

# Inspect running Docker containers
sled run docker_ps all=false

# Query journal logs for systemd units
sled run journalctl unit=tailscaled lines=25
```

---

## Client Integration

### Antigravity & OpenCode Setup

In your agent client configuration file:

```json
{
  "mcpServers": {
    "sled": {
      "command": "sled",
      "args": ["serve"]
    }
  }
}
```

### Claude Desktop Setup

To connect Sled to Claude Desktop, insert the configuration snippet into:
- Linux: `~/.config/Claude/claude_desktop_config.json`
- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`

```json
{
  "mcpServers": {
    "sled": {
      "command": "sled",
      "args": ["serve"]
    }
  }
}
```

### Automatic Hub Configuration

To print a pre-configured JSON snippet matching your active system paths:

```bash
sled hub-json
```

Copy the generated JSON block directly into your client's settings.
