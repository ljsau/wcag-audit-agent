"""
tests/test_crawler_agent.py

Unit tests for crawler_agent.py's two deterministic tools:
  - structure_dom_data
  - detect_spa_and_suggest_retry

No LLM, no network, no API key required.
All browser MCP responses are mocked as JSON strings.

These tests verify the spec's edge cases directly:
  - Happy path: valid page with content
  - SPA empty tree → should_retry = True
  - Large page HTML truncation → warning present
  - Login wall detection → status = "login_wall"
  - MCP error surfaces cleanly → status = "error"
  - dom_data schema fields all present

Run: pytest tests/test_crawler_agent.py -v
"""

import json
import pytest
import sys
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))

from agents.crawler_agent import (
    structure_dom_data,
    detect_spa_and_suggest_retry,
    _flatten_tree,
)


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

def _make_fetch_result(
    title:          str  = "Test Page",
    html:           str  = "<html><body><h1>Hello</h1></body></html>",
    links:          list = None,
    truncated:      bool = False,
) -> str:
    return json.dumps({
        "url":           "https://example.com",
        "title":         title,
        "rendered_html": html,
        "internal_links": links or ["https://example.com/about"],
        "truncated":     truncated,
        "html_length":   len(html),
    })


def _make_snapshot_result(
    tree:      dict = None,
    headings:  list = None,
    images:    list = None,
    landmarks: list = None,
) -> str:
    return json.dumps({
        "accessibility_tree": tree or {
            "role": "document",
            "children": [
                {"role": "navigation", "name": "Main nav", "children": [
                    {"role": "link", "name": "Home"},
                    {"role": "link", "name": "About"},
                ]},
                {"role": "heading", "name": "Hello", "level": 1},
                {"role": "main", "children": [
                    {"role": "paragraph", "name": "Body text"},
                    {"role": "button", "name": "Submit"},
                    {"role": "textbox", "name": "Email"},
                ]},
            ],
        },
        "headings":  headings  or [{"level": 1, "text": "Hello", "has_id": False}],
        "images":    images    or [],
        "landmarks": landmarks or [{"role": "main", "tag": "MAIN", "label": None}],
    })


def _make_empty_snapshot() -> str:
    return json.dumps({
        "accessibility_tree": {},
        "headings": [],
        "images":   [],
        "landmarks": [],
    })


def _make_minimal_snapshot(node_count: int = 2) -> str:
    """Creates a snapshot with a very small accessibility tree."""
    children = [{"role": "paragraph", "name": f"text {i}"} for i in range(node_count)]
    return json.dumps({
        "accessibility_tree": {
            "role": "document",
            "children": children,
        },
        "headings": [],
        "images":   [],
        "landmarks": [],
    })


# ---------------------------------------------------------------------------
# structure_dom_data tests
# ---------------------------------------------------------------------------

