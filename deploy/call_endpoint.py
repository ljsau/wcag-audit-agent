"""
deploy/call_endpoint.py

Phase 3 verification: call the deployed Agent Engine endpoint and print the
report. This is what produces the real numbers for the writeup Results section
and the "observe" footage for the demo video.

Usage:
    python deploy/call_endpoint.py <resource_name> [--url https://example.com]
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

_REPO_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_REPO_ROOT / ".env")


def main() -> None:
    parser = argparse.ArgumentParser(description="Call the deployed WCAG audit endpoint")
    parser.add_argument("resource_name", help="Agent Engine resource name from deploy.py")
    parser.add_argument("--url", default="https://example.com", help="URL to audit")
    args = parser.parse_args()

    project = os.getenv("GOOGLE_CLOUD_PROJECT")
    location = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")
    if not project:
        sys.exit("[call] Missing GOOGLE_CLOUD_PROJECT")

    import vertexai
    from vertexai import agent_engines

    vertexai.init(project=project, location=location)

    remote = agent_engines.get(args.resource_name)
    print(f"[call] querying {args.resource_name} with url={args.url} ...")
    result = remote.query(url=args.url)

    status = result.get("status")
    print(f"[call] status={status}  url={result.get('url')}")
    if status == "ok":
        print("\n----- report_md -----\n")
        print(result["report_md"])
    else:
        print(f"[call] error: {result.get('error')}")


if __name__ == "__main__":
    main()
