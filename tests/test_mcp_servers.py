"""
tests/test_mcp_servers.py

Handshake and schema validation tests for all three MCP servers.
Run these BEFORE building any agents — if the transport pipes are broken,
no amount of agent prompt tweaking will fix them.

This is the "debug the pipes, not the system prompt" principle from Day 2
applied as a test suite.

Usage:
    pytest tests/test_mcp_servers.py -v
    pytest tests/test_mcp_servers.py -v -k "browser"
    pytest tests/test_mcp_servers.py -v -k "axecore"
    pytest tests/test_mcp_servers.py -v -k "screenshot"

Requires all three MCP servers to be accessible at their script paths.
Requires: playwright install chromium (run once after pip install playwright)
"""

import asyncio
import json
import pytest
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SERVERS = {
    "browser":    Path("mcp_servers/browser_mcp.py"),
    "axecore":    Path("mcp_servers/axecore_mcp.py"),
    "screenshot": Path("mcp_servers/screenshot_mcp.py"),
}

# A stable, accessible public URL for live tool tests
TEST_URL = "https://example.com"

# A URL known to have contrast issues (use your own low-contrast test page
# or the W3C's intentionally bad accessibility demo)
LOW_CONTRAST_URL = "https://www.w3.org/WAI/demos/bad/after/home.html"


async def _connect(server_key: str):
    """Opens a stdio connection to an MCP server subprocess."""
    script = SERVERS[server_key]
    if not script.exists():
        pytest.skip(f"Server script not found: {script}")

    params = StdioServerParameters(
        command=sys.executable,
        args=[str(script)],
    )
    return stdio_client(params)


# ---------------------------------------------------------------------------
# Handshake tests — verify JSON-RPC transport is working
# ---------------------------------------------------------------------------

class TestBrowserMCPHandshake:

    @pytest.mark.asyncio
    async def test_connection_and_initialize(self):
        """Server must respond to the MCP initialization handshake."""
        async with await _connect("browser") as (read, write):
            async with ClientSession(read, write) as session:
                result = await session.initialize()
                assert result is not None, "initialize() returned None"

    @pytest.mark.asyncio
    async def test_list_tools_returns_four_tools(self):
        """Server must advertise exactly the four expected tools."""
        async with await _connect("browser") as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools_result = await session.list_tools()
                tool_names = {t.name for t in tools_result.tools}

                expected = {
                    "fetch_page",
                    "get_computed_styles",
                    "get_dom_snapshot",
                    "simulate_keyboard_nav",
                }
                assert tool_names == expected, (
                    f"Expected tools {expected}, got {tool_names}"
                )

    @pytest.mark.asyncio
    async def test_tool_schemas_have_required_url_field(self):
        """Every tool must declare 'url' as a required input."""
        async with await _connect("browser") as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools_result = await session.list_tools()
                for tool in tools_result.tools:
                    required = tool.inputSchema.get("required", [])
                    assert "url" in required, (
                        f"Tool '{tool.name}' is missing 'url' in required fields"
                    )


# ---------------------------------------------------------------------------
# Security tests — validate read-only constraints work as expected
# ---------------------------------------------------------------------------

class TestBrowserMCPSecurity:

    @pytest.mark.asyncio
    async def test_rejects_localhost_url(self):
        """Server must reject requests targeting localhost."""
        async with await _connect("browser") as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(
                    "fetch_page", {"url": "http://localhost:8080"}
                )
                response = json.loads(result.content[0].text)
                assert "error" in response, (
                    "Server should have rejected localhost URL"
                )
                assert "private" in response["message"].lower() or \
                       "not permitted" in response["message"].lower()

    @pytest.mark.asyncio
    async def test_rejects_private_network_url(self):
        """Server must reject requests targeting private IP ranges."""
        async with await _connect("browser") as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(
                    "fetch_page", {"url": "http://192.168.1.1"}
                )
                response = json.loads(result.content[0].text)
                assert "error" in response

    @pytest.mark.asyncio
    async def test_rejects_non_http_url(self):
        """Server must reject file:// and other non-HTTP schemes."""
        async with await _connect("browser") as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(
                    "fetch_page", {"url": "file:///etc/passwd"}
                )
                response = json.loads(result.content[0].text)
                assert "error" in response

    @pytest.mark.asyncio
    async def test_rejects_dangerous_selector(self):
        """get_computed_styles must reject selectors with JS injection attempts."""
        async with await _connect("browser") as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(
                    "get_computed_styles",
                    {
                        "url": TEST_URL,
                        "selector": "p; alert('xss')"
                    }
                )
                response = json.loads(result.content[0].text)
                assert "error" in response

    @pytest.mark.asyncio
    async def test_unknown_tool_returns_error_not_crash(self):
        """Calling a non-existent tool must return a clean error, not crash."""
        async with await _connect("browser") as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(
                    "write_to_filesystem",
                    {"path": "/etc/passwd", "content": "hacked"}
                )
                response = json.loads(result.content[0].text)
                assert "error" in response
                assert response["error"] == "unknown_tool"


