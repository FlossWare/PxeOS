"""Capture PxeOS web UI screenshots using Playwright.

Usage:
    pip install playwright && playwright install chromium
    python scripts/capture_screenshots.py

Options:
    --base-url URL     PxeOS server URL (default: http://localhost:8443)
    --output-dir DIR   Output directory (default: docs/screenshots)
    --width WIDTH      Viewport width (default: 1280)
    --height HEIGHT    Viewport height (default: 800)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print(
        "Playwright is not installed.\n"
        "Install it with:\n"
        "  pip install playwright && playwright install chromium"
    )
    sys.exit(1)


# Each entry: (screenshot_name, url_path, page_title)
PAGES = [
    ("dashboard", "/web/", "Dashboard"),
    ("distros", "/web/distros", "Imported Distros"),
    ("profiles", "/web/profiles", "Provisioning Profiles"),
    ("hosts", "/web/hosts", "Host Rules"),
    ("cloud-init", "/web/cloud-init", "Cloud-Init Config Generator"),
    ("import", "/web/import", "Import Distro"),
]


def capture(
    base_url: str = "http://localhost:8443",
    output_dir: str = "docs/screenshots",
    width: int = 1280,
    height: int = 800,
) -> list[str]:
    """Capture screenshots of all PxeOS web UI pages.

    Args:
        base_url: PxeOS server URL (no trailing slash).
        output_dir: Directory to save screenshots.
        width: Browser viewport width.
        height: Browser viewport height.

    Returns:
        List of saved screenshot file paths.
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    saved: list[str] = []

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": width, "height": height})

        for name, path, title in PAGES:
            url = f"{base_url}{path}"
            print(f"  Capturing {name} ({title})... ", end="", flush=True)
            try:
                page.goto(url, wait_until="networkidle", timeout=15000)
                filepath = out / f"{name}.png"
                page.screenshot(path=str(filepath), full_page=True)
                saved.append(str(filepath))
                print("OK")
            except Exception as exc:
                print(f"FAILED: {exc}")

        browser.close()

    print(f"\nCaptured {len(saved)}/{len(PAGES)} screenshots in {output_dir}/")
    return saved


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Capture PxeOS web UI screenshots"
    )
    parser.add_argument(
        "--base-url",
        default="http://localhost:8443",
        help="PxeOS server URL (default: http://localhost:8443)",
    )
    parser.add_argument(
        "--output-dir",
        default="docs/screenshots",
        help="Output directory (default: docs/screenshots)",
    )
    parser.add_argument(
        "--width",
        type=int,
        default=1280,
        help="Viewport width (default: 1280)",
    )
    parser.add_argument(
        "--height",
        type=int,
        default=800,
        help="Viewport height (default: 800)",
    )
    args = parser.parse_args()
    capture(
        base_url=args.base_url,
        output_dir=args.output_dir,
        width=args.width,
        height=args.height,
    )


if __name__ == "__main__":
    main()
