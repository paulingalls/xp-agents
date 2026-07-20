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

from _system_context_fixtures import valid_doc
from conftest import _SMMTestCase
from scaffold_detect import (
    canonical_tools_for,
    detect_existing_tooling,
    read_acceptance_surfaces,
)
from system_context_schema import SYSTEM_CONTEXT_FILENAME


class TestReadAcceptanceSurfaces(_SMMTestCase):
    def test_empty_when_file_missing(self) -> None:
        self.assertEqual(read_acceptance_surfaces(self.smm_dir), [])

    def test_empty_when_field_absent(self) -> None:
        path = self.smm_dir / SYSTEM_CONTEXT_FILENAME
        path.write_text(json.dumps(valid_doc()))
        self.assertEqual(read_acceptance_surfaces(self.smm_dir), [])

    def test_propagates_value_error_on_corrupt_file(self) -> None:
        path = self.smm_dir / SYSTEM_CONTEXT_FILENAME
        path.write_text("not json {{{")
        with self.assertRaises(ValueError):
            read_acceptance_surfaces(self.smm_dir)

    def test_propagates_os_error_on_symlink(self) -> None:
        real = self.smm_dir / "real.json"
        real.write_text(json.dumps(valid_doc()))
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
        path.write_text(json.dumps(valid_doc(acceptance_surfaces=surfaces)))
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

    def test_http_websocket_includes_bun(self) -> None:
        self.assertIn("bun", canonical_tools_for("http_websocket"))

    def test_sdk_includes_bun(self) -> None:
        self.assertIn("bun", canonical_tools_for("sdk"))

    def test_cli_includes_bun(self) -> None:
        self.assertIn("bun", canonical_tools_for("cli"))

    def test_browser_includes_cucumber(self) -> None:
        tools = canonical_tools_for("browser")
        self.assertIn("cucumber", tools)
        self.assertIn("playwright", tools)
        self.assertIn("cypress", tools)

    def test_sdk_includes_python_bdd_tools(self) -> None:
        tools = canonical_tools_for("sdk")
        self.assertIn("pytest-bdd", tools)
        self.assertIn("behave", tools)

    def test_sdk_includes_gauge(self) -> None:
        self.assertIn("gauge", canonical_tools_for("sdk"))


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

    def test_detects_bun_via_bunfig_for_http_websocket(self) -> None:
        cfg = self.repo / "bunfig.toml"
        cfg.write_text("")
        result = detect_existing_tooling("http_websocket", self.repo)
        self.assertTrue(result["has_tooling"])
        self.assertEqual(result["tool_name"], "bun")

    def test_detects_bun_via_bunfig_for_sdk(self) -> None:
        cfg = self.repo / "bunfig.toml"
        cfg.write_text("")
        result = detect_existing_tooling("sdk", self.repo)
        self.assertTrue(result["has_tooling"])
        self.assertEqual(result["tool_name"], "bun")

    def test_bun_yields_to_earlier_canonical_when_both_configured(self) -> None:
        """When both pytest (cli surface, earlier in canonical list) and bunfig
        configs exist, the earlier canonical wins. Bun is intentionally placed
        after established tools so it acts as a fall-through, not an override."""
        (self.repo / "pytest.ini").write_text("[pytest]\n")
        (self.repo / "bunfig.toml").write_text("")
        result = detect_existing_tooling("cli", self.repo)
        self.assertEqual(result["tool_name"], "pytest-console-scripts")

    def test_detects_cucumber_js_config(self) -> None:
        cfg = self.repo / "cucumber.js"
        cfg.write_text("module.exports = {};")
        result = detect_existing_tooling("browser", self.repo)
        self.assertTrue(result["has_tooling"])
        self.assertEqual(result["tool_name"], "cucumber")
        self.assertIn(cfg, result["config_files"])

    def test_detects_cucumber_json_config(self) -> None:
        cfg = self.repo / "cucumber.json"
        cfg.write_text("{}")
        result = detect_existing_tooling("browser", self.repo)
        self.assertTrue(result["has_tooling"])
        self.assertEqual(result["tool_name"], "cucumber")

    def test_detects_behave_ini_config(self) -> None:
        cfg = self.repo / "behave.ini"
        cfg.write_text("[behave]\n")
        result = detect_existing_tooling("sdk", self.repo)
        self.assertTrue(result["has_tooling"])
        self.assertEqual(result["tool_name"], "behave")

    def test_detects_pytest_bdd_via_pyproject_marker(self) -> None:
        cfg = self.repo / "pyproject.toml"
        cfg.write_text('[project]\nname = "x"\ndependencies = ["pytest-bdd>=7.0"]\n')
        result = detect_existing_tooling("sdk", self.repo)
        self.assertTrue(result["has_tooling"])
        self.assertEqual(result["tool_name"], "pytest-bdd")

    def test_pytest_bdd_marker_rejects_prefix_match(self) -> None:
        """Quote-bounded marker '\"pytest-bdd\"' must not match pytest-bdd-html
        or other prefix-share packages."""
        cfg = self.repo / "pyproject.toml"
        cfg.write_text(
            '[project]\nname = "x"\ndependencies = ["pytest-bdd-html>=1.0"]\n'
        )
        result = detect_existing_tooling("sdk", self.repo)
        self.assertFalse(result["has_tooling"])

    def test_detects_gauge_via_manifest_marker(self) -> None:
        cfg = self.repo / "manifest.json"
        cfg.write_text('{"Language": "python", "Plugins": ["html-report"]}\n')
        result = detect_existing_tooling("sdk", self.repo)
        self.assertTrue(result["has_tooling"])
        self.assertEqual(result["tool_name"], "gauge")

    def test_gauge_marker_rejects_pwa_manifest(self) -> None:
        """The "Plugins": marker must not match a PWA/extension manifest.json
        that has a "Language" key but no gauge "Plugins" list."""
        cfg = self.repo / "manifest.json"
        cfg.write_text('{"name": "My PWA", "lang": "en", "Language": "en"}\n')
        result = detect_existing_tooling("sdk", self.repo)
        self.assertFalse(result["has_tooling"])

    def test_playwright_wins_over_cucumber_when_both_configured(self) -> None:
        """Precedence pin: cucumber appended after playwright in _CANONICAL_TOOLS
        so existing playwright defaults are preserved when both configs exist."""
        (self.repo / "playwright.config.ts").write_text("export default {};")
        (self.repo / "cucumber.js").write_text("module.exports = {};")
        result = detect_existing_tooling("browser", self.repo)
        self.assertEqual(result["tool_name"], "playwright")


if __name__ == "__main__":
    unittest.main()