# ---------------------------------------------------------------------------
# Functional tests — live calls against example.com
# ---------------------------------------------------------------------------

class TestBrowserMCPFunctional:

    @pytest.mark.asyncio
    async def test_fetch_page_returns_html(self):
        """fetch_page must return HTML content for a valid URL."""
        async with await _connect("browser") as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(
                    "fetch_page", {"url": TEST_URL}
                )
                response = json.loads(result.content[0].text)

                assert "error" not in response, f"Unexpected error: {response}"
                assert "rendered_html" in response
                assert len(response["rendered_html"]) > 100
                assert "title" in response
                assert response["url"] == TEST_URL

    @pytest.mark.asyncio
    async def test_get_computed_styles_returns_elements(self):
        """get_computed_styles must return elements with colour properties."""
        async with await _connect("browser") as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(
                    "get_computed_styles",
                    {"url": TEST_URL, "selector": "p,h1,h2"}
                )
                response = json.loads(result.content[0].text)

                assert "error" not in response
                assert "elements" in response
                assert len(response["elements"]) > 0

                # Every element must have the fields the contrast agent needs
                for el in response["elements"]:
                    assert "tag" in el
                    assert "color" in el
                    assert "background_color" in el
                    assert "font_size" in el
                    # Colour values should be CSS rgb() format
                    assert el["color"].startswith("rgb"), (
                        f"Expected rgb() colour, got: {el['color']}"
                    )

    @pytest.mark.asyncio
    async def test_get_dom_snapshot_returns_tree(self):
        """get_dom_snapshot must return an accessibility tree."""
        async with await _connect("browser") as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(
                    "get_dom_snapshot", {"url": TEST_URL}
                )
                response = json.loads(result.content[0].text)

                assert "error" not in response
                assert "accessibility_tree" in response
                assert response["accessibility_tree"] is not None
                assert "headings" in response
                assert "images" in response
                assert "landmarks" in response

    @pytest.mark.asyncio
    async def test_simulate_keyboard_nav_returns_focus_order(self):
        """simulate_keyboard_nav must return a non-empty focus order."""
        async with await _connect("browser") as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(
                    "simulate_keyboard_nav",
                    {"url": TEST_URL, "max_steps": 10}
                )
                response = json.loads(result.content[0].text)

                assert "error" not in response
                assert "focus_order" in response
                assert "trap_detected" in response
                assert isinstance(response["trap_detected"], bool)
                assert "missing_focus_count" in response


# ---------------------------------------------------------------------------
# axe-core MCP tests
# ---------------------------------------------------------------------------

class TestAxecoreMCPHandshake:

    @pytest.mark.asyncio
    async def test_connection_and_initialize(self):
        async with await _connect("axecore") as (read, write):
            async with ClientSession(read, write) as session:
                result = await session.initialize()
                assert result is not None

    @pytest.mark.asyncio
    async def test_list_tools_returns_run_axe_scan(self):
        async with await _connect("axecore") as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools_result = await session.list_tools()
                tool_names = {t.name for t in tools_result.tools}
                assert "run_axe_scan" in tool_names


