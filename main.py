"""
main.py

Entry point for the WCAG Audit Agent.
Accepts a URL from the CLI, runs the full audit DAG, and prints the report.

Usage:
    python main.py --url https://example.com
    python main.py --url https://example.com --output report.md

HTML input mode (for bot-protected sites like Gumtree):
    1. Open the page in your real Chrome browser
    2. Press F12 → Elements panel → right-click the <html> tag
       → Copy → Copy outerHTML
    3. Paste into a file, e.g. page.html
    4. Run:
       python main.py --url https://www.gumtree.com.au --html-file page.html

    The structural audit (title, language, landmarks, headings, images, links)
    runs against your real browser's DOM. Contrast and ARIA checks still use
    the live URL.
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


async def run_audit(
    url: str,
    depth: int = 1,
    output_path: str | None = None,
    html_content: str | None = None,
) -> str:
    """
    Runs the full WCAG audit DAG against a URL.
    If html_content is provided, uses that for structural checks instead of
    fetching the page (HTML input mode for bot-protected sites).
    Returns the Markdown report as a string.
    """
    import json
    from agents.orchestrator import validate_url, _run_audit_pipeline_async

    validation = json.loads(validate_url(url))
    if not validation["valid"]:
        return f"# Audit Error\n\n{validation['error']}"

    normalised_url = validation["normalised_url"]

    mode_label = "WCAG audit (HTML input mode)..." if html_content else "Running WCAG audit..."

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        TimeElapsedColumn(),
        console=console,
        transient=True,
    ) as progress:
        task = progress.add_task(mode_label, total=None)
        report_md = await _run_audit_pipeline_async(
            normalised_url, html_content=html_content
        )
        progress.update(task, description="Audit complete.")

    if not report_md:
        report_md = "# Audit Error\n\nThe audit did not produce a report. Check logs."

    if output_path:
        Path(output_path).write_text(report_md, encoding="utf-8")
        console.print(f"\n[green]Report saved to {output_path}[/green]")

    return report_md


def main() -> None:
    parser = argparse.ArgumentParser(
        description="WCAG Audit Agent — accessibility audit for any public URL",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "HTML input mode (for bot-protected sites):\n"
            "  1. Open the page in Chrome → F12 → Elements\n"
            "  2. Right-click <html> → Copy → Copy outerHTML → save to file\n"
            "  3. python main.py --url https://example.com --html-file page.html\n"
        ),
    )
    parser.add_argument(
        "--url", required=True,
        help="Public URL to audit (must start with http:// or https://)",
    )
    parser.add_argument(
        "--html-file", default=None, metavar="FILE",
        help=(
            "Path to an HTML file containing the page's rendered DOM. "
            "Use this for sites that block automated browsers. "
            "Get it via Chrome DevTools → Elements → right-click <html> "
            "→ Copy → Copy outerHTML."
        ),
    )
    parser.add_argument(
        "--depth", type=int, default=1,
        help="How many levels of internal links to follow (default: 1, max: 3)",
    )
    parser.add_argument(
        "--output", default=None,
        help="Save the Markdown report to this file path",
    )
    args = parser.parse_args()

    _check_env()

    html_content: str | None = None
    if args.html_file:
        html_path = Path(args.html_file)
        if not html_path.exists():
            console.print(f"[red]HTML file not found: {args.html_file}[/red]")
            sys.exit(1)
        html_content = html_path.read_text(encoding="utf-8", errors="replace")
        console.print(
            f"[dim]HTML input mode: using {html_path.name} "
            f"({len(html_content):,} bytes)[/dim]"
        )

    console.print(Panel(
        f"[bold]WCAG Audit Agent[/bold]\n"
        f"URL: {args.url}"
        + (f"\nHTML file: {args.html_file}" if args.html_file else ""),
        border_style="blue",
    ))

    report = asyncio.run(run_audit(args.url, args.depth, args.output, html_content))

    console.print("\n")
    console.print(Markdown(report))


if __name__ == "__main__":
    main()
