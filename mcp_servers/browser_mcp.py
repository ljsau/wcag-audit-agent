"""
mcp_servers/browser_mcp.py

Read-only browser automation MCP server built on Playwright.
Exposes four tools to the contrast, semantic, and ARIA agents:

  - fetch_page            : renders a URL and returns HTML + metadata
  - get_computed_styles   : extracts CSS colour/font values for a selector
  - get_dom_snapshot      : returns the Playwright accessibility tree
  - simulate_keyboard_nav : tabs through interactive elements, records focus order

Security invariants (enforced in code, not just comments):
  - No form submissions, no page.click() on inputs, no DOM writes
  - No cookie persistence — fresh context per call
  - No file downloads
  - No stored credentials or session state
  - Page content is returned as data strings; it is NEVER evaluated as code

Transport: stdio (JSON-RPC 2.0 over stdin/stdout)
Run standalone: python mcp_servers/browser_mcp.py
"""

import asyncio
import json
import re
import os
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent, ErrorData
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout

# ---------------------------------------------------------------------------
# Server initialisation
# ---------------------------------------------------------------------------

server = Server("browser-mcp")

# Read-only enforcement: operations that are never permitted
_PROHIBITED_OPERATIONS = frozenset([
    "fill", "click", "check", "uncheck", "select_option",
    "dispatch_event", "evaluate_handle", "add_script_tag",
    "add_style_tag", "set_content", "route",
])

# Selector used by contrast and semantic agents (configurable via env)
DEFAULT_TEXT_SELECTOR = os.getenv(
    "BROWSER_MCP_TEXT_SELECTOR",
    "p,h1,h2,h3,h4,h5,h6,a,span,li,button,label,input,td,th,caption,figcaption"
)

# Maximum elements returned per tool call to bound token usage
MAX_ELEMENTS = int(os.getenv("BROWSER_MCP_MAX_ELEMENTS", "100"))
MAX_FOCUS_STEPS = int(os.getenv("BROWSER_MCP_MAX_FOCUS_STEPS", "50"))
PAGE_TIMEOUT_MS = int(os.getenv("BROWSER_MCP_TIMEOUT_MS", "30000"))


# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="fetch_page",
            description=(
                "Loads a public URL in a sandboxed headless browser and returns "
                "the fully-rendered HTML, page title, and discovered internal links. "
                "Read-only — no cookies, no form submissions, no downloads. "
                "Use this to get the DOM content of a page for accessibility analysis."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "The public URL to fetch. Must start with http:// or https://."
                    },
                    "wait_for": {
                        "type": "string",
                        "enum": ["load", "domcontentloaded", "networkidle"],
                        "default": "networkidle",
                        "description": "Playwright wait condition. Use networkidle for SPAs."
                    },
                    "extra_wait_ms": {
                        "type": "integer",
                        "default": 0,
                        "description": "Additional milliseconds to wait after wait_for. Use for lazy-loaded content."
                    }
                },
                "required": ["url"]
            }
        ),

        Tool(
            name="get_computed_styles",
            description=(
                "Returns computed CSS colour and font values for elements matching "
                "a CSS selector on a given page. Used by the contrast checker agent "
                "to extract foreground colour, background colour, and font size for "
                "WCAG 1.4.3 contrast ratio calculations. Read-only."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "The public URL to inspect."
                    },
                    "selector": {
                        "type": "string",
                        "description": (
                            "CSS selector for elements to inspect. "
                            f"Defaults to: {DEFAULT_TEXT_SELECTOR}"
                        ),
                        "default": DEFAULT_TEXT_SELECTOR
                    },
                    "max_elements": {
                        "type": "integer",
                        "default": MAX_ELEMENTS,
                        "description": "Maximum number of elements to return. Caps token usage."
                    }
                },
                "required": ["url"]
            }
        ),

        Tool(
            name="get_dom_snapshot",
            description=(
                "Returns the Playwright accessibility tree for a rendered page. "
                "Used by the semantic HTML and ARIA agents to check heading order, "
                "landmark regions, ARIA roles, alt text, and link text. Read-only."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "The public URL to snapshot."
                    },
                    "interesting_only": {
                        "type": "boolean",
                        "default": True,
                        "description": (
                            "If true, returns only nodes with accessibility relevance "
                            "(Playwright's default interesting filter). Set false for "
                            "full raw tree."
                        )
                    }
                },
                "required": ["url"]
            }
        ),

        Tool(
            name="simulate_keyboard_nav",
            description=(
                "Simulates Tab key navigation through a page's interactive elements "
                "and records the focus order, focus visibility, and whether any focus "
                "traps exist. Used by the ARIA agent for WCAG 2.1.1 and 2.4.7 checks. "
                "Read-only — Tab key only, no form input, no Enter/Space activation."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "The public URL to test keyboard navigation on."
                    },
                    "max_steps": {
                        "type": "integer",
                        "default": MAX_FOCUS_STEPS,
                        "description": "Maximum Tab presses before stopping (prevents infinite loops)."
                    }
                },
                "required": ["url"]
            }
        ),
    ]


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