class TestAxecoreMCPFunctional:

    @pytest.mark.asyncio
    async def test_run_axe_scan_returns_structured_output(self):
        """run_axe_scan must return violation_count and violations list."""
        async with await _connect("axecore") as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(
                    "run_axe_scan", {"url": TEST_URL}
                )
                response = json.loads(result.content[0].text)

                assert "error" not in response, f"Unexpected error: {response}"
                assert "violation_count" in response
                assert "violations" in response
                assert "passes_count" in response
                assert isinstance(response["violations"], list)

    @pytest.mark.asyncio
    async def test_axe_violation_has_wcag_criterion(self):
        """Each violation must include a normalised WCAG criterion."""
        async with await _connect("axecore") as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(
                    "run_axe_scan", {"url": LOW_CONTRAST_URL}
                )
                response = json.loads(result.content[0].text)

                assert "error" not in response
                # The W3C bad demo page should have violations
                if response["violation_count"] > 0:
                    v = response["violations"][0]
                    assert "wcag_criterion" in v
                    assert "severity_raw" in v
                    assert "affected_nodes" in v
                    assert isinstance(v["affected_nodes"], list)

    @pytest.mark.asyncio
    async def test_axecore_rejects_localhost(self):
        """axe-core server must also reject private network URLs."""
        async with await _connect("axecore") as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(
                    "run_axe_scan", {"url": "http://localhost:3000"}
                )
                response = json.loads(result.content[0].text)
                assert "error" in response


# ---------------------------------------------------------------------------
# Schema contract test — verifies output matches spec/audit_agent_spec.md
# ---------------------------------------------------------------------------

class TestOutputSchemaContract:

    @pytest.mark.asyncio
    async def test_computed_styles_element_matches_contract(self):
        """
        Every element in get_computed_styles output must have the exact fields
        expected by check_contrast_ratios in contrast_agent.py.
        Required: tag, text, color, background_color, font_size
        """
        async with await _connect("browser") as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(
                    "get_computed_styles",
                    {"url": TEST_URL, "selector": "p"}
                )
                response = json.loads(result.content[0].text)
                required_fields = {"tag", "text", "color", "background_color", "font_size"}

                for el in response.get("elements", []):
                    missing = required_fields - set(el.keys())
                    assert not missing, (
                        f"Element missing required fields for contrast agent: {missing}\n"
                        f"Element: {el}"
                    )

    @pytest.mark.asyncio
    async def test_dom_snapshot_includes_headings_images_landmarks(self):
        """
        get_dom_snapshot must include the three supplementary extractions
        the semantic agent depends on.
        """
        async with await _connect("browser") as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(
                    "get_dom_snapshot", {"url": TEST_URL}
                )
                response = json.loads(result.content[0].text)

                assert "headings" in response,  "Missing headings in DOM snapshot"
                assert "images" in response,    "Missing images in DOM snapshot"
                assert "landmarks" in response, "Missing landmarks in DOM snapshot"


# ---------------------------------------------------------------------------
# Screenshot MCP tests
# ---------------------------------------------------------------------------

class TestScreenshotMCPHandshake:

    @pytest.mark.asyncio
    async def test_connection_and_initialize(self):
        """Server must respond to the MCP initialization handshake."""
        async with await _connect("screenshot") as (read, write):
            async with ClientSession(read, write) as session:
                result = await session.initialize()
                assert result is not None, "initialize() returned None"

    @pytest.mark.asyncio
    async def test_list_tools_returns_capture_screenshot(self):
        """Server must advertise exactly one tool: capture_screenshot."""
        async with await _connect("screenshot") as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools_result = await session.list_tools()
                tool_names = {t.name for t in tools_result.tools}
                assert tool_names == {"capture_screenshot"}, (
                    f"Expected {{'capture_screenshot'}}, got {tool_names}"
                )

    @pytest.mark.asyncio
    async def test_tool_schema_has_required_url_field(self):
        """capture_screenshot must declare 'url' as required."""
        async with await _connect("screenshot") as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools_result = await session.list_tools()
                tool = tools_result.tools[0]
                required = tool.inputSchema.get("required", [])
                assert "url" in required, (
                    f"capture_screenshot missing 'url' in required fields"
                )


