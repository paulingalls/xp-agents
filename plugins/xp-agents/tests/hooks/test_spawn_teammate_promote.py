#!/usr/bin/env python3
"""Mechanical promote-to-reviewing on clean teammate exit (split from
test_spawn_teammate.py per the max-500 rule).

spawn_teammate.main() CAS-promotes a story in-progress -> reviewing after a
clean run (rc=0), and leaves it in-progress on rc!=0 / filter-died-before-report
so the orchestrator can re-spawn. This suite pins that lifecycle; the sibling
test_spawn_teammate.py keeps build_command, story-assignment, and name
pass-through.
"""

import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from conftest import _SMMTestCase


class TestMechanicalPromote(_SMMTestCase):
    """Story-004: spawn_teammate.main() promotes the story to `reviewing`
    after a clean teammate exit (rc=0). On rc!=0 the teammate stays
    `in-progress` for debug. The promote is mechanical — no LLM
    judgment, no prompt-template instruction; the wrapper does it.

    Story-002 (sprint-068): the get_story → update_story_status pair
    was replaced with a single atomic update_story_status_if CAS —
    these tests assert against the CAS callsite, not the legacy pair.
    """

    def _make_prompt_file(self, story_id: str | None):
        """A prompt naming *story_id* — spawn refuses one that does not name the
        story it is spawning (story-014: prompt files outlive their story and
        story ids repeat every sprint), so a bare "body" never reaches the
        promote this class is about."""
        import tempfile

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".prompt.txt", delete=False
        ) as f:
            f.write(f"body for {story_id}" if story_id else "ad-hoc body")
            return f.name

    def _run_promote(
        self,
        *,
        story_id: str | None = "story-001",
        cas_return: bool = True,
        run_with_tee_side_effect=None,
        run_with_tee_return: bool = False,
        report_exists: bool = False,
    ) -> list[tuple[str, str, str, str]]:
        """Run spawn_teammate.main with stubbed worktree+subprocess+sprint
        and return the captured update_story_status_if calls as
        (smm_dir, story_id, expected, new) tuples.

        story_id=None omits --story-id (ad-hoc teammate).
        cas_return controls what the patched CAS returns (True=updated,
        False=expected mismatch — actual already advanced past expected).
        run_with_tee_side_effect raises if you want rc!=0 simulation.
        run_with_tee_return is run_with_tee's stdout_broken flag (True means
        the downstream stdout pipe broke).
        report_exists pre-writes the teammate report file so a broken stdout is
        recognised as a benign late pipe-close (the filter wrote its report
        before exiting) rather than a filter that died before finishing.

        Also records self._prompt_existed_after: whether main() left the prompt
        file on disk (the in-progress ⇒ prompt-preserved-for-re-spawn invariant).
        """
        from unittest.mock import patch

        import spawn_teammate
        import worktree

        prompt_path = self._make_prompt_file(story_id)
        captured_calls: list[tuple[str, str, str, str]] = []
        name = "worktree-story-001" if story_id else "worktree-foo"

        if report_exists:
            worktree.teammate_report_path(self.smm_dir, name).write_text("done")

        def fake_cas(smm_dir, sid, *, expected, new):
            captured_calls.append((str(smm_dir), sid, expected, new))
            return cas_return

        argv = [
            "--name",
            name,
            "--smm-dir",
            str(self.smm_dir),
            "--prompt-file",
            prompt_path,
        ]
        if story_id is not None:
            argv += ["--story-id", story_id]

        try:
            with (
                patch.object(spawn_teammate, "create_worktree", return_value="/tmp/wt"),
                patch.object(
                    spawn_teammate,
                    "run_with_tee",
                    side_effect=run_with_tee_side_effect,
                    return_value=run_with_tee_return,
                ),
                patch.object(
                    spawn_teammate.sprint_store,
                    "update_story_status_if",
                    side_effect=fake_cas,
                ),
            ):
                spawn_teammate.main(argv)
            self._prompt_existed_after = Path(prompt_path).exists()
        finally:
            Path(prompt_path).unlink(missing_ok=True)

        return captured_calls

    def test_promotes_to_reviewing_on_rc_0(self):
        """Successful teammate (rc=0) triggers a single CAS in-progress→reviewing."""
        captured = self._run_promote()
        self.assertEqual(
            captured,
            [(str(self.smm_dir), "story-001", "in-progress", "reviewing")],
            f"expected single CAS call (in-progress→reviewing), got: {captured!r}",
        )

    def test_cas_returns_false_does_not_raise(self):
        """When the CAS sees actual!=expected (concurrent advance to
        done/deferred), spawn_teammate accepts the no-op silently — the
        caller's job was 'try to promote', not 'demand promotion'.
        Pins close-reviewer concern 3ba0b6237c65 end-to-end."""
        captured = self._run_promote(cas_return=False)
        self.assertEqual(
            captured,
            [(str(self.smm_dir), "story-001", "in-progress", "reviewing")],
            "CAS must still be invoked even when it returns False",
        )

    def test_does_not_promote_on_rc_nonzero(self):
        """Failed teammate (rc!=0) leaves story in-progress for debug —
        the CAS is never invoked because the exception propagates first."""
        with self.assertRaises(subprocess.CalledProcessError):
            self._run_promote(
                run_with_tee_side_effect=subprocess.CalledProcessError(2, ["fake"])
            )

    def test_does_not_promote_when_filter_died_before_report(self):
        """Filter death with NO report (stdout_broken=True, report absent) leaves
        the story in-progress: the filter that owns report/completion/
        coordination-clear never finished, so a promote to reviewing would hand
        the lead an unwritten report over stale state. The prompt is preserved
        for re-spawn."""
        captured = self._run_promote(run_with_tee_return=True, report_exists=False)
        self.assertEqual(
            captured,
            [],
            f"CAS must be skipped when the filter died pre-report, got: {captured!r}",
        )
        self.assertTrue(
            self._prompt_existed_after,
            "prompt must be preserved for re-spawn when the story stays in-progress",
        )

    def test_promotes_when_stdout_broke_but_report_written(self):
        """A stdout break AFTER the report was written is a benign late
        pipe-close (the filter writes its report, then exits and closes the
        pipe ~0.1s later). The run succeeded, so it must promote — and unlink
        the now-consumed prompt."""
        captured = self._run_promote(run_with_tee_return=True, report_exists=True)
        self.assertEqual(
            captured,
            [(str(self.smm_dir), "story-001", "in-progress", "reviewing")],
            f"a late pipe-close after a written report must promote, got: {captured!r}",
        )
        self.assertFalse(
            self._prompt_existed_after,
            "prompt must be unlinked when we promote (run succeeded)",
        )

    def test_unlinks_prompt_on_clean_promote(self):
        """A clean run (no stdout break) unlinks the consumed prompt file."""
        self._run_promote()
        self.assertFalse(
            self._prompt_existed_after,
            "prompt must be unlinked after a clean promote",
        )

    def test_does_not_promote_when_story_id_absent(self):
        """No --story-id → no CAS attempted (ad-hoc teammates without
        sprint context just exit cleanly)."""
        captured = self._run_promote(story_id=None)
        self.assertEqual(captured, [], f"unexpected CAS without story-id: {captured!r}")


if __name__ == "__main__":
    unittest.main()
