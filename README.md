# WCAG Audit Agent

> An ADK-powered multi-agent system that audits any public URL for WCAG 2.1 AA accessibility compliance and delivers a prioritised, plain-English remediation report — turning a $5,000 manual audit into a 30-second automated one.

**Track:** Agents for Good · Kaggle 5-Day AI Agents Intensive Capstone

---

## The problem

Roughly 1.3 billion people live with a disability. Web accessibility compliance (WCAG 2.1 AA) is a legal requirement in most jurisdictions and a baseline of usability for this population. Despite this, the vast majority of public websites fail basic accessibility checks every day.

Manual audits by certified specialists cost $3,000–$8,000 and take days. Automated tools like axe-core exist, but they produce raw JSON output requiring expert interpretation — a developer looking at 200 violation objects has no way to prioritise or act on them without significant domain knowledge.

The gap is not detection. The gap is **interpretation and prioritisation**. That is precisely where agents add value that a script cannot.

---

## Architecture

```
User (URL)
    │
    ▼
┌─────────────────────────────────────────────────────────┐
│                    Orchestrator Agent                    │
│           gemini-2.5-pro · DAG coordinator              │
│  validate_url · detect_injection_attempt · generate_report│
└──────────┬──────────────────────────────────────────────┘
           │ Step 1: crawl
           ▼
┌─────────────────────┐
│   Crawler Agent     │
│  gemini-2.5-flash   │
│  structure_dom_data │
│  detect_spa_retry   │
└──────────┬──────────┘
           │ dom_data (structured)
           │
     ┌─────┴──────────────────────┐
     │ Step 2: parallel fan-out   │
     ▼            ▼               ▼
┌──────────┐ ┌──────────┐ ┌──────────────┐
│ Contrast │ │ Semantic │ │     ARIA     │
│  Agent   │ │  Agent   │ │    Agent     │
│  Flash   │ │  Flash   │ │    Flash     │
│ WCAG     │ │ WCAG     │ │ WCAG 2.1.1   │
│ 1.4.3    │ │ 1.1.1    │ │ 2.1.2, 2.4.7 │
│ 1.4.6    │ │ 1.3.1    │ │ 4.1.2        │
│          │ │ 2.4.4    │ │              │
│          │ │ 2.4.6    │ │              │
└────┬─────┘ └────┬─────┘ └──────┬───────┘
     │            │              │
     └────────────┴──────────────┘
                  │ findings[]
                  ▼
     ┌─────────────────────────┐
     │    Evaluator Agent      │
     │    gemini-2.5-pro       │
     │  LLM-as-judge · dedup   │
     │  severity triage        │
     └────────────┬────────────┘
                  │ triaged_findings[]
                  ▼
     ┌─────────────────────────┐
     │   Report Generator      │
     │   pure Python · no LLM  │
     │   Markdown + scoring    │
     └─────────────────────────┘
                  │
                  ▼
          Markdown Report

MCP Tool Layer (read-only throughout):
  ├── browser_mcp.py    — Playwright: fetch_page, get_computed_styles,
  │                       get_dom_snapshot, simulate_keyboard_nav
  └── axecore_mcp.py    — axe-core: run_axe_scan
```

### Agent roles

| Agent | Model | Responsibility |
|---|---|---|
| **Orchestrator** | gemini-2.5-pro | URL validation, DAG coordination, injection detection, report trigger |
| **Crawler** | gemini-2.5-flash | Page fetch, DOM extraction, SPA detection, login-wall detection |
| **Contrast** | gemini-2.5-flash | WCAG 1.4.3/1.4.6 — deterministic WCAG luminance formula in pure Python |
| **Semantic** | gemini-2.5-flash | WCAG 1.1.1, 1.3.1, 2.4.4, 2.4.6 — heading order, alt text, link text, landmarks |
| **ARIA** | gemini-2.5-flash | WCAG 2.1.1, 2.1.2, 2.4.7, 4.1.2 — keyboard nav, focus, ARIA roles |
| **Evaluator** | gemini-2.5-pro | Deduplication, LLM-as-judge severity triage, WCAG criterion mapping |
| **Report generator** | None (pure Python) | Deterministic Markdown rendering, score calculation |

### MCP servers

| Server | Transport | Tools | Purpose |
|---|---|---|---|
| `browser_mcp.py` | stdio | `fetch_page`, `get_computed_styles`, `get_dom_snapshot`, `simulate_keyboard_nav` | Sandboxed read-only browser via Playwright |
| `axecore_mcp.py` | stdio | `run_axe_scan` | WCAG rule-based scanning via axe-core |

---

## Course concepts demonstrated

