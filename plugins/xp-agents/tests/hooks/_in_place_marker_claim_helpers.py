#!/usr/bin/env python3
"""Shared base fixture for the in-place marker claim test siblings.

Not `test_`-prefixed, so pytest/unittest discovery never collects it directly.
Extracted from test_in_place_marker_claim.py at the 500-line ceiling because
`_ClaimTestCase` is used by every claim/rewrite test class, and those classes
landed in different sibling files after the split — duplicating it would let
the copies drift.
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import worktree
from conftest import release_in_place_holds


class _ClaimTestCase(unittest.TestCase):
    """A temp SMM dir, the name under test, and its marker path.

    tearDown gives back any holder lock this process still holds. A claim keeps
    its lock for the LIFE OF THE PROCESS — which is right for a supervisor (it
    then exits) and wrong for a test worker (it runs thousands more tests), so
    without this every claiming test leaks an fd and leaves a flock held on a temp
    dir that is about to be deleted. Registered before the temp dir's own cleanup
    so it runs BEFORE it (addCleanup is LIFO): the release finds its lock files by
    globbing the dir, so it cannot run after the dir is gone.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.smm_dir = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.addCleanup(release_in_place_holds, self.smm_dir)
        self.name = "worktree-story-001"
        self.marker = worktree.in_place_marker_path(self.smm_dir, self.name)
