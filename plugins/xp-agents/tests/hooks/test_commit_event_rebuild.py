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
import markers
from _commit_repo_case import _RebuildTestCase
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
)

# Two shapes of "the hook cannot expand this message". `-F <path>` yields no
# message at all; `"$MSG"` yields the literal variable name, which never
# matches HEAD. Both are real: the recorded incident used a command
# substitution, and `-F -` with a heredoc is the other common spelling.
_UNREADABLE_F = "git commit -F {repo}/.git/MSG-ALREADY-GONE"
_UNREADABLE_VAR = 'git commit -m "$MSG"'


class TestRebuildFromGit(_RebuildTestCase):
    """AC-1: the message the command could not supply is read back from git."""

    def test_unreadable_message_still_records_a_commit_event(self):
        head = self.commit("feat: the subject git kept\n\nwhy it was done")
        self.run_hook(_UNREADABLE_F)
        events = self.commit_events()
        self.assertEqual(len(events), 1)
        self.assertIn("feat: the subject git kept", events[0]["content"])
        self.assertEqual(events[0]["metadata"]["commit_hash"], head)

    def test_shell_variable_message_also_rebuilds(self):
        self.commit("feat: hidden behind a variable")
        self.run_hook(_UNREADABLE_VAR)
        self.assertEqual(len(self.commit_events()), 1)

    def test_rebuilt_event_carries_the_committed_files(self):
        self.commit("feat: x", path="src/foo.py")
        self.run_hook(_UNREADABLE_F)
        self.assertEqual(self.commit_events()[0]["files"], ["src/foo.py"])

    def test_recording_suppresses_the_trace(self):
        """One observation per commit: the trace exists for the case the
        rebuild could NOT cover, so firing both would double-report."""
        self.commit("feat: x")
        self.run_hook(_UNREADABLE_F)
        self.assertEqual(self.concerns(), [])

    def test_second_run_on_the_same_head_does_not_duplicate(self):
        self.commit("feat: x")
        self.run_hook(_UNREADABLE_F)
        self.run_hook(_UNREADABLE_F)
        self.assertEqual(len(self.commit_events()), 1)


class TestTrailerActuallyResolves(_RebuildTestCase):
    """AC-2: the point of the whole story — the trailer must RESOLVE, not
    merely land in metadata. Resolution is what the open-concern backlog
    was silently missing."""

    def test_rebuilt_trailer_closes_the_named_concern(self):
        concern_id = self.seed_concern()
        self.commit(f"fix: close it\n\nResolves-Event: {concern_id}")
        self.run_hook(_UNREADABLE_F)
        resolutions = compute_resolutions(self._read_events())
        self.assertIn(concern_id, resolutions["resolved_concern_ids"])

    def test_trailer_is_stripped_from_the_recorded_body(self):
        concern_id = self.seed_concern()
        self.commit(f"fix: close it\n\nResolves-Event: {concern_id}")
        self.run_hook(_UNREADABLE_F)
        self.assertNotIn("Resolves-Event", self.commit_events()[0]["content"])

    def test_co_authored_by_is_stripped_like_the_success_path(self):
        self.commit("feat: x\n\nCo-Authored-By: Someone <s@example.com>")
        self.run_hook(_UNREADABLE_F)
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
        self.run_hook(_UNREADABLE_F)
        self.assertEqual(len(self.commit_events()), 1)


class TestDegradesLoudly(_RebuildTestCase):
    """AC-4: an unreadable body is reported, never passed over in silence."""

    def test_body_read_failure_falls_back_to_the_trace(self):
        head = self.commit("feat: x")
        with patch("commits.get_commit_message_body", return_value=None):
            self.run_hook(_UNREADABLE_F)
        self.assertEqual(self.commit_events(), [])
        concerns = self.concerns()
        self.assertEqual(len(concerns), 1)
        self.assertEqual(concerns[0]["metadata"]["commit_hash"], head)
        self.assertEqual(concerns[0]["severity"], "low")


