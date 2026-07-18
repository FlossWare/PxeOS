#!/bin/bash
# Automated screenshot capture for PxeOS web UI
#
# This script provides instructions and helpers for capturing
# screenshots of every PxeOS web UI page.
#
# Prerequisites:
#   - A running PxeOS server (pxeos server start --config config/pxeos.toml)
#   - One of the capture methods below
#
# Option A: Using Playwright (Python) -- recommended
#   pip install playwright && playwright install chromium
#   python scripts/capture_screenshots.py
#
# Option B: Using Chrome headless
#   for each page/URL pair, run:
#   google-chrome --headless --screenshot=docs/screenshots/<page>.png \
#     --window-size=1280,800 http://localhost:8443/web/<path>
#
# Option C: Manual capture
#   1. Start server: pxeos server start --config config/pxeos.toml
#   2. Open http://localhost:8443/web/ in browser
#   3. Navigate to each page and take a screenshot
#   4. Save to docs/screenshots/

set -euo pipefail

BASE_URL="${PXEOS_URL:-http://localhost:8443}"
OUTPUT_DIR="${SCREENSHOT_DIR:-docs/screenshots}"

# Pages to capture: name path
PAGES=(
    "dashboard:/"
    "distros:/distros"
    "profiles:/profiles"
    "hosts:/hosts"
    "cloud-init:/cloud-init"
    "import:/import"
)

echo "PxeOS Web UI Screenshot Capture"
echo "================================"
echo "Base URL: ${BASE_URL}"
echo "Output:   ${OUTPUT_DIR}"
echo ""

# Check if server is running
if ! curl -sf "${BASE_URL}/api/v1/health" > /dev/null 2>&1; then
    echo "ERROR: PxeOS server is not running at ${BASE_URL}"
    echo "Start it with: pxeos server start --config config/pxeos.toml"
    exit 1
fi

mkdir -p "${OUTPUT_DIR}"

# Try Playwright first
if python3 -c "from playwright.sync_api import sync_playwright" 2>/dev/null; then
    echo "Using Playwright for capture..."
    python3 scripts/capture_screenshots.py --base-url "${BASE_URL}" --output-dir "${OUTPUT_DIR}"
    exit $?
fi

# Try Chrome headless
if command -v google-chrome &>/dev/null || command -v chromium-browser &>/dev/null; then
    CHROME=$(command -v google-chrome || command -v chromium-browser)
    echo "Using Chrome headless for capture..."
    for entry in "${PAGES[@]}"; do
        name="${entry%%:*}"
        path="${entry#*:}"
        echo "  Capturing ${name}..."
        "${CHROME}" --headless --disable-gpu --no-sandbox \
            "--screenshot=${OUTPUT_DIR}/${name}.png" \
            --window-size=1280,800 \
            "${BASE_URL}/web${path}" 2>/dev/null
    done
    echo "Done. Screenshots saved to ${OUTPUT_DIR}/"
    exit 0
fi

echo "No screenshot tool found."
echo ""
echo "Install one of:"
echo "  pip install playwright && playwright install chromium"
echo "  dnf install chromium   # or apt install chromium-browser"
echo ""
echo "Or capture manually -- see page list:"
for entry in "${PAGES[@]}"; do
    name="${entry%%:*}"
    path="${entry#*:}"
    echo "  ${name}: ${BASE_URL}/web${path}"
done
exit 1
