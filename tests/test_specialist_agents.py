"""
tests/test_specialist_agents.py

Unit tests for the deterministic tools in semantic_agent.py and aria_agent.py.
These test pure Python logic — no LLM, no network, no API key required.

Run: pytest tests/test_specialist_agents.py -v
"""

import json
import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from agents.semantic_agent import (
    check_heading_hierarchy,
    check_landmark_regions,
    check_images,
    check_link_text,
)
from agents.aria_agent import (
    analyse_keyboard_results,
    analyse_axe_results,
    check_interactive_element_labels,
    _map_axe_violation,
)


# ===========================================================================
# Semantic agent tool tests
# ===========================================================================

class TestCheckHeadingHierarchy:

    def _run(self, headings: list) -> dict:
        return json.loads(check_heading_hierarchy(json.dumps(headings)))

    def test_valid_linear_hierarchy_no_findings(self):
        headings = [
            {"level": 1, "text": "Page title", "has_id": True},
            {"level": 2, "text": "Section one", "has_id": False},
            {"level": 3, "text": "Subsection", "has_id": False},
            {"level": 2, "text": "Section two", "has_id": False},
        ]
        result = self._run(headings)
        assert result["findings"] == []
        assert result["h1_count"] == 1

    def test_missing_h1_reported(self):
        headings = [
            {"level": 2, "text": "Section", "has_id": False},
            {"level": 3, "text": "Sub", "has_id": False},
        ]
        result = self._run(headings)
        criterion_findings = [f for f in result["findings"]
                              if f["wcag_criterion"] == "1.3.1"]
        assert any("no h1" in f["description"].lower() for f in criterion_findings)

    def test_multiple_h1s_reported(self):
        headings = [
            {"level": 1, "text": "First H1", "has_id": False},
            {"level": 1, "text": "Second H1", "has_id": False},
        ]
        result = self._run(headings)
        assert result["h1_count"] == 2
        assert any("2" in f["description"] for f in result["findings"])

    def test_h1_to_h3_skip_reported(self):
        headings = [
            {"level": 1, "text": "Title", "has_id": True},
            {"level": 3, "text": "Jumped", "has_id": False},  # skips h2
        ]
        result = self._run(headings)
        assert len(result["findings"]) >= 1
        skip_findings = [f for f in result["findings"]
                         if "skipped" in f["description"].lower() or
                            "skip" in f["description"].lower()]
        assert len(skip_findings) >= 1

    def test_h2_to_h4_skip_reported(self):
        headings = [
            {"level": 1, "text": "Title", "has_id": True},
            {"level": 2, "text": "Section", "has_id": False},
            {"level": 4, "text": "Deep", "has_id": False},  # skips h3
        ]
        result = self._run(headings)
        skip_findings = [f for f in result["findings"]
                         if "h3" in f["description"] or "h4" in f["description"]]
        assert len(skip_findings) >= 1

    def test_descending_level_valid(self):
        """h3 → h2 is a valid 'closing a section' move, not a skip."""
        headings = [
            {"level": 1, "text": "Title", "has_id": True},
            {"level": 2, "text": "S1", "has_id": False},
            {"level": 3, "text": "S1.1", "has_id": False},
            {"level": 2, "text": "S2", "has_id": False},  # valid jump back
        ]
        result = self._run(headings)
        # Should only report if there were actual skips — there aren't here
        skip_findings = [f for f in result["findings"]
                         if "skipped" in f["description"].lower()]
        assert len(skip_findings) == 0

    def test_empty_headings_no_findings(self):
        result = self._run([])
        assert result["findings"] == []
        assert result["heading_count"] == 0