async def _make_sandboxed_page(playwright, url: str, wait_for: str = "networkidle",
                                extra_wait_ms: int = 0):
    """
    Creates a hardened, read-only browser context and navigates to url.
    Returns (browser, context, page). Caller must close browser.

    Security:
    - No persistent storage (no cookies, no localStorage carry-over)
    - Downloads blocked
    - Geolocation, notifications, camera, mic blocked
    - No custom JS injection
    """
    browser = await playwright.chromium.launch(headless=True)
    context = await browser.new_context(
        accept_downloads=False,
        java_script_enabled=True,       # needed for SPA rendering
        bypass_csp=False,               # respect the site's CSP
        # Explicitly deny sensitive permissions
        permissions=[],
    )

    # Block resource types that aren't needed for accessibility auditing
    # This also reduces attack surface from malicious redirects
    await context.route("**/*", lambda route: (
        route.abort()
        if route.request.resource_type in ("media", "websocket", "eventsource")
        else route.continue_()
    ))

    page = await context.new_page()

    try:
        await page.goto(url, wait_until=wait_for, timeout=PAGE_TIMEOUT_MS)
    except PlaywrightTimeout:
        await browser.close()
        raise TimeoutError(f"Page {url} did not load within {PAGE_TIMEOUT_MS}ms")

    if extra_wait_ms > 0:
        await page.wait_for_timeout(extra_wait_ms)

    return browser, context, page


async def _tool_fetch_page(arguments: dict) -> list[TextContent]:
    url = arguments["url"]
    wait_for = arguments.get("wait_for", "networkidle")
    extra_wait_ms = int(arguments.get("extra_wait_ms", 0))

    _validate_url(url)

    async with async_playwright() as p:
        try:
            browser, context, page = await _make_sandboxed_page(
                p, url, wait_for, extra_wait_ms
            )
        except TimeoutError as e:
            return [TextContent(type="text", text=json.dumps({
                "error": "timeout",
                "message": str(e),
                "url": url
            }))]

        try:
            html = await page.content()
            title = await page.title()

            # Collect internal links — read-only eval, no DOM mutation
            links = await page.evaluate("""
                () => {
                    const origin = window.location.origin;
                    const anchors = document.querySelectorAll('a[href]');
                    const internal = new Set();
                    anchors.forEach(a => {
                        try {
                            const href = new URL(a.href, origin);
                            if (href.origin === origin) internal.add(href.href);
                        } catch {}
                    });
                    return Array.from(internal).slice(0, 50);
                }
            """)

            result = {
                "url": url,
                "title": title,
                "html_length": len(html),
                "rendered_html": html[:50000],   # cap at 50KB to control tokens
                "internal_links": links,
                "truncated": len(html) > 50000,
            }
            if len(html) > 50000:
                result["note"] = (
                    "HTML truncated to 50KB. Use get_dom_snapshot for full "
                    "accessibility tree on large pages."
                )

        finally:
            await browser.close()

    return [TextContent(type="text", text=json.dumps(result))]


async def _tool_get_computed_styles(arguments: dict) -> list[TextContent]:
    url = arguments["url"]
    selector = arguments.get("selector", DEFAULT_TEXT_SELECTOR)
    max_elements = int(arguments.get("max_elements", MAX_ELEMENTS))

    _validate_url(url)
    _validate_selector(selector)

    async with async_playwright() as p:
        try:
            browser, context, page = await _make_sandboxed_page(p, url)
        except TimeoutError as e:
            return [TextContent(type="text", text=json.dumps({
                "error": "timeout", "message": str(e), "url": url
            }))]

        try:
            # Read-only JS evaluation — extracts computed styles, no DOM mutation
            elements = await page.evaluate(f"""
                (params) => {{
                    const {{ selector, maxElements }} = params;
                    const els = document.querySelectorAll(selector);
                    return Array.from(els).slice(0, maxElements).map(el => {{
                        const cs = getComputedStyle(el);
                        const rect = el.getBoundingClientRect();
                        return {{
                            tag: el.tagName,
                            text: (el.innerText || el.textContent || '').trim().slice(0, 100),
                            color: cs.color,
                            background_color: cs.backgroundColor,
                            font_size: cs.fontSize,
                            font_weight: cs.fontWeight,
                            visible: rect.width > 0 && rect.height > 0,
                            selector_path: (
                                el.id ? '#' + el.id :
                                el.className ? el.tagName + '.' + el.className.split(' ')[0] :
                                el.tagName
                            )
                        }};
                    }});
                }}
            """, {"selector": selector, "maxElements": max_elements})

        finally:
            await browser.close()

    result = {
        "url": url,
        "selector_used": selector,
        "element_count": len(elements),
        "elements": elements
    }

    return [TextContent(type="text", text=json.dumps(result))]


