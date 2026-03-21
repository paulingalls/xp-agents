"""Tests for seed_smm.py — default SMM generation."""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import seed_smm


class TestDetection(unittest.TestCase):
    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())

    def tearDown(self):
        import shutil

        shutil.rmtree(self.tmpdir)

    def test_no_linter(self):
        self.assertFalse(seed_smm.has_linter(self.tmpdir))

    def test_has_eslintrc(self):
        (self.tmpdir / ".eslintrc.json").touch()
        self.assertTrue(seed_smm.has_linter(self.tmpdir))

    def test_has_ruff_toml(self):
        (self.tmpdir / "ruff.toml").touch()
        self.assertTrue(seed_smm.has_linter(self.tmpdir))

    def test_has_swiftlint(self):
        (self.tmpdir / ".swiftlint.yml").touch()
        self.assertTrue(seed_smm.has_linter(self.tmpdir))

    def test_has_biome(self):
        (self.tmpdir / "biome.json").touch()
        self.assertTrue(seed_smm.has_linter(self.tmpdir))

    def test_pyproject_with_ruff(self):
        (self.tmpdir / "pyproject.toml").write_text("[tool.ruff]\nline-length = 88")
        self.assertTrue(seed_smm.has_linter(self.tmpdir))

    def test_pyproject_without_ruff(self):
        (self.tmpdir / "pyproject.toml").write_text("[project]\nname = 'foo'")
        self.assertFalse(seed_smm.has_linter(self.tmpdir))

    def test_no_tests(self):
        self.assertFalse(seed_smm.has_tests(self.tmpdir))

    def test_has_tests_dir(self):
        (self.tmpdir / "tests").mkdir()
        self.assertTrue(seed_smm.has_tests(self.tmpdir))

    def test_has_test_file(self):
        (self.tmpdir / "test_foo.py").touch()
        self.assertTrue(seed_smm.has_tests(self.tmpdir))

    def test_has_jest_test(self):
        (self.tmpdir / "app.test.ts").touch()
        self.assertTrue(seed_smm.has_tests(self.tmpdir))

    def test_has_swift_test(self):
        (self.tmpdir / "FooTests.swift").touch()
        self.assertTrue(seed_smm.has_tests(self.tmpdir))

    def test_has_src_test(self):
        (self.tmpdir / "src" / "test").mkdir(parents=True)
        self.assertTrue(seed_smm.has_tests(self.tmpdir))

    def test_no_hooks(self):
        self.assertFalse(seed_smm.has_git_hooks(self.tmpdir))

    def test_has_lefthook(self):
        (self.tmpdir / "lefthook.yml").touch()
        self.assertTrue(seed_smm.has_git_hooks(self.tmpdir))

    def test_has_husky(self):
        (self.tmpdir / ".husky").mkdir()
        (self.tmpdir / ".husky" / "pre-commit").write_text("#!/bin/sh\nnpx lint-staged")
        self.assertTrue(seed_smm.has_git_hooks(self.tmpdir))

    def test_no_ci(self):
        self.assertFalse(seed_smm.has_ci(self.tmpdir))

    def test_has_github_actions(self):
        (self.tmpdir / ".github" / "workflows").mkdir(parents=True)
        self.assertTrue(seed_smm.has_ci(self.tmpdir))

    def test_has_gitlab_ci(self):
        (self.tmpdir / ".gitlab-ci.yml").touch()
        self.assertTrue(seed_smm.has_ci(self.tmpdir))


class TestGenerateSMM(unittest.TestCase):
    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())

    def tearDown(self):
        import shutil

        shutil.rmtree(self.tmpdir)

    def test_empty_project_has_all_risks(self):
        smm = seed_smm.generate_smm(self.tmpdir)
        self.assertIn("No linter configured", smm)
        self.assertIn("No test files detected", smm)
        self.assertIn("No git commit hooks", smm)
        self.assertIn("No CI/CD configured", smm)

    def test_project_with_everything_has_no_risks(self):
        (self.tmpdir / "ruff.toml").touch()
        (self.tmpdir / "tests").mkdir()
        (self.tmpdir / "lefthook.yml").touch()
        (self.tmpdir / ".github" / "workflows").mkdir(parents=True)
        smm = seed_smm.generate_smm(self.tmpdir)
        self.assertIn("none detected", smm)

    def test_has_xp_constraints(self):
        smm = seed_smm.generate_smm(self.tmpdir)
        self.assertIn("TDD", smm)
        self.assertIn("plan", smm.lower())
        self.assertIn("Small commits", smm)
        self.assertIn("strict linting", smm)
        self.assertIn("commit hooks", smm)

    def test_has_wisdom(self):
        smm = seed_smm.generate_smm(self.tmpdir)
        self.assertIn("xp-kickoff", smm)

    def test_has_four_pillars(self):
        smm = seed_smm.generate_smm(self.tmpdir)
        self.assertIn("## Intent", smm)
        self.assertIn("## Constraints", smm)
        self.assertIn("## Risks", smm)
        self.assertIn("## Wisdom", smm)


if __name__ == "__main__":
    unittest.main()