class TestCheckLandmarkRegions:

    def _run(self, landmarks: list) -> dict:
        return json.loads(check_landmark_regions(json.dumps(landmarks)))

    def test_required_landmarks_present_no_findings(self):
        landmarks = [
            {"role": "main", "tag": "MAIN", "label": None},
            {"role": "nav",  "tag": "NAV",  "label": "Main navigation"},
        ]
        result = self._run(landmarks)
        assert result["findings"] == []

    def test_missing_main_reported_as_serious(self):
        landmarks = [{"role": "nav", "tag": "NAV", "label": None}]
        result = self._run(landmarks)
        main_findings = [f for f in result["findings"]
                         if "main" in f["description"].lower()]
        assert len(main_findings) >= 1
        assert main_findings[0]["severity_raw"] == "serious"

    def test_missing_nav_reported(self):
        landmarks = [{"role": "main", "tag": "MAIN", "label": None}]
        result = self._run(landmarks)
        nav_findings = [f for f in result["findings"]
                        if "nav" in f["description"].lower()]
        assert len(nav_findings) >= 1

    def test_multiple_unlabelled_navs_reported(self):
        landmarks = [
            {"role": "main", "tag": "MAIN", "label": None},
            {"role": "nav",  "tag": "NAV",  "label": None},
            {"role": "nav",  "tag": "NAV",  "label": None},
        ]
        result = self._run(landmarks)
        nav_label_findings = [f for f in result["findings"]
                               if "nav" in f["description"].lower() and
                                  "aria-label" in f["recommended_fix"].lower()]
        assert len(nav_label_findings) >= 1

    def test_multiple_labelled_navs_no_finding(self):
        landmarks = [
            {"role": "main", "tag": "MAIN", "label": None},
            {"role": "nav",  "tag": "NAV",  "label": "Main navigation"},
            {"role": "nav",  "tag": "NAV",  "label": "Breadcrumb"},
        ]
        result = self._run(landmarks)
        assert result["findings"] == []


class TestCheckImages:

    def _run(self, images: list) -> dict:
        return json.loads(check_images(json.dumps(images)))

    def test_image_with_good_alt_no_finding(self):
        images = [{
            "src": "photo.jpg", "alt": "Two developers pair programming",
            "has_alt": True, "alt_is_empty": False,
            "role": None, "aria_label": None, "visible": True
        }]
        result = self._run(images)
        assert result["findings"] == []

    def test_image_with_empty_alt_decorative_no_finding(self):
        images = [{
            "src": "divider.png", "alt": "",
            "has_alt": True, "alt_is_empty": True,
            "role": None, "aria_label": None, "visible": True
        }]
        result = self._run(images)
        assert result["findings"] == []

    def test_image_missing_alt_entirely_reported(self):
        images = [{
            "src": "chart.png", "alt": None,
            "has_alt": False, "alt_is_empty": False,
            "role": None, "aria_label": None, "visible": True
        }]
        result = self._run(images)
        assert len(result["findings"]) == 1
        assert result["findings"][0]["wcag_criterion"] == "1.1.1"
        assert result["findings"][0]["severity_raw"] == "serious"

    def test_image_role_presentation_skipped(self):
        """Images with role=presentation are intentionally decorative."""
        images = [{
            "src": "bg.jpg", "alt": None,
            "has_alt": False, "alt_is_empty": False,
            "role": "presentation", "aria_label": None, "visible": True
        }]
        result = self._run(images)
        assert result["findings"] == []

    def test_filename_alt_text_reported(self):
        images = [{
            "src": "hero.jpg", "alt": "hero.jpg",
            "has_alt": True, "alt_is_empty": False,
            "role": None, "aria_label": None, "visible": True
        }]
        result = self._run(images)
        assert len(result["findings"]) >= 1
        assert "filename" in result["findings"][0]["description"].lower()

    def test_invisible_images_skipped(self):
        """Hidden images (display:none or zero dimensions) should not be checked."""
        images = [{
            "src": "hidden.png", "alt": None,
            "has_alt": False, "alt_is_empty": False,
            "role": None, "aria_label": None, "visible": False
        }]
        result = self._run(images)
        assert result["findings"] == []

    def test_aria_label_substitutes_alt(self):
        """aria-label on an image should substitute for missing alt."""
        images = [{
            "src": "chart.png", "alt": None,
            "has_alt": False, "alt_is_empty": False,
            "role": None, "aria_label": "Q3 revenue chart", "visible": True
        }]
        result = self._run(images)
        # aria-label provides an accessible name — should not be flagged
        assert result["findings"] == []