class TestScreenshotMCPSecurity:

    @pytest.mark.asyncio
    async def test_rejects_localhost_url(self):
        """Server must reject requests targeting localhost."""
        async with await _connect("screenshot") as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(
                    "capture_screenshot", {"url": "http://localhost:8080"}
                )
                response = json.loads(result.content[0].text)
                assert "error" in response, (
                    "Server should have rejected localhost URL"
                )

    @pytest.mark.asyncio
    async def test_rejects_private_network_url(self):
        """Server must reject requests targeting private IP ranges."""
        async with await _connect("screenshot") as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(
                    "capture_screenshot", {"url": "http://192.168.1.1"}
                )
                response = json.loads(result.content[0].text)
                assert "error" in response

    @pytest.mark.asyncio
    async def test_rejects_non_http_url(self):
        """Server must reject file:// and other non-HTTP schemes."""
        async with await _connect("screenshot") as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(
                    "capture_screenshot", {"url": "file:///etc/passwd"}
                )
                response = json.loads(result.content[0].text)
                assert "error" in response

    @pytest.mark.asyncio
    async def test_rejects_dangerous_selector(self):
        """highlight_selector must reject JS injection attempts."""
        async with await _connect("screenshot") as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(
                    "capture_screenshot",
                    {
                        "url": TEST_URL,
                        "highlight_selector": "p; javascript:alert(1)"
                    }
                )
                response = json.loads(result.content[0].text)
                assert "error" in response

    @pytest.mark.asyncio
    async def test_unknown_tool_returns_error_not_crash(self):
        """Calling a non-existent tool must return a clean error."""
        async with await _connect("screenshot") as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(
                    "delete_screenshot", {"id": "abc"}
                )
                response = json.loads(result.content[0].text)
                assert "error" in response
                assert response["error"] == "unknown_tool"


class TestScreenshotMCPFunctional:

    @pytest.mark.asyncio
    async def test_returns_base64_png(self):
        """capture_screenshot must return a base64-encoded PNG."""
        async with await _connect("screenshot") as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(
                    "capture_screenshot",
                    {"url": TEST_URL, "full_page": False}
                )
                response = json.loads(result.content[0].text)

                assert "error" not in response, f"Unexpected error: {response}"
                assert "screenshot_b64" in response
                assert response["mime_type"] == "image/png"
                assert response["size_bytes"] > 0

                import base64
                decoded = base64.b64decode(response["screenshot_b64"])
                assert decoded[:4] == b'\x89PNG', (
                    "Decoded screenshot does not start with PNG magic bytes"
                )

    @pytest.mark.asyncio
    async def test_returns_correct_dimensions(self):
        """Returned metadata must reflect the requested viewport."""
        async with await _connect("screenshot") as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(
                    "capture_screenshot",
                    {"url": TEST_URL, "viewport_width": 800, "viewport_height": 600}
                )
                response = json.loads(result.content[0].text)

                assert "error" not in response
                assert response["width_px"] == 800
                assert response["height_px"] == 600

    @pytest.mark.asyncio
    async def test_highlight_selector_metadata(self):
        """When highlight_selector is provided, response.highlighted must be true."""
        async with await _connect("screenshot") as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(
                    "capture_screenshot",
                    {"url": TEST_URL, "highlight_selector": "h1"}
                )
                response = json.loads(result.content[0].text)

                assert "error" not in response
                assert response["highlighted"] is True

    @pytest.mark.asyncio
    async def test_no_highlight_by_default(self):
        """Without highlight_selector, response.highlighted must be false."""
        async with await _connect("screenshot") as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(
                    "capture_screenshot", {"url": TEST_URL}
                )
                response = json.loads(result.content[0].text)

                assert "error" not in response
                assert response["highlighted"] is False

    @pytest.mark.asyncio
    async def test_viewport_clamped_to_maximum(self):
        """Viewport dimensions exceeding the max must be clamped, not rejected."""
        async with await _connect("screenshot") as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(
                    "capture_screenshot",
                    {"url": TEST_URL, "viewport_width": 9999, "viewport_height": 9999}
                )
                response = json.loads(result.content[0].text)

                assert "error" not in response
                assert response["width_px"] <= 1440
                assert response["height_px"] <= 900


# ---------------------------------------------------------------------------
# Screenshot schema contract test
# ---------------------------------------------------------------------------

class TestScreenshotSchemaContract:

    @pytest.mark.asyncio
    async def test_screenshot_response_has_all_required_fields(self):
        """
        Every screenshot response must include the fields the evaluator
        agent's capture_screenshot_evidence tool expects.
        """
        async with await _connect("screenshot") as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(
                    "capture_screenshot", {"url": TEST_URL}
                )
                response = json.loads(result.content[0].text)

                required_fields = {
                    "url", "screenshot_b64", "mime_type",
                    "width_px", "height_px", "full_page",
                    "highlighted", "clipped", "size_bytes",
                }
                missing = required_fields - set(response.keys())
                assert not missing, (
                    f"Screenshot response missing required fields: {missing}"
                )