class TestStructureDomData:

    def _run(self, fetch=None, snapshot=None, url="https://example.com") -> dict:
        result = structure_dom_data(
            url=url,
            fetch_result_json=fetch or _make_fetch_result(),
            snapshot_result_json=snapshot or _make_snapshot_result(),
        )
        return json.loads(result)

    # ── Happy path ──────────────────────────────────────────────────────────

    def test_ok_status_on_valid_page(self):
        result = self._run()
        assert result["status"] == "ok"

    def test_dom_data_not_none_on_valid_page(self):
        result = self._run()
        assert result["dom_data"] is not None

    def test_all_spec_fields_present(self):
        """Every field from the dom_data schema in specs/audit_agent_spec.md
        must be present in the output."""
        required_fields = {
            "url", "rendered_html", "accessibility_tree",
            "computed_styles_selector", "internal_links",
            "page_title", "timestamp",
        }
        result = self._run()
        dom = result["dom_data"]
        missing = required_fields - set(dom.keys())
        assert not missing, f"dom_data missing required fields: {missing}"

    def test_enriched_fields_present(self):
        """Enriched fields (headings, images, landmarks) from get_dom_snapshot
        must also be included for specialists that need them directly."""
        result = self._run()
        dom = result["dom_data"]
        assert "headings"  in dom
        assert "images"    in dom
        assert "landmarks" in dom

    def test_url_preserved(self):
        result = self._run(url="https://mysite.example/page")
        assert result["dom_data"]["url"] == "https://mysite.example/page"

    def test_page_title_preserved(self):
        fetch = _make_fetch_result(title="My Accessibility Page")
        result = self._run(fetch=fetch)
        assert result["dom_data"]["page_title"] == "My Accessibility Page"

    def test_internal_links_preserved(self):
        fetch = _make_fetch_result(links=["https://example.com/about",
                                          "https://example.com/contact"])
        result = self._run(fetch=fetch)
        assert "https://example.com/about"   in result["dom_data"]["internal_links"]
        assert "https://example.com/contact" in result["dom_data"]["internal_links"]

    def test_timestamp_is_iso8601(self):
        result = self._run()
        ts = result["dom_data"]["timestamp"]
        # Should parse without error
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        assert dt is not None

    def test_computed_styles_selector_is_set(self):
        result = self._run()
        sel = result["dom_data"]["computed_styles_selector"]
        assert "p" in sel
        assert "h1" in sel
        assert "button" in sel

    def test_no_warnings_on_clean_page(self):
        result = self._run()
        assert result["warnings"] == []

    # ── Login wall detection ────────────────────────────────────────────────

    def test_login_wall_detected_on_sign_in_page(self):
        """Page with 'Sign in' in title and no main content → login_wall status."""
        fetch = _make_fetch_result(title="Sign in to your account")
        # Snapshot with no main content landmark
        snapshot = json.dumps({
            "accessibility_tree": {
                "role": "document",
                "children": [
                    {"role": "heading", "name": "Sign in", "level": 1},
                    {"role": "textbox", "name": "Email"},
                    {"role": "textbox", "name": "Password"},
                    {"role": "button",  "name": "Sign in"},
                ],
            },
            "headings": [{"level": 1, "text": "Sign in", "has_id": False}],
            "images":   [],
            "landmarks": [],   # No main landmark = likely login wall
        })
        result = self._run(fetch=fetch, snapshot=snapshot)
        assert result["status"] == "login_wall"
        assert any("login" in w.lower() or "paywall" in w.lower()
                   for w in result["warnings"])

    def test_login_link_in_header_not_flagged_as_wall(self):
        """A page with a 'Login' link in the nav but real main content
        should NOT be flagged as a login wall."""
        snapshot = json.dumps({
            "accessibility_tree": {
                "role": "document",
                "children": [
                    {"role": "navigation", "name": "Main nav", "children": [
                        {"role": "link", "name": "Login"},
                    ]},
                    {"role": "main", "children": [    # main content present
                        {"role": "heading",   "name": "Welcome to our site"},
                        {"role": "paragraph", "name": "Real content here."},
                    ]},
                ],
            },
            "headings":  [{"level": 1, "text": "Welcome", "has_id": False}],
            "images":    [],
            "landmarks": [{"role": "main", "tag": "MAIN", "label": None}],
        })
        result = self._run(snapshot=snapshot)
        # Should not be a login wall — main content exists
        assert result["status"] != "login_wall"

    # ── Large page handling ─────────────────────────────────────────────────

    def test_truncated_page_includes_warning(self):
        fetch = _make_fetch_result(html="x" * 60_000, truncated=True)
        result = self._run(fetch=fetch)
        assert any("truncated" in w.lower() for w in result["warnings"])

    def test_truncated_page_still_returns_dom_data(self):
        """Truncation is a warning, not a failure — dom_data must still be returned."""
        fetch = _make_fetch_result(html="x" * 60_000, truncated=True)
        result = self._run(fetch=fetch)
        assert result["dom_data"] is not None
        assert result["status"] in ("ok", "login_wall")  # not "error"

    # ── Empty accessibility tree ─────────────────────────────────────────────

    def test_empty_tree_reports_warning(self):
        result = self._run(snapshot=_make_empty_snapshot())
        assert result["status"] == "empty_tree"
        assert any("empty" in w.lower() or "rendering" in w.lower()
                   for w in result["warnings"])

    def test_empty_tree_still_returns_partial_dom_data(self):
        """Empty tree is a warning, not a fatal error. dom_data still returned."""
        result = self._run(snapshot=_make_empty_snapshot())
        assert result["dom_data"] is not None

    # ── MCP error surfaces ──────────────────────────────────────────────────

    def test_fetch_error_returns_error_status(self):
        fetch_error = json.dumps({
            "error":   "timeout",
            "message": "Page did not load within 30000ms",
        })
        result = self._run(fetch=fetch_error)
        assert result["status"] == "error"
        assert result["dom_data"] is None
        assert any("timeout" in w.lower() or "fetch" in w.lower()
                   for w in result["warnings"])

    def test_snapshot_error_returns_error_status(self):
        snapshot_error = json.dumps({
            "error":   "network_error",
            "message": "Could not connect to browser",
        })
        result = self._run(snapshot=snapshot_error)
        assert result["status"] == "error"
        assert result["dom_data"] is None


