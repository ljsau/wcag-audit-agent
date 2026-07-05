"""
agent_engine_app.py

Deployable wrapper for Google Agent Engine (Vertex AI Reasoning Engine).

Agent Engine deploys a *callable object*, not a CLI. This module exposes the
existing audit pipeline (agents.orchestrator._run_audit_pipeline_async) through
the Agent Engine "custom template" contract:

  - set_up(self)          : one-time init in the remote runtime
  - query(self, **kwargs) : synchronous request handler returning JSON-able dict

The underlying pipeline is unchanged — this class only adapts the async,
CLI-oriented entry point to the sync request/response shape Agent Engine calls.

Local smoke test (free, no cloud):
    python agent_engine_app.py --url https://example.com
"""

from __future__ import annotations

import asyncio
import json
from typing import Any


def _run_sync(coro: Any) -> Any:
    """
    Run a coroutine to completion from a sync context, tolerating the case
    where Agent Engine already has a running event loop on the calling thread.
    """
    try:
        running = asyncio.get_running_loop()
    except RuntimeError:
        running = None

    if running is not None and running.is_running():
        # Off-load to a worker thread with its own fresh loop.
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(lambda: asyncio.run(coro)).result()

    return asyncio.run(coro)


class WcagAuditEngine:
    """Agent Engine custom-template app for the WCAG audit pipeline."""

    def set_up(self) -> None:
        """
        Called once when the remote instance boots. Imports are deferred to
        here so the module pickles cleanly and heavy deps load in the runtime,
        not at deploy-packaging time.
        """
        from agents.orchestrator import validate_url, _run_audit_pipeline_async

        self._validate_url = validate_url
        self._run_pipeline = _run_audit_pipeline_async

    def query(self, url: str, html_content: str | None = None) -> dict:
        """
        Run a full WCAG audit against `url`.

        Args:
            url: Public URL to audit (http/https).
            html_content: Optional pre-fetched rendered DOM (HTML-input mode,
                for bot-protected sites). Structural checks run against this
                instead of fetching the page.

        Returns:
            {"status": "ok", "url": ..., "report_md": ...} on success,
            {"status": "error", "error": ...} on validation/pipeline failure.
        """
        validation = json.loads(self._validate_url(url))
        if not validation.get("valid"):
            return {"status": "error", "error": validation.get("error", "invalid url")}

        normalised = validation["normalised_url"]
        report_md = _run_sync(
            self._run_pipeline(normalised, html_content=html_content)
        )

        if not report_md:
            return {
                "status": "error",
                "url": normalised,
                "error": "pipeline produced no report",
            }

        return {"status": "ok", "url": normalised, "report_md": report_md}


# Module-level factory Agent Engine (and agents-cli) can import by path.
def get_agent() -> WcagAuditEngine:
    return WcagAuditEngine()


if __name__ == "__main__":
    # Local smoke test — exercises the exact object Agent Engine will run,
    # without any cloud calls. Verifies set_up() + query() end to end.
    import argparse
    import sys
    from dotenv import load_dotenv

    # Reports contain emoji (e.g. 🟢); Windows consoles default to cp1252.
    # This only affects local printing — Agent Engine returns JSON, not stdout.
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    load_dotenv()

    parser = argparse.ArgumentParser(description="Local smoke test of the Agent Engine wrapper")
    parser.add_argument("--url", required=True, help="URL to audit")
    parser.add_argument("--html-file", default=None, help="Optional HTML-input-mode file")
    args = parser.parse_args()

    html = None
    if args.html_file:
        from pathlib import Path

        html = Path(args.html_file).read_text(encoding="utf-8", errors="replace")

    app = get_agent()
    app.set_up()
    result = app.query(url=args.url, html_content=html)
    print(json.dumps({k: v for k, v in result.items() if k != "report_md"}, indent=2))
    if result.get("report_md"):
        print("\n----- report_md -----\n")
        print(result["report_md"])
