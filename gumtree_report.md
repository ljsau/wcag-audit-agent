# WCAG Accessibility Audit Report
**URL:** https://www.gumtree.com.au/  
**Audited:** 2026-06-27 01:34 UTC  
🟡 **Score: 71/100 (Grade B)** · ❌ WCAG 2.1 AA Fail

---
## Executive Summary
| Severity | Count |
|---|---|
| 🔴 Critical | 0 |
| 🟠 Serious | 5 |
| 🟡 Moderate | 2 |
| 🔵 Minor | 0 |
> ❌ **This page fails WCAG 2.1 AA.** 5 issue(s) rated critical or serious must be resolved. These create real barriers for users with disabilities.

## Top Issues — Immediate Action Required
_These are the highest-priority findings. Fix these first._

### 1. 🟠 Page is missing a 'main' landmark region. Screen reader users rely on landmarks to navigate directly to major sections.

**Severity:** Serious  
**Rationale:** The missing 'main' landmark forces screen reader users to navigate through repetitive header content on every page, significantly impeding access to the primary content.  
**WCAG Criterion:** 1.3.1 — Info and Relationships  
**Element:** `[role='main']`  

```html
(no main landmark found)
```

**How to fix:** Add a <main> element or role="main" attribute to the appropriate container.
### 2. 🟠 Image is missing an alt attribute entirely. All img elements must have an alt attribute.

**Severity:** Serious  
**Rationale:** Missing alt text means visually impaired users cannot access information conveyed by the image. If the image is informative, this significantly impedes understanding the content.  
**WCAG Criterion:** 1.1.1 — Non-text Content  
**Element:** `img[src*='7yfJgN4yEjjVvxu0mJXn_1Iqg0LVao&consent=1']`  

```html
<img src="https://ib.adnxs.com/setuid?entity=315&code=rmF6RJW7k8f5A7yfJgN4yEjjVvxu0mJXn_1Iqg0LVao&consent=1">
```

**How to fix:** Add alt="" if the image is decorative, or add alt="[describe what the image shows]" if it conveys information.
### 3. 🟠 Image is missing an alt attribute entirely. All img elements must have an alt attribute.

**Severity:** Serious  
**Rationale:** Missing alt text means visually impaired users cannot access information conveyed by the image. If the image is informative, this significantly impedes understanding the content.  
**WCAG Criterion:** 1.1.1 — Non-text Content  
**Element:** `img[src*='373929934993535556230&ev_gtm.js_count=1&']`  

```html
<img src="https://pixel.everesttech.net/8045/t?ecvid=43306817594582151373929934993535556230&ev_gtm.js_count=1&">
```

**How to fix:** Add alt="" if the image is decorative, or add alt="[describe what the image shows]" if it conveys information.
### 4. 🟠 Image is missing an alt attribute entirely. All img elements must have an alt attribute.

**Severity:** Serious  
**Rationale:** Missing alt text means visually impaired users cannot access information conveyed by the image. If the image is informative, this significantly impedes understanding the content.  
**WCAG Criterion:** 1.1.1 — Non-text Content  
**Element:** `img[src*='https://cm.everesttech.net/cm']`  

```html
<img src="https://cm.everesttech.net/cm">
```

**How to fix:** Add alt="" if the image is decorative, or add alt="[describe what the image shows]" if it conveys information.
### 5. 🟠 Link text "See more" is not descriptive. Screen reader users navigating by links cannot determine the link's destination

**Severity:** Serious  
**Rationale:** Ambiguous link text forces screen reader users to guess the link's destination, significantly impeding their ability to navigate the site effectively.  
**WCAG Criterion:** 2.4.4 — Link Purpose (In Context)  
**Element:** `a`  

```html
<a ...>See more</a>
```

**How to fix:** Replace "See more" with text that describes the destination or action, e.g. "Read our accessibility policy" instead of "Read more".
## All Findings
| # | Severity | WCAG | Description | Element |
|---|---|---|---|---|
| 1 | 🟠 Serious | 1.3.1 | Page is missing a 'main' landmark region. Screen reader users rely on landmarks… | `[role='main']` |
| 2 | 🟠 Serious | 1.1.1 | Image is missing an alt attribute entirely. All img elements must have an alt at… | `img[src*='7yfJgN4yEjjVvxu0mJXn_1Iqg0LVao` |
| 3 | 🟠 Serious | 1.1.1 | Image is missing an alt attribute entirely. All img elements must have an alt at… | `img[src*='373929934993535556230&ev_gtm.j` |
| 4 | 🟠 Serious | 1.1.1 | Image is missing an alt attribute entirely. All img elements must have an alt at… | `img[src*='https://cm.everesttech.net/cm'` |
| 5 | 🟠 Serious | 2.4.4 | Link text "See more" is not descriptive. Screen reader users navigating by links… | `a` |
| 6 | 🟡 Moderate | 1.3.1 | Heading level skipped: h1 followed by h5. Missing level(s): h2, h3, h4.… | `h5` |
| 7 | 🟡 Moderate | 1.3.1 | Heading level skipped: h2 followed by h5. Missing level(s): h3, h4.… | `h5` |

## WCAG Criteria Affected
| WCAG Criterion | Name | Findings |
|---|---|---|
| 1.1.1 | Non-text Content | 🟠 3 |
| 1.3.1 | Info and Relationships | 🟠 3 |
| 2.4.4 | Link Purpose (In Context) | 🟠 1 |

## Pages Audited
- https://www.gumtree.com.au/

## Audit Metadata
| Field | Value |
|---|---|
| Audit started | 2026-06-27 01:34 UTC |
| Pages audited | 1 |
| Total findings | 7 |
| Duplicates removed | 0 |
| google-adk version | 2.3.0 |
| Playwright version | 1.60.0 |
| axe-core wrapper | 0.1.7 |
| WCAG standard | 2.1 AA |
| Scoring model | critical=−10, serious=−5, moderate=−2, minor=−1 |

---
_Generated by WCAG Audit Agent · [github.com/your-repo/wcag-audit-agent](https://github.com) · Results are automatically generated and should be verified by a qualified accessibility specialist for formal compliance purposes._