class TestCheckLinkText:

    def _make_tree(self, links: list[str]) -> str:
        """Creates a minimal accessibility tree with the given link names."""
        children = [{"role": "link", "name": name} for name in links]
        return json.dumps({"role": "document", "children": children})

    def test_descriptive_links_no_findings(self):
        tree = self._make_tree(["Read our accessibility policy",
                                "Download the annual report (PDF)",
                                "Contact the support team"])
        result = json.loads(check_link_text(tree))
        assert result["findings"] == []

    def test_click_here_reported(self):
        tree = self._make_tree(["Click here"])
        result = json.loads(check_link_text(tree))
        assert len(result["findings"]) == 1
        assert result["findings"][0]["wcag_criterion"] == "2.4.4"

    def test_read_more_reported(self):
        tree = self._make_tree(["Read more"])
        result = json.loads(check_link_text(tree))
        assert len(result["findings"]) >= 1

    def test_here_alone_reported(self):
        tree = self._make_tree(["here"])
        result = json.loads(check_link_text(tree))
        assert len(result["findings"]) >= 1

    def test_mixed_links_only_bad_ones_reported(self):
        tree = self._make_tree([
            "View our privacy policy",
            "click here",
            "Annual report 2025 (PDF)",
            "more",
        ])
        result = json.loads(check_link_text(tree))
        assert len(result["findings"]) == 2  # "click here" and "more"

    def test_empty_tree_no_crash(self):
        result = json.loads(check_link_text(json.dumps({"role": "document"})))
        assert result["findings"] == []

    def test_nested_links_found(self):
        """Links nested in sections must still be found."""
        tree = json.dumps({
            "role": "document",
            "children": [{
                "role": "main",
                "children": [{
                    "role": "article",
                    "children": [{"role": "link", "name": "click here"}]
                }]
            }]
        })
        result = json.loads(check_link_text(tree))
        assert len(result["findings"]) == 1


# ===========================================================================
# ARIA agent tool tests
# ===========================================================================

class TestAnalyseKeyboardResults:

    def _make_nav(self, trap=False, focus_order=None, missing_focus=None,
                  steps=5) -> str:
        return json.dumps({
            "trap_detected": trap,
            "steps_taken": steps,
            "focus_order": focus_order or [],
            "missing_focus_indicators": missing_focus or [],
            "missing_focus_count": len(missing_focus or []),
        })

    def test_clean_keyboard_nav_no_findings(self):
        result = json.loads(analyse_keyboard_results(self._make_nav()))
        assert result["findings"] == []

    def test_trap_detected_critical_finding(self):
        nav = self._make_nav(
            trap=True,
            focus_order=[{"tag": "DIV", "trap_detected": True,
                          "selector_path": "div#modal"}]
        )
        result = json.loads(analyse_keyboard_results(nav))
        trap_findings = [f for f in result["findings"]
                         if f["wcag_criterion"] == "2.1.2"]
        assert len(trap_findings) == 1
        assert trap_findings[0]["severity_raw"] == "critical"

    def test_missing_focus_indicators_reported(self):
        nav = self._make_nav(
            missing_focus=[
                {"tag": "BUTTON", "has_visible_focus": False, "selector_path": "button"},
                {"tag": "BUTTON", "has_visible_focus": False, "selector_path": "button"},
                {"tag": "A", "has_visible_focus": False, "selector_path": "a"},
            ]
        )
        result = json.loads(analyse_keyboard_results(nav))
        focus_findings = [f for f in result["findings"]
                          if f["wcag_criterion"] == "2.4.7"]
        assert len(focus_findings) >= 1
        # Should group by tag — 2 buttons → one finding mentioning ×2
        button_findings = [f for f in focus_findings if "button" in f["element_selector"]]
        assert len(button_findings) == 1
        assert "×2" in button_findings[0]["element_html_snippet"]

    def test_zero_steps_critical_keyboard_finding(self):
        """If no elements received focus at all, keyboard access is completely broken."""
        nav = self._make_nav(steps=0)
        result = json.loads(analyse_keyboard_results(nav))
        keyboard_findings = [f for f in result["findings"]
                              if f["wcag_criterion"] == "2.1.1"]
        assert len(keyboard_findings) >= 1
        assert keyboard_findings[0]["severity_raw"] == "critical"


