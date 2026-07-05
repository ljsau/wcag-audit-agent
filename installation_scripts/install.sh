#!/usr/bin/env bash
# Build-time install script for the Agent Engine container.
#
# CRITICAL ORDERING FACT: Agent Engine runs installation_scripts at Dockerfile
# step 16 (as root), BEFORE pip installs the app requirements into /code/.venv
# at step 19. So `playwright` is NOT importable when this runs — we must pip
# install it ourselves here. And because the runtime venv is a *different*
# Python from this build-time system Python, we install the browser into a
# FIXED, shared, absolute path (not PLAYWRIGHT_BROWSERS_PATH=0, which would put
# it inside whichever interpreter's site-packages). The runtime sets the same
# PLAYWRIGHT_BROWSERS_PATH (see deploy.py env_vars) so its venv Playwright finds
# the browser here.
#
# The playwright version is pinned to match deploy/requirements.txt so the
# browser build number matches what the runtime Playwright expects.
set -euo pipefail

export PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers
PW_VERSION="1.61.0"

echo "[install.sh] pip installing playwright==${PW_VERSION} (build-time CLI for browser download)..."
python -m pip install --quiet "playwright==${PW_VERSION}"

echo "[install.sh] Installing Chromium + system libs into ${PLAYWRIGHT_BROWSERS_PATH} (running as root)..."
python -m playwright install --with-deps chromium

echo "[install.sh] Making browsers traversable/readable for the runtime user..."
chmod -R a+rX "${PLAYWRIGHT_BROWSERS_PATH}"

echo "[install.sh] Chromium install complete."
ls -la "${PLAYWRIGHT_BROWSERS_PATH}" || true
