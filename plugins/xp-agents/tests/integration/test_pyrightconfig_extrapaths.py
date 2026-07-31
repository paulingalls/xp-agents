#!/usr/bin/env python3
"""Drift guard for pyrightconfig.json's path lists (`extraPaths`, `include`).

Pyright resolves imports against `extraPaths`. The list rots in two
directions: dead entries (path removed but listing kept) silently mask real
import errors, and missing entries (new skill scripts/ dir not added)
produce false-positive `reportMissingImports`. This test reconciles the
declared list with the filesystem in both directions.

Two configs to keep in sync (pyright lacks `extends` across cwds, so the
repo-root config duplicates the plugin-local one with prefixes for IDE
language-server discovery from the repo root). Both are validated here:
plugin-local entries are relative to `plugins/xp-agents/`; root-config
entries are relative to the repo root.
"""

import json
import unittest
from pathlib import Path

from conftest import _PLUGIN_ROOT

_PLUGIN_PYRIGHT_CONFIG = _PLUGIN_ROOT / "pyrightconfig.json"
_REPO_ROOT = _PLUGIN_ROOT.parent.parent
_ROOT_PYRIGHT_CONFIG = _REPO_ROOT / "pyrightconfig.json"
_SKILLS_DIR = _PLUGIN_ROOT / "skills"


def _load_paths(config_path: Path, key: str) -> list[str]:
    config = json.loads(config_path.read_text())
    return config[key]


def _load_extra_paths(config_path: Path) -> list[str]:
    return _load_paths(config_path, "extraPaths")


def _has_direct_py_files(directory: Path) -> bool:
    return any(directory.glob("*.py"))


class TestPyrightExtraPathsDriftGuard(unittest.TestCase):
    def _check_paths_resolve(self, base: Path, entries: list[str]) -> list[str]:
        violations = []
        for entry in entries:
            target = base / entry
            if not target.is_dir():
                violations.append(f"{entry!r}: not a directory (resolved to {target})")
                continue
            if not _has_direct_py_files(target):
                violations.append(
                    f"{entry!r}: contains no .py files — dead entry, remove it"
                )
        return violations

    def test_every_declared_extra_path_is_a_real_dir_with_py_files(self):
        # Plugin-local config: entries relative to plugins/xp-agents/.
        violations = self._check_paths_resolve(
            _PLUGIN_ROOT, _load_extra_paths(_PLUGIN_PYRIGHT_CONFIG)
        )
        self.assertFalse(
            violations,
            "plugins/xp-agents/pyrightconfig.json:extraPaths drift:\n  "
            + "\n  ".join(violations),
        )

    def test_root_config_extra_paths_resolve(self):
        # Root config: entries relative to repo root, prefixed with
        # plugins/xp-agents/. Same drift modes as the plugin-local config.
        violations = self._check_paths_resolve(
            _REPO_ROOT, _load_extra_paths(_ROOT_PYRIGHT_CONFIG)
        )
        self.assertFalse(
            violations,
            "repo-root pyrightconfig.json:extraPaths drift:\n  "
            + "\n  ".join(violations),
        )

    def test_root_and_plugin_extra_paths_stay_in_sync(self):
        self._assert_key_in_sync("extraPaths")

    def test_root_and_plugin_include_stay_in_sync(self):
        # `include` drifts with worse consequences than `extraPaths`: it is the
        # set pyright CHECKS. The commit gate runs pyright with
        # `root: plugins/xp-agents/`, so it reads the plugin-local config —
        # a dir added to the root config alone is checked by editors and by
        # nothing that gates a commit.
        self._assert_key_in_sync("include")

    def _assert_key_in_sync(self, key: str):
        # The two configs MUST list the same logical paths (root-config
        # entries are just plugin-local entries with `plugins/xp-agents/`
        # prepended). Keeping them in sync prevents IDE-vs-CLI diagnostic
        # divergence: an import error caught by one config but masked by
        # the other is a worst-case false-pass.
        plugin_paths = set(_load_paths(_PLUGIN_PYRIGHT_CONFIG, key))
        root_paths = set(_load_paths(_ROOT_PYRIGHT_CONFIG, key))
        prefix = "plugins/xp-agents/"
        derived_from_root = {
            p[len(prefix) :] for p in root_paths if p.startswith(prefix)
        }
        non_prefixed = {p for p in root_paths if not p.startswith(prefix)}
        self.assertFalse(
            non_prefixed,
            f"repo-root pyrightconfig.json {key} entries must all start with "
            f"{prefix!r}; offending entries: {non_prefixed}",
        )
        self.assertEqual(
            plugin_paths,
            derived_from_root,
            f"pyrightconfig.json {key} drift between plugin-local and "
            f"repo-root configs.\n  plugin-only: {plugin_paths - derived_from_root}"
            f"\n  root-only:   {derived_from_root - plugin_paths}",
        )

    def test_every_skill_scripts_dir_with_py_files_is_declared(self):
        declared = set(_load_extra_paths(_PLUGIN_PYRIGHT_CONFIG))
        missing = []
        for scripts_dir in sorted(_SKILLS_DIR.glob("*/scripts")):
            if not scripts_dir.is_dir():
                continue
            if not _has_direct_py_files(scripts_dir):
                continue
            relative = scripts_dir.relative_to(_PLUGIN_ROOT).as_posix()
            if relative not in declared:
                missing.append(relative)
        self.assertFalse(
            missing,
            "skill scripts dirs with .py files missing from "
            "pyrightconfig.json:extraPaths:\n  " + "\n  ".join(missing),
        )


if __name__ == "__main__":
    unittest.main()