class TestAnalyseAxeResults:

    def _make_violation(self, rule_id: str, impact: str = "serious") -> dict:
        return {
            "id": rule_id,
            "description": f"Test violation: {rule_id}",
            "help": f"Fix {rule_id}",
            "help_url": "https://dequeuniversity.com",
            "impact": impact,
            "severity_raw": impact,
            "tags": ["wcag2a", "wcag412"],
            "affected_nodes": [{
                "selector": "button.no-name",
                "html_snippet": "<button class='no-name'></button>",
                "failure_summary": "Fix: add accessible name",
            }],
            "affected_node_count": 1,
        }

    def test_aria_violations_mapped_correctly(self):
        axe_output = json.dumps({
            "violation_count": 1,
            "violations": [self._make_violation("button-name")],
        })
        result = json.loads(analyse_axe_results(axe_output))
        assert len(result["findings"]) == 1
        assert result["findings"][0]["wcag_criterion"] == "4.1.2"

    def test_contrast_violations_filtered_out(self):
        """Contrast violations belong to contrast_agent — must not appear here."""
        axe_output = json.dumps({
            "violation_count": 1,
            "violations": [self._make_violation("color-contrast")],
        })
        result = json.loads(analyse_axe_results(axe_output))
        # color-contrast is not in _AXE_RULE_TO_WCAG — it should be excluded
        # because it maps to 1.4.3 which is not in aria_relevant_criteria
        assert len(result["findings"]) == 0 or \
               all(f["wcag_criterion"] != "1.4.3" for f in result["findings"])

    def test_axe_error_returns_structured_finding(self):
        """axe-core failures must not silently disappear."""
        axe_output = json.dumps({
            "error": "timeout",
            "message": "Page timed out",
        })
        result = json.loads(analyse_axe_results(axe_output))
        assert len(result["findings"]) == 1
        assert "failed" in result["findings"][0]["description"].lower()

    def test_empty_violations_no_findings(self):
        axe_output = json.dumps({
            "violation_count": 0,
            "violations": [],
        })
        result = json.loads(analyse_axe_results(axe_output))
        assert result["findings"] == []


class TestCheckInteractiveElementLabels:

    def _make_tree(self, elements: list[dict]) -> str:
        return json.dumps({"role": "document", "children": elements})

    def test_labelled_button_no_finding(self):
        tree = self._make_tree([{"role": "button", "name": "Submit form"}])
        result = json.loads(check_interactive_element_labels(tree))
        assert result["findings"] == []

    def test_unlabelled_button_reported(self):
        tree = self._make_tree([{"role": "button", "name": ""}])
        result = json.loads(check_interactive_element_labels(tree))
        assert len(result["findings"]) >= 1
        assert result["findings"][0]["wcag_criterion"] == "4.1.2"

    def test_multiple_unlabelled_buttons_grouped(self):
        """Multiple unlabelled buttons of the same role → one grouped finding."""
        tree = self._make_tree([
            {"role": "button", "name": ""},
            {"role": "button", "name": ""},
            {"role": "button", "name": ""},
        ])
        result = json.loads(check_interactive_element_labels(tree))
        button_findings = [f for f in result["findings"]
                           if "button" in f["element_selector"]]
        assert len(button_findings) == 1
        assert "3" in button_findings[0]["description"]

    def test_labelled_and_unlabelled_mixed(self):
        tree = self._make_tree([
            {"role": "button", "name": "Close dialog"},  # labelled
            {"role": "button", "name": ""},               # unlabelled
            {"role": "textbox", "name": "Email address"}, # labelled
            {"role": "textbox", "name": ""},              # unlabelled
        ])
        result = json.loads(check_interactive_element_labels(tree))
        # Should have 2 findings: one for button, one for textbox
        assert len(result["findings"]) == 2

    def test_non_interactive_elements_skipped(self):
        """Headings, paragraphs etc. without names should not be flagged."""
        tree = self._make_tree([
            {"role": "heading", "name": ""},
            {"role": "paragraph", "name": ""},
            {"role": "img", "name": ""},         # img is not in interactive_roles
        ])
        result = json.loads(check_interactive_element_labels(tree))
        assert result["findings"] == []

    def test_deeply_nested_unlabelled_element_found(self):
        """Unlabelled elements inside nav > ul > li > button must be found."""
        tree = json.dumps({
            "role": "document",
            "children": [{
                "role": "navigation",
                "name": "Main",
                "children": [{
                    "role": "list",
                    "children": [{
                        "role": "listitem",
                        "children": [{"role": "button", "name": ""}]
                    }]
                }]
            }]
        })
        result = json.loads(check_interactive_element_labels(tree))
        assert len(result["findings"]) >= 1
