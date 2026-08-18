#!/usr/bin/env python3
"""Pins for guards whose non-match reads as success.

`_WORKTREE_SEGMENT_RE` (`_budget_helpers.py`) and `assert_emitter_under_budgets`'s
missing `normalize_paths` (also `_budget_helpers.py`) were both dead for a whole
release span: a regex written for `/.claude/worktrees/<dir>` stopped matching
once worktrees moved under the data root in v5.0.0, and a normalization helper
never wired in never normalized anything. Neither ever raised — a pattern that
matches nothing and a normalization that normalizes nothing both look exactly
like success. `bff57399` fixed both; this module stops the CLASS from arriving
dead again.

Every specimen here is DERIVED by calling production — `worktree.worktree_path`,
`event_builder.generate_id` — never hand-typed. A hand-typed specimen carries
the same weakness as the guard it pins: when the real shape drifts, the
literal and the pattern go stale TOGETHER and the pin stays green, which is
the exact failure one layer up from the one this module exists to catch (see
the retired `test_measured_len_normalizes_the_real_worktree_layout` in
`test_budget_helpers_shim.py`, folded into `TestWorktreeSegmentGuardIsPinned`).

`_HISTORICAL_ID_RE` is pinned alongside the worktree-segment regex because it
is the same class of defect in a different shape: a DETECTOR whose non-match
reads as "no ids found" — exactly as green as a real absence.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import _append_impl
import _budget_helpers
import event_builder
import worktree
from _repo_fixtures import init_repo

# ---------------------------------------------------------------------------
# Specimens — each derived by calling the real production code path.
# ---------------------------------------------------------------------------


def _out_of_repo_worktree_specimen(
    name: str = "worktree-story-004",
) -> tuple[str, str]:
    """(plain project dir, worktree dir) for the resolvable-SMM placement:
    `{base}/{project-id}/worktrees/{name}`, obtained by actually calling
    `worktree.worktree_path` with a resolvable `SMM_DIR`."""
    with tempfile.TemporaryDirectory() as base:
        smm = Path(base) / "proj-abc" / "smm"
        smm.mkdir(parents=True)
        worktree._clear_git_root_cache()
        with patch.dict(os.environ, {"SMM_DIR": str(smm)}):
            wt = worktree.worktree_path(name, base)
        plain = smm.resolve().parent
        return str(plain), str(wt)


def _legacy_in_repo_worktree_specimen(
    name: str = "worktree-story-004",
) -> tuple[str, str]:
    """(plain git root, worktree dir) for the legacy in-repo placement:
    `{git_root}/.claude/worktrees/{name}`, reached by forcing
    `resolve_smm_dir()` to return None so `worktree_path` falls back."""
    with tempfile.TemporaryDirectory() as repo:
        init_repo(repo)
        worktree._clear_git_root_cache()
        with patch.object(_append_impl, "resolve_smm_dir", return_value=None):
            wt = worktree.worktree_path(name, repo)
        git_root = worktree.resolve_git_root(repo)
        assert git_root is not None
        return git_root, str(wt)


# ---------------------------------------------------------------------------
# Increment 1 — the registry's first two entries.
# ---------------------------------------------------------------------------


class TestWorktreeSegmentGuardIsPinned(unittest.TestCase):
    """`_WORKTREE_SEGMENT_RE` must match BOTH placements `worktree_path` can
    produce. It shipped `.claude/`-only, which matched neither for the whole
    span between the v5.0.0 data-root move and `bff57399` — every emitter
    budget measured longer inside a teammate worktree than in the main
    checkout, purely from path length, and cost two teammates a
    misdiagnosis each in one session.
    """

    def test_matches_the_out_of_repo_placement(self):
        _plain, wt = _out_of_repo_worktree_specimen()
        text = f"cwd={wt}/smm\n"
        self.assertRegex(text, _budget_helpers._WORKTREE_SEGMENT_RE)

    def test_matches_the_legacy_in_repo_placement(self):
        _plain, wt = _legacy_in_repo_worktree_specimen()
        text = f"cwd={wt}/smm\n"
        self.assertRegex(text, _budget_helpers._WORKTREE_SEGMENT_RE)


class TestHistoricalIdGuardIsPinned(unittest.TestCase):
    """`_HISTORICAL_ID_RE` is a DETECTOR, not a normalization: a non-match
    reports "no ids found", which reads exactly as green as a real absence.
    Pinned against an id taken from the generator, not typed — a hand-typed
    hex string can drift from whatever `generate_id` actually produces
    without either side noticing.
    """

    def test_matches_a_real_generated_id(self):
        real_id = event_builder.generate_id()
        text = f"See concern {real_id} for background.\n"
        match = _budget_helpers._HISTORICAL_ID_RE.search(text)
        self.assertIsNotNone(match, f"did not match a real generated id: {real_id!r}")
        assert match is not None
        self.assertEqual(match.group(0), real_id)


if __name__ == "__main__":
    unittest.main()