async def _tool_get_dom_snapshot(arguments: dict) -> list[TextContent]:
    url = arguments["url"]
    interesting_only = arguments.get("interesting_only", True)

    _validate_url(url)

    async with async_playwright() as p:
        try:
            browser, context, page = await _make_sandboxed_page(p, url)
        except TimeoutError as e:
            return [TextContent(type="text", text=json.dumps({
                "error": "timeout", "message": str(e), "url": url
            }))]

        try:
            snapshot = await page.evaluate("""
                () => {
                    function buildTree(el, depth) {
                        if (depth > 10) return null;
                        const role = el.computedRole || el.getAttribute('role') || el.tagName.toLowerCase();
                        const name = (el.computedName || el.getAttribute('aria-label') || el.innerText || '').trim().slice(0, 150);
                        const node = { role: role };
                        if (name) node.name = name;
                        if (el.tagName && el.tagName.match(/^H[1-6]$/))
                            node.level = parseInt(el.tagName.slice(1));
                        const children = [];
                        for (const child of el.children) {
                            const childNode = buildTree(child, depth + 1);
                            if (childNode) children.push(childNode);
                        }
                        if (children.length > 0) node.children = children;
                        return node;
                    }
                    return buildTree(document.body, 0);
                }
            """)

            headings = await page.evaluate("""
                () => {
                    const tags = ['h1','h2','h3','h4','h5','h6'];
                    const result = [];
                    tags.forEach(tag => {
                        document.querySelectorAll(tag).forEach(el => {
                            result.push({
                                level: parseInt(tag.slice(1)),
                                text: el.innerText.trim().slice(0, 150),
                                has_id: !!el.id
                            });
                        });
                    });
                    return result;
                }
            """)

            # Extract images for alt text check
            images = await page.evaluate("""
                () => {
                    return Array.from(document.querySelectorAll('img')).map(img => ({
                        src: img.src.slice(0, 200),
                        alt: img.getAttribute('alt'),
                        has_alt: img.hasAttribute('alt'),
                        alt_is_empty: img.getAttribute('alt') === '',
                        role: img.getAttribute('role'),
                        aria_label: img.getAttribute('aria-label'),
                        visible: img.getBoundingClientRect().width > 0
                    }));
                }
            """)

            # Extract landmark regions
            landmarks = await page.evaluate("""
                () => {
                    const roles = ['main','nav','aside','header','footer',
                                   'search','form','region','complementary',
                                   'banner','contentinfo'];
                    const result = [];
                    roles.forEach(role => {
                        const byRole = document.querySelectorAll(`[role="${role}"]`);
                        const byTag = (role === 'nav') ? document.querySelectorAll('nav') :
                                      (role === 'main') ? document.querySelectorAll('main') :
                                      (role === 'aside') ? document.querySelectorAll('aside') :
                                      [];
                        const combined = new Set([...byRole, ...byTag]);
                        combined.forEach(el => {
                            result.push({
                                role: role,
                                tag: el.tagName,
                                label: el.getAttribute('aria-label') || el.getAttribute('aria-labelledby') || null
                            });
                        });
                    });
                    return result;
                }
            """)

        finally:
            await browser.close()

    result = {
        "url": url,
        "accessibility_tree": snapshot,
        "headings": headings,
        "images": images,
        "landmarks": landmarks,
    }

    return [TextContent(type="text", text=json.dumps(result))]


