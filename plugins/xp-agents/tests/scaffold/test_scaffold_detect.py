#!/usr/bin/env python3
"""Tests for scaffold_detect.py — surfaces, tooling detection, canonical tools."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

from conftest import _SMMTestCase
from scaffold_detect import (
    canonical_tools_for,
    detect_existing_tooling,
    read_acceptance_surfaces,
)
from system_context_schema import SYSTEM_CONTEXT_FILENAME


def _valid_doc(surfaces: list[dict] | None = None) -> dict:
    """Minimal valid system context with optional acceptance_surfaces."""
    doc: dict = {
        "product": "A test product.",
        "architecture_overview": "Simple architecture.",
        "stack": {"languages": ["Python"]},
        "modules": [{"name": "core", "purpose": "Core logic", "path": "src/core"}],
        "conventions": ["Use type hints"],
        "key_decisions": [{"topic": "language", "decision": "Use Python"}],
        "sources": ["CLAUDE.md"],
        "project_specific": [],
    }
    if surfaces is not None:
        doc["acceptance_surfaces"] = surfaces
    return doc


class TestReadAcceptanceSurfaces(_SMMTestCase):
    def test_empty_when_file_missing(self) -> None:
        self.assertEqual(read_acceptance_surfaces(self.smm_dir), [])

    def test_empty_when_field_absent(self) -> None:
        path = self.smm_dir / SYSTEM_CONTEXT_FILENAME
        path.write_text(json.dumps(_valid_doc()))
        self.assertEqual(read_acceptance_surfaces(self.smm_dir), [])

    def test_propagates_value_error_on_corrupt_file(self) -> None:
        path = self.smm_dir / SYSTEM_CONTEXT_FILENAME
        path.write_text("not json {{{")
        with self.assertRaises(ValueError):
            read_acceptance_surfaces(self.smm_dir)

    def test_propagates_os_error_on_symlink(self) -> None:
        real = self.smm_dir / "real.json"
        real.write_text(json.dumps(_valid_doc()))
        link = self.smm_dir / SYSTEM_CONTEXT_FILENAME
        link.symlink_to(real)
        with self.assertRaises(OSError):
            read_acceptance_surfaces(self.smm_dir)

    def test_returns_surfaces_when_present(self) -> None:
        surfaces = [
            {
                "name": "browser",
                "signals": ["next in package.json"],
                "harness": "playwright",
                "status": "covered",
            },
            {"name": "cli", "signals": ["bin/ in package.json"], "status": "gap"},
        ]
        path = self.smm_dir / SYSTEM_CONTEXT_FILENAME
        path.write_text(json.dumps(_valid_doc(surfaces)))
        self.assertEqual(read_acceptance_surfaces(self.smm_dir), surfaces)


class TestCanonicalToolsFor(unittest.TestCase):
    def test_browser_includes_playwright_and_cypress(self) -> None:
        tools = canonical_tools_for("browser")
        self.assertIn("playwright", tools)
        self.assertIn("cypress", tools)

    def test_http_websocket_includes_hurl_and_bruno(self) -> None:
        tools = canonical_tools_for("http_websocket")
        self.assertIn("hurl", tools)
        self.assertIn("bruno", tools)

    def test_cli_includes_bats(self) -> None:
        self.assertIn("bats", canonical_tools_for("cli"))

    def test_sdk_returns_list(self) -> None:
        self.assertIsInstance(canonical_tools_for("sdk"), list)
        self.assertGreater(len(canonical_tools_for("sdk")), 0)

    def test_automation_returns_list(self) -> None:
        self.assertIsInstance(canonical_tools_for("automation"), list)
        self.assertGreater(len(canonical_tools_for("automation")), 0)

    def test_message_event_returns_list(self) -> None:
        self.assertIsInstance(canonical_tools_for("message_event"), list)
        self.assertGreater(len(canonical_tools_for("message_event")), 0)

    def test_unknown_surface_returns_empty(self) -> None:
        self.assertEqual(canonical_tools_for("not-a-surface"), [])


class TestDetectExistingTooling(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = Path(tempfile.mkdtemp())

    def tearDown(self) -> None:
        import shutil

        shutil.rmtree(self.repo)

    def test_no_tooling_returns_false(self) -> None:
        result = detect_existing_tooling("browser", self.repo)
        self.assertEqual(
            result, {"has_tooling": False, "tool_name": None, "config_files": []}
        )

    def test_detects_playwright_ts_config(self) -> None:
        cfg = self.repo / "playwright.config.ts"
        cfg.write_text("export default {};")
        result = detect_existing_tooling("browser", self.repo)
        self.assertTrue(result["has_tooling"])
        self.assertEqual(result["tool_name"], "playwright")
        self.assertIn(cfg, result["config_files"])

    def test_detects_playwright_js_config(self) -> None:
        cfg = self.repo / "playwright.config.js"
        cfg.write_text("module.exports = {};")
        result = detect_existing_tooling("browser", self.repo)
        self.assertTrue(result["has_tooling"])
        self.assertEqual(result["tool_name"], "playwright")

    def test_detects_cypress_config(self) -> None:
        cfg = self.repo / "cypress.config.ts"
        cfg.write_text("export default {};")
        result = detect_existing_tooling("browser", self.repo)
        self.assertTrue(result["has_tooling"])
        self.assertEqual(result["tool_name"], "cypress")

    def test_detects_hurl_config(self) -> None:
        cfg = self.repo / "hurl.config"
        cfg.write_text("")
        result = detect_existing_tooling("http_websocket", self.repo)
        self.assertTrue(result["has_tooling"])
        self.assertEqual(result["tool_name"], "hurl")

    def test_detects_bruno_config(self) -> None:
        cfg = self.repo / "bruno.json"
        cfg.write_text("{}")
        result = detect_existing_tooling("http_websocket", self.repo)
        self.assertTrue(result["has_tooling"])
        self.assertEqual(result["tool_name"], "bruno")

    def test_detects_bats_config(self) -> None:
        cfg = self.repo / ".batsrc"
        cfg.write_text("")
        result = detect_existing_tooling("cli", self.repo)
        self.assertTrue(result["has_tooling"])
        self.assertEqual(result["tool_name"], "bats")

    def test_detects_pytest_via_pyproject(self) -> None:
        cfg = self.repo / "pyproject.toml"
        cfg.write_text(
            '[project]\nname = "x"\n\n[tool.pytest.ini_options]\nminversion = "6.0"\n'
        )
        result = detect_existing_tooling("cli", self.repo)
        self.assertTrue(result["has_tooling"])

    def test_detects_pytest_via_pytest_ini(self) -> None:
        cfg = self.repo / "pytest.ini"
        cfg.write_text("[pytest]\n")
        result = detect_existing_tooling("cli", self.repo)
        self.assertTrue(result["has_tooling"])

    def test_unknown_surface_returns_no_tooling(self) -> None:
        result = detect_existing_tooling("not-a-surface", self.repo)
        self.assertFalse(result["has_tooling"])
        self.assertIsNone(result["tool_name"])
        self.assertEqual(result["config_files"], [])

    def test_detects_detox_config(self) -> None:
        cfg = self.repo / ".detoxrc.json"
        cfg.write_text("{}")
        result = detect_existing_tooling("automation", self.repo)
        self.assertTrue(result["has_tooling"])
        self.assertEqual(result["tool_name"], "detox")

    def test_detects_appium_config(self) -> None:
        cfg = self.repo / "appium.conf.json"
        cfg.write_text("{}")
        result = detect_existing_tooling("automation", self.repo)
        self.assertTrue(result["has_tooling"])
        self.assertEqual(result["tool_name"], "appium")

    def test_pyproject_without_pytest_section_not_detected(self) -> None:
        cfg = self.repo / "pyproject.toml"
        cfg.write_text('[project]\nname = "x"\n')
        result = detect_existing_tooling("cli", self.repo)
        self.assertFalse(result["has_tooling"])


if __name__ == "__main__":
    unittest.main()
