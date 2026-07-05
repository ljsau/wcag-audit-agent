"""
mcp_servers/axecore_mcp.py

MCP server wrapping axe-playwright-python for automated WCAG rule-based scanning.
axe-core is Deque's open-source accessibility engine — the industry standard,
used by the US government, GOV.UK, and most major accessibility tooling.

Exposes one tool:
  - run_axe_scan : runs axe-core against a URL and returns structured violations

Why axe-core as a separate MCP server rather than calling it directly from agents?
  - Follows MCP's O(N+M) principle: any future agent can consume this server
  - axe-core results are deterministic; keeping them in a separate tool layer
    preserves the contrast agent's "no LLM in the calculation" invariant
  - The MCP boundary makes it easy to swap axe-core for a different engine later

Transport: stdio
Run standalone: python mcp_servers/axecore_mcp.py
"""

import asyncio
import json
import re
import os

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout

# axe-playwright-python wraps axe-core via Playwright
from axe_playwright_python.async_playwright import Axe

server = Server("axecore-mcp")

PAGE_TIMEOUT_MS = int(os.getenv("BROWSER_MCP_TIMEOUT_MS", "30000"))

# WCAG 2.1 AA ruleset — explicitly scoped, not "run everything"
# Full list: https://github.com/dequelabs/axe-core/blob/develop/doc/rule-descriptions.md
WCAG_AA_TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "best-practice"]


# ---------------------------------------------------------------------------
# Tool definition
# ---------------------------------------------------------------------------

@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="run_axe_scan",
            description=(
                "Runs the axe-core accessibility engine against a rendered page "
                "and returns structured WCAG 2.1 AA violations. Each violation "
                "includes the WCAG criterion, affected elements (CSS selectors), "
                "impact level, and fix guidance. Read-only — no DOM modifications."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "The public URL to scan. Must be http:// or https://."
                    },
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "default": WCAG_AA_TAGS,
                        "description": (
                            "axe-core rule tags to run. Defaults to WCAG 2.1 AA + "
                            "best-practice. Other valid values: wcag2aaa, wcag22aa."
                        )
                    },
                    "context": {
                        "type": "string",
                        "default": "document",
                        "description": (
                            "CSS selector to scope the scan to. Defaults to the "
                            "full document."
                        )
                    }
                },
                "required": ["url"]
            }
        )
    ]


# ---------------------------------------------------------------------------
# Tool implementation
# ---------------------------------------------------------------------------

def _validate_url(url: str) -> None:
    if not re.match(r"^https?://", url, re.IGNORECASE):
        raise ValueError(f"URL must start with http:// or https://. Got: {url!r}")
    blocked = [
        r"localhost", r"127\.", r"0\.0\.0\.0",
        r"10\.\d+\.\d+\.\d+", r"192\.168\.", r"file://",
    ]
    for pattern in blocked:
        if re.search(pattern, url, re.IGNORECASE):
            raise ValueError(f"Private network URL not permitted: {url!r}")


def _normalise_violation(v: dict) -> dict:
    """
    Flattens an axe-core violation into the finding schema defined in
    specs/audit_agent_spec.md. Maps axe impact levels to WCAG severity.
    """
    impact_to_severity = {
        "critical": "critical",
        "serious":  "serious",
        "moderate": "moderate",
        "minor":    "minor",
    }

    # Extract WCAG criterion from tags (e.g. "wcag143" → "1.4.3")
    wcag_criterion = None
    for tag in v.get("tags", []):
        match = re.match(r"wcag(\d)(\d+)(\w*)", tag)
        if match:
            digits = match.group(2)
            # Convert "143" → "1.4.3"
            if len(digits) == 3:
                wcag_criterion = f"{digits[0]}.{digits[1]}.{digits[2]}"
            elif len(digits) == 2:
                wcag_criterion = f"{match.group(1)}.{digits[0]}.{digits[1]}"
            break

    # Collect affected element selectors (first 10 to bound output size)
    affected_nodes = []
    for node in v.get("nodes", [])[:10]:
        selectors = node.get("target", [])
        html_snippet = node.get("html", "")[:200]
        failure_summary = node.get("failureSummary", "")
        affected_nodes.append({
            "selector": selectors[0] if selectors else "unknown",
            "html_snippet": html_snippet,
            "failure_summary": failure_summary,
        })

    return {
        "id": v.get("id"),
        "description": v.get("description"),
        "help": v.get("help"),
        "help_url": v.get("helpUrl"),
        "wcag_criterion": wcag_criterion,
        "tags": v.get("tags", []),
        "impact": v.get("impact"),
        "severity_raw": impact_to_severity.get(v.get("impact", "minor"), "minor"),
        "affected_nodes": affected_nodes,
        "affected_node_count": len(v.get("nodes", [])),
    }


async def _tool_run_axe_scan(arguments: dict) -> list[TextContent]:
    url = arguments["url"]
    tags = arguments.get("tags", WCAG_AA_TAGS)
    context_selector = arguments.get("context", "document")

    _validate_url(url)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        browser_context = await browser.new_context(
            accept_downloads=False,
            permissions=[],
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 800},
            locale="en-AU",
        )
        # Stealth init — same script as browser_mcp._make_sandboxed_page.
        # navigator.webdriver alone isn't sufficient; Cloudflare-style WAFs also
        # check plugins count, window.chrome presence, and permissions behaviour.
        await browser_context.add_init_script("""
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
        page = await browser_context.new_page()

        try:
            try:
                # wait_until="load" (not "networkidle"): axe needs the DOM,
                # stylesheets, and images loaded (for contrast/alt checks), but
                # "networkidle" can hang for minutes on pages with continuous
                # background requests (analytics, trackers), timing out before
                # axe ever runs. "load" fires as soon as page resources finish.
                await page.goto(url, wait_until="load",
                                timeout=PAGE_TIMEOUT_MS)
            except PlaywrightTimeout:
                await browser.close()
                return [TextContent(type="text", text=json.dumps({
                    "error": "timeout",
                    "message": f"Page did not load within {PAGE_TIMEOUT_MS}ms",
                    "url": url,
                }))]

            axe = Axe()
            axe_results = await axe.run(
                page,
                options={
                    "runOnly": {"type": "tag", "values": tags},
                    **({"context": context_selector}
                       if context_selector != "document" else {})
                }
            )
            results = axe_results.response if hasattr(axe_results, "response") else axe_results

        finally:
            await browser.close()

    violations = [_normalise_violation(v) for v in results.get("violations", [])]
    passes    = len(results.get("passes", []))
    incomplete = len(results.get("incomplete", []))
    inapplicable = len(results.get("inapplicable", []))

    output = {
        "url": url,
        "tags_run": tags,
        "violation_count": len(violations),
        "passes_count": passes,
        "incomplete_count": incomplete,
        "inapplicable_count": inapplicable,
        "violations": violations,
        "axe_version": results.get("testEngine", {}).get("version", "unknown"),
        "timestamp": results.get("timestamp", ""),
    }

    return [TextContent(type="text", text=json.dumps(output))]


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    if name == "run_axe_scan":
        try:
            return await _tool_run_axe_scan(arguments)
        except ValueError as e:
            return [TextContent(type="text", text=json.dumps({
                "error": "validation_error", "message": str(e)
            }))]
        except Exception as e:
            return [TextContent(type="text", text=json.dumps({
                "error": "tool_error", "tool": name, "message": str(e)
            }))]
    return [TextContent(type="text", text=json.dumps({
        "error": "unknown_tool",
        "message": f"Tool '{name}' not found.",
        "available_tools": ["run_axe_scan"]
    }))]


async def main():
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
