#!/usr/bin/env python3
"""Shared harness for pre_tool_write's schedule-gate suites.

Extracted when `test_pre_tool_write_schedule_gate.py` crossed the 500-line cap
for the second time — the same move that produced that file from
`test_pre_tool_write_gates.py`. Two suites now drive the same gate through the
same seams (the scope exemptions, and the merge exemption), and a copied fixture
is how two harnesses come to stub different things and disagree about what the
gate costs.

Lives in `tests/` rather than `tests/hooks/` beside its consumers because that is
where every other shared fixture module lives, and underscore-prefixed names are
the convention inside one (see `_bases._HookTestCase`).
"""

import contextlib
import shutil
import sys
import tempfile
from pathlib import Path
from typing import NamedTuple
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import pre_tool_write
import worktree
from conftest import _HookTestCase, _make_write_input

_STORY_BRANCH = "paulingalls/story-001-schedule-gate"
_FREE_BRANCH = "paulingalls/free-2026-07-13-scratch"


class _Probes(NamedTuple):
    """The two subprocess probes the gate's exemption chain can pay for.

    Both are stubbed on every gate test, not just the ones that assert on them.
    An unstubbed `merge_in_progress` would shell `git rev-parse` against the
    fixture's cwd — a bare mkdtemp — in every gate-window test, which answers
    correctly today only because that directory happens not to be a repo.
    """

    branch: Mock
    merge: Mock


class _ScheduleGateFixture(_HookTestCase):
    """A repo root on disk, plus the two git probes stubbed at their seams.

    The repo lives under `mkdtemp()`, which on macOS hands back a path through
    a symlink (`/var/folders/...` -> `/private/var/folders/...`). That is the
    point, not an accident: `git rev-parse --show-toplevel` returns the PHYSICAL
    root, while the hook builds its target from the payload's `cwd`, which comes
    through the symlink. `_root` and `_cwd` below reproduce exactly that split,
    so a containment check that resolves only one side fails these tests — the
    same trap the schedule-frontier e2e catches against a real git repo.

    The git-root cache is a module global that outlives a test under
    `pytest -n auto`, so clear it on BOTH sides of every test.
    """

    def setUp(self):
        super().setUp()
        worktree._clear_git_root_cache()
        # BUILD the symlink; do not inherit one from the platform.
        #
        # This used to be a bare `mkdtemp()` for `_cwd` and its `.resolve()` for
        # `_root`, which differ ONLY because macOS makes /tmp a symlink into
        # /private/tmp. On Linux they are the same string, so `_cwd == _root`, the
        # guard assertion fired, and CI went red — while the suite stayed green on
        # every developer's Mac. The symlink case was never exercised on the platform
        # CI runs, which is the one that matters: a fixture that depends on the OS's
        # own filesystem layout tests the OS, not the code.
        physical = tempfile.mkdtemp(prefix="xp-gate-repo-")
        link = Path(tempfile.mkdtemp(prefix="xp-gate-link-")) / "repo"
        link.symlink_to(physical, target_is_directory=True)
        self.addCleanup(shutil.rmtree, physical, ignore_errors=True)
        self.addCleanup(shutil.rmtree, link.parent, ignore_errors=True)

        self._cwd = str(link)  # through the symlink, as a hook payload carries it
        self._root = str(Path(physical).resolve())  # physical, as git reports it

    def tearDown(self):
        worktree._clear_git_root_cache()
        super().tearDown()

    @contextlib.contextmanager
    def _probes(self, *, root: str | None, branch: str, merging: bool = False):
        """Stub the git root and both git-state probes at their late-bound seams.

        `merging` defaults to False — no merge in progress — which is the state
        every pre-existing case in this file was written against.
        """
        with (
            patch.object(
                pre_tool_write.worktree, "resolve_git_root", return_value=root
            ),
            patch.object(
                pre_tool_write.identity, "get_current_branch", return_value=branch
            ) as branch_probe,
            patch.object(
                pre_tool_write.identity, "merge_in_progress", return_value=merging
            ) as merge_probe,
        ):
            yield _Probes(branch=branch_probe, merge=merge_probe)

    def _write(self, target: str) -> dict:
        return _make_write_input(
            session_id="t",
            cwd=self._cwd,
            tool_input={"file_path": target, "content": "x"},
        )
