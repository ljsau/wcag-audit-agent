#!/usr/bin/env bash
# Build-time install script for the Agent Engine container.
#
# Runs during image build, before the agent starts, in the same environment
# where pip requirements are installed. Installs the headless Chromium binary
# AND its system libraries (libnss3, libatk-bridge2.0, libgbm, fonts, ...),
# which the Playwright pip package alone does NOT provide.
#
# Referenced from deploy/deploy.py via build_options.installation_scripts.
set -euo pipefail

echo "[install.sh] Installing Playwright Chromium + system deps..."
python -m playwright install --with-deps chromium
echo "[install.sh] Chromium install complete."
