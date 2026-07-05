#!/usr/bin/env bash
# Build-time install script for the Agent Engine container.
#
# Runs during image build, before the agent starts, in the same environment
# where pip requirements are installed. Installs the headless Chromium binary
# AND its system libraries (libnss3, libatk-bridge2.0, libgbm, fonts, ...),
# which the Playwright pip package alone does NOT provide.
#
# MUST live in a top-level `installation_scripts/` directory and be referenced
# from deploy.py via build_options["installation_scripts"] — the SDK only runs
# scripts whose path starts with "installation_scripts" (see
# vertexai/agent_engines/_utils.py:validate_installation_scripts_or_raise).
set -euo pipefail

# PLAYWRIGHT_BROWSERS_PATH=0 installs the browser INTO the pip package
# (site-packages), not $HOME/.cache. The build runs as one user (root) and the
# runtime as another (appuser); a $HOME-based cache would be invisible to the
# runtime user. site-packages is shared, so both find the same binary. The
# runtime must set the SAME env var, forwarded to the MCP subprocess via
# child_env() (see deploy.py env_vars + agents/mcp_tools.py).
export PLAYWRIGHT_BROWSERS_PATH=0

echo "[install.sh] Installing Playwright Chromium + system deps (PLAYWRIGHT_BROWSERS_PATH=0)..."
python -m playwright install --with-deps chromium
echo "[install.sh] Chromium install complete."
