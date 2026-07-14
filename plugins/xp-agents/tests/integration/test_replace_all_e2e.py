#!/usr/bin/env python3
"""Story-018 capstone: AC4 multi-file replace_all E2E.

Drives the real hook chain (pre_tool_write -> lint_check -> pre_tool_bash)
over a 3-edit migration where ``import re`` is added to file_a.py before it
has any consumer, then file_b.py grows the call site, then file_a.py is
completed. Between edits 1 and 3 the ``import re`` in file_a.py is locally
unused -- ruff would emit F401 if the edit-time deferral filter
(``lint_check.run_ruff``, which drops EDIT_DEFERRED_CODES) weren't engaged.

Pins story-007 AC4 ("E2E multi-file replace_all migration with imports
added then consumed -> no stale F401"). Existing unit slices cover the
contract piecewise; this test wires them together end-to-end so a
regression that re-routes either hook past the deferral filter -- or
flips ``EDIT_DEFERRED_CODES`` -- breaks here, not just in
``test_lint`` / ``test_pre_tool_bash``.

Skipped when ``ruff`` isn't on PATH; without it the commit gate cannot read
anything (it fails closed as unverified) and an absent-F401 assertion would
pass for the wrong reason.
"""

import shutil
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import markers
from conftest import _IntegrationTestCase, _make_bash_input
from event_helpers import events_of_type
from event_schema import EVENT_TYPE_CONCERN

# Pre-satisfy the simplify/quality gates so the commit-time check focuses
# on the staging-time ruff path the AC actually exercises. Two staged .py
# files cross commits.REVIEW_CYCLE_THRESHOLD; without this the simplify
# gate would block first and mask the F401 outcome under test.
_REVIEW_DONE = dict(markers._DEFAULT_REVIEW_CYCLE) | {
    "simplify_done": True,
    "quality_review_done": True,
}


class TestReplaceAllMultiFileE2E(_IntegrationTestCase):
    """End-to-end: edit-time deferral + staging-time gate, real ruff."""

    def setUp(self):
        super().setUp()
        if not shutil.which("ruff"):
            self.skipTest("ruff not on PATH; staging gate would no-op")
        # Default-rule ruff config so detect_linter_config picks ruff.
        (self.tmpdir / "ruff.toml").write_text("[lint]\n")

    def _drive_edit(self, name: str, content: str) -> None:
        """Simulate an Edit: PreToolUse hook, write to disk, PostToolUse hook.

        Both hooks must exit 0 -- a non-zero return would mean the live
        chain blocked the edit, which the AC forbids for F401.
        """
        path = self.tmpdir / name
        edit_input = {
            "session_id": "int-test",
            "tool_name": "Edit",
            "tool_input": {
                "file_path": str(path),
                "old_string": "",
                "new_string": content,
            },
            "cwd": str(self.tmpdir),
            "agent_id": "main",
        }
        pre = self._run_script("pre_tool_write.py", edit_input)
        self.assertEqual(pre.returncode, 0, f"pre_tool_write blocked: {pre.stderr}")

        path.write_text(content)

        post_input = {
            "session_id": "int-test",
            "tool_name": "Edit",
            "tool_input": {"file_path": str(path)},
            "cwd": str(self.tmpdir),
            "agent_id": "main",
        }
        post = self._run_script("lint_check.py", post_input)
        self.assertEqual(post.returncode, 0, f"lint_check failed: {post.stderr}")

    def _f401_concerns(self) -> list[dict]:
        return [
            e
            for e in events_of_type(self._read_events(), EVENT_TYPE_CONCERN)
            if "F401" in e.get("content", "")
        ]

    def test_multi_file_replace_all_no_stale_F401(self):
        """AC1-4: import added to file_a, consumed in file_b, then completed
        in file_a. No F401 concern at any edit; commit hook does not block.
        """
        # Edit 1: introduce `import re` in file_a.py. Locally unused --
        # ruff(edit) must filter F401, otherwise a stale concern lands.
        self._drive_edit("file_a.py", "import re\n")

        # Edit 2: file_b.py is self-contained -- realistic second step of
        # a multi-file migration but not itself a F401 candidate.
        self._drive_edit("file_b.py", "import re\n\nre.match('x', 'y')\n")

        # Edit 3: file_a.py completes the migration. Now uses re itself.
        self._drive_edit("file_a.py", "import re\n\nre.compile('x')\n")

        # AC1 + AC4: zero F401 concerns recorded across the edit chain.
        self.assertEqual(
            self._f401_concerns(),
            [],
            "Stale F401 concern emitted at edit time -- "
            "EDIT_DEFERRED_CODES filter is not engaged.",
        )

        # Stage both files for the commit-time gate.
        markers.write_review_cycle(self.smm_dir, "main", _REVIEW_DONE)
        subprocess.run(
            ["git", "add", "file_a.py", "file_b.py"],
            cwd=self.tmpdir,
            capture_output=True,
            check=True,
        )

        # AC2 + AC3: pre_tool_bash on `git commit` runs ruff(staging) over
        # the staged .py files. Both are now F401-clean -- gate must pass.
        commit_result = self._run_script(
            "pre_tool_bash.py",
            _make_bash_input(
                command="git commit -m 'replace_all migration'",
                cwd=str(self.tmpdir),
            ),
        )
        self.assertEqual(
            commit_result.returncode,
            0,
            f"Commit hook blocked clean migration; stderr: {commit_result.stderr}",
        )
        self.assertNotIn("F401", commit_result.stderr)


if __name__ == "__main__":
    unittest.main()
