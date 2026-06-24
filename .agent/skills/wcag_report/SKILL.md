---
name: wcag-report
version: 1.0.0
description: |
  Generates a complete, prioritised WCAG 2.1 AA accessibility audit report
  for a web page or site. Orchestrates the full audit pipeline: crawl, run
  contrast/semantic/ARIA checks in parallel, triage findings by severity, and
  render a scored Markdown report with actionable remediation guidance.
  Use when the user asks for a full accessibility audit, accessibility report,
  WCAG compliance report, or comprehensive check of a site.
  Do NOT use for targeted single-criterion checks — use the specific skill
  (wcag-contrast, wcag-semantic, wcag-aria) when the user asks about one
  specific aspect.
security_level: read-only
hitl_required: false
trajectory_mode: IN_ORDER
estimated_tokens: 1200
---

# WCAG full audit report generator

Orchestrates the complete four-agent WCAG 2.1 AA audit pipeline and produces
a scored Markdown report. This skill calls the orchestrator agent, which fans
out to the specialist agents and evaluator. The report generator itself is
deterministic Python — no LLM token cost at the rendering step.

## Trigger

**Positive triggers** — use this skill when the user asks for:
- "Run a full accessibility audit on https://example.com"
- "Generate a WCAG compliance report for this site"
- "Check accessibility of https://example.com"
- "Audit this page for accessibility issues"

**Negative triggers** — do NOT use this skill for targeted single-criterion
checks. Prefer the specific skill to avoid unnecessary token cost:
- Contrast only → `wcag-contrast`
- Heading order only → `wcag-semantic`
- Keyboard navigation only → `wcag-aria`

## Execution

The orchestrator handles the full pipeline. This skill's role is to initiate
it with the correct parameters.

```yaml
steps:
  - order: 1
    action: validate_url
    args:
      url: "{{url}}"
    gate: stop_if_invalid
    critical: true

  - order: 2
    action: delegate_to_orchestrator
    args:
      url: "{{validated_url}}"
      depth: "{{depth | default: 1}}"
      max_pages: "{{max_pages | default: 10}}"
    note: >
      Orchestrator fans out to crawler → [contrast, semantic, aria in parallel]
      → evaluator → report_generator. Do not call specialist agents directly
      from this skill.
    critical: true

  - order: 3
    action: return_report
    note: Return the Markdown report string to the user.
```

## Report structure

The generated report contains:

```yaml
sections:
  - Executive summary (score badge, severity table, pass/fail status)
  - Security notes (if injection attempt detected during crawl)
  - Top 5 issues (full detail: description, WCAG criterion, element, fix)
  - All findings table (severity, criterion, element, description)
  - WCAG criteria affected (grouped by criterion)
  - Pages audited
  - Metadata (timestamps, tool versions, scoring model)
```

## Scoring model

```yaml
score: max(0, 100 - sum_of_penalties)
penalties:
  critical: 10
  serious:   5
  moderate:  2
  minor:     1
wcag_aa_pass: critical_count == 0 AND serious_count == 0
```

## Multi-page audits

If `depth` > 1, the crawler discovers internal links and the orchestrator
audits up to `max_pages` unique pages. Findings are aggregated across all
pages with per-page attribution.

Depth 1 (default): root page only.
Depth 2: root + all internal links from root.
Depth 3: root + 2 levels of internal links.
Maximum: depth=3, max_pages=10.

## Security note

The orchestrator scans crawled HTML for injection patterns before any
specialist agent processes it. If an injection attempt is detected, it is
logged as a security note in the report and the audit continues normally.
This skill does not need to handle injection separately.

## Token budget

Estimated skill body tokens: ~1,200. The full pipeline token cost is
determined by the page complexity and number of pages audited, not by
this skill's body size. Flash models are used for all specialist agents;
Pro is reserved for the orchestrator and evaluator only.

## Eval cases

The full audit pipeline is tested by `tests/test_orchestrator.py`. For
this skill's trigger accuracy, write cases in `evals/report_eval.json`.

Include at minimum:
1. Full audit request → triggers this skill (not a specialist)
2. Contrast-only request → must NOT trigger this skill
3. Rephrased audit request ("check accessibility") → triggers this skill

Required trigger accuracy: 90%.

## Known limitations

- Pages behind authentication are not audited (login-wall warning returned)
- WCAG 2.1 AAA criteria are not assessed
- PDF and non-HTML content are out of scope
- Very large pages (>500KB HTML) use accessibility-tree-only mode