# ---------------------------------------------------------------------------
# detect_spa_and_suggest_retry tests
# ---------------------------------------------------------------------------

class TestDetectSpaAndSuggestRetry:

    def _run(self, snapshot: str) -> dict:
        return json.loads(detect_spa_and_suggest_retry(snapshot))

    def test_fully_rendered_page_no_retry(self):
        """A rich page should not trigger a retry."""
        result = self._run(_make_snapshot_result())
        assert result["should_retry"] is False
        assert result["is_spa_like"] is False

    def test_empty_tree_triggers_retry(self):
        result = self._run(_make_empty_snapshot())
        assert result["should_retry"] is True
        assert result["is_spa_like"] is True
        assert result["suggested_wait_ms"] > 0

    def test_minimal_tree_triggers_retry(self):
        """Less than 5 nodes → SPA not done rendering."""
        result = self._run(_make_minimal_snapshot(node_count=2))
        assert result["should_retry"] is True

    def test_suggested_wait_ms_is_3000_for_empty_tree(self):
        """Spec says retry with 3-second additional delay."""
        result = self._run(_make_empty_snapshot())
        assert result["suggested_wait_ms"] == 3000

    def test_reason_string_is_meaningful(self):
        result = self._run(_make_empty_snapshot())
        assert len(result["reason"]) > 10
        assert isinstance(result["reason"], str)

    def test_rich_page_returns_zero_wait(self):
        result = self._run(_make_snapshot_result())
        assert result["suggested_wait_ms"] == 0

    def test_no_crash_on_snapshot_with_no_children(self):
        snapshot = json.dumps({
            "accessibility_tree": {"role": "document"},
            "headings": [], "images": [], "landmarks": [],
        })
        # Should not raise
        result = self._run(snapshot)
        assert "should_retry" in result

    def test_page_with_only_interactive_elements_not_flagged(self):
        """A small but complete page (e.g. a login form) should not be retried
        if it has a reasonable number of interactive nodes."""
        snapshot = json.dumps({
            "accessibility_tree": {
                "role": "document",
                "children": [
                    {"role": "main", "children": [
                        {"role": "heading",  "name": "Sign in", "level": 1},
                        {"role": "textbox",  "name": "Email"},
                        {"role": "textbox",  "name": "Password"},
                        {"role": "button",   "name": "Sign in"},
                        {"role": "link",     "name": "Forgot password?"},
                        {"role": "link",     "name": "Create account"},
                    ]},
                ],
            },
            "headings":  [{"level": 1, "text": "Sign in", "has_id": False}],
            "images":    [],
            "landmarks": [{"role": "main", "tag": "MAIN", "label": None}],
        })
        result = self._run(snapshot)
        # 6 meaningful interactive nodes → fully rendered, no retry
        assert result["should_retry"] is False


# ---------------------------------------------------------------------------
# _flatten_tree helper tests
# ---------------------------------------------------------------------------

class TestFlattenTree:

    def test_empty_dict_returns_empty_list(self):
        assert _flatten_tree({}) == []

    def test_root_node_excluded(self):
        """Root document node should not be counted."""
        tree = {"role": "document", "children": []}
        assert _flatten_tree(tree) == []

    def test_single_child_returned(self):
        tree = {
            "role": "document",
            "children": [{"role": "heading", "name": "Title"}],
        }
        result = _flatten_tree(tree)
        assert len(result) == 1
        assert result[0]["role"] == "heading"

    def test_nested_children_all_returned(self):
        tree = {
            "role": "document",
            "children": [{
                "role": "main",
                "children": [
                    {"role": "heading",   "name": "H1"},
                    {"role": "paragraph", "name": "P1"},
                    {"role": "list", "children": [
                        {"role": "listitem", "name": "Item 1"},
                        {"role": "listitem", "name": "Item 2"},
                    ]},
                ],
            }],
        }
        result = _flatten_tree(tree)
        roles = [n["role"] for n in result]
        assert "main"      in roles
        assert "heading"   in roles
        assert "paragraph" in roles
        assert "list"      in roles
        assert "listitem"  in roles
        assert len(result) == 6  # main + heading + para + list + 2 listitems

    def test_non_dict_nodes_skipped_without_crash(self):
        """Malformed tree nodes should not raise exceptions."""
        tree = {
            "role": "document",
            "children": [
                {"role": "heading", "name": "Valid"},
                None,          # malformed
                "string node", # malformed
                42,            # malformed
            ],
        }
        result = _flatten_tree(tree)
        # Only the valid dict node should be returned
        assert len(result) == 1
        assert result[0]["role"] == "heading"
