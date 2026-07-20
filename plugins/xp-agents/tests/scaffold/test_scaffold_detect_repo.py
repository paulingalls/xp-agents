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
from scaffold_detect import (
    detect_monorepo,
    find_introducing_commit,
)


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
