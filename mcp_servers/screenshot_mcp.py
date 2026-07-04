"""
mcp_servers/screenshot_mcp.py

Read-only screenshot MCP server built on Playwright.
Exposes a single tool: capture_screenshot.

Purpose:
  Captures visual evidence of accessibility findings so the report can
  include annotated screenshots. Used by the evaluator agent to visually
  verify high-severity findings before including them in the Top 5 section
  of the report.

Why a separate MCP server (not part of browser_mcp):
  The screenshot tool has a different concern from browser_mcp's tools:
    - browser_mcp tools extract data (HTML, styles, DOM tree)
    - screenshot_mcp captures rendered visual state for human review
  Separating them follows the O(N+M) MCP principle — future agents that
  only need screenshots don't inherit the full Playwright data-extraction
  surface, and vice versa.

  It also keeps the tool schema clean: capture_screenshot has meaningfully
  different parameters (viewport, clip region, element highlight) from
  fetch_page or get_computed_styles.

Security invariants (same as browser_mcp):
  - No form submissions, no DOM writes, no cookie persistence
  - No file downloads
  - Private network addresses blocked
  - Screenshots are returned as base64 PNG — not saved to disk by this server
    (the caller decides what to do with the data)

Transport: stdio (JSON-RPC 2.0 over stdin/stdout)
Run standalone: python mcp_servers/screenshot_mcp.py
"""

import asyncio
import base64
import json
import re
import os
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout

server = Server("screenshot-mcp")

PAGE_TIMEOUT_MS = int(os.getenv("BROWSER_MCP_TIMEOUT_MS", "30000"))

# Maximum screenshot dimension — prevents huge base64 payloads in the context window
MAX_VIEWPORT_WIDTH  = 1440
MAX_VIEWPORT_HEIGHT = 900
DEFAULT_WIDTH       = 1280
DEFAULT_HEIGHT      = 800


# ---------------------------------------------------------------------------
# Tool definition
# ---------------------------------------------------------------------------

@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="capture_screenshot",
            description=(
                "Captures a screenshot of a rendered web page and returns it as "
                "a base64-encoded PNG. Used to generate visual evidence of "
                "accessibility findings for audit reports. "
                "Optionally highlights a specific element by CSS selector. "
                "Read-only — no DOM modifications, no cookies, no downloads."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "The public URL to screenshot. Must be http:// or https://."
                    },
                    "viewport_width": {
                        "type": "integer",
                        "default": DEFAULT_WIDTH,
                        "description": f"Viewport width in pixels. Max {MAX_VIEWPORT_WIDTH}."
                    },
                    "viewport_height": {
                        "type": "integer",
                        "default": DEFAULT_HEIGHT,
                        "description": f"Viewport height in pixels. Max {MAX_VIEWPORT_HEIGHT}."
                    },
                    "highlight_selector": {
                        "type": "string",
                        "default": None,
                        "description": (
                            "Optional CSS selector. If provided, the matching element "
                            "is highlighted with a red outline before screenshotting. "
                            "Useful for annotating which element has a finding."
                        )
                    },
                    "full_page": {
                        "type": "boolean",
                        "default": False,
                        "description": (
                            "If true, captures the full page length (not just the "
                            "visible viewport). Use false for findings above the fold."
                        )
                    },
                    "clip_to_element": {
                        "type": "boolean",
                        "default": False,
                        "description": (
                            "If true AND highlight_selector is set, crops the "
                            "screenshot to the bounding box of the selected element "
                            "plus padding. Produces a focused finding screenshot."
                        )
                    }
                },
                "required": ["url"]
            }
        )
    ]


# ---------------------------------------------------------------------------
# Security helpers
# ---------------------------------------------------------------------------

