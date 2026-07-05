"""
deploy/deploy.py

One-command deploy of the WCAG Audit Agent to Google Agent Engine
(Vertex AI Reasoning Engine), including a build-time Playwright/Chromium install.

Prerequisites (Phase 0 — done once, by you):
    gcloud auth login
    gcloud auth application-default login
    # a GCP project with billing enabled and the Vertex AI API turned on
    # a Cloud Storage bucket for staging

Environment (read from your shell or .env):
    GOOGLE_CLOUD_PROJECT   your GCP project id
    GOOGLE_CLOUD_LOCATION  region, e.g. us-central1
    STAGING_BUCKET         gs://your-bucket   (staging for the build)
    GOOGLE_API_KEY         Gemini key — injected into the runtime env

Run:
    python deploy/deploy.py

On success it prints the deployed resource name (the endpoint handle you put
in kaggle_writeup.md / README). Re-running creates a NEW instance unless you
pass --update <resource_name>.

NOTE ON SDK SURFACE: the exact keyword for build-time scripts has shifted
across aiplatform releases (build_options vs. installation_scripts). This
script targets the current agent_engines API; if create() rejects a kwarg,
print(help(agent_engines.create)) against your installed version and adjust
the two flagged lines below. Everything else is stable.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# Load repo-root .env so GOOGLE_* vars are available when run locally.
_REPO_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_REPO_ROOT / ".env")

# Make the repo root importable so `agent_engine_app` resolves.
sys.path.insert(0, str(_REPO_ROOT))


def _require(name: str) -> str:
    val = os.getenv(name)
    if not val:
        sys.exit(f"[deploy] Missing required env var: {name}")
    return val


def main() -> None:
    parser = argparse.ArgumentParser(description="Deploy WCAG Audit Agent to Agent Engine")
    parser.add_argument(
        "--update", default=None, metavar="RESOURCE_NAME",
        help="Update an existing Agent Engine instead of creating a new one",
    )
    parser.add_argument(
        "--display-name", default="wcag-audit-agent",
        help="Display name for the deployed agent",
    )
    args = parser.parse_args()

    project = _require("GOOGLE_CLOUD_PROJECT")
    location = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")
    staging_bucket = _require("STAGING_BUCKET")
    google_api_key = _require("GOOGLE_API_KEY")

    import vertexai
    from vertexai import agent_engines

    vertexai.init(project=project, location=location, staging_bucket=staging_bucket)

    # The SDK resolves extra_packages / build_options paths relative to the
    # current working directory, so anchor CWD at the repo root and use
    # repo-relative paths from here on (matches the documented convention).
    os.chdir(_REPO_ROOT)

    from agent_engine_app import WcagAuditEngine

    requirements = (_REPO_ROOT / "deploy" / "requirements.txt").read_text().splitlines()
    requirements = [r.strip() for r in requirements if r.strip() and not r.startswith("#")]

    # Everything the remote runtime must import / spawn. Relative paths inside
    # these packages are preserved, so the stdio MCP subprocess launch keeps
    # resolving mcp_servers/browser_mcp.py exactly as it does locally. The
    # install script must be uploaded here too so build_options can run it.
    # The install script MUST be under a top-level "installation_scripts/" dir
    # and listed in extra_packages — the SDK only executes scripts whose path
    # starts with "installation_scripts" (validate_installation_scripts_or_raise).
    extra_packages = [
        "agent_engine_app.py",
        "agents",
        "mcp_servers",
        "report",
        "installation_scripts/install.sh",
    ]

    # Build-time Chromium install. Key is "installation_scripts" — verified
    # against the SDK source (_agent_engines.py:98 _BUILD_OPTIONS_INSTALLATION,
    # used as the build_options key at line 1176). The create() DOCSTRING says
    # "installation", but that key is silently ignored — the code reads
    # "installation_scripts". Path must match its extra_packages entry.
    build_options = {
        "installation_scripts": ["installation_scripts/install.sh"],
    }

    common_kwargs = dict(
        requirements=requirements,
        extra_packages=extra_packages,
        display_name=args.display_name,
        # PLAYWRIGHT_BROWSERS_PATH must match install.sh's fixed path so the
        # runtime venv Playwright finds the browser the build installed there.
        # (Not "0": build-time and runtime use different Python interpreters, so
        # a per-interpreter site-packages path would not be shared.)
        env_vars={
            "GOOGLE_API_KEY": google_api_key,
            "PLAYWRIGHT_BROWSERS_PATH": "/opt/pw-browsers",
        },
        build_options=build_options,
        # Headless Chromium needs headroom — default 1 vCPU can OOM mid-audit.
        resource_limits={"cpu": "4", "memory": "8Gi"},
    )

    print(f"[deploy] project={project} location={location}")
    print(f"[deploy] extra_packages={extra_packages}")
    print("[deploy] Building + deploying (first build downloads Chromium — this is slow)...")

    if args.update:
        remote = agent_engines.update(resource_name=args.update, agent_engine=WcagAuditEngine(), **common_kwargs)
    else:
        remote = agent_engines.create(agent_engine=WcagAuditEngine(), **common_kwargs)

    print("\n[deploy] SUCCESS")
    print(f"[deploy] resource_name: {remote.resource_name}")
    print("[deploy] Put this resource_name in kaggle_writeup.md and README as the live endpoint.")
    print("\n[deploy] Smoke-test it with:  python deploy/call_endpoint.py " + remote.resource_name)


if __name__ == "__main__":
    main()
