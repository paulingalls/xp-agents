#!/usr/bin/env python3
"""A temp git repo whose SMM may declare a worktree bootstrap.

Shared by the three suites `test_spawn_teammate_bootstrap.py` was split into at
500 lines. Note what `spawn` does NOT do: it calls `create_worktree` directly,
passing `smm_dir` by hand. Only `main()` passes it in production, which is why
one suite still drives `main()` end to end.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import spawn_teammate
from _system_context_fixtures import valid_doc, write_doc
from conftest import _IntegrationTestCase, cleanup_test_worktrees


class _BootstrapTestCase(_IntegrationTestCase):
    """Shared setup: a temp git repo whose SMM may declare a bootstrap."""

    def tearDown(self):
        cleanup_test_worktrees(self.tmpdir)
        super().tearDown()

    def declare_bootstrap(self, command: str) -> None:
        """Declare `stack.worktree_bootstrap` in this repo's system_context."""
        doc = valid_doc()
        doc["stack"]["worktree_bootstrap"] = command
        write_doc(self.smm_dir, doc)

    def spawn(self, name: str = "worktree-story-bootstrap") -> str:
        """create_worktree with this test's SMM dir threaded in."""
        return spawn_teammate.create_worktree(
            name, str(self.tmpdir), smm_dir=self.smm_dir
        )
