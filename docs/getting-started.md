# Getting Started

This guide walks through installing Sled, initializing your configuration, running the MCP server bridge, and connecting client applications.

---

## Installation

### Nix Flake (Recommended)

Run Sled directly using Nix Flakes:

```bash
# Run interactive store
nix run github:SpanishSyntax/Sled -- store

# Run MCP server bridge over stdio
nix run github:SpanishSyntax/Sled -- serve
```

To load Sled into your ephemeral shell:

```bash
nix shell github:SpanishSyntax/Sled
```

### Python Package (pip)

Clone the repository and install with pip:

```bash
git clone https://github.com/SpanishSyntax/Sled.git
cd Sled
pip install .
```

For development mode:

```bash
pip install -e .
```

---

## Quick Start

### 1. Initialize Configuration

Sled employs a Zero-Trust security model: upon fresh installation, no tools are active until declared in `~/.config/sled/sled.toml`.

To enable initial packs:

```bash
# Enable foundational filesystem and git packs
sled enable fs git system
```

Alternatively, launch the interactive store to toggle packs and tools:

```bash
sled store
```

### 2. Verify Available Tools

List all enabled atomic tools:

```bash
sled tools
```

To view all built-in tools regardless of activation state:

```bash
sled tools --all
```

### 3. Test Direct Tool Execution

Before attaching an MCP client, test tools directly from your terminal:

```bash
# Inspect current directory
sled run ls path=.

# View recent git commits
sled run git_log max_count=5

# Check kernel and host properties
sled run uname
```

---

## MCP Client Configuration

Sled runs as a standard Model Context Protocol (MCP) server communicating over `stdio`.

### Antigravity / OpenCode Configuration

Add the server definition to your MCP settings file (e.g., `~/.gemini/antigravity-cli/mcp_config.json` or project-local config):

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

Or via direct Nix invocation without global installation:

```json
{
  "mcpServers": {
    "sled": {
      "command": "nix",
      "args": ["run", "github:SpanishSyntax/Sled", "--", "serve"]
    }
  }
}
```

### Claude Desktop Configuration

In `~/.config/Claude/claude_desktop_config.json` (Linux) or `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS):

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

To generate this snippet automatically from your active Sled configuration:

```bash
sled hub-json
```

---

## NixOS & Frost Integration

In the **Frost** ecosystem, Sled is managed declaratively via Home Manager:

```nix
# home/applications/icebergs/sled.nix
{ config, lib, pkgs, ... }:

{
  frost.home.apps.icebergs.sled = {
    enable = true;

    # Declarative pack enablement
    packs = [
      "fs"
      "git"
      "system"
      "docker"
      "systemd"
      "nixos"
      "network"
      "dev"
    ];

    # Optional atomic tool overrides:
    # tools = [ "ls" "cat" "grep" "git_status" "docker_ps" ];
  };
}
```

By default in Frost, `~/.config/sled/sled.toml` is symlinked via `mkOutOfStoreSymlink` to the live repository dotfile. Edits made via `sled store` or `sled enable` persist immediately without requiring a full `nixos-rebuild switch`.
