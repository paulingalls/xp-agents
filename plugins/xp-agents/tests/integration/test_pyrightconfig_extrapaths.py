#!/usr/bin/env python3
"""Drift guard for pyrightconfig.json:extraPaths.

Pyright resolves imports against `extraPaths`. The list rots in two
directions: dead entries (path removed but listing kept) silently mask real
import errors, and missing entries (new skill scripts/ dir not added)
produce false-positive `reportMissingImports`. This test reconciles the
declared list with the filesystem in both directions.
"""

import json
import unittest
from pathlib import Path

from conftest import _PLUGIN_ROOT

_PYRIGHT_CONFIG = _PLUGIN_ROOT / "pyrightconfig.json"
_SKILLS_DIR = _PLUGIN_ROOT / "skills"


def _load_extra_paths() -> list[str]:
    config = json.loads(_PYRIGHT_CONFIG.read_text())
    return config["extraPaths"]


def _has_direct_py_files(directory: Path) -> bool:
    return any(directory.glob("*.py"))


class TestPyrightExtraPathsDriftGuard(unittest.TestCase):
    def test_every_declared_extra_path_is_a_real_dir_with_py_files(self):
        # Aggregate so a single dead entry doesn't hide the rest.
        violations = []
        for entry in _load_extra_paths():
            target = _PLUGIN_ROOT / entry
            if not target.is_dir():
                violations.append(f"{entry!r}: not a directory (resolved to {target})")
                continue
            if not _has_direct_py_files(target):
                violations.append(
                    f"{entry!r}: contains no .py files — dead entry, remove it"
                )
        self.assertFalse(
            violations,
            "pyrightconfig.json:extraPaths drift:\n  " + "\n  ".join(violations),
        )

    def test_every_skill_scripts_dir_with_py_files_is_declared(self):
        declared = set(_load_extra_paths())
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