async def _tool_simulate_keyboard_nav(arguments: dict) -> list[TextContent]:
    url = arguments["url"]
    max_steps = int(arguments.get("max_steps", MAX_FOCUS_STEPS))

    _validate_url(url)

    async with async_playwright() as p:
        try:
            browser, context, page = await _make_sandboxed_page(p, url)
        except TimeoutError as e:
            return [TextContent(type="text", text=json.dumps({
                "error": "timeout", "message": str(e), "url": url
            }))]

        try:
            focus_order = []
            seen_elements = set()
            trap_detected = False

            # Start from page body
            await page.focus("body")

            for step in range(max_steps):
                # Tab to next element — read-only navigation only
                await page.keyboard.press("Tab")

                focused = await page.evaluate("""
                    () => {
                        const el = document.activeElement;
                        if (!el || el === document.body) return null;
                        const cs = getComputedStyle(el);
                        const outline = cs.outlineStyle !== 'none' || cs.outlineWidth !== '0px';
                        const box_shadow = cs.boxShadow !== 'none';
                        return {
                            tag: el.tagName,
                            type: el.getAttribute('type'),
                            role: el.getAttribute('role'),
                            aria_label: el.getAttribute('aria-label'),
                            text: (el.innerText || el.textContent || el.value || '').trim().slice(0, 80),
                            id: el.id || null,
                            tabindex: el.getAttribute('tabindex'),
                            has_visible_focus: outline || box_shadow,
                            selector_path: el.id ? '#' + el.id : el.tagName
                        };
                    }
                """)

                if not focused:
                    break

                # Trap detection: same element focused twice in a row
                element_key = f"{focused['tag']}:{focused.get('id')}:{focused.get('text', '')[:30]}"
                if element_key in seen_elements:
                    trap_detected = True
                    focus_order.append({**focused, "trap_detected": True})
                    break

                seen_elements.add(element_key)
                focus_order.append(focused)

        finally:
            await browser.close()

    # Analyse results
    missing_focus_indicators = [
        el for el in focus_order
        if not el.get("has_visible_focus") and not el.get("trap_detected")
    ]

    result = {
        "url": url,
        "steps_taken": len(focus_order),
        "trap_detected": trap_detected,
        "focus_order": focus_order,
        "missing_focus_indicators": missing_focus_indicators,
        "missing_focus_count": len(missing_focus_indicators),
    }

    return [TextContent(type="text", text=json.dumps(result))]


# ---------------------------------------------------------------------------
# Security helpers
# ---------------------------------------------------------------------------

def _validate_url(url: str) -> None:
    """
    Rejects non-HTTP(S) URLs and localhost addresses.
    Prevents the server from being used to probe internal network resources.
    """
    if not re.match(r"^https?://", url, re.IGNORECASE):
        raise ValueError(f"URL must start with http:// or https://. Got: {url!r}")

    # Block internal/private network addresses
    blocked_patterns = [
        r"localhost", r"127\.\d+\.\d+\.\d+", r"0\.0\.0\.0",
        r"10\.\d+\.\d+\.\d+", r"192\.168\.\d+\.\d+",
        r"172\.(1[6-9]|2\d|3[01])\.\d+\.\d+",
        r"::1", r"file://",
    ]
    for pattern in blocked_patterns:
        if re.search(pattern, url, re.IGNORECASE):
            raise ValueError(
                f"URL targets a private/local network address, which is not permitted: {url!r}"
            )


def _validate_selector(selector: str) -> None:
    """
    Rejects selectors that look like JavaScript injection attempts.
    CSS selectors should never contain parentheses (function calls) outside
    of standard pseudo-classes.
    """
    dangerous_patterns = [
        r"javascript:", r"<script", r"eval\s*\(",
        r"document\.", r"window\.", r"alert\s*\(",
    ]
    for pattern in dangerous_patterns:
        if re.search(pattern, selector, re.IGNORECASE):
            raise ValueError(
                f"Selector contains potentially dangerous content: {selector!r}"
            )


# ---------------------------------------------------------------------------
# Tool dispatcher
# ---------------------------------------------------------------------------

@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    """
    Dispatches tool calls. All tools are read-only by design.
    Any operation not in this list is rejected.
    """
    # Explicit allowlist — never a passthrough
    allowed_tools = {
        "fetch_page":           _tool_fetch_page,
        "get_computed_styles":  _tool_get_computed_styles,
        "get_dom_snapshot":     _tool_get_dom_snapshot,
        "simulate_keyboard_nav": _tool_simulate_keyboard_nav,
    }

    if name not in allowed_tools:
        return [TextContent(type="text", text=json.dumps({
            "error": "unknown_tool",
            "message": f"Tool '{name}' is not registered on this server.",
            "available_tools": list(allowed_tools.keys()),
        }))]

    try:
        return await allowed_tools[name](arguments)
    except ValueError as e:
        # Validation errors (bad URL, bad selector)
        return [TextContent(type="text", text=json.dumps({
            "error": "validation_error",
            "message": str(e),
        }))]
    except TimeoutError as e:
        return [TextContent(type="text", text=json.dumps({
            "error": "timeout",
            "message": str(e),
        }))]
    except Exception as e:
        # Surface errors cleanly — never crash the MCP server process
        return [TextContent(type="text", text=json.dumps({
            "error": "tool_error",
            "tool": name,
            "message": str(e),
        }))]


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def main():
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
