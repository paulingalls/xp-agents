"""Tests for seed_smm.py — default SMM generation."""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import seed_smm
import smm_schema


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

    def test_has_nested_tests_dir(self):
        (self.tmpdir / "packages" / "api" / "tests").mkdir(parents=True)
        self.assertTrue(seed_smm.has_tests(self.tmpdir))

    def test_has_xcode_tests_dir(self):
        (self.tmpdir / "app" / "MyAppTests").mkdir(parents=True)
        self.assertTrue(seed_smm.has_tests(self.tmpdir))

    def test_has_monorepo_src_test(self):
        (self.tmpdir / "packages" / "api" / "src" / "test").mkdir(parents=True)
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

    def test_returns_dict(self):
        smm = seed_smm.generate_smm(self.tmpdir)
        self.assertIsInstance(smm, dict)

    def test_has_four_pillars(self):
        smm = seed_smm.generate_smm(self.tmpdir)
        for pillar in smm_schema.PILLARS:
            self.assertIn(pillar, smm)
            self.assertIsInstance(smm[pillar], list)

    def test_validates_against_schema(self):
        smm = seed_smm.generate_smm(self.tmpdir)
        errors = smm_schema.validate_smm(smm)
        self.assertEqual(errors, [], f"Schema errors: {errors}")

    def test_entries_have_source_seed(self):
        smm = seed_smm.generate_smm(self.tmpdir)
        for pillar in smm_schema.PILLARS:
            for entry in smm[pillar]:
                self.assertEqual(
                    entry["source"],
                    "seed",
                    f"{pillar} entry missing source='seed'",
                )

    def test_entries_have_uuid_ids(self):
        smm = seed_smm.generate_smm(self.tmpdir)
        seen = set()
        for pillar in smm_schema.PILLARS:
            for entry in smm[pillar]:
                self.assertIn("id", entry)
                self.assertNotIn(entry["id"], seen, "duplicate id")
                seen.add(entry["id"])

    def test_empty_project_has_all_risks(self):
        smm = seed_smm.generate_smm(self.tmpdir)
        contents = [e["content"] for e in smm["risks"]]
        joined = " ".join(contents)
        self.assertIn("No linter configured", joined)
        self.assertIn("No test files detected", joined)
        self.assertIn("No git commit hooks", joined)
        self.assertIn("No CI/CD configured", joined)

    def test_project_with_everything_has_no_risks(self):
        (self.tmpdir / "ruff.toml").touch()
        (self.tmpdir / "tests").mkdir()
        (self.tmpdir / "lefthook.yml").touch()
        (self.tmpdir / ".github" / "workflows").mkdir(parents=True)
        smm = seed_smm.generate_smm(self.tmpdir)
        self.assertEqual(smm["risks"], [])

    def test_has_xp_constraints(self):
        smm = seed_smm.generate_smm(self.tmpdir)
        contents = [e["content"] for e in smm["constraints"]]
        joined = " ".join(contents)
        self.assertIn("TDD", joined)
        self.assertIn("red, green, commit", joined)
        self.assertIn("Small commits", joined)
        self.assertIn("strict linting", joined)

    def test_has_wisdom(self):
        smm = seed_smm.generate_smm(self.tmpdir)
        contents = [e["content"] for e in smm["wisdom"]]
        joined = " ".join(contents)
        self.assertIn("xp-kickoff", joined)

    def test_has_commit_after_green_wisdom(self):
        smm = seed_smm.generate_smm(self.tmpdir)
        contents = [e["content"] for e in smm["wisdom"]]
        joined = " ".join(contents)
        self.assertIn("Commit after every green", joined)

    def test_deterministic_ids(self):
        """Seeded ids are stable across calls (uuid5 from content)."""
        smm1 = seed_smm.generate_smm(self.tmpdir)
        smm2 = seed_smm.generate_smm(self.tmpdir)
        ids1 = {e["id"] for p in smm_schema.PILLARS for e in smm1[p]}
        ids2 = {e["id"] for p in smm_schema.PILLARS for e in smm2[p]}
        self.assertEqual(ids1, ids2)


if __name__ == "__main__":
    unittest.main()
