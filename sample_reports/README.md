# Sample reports

Reference outputs captured from the **live Agent Engine endpoint** so future
runs have a known-good baseline to compare against.

| File | Target | Score | Findings |
|---|---|---|---|
| `example_com.md` | https://example.com | 93/100 (A) | 2 — landmarks only (a minimal, clean page) |
| `w3c_bad_demo.md` | W3C BAD "before" demo | 80/100 (B) | 3 — keyboard, landmark, + real axe-core meta-refresh catch |

**Endpoint:** `projects/947165968965/locations/us-central1/reasoningEngines/5832845963433082880`
**Regenerate:**
```bash
python deploy/call_endpoint.py <resource_name> --url <target_url>
```

## Why these differ across runs (read before debugging a "mismatch")

The pipeline is **not deterministic end to end** — an LLM evaluator triages
severity and writes each finding's rationale. So across runs of the *same* URL:

- **Rationale wording varies** every time (it's generated prose).
- **Severity can shift** by a level (e.g. the keyboard finding has come back both
  Critical and Serious), which moves the overall score a few points. The W3C page
  has produced 2–3 findings and scores of 80–92.
- **What's stable:** the report's *structure* (every section present and filled),
  the WCAG criteria detected, and the axe-core meta-refresh finding on the W3C
  page (a deterministic scanner catch with the actual offending HTML).

So if a future run looks different, that's expected for wording/severity. Only
worry if a **whole section is missing/empty**, the **crawl fails** ("Page could
not be crawled"), or **axe-core times out** ("axe-core scan failed: timeout") —
those are real regressions, not triage variance.
