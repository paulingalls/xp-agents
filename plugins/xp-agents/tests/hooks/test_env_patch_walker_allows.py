#!/usr/bin/env python3
"""The safe rows the env-patch-cleanup walker must NOT flag (AC#3, AC#4).

The pin is fail-closed: anything not matching an enumerated safe row is flagged.
That makes these the load-bearing half of the walker's proof -- without them a
scanner that flags every `patch.dict(os.environ, ...)` would look correct, and
the pin would be unusable noise on a tree that is already compliant.

The `self._p = patch.dict(...)` rows carry the discriminator: `.stop()` must be
CALLED inside a `tearDown`, not merely handed to `addCleanup`, which fires after
`tearDown` and is exactly the bug. Its counterpart is
`test_env_patch_walker_flags.py`.
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

from _env_patch_walker import _scan_file


class TestWalkerIgnoresSafeShapes(unittest.TestCase):
    def test_ignores_with_single_item(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td) / "test_clean.py"
            tmp.write_text(
                "import os\n"
                "import unittest\n"
                "from unittest.mock import patch\n"
                "class T(unittest.TestCase):\n"
                "    def test_x(self):\n"
                '        with patch.dict(os.environ, {"X": "1"}):\n'
                "            pass\n"
            )
            self.assertEqual(_scan_file(tmp), [])

    def test_ignores_with_multi_item_form(self) -> None:
        """Reconstructs test_lead_gates.py:296 / test_identity.py:465's
        `with (patch.dict(os.environ, ...), other()):` shape -- a naive
        implementation that only checks `With.items[0]` breaks here."""
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td) / "test_clean.py"
            tmp.write_text(
                "import os\n"
                "import unittest\n"
                "from unittest.mock import patch\n"
                "class T(unittest.TestCase):\n"
                "    def test_x(self):\n"
                "        with (\n"
                '            patch.dict(os.environ, {"X": "1"}, clear=False),\n'
                "            self._spawned(),\n"
                "        ):\n"
                "            pass\n"
            )
            self.assertEqual(_scan_file(tmp), [])

    def test_ignores_decorator(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td) / "test_clean.py"
            tmp.write_text(
                "import os\n"
                "import unittest\n"
                "from unittest.mock import patch\n"
                "class T(unittest.TestCase):\n"
                '    @patch.dict(os.environ, {"X": "1"})\n'
                "    def test_x(self):\n"
                "        pass\n"
            )
            self.assertEqual(_scan_file(tmp), [])

    def test_ignores_class_level_decorator(self) -> None:
        """mock's `decorate_class` wraps each `test*` method, so a class-level
        `@patch.dict(os.environ, ...)` restores inside each test -- setUp and
        tearDown never see the patched values. Flagging it would fail a safe
        idiom with a message claiming it is not a decorator."""
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td) / "test_clean.py"
            tmp.write_text(
                "import os\n"
                "import unittest\n"
                "from unittest.mock import patch\n"
                '@patch.dict(os.environ, {"X": "1"})\n'
                "class T(unittest.TestCase):\n"
                "    def test_x(self):\n"
                "        pass\n"
            )
            self.assertEqual(_scan_file(tmp), [])

    def test_ignores_annotated_self_attr_with_teardown_stop(self) -> None:
        """The safe self.<attr> row must survive an annotation: `self._p: X =`
        parses as AnnAssign, not Assign, and matching only Assign would flag
        the identical safe lifecycle."""
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td) / "test_clean.py"
            tmp.write_text(
                "import os\n"
                "import unittest\n"
                "from typing import Any\n"
                "from unittest.mock import patch\n"
                "class T(unittest.TestCase):\n"
                "    def setUp(self):\n"
                '        self._p: Any = patch.dict(os.environ, {"X": "1"})\n'
                "        self._p.start()\n"
                "    def tearDown(self):\n"
                "        self._p.stop()\n"
                "    def test_x(self):\n"
                "        pass\n"
            )
            self.assertEqual(_scan_file(tmp), [])

    def test_flags_annotated_self_attr_without_teardown_stop(self) -> None:
        """Negative control for the row above -- the annotation must not by
        itself buy a pass."""
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td) / "test_violation.py"
            tmp.write_text(
                "import os\n"
                "import unittest\n"
                "from typing import Any\n"
                "from unittest.mock import patch\n"
                "class T(unittest.TestCase):\n"
                "    def setUp(self):\n"
                '        self._p: Any = patch.dict(os.environ, {"X": "1"})\n'
                "        self._p.start()\n"
                "    def test_x(self):\n"
                "        pass\n"
            )
            violations = _scan_file(tmp)
            self.assertEqual(len(violations), 1)
            self.assertIn("tearDown", violations[0][1])

    def test_ignores_helper_return_consumed_via_with(self) -> None:
        """Reconstructs test_tdd_gate_in_place_teammate.py's `_in_place_env`
        shape: `return patch.dict(...)` consumed via `with self._x():`."""
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td) / "test_clean.py"
            tmp.write_text(
                "import os\n"
                "import unittest\n"
                "from unittest.mock import patch\n"
                "class T(unittest.TestCase):\n"
                "    def _env_patch(self):\n"
                '        return patch.dict(os.environ, {"X": "1"})\n'
                "    def test_x(self):\n"
                "        with self._env_patch():\n"
                "            pass\n"
            )
            self.assertEqual(_scan_file(tmp), [])

    def test_ignores_self_attr_started_in_setup_stopped_in_teardown(self) -> None:
        """AC#4: reconstructs test_worktree_removal.py:137's exact shape --
        `self._p = patch.dict(os.environ, ...)` + `.start()` in setUp,
        `.stop()` called inside tearDown in the same class."""
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td) / "test_clean.py"
            tmp.write_text(
                "import os\n"
                "import unittest\n"
                "from unittest.mock import patch\n"
                "class T(unittest.TestCase):\n"
                "    def setUp(self):\n"
                '        self._smm_patch = patch.dict(os.environ, {"X": "1"})\n'
                "        self._smm_patch.start()\n"
                "    def tearDown(self):\n"
                "        self._smm_patch.stop()\n"
                "    def test_x(self):\n"
                "        pass\n"
            )
            self.assertEqual(_scan_file(tmp), [])

    def test_flags_self_attr_without_teardown_stop(self) -> None:
        """Negative control for the row above: the self.<attr> assignment
        shape alone is not enough -- .stop() must actually be CALLED inside
        tearDown, or it is exactly as unbounded as any other assignment."""
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td) / "test_violation.py"
            tmp.write_text(
                "import os\n"
                "import unittest\n"
                "from unittest.mock import patch\n"
                "class T(unittest.TestCase):\n"
                "    def setUp(self):\n"
                '        self._p = patch.dict(os.environ, {"X": "1"})\n'
                "        self._p.start()\n"
                "    def tearDown(self):\n"
                "        pass\n"
                "    def test_x(self):\n"
                "        pass\n"
            )
            violations = _scan_file(tmp)
            self.assertEqual(len(violations), 1)
            self.assertIn("tearDown", violations[0][1])

    def test_addcleanup_handed_stop_is_still_flagged_not_confused_for_safe_row(
        self,
    ) -> None:
        """The discriminator: handing `self._p.stop` to `addCleanup` (fires
        AFTER tearDown) must not be confused with CALLING `self._p.stop()`
        inside tearDown (the actual safe row)."""
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td) / "test_violation.py"
            tmp.write_text(
                "import os\n"
                "import unittest\n"
                "from unittest.mock import patch\n"
                "class T(unittest.TestCase):\n"
                "    def setUp(self):\n"
                '        self._p = patch.dict(os.environ, {"X": "1"})\n'
                "        self._p.start()\n"
                "        self.addCleanup(self._p.stop)\n"
                "    def test_x(self):\n"
                "        pass\n"
            )
            violations = _scan_file(tmp)
            self.assertEqual(len(violations), 1)
            self.assertIn("tearDown", violations[0][1])


if __name__ == "__main__":
    unittest.main()
