"""Tests for web UI screenshot infrastructure and documentation."""

from __future__ import annotations

import ast
import importlib
import re
import sys
from pathlib import Path
from unittest import mock

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = ROOT / "scripts"
DOCS_DIR = ROOT / "docs"
SCREENSHOTS_DIR = DOCS_DIR / "screenshots"


# ---- Helper: extract PAGES list from capture_screenshots.py ----

def _load_pages_from_script() -> list[tuple[str, str, str]]:
    """Parse PAGES from capture_screenshots.py without importing playwright."""
    script = SCRIPTS_DIR / "capture_screenshots.py"
    source = script.read_text()
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "PAGES":
                    return ast.literal_eval(node.value)
    raise RuntimeError("PAGES not found in capture_screenshots.py")


def _get_web_route_paths() -> set[str]:
    """Extract route paths from pxeos/web/routes.py using AST parsing."""
    routes_file = ROOT / "pxeos" / "web" / "routes.py"
    source = routes_file.read_text()
    tree = ast.parse(source)

    paths: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            # Look for @router.get("/path") decorators
            if isinstance(node.func, ast.Attribute) and node.func.attr == "get":
                if node.args:
                    arg = node.args[0]
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        path = arg.value
                        # Only include page routes (GET that return HTML pages),
                        # not API-style sub-resource routes
                        if path in ("/", "/distros", "/profiles", "/hosts",
                                     "/cloud-init", "/import"):
                            paths.add(f"/web{path}")
    return paths


# ---- Tests ----


class TestCaptureScriptExists:
    """Verify screenshot capture scripts exist and are well-formed."""

    def test_python_script_exists(self):
        script = SCRIPTS_DIR / "capture_screenshots.py"
        assert script.exists(), "scripts/capture_screenshots.py not found"

    def test_shell_script_exists(self):
        script = SCRIPTS_DIR / "capture-screenshots.sh"
        assert script.exists(), "scripts/capture-screenshots.sh not found"

    def test_shell_script_is_executable(self):
        script = SCRIPTS_DIR / "capture-screenshots.sh"
        assert script.stat().st_mode & 0o111, (
            "capture-screenshots.sh should be executable"
        )

    def test_python_script_is_valid_syntax(self):
        """Ensure capture_screenshots.py has valid Python syntax."""
        script = SCRIPTS_DIR / "capture_screenshots.py"
        source = script.read_text()
        # ast.parse raises SyntaxError if invalid
        ast.parse(source)

    def test_python_script_has_pages_list(self):
        """PAGES list should be parseable from the script."""
        pages = _load_pages_from_script()
        assert isinstance(pages, list)
        assert len(pages) > 0

    def test_python_script_pages_are_tuples(self):
        """Each PAGES entry should be a 3-tuple (name, path, title)."""
        pages = _load_pages_from_script()
        for entry in pages:
            assert isinstance(entry, (list, tuple)), f"Expected tuple, got {type(entry)}"
            assert len(entry) == 3, f"Expected 3 elements, got {len(entry)}: {entry}"
            name, path, title = entry
            assert isinstance(name, str) and name
            assert isinstance(path, str) and path.startswith("/web/") or path == "/web/"
            assert isinstance(title, str) and title


class TestPagesCoversRoutes:
    """Verify the PAGES list in capture_screenshots.py covers all web routes."""

    def test_all_get_page_routes_covered(self):
        """PAGES should include every GET page route."""
        pages = _load_pages_from_script()
        page_paths = {p[1] for p in pages}
        route_paths = _get_web_route_paths()

        missing = route_paths - page_paths
        assert not missing, (
            f"Web routes not covered in PAGES list: {missing}"
        )

    def test_no_extra_pages(self):
        """PAGES should not include paths that don't exist as routes."""
        pages = _load_pages_from_script()
        page_paths = {p[1] for p in pages}
        route_paths = _get_web_route_paths()

        extra = page_paths - route_paths
        assert not extra, (
            f"PAGES lists paths that are not web routes: {extra}"
        )

    def test_pages_have_unique_names(self):
        """Each page name should be unique (used as screenshot filename)."""
        pages = _load_pages_from_script()
        names = [p[0] for p in pages]
        assert len(names) == len(set(names)), (
            f"Duplicate page names: {[n for n in names if names.count(n) > 1]}"
        )


class TestWebUIDocumentation:
    """Verify docs/WEB_UI.md covers all web UI pages."""

    def test_web_ui_md_exists(self):
        doc = DOCS_DIR / "WEB_UI.md"
        assert doc.exists(), "docs/WEB_UI.md not found"

    def test_web_ui_md_covers_all_pages(self):
        """WEB_UI.md should mention every page from PAGES."""
        doc = DOCS_DIR / "WEB_UI.md"
        content = doc.read_text()
        pages = _load_pages_from_script()

        for name, path, title in pages:
            # Check that either the page name, path, or title appears
            assert (
                name in content.lower()
                or path in content
                or title in content
            ), f"docs/WEB_UI.md does not mention page '{name}' ({path}, {title})"

    def test_web_ui_md_has_sections(self):
        """WEB_UI.md should have sections for key topics."""
        doc = DOCS_DIR / "WEB_UI.md"
        content = doc.read_text()
        for section in ["Dashboard", "Distros", "Profiles", "Host Rules",
                        "Cloud-Init", "Import"]:
            assert section in content, (
                f"docs/WEB_UI.md missing section for '{section}'"
            )


class TestScreenshotsDirectory:
    """Verify the screenshots directory exists."""

    def test_screenshots_dir_exists(self):
        assert SCREENSHOTS_DIR.exists(), "docs/screenshots/ directory not found"

    def test_screenshots_dir_has_gitkeep(self):
        gitkeep = SCREENSHOTS_DIR / ".gitkeep"
        assert gitkeep.exists(), "docs/screenshots/.gitkeep not found"


class TestReadmeWebUISection:
    """Verify README.md includes the Web UI section."""

    def test_readme_has_web_ui_section(self):
        readme = ROOT / "README.md"
        content = readme.read_text()
        assert "## Web UI" in content, "README.md missing '## Web UI' section"

    def test_readme_links_to_web_ui_docs(self):
        readme = ROOT / "README.md"
        content = readme.read_text()
        assert "docs/WEB_UI.md" in content, (
            "README.md should link to docs/WEB_UI.md"
        )

    def test_readme_mentions_capture_script(self):
        readme = ROOT / "README.md"
        content = readme.read_text()
        assert "capture_screenshots.py" in content, (
            "README.md should mention the capture script"
        )

    def test_readme_lists_web_pages(self):
        readme = ROOT / "README.md"
        content = readme.read_text()
        for page_path in ["/web/", "/web/distros", "/web/profiles",
                          "/web/hosts", "/web/cloud-init", "/web/import"]:
            assert page_path in content, (
                f"README.md should list web page path '{page_path}'"
            )
