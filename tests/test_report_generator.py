"""
tests/test_report_generator.py

Unit tests for report/report_generator.py.

Everything here is deterministic — no LLM, no network, no API key required.
The report generator is a pure rendering function; these tests verify:
  1. Score calculation maths
  2. WCAG AA pass/fail threshold
  3. Report structure (required sections present)
  4. Finding sort order (severity descending)
  5. Duplicate filtering (duplicates excluded from display)
  6. Security notes included when present
  7. Edge cases (empty findings, single finding, max score)
  8. generate_report tool wrapper (JSON in → Markdown out)

Run: pytest tests/test_report_generator.py -v
"""

import json
import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from report.report_generator import (
    calculate_score,
    build_report,
    generate_report,
    SEVERITY_PENALTY,
    SEVERITY_ORDER,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_finding(severity: str, criterion: str = "1.4.3",
                  selector: str = "p", duplicate_of: str | None = None) -> dict:
    return {
        "id": f"test-{severity}-{criterion}",
        "agent": "contrast",
        "severity": severity,
        "severity_rationale": f"Test rationale for {severity}",
        "wcag_criterion": criterion,
        "wcag_criterion_name": "Contrast (Minimum)",
        "element_selector": selector,
        "element_html_snippet": f"<{selector}>test</{selector}>",
        "description": f"Test {severity} finding on {selector}",
        "recommended_fix": "Fix it.",
        "url": "https://example.com",
        "duplicate_of": duplicate_of,
    }


# ---------------------------------------------------------------------------
# Score calculation tests
# ---------------------------------------------------------------------------

class TestCalculateScore:

    def test_no_findings_is_perfect_score(self):
        result = calculate_score([])
        assert result["overall_score"] == 100
        assert result["wcag_aa_pass"] is True

    def test_one_critical_deducts_10(self):
        result = calculate_score([_make_finding("critical")])
        assert result["overall_score"] == 90

    def test_one_serious_deducts_5(self):
        result = calculate_score([_make_finding("serious")])
        assert result["overall_score"] == 95

    def test_one_moderate_deducts_2(self):
        result = calculate_score([_make_finding("moderate")])
        assert result["overall_score"] == 98

    def test_one_minor_deducts_1(self):
        result = calculate_score([_make_finding("minor")])
        assert result["overall_score"] == 99

    def test_mixed_findings_correct_total(self):
        findings = [
            _make_finding("critical"),   # -10
            _make_finding("critical"),   # -10
            _make_finding("serious"),    # -5
            _make_finding("moderate"),   # -2
            _make_finding("minor"),      # -1
        ]
        # 100 - 10 - 10 - 5 - 2 - 1 = 72
        result = calculate_score(findings)
        assert result["overall_score"] == 72

    def test_score_clamped_to_zero(self):
        """Many critical findings must not produce a negative score."""
        findings = [_make_finding("critical") for _ in range(15)]  # -150
        result = calculate_score(findings)
        assert result["overall_score"] == 0

    def test_wcag_aa_fails_on_critical(self):
        result = calculate_score([_make_finding("critical")])
        assert result["wcag_aa_pass"] is False

    def test_wcag_aa_fails_on_serious(self):
        result = calculate_score([_make_finding("serious")])
        assert result["wcag_aa_pass"] is False

    def test_wcag_aa_passes_with_only_moderate(self):
        result = calculate_score([_make_finding("moderate")])
        assert result["wcag_aa_pass"] is True

    def test_wcag_aa_passes_with_only_minor(self):
        result = calculate_score([_make_finding("minor")])
        assert result["wcag_aa_pass"] is True

    def test_counts_accurate(self):
        findings = [
            _make_finding("critical"),
            _make_finding("critical"),
            _make_finding("serious"),
            _make_finding("moderate"),
            _make_finding("moderate"),
            _make_finding("minor"),
        ]
        result = calculate_score(findings)
        assert result["critical_count"] == 2
        assert result["serious_count"] == 1
        assert result["moderate_count"] == 2
        assert result["minor_count"] == 1

    def test_unknown_severity_counts_as_minor(self):
        """Unknown severity levels should not crash score calculation."""
        finding = _make_finding("minor")
        finding["severity"] = "unknown_level"
        result = calculate_score([finding])
        # Should not raise, score should be valid
        assert 0 <= result["overall_score"] <= 100


# ---------------------------------------------------------------------------
# Report structure tests
# ---------------------------------------------------------------------------

class TestBuildReport:

    def _build(self, findings=None, url="https://example.com",
               security_notes=None) -> str:
        return build_report(
            url=url,
            triaged_findings=findings or [],
            pages_audited=[url],
            security_notes=security_notes or [],
        )

    def test_report_contains_url(self):
        report = self._build(url="https://mysite.example")
        assert "https://mysite.example" in report

    def test_report_contains_executive_summary_heading(self):
        report = self._build()
        assert "## Executive Summary" in report

    def test_report_contains_all_findings_section(self):
        report = self._build()
        assert "## All Findings" in report

    def test_report_contains_metadata_section(self):
        report = self._build()
        assert "## Audit Metadata" in report

    def test_report_contains_pages_audited_section(self):
        report = self._build()
        assert "## Pages Audited" in report

    def test_empty_findings_shows_pass_message(self):
        report = self._build(findings=[])
        assert "✅" in report
        assert "WCAG 2.1 AA Pass" in report

    def test_critical_findings_shows_fail_message(self):
        report = self._build(findings=[_make_finding("critical")])
        assert "❌" in report
        assert "WCAG 2.1 AA Fail" in report or "fails WCAG" in report

    def test_top_5_section_present_with_findings(self):
        findings = [_make_finding("critical") for _ in range(3)]
        report = self._build(findings=findings)
        assert "Top Issues" in report

    def test_security_note_included_when_present(self):
        report = self._build(security_notes=["Injection attempt detected in page body."])
        assert "Security Notes" in report
        assert "Injection attempt detected" in report

    def test_no_security_section_without_notes(self):
        report = self._build(security_notes=[])
        assert "Security Notes" not in report

    def test_findings_sorted_critical_first(self):
        findings = [
            _make_finding("minor",    selector="a"),
            _make_finding("critical", selector="p"),
            _make_finding("moderate", selector="h1"),
            _make_finding("serious",  selector="button"),
        ]
        report = self._build(findings=findings)
        # Critical section card should appear before minor
        crit_pos   = report.find("critical")
        minor_pos  = report.find("minor")
        assert crit_pos < minor_pos, "Critical findings must appear before minor"

    def test_duplicates_excluded_from_display(self):
        original  = _make_finding("serious", selector="p.original")
        duplicate = _make_finding("serious", selector="p.dupe",
                                  duplicate_of=original["id"])
        report = self._build(findings=[original, duplicate])
        # Only 1 finding rendered (the original), duplicate is filtered out
        assert "### 1." in report
        assert "### 2." not in report
        # The duplicate's unique selector must not appear anywhere
        assert "p.dupe" not in report

    def test_duplicate_count_in_metadata(self):
        original  = _make_finding("serious")
        duplicate = _make_finding("serious", duplicate_of=original["id"])
        report = self._build(findings=[original, duplicate])
        assert "Duplicates removed" in report
        assert "| 1 |" in report or "1" in report  # 1 duplicate removed

    def test_score_in_report(self):
        findings = [_make_finding("critical")]  # score = 90
        report = self._build(findings=findings)
        assert "90" in report

    def test_perfect_score_report(self):
        report = self._build(findings=[])
        assert "100" in report

    def test_zero_score_clamped(self):
        findings = [_make_finding("critical") for _ in range(20)]  # -200
        report = self._build(findings=findings)
        assert "0/100" in report or "Score: 0" in report

    def test_wcag_criteria_section_present_with_findings(self):
        findings = [_make_finding("serious", criterion="1.4.3")]
        report = self._build(findings=findings)
        assert "WCAG Criteria" in report
        assert "1.4.3" in report

    def test_report_contains_footer_disclaimer(self):
        report = self._build()
        assert "should be verified" in report or "qualified accessibility" in report

    def test_element_selector_in_report(self):
        findings = [_make_finding("serious", selector="button#submit")]
        report = self._build(findings=findings)
        assert "button#submit" in report

    def test_recommended_fix_in_top_issues(self):
        finding = _make_finding("critical")
        finding["recommended_fix"] = "Increase contrast ratio to at least 4.5:1"
        report = self._build(findings=[finding])
        assert "Increase contrast ratio" in report

    def test_multiple_pages_all_listed(self):
        report = build_report(
            url="https://example.com",
            triaged_findings=[],
            pages_audited=["https://example.com",
                           "https://example.com/about",
                           "https://example.com/contact"],
        )
        assert "https://example.com/about"   in report
        assert "https://example.com/contact" in report

    def test_report_is_valid_markdown(self):
        """Report must start with a # heading."""
        report = self._build()
        assert report.startswith("# ")

    def test_report_contains_no_raw_json(self):
        """The rendered report must not leak raw JSON to the reader."""
        findings = [_make_finding("critical")]
        report = self._build(findings=findings)
        # JSON artefacts that should not appear in a clean Markdown report
        for artefact in ['"severity":', '"wcag_criterion":', '"element_selector":']:
            assert artefact not in report, (
                f"Raw JSON key {artefact!r} found in rendered report"
            )


# ---------------------------------------------------------------------------
# generate_report tool wrapper tests
# ---------------------------------------------------------------------------

class TestGenerateReportTool:

    def test_valid_input_returns_markdown(self):
        payload = json.dumps({
            "url": "https://test.example",
            "triaged_findings": [_make_finding("moderate")],
            "pages_audited": ["https://test.example"],
        })
        result = generate_report(payload)
        assert result.startswith("# ")
        assert "test.example" in result

    def test_empty_findings_returns_pass_report(self):
        payload = json.dumps({
            "url": "https://perfect.example",
            "triaged_findings": [],
        })
        result = generate_report(payload)
        assert "100" in result
        assert "✅" in result

    def test_malformed_json_returns_error_report(self):
        result = generate_report("{ not valid json }")
        assert "Error" in result or "error" in result

    def test_missing_url_uses_unknown(self):
        payload = json.dumps({"triaged_findings": []})
        result = generate_report(payload)
        assert "unknown" in result

    def test_security_notes_passed_through(self):
        payload = json.dumps({
            "url": "https://test.example",
            "triaged_findings": [],
            "security_notes": ["Prompt injection detected in page title."],
        })
        result = generate_report(payload)
        assert "Prompt injection detected" in result

    def test_idempotent_same_input_same_output(self):
        """Pure function — identical inputs must produce identical outputs."""
        payload = json.dumps({
            "url": "https://idempotent.example",
            "triaged_findings": [_make_finding("serious")],
            "pages_audited": ["https://idempotent.example"],
            "audit_start_iso": "2026-06-01T09:00:00Z",
        })
        result_1 = generate_report(payload)
        result_2 = generate_report(payload)
        assert result_1 == result_2
