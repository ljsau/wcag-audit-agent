"""
main.py

Entry point for the WCAG Audit Agent.
Accepts a URL from the CLI, runs the full audit DAG, and prints the report.

Usage:
    python main.py --url https://example.com
    python main.py --url https://example.com --depth 2
    python main.py --url https://example.com --output report.md
"""

import argparse
import asyncio
import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

load_dotenv()
console = Console(force_terminal=True)


def _check_env() -> None:
    """Fail fast if required environment variables are missing."""
    required = ["GOOGLE_API_KEY"]
    missing = [k for k in required if not os.getenv(k)]
    if missing:
        console.print(
            f"[red]Missing required environment variables: {missing}\n"
            f"Copy .env.example to .env and fill in your credentials.[/red]"
        )
        sys.exit(1)


async def run_audit(url: str, depth: int = 1, output_path: str | None = None) -> str:
    """
    Runs the full WCAG audit DAG against a URL.
    Returns the Markdown report as a string.
    """
    import json
    from agents.orchestrator import validate_url, _run_audit_pipeline_async

    # Step 1: Validate URL
    validation = json.loads(validate_url(url))
    if not validation["valid"]:
        return f"# Audit Error\n\n{validation['error']}"

    normalised_url = validation["normalised_url"]

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        TimeElapsedColumn(),
        console=console,
        transient=True,
    ) as progress:
        task = progress.add_task("Running WCAG audit...", total=None)

        # Step 2: Run the full pipeline directly (avoids nested runner issues)
        report_md = await _run_audit_pipeline_async(normalised_url)

        progress.update(task, description="Audit complete.")

    if not report_md:
        report_md = "# Audit Error\n\nThe audit did not produce a report. Check logs."

    if output_path:
        Path(output_path).write_text(report_md, encoding="utf-8")
        console.print(f"\n[green]Report saved to {output_path}[/green]")

    return report_md


def main() -> None:
    parser = argparse.ArgumentParser(
        description="WCAG Audit Agent — accessibility audit for any public URL"
    )
    parser.add_argument(
        "--url", required=True,
        help="Public URL to audit (must start with http:// or https://)"
    )
    parser.add_argument(
        "--depth", type=int, default=1,
        help="How many levels of internal links to follow (default: 1, max: 3)"
    )
    parser.add_argument(
        "--output", default=None,
        help="Save the Markdown report to this file path"
    )
    args = parser.parse_args()

    _check_env()

    console.print(Panel(
        f"[bold]WCAG Audit Agent[/bold]\n"
        f"URL: {args.url}\n"
        f"Depth: {args.depth}",
        border_style="blue",
    ))

    report = asyncio.run(run_audit(args.url, args.depth, args.output))

    console.print("\n")
    console.print(Markdown(report))


if __name__ == "__main__":
    main()