| Concept | Where | Notes |
|---|---|---|
| **ADK / Multi-agent system** | `agents/` | 6-agent DAG — orchestrator + crawler + 3 specialists + evaluator. Demonstrates internal specialisation as a scaling mechanism (Day 2). |
| **MCP server** | `mcp_servers/` | Two custom MCP servers. Read-only enforcement at the server layer, not via model instructions. |
| **Antigravity / Agents CLI** | Deployment | Scaffolded and deployed via `uvx google-agents-cli`. Full lifecycle: scaffold → eval → deploy → observe. |
| **Security features** | `agents/orchestrator.py`, evals | Deterministic injection detection tool. Read-only MCP constraint. Zero ambient authority browser context. Injection test case in eval suite. |
| **Deployability** | Google Agent Engine | One-command deploy. Public endpoint. See [Deployment](#deployment). |
| **Agent skills** | `.agent/skills/` | Four SKILL.md files with positive/negative triggers, token budget notes, and EDD eval cases. |

---

## Prerequisites

- Python 3.12+
- Node.js 18+ (required by axe-core)
- Google Cloud project with Vertex AI API enabled
- `GOOGLE_API_KEY` — get one at [aistudio.google.com](https://aistudio.google.com)

---

## Setup

### 1. Clone and install

```bash
git clone https://github.com/your-username/wcag-audit-agent.git
cd wcag-audit-agent

pip install -r requirements.txt
playwright install chromium
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env and add your GOOGLE_API_KEY
```

`.env.example` contains all required variables — never commit `.env` to git.

### 3. Verify MCP servers

Before running any agents, verify the transport pipes are working:

```bash
pytest tests/test_mcp_servers.py -v
```

All handshake, security, and schema contract tests must pass before proceeding. If a test fails, debug the MCP server directly rather than adjusting agent prompts — fix the pipes, not the instructions.

### 4. Run the deterministic test suite

```bash
# Fast — no API key required, no network calls
pytest tests/ -v -k "not Workflow and not golden"
```

This runs all unit tests for every deterministic tool across all agents (~120 tests). These must pass before running the full eval suite.

---

## Usage

### Single-page audit

```bash
python main.py --url https://example.com
```

### Multi-page audit (follow internal links up to depth 2)

```bash
python main.py --url https://example.com --depth 2
```

### Save report to file

```bash
python main.py --url https://example.com --output report.md
```

### Example output

```
┌─────────────────────────────────────────────────────┐
│ WCAG Audit Agent                                     │
│ URL: https://example.com                             │
│ Depth: 1                                             │
└─────────────────────────────────────────────────────┘

# WCAG Accessibility Audit Report

**URL:** https://example.com
**Audited:** 2026-06-01 09:14 UTC

🟡 **Score: 74/100 (Grade B)** · ❌ WCAG 2.1 AA Fail

## Executive Summary

| Severity   | Count |
|------------|-------|
| 🔴 Critical | 0     |
| 🟠 Serious  | 3     |
| 🟡 Moderate | 8     |
| 🔵 Minor    | 5     |

> ❌ This page fails WCAG 2.1 AA. 3 issue(s) rated critical or serious
> must be resolved.

## Top Issues — Immediate Action Required

### 1. 🟠 Text has contrast ratio of 3.2:1, below the 4.5:1 AA minimum
...
```

---

## Running the evaluation suite

### Contrast agent eval (full EDD suite)

```bash
python evals/run_contrast_evals.py
```

Runs 17 cases across trigger, execution, security, regression, and token-budget categories. The graduation gate requires all cases to pass with ≥ 90% trigger accuracy before the contrast agent is considered integration-ready.

To run a single case:

```bash
python evals/run_contrast_evals.py --case sec_001
```

To run only the security cases:

```bash
python evals/run_contrast_evals.py --category security
```

### LLM-as-judge calibration (requires `GOOGLE_API_KEY`)

```bash
pytest tests/test_evaluator_agent.py -v -k "golden"
```

Runs the 8-case human-labelled golden dataset against the live evaluator agent. Agreement threshold is 85%. If below threshold, review the severity rubric in `agents/evaluator_agent.py`.

### Full integration tests (requires `GOOGLE_API_KEY`)

```bash
pytest tests/test_orchestrator.py -v -k "Workflow"
```

---

## Deployment

### Deploy to Google Agent Engine via Agents CLI

```bash
# One-time setup (installs 7 lifecycle skills into your coding agent)
uvx google-agents-cli setup

# Deploy
agents-cli deploy --agent agents/orchestrator.py \
                  --project $GOOGLE_CLOUD_PROJECT \
                  --region us-central1
```

### Environment variables for deployment

```bash
GOOGLE_API_KEY=...
GOOGLE_CLOUD_PROJECT=your-project-id
GOOGLE_CLOUD_LOCATION=us-central1
DEFAULT_CRAWL_DEPTH=1
DEFAULT_MAX_PAGES=10
```

No API keys in source code. All credentials via environment variables or Google Cloud Secret Manager.

---

## Project structure

```
wcag-audit-agent/
│
├── specs/
│   └── audit_agent_spec.md          # BDD specification — Architectural North Star
│
├── architecture_decisions.md        # 7 documented architectural decisions
│
├── .agent/skills/
│   ├── wcag_contrast/SKILL.md       # Contrast checker skill
│   ├── wcag_semantic/SKILL.md       # Semantic HTML skill
│   ├── wcag_aria/SKILL.md           # ARIA + keyboard skill
│   └── wcag_report/SKILL.md         # Report generation skill
│
├── mcp_servers/
│   ├── browser_mcp.py               # Playwright MCP — 4 read-only tools
│   └── axecore_mcp.py               # axe-core MCP — WCAG rule scanning
│
├── agents/
│   ├── crawler_agent.py             # Generator: DOM extraction
│   ├── contrast_agent.py            # Specialist: colour contrast
│   ├── semantic_agent.py            # Specialist: semantic HTML
│   ├── aria_agent.py                # Specialist: ARIA + keyboard
│   ├── evaluator_agent.py           # LLM-as-judge: severity triage
│   └── orchestrator.py              # Root: DAG coordination
│
├── report/
│   └── report_generator.py          # Pure-function Markdown renderer
│
├── evals/
│   ├── contrast_eval.json           # EDD eval suite (17 cases)
│   └── run_contrast_evals.py        # Eval runner
│
├── tests/
│   ├── test_mcp_servers.py          # MCP handshake + schema contract tests
│   ├── test_crawler_agent.py        # Crawler deterministic tool tests
│   ├── test_evaluator_agent.py      # Evaluator unit + golden dataset tests
│   ├── test_specialist_agents.py    # Semantic + ARIA tool unit tests
│   ├── test_orchestrator.py         # Orchestrator routing + injection tests
│   └── test_report_generator.py     # Report scoring + rendering tests
│
├── main.py                          # CLI entry point
├── AGENTS.md                        # Cross-tool agent constitution
├── requirements.txt
├── .env.example
└── README.md
```

---

## Architectural decisions

Seven key decisions are documented in [`architecture_decisions.md`](architecture_decisions.md). The most important:

**Why internal specialisation, not A2A?** All four specialist agents are maintained in this repo by a single developer. A2A is the correct pattern when specialists are built by different teams across network boundaries — it would add latency and serialisation overhead for no architectural benefit here. The A2A upgrade path (exposing specialist agents as public A2A services with Agent Cards) is documented as the natural v2 evolution.

**Why deterministic Python for contrast ratios?** WCAG 1.4.3 contrast ratios are defined by a mathematical formula with exactly one correct answer per colour pair. Using the LLM to compute or estimate a ratio introduces hallucination risk where there should be zero. The contrast agent calls a pure Python function (`check_contrast_ratios`) and the LLM's role is orchestration only.

**Why Pro for the orchestrator and evaluator, Flash for specialists?** Token economy (Day 1). Flash is ~10x cheaper per token than Pro. Specialists perform bounded, tool-heavy tasks that don't require deep reasoning. The orchestrator handles security-sensitive routing decisions; the evaluator handles nuanced severity triage. Pro is spent only where reasoning complexity justifies the cost.

**Model-agnostic by design.** The business logic lives in the harness — MCP tool definitions, SKILL.md files, BDD spec, eval cases, report template. The LLM is a pluggable reasoning engine. Swapping from Gemini to another model requires changing `model=` in six agent definitions. Documented future paths include Claude via LiteLLM and Ollama for air-gapped enterprise deployments.

---

## Security

- **All MCP tools are read-only.** No form submissions, no cookie persistence, no file downloads. Enforced in `browser_mcp.py` at the tool layer, not via model instructions.
- **Prompt injection defence.** The `detect_injection_attempt` tool in `orchestrator.py` scans crawled HTML with compiled regex before the LLM sees it. If injection patterns are detected, the audit continues normally and a security note is appended to the report. Proven by `sec_001` through `sec_003` in the eval suite.
- **Zero ambient authority.** The browser runs in a fresh, sandboxed Playwright context with no stored credentials, no persistent cookies, and downloads blocked.
- **No credentials in source.** All API keys via environment variables. `git-secrets` scan is part of the definition-of-done checklist in the spec.

---

## Known limitations

- Pages behind authentication are not supported (login-wall detection flags them with a warning)
- WCAG 2.1 AAA criteria are not assessed — only AA
- PDF and non-HTML content are out of scope
- Very large SPAs may require increasing `BROWSER_MCP_TIMEOUT_MS`
- Mobile viewport simulation is not implemented

---

## Requirements

```
google-adk>=1.0.0
google-generativeai>=0.8.0
playwright==1.44.0
mcp==1.0.0
axe-playwright-python==0.1.0
python-dotenv==1.0.0
pydantic==2.7.0
pytest==8.2.0
pytest-asyncio==0.23.6
rich==13.7.0
```

---

## Licence

MIT
