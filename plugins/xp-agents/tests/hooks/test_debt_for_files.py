#!/usr/bin/env python3
"""Tests for the xp-quality-review debt_for_files preload script.

Pins the resolution-awareness contract: a concern/debt resolved by an
earlier commit/decision must NOT resurface in the "Debt for Changed Files"
section just because a later diff touches the same file (regression for
db3f978251d6, which kept reappearing across commits).
"""

import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(
    0,
    str(
        Path(__file__).parent.parent.parent / "skills" / "xp-quality-review" / "scripts"
    ),
)
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

import _common
import debt_for_files
from conftest import _SMMTestCase, make_event
from event_schema import EVENT_TYPE_CONCERN, EVENT_TYPE_DECISION


class TestDebtForFiles(_SMMTestCase):
    def _run(self, *files: str) -> str:
        argv = ["debt_for_files", "--smm-dir", str(self.smm_dir), *files]
        buf = io.StringIO()
        with patch.object(sys, "argv", argv), redirect_stdout(buf):
            debt_for_files.main()
        return buf.getvalue()

    def test_open_concern_for_file_is_shown(self):
        concern = make_event(
            EVENT_TYPE_CONCERN, content="auth bug", files=["scripts/auth.py"]
        )
        _common.append_safe(self.smm_dir, concern)
        out = self._run("scripts/auth.py")
        self.assertIn(concern["id"], out)

    def test_resolved_concern_for_file_is_excluded(self):
        """A concern resolved by a prior decision must not resurface."""
        concern = make_event(
            EVENT_TYPE_CONCERN, content="auth bug", files=["scripts/auth.py"]
        )
        _common.append_safe(self.smm_dir, concern)
        decision = make_event(
            EVENT_TYPE_DECISION,
            content="fix auth",
            topic="auth",
            metadata={"resolves": [concern["id"]]},
        )
        _common.append_safe(self.smm_dir, decision)
        out = self._run("scripts/auth.py")
        self.assertNotIn(concern["id"], out)


if __name__ == "__main__":
    unittest.main()