def _validate_url(url: str) -> None:
    """Rejects non-HTTP(S) and private/local network URLs."""
    if not re.match(r"^https?://", url, re.IGNORECASE):
        raise ValueError(
            f"URL must start with http:// or https://. Got: {url!r}"
        )
    blocked = [
        r"localhost", r"127\.\d+\.\d+\.\d+", r"0\.0\.0\.0",
        r"10\.\d+\.\d+\.\d+", r"192\.168\.\d+\.\d+",
        r"172\.(1[6-9]|2\d|3[01])\.\d+\.\d+",
        r"::1", r"file://",
    ]
    for pattern in blocked:
        if re.search(pattern, url, re.IGNORECASE):
            raise ValueError(
                f"URL targets a private/local network address, "
                f"which is not permitted: {url!r}"
            )


def _validate_selector(selector: str | None) -> None:
    """Rejects selectors that look like JS injection attempts."""
    if not selector:
        return
    dangerous = [
        r"javascript:", r"<script", r"eval\s*\(",
        r"document\.", r"window\.", r"alert\s*\(",
    ]
    for pattern in dangerous:
        if re.search(pattern, selector, re.IGNORECASE):
            raise ValueError(
                f"Selector contains potentially dangerous content: {selector!r}"
            )


# ---------------------------------------------------------------------------
# Tool implementation
# ---------------------------------------------------------------------------

async def _tool_capture_screenshot(arguments: dict) -> list[TextContent]:
    url               = arguments["url"]
    viewport_width    = min(int(arguments.get("viewport_width", DEFAULT_WIDTH)),
                            MAX_VIEWPORT_WIDTH)
    viewport_height   = min(int(arguments.get("viewport_height", DEFAULT_HEIGHT)),
                            MAX_VIEWPORT_HEIGHT)
    highlight_selector = arguments.get("highlight_selector")
    full_page         = bool(arguments.get("full_page", False))
    clip_to_element   = bool(arguments.get("clip_to_element", False))

    _validate_url(url)
    _validate_selector(highlight_selector)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={"width": viewport_width, "height": viewport_height},
            accept_downloads=False,
            permissions=[],
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
            locale="en-AU",
        )
        # Stealth init — same script as browser_mcp._make_sandboxed_page
        await context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            Object.defineProperty(navigator, 'plugins', {
                get: () => Object.assign(
                    [
                        {name:'Chrome PDF Plugin', filename:'internal-pdf-viewer', description:''},
                        {name:'Chrome PDF Viewer', filename:'mhjfbmdgcfjbbpaeojofohoefgiehjai', description:''},
                        {name:'Native Client', filename:'internal-nacl-plugin', description:''},
                    ],
                    {item: function(i){return this[i];}, namedItem: function(n){return null;}, refresh: function(){}}
                )
            });
            if (!window.chrome) {
                window.chrome = {runtime: {}, loadTimes: function(){}, csi: function(){}, app: {}};
            }
            if (navigator.permissions && navigator.permissions.query) {
                const _origQuery = navigator.permissions.query.bind(navigator.permissions);
                navigator.permissions.query = (params) =>
                    params && params.name === 'notifications'
                        ? Promise.resolve({state: 'default', onchange: null})
                        : _origQuery(params);
            }
        """)

        # Route: block media and websockets (not needed for screenshots)
        await context.route("**/*", lambda route: (
            route.abort()
            if route.request.resource_type in ("media", "websocket", "eventsource")
            else route.continue_()
        ))

        page = await context.new_page()

        try:
            await page.goto(url, wait_until="networkidle",
                            timeout=PAGE_TIMEOUT_MS)
        except PlaywrightTimeout:
            await browser.close()
            return [TextContent(type="text", text=json.dumps({
                "error": "timeout",
                "message": f"Page did not load within {PAGE_TIMEOUT_MS}ms",
                "url": url,
            }))]

        # Highlight the element if requested
        # This is a read-only CSS-only highlight — no DOM structure changes
        clip = None
        element_info = None

        if highlight_selector:
            try:
                # Inject a read-only style overlay (no DOM mutations)
                await page.evaluate(
                    """(selector) => {
                        const els = document.querySelectorAll(selector);
                        els.forEach(el => {
                            el.style.outline = '3px solid #ff0000';
                            el.style.outlineOffset = '2px';
                        });
                    }""",
                    highlight_selector,
                )

                # Get bounding box for clip_to_element
                if clip_to_element:
                    el = await page.query_selector(highlight_selector)
                    if el:
                        box = await el.bounding_box()
                        if box:
                            padding = 20
                            clip = {
                                "x":      max(0, box["x"] - padding),
                                "y":      max(0, box["y"] - padding),
                                "width":  box["width"] + padding * 2,
                                "height": box["height"] + padding * 2,
                            }
                            element_info = {
                                "selector": highlight_selector,
                                "bounding_box": box,
                            }

            except Exception as e:
                # Highlight failure is non-fatal — proceed with plain screenshot
                pass

        # Capture screenshot
        screenshot_kwargs: dict[str, Any] = {
            "type": "png",
            "full_page": full_page,
        }
        if clip:
            screenshot_kwargs["clip"] = clip

        screenshot_bytes = await page.screenshot(**screenshot_kwargs)
        await browser.close()

    # Return as base64 — the caller renders or saves it
    b64 = base64.b64encode(screenshot_bytes).decode("utf-8")

    result = {
        "url":             url,
        "screenshot_b64":  b64,
        "mime_type":       "image/png",
        "width_px":        viewport_width,
        "height_px":       viewport_height,
        "full_page":       full_page,
        "highlighted":     highlight_selector is not None,
        "clipped":         clip is not None,
        "element_info":    element_info,
        "size_bytes":      len(screenshot_bytes),
    }

    return [TextContent(type="text", text=json.dumps(result))]


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    if name != "capture_screenshot":
        return [TextContent(type="text", text=json.dumps({
            "error": "unknown_tool",
            "message": f"Tool '{name}' is not registered on this server.",
            "available_tools": ["capture_screenshot"],
        }))]

    try:
        return await _tool_capture_screenshot(arguments)
    except ValueError as e:
        return [TextContent(type="text", text=json.dumps({
            "error": "validation_error",
            "message": str(e),
        }))]
    except Exception as e:
        return [TextContent(type="text", text=json.dumps({
            "error": "tool_error",
            "tool": name,
            "message": str(e),
        }))]


# ---------------------------------------------------------------------------
# Handshake tests (inline — run via pytest tests/test_mcp_servers.py)
# ---------------------------------------------------------------------------

"""
To add screenshot MCP tests, extend tests/test_mcp_servers.py with:

