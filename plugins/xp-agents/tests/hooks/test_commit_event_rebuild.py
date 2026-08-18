#!/usr/bin/env python3
"""The HEAD-moved commit-event rebuild.

A `Resolves-Event:` trailer is honored ONLY through a commit event's
`metadata.resolves`. So a commit whose event never gets built silently loses
its trailer — the ids stay open and nothing says so. That happens when both
commit-success signals go blind at once: stdout truncated past the
`[branch hash] msg` line by a large pre-commit run, AND an `-m`/`-F` argument
the hook cannot expand. The recorded case resolved zero of 17 named ids.

The second blindness has a second cause, and it is the dominant one: a
`run_in_background: true` Bash returns the tool call at LAUNCH. git has written
nothing yet, so there is no success line AND the message — perfectly readable —
is compared against a HEAD the command has not moved. See
`docs/completed/BUG_backgrounded_commit_no_event.md`.

These tests run against a REAL temp git repo rather than patched `commits.*`
lookups, because the discriminators the rebuild leans on — committer
timestamp, parent count, reflog action — are properties of git's own history
that a stub would let us assert into existence. The fixture itself lives in
`_commit_repo_case.py`.

Scope: what the rebuild DOES once it has decided the head in front of it is
one it may claim. Whether it may — the three discriminators above, and every
head shape that must be refused — is `test_commit_event_provenance.py`.
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import _common
import review_records
from _commit_repo_case import UNREADABLE_F, UNREADABLE_VAR, _RebuildTestCase
from conftest import compute_resolutions, make_event
from event_schema import EVENT_TYPE_COMMIT, EVENT_TYPE_CONCERN

_SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"

# Same sub-cap and reasoning as the markers split: 450, not 499, because
# "comfortably under 500" is a judgement a green suite cannot make. The
# extracted fixture is capped alongside its consumer, or moving code into it
# would be a way to dodge the cap rather than to hold it.
_LINE_SUB_CAP = 450
_CAPPED_FILES = (
    _SCRIPTS_DIR / "commit_handling.py",
    _SCRIPTS_DIR / "commit_event.py",
    _SCRIPTS_DIR / "commit_emit.py",
    _SCRIPTS_DIR / "commits.py",
    Path(__file__).resolve(),
    Path(__file__).resolve().parent / "_commit_repo_case.py",
    # The provenance split, capped alongside its origin for the same reason the
    # fixture is: uncapped, it would be somewhere to move code to rather than a
    # place the code belongs.
    Path(__file__).resolve().parent / "test_commit_event_provenance.py",
    # The message-parsing half of `commits.py`, capped on arrival for that same
    # reason. It is far under today, which is exactly when to record it: the cap
    # exists to force a placement decision, and a file only added once it is
    # crowded has already had that decision made for it.
    _SCRIPTS_DIR / "commit_trailers.py",
    # The diff-text parser, split out along the same text/git line when the
    # review-scope budget pushed `commits.py` past this cap. Capped on arrival
    # like its siblings.
    _SCRIPTS_DIR / "diff_filenames.py",
    # The merge-range readers, and the two suites the close review's findings
    # split out. Capped on arrival for the same reason as everything above: a file
    # added to this list only once it is crowded has already had its placement
    # decision made for it.
    _SCRIPTS_DIR / "merged_range.py",
    Path(__file__).resolve().parent / "test_manual_merge_commit_event.py",
    Path(__file__).resolve().parent / "test_merge_event_contents.py",
    # The catch-up observer and the HEAD reader it rides on, plus the two suites
    # that pin them. Capped on arrival, per the rule this list already states:
    # the observer is a THIRD commit-recording path, so it is exactly the kind
    # of file the other three would otherwise grow into.
    _SCRIPTS_DIR / "commit_observer.py",
    _SCRIPTS_DIR / "git_head.py",
    Path(__file__).resolve().parent / "test_commit_observer.py",
    Path(__file__).resolve().parent / "test_commit_event_recording.py",
)


class TestRebuildFromGit(_RebuildTestCase):
    """AC-1: the message the command could not supply is read back from git."""

    def test_unreadable_message_still_records_a_commit_event(self):
        head = self.commit("feat: the subject git kept\n\nwhy it was done")
        self.run_hook(UNREADABLE_F)
        events = self.commit_events()
        self.assertEqual(len(events), 1)
        self.assertIn("feat: the subject git kept", events[0]["content"])
        self.assertEqual(events[0]["metadata"]["commit_hash"], head)

    def test_shell_variable_message_also_rebuilds(self):
        self.commit("feat: hidden behind a variable")
        self.run_hook(UNREADABLE_VAR)
        self.assertEqual(len(self.commit_events()), 1)

    def test_rebuilt_event_carries_the_committed_files(self):
        self.commit("feat: x", path="src/foo.py")
        self.run_hook(UNREADABLE_F)
        self.assertEqual(self.commit_events()[0]["files"], ["src/foo.py"])

    def test_recording_suppresses_the_trace(self):
        """One observation per commit: the trace exists for the case the
        rebuild could NOT cover, so firing both would double-report."""
        self.commit("feat: x")
        self.run_hook(UNREADABLE_F)
        self.assertEqual(self.concerns(), [])

    def test_second_run_on_the_same_head_does_not_duplicate(self):
        self.commit("feat: x")
        self.run_hook(UNREADABLE_F)
        self.run_hook(UNREADABLE_F)
        self.assertEqual(len(self.commit_events()), 1)


class TestTrailerActuallyResolves(_RebuildTestCase):
    """AC-2: the point of the whole story — the trailer must RESOLVE, not
    merely land in metadata. Resolution is what the open-concern backlog
    was silently missing."""

    def test_rebuilt_trailer_closes_the_named_concern(self):
        concern_id = self.seed_concern()
        self.commit(f"fix: close it\n\nResolves-Event: {concern_id}")
        self.run_hook(UNREADABLE_F)
        resolutions = compute_resolutions(self._read_events())
        self.assertIn(concern_id, resolutions["resolved_concern_ids"])

    def test_trailer_is_stripped_from_the_recorded_body(self):
        concern_id = self.seed_concern()
        self.commit(f"fix: close it\n\nResolves-Event: {concern_id}")
        self.run_hook(UNREADABLE_F)
        self.assertNotIn("Resolves-Event", self.commit_events()[0]["content"])

    def test_co_authored_by_is_stripped_like_the_success_path(self):
        self.commit("feat: x\n\nCo-Authored-By: Someone <s@example.com>")
        self.run_hook(UNREADABLE_F)
        self.assertNotIn("Co-Authored-By", self.commit_events()[0]["content"])


class TestNoDoubleRecording(_RebuildTestCase):
    """AC-3: a message that DID parse must yield exactly one event."""

    def test_parsed_command_records_once(self):
        self.commit("feat: parsed subject")
        self.run_hook(
            "git commit -m 'feat: parsed subject'",
            stdout="[main 1234567] feat: parsed subject\n 1 file changed",
        )
        self.assertEqual(len(self.commit_events()), 1)

    def test_unreadable_retry_after_a_parsed_success_adds_nothing(self):
        """The retry shape that would double-count: the same HEAD reached
        first through the success path, then through the rebuild."""
        self.commit("feat: parsed subject")
        self.run_hook(
            "git commit -m 'feat: parsed subject'",
            stdout="[main 1234567] feat: parsed subject\n 1 file changed",
        )
        self.run_hook(UNREADABLE_F)
        self.assertEqual(len(self.commit_events()), 1)


class TestDegradesLoudly(_RebuildTestCase):
    """AC-4: an unreadable body is reported, never passed over in silence."""

    def test_body_read_failure_falls_back_to_the_trace(self):
        head = self.commit("feat: x")
        with patch("commits.get_commit_message_body", return_value=None):
            self.run_hook(UNREADABLE_F)
        self.assertEqual(self.commit_events(), [])
        concerns = self.concerns()
        self.assertEqual(len(concerns), 1)
        self.assertEqual(concerns[0]["metadata"]["commit_hash"], head)
        self.assertEqual(concerns[0]["severity"], "low")


class TestBackgroundedCommitIsNotEvidence(_RebuildTestCase):
    """The dominant loss path: 79% of this sprint's plain commits, and 16 of
    16 backgrounded ones, left no commit event at all.

    `run_in_background: true` returns the tool call at LAUNCH. git has written
    nothing, so stdout carries the harness notice instead of a success line —
    and the readable `-m` message is compared against a HEAD this command has
    not moved. That mismatch is the one thing the rebuild's message guard
    reads as evidence, and here it is evidence of nothing: the command has not
    run yet. HEAD is instead very often the PREVIOUS backgrounded commit,
    unrecorded for exactly this reason, and recovering it is the rebuild's own
    stated claim — "a commit exists at this hash with no event, here is its
    message read back from git".
    """

    _LAUNCH_NOTICE = "Command running in background with ID: b1s2v6k3o"
    _STILL_RUNNING = "git commit -m 'a subject git has not written yet'"

    def test_previous_backgrounded_commit_is_recovered(self):
        head = self.commit("feat: landed in the background, unobserved")
        self.run_hook(self._STILL_RUNNING, stdout=self._LAUNCH_NOTICE, background=True)
        events = self.commit_events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["metadata"]["commit_hash"], head)
        self.assertIn("landed in the background", events[0]["content"])

    def test_recovered_commit_closes_its_trailer(self):
        """AC-2: the trailer resolves at commit time, not only at the merge."""
        concern_id = self.seed_concern()
        self.commit(f"fix: close it\n\nResolves-Event: {concern_id}")
        self.run_hook(self._STILL_RUNNING, stdout=self._LAUNCH_NOTICE, background=True)
        resolutions = compute_resolutions(self._read_events())
        self.assertIn(concern_id, resolutions["resolved_concern_ids"])

    def test_recovery_replaces_the_false_trace(self):
        """The two traces this bug left in the live log claimed a commit whose
        message "did not parse" — of a message that parses fine. Recording the
        commit is the honest observation; the trace must not also fire."""
        self.commit("feat: landed in the background, unobserved")
        self.run_hook(self._STILL_RUNNING, stdout=self._LAUNCH_NOTICE, background=True)
        self.assertEqual(self.concerns(), [])

    def test_a_backgrounded_launch_over_recorded_history_stays_quiet(self):
        """The first backgrounded commit of a branch: HEAD is still the
        recorded commit the branch was cut from, and there is nothing to
        recover yet. Silence, not a fabricated second event for that hash."""
        head = self.commit("feat: already accounted for")
        _common.append_safe(
            self.smm_dir,
            make_event(
                EVENT_TYPE_COMMIT,
                content="feat: already accounted for",
                metadata={"commit_hash": head, "action": "commit_success"},
            ),
        )
        self.run_hook(self._STILL_RUNNING, stdout=self._LAUNCH_NOTICE, background=True)
        self.assertEqual(len(self.commit_events()), 1)
        self.assertEqual(self.concerns(), [])

    def test_the_reset_is_keyed_to_the_commit_recovered(self):
        """Not to the one this launch will eventually make — that hash does
        not exist yet, and the next commit's gate sizes its review by diffing
        `last_review_commit..HEAD`."""
        review_records.set_review_flag(self.smm_dir, "main", "quality_review_done")
        head = self.commit("feat: landed in the background, unobserved")
        self.run_hook(self._STILL_RUNNING, stdout=self._LAUNCH_NOTICE, background=True)
        cycle = review_records.read_review_flags(self.smm_dir, "main")
        self.assertFalse(cycle["quality_review_done"])
        self.assertEqual(
            review_records.read_review_watermark(self.smm_dir, "main"), head
        )

    def test_the_other_guards_still_stand_when_backgrounded(self):
        """Only the message guard is bypassed. An old HEAD is still someone
        else's history, backgrounded or not."""
        self.commit("feat: yesterday's work", age_seconds=6 * 3600)
        self.run_hook(self._STILL_RUNNING, stdout=self._LAUNCH_NOTICE, background=True)
        self.assertEqual(self.commit_events(), [])


