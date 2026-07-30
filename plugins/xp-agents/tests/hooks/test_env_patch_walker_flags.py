#!/usr/bin/env python3
"""The shapes the env-patch-cleanup walker FLAGS (AC#1, AC#2, AC#6).

The tree-wide pin in `test_env_patch_cleanup_pin.py` asserts zero violations,
which is indistinguishable from a scanner that never runs. These point the
scanner at synthetic files carrying each unsafe spelling and prove it fires.

Its counterpart is `test_env_patch_walker_allows.py`, which pins the safe rows
the walker must NOT flag. Both are needed: a scanner that flags everything
passes this file and fails that one.
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

from _env_patch_walker import _scan_file


class TestWalkerDetectsViolations(unittest.TestCase):
    def test_detects_entercontext_direct(self) -> None:
        """AC#1: self.enterContext(patch.dict(os.environ, ...)) flags,
        naming file and line."""
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td) / "test_violation.py"
            tmp.write_text(
                "import os\n"
                "import unittest\n"
                "from unittest.mock import patch\n"
                "class T(unittest.TestCase):\n"
                "    def test_x(self):\n"
                '        self.enterContext(patch.dict(os.environ, {"X": "1"}))\n'
            )
            violations = _scan_file(tmp)
            self.assertEqual(len(violations), 1)
            lineno, reason = violations[0]
            self.assertEqual(lineno, 6)
            self.assertIn("enterContext", reason)

    def test_detects_addcleanup_of_local_var_patcher(self) -> None:
        """AC#2: patcher = patch.dict(os.environ, ...); addCleanup(patcher.stop)
        flags -- position-based: assignment to a bare local variable is
        never a safe row, regardless of downstream use."""
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td) / "test_violation.py"
            tmp.write_text(
                "import os\n"
                "import unittest\n"
                "from unittest.mock import patch\n"
                "class T(unittest.TestCase):\n"
                "    def test_x(self):\n"
                '        patcher = patch.dict(os.environ, {"X": "1"})\n'
                "        self.addCleanup(patcher.stop)\n"
            )
            violations = _scan_file(tmp)
            self.assertEqual(len(violations), 1)
            lineno, reason = violations[0]
            self.assertEqual(lineno, 6)
            self.assertIn("local variable", reason)

    def test_detects_bare_expression_statement(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td) / "test_violation.py"
            tmp.write_text(
                "import os\n"
                "import unittest\n"
                "from unittest.mock import patch\n"
                "class T(unittest.TestCase):\n"
                "    def test_x(self):\n"
                '        patch.dict(os.environ, {"X": "1"})\n'
            )
            violations = _scan_file(tmp)
            self.assertEqual(len(violations), 1)
            self.assertEqual(violations[0][0], 6)

    def test_detects_dotted_mock_patch_dict_spelling(self) -> None:
        """11 real call sites use `mock.patch.dict(os.environ, ...)`;
        missing this spelling would miss them."""
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td) / "test_violation.py"
            tmp.write_text(
                "import os\n"
                "import unittest\n"
                "import unittest.mock as mock\n"
                "class T(unittest.TestCase):\n"
                "    def test_x(self):\n"
                '        self.enterContext(mock.patch.dict(os.environ, {"X": "1"}))\n'
            )
            violations = _scan_file(tmp)
            self.assertEqual(len(violations), 1)

    def test_detects_string_target_spelling(self) -> None:
        """`patch.dict("os.environ", ...)` is the same patch by a string mock
        imports itself -- matching only the `os.environ` attribute node would
        let the identical leak through under a different spelling."""
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td) / "test_violation.py"
            tmp.write_text(
                "import unittest\n"
                "from unittest.mock import patch\n"
                "class T(unittest.TestCase):\n"
                "    def test_x(self):\n"
                '        self.enterContext(patch.dict("os.environ", {"X": "1"}))\n'
            )
            violations = _scan_file(tmp)
            self.assertEqual(len(violations), 1)
            self.assertIn("enterContext", violations[0][1])

    def test_detects_in_dict_keyword_spelling(self) -> None:
        """`patch.dict`'s mapping can be passed by keyword; reading only
        `args[0]` would see no arguments at all and pass the file clean."""
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td) / "test_violation.py"
            tmp.write_text(
                "import os\n"
                "import unittest\n"
                "from unittest.mock import patch\n"
                "class T(unittest.TestCase):\n"
                "    def test_x(self):\n"
                "        self.enterContext(\n"
                '            patch.dict(in_dict=os.environ, values={"X": "1"})\n'
                "        )\n"
            )
            violations = _scan_file(tmp)
            self.assertEqual(len(violations), 1)
            self.assertIn("enterContext", violations[0][1])

    def test_detects_entercontext_on_helper_returning_patcher(self) -> None:
        """AC#6: a helper whose returned patcher is passed to enterContext
        is flagged -- the helper's own `return` is safe on its own, but the
        caller's indirection through enterContext is not."""
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td) / "test_violation.py"
            tmp.write_text(
                "import os\n"
                "import unittest\n"
                "from unittest.mock import patch\n"
                "class T(unittest.TestCase):\n"
                "    def _env_patch(self):\n"
                '        return patch.dict(os.environ, {"X": "1"})\n'
                "    def test_x(self):\n"
                "        self.enterContext(self._env_patch())\n"
            )
            violations = _scan_file(tmp)
            self.assertEqual(len(violations), 1)
            lineno, reason = violations[0]
            self.assertEqual(lineno, 8)
            self.assertIn("_env_patch", reason)

    def test_ignores_patch_dict_on_other_mapping(self) -> None:
        """patch.dict(some_other_dict, ...) is out of scope entirely."""
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td) / "test_clean.py"
            tmp.write_text(
                "import unittest\n"
                "from unittest.mock import patch\n"
                "class T(unittest.TestCase):\n"
                "    def test_x(self):\n"
                '        self.enterContext(patch.dict({"a": "1"}, {"a": "2"}))\n'
            )
            self.assertEqual(_scan_file(tmp), [])

    def test_detects_aliased_patch_import(self) -> None:
        """`from unittest.mock import patch as p` then `p.dict(os.environ,
        ...)` is flagged -- the matcher must not be keyed on the literal
        name `patch`."""
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td) / "test_violation.py"
            tmp.write_text(
                "import os\n"
                "import unittest\n"
                "from unittest.mock import patch as p\n"
                "class T(unittest.TestCase):\n"
                "    def test_x(self):\n"
                '        self.enterContext(p.dict(os.environ, {"X": "1"}))\n'
            )
            violations = _scan_file(tmp)
            self.assertEqual(len(violations), 1)
            lineno, reason = violations[0]
            self.assertEqual(lineno, 6)
            self.assertIn("enterContext", reason)


if __name__ == "__main__":
    unittest.main()