class TestScreenshotMCPHandshake:
    @pytest.mark.asyncio
    async def test_connection_and_initialize(self):
        async with await _connect("screenshot") as (read, write):
            async with ClientSession(read, write) as session:
                result = await session.initialize()
                assert result is not None

    @pytest.mark.asyncio
    async def test_list_tools_returns_capture_screenshot(self):
        async with await _connect("screenshot") as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools_result = await session.list_tools()
                tool_names = {t.name for t in tools_result.tools}
                assert "capture_screenshot" in tool_names

    @pytest.mark.asyncio
    async def test_rejects_localhost_url(self):
        async with await _connect("screenshot") as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(
                    "capture_screenshot", {"url": "http://localhost:8080"}
                )
                response = json.loads(result.content[0].text)
                assert "error" in response

    @pytest.mark.asyncio
    async def test_returns_base64_png(self):
        async with await _connect("screenshot") as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(
                    "capture_screenshot",
                    {"url": "https://example.com", "full_page": False}
                )
                response = json.loads(result.content[0].text)
                assert "error" not in response
                assert "screenshot_b64" in response
                assert response["mime_type"] == "image/png"
                # Verify it's valid base64
                import base64
                decoded = base64.b64decode(response["screenshot_b64"])
                assert decoded[:8] == b'\\x89PNG\\r\\n\\x1a\\n'  # PNG magic bytes

Add "screenshot": Path("mcp_servers/screenshot_mcp.py") to the SERVERS dict.
"""


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def main():
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
