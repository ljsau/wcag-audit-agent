"""
report/report_generator.py

Fully deterministic Markdown report generator.

No LLM involvement — all judgement was exercised upstream in the
evaluator_agent. This module renders structured data into a readable,
actionable Markdown document.

Exposed as an ADK @tool so the orchestrator can call it directly.

Design principle (Day 3 — "Shift Intelligence Left"):
  All reasoning about severity, WCAG criteria, and remediation priority
  happened in specialist agents and the evaluator. The report generator
  is a pure rendering function — given the same triaged findings it will
  always produce the same report. No non-determinism here.

Scoring formula (from specs/audit_agent_spec.md):
  score = max(0, 100 - sum of penalties)
  Penalties: critical=10, serious=5, moderate=2, minor=1
  wcag_aa_pass = (critical_count == 0 and serious_count == 0)
"""

import json
import uuid
from datetime import datetime, timezone
from typing import Any

# ---------------------------------------------------------------------------
# Severity ordering and scoring weights
# ---------------------------------------------------------------------------

SEVERITY_ORDER   = {"critical": 0, "serious": 1, "moderate": 2, "minor": 3}
SEVERITY_PENALTY = {"critical": 10, "serious": 5, "moderate": 2, "minor": 1}
SEVERITY_EMOJI   = {"critical": "🔴", "serious": "🟠", "moderate": "🟡", "minor": "🔵"}

# WCAG pass threshold: no critical or serious findings
WCAG_AA_PASS_THRESHOLD = {"critical", "serious"}

# Tool version detection — graceful fallback if packages not installed
def _get_version(package: str, fallback: str = "unknown") -> str:
    try:
        import importlib.metadata
        return importlib.metadata.version(package)
    except Exception:
        return fallback


# ---------------------------------------------------------------------------
# Score calculation (deterministic — tested independently)
# ---------------------------------------------------------------------------

def calculate_score(findings: list[dict]) -> dict:
    """
    Calculates the overall accessibility score and per-severity counts.

    Args:
        findings: List of triaged finding dicts with 'severity' field.

    Returns:
        dict with overall_score, counts by severity, wcag_aa_pass.
    """
    counts = {"critical": 0, "serious": 0, "moderate": 0, "minor": 0}

    for f in findings:
        sev = f.get("severity", "minor").lower()
        if sev in counts:
            counts[sev] += 1

    penalty = sum(
        counts[sev] * SEVERITY_PENALTY[sev]
        for sev in counts
    )

    score = max(0, 100 - penalty)
    wcag_aa_pass = counts["critical"] == 0 and counts["serious"] == 0

    return {
        "overall_score": score,
        "critical_count": counts["critical"],
        "serious_count": counts["serious"],
        "moderate_count": counts["moderate"],
        "minor_count": counts["minor"],
        "wcag_aa_pass": wcag_aa_pass,
    }


# ---------------------------------------------------------------------------
# Markdown section builders
# ---------------------------------------------------------------------------

def _render_score_badge(score: int, wcag_pass: bool) -> str:
    if score >= 90:
        grade, colour = "A", "🟢"
    elif score >= 70:
        grade, colour = "B", "🟡"
    elif score >= 50:
        grade, colour = "C", "🟠"
    else:
        grade, colour = "D", "🔴"

    wcag_status = "✅ WCAG 2.1 AA Pass" if wcag_pass else "❌ WCAG 2.1 AA Fail"
    return f"{colour} **Score: {score}/100 (Grade {grade})** · {wcag_status}"


def _render_summary_table(stats: dict) -> str:
    rows = []
    for sev in ("critical", "serious", "moderate", "minor"):
        count = stats[f"{sev}_count"]
        emoji = SEVERITY_EMOJI[sev]
        rows.append(f"| {emoji} {sev.capitalize()} | {count} |")

    return (
        "| Severity | Count |\n"
        "|---|---|\n"
        + "\n".join(rows)
    )


