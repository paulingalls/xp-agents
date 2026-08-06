#!/usr/bin/env python3
"""Tests for seed_detect.py — project feature detection.

Imports `seed_detect` directly rather than reaching it through `seed_smm`'s
re-exported names. Those names are bound in the importer's namespace, so a test
that reached them through `seed_smm` would break on a tidy-up that changed how
`seed_smm` imports, and a future patch of `seed_detect.has_linter` would not
reach `generate_smm` at all while appearing to stub it.
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import seed_detect


class TestDetection(unittest.TestCase):
    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())

    def tearDown(self):
        import shutil

        shutil.rmtree(self.tmpdir)

    def test_no_linter(self):
        self.assertFalse(seed_detect.has_linter(self.tmpdir))

    def test_has_eslintrc(self):
        (self.tmpdir / ".eslintrc.json").touch()
        self.assertTrue(seed_detect.has_linter(self.tmpdir))

    def test_has_ruff_toml(self):
        (self.tmpdir / "ruff.toml").touch()
        self.assertTrue(seed_detect.has_linter(self.tmpdir))

    def test_has_swiftlint(self):
        (self.tmpdir / ".swiftlint.yml").touch()
        self.assertTrue(seed_detect.has_linter(self.tmpdir))

    def test_has_biome(self):
        (self.tmpdir / "biome.json").touch()
        self.assertTrue(seed_detect.has_linter(self.tmpdir))

    def test_pyproject_with_ruff(self):
        (self.tmpdir / "pyproject.toml").write_text("[tool.ruff]\nline-length = 88")
        self.assertTrue(seed_detect.has_linter(self.tmpdir))

    def test_pyproject_without_ruff(self):
        (self.tmpdir / "pyproject.toml").write_text("[project]\nname = 'foo'")
        self.assertFalse(seed_detect.has_linter(self.tmpdir))

    def test_no_tests(self):
        self.assertFalse(seed_detect.has_tests(self.tmpdir))

    def test_has_tests_dir(self):
        (self.tmpdir / "tests").mkdir()
        self.assertTrue(seed_detect.has_tests(self.tmpdir))

    def test_has_test_file(self):
        (self.tmpdir / "test_foo.py").touch()
        self.assertTrue(seed_detect.has_tests(self.tmpdir))

    def test_has_jest_test(self):
        (self.tmpdir / "app.test.ts").touch()
        self.assertTrue(seed_detect.has_tests(self.tmpdir))

    def test_has_swift_test(self):
        (self.tmpdir / "FooTests.swift").touch()
        self.assertTrue(seed_detect.has_tests(self.tmpdir))

    def test_has_src_test(self):
        (self.tmpdir / "src" / "test").mkdir(parents=True)
        self.assertTrue(seed_detect.has_tests(self.tmpdir))

    def test_has_nested_tests_dir(self):
        (self.tmpdir / "packages" / "api" / "tests").mkdir(parents=True)
        self.assertTrue(seed_detect.has_tests(self.tmpdir))

    def test_has_xcode_tests_dir(self):
        (self.tmpdir / "app" / "MyAppTests").mkdir(parents=True)
        self.assertTrue(seed_detect.has_tests(self.tmpdir))

    def test_has_monorepo_src_test(self):
        (self.tmpdir / "packages" / "api" / "src" / "test").mkdir(parents=True)
        self.assertTrue(seed_detect.has_tests(self.tmpdir))

    def test_no_hooks(self):
        self.assertFalse(seed_detect.has_git_hooks(self.tmpdir))

    def test_has_lefthook(self):
        (self.tmpdir / "lefthook.yml").touch()
        self.assertTrue(seed_detect.has_git_hooks(self.tmpdir))

    def test_has_husky(self):
        (self.tmpdir / ".husky").mkdir()
        (self.tmpdir / ".husky" / "pre-commit").write_text("#!/bin/sh\nnpx lint-staged")
        self.assertTrue(seed_detect.has_git_hooks(self.tmpdir))

    def test_has_core_hookspath_override_with_executable_hook(self):
        """`core.hooksPath` pointing at executable hooks counts as configured.

        The case lefthook hits (debt e0743ac82ba9).
        """
        import subprocess

        subprocess.run(
            ["git", "init", "-b", "main", str(self.tmpdir)],
            capture_output=True,
            check=True,
        )
        custom = self.tmpdir / "custom-hooks"
        custom.mkdir()
        hook = custom / "pre-commit"
        hook.write_text("#!/bin/sh\nexit 0\n")
        hook.chmod(0o755)
        subprocess.run(
            ["git", "config", "core.hooksPath", str(custom)],
            cwd=self.tmpdir,
            capture_output=True,
            check=True,
        )
        self.assertTrue(seed_detect.has_git_hooks(self.tmpdir))

    def _write_pre_commit(self, body: str) -> None:
        """A non-executable `.git/hooks/pre-commit` — the intent-only fallback.

        Not chmod +x, so `git_hooks.will_fire_hook` says False and the verdict
        rests entirely on the content check.
        """
        hooks = self.tmpdir / ".git" / "hooks"
        hooks.mkdir(parents=True)
        (hooks / "pre-commit").write_text(body)

    def test_a_non_executable_pre_commit_with_a_body_counts_as_intent(self):
        self._write_pre_commit("#!/bin/sh\nmake test\n")
        self.assertTrue(seed_detect.has_git_hooks(self.tmpdir))

    def test_an_empty_pre_commit_is_not_intent(self):
        """A hook with nothing in it gates no commit, so reading it as
        configured suppresses the ungated-commits risk the seed exists to
        raise."""
        self._write_pre_commit("")
        self.assertFalse(seed_detect.has_git_hooks(self.tmpdir))

    def test_a_shebang_only_pre_commit_is_not_intent(self):
        self._write_pre_commit("#!/bin/sh\n\n")
        self.assertFalse(seed_detect.has_git_hooks(self.tmpdir))

    def test_gits_own_sample_text_is_not_intent(self):
        self._write_pre_commit(
            "#!/bin/sh\n# This hook is invoked by git-commit\nexit 0\n"
        )
        self.assertFalse(seed_detect.has_git_hooks(self.tmpdir))

    def test_no_ci(self):
        self.assertFalse(seed_detect.has_ci(self.tmpdir))

    def test_has_github_actions(self):
        (self.tmpdir / ".github" / "workflows").mkdir(parents=True)
        self.assertTrue(seed_detect.has_ci(self.tmpdir))

    def test_has_gitlab_ci(self):
        (self.tmpdir / ".gitlab-ci.yml").touch()
        self.assertTrue(seed_detect.has_ci(self.tmpdir))


if __name__ == "__main__":
    unittest.main()
