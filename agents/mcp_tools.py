"""
agents/mcp_tools.py

Shared MCP toolset definitions for all agents.
Each toolset connects to one MCP server via stdio and exposes its tools
to any agent that includes it in its tools=[] list.

ADK 2.x requires MCP tools to be passed as McpToolset objects —
plain function references don't work for tools hosted in MCP servers.
"""

import sys
from pathlib import Path
from mcp import StdioServerParameters
from google.adk.tools import McpToolset
from google.adk.tools.mcp_tool.mcp_toolset import StdioConnectionParams

_MCP_DIR = Path(__file__).parent.parent / "mcp_servers"
_MCP_TIMEOUT = 60.0

browser_toolset = McpToolset(
    connection_params=StdioConnectionParams(
        server_params=StdioServerParameters(
            command=sys.executable,
            args=[str(_MCP_DIR / "browser_mcp.py")],
        ),
        timeout=_MCP_TIMEOUT,
    ),
)

axecore_toolset = McpToolset(
    connection_params=StdioConnectionParams(
        server_params=StdioServerParameters(
            command=sys.executable,
            args=[str(_MCP_DIR / "axecore_mcp.py")],
        ),
        timeout=_MCP_TIMEOUT,
    ),
)

screenshot_toolset = McpToolset(
    connection_params=StdioConnectionParams(
        server_params=StdioServerParameters(
            command=sys.executable,
            args=[str(_MCP_DIR / "screenshot_mcp.py")],
        ),
        timeout=_MCP_TIMEOUT,
    ),
)
