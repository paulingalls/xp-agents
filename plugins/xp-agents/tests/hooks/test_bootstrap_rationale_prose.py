#!/usr/bin/env python3
"""The bootstrap's recorded rationale must name BOTH failure modes.

Split from `test_spawn_teammate_bootstrap.py` (500 lines). spike-005 measured the
false-RED as the dominant, loud mode (TS2882, exit 2) and the false-GREEN as
contrived; the docstring and CHANGELOG named only the false-GREEN and called the
bootstrap's absence "not reliably loud", contradicting the SMM risk they were
written from. These assert PROSE, so they group away from the behavioural suites
— a prose assertion sitting among behavioural ones reads as one and gets edited
like one.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from _bootstrap_fixtures import _BootstrapTestCase


class TestBootstrapRationaleNamesBothFailureModes(_BootstrapTestCase):
    """spike-005 measured the false-RED as the DOMINANT, loud mode (TS2882,
    exit 2; bare tests exit 1) and the false-GREEN as contrived/masked. The
    docstring and CHANGELOG previously named only the false-GREEN and called
    the absence "not reliably loud" — self-contradicting SMM risk
    f9afab74c152, which recorded the gate as failing. This pins the correction
    so the record cannot silently regress to the half-story."""

    def test_docstring_names_both_modes_and_drops_stale_phrase(self):
        import worktree_bootstrap

        doc = worktree_bootstrap.run_bootstrap.__doc__ or ""

        self.assertNotIn(
            "not reliably loud",
            doc,
            "the docstring must no longer claim the absence is quiet — "
            "spike-005 measured a loud false-RED as the dominant mode",
        )
        self.assertTrue(
            "TS2882" in doc or "false-RED" in doc or "exit 2" in doc,
            "the docstring must name the measured false-RED mode",
        )
        self.assertIn(
            "permissive",
            doc,
            "the docstring must still explain the false-GREEN mode",
        )

    def test_changelog_drops_stale_false_green_only_framing(self):
        # The entry lives in the v4.x archive since the v5.0 cut split
        # history out of CHANGELOG.md; the pin follows the entry.
        repo_root = Path(__file__).parent.parent.parent.parent.parent
        text = (repo_root / "changelog_pre_v5.md").read_text()

        self.assertNotIn(
            "not reliably loud",
            text,
            "CHANGELOG must not still assert the absence is quiet",
        )
        self.assertTrue(
            "TS2882" in text or "false-RED" in text or "exit 2" in text,
            "CHANGELOG must name the measured false-RED mode, not frame "
            "the false-GREEN as the only failure",
        )


if __name__ == "__main__":
    unittest.main()


if __name__ == "__main__":
    unittest.main()