def _render_finding_card(finding: dict, index: int) -> str:
    sev  = finding.get("severity", "minor")
    crit = finding.get("wcag_criterion", "")
    name = finding.get("wcag_criterion_name", "")
    desc = finding.get("description", "")
    fix  = finding.get("recommended_fix", "")
    sel  = finding.get("element_selector", "")
    snip = finding.get("element_html_snippet", "")
    rat  = finding.get("severity_rationale", "")
    emoji = SEVERITY_EMOJI.get(sev, "⚪")

    lines = [f"### {index}. {emoji} {desc[:120]}"]
    lines.append("")
    lines.append(f"**Severity:** {sev.capitalize()}  ")
    if rat:
        lines.append(f"**Rationale:** {rat}  ")
    lines.append(f"**WCAG Criterion:** {crit} — {name}  ")
    if sel:
        lines.append(f"**Element:** `{sel}`  ")
    if snip:
        lines.append(f"\n```html\n{snip[:300]}\n```")
    lines.append(f"\n**How to fix:** {fix}")
    lines.append("")
    return "\n".join(lines)


def _render_all_findings_table(findings: list[dict]) -> str:
    if not findings:
        return "_No findings — congratulations, this page passes all checked criteria._\n"

    header = "| # | Severity | WCAG | Description | Element |\n|---|---|---|---|---|\n"
    rows = []
    for i, f in enumerate(findings, 1):
        sev   = f.get("severity", "minor")
        emoji = SEVERITY_EMOJI.get(sev, "⚪")
        crit  = f.get("wcag_criterion", "")
        desc  = f.get("description", "")[:80].rstrip()
        sel   = f.get("element_selector", "")[:40]
        # Escape pipe characters inside table cells
        desc  = desc.replace("|", "\\|")
        sel   = sel.replace("|", "\\|")
        rows.append(f"| {i} | {emoji} {sev.capitalize()} | {crit} | {desc}… | `{sel}` |")

    return header + "\n".join(rows) + "\n"


def _render_criteria_coverage(findings: list[dict]) -> str:
    """Groups findings by WCAG criterion for a coverage summary."""
    from collections import defaultdict
    by_criterion: dict[str, list] = defaultdict(list)
    for f in findings:
        crit = f.get("wcag_criterion", "unknown")
        by_criterion[crit].append(f)

    lines = ["| WCAG Criterion | Name | Findings |",
             "|---|---|---|"]
    for crit in sorted(by_criterion.keys()):
        items = by_criterion[crit]
        name = items[0].get("wcag_criterion_name", "")
        count = len(items)
        worst = min(items, key=lambda x: SEVERITY_ORDER.get(x.get("severity", "minor"), 3))
        emoji = SEVERITY_EMOJI.get(worst.get("severity", "minor"), "⚪")
        lines.append(f"| {crit} | {name} | {emoji} {count} |")

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Main report builder
# ---------------------------------------------------------------------------

