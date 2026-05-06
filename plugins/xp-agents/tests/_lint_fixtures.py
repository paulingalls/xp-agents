#!/usr/bin/env python3
"""Shared lint-test fixtures.

`_LintTmpDirMixin` provides a per-test tmpdir seeded with `ruff.toml` —
the canonical setup for tests that exercise `lint_check.detect_linter_config`,
`lint_check.run`, or any path that walks for a ruff config.

Promoted from an inline copy in `tests/hooks/test_auto_resolve.py` and
13 hand-rolled mkdtemp/ruff.toml/rmtree triples in `tests/hooks/test_lint.py`.
A subclass that needs additional config files (e.g. `eslint.config.js` for
multi-linter detection tests) creates them on top of `self._lint_tmpdir`
in its own `setUp`.

Pinned by `tests/integration/test_conftest_consolidation_pin.py
::test_single_lint_tmpdir_mixin_definition` and
`::test_test_lint_does_not_hand_roll_ruff_toml_tmpdir`.
"""

import shutil
import tempfile
from pathlib import Path

from _test_typing import _MixinBase


class _LintTmpDirMixin(_MixinBase):
    """setUp/tearDown that creates a tmpdir with `ruff.toml` and removes it."""

    def setUp(self):
        super().setUp()
        self._lint_tmpdir = Path(tempfile.mkdtemp())
        (self._lint_tmpdir / "ruff.toml").touch()

    def tearDown(self):
        shutil.rmtree(self._lint_tmpdir, ignore_errors=True)
        super().tearDown()


def _mock_ruff_result(
    returncode: int = 0, stdout: str = "", stderr: str = ""
) -> object:
    """Build a fake `subprocess.CompletedProcess` for `lint_check.subprocess.run`.

    The lint_check tests don't care that it's a real CompletedProcess —
    they just access `.returncode`, `.stdout`, `.stderr`. Hand-rolled
    `type("R", (), {...})()` literals duplicated across ~8 sites in
    test_lint.py and test_lint_detection.py; one helper kills the noise.
    """
    return type(
        "R",
        (),
        {"returncode": returncode, "stdout": stdout, "stderr": stderr},
    )()


__all__ = ["_LintTmpDirMixin", "_mock_ruff_result"]
