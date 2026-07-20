#!/usr/bin/env python3
"""Shared fixtures for the mark-done merge gate tests.

Split from test_story_done_gate.py (was 539 lines) when it crossed the
500-line cap. `_GateCase` (a real git repo plus a sprint whose story names a
real branch) and its supporting constants are shared by both siblings:
test_story_done_gate_bash_hook.py (the regex-driven `pre_tool_bash` gate) and
test_story_done_gate_engine_backstop.py (the same proof, driven straight
through `sprint_cli.py`, below the shell).
"""

import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import pre_tool_bash
import sprint_store
from _branching_fixtures import append_commit, init_repo, write_system_context
from conftest import _HookTestCase, _make_bash_input

_BASE = "main"
_STORY_BRANCH = "paulingalls/story-001-thing"
_CLI = Path(__file__).parent.parent.parent / "smm" / "sprint_cli.py"


def _done_cmd(story_id: str = "story-001", extra: str = "") -> str:
    return (
        f"python3 /path/to/sprint_cli.py --smm-dir /tmp/smm "
        f"update-story {story_id} done{extra}"
    )


class _GateCase(_HookTestCase):
    """A real git repo plus a sprint whose story names a real branch."""

    def setUp(self):
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.repo = self._tmp.name
        init_repo(self.repo)
        write_system_context(self.smm_dir, 2)

    # -- fixture helpers ---------------------------------------------------

    def _git(self, *args: str) -> None:
        subprocess.run(["git", *args], cwd=self.repo, capture_output=True, check=True)

    def _unmerged_story_branch(self) -> None:
        """A story branch holding a commit the base does not have."""
        self._git("checkout", "-b", _STORY_BRANCH)
        append_commit(self.repo, "story.txt")
        self._git("checkout", _BASE)

    def _story(
        self,
        story_id: str = "story-001",
        *,
        status: str = "closing",
        branch: str | None = _STORY_BRANCH,
    ) -> dict:
        story = {
            "id": story_id,
            "title": "Test",
            "status": status,
            "dependencies": [],
            "milestone_ref": "test",
            "design_sources": "test",
            "context": "test",
            "file_domain": [],
            "interface_contracts": [],
            "acceptance_criteria": ["test"],
        }
        if branch is not None:
            story["branch_name"] = branch
        return story

    def _seed_stories(self, *stories: dict) -> None:
        sprint_store.save_sprint(
            self.smm_dir,
            {
                "sprint_id": "sprint-001",
                "goal": "g",
                "started": "2026-04-22",
                "milestone": "test",
                "branch_name": _BASE,
                "stories": list(stories),
            },
        )

    def _seed_sprint(
        self, *, status: str = "closing", branch: str | None = _STORY_BRANCH
    ):
        self._seed_stories(self._story(status=status, branch=branch))

    def _run(self, cmd: str):
        return pre_tool_bash.run(
            _make_bash_input(command=cmd, cwd=self.repo), smm_dir=self.smm_dir
        )
