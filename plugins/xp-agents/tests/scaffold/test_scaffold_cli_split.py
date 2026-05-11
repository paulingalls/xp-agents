#!/usr/bin/env python3
"""Pin the scaffold_cli.py / scaffold_cli_apply.py split.

The 7 ``_cmd_apply_*`` callables live in ``scaffold_cli_apply`` after
sprint-082 story-002. ``scaffold_cli`` re-exports them as a shim so
external callers (``from scaffold_cli import _cmd_apply_write``) keep
working without churn.

This pin file exists to catch silent regressions during future edits to
either module — an accidental local re-definition or a missed re-export
trips here in <1s instead of waiting for a downstream cascade.
"""

import importlib
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

_APPLY_FN_NAMES = (
    "_cmd_apply_write",
    "_cmd_apply_install",
    "_cmd_apply_verify_identity",
    "_cmd_apply_verify",
    "_cmd_apply_revert",
    "_cmd_apply_commit",
    "_cmd_apply_record",
)

_SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
_SCAFFOLD_CLI = _SCRIPTS_DIR / "scaffold_cli.py"
_SCAFFOLD_CLI_APPLY = _SCRIPTS_DIR / "scaffold_cli_apply.py"


class TestScaffoldCliSplit(unittest.TestCase):
    def test_apply_module_importable(self) -> None:
        """scaffold_cli_apply exists as a standalone module."""
        mod = importlib.import_module("scaffold_cli_apply")
        for name in _APPLY_FN_NAMES:
            with self.subTest(name=name):
                fn = getattr(mod, name, None)
                self.assertIsNotNone(
                    fn, f"{name} must be defined in scaffold_cli_apply"
                )
                self.assertTrue(callable(fn), f"{name} must be callable")

    def test_scaffold_cli_reexports_apply_funcs(self) -> None:
        """scaffold_cli re-exports each _cmd_apply_* via a shim import.

        ``from scaffold_cli import _cmd_apply_write`` must still resolve so
        callers (dispatch table, direct imports in tests) don't break.
        """
        cli = importlib.import_module("scaffold_cli")
        apply_mod = importlib.import_module("scaffold_cli_apply")
        for name in _APPLY_FN_NAMES:
            with self.subTest(name=name):
                shim = getattr(cli, name, None)
                self.assertIsNotNone(shim, f"scaffold_cli must re-export {name}")
                # Identity check — re-export, not a wrapper or a re-definition.
                self.assertIs(
                    shim,
                    getattr(apply_mod, name),
                    f"{name} on scaffold_cli must be the same object as on "
                    f"scaffold_cli_apply (re-export, not a local copy)",
                )

    def test_scaffold_cli_under_500_lines(self) -> None:
        """The whole point of the split — keep scaffold_cli under the budget."""
        line_count = sum(1 for _ in _SCAFFOLD_CLI.read_text().splitlines())
        self.assertLess(
            line_count,
            500,
            f"scaffold_cli.py is {line_count} lines — extract more into "
            f"scaffold_cli_apply.py",
        )

    def test_scaffold_cli_apply_under_500_lines(self) -> None:
        """Symmetric budget — extracting into a sibling that itself busts the
        budget would just defer the next split. Both modules earn their keep
        only if both stay under 500 lines."""
        line_count = sum(1 for _ in _SCAFFOLD_CLI_APPLY.read_text().splitlines())
        self.assertLess(
            line_count,
            500,
            f"scaffold_cli_apply.py is {line_count} lines — extract a "
            f"cohesive group of phases into a third module",
        )


if __name__ == "__main__":
    unittest.main()
