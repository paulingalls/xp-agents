#!/usr/bin/env python3
"""The lint modules import cleanly from either end.

`linters` (the tables) and `linter_invocation` (the judgement on them) referred to
each other: the invocation module imports the tables, and the tables re-exported the
invocation functions from the bottom of the file. That works only as long as
`linters` happens to be imported FIRST — which every entry point happens to do today.

Import `linter_invocation` first and it raised:

    ImportError: cannot import name '_compile_db_covers' from 'linter_invocation'

In a PreToolUse hook an ImportError exits 1, and the harness treats a non-2 exit as
NON-BLOCKING — so the commit lint gate would not fail closed, it would **fail open**,
and the commit would sail through unlinted. That is the exact failure this release is
named after, sitting in the seam between two modules the release itself created.

The order-dependence is the bug, not the symptom. These run each import in a FRESH
interpreter, because once either module is in `sys.modules` the cycle is invisible.
"""

import subprocess
import sys
import unittest
from pathlib import Path

_SCRIPTS = Path(__file__).parent.parent.parent / "scripts"


def _import_in_fresh_process(statement: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-c", statement],
        cwd=str(_SCRIPTS),
        capture_output=True,
        text=True,
        timeout=60,
    )


class TestTheLintModulesImportFromEitherEnd(unittest.TestCase):
    def test_importing_the_tables_first_works(self):
        """The order production happens to use today."""
        r = _import_in_fresh_process("import linters; linters.linter_argv")

        self.assertEqual(r.returncode, 0, r.stderr)

    def test_importing_the_invocation_module_first_works(self):
        """The order nothing uses today — and the one that used to raise.

        A future hook that reaches for `linter_invocation` directly (it is the module
        that owns the argv, so it is the obvious import) would have taken the gate
        down silently, because the failure mode of an ImportError in a PreToolUse hook
        is not a block: it is a pass.
        """
        r = _import_in_fresh_process(
            "import linter_invocation; linter_invocation.linter_argv"
        )

        self.assertEqual(r.returncode, 0, r.stderr)

    def test_the_re_export_is_still_by_identity(self):
        """Breaking the cycle must not fork the function into two objects: tests and
        callers reach it through `linters`, and a patch on one name has to intercept
        the other."""
        r = _import_in_fresh_process(
            "import linters, linter_invocation;"
            "assert linters.linter_argv is linter_invocation.linter_argv;"
            "assert linters.degrade_reason is linter_invocation.degrade_reason"
        )

        self.assertEqual(r.returncode, 0, r.stderr)


if __name__ == "__main__":
    unittest.main()
