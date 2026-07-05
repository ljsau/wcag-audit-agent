"""
agents/mcp_tools.py

Shared MCP toolset definitions for all agents.
Each toolset connects to one MCP server via stdio and exposes its tools
to any agent that includes it in its tools=[] list.

ADK 2.x requires MCP tools to be passed as McpToolset objects —
plain function references don't work for tools hosted in MCP servers.
"""

import os
import sys
from pathlib import Path
from mcp import StdioServerParameters
from google.adk.tools import McpToolset
from google.adk.tools.mcp_tool.mcp_toolset import StdioConnectionParams

_MCP_DIR = Path(__file__).parent.parent / "mcp_servers"
# Axe-core scans of heavy real-world pages can take minutes (page must reach
# networkidle, then axe injects + runs). 300s per the observed need; the
# page-load ceiling (BROWSER_MCP_TIMEOUT_MS, default raised below) sits under
# this so axe has room to run within the window.
_MCP_TIMEOUT = 300.0


def child_env() -> dict:
    """
    Full parent environment for MCP subprocesses.

    The MCP stdio client forwards only a safe allowlist to spawned servers by
    default, which drops custom vars like PLAYWRIGHT_BROWSERS_PATH. In the
    deployed Agent Engine runtime the build installs Chromium into site-packages
    (PLAYWRIGHT_BROWSERS_PATH=0); without forwarding that var the browser
    subprocess falls back to $HOME/.cache and can't find Chromium. Locally the
    var is unset, so this is a no-op there.
    """
    return {**os.environ}


browser_toolset = McpToolset(
    connection_params=StdioConnectionParams(
        server_params=StdioServerParameters(
            command=sys.executable,
            args=[str(_MCP_DIR / "browser_mcp.py")],
            env=child_env(),
        ),
        timeout=_MCP_TIMEOUT,
    ),
)

axecore_toolset = McpToolset(
    connection_params=StdioConnectionParams(
        server_params=StdioServerParameters(
            command=sys.executable,
            args=[str(_MCP_DIR / "axecore_mcp.py")],
            env=child_env(),
        ),
        timeout=_MCP_TIMEOUT,
    ),
)

screenshot_toolset = McpToolset(
    connection_params=StdioConnectionParams(
        server_params=StdioServerParameters(
            command=sys.executable,
            args=[str(_MCP_DIR / "screenshot_mcp.py")],
            env=child_env(),
        ),
        timeout=_MCP_TIMEOUT,
    ),
)