class TestAmbiguousHeadIsNotClaimed(_RebuildTestCase):
    """AC-6 and the reflog discriminators. Recording an AMBIGUOUS head would
    fabricate a commit this command never made, and honor a trailer from
    someone else's history — a worse fail-open than the one being fixed.

    A fresh two-parent merge is no longer one of the ambiguous cases: the
    reflog says how it landed, and it is recorded as a merge (see below). The
    ambiguity that still refuses is an OLD head, or a head whose reflog cannot
    be read at all."""

    def test_rejection_atop_old_unrecorded_history(self):
        """AC-6: HEAD is old, so the just-run command did not produce it."""
        self.commit("feat: yesterday's work", age_seconds=6 * 3600)
        self.run_hook(_UNREADABLE_F)
        self.assertEqual(self.commit_events(), [])
        self.assertEqual(len(self.concerns()), 1)

    def _merge_a_side_branch(self) -> None:
        """Leave HEAD on a fresh two-parent `--no-ff` merge commit."""
        self.commit("feat: mainline")
        base = self.git("rev-parse", "HEAD~1")
        self.git("checkout", "-q", "-b", "side", base)
        self.commit("feat: side work", path="src/side.py")
        self.git("checkout", "-q", "main")
        self.git("merge", "-q", "--no-ff", "-m", "Merge side", "side")

    def test_young_merge_head_is_recorded_as_a_merge_not_a_plain_commit(self):
        """SUPERSEDES the earlier AC-7 stance, which refused a merge HEAD
        outright. Its three stated costs are all measurable here, and none is
        incurred: `files` is the merge's diff against its FIRST PARENT (one
        file), not the whole merged branch; the event carries `is_merge`; and
        that tag is precisely what excludes it from the resolves-link-rate
        denominator. What the refusal actually bought was a hand-run merge
        going unrecorded, while `merge_commit_event` closed the same hole for
        the close cycle's own merges and called it a hole.

        The distinction the old name reached for is real and still holds: a
        merge HEAD is not a PLAIN commit. It is now recorded AS a merge rather
        than refused for not being plain."""
        self._merge_a_side_branch()
        self.run_hook(_UNREADABLE_F)
        events = self.commit_events()
        self.assertEqual(len(events), 1)
        self.assertTrue(events[0]["metadata"]["is_merge"])
        self.assertEqual(events[0]["files"], ["src/side.py"])
        # Claimed, so no head-moved trace: one observation per commit.
        self.assertEqual(self.concerns(), [])

    def test_merge_head_is_refused_on_the_parent_count_alone(self):
        """The parent-count guard, isolated. With a reflog present the case
        above is vetoed by the `merge` action before parent count is ever
        load-bearing — deleting the parent check left that test green. Take
        the reflog away (the degrade-to-allow path) and the count is the
        ONLY signal separating a two-parent merge from a landed commit."""
        self._merge_a_side_branch()
        self.erase_reflog()
        self.run_hook(_UNREADABLE_F)
        self.assertEqual(self.commit_events(), [])
        self.assertEqual(len(self.concerns()), 1)

    def test_amended_head_is_not_a_fresh_commit(self):
        """`commit (amend)` rewrites HEAD to a new hash whose predecessor
        may already carry an event. The timestamp cannot tell them apart;
        the reflog can."""
        self.commit("feat: x")
        self.git("commit", "-q", "--amend", "-m", "feat: x amended")
        self.run_hook(_UNREADABLE_F)
        self.assertEqual(self.commit_events(), [])
        self.assertEqual(len(self.concerns()), 1)

    def test_reset_to_a_young_commit_is_not_a_commit(self):
        """HEAD young, single-parent, and still not produced by committing."""
        self.commit("feat: a")
        target = self.head()
        self.commit("feat: b")
        self.git("reset", "-q", "--hard", target)
        self.run_hook(_UNREADABLE_F)
        self.assertEqual(self.commit_events(), [])

    def test_readable_message_that_missed_is_evidence_against_recording(self):
        """The hole a whole-suite run found. A plain `-m 'subject'` the hook
        CAN read, which did not match HEAD, is positive evidence this command
        did not make HEAD — a rejection on top of recent history, or a
        commit-msg hook rewrite. HEAD here is fresh, single-parent and
        reflogged as `commit`, so those three guards all pass and only the
        readable-message check stands between us and fabricating an event
        (and honoring the older commit's trailer) off someone else's work."""
        self.commit("feat: history that predates this command")
        self.run_hook("git commit -m 'a subject that never landed'")
        self.assertEqual(self.commit_events(), [])
        self.assertEqual(len(self.concerns()), 1)

    def test_missing_reflog_vetoes_the_rebuild(self):
        """`core.logAllRefUpdates` can be off (bare repos, and anyone who set
        it), and `git reflog expire` empties the log. Absence VETOES.

        Degrading to allow was the widest residual fabrication path: with no
        reflog, an amend or a reset/ff-merge onto a fresh unrecorded commit
        followed by a failed unreadable commit satisfies freshness, parent count
        and unreadability, and records an event for a commit this command did
        not make — whose trailer then resolves real ids on false evidence.

        Vetoing costs a reflog-less repo only the trace it already got before
        this story existed, so it is not a regression there. The asymmetry is
        lopsided, and it matches the recorded fail-closed doctrine for an
        unresolvable `git -C` target.

        NOT a fresh clone, which does have a reflog: `git clone` writes a
        `clone: from <url>` HEAD entry, so that case is vetoed on the action."""
        self.commit("feat: x")
        self.erase_reflog()
        self.run_hook(_UNREADABLE_F)
        self.assertEqual(len(self.commit_events()), 0)

    def test_future_committer_date_is_not_maximally_fresh(self):
        """A future committer timestamp must not read as fresh.

        `now - ts > MAX` alone is one-sided: a clock-skewed committing host
        yields a negative age, which compares under any positive bound and so
        defeats the freshness guard outright rather than tripping it. Bounding
        at both ends (`0 <= age <= MAX`) is how the housekeeping gate reads the
        same helper. Negative `age_seconds` forward-dates the commit."""
        self.commit("feat: x", age_seconds=-7200)
        self.run_hook(_UNREADABLE_F)
        self.assertEqual(len(self.commit_events()), 0)


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
        markers.set_review_flag(self.smm_dir, "main", "quality_review_done")
        head = self.commit("feat: landed in the background, unobserved")
        self.run_hook(self._STILL_RUNNING, stdout=self._LAUNCH_NOTICE, background=True)
        cycle = markers.read_review_cycle(self.smm_dir, "main")
        self.assertFalse(cycle["quality_review_done"])
        self.assertEqual(cycle["last_review_commit"], head)

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
        self.run_hook(_UNREADABLE_F)
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
        self.run_hook(_UNREADABLE_F)
        self.assertEqual(len(self.commit_events()), 1)
        self.assertEqual(self.concerns(), [])


