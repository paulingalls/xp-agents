#!/usr/bin/env python3
"""group_paths_by_linter: shared (linter, config) routing, no eligibility filter."""

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent))

import lint_grouping
from _lint_fixtures import _LintTmpDirMixin


class TestGroupPathsByLinter(_LintTmpDirMixin, unittest.TestCase):
    def test_two_ecosystems_group_under_distinct_keys(self):
        root = self._lint_tmpdir
        (root / ".golangci.yml").touch()
        (root / "a.py").touch()
        (root / "b.py").touch()
        (root / "c.go").touch()

        groups = lint_grouping.group_paths_by_linter(
            ["a.py", "b.py", "c.go"], str(root), str(root)
        )

        all_paths = [p for paths in groups.values() for p in paths]
        self.assertEqual(sorted(all_paths), ["a.py", "b.py", "c.go"])
        self.assertEqual(len(groups), 2)
        py_key = next(k for k, v in groups.items() if "a.py" in v)
        go_key = next(k for k, v in groups.items() if "c.go" in v)
        self.assertNotEqual(py_key, go_key)
        self.assertEqual(sorted(groups[py_key]), ["a.py", "b.py"])
        self.assertEqual(groups[go_key], ["c.go"])

    def test_unconfigured_ecosystem_is_absent_from_every_group(self):
        root = self._lint_tmpdir
        (root / "main.rs").touch()

        groups = lint_grouping.group_paths_by_linter(["main.rs"], str(root), str(root))

        all_paths = [p for paths in groups.values() for p in paths]
        self.assertNotIn("main.rs", all_paths)

    def test_paths_absent_from_disk_and_index_are_still_grouped(self):
        root = self._lint_tmpdir

        groups = lint_grouping.group_paths_by_linter(["ghost.py"], str(root), str(root))

        all_paths = [p for paths in groups.values() for p in paths]
        self.assertIn("ghost.py", all_paths)

    def test_patch_seam_is_lint_check_namespace(self):
        with mock.patch("lint_check.detect_linter_config") as mock_detect:
            mock_detect.return_value = ("ruff", "/some/ruff.toml")

            groups = lint_grouping.group_paths_by_linter(
                ["x.py"], str(self._lint_tmpdir), str(self._lint_tmpdir)
            )

            mock_detect.assert_called_once()
            self.assertEqual(groups[("ruff", "/some/ruff.toml")], ["x.py"])

    def test_cwd_is_the_join_base_not_git_root(self):
        """A path is joined to `cwd`, so a nearer config beats the root's one.

        Passing `git_root` for both would start the walk at the root and find
        the root's `ruff.toml` instead.
        """
        root = self._lint_tmpdir
        sub = root / "subproj"
        sub.mkdir()
        (sub / "ruff.toml").touch()
        (sub / "nested.py").touch()

        groups = lint_grouping.group_paths_by_linter(["nested.py"], str(sub), str(root))

        all_paths = [p for paths in groups.values() for p in paths]
        self.assertIn("nested.py", all_paths)
        (config_path,) = {config for (_, config) in groups}
        self.assertEqual(Path(config_path).resolve(), (sub / "ruff.toml").resolve())

    def test_git_root_is_the_walk_ceiling_not_cwd(self):
        """The walk climbs PAST `cwd` to `git_root`, which the sibling above
        cannot see: with a config in `cwd` too, passing `cwd` for both still
        finds one. Here only the root has a config, so a collapsed ceiling
        stops at `sub` and drops the path entirely."""
        root = self._lint_tmpdir
        sub = root / "subproj"
        sub.mkdir()
        (sub / "nested.py").touch()

        groups = lint_grouping.group_paths_by_linter(["nested.py"], str(sub), str(root))

        all_paths = [p for paths in groups.values() for p in paths]
        self.assertIn("nested.py", all_paths)
        (config_path,) = {config for (_, config) in groups}
        self.assertEqual(Path(config_path).resolve(), (root / "ruff.toml").resolve())


if __name__ == "__main__":
    unittest.main()