class TestRebuildGateIsHashOnly(_RebuildTestCase):
    """The trace dedup must not double as a rebuild gate. A hash already
    carrying a trace — from an earlier attempt whose body read failed —
    could otherwise never be rebuilt, and its trailer stays dropped."""

    def test_prior_trace_on_this_hash_does_not_block_the_rebuild(self):
        head = self.commit("feat: x")
        _common.append_safe(
            self.smm_dir,
            make_event(
                EVENT_TYPE_CONCERN,
                content="earlier attempt could not read the message",
                metadata={"commit_hash": head},
            ),
        )
        self.run_hook(UNREADABLE_F)
        self.assertEqual(len(self.commit_events()), 1)

    def test_already_recorded_hash_is_left_alone(self):
        head = self.commit("feat: x")
        _common.append_safe(
            self.smm_dir,
            make_event(
                EVENT_TYPE_COMMIT,
                content="feat: x",
                metadata={"commit_hash": head, "action": "commit_success"},
            ),
        )
        self.run_hook(UNREADABLE_F)
        self.assertEqual(len(self.commit_events()), 1)
        self.assertEqual(self.concerns(), [])


class TestReviewCycleReset(_RebuildTestCase):
    """The rebuild resets the cycle for the same reason the success path
    does: a commit event recorded without it leaves the prior cycle's
    quality-review flag latched, so the NEXT commit's gate reads satisfied
    off a review that predates this commit."""

    def test_rebuild_resets_the_review_cycle(self):
        review_records.set_review_flag(self.smm_dir, "main", "quality_review_done")
        head = self.commit("feat: x")
        self.run_hook(UNREADABLE_F)
        cycle = review_records.read_review_flags(self.smm_dir, "main")
        self.assertFalse(cycle["quality_review_done"])
        self.assertEqual(
            review_records.read_review_watermark(self.smm_dir, "main"), head
        )

    def test_trace_only_path_leaves_the_cycle_alone(self):
        """No event recorded means nothing to gate against — and the branch
        we did not claim must not mutate state either."""
        review_records.set_review_flag(self.smm_dir, "main", "quality_review_done")
        self.commit("feat: yesterday's work", age_seconds=6 * 3600)
        self.run_hook(UNREADABLE_F)
        self.assertTrue(
            review_records.read_review_flags(self.smm_dir, "main")[
                "quality_review_done"
            ]
        )

    def test_leaked_xp_agent_type_records_but_does_not_reset(self):
        """Mirrors the success path's is_xp_agent_leak mode: record the
        commit, mutate nothing else, so a leaked subagent identity cannot
        clear main's flags."""
        review_records.set_review_flag(self.smm_dir, "main", "quality_review_done")
        self.commit("feat: x")
        self.run_hook(UNREADABLE_F, agent_type="xp-leaked")
        self.assertEqual(len(self.commit_events()), 1)
        self.assertTrue(
            review_records.read_review_flags(self.smm_dir, "main")[
                "quality_review_done"
            ]
        )


class TestFileSizeCap(unittest.TestCase):
    """The split exists to hold a cap; pin it so a later addition to any of
    these files has to make the same placement decision consciously."""

    def test_touched_modules_stay_under_the_sub_cap(self):
        over = {
            path.name: len(path.read_text(encoding="utf-8").splitlines())
            for path in _CAPPED_FILES
            if len(path.read_text(encoding="utf-8").splitlines()) > _LINE_SUB_CAP
        }
        self.assertEqual(over, {}, f"over the {_LINE_SUB_CAP}-line sub-cap: {over}")


if __name__ == "__main__":
    unittest.main()