class TestReviewCycleReset(_RebuildTestCase):
    """The rebuild resets the cycle for the same reason the success path
    does: a commit event recorded without it leaves the prior cycle's
    quality-review flag latched, so the NEXT commit's gate reads satisfied
    off a review that predates this commit."""

    def test_rebuild_resets_the_review_cycle(self):
        markers.set_review_flag(self.smm_dir, "main", "quality_review_done")
        head = self.commit("feat: x")
        self.run_hook(_UNREADABLE_F)
        cycle = markers.read_review_cycle(self.smm_dir, "main")
        self.assertFalse(cycle["quality_review_done"])
        self.assertEqual(cycle["last_review_commit"], head)

    def test_trace_only_path_leaves_the_cycle_alone(self):
        """No event recorded means nothing to gate against — and the branch
        we did not claim must not mutate state either."""
        markers.set_review_flag(self.smm_dir, "main", "quality_review_done")
        self.commit("feat: yesterday's work", age_seconds=6 * 3600)
        self.run_hook(_UNREADABLE_F)
        self.assertTrue(
            markers.read_review_cycle(self.smm_dir, "main")["quality_review_done"]
        )

    def test_leaked_xp_agent_type_records_but_does_not_reset(self):
        """Mirrors the success path's is_xp_agent_leak mode: record the
        commit, mutate nothing else, so a leaked subagent identity cannot
        clear main's flags."""
        markers.set_review_flag(self.smm_dir, "main", "quality_review_done")
        self.commit("feat: x")
        self.run_hook(_UNREADABLE_F, agent_type="xp-leaked")
        self.assertEqual(len(self.commit_events()), 1)
        self.assertTrue(
            markers.read_review_cycle(self.smm_dir, "main")["quality_review_done"]
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