def build_report(
    url: str,
    triaged_findings: list[dict],
    pages_audited: list[str] | None = None,
    security_notes: list[str] | None = None,
    audit_start_iso: str | None = None,
) -> str:
    """
    Builds the complete Markdown audit report. Pure function — no side effects,
    no API calls. Always produces the same output for the same inputs.

    Args:
        url:              The root URL that was audited.
        triaged_findings: List of triaged finding dicts from evaluator_agent.
        pages_audited:    List of page URLs that were crawled.
        security_notes:   Any injection detection notes from the orchestrator.
        audit_start_iso:  ISO 8601 timestamp of when the audit started.

    Returns:
        Complete Markdown report as a string.
    """
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    audit_time = audit_start_iso or now
    pages = pages_audited or [url]
    security_notes = security_notes or []

    # Filter out duplicates for display (keep originals only)
    display_findings = [
        f for f in triaged_findings
        if not f.get("duplicate_of")
    ]

    # Sort by severity
    display_findings.sort(
        key=lambda f: SEVERITY_ORDER.get(f.get("severity", "minor"), 3)
    )

    stats = calculate_score(display_findings)
    top_5 = display_findings[:5]

    # Tool versions
    versions = {
        "adk":        _get_version("google-adk"),
        "playwright": _get_version("playwright"),
        "axe_core":   _get_version("axe-playwright-python"),
    }

    sections = []

    # ── Header ──────────────────────────────────────────────────────────────
    sections.append(f"# WCAG Accessibility Audit Report\n")
    sections.append(f"**URL:** {url}  \n**Audited:** {now}  \n")
    sections.append(_render_score_badge(stats["overall_score"], stats["wcag_aa_pass"]))
    sections.append("\n\n---\n")

    # ── Executive Summary ────────────────────────────────────────────────────
    sections.append("## Executive Summary\n")
    sections.append(_render_summary_table(stats))
    sections.append("\n")

    if stats["wcag_aa_pass"]:
        sections.append(
            "> ✅ **This page passes WCAG 2.1 AA.** No critical or serious "
            "barriers were found. Review moderate and minor findings to "
            "further improve accessibility.\n"
        )
    else:
        blocker_count = stats["critical_count"] + stats["serious_count"]
        sections.append(
            f"> ❌ **This page fails WCAG 2.1 AA.** {blocker_count} "
            f"issue(s) rated critical or serious must be resolved. "
            f"These create real barriers for users with disabilities.\n"
        )

    sections.append("\n")

    # ── Security notes ───────────────────────────────────────────────────────
    if security_notes:
        sections.append("## ⚠️ Security Notes\n")
        for note in security_notes:
            sections.append(f"> {note}\n\n")

    # ── Top 5 Issues ─────────────────────────────────────────────────────────
    if top_5:
        sections.append("## Top Issues — Immediate Action Required\n")
        sections.append(
            "_These are the highest-priority findings. Fix these first._\n\n"
        )
        for i, finding in enumerate(top_5, 1):
            sections.append(_render_finding_card(finding, i))

    # ── All Findings Table ───────────────────────────────────────────────────
    sections.append("## All Findings\n")
    sections.append(_render_all_findings_table(display_findings))
    sections.append("\n")

    # ── Criteria Coverage ────────────────────────────────────────────────────
    if display_findings:
        sections.append("## WCAG Criteria Affected\n")
        sections.append(_render_criteria_coverage(display_findings))
        sections.append("\n")

    # ── Pages Audited ─────────────────────────────────────────────────────────
    sections.append("## Pages Audited\n")
    for page in pages:
        sections.append(f"- {page}\n")
    sections.append("\n")

    # ── Metadata ─────────────────────────────────────────────────────────────
    sections.append("## Audit Metadata\n")
    sections.append(
        f"| Field | Value |\n"
        f"|---|---|\n"
        f"| Audit started | {audit_time} |\n"
        f"| Pages audited | {len(pages)} |\n"
        f"| Total findings | {len(display_findings)} |\n"
        f"| Duplicates removed | {len(triaged_findings) - len(display_findings)} |\n"
        f"| google-adk version | {versions['adk']} |\n"
        f"| Playwright version | {versions['playwright']} |\n"
        f"| axe-core wrapper | {versions['axe_core']} |\n"
        f"| WCAG standard | 2.1 AA |\n"
        f"| Scoring model | critical=−10, serious=−5, moderate=−2, minor=−1 |\n"
    )
    sections.append("\n")

    # ── Footer ────────────────────────────────────────────────────────────────
    sections.append(
        "---\n"
        "_Generated by WCAG Audit Agent · "
        "[github.com/ljsau/wcag-audit-agent](https://github.com/ljsau/wcag-audit-agent) · "
        "Results are automatically generated and should be verified by a "
        "qualified accessibility specialist for formal compliance purposes._\n"
    )

    return "".join(sections)


# ---------------------------------------------------------------------------
# ADK tool wrapper — called by orchestrator
# ---------------------------------------------------------------------------

def generate_report(report_input_json: str) -> str:
    """
    Generates the final WCAG audit Markdown report from triaged findings.
    This is a pure rendering function — no LLM, no API calls.

    Args:
        report_input_json: JSON object with keys:
            - url: string
            - triaged_findings: list of triaged finding dicts
            - pages_audited: list[str] (optional)
            - security_notes: list[str] (optional)
            - audit_start_iso: string (optional)

    Returns:
        Complete Markdown audit report as a string.
    """
    try:
        data = json.loads(report_input_json)
    except json.JSONDecodeError as e:
        return f"# Report Generation Error\n\nFailed to parse report input: {e}\n"

    url             = data.get("url", "unknown")
    findings        = data.get("triaged_findings", [])
    pages_audited   = data.get("pages_audited", [url])
    security_notes  = data.get("security_notes", [])
    audit_start_iso = data.get("audit_start_iso")

    return build_report(
        url=url,
        triaged_findings=findings,
        pages_audited=pages_audited,
        security_notes=security_notes,
        audit_start_iso=audit_start_iso,
    )
