#!/usr/bin/env python3
"""Shared worktree-test fixtures.

`_NormalizePathIdentityMixin` stubs `worktree.normalize_path` to identity
in setUp — for tests where canonical path form is incidental and only
set equality on raw paths matters. Tests that assert against the
canonical-form contract itself (e.g. TestFileOverlapNormalization) must
keep their inline patches.

Promoted from an inline copy in `tests/hooks/test_retro_metrics.py` plus
hand-rolled patcher.start()/addCleanup pairs across multiple test files.
The retro flagged 8+ pre-existing copies of the identity stub; this
module is the canonical home for the setUp-mixin variant.

Pinned by `tests/integration/test_conftest_consolidation_pin.py
::test_single_normalize_path_identity_mixin_definition`.

`make_teammate_worktree` is the canonical helper for creating
`.claude/worktrees/worktree-<story-id>` git worktrees in integration
tests. Promoted from per-class methods in test_preload_markers.py +
test_quality_review_preload.py to prevent a 3rd duplicate from
landing in story-007's capstone test.
"""

import os
import subprocess
from pathlib import Path
from unittest.mock import patch

from _test_typing import _MixinBase


class _NormalizePathIdentityMixin(_MixinBase):
    """Stub `worktree.normalize_path` to identity in setUp."""

    def setUp(self):
        super().setUp()
        patcher = patch("worktree.normalize_path", side_effect=lambda p, _cwd: p)
        patcher.start()
        self.addCleanup(patcher.stop)


def make_teammate_worktree(
    repo: Path, story_id: str, branch: str, start_point: str = "HEAD"
) -> Path:
    """Create `.claude/worktrees/worktree-<story_id>` git worktree at `repo`.

    Pass `story_id` with the canonical `story-NNN` prefix so the resulting
    directory name matches `identity._TEAMMATE_PREFIX` (`worktree-story-`).
    `start_point` is the fork point for the new branch (default `HEAD`,
    preserving prior behavior); pass e.g. `"main"` when the test needs the
    worktree to fork from a named ref instead of wherever `repo` currently
    has checked out.
    Returns the absolute realpath as a Path so callers can both .exists()
    and str() it without knowing whether macOS resolved a symlink en route.
    """
    path = repo / ".claude" / "worktrees" / f"worktree-{story_id}"
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "worktree", "add", "-b", branch, str(path), start_point],
        cwd=str(repo),
        capture_output=True,
        check=True,
    )
    return Path(os.path.realpath(str(path)))


__all__ = ["_NormalizePathIdentityMixin", "make_teammate_worktree"]
