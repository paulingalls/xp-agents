#!/usr/bin/env python3
"""Tests for scaffold_detect.py — surfaces, tooling detection, canonical tools."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

from _branching_fixtures import GIT_ENV
from _system_context_fixtures import valid_doc
from conftest import _SMMTestCase
from scaffold_detect import (
    canonical_tools_for,
    detect_existing_tooling,
    detect_monorepo,
    find_introducing_commit,
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


def _git(args: list[str], cwd: Path) -> None:
    """Run a git command in cwd; raise on failure. Used by introducing-commit tests."""
    subprocess.run(args, cwd=cwd, capture_output=True, check=True, env=GIT_ENV)


def _commit(repo: Path, filename: str, body: str, message: str) -> None:
    (repo / filename).write_text(body, encoding="utf-8")
    _git(["git", "add", filename], repo)
    _git(["git", "commit", "-m", message], repo)


class TestFindIntroducingCommit(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = Path(tempfile.mkdtemp(prefix="scaffold-introducing-"))
        _git(["git", "init", "-b", "main", str(self.repo)], Path("/tmp"))
        _git(["git", "config", "user.email", "test@example.com"], self.repo)
        _git(["git", "config", "user.name", "Test"], self.repo)

    def tearDown(self) -> None:
        import shutil

        shutil.rmtree(self.repo, ignore_errors=True)

    def test_returns_commit_that_introduced_config_file(self) -> None:
        """Three commits; the second introduces playwright.config.ts."""
        _commit(self.repo, "README.md", "seed\n", "first")
        _commit(
            self.repo, "playwright.config.ts", "export default {};\n", "add playwright"
        )
        _commit(self.repo, "extra.txt", "more\n", "third")

        result = find_introducing_commit(
            self.repo, [self.repo / "playwright.config.ts"]
        )
        assert result is not None
        self.assertEqual(result["subject"], "add playwright")
        self.assertTrue(len(result["sha"]) >= 7)
        self.assertIn("date", result)

    def test_picks_oldest_introducer_across_multiple_files(self) -> None:
        """Two config files: oldest introducing commit wins."""
        _commit(self.repo, "README.md", "seed\n", "first")
        _commit(self.repo, "a.config.ts", "{}\n", "add a")
        _commit(self.repo, "filler.txt", "x\n", "filler")
        _commit(self.repo, "b.config.ts", "{}\n", "add b")

        result = find_introducing_commit(
            self.repo, [self.repo / "a.config.ts", self.repo / "b.config.ts"]
        )
        assert result is not None
        self.assertEqual(result["subject"], "add a")

    def test_untracked_file_returns_none(self) -> None:
        _commit(self.repo, "README.md", "seed\n", "first")
        (self.repo / "untracked.config.ts").write_text("{}\n", encoding="utf-8")

        result = find_introducing_commit(self.repo, [self.repo / "untracked.config.ts"])
        self.assertIsNone(result)

    def test_missing_file_returns_none(self) -> None:
        _commit(self.repo, "README.md", "seed\n", "first")

        missing = self.repo / "nonexistent.config.ts"
        result = find_introducing_commit(self.repo, [missing])
        self.assertIsNone(result)

    def test_non_git_repo_returns_none(self) -> None:
        non_git = Path(tempfile.mkdtemp(prefix="scaffold-non-git-"))
        try:
            cfg = non_git / "playwright.config.ts"
            cfg.write_text("{}\n", encoding="utf-8")
            result = find_introducing_commit(non_git, [cfg])
            self.assertIsNone(result)
        finally:
            import shutil

            shutil.rmtree(non_git, ignore_errors=True)


class TestDetectMonorepo(unittest.TestCase):
    """Priority-ordered monorepo detection: pnpm > turbo > nx > lerna >
    workspaces > cargo > multi-pyproject. is_monorepo=False when no signal."""

    def setUp(self) -> None:
        self.repo = Path(tempfile.mkdtemp(prefix="scaffold-monorepo-"))

    def tearDown(self) -> None:
        import shutil

        shutil.rmtree(self.repo, ignore_errors=True)

    def _mkpkg(self, *parts: str) -> Path:
        d = self.repo.joinpath(*parts)
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _mk_pyproject(self, parent: str, name: str) -> None:
        self._mkpkg(parent, name)
        (self.repo / parent / name / "pyproject.toml").write_text(
            f'[project]\nname = "{name}"\n', encoding="utf-8"
        )

    def test_single_package_returns_false(self) -> None:
        (self.repo / "package.json").write_text('{"name":"x"}', encoding="utf-8")
        result = detect_monorepo(self.repo)
        self.assertEqual(result, {"is_monorepo": False, "kind": None, "packages": []})

    def test_detect_pnpm(self) -> None:
        (self.repo / "pnpm-workspace.yaml").write_text(
            'packages:\n  - "packages/*"\n  - "apps/*"\n', encoding="utf-8"
        )
        self._mkpkg("packages", "web")
        self._mkpkg("packages", "api")
        self._mkpkg("apps", "site")
        result = detect_monorepo(self.repo)
        self.assertTrue(result["is_monorepo"])
        self.assertEqual(result["kind"], "pnpm")
        self.assertIn("packages/web", result["packages"])
        self.assertIn("packages/api", result["packages"])
        self.assertIn("apps/site", result["packages"])

    def test_detect_npm_workspaces(self) -> None:
        (self.repo / "package.json").write_text(
            json.dumps({"name": "root", "workspaces": ["packages/*"]}),
            encoding="utf-8",
        )
        self._mkpkg("packages", "core")
        result = detect_monorepo(self.repo)
        self.assertTrue(result["is_monorepo"])
        self.assertEqual(result["kind"], "npm-workspaces")
        self.assertIn("packages/core", result["packages"])

    def test_detect_yarn_workspaces(self) -> None:
        (self.repo / "package.json").write_text(
            json.dumps({"name": "root", "workspaces": ["packages/*"]}),
            encoding="utf-8",
        )
        (self.repo / "yarn.lock").write_text("", encoding="utf-8")
        self._mkpkg("packages", "core")
        result = detect_monorepo(self.repo)
        self.assertTrue(result["is_monorepo"])
        self.assertEqual(result["kind"], "yarn-workspaces")

    def test_detect_turbo_with_packages_workspaces(self) -> None:
        (self.repo / "turbo.json").write_text("{}", encoding="utf-8")
        (self.repo / "package.json").write_text(
            json.dumps({"name": "root", "workspaces": ["apps/*"]}),
            encoding="utf-8",
        )
        self._mkpkg("apps", "web")
        result = detect_monorepo(self.repo)
        self.assertTrue(result["is_monorepo"])
        self.assertEqual(result["kind"], "turbo")
        self.assertIn("apps/web", result["packages"])

    def test_detect_turbo_fallback_packages_glob(self) -> None:
        (self.repo / "turbo.json").write_text("{}", encoding="utf-8")
        self._mkpkg("packages", "x")
        result = detect_monorepo(self.repo)
        self.assertEqual(result["kind"], "turbo")
        self.assertIn("packages/x", result["packages"])

    def test_detect_nx(self) -> None:
        (self.repo / "nx.json").write_text("{}", encoding="utf-8")
        self._mkpkg("packages", "core")
        (self.repo / "packages" / "core" / "project.json").write_text(
            "{}", encoding="utf-8"
        )
        self._mkpkg("apps", "web")
        (self.repo / "apps" / "web" / "project.json").write_text("{}", encoding="utf-8")
        result = detect_monorepo(self.repo)
        self.assertTrue(result["is_monorepo"])
        self.assertEqual(result["kind"], "nx")
        self.assertIn("packages/core", result["packages"])
        self.assertIn("apps/web", result["packages"])

    def test_detect_nx_finds_depth_1_and_2(self) -> None:
        """project.json is found 1 level deep (packages/core) AND 2 levels
        deep (apps/group/web). Pins the bounded-depth contract."""
        (self.repo / "nx.json").write_text("{}", encoding="utf-8")
        self._mkpkg("packages", "core")
        (self.repo / "packages" / "core" / "project.json").write_text(
            "{}", encoding="utf-8"
        )
        self._mkpkg("apps", "group", "web")
        (self.repo / "apps" / "group" / "web" / "project.json").write_text(
            "{}", encoding="utf-8"
        )
        result = detect_monorepo(self.repo)
        self.assertEqual(result["kind"], "nx")
        self.assertIn("packages/core", result["packages"])
        self.assertIn("apps/group/web", result["packages"])

    def test_detect_nx_finds_deeply_nested_project(self) -> None:
        """A project nested 3 levels under a grouping dir
        (packages/group/sub/proj) is still discovered — grouping conventions
        push projects past depth 2, so the walk must not be depth-bounded."""
        (self.repo / "nx.json").write_text("{}", encoding="utf-8")
        self._mkpkg("packages", "group", "sub", "proj")
        (self.repo / "packages" / "group" / "sub" / "proj" / "project.json").write_text(
            "{}", encoding="utf-8"
        )
        result = detect_monorepo(self.repo)
        self.assertEqual(result["kind"], "nx")
        self.assertIn("packages/group/sub/proj", result["packages"])

    def test_detect_nx_prunes_node_modules(self) -> None:
        """A project.json under node_modules is NOT reported — pruning heavy
        vendor dirs is what keeps the unbounded walk cheap and correct."""
        (self.repo / "nx.json").write_text("{}", encoding="utf-8")
        self._mkpkg("packages", "core")
        (self.repo / "packages" / "core" / "project.json").write_text(
            "{}", encoding="utf-8"
        )
        self._mkpkg("packages", "core", "node_modules", "dep")
        (
            self.repo / "packages" / "core" / "node_modules" / "dep" / "project.json"
        ).write_text("{}", encoding="utf-8")
        result = detect_monorepo(self.repo)
        self.assertIn("packages/core", result["packages"])
        self.assertNotIn("packages/core/node_modules/dep", result["packages"])

    def test_detect_lerna(self) -> None:
        (self.repo / "lerna.json").write_text(
            json.dumps({"packages": ["packages/*"]}), encoding="utf-8"
        )
        self._mkpkg("packages", "a")
        result = detect_monorepo(self.repo)
        self.assertTrue(result["is_monorepo"])
        self.assertEqual(result["kind"], "lerna")
        self.assertIn("packages/a", result["packages"])

    def test_detect_cargo_workspace(self) -> None:
        (self.repo / "Cargo.toml").write_text(
            '[workspace]\nmembers = ["crates/*"]\n', encoding="utf-8"
        )
        self._mkpkg("crates", "core")
        result = detect_monorepo(self.repo)
        self.assertTrue(result["is_monorepo"])
        self.assertEqual(result["kind"], "cargo")
        self.assertIn("crates/core", result["packages"])

    def test_detect_cargo_workspace_without_members(self) -> None:
        """Empty [workspace] table still signals a cargo monorepo."""
        (self.repo / "Cargo.toml").write_text("[workspace]\n", encoding="utf-8")
        result = detect_monorepo(self.repo)
        self.assertTrue(result["is_monorepo"])
        self.assertEqual(result["kind"], "cargo")
        self.assertEqual(result["packages"], [])

    def test_detect_multi_pyproject(self) -> None:
        self._mk_pyproject("packages", "lib_a")
        self._mk_pyproject("packages", "lib_b")
        result = detect_monorepo(self.repo)
        self.assertTrue(result["is_monorepo"])
        self.assertEqual(result["kind"], "multi-pyproject")
        self.assertIn("packages/lib_a", result["packages"])
        self.assertIn("packages/lib_b", result["packages"])

    def test_detect_multi_pyproject_includes_examples_docs_and_vendor(self) -> None:
        """Pin: vendor/examples/docs subdirs with pyproject.toml flag as packages.

        Doctrine accepts this false-positive risk — see concern 828ea567ff55.
        ``detect_monorepo`` does not exclude ``examples/``, ``docs/``, or
        ``vendor/`` paths; callers downstream (the SKILL agent) negotiate
        with the customer about which "package" actually deserves a
        scaffold. Tightening detect_monorepo here would silently break the
        flow without that negotiation point. This test is the contract,
        not a bug indicator: do NOT 'fix' it by adding an exclude-list.
        """
        self._mk_pyproject("packages", "lib_a")
        self._mk_pyproject("examples", "sample")
        self._mk_pyproject("docs", "x")
        self._mk_pyproject("vendor", "third_party")
        result = detect_monorepo(self.repo)
        self.assertTrue(result["is_monorepo"])
        self.assertEqual(result["kind"], "multi-pyproject")
        self.assertIn("packages/lib_a", result["packages"])
        self.assertIn("examples/sample", result["packages"])
        self.assertIn("docs/x", result["packages"])
        self.assertIn("vendor/third_party", result["packages"])

    def test_priority_pnpm_over_workspaces(self) -> None:
        """pnpm-workspace.yaml outranks package.json workspaces."""
        (self.repo / "pnpm-workspace.yaml").write_text(
            'packages:\n  - "packages/*"\n', encoding="utf-8"
        )
        (self.repo / "package.json").write_text(
            json.dumps({"name": "root", "workspaces": ["apps/*"]}),
            encoding="utf-8",
        )
        self._mkpkg("packages", "x")
        result = detect_monorepo(self.repo)
        self.assertEqual(result["kind"], "pnpm")


if __name__ == "__main__":
    unittest.main()
