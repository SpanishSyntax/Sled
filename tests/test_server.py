from sled.tools import (
    PACK_CATALOG,
    _discover_all_tool_specs,
    get_all_tool_map,
)

try:
    from mcp.server import MCPServer
except ImportError:
    try:
        from mcp.server.fastmcp import FastMCP as MCPServer
    except ImportError:
        from mcp.server.mcpserver import MCPServer
from sled.tools import register_all_tools


def test_catalog_and_discovery():
    assert "fs" in PACK_CATALOG
    assert "git" in PACK_CATALOG
    assert "system" in PACK_CATALOG

    all_specs = _discover_all_tool_specs()
    assert len(all_specs) >= 60

    tool_map = get_all_tool_map()
    assert "ls" in tool_map
    assert "cat" in tool_map
    assert "grep" in tool_map
    assert "git_status" in tool_map
    assert "ps" in tool_map


def test_mcpserver_registration(tmp_path):
    # Zero-trust verification: with an empty config, 0 tools are registered
    empty_cfg = tmp_path / "empty_sled.toml"
    empty_cfg.write_text("[store]\nenabled_tools = []\n")
    mcp_empty = MCPServer("TestSledEmpty")
    registered_empty = register_all_tools(mcp_empty, explicit_config=str(empty_cfg))
    assert registered_empty == []

    # With explicit enabled tools, only requested tools are registered
    active_cfg = tmp_path / "active_sled.toml"
    active_cfg.write_text('[store]\nenabled_tools = ["ls", "git_status", "ps"]\n')
    mcp = MCPServer("TestSled")
    registered = register_all_tools(mcp, explicit_config=str(active_cfg))
    assert len(registered) == 3
    assert "ls" in registered
    assert "git_status" in registered
    assert "ps" in registered
