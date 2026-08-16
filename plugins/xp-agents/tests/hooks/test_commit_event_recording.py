#!/usr/bin/env python3
"""One fixture per commit shape that reached HEAD without reaching the log.

A commit can move HEAD and leave no event. That silently voids every
`Resolves-Event:` trailer on it — a trailer is honored ONLY through
`metadata.resolves` — so every id the author named stays open while the commit
message claims otherwise. The gap has been filed three times and adopted twice
without landing, and one debt was marked resolved before it recurred.

**Several of these pass on day one, and that is the point.** A pin that is
green from the first run still earns its place: it names WHICH shape is handled
and by WHICH predicate, so the next recurrence names a shape instead of
restarting the audit from the event log. Do not delete a case here because it
"tests nothing new" — the thing it tests is that this shape was measured.

The shapes, as measured against this repo's own history and event log:

| specimen   | shape                                | trace | event |
|------------|--------------------------------------|-------|-------|
| `dadf5248` | backgrounded commit                  | no    | no    |
| `d582871c` | ordinary commit, multi-line command  | yes   | no    |
| `6d380d36` | real merge commit                    | yes   | no    |
| `de7a1ae4` | real merge, stdout piped to `tail`   | —     | yes   |
| `c835c4c0` | fast-forward                         | yes   | no    |

Two predicates account for the whole table, and neither is a bug in the
recording machinery itself:

* **`_commit_hash_recorded` short-circuiting on a stale HEAD.** For a
  backgrounded launch PostToolUse fires BEFORE HEAD moves, so the hash probed
  is the PRE-commit one. That hash is already recorded, so the rebuild is never
  reached and neither event nor trace is written. Upgrading the trace to a
  recording there — the remedy debt `fd28b2db07f5` proposed — would have
  recorded the wrong commit.
* **No catch-up observer.** `commit_emit.rebuild_at_head` had exactly one
  caller, inside `commit_handling._handle_commit`, which `bash_post_tool` only
  reaches when `git_commits.is_git_commit(command)` is true. Once a
  commit-shaped Bash returned, nothing looked at HEAD again — ever. That is the
  architectural hole, and `commit_observer` is the fix.

The rebuild machinery itself works: `de7a1ae4`, a real merge whose stdout went
blind behind `| tail -20`, was recovered correctly. It is the control below —
if `TestTruncatedStdoutIsTheWorkingControl` ever goes red, the rebuild
regressed and the observer is masking it.

Fast-forward is OUT OF SCOPE for the existing commit path by customer decision:
`_a_commit_freshly_landed`'s merge arm refuses it deliberately, because a
fast-forward did not create those commits and attributing them to the
fast-forwarding command would fabricate. That refusal is pinned here as the
CORRECT outcome. The observer makes no such attribution, so what it records
about a reachable commit is a different (weaker) claim — see
`commit_observer`'s module docstring.

Real temp git repos, not patched `commits.*` lookups: every discriminator in
play — committer timestamp, parent count, reflog action, ancestry — is a
property of git's own history that a stub would let us assert into existence.
The fixture lives in `_commit_repo_case.py`.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import _common
from _commit_repo_case import _MergeCase, _RebuildTestCase
from conftest import compute_resolutions, make_event
from event_schema import EVENT_TYPE_COMMIT

# An ordinary Bash that is not commit-shaped and not a test run — the shape of
# the overwhelming majority of tool calls, and the one the catch-up observation
# has to ride on. `ls` rather than anything git: the observer must not need a
# git-shaped command to notice that HEAD moved.
ORDINARY_BASH = "ls -la"

# The multi-line shape behind two of the recorded traces. The message is in a
# heredoc, so `commit_message.recover_commit_message` has nothing to expand and
# `_message_unreadable_from_command` is True; the `cd` on line one is what the
# trace reports, because `_record_head_moved_trace` keeps only the first line.
# That is conclusion 4 of the audit: the concerns naming `Command: cd ...` are
# not a separate class, only a misleading label on this one.
MULTILINE_HEREDOC_COMMIT = "cd {repo}\ngit commit -F - <<'EOF'\nsubject\nEOF"


class _ObserverCase(_RebuildTestCase):
    """A repo whose session has already had one ordinary Bash.

    Every case here needs that, because the FIRST observation of a session has
    no last-seen HEAD to compare against and must seed rather than reconcile —
    an unbounded lower bound would walk the whole history. Making the seeding
    Bash explicit in each test keeps that cold start visible rather than
    hiding it in setUp.
    """

    def seed_observer(self) -> str | None:
        """The first Bash of a session: seeds the marker, reconciles nothing."""
        return self.run_hook(ORDINARY_BASH)

    def observe(self) -> str | None:
        """A later ordinary Bash — where the catch-up happens."""
        return self.run_hook(ORDINARY_BASH)

    def record_commit_event(self, commit_hash: str) -> None:
        """Pretend a commit already reached the log, as the branch point has."""
        _common.append_safe(
            self.smm_dir,
            make_event(
                EVENT_TYPE_COMMIT,
                content="already accounted for",
                metadata={"commit_hash": commit_hash, "action": "commit_success"},
            ),
        )

    def recorded_hashes(self) -> list[str]:
        return [e["metadata"].get("commit_hash") for e in self.commit_events()]


class TestBackgroundedCommit(_ObserverCase):
    """Specimen `dadf5248` — the shape that recurred after being closed.

    Predicate: `_commit_hash_recorded` short-circuits on a STALE HEAD. A
    `run_in_background: true` Bash returns at LAUNCH, so the hash
    `commits.get_head_commit_hash` reads is the commit BEFORE this one — which
    is already recorded, so `_handle_commit`'s rebuild branch is skipped and
    neither an event nor a trace is written. `dadf5248` has zero of both, and
    it carried two `Resolves-Event:` trailers.
    """

    _LAUNCH_NOTICE = "Command running in background with ID: b1s2v6k3o"
    _LAUNCHING = "git commit -m 'a subject git has not written yet'"

    def _launch(self) -> None:
        self.run_hook(self._LAUNCHING, stdout=self._LAUNCH_NOTICE, background=True)

    def test_the_launch_itself_records_nothing_and_that_is_correct(self):
        """The audit's verdict at LAUNCH time: silence, and rightly so. HEAD
        still points at recorded history, and the commit this call will make
        does not exist yet — there is nothing honest to record about it."""
        self.record_commit_event(self.head())
        self.seed_observer()
        self._launch()
        self.assertEqual(len(self.commit_events()), 1)
        self.assertEqual(self.concerns(), [])

    def test_the_landed_background_commit_is_recorded_by_the_next_bash(self):
        """The defect, and the requirement: nothing looked at HEAD again.

        The commit lands after the tool call returned. Under the old code the
        next Bash was not commit-shaped, so `is_git_commit` was False and
        `_handle_commit` — the only caller of the rebuild — never ran.
        """
        self.record_commit_event(self.head())
        self.seed_observer()
        self._launch()
        landed = self.commit("feat: landed in the background, unobserved")
        self.observe()
        self.assertIn(landed, self.recorded_hashes())

    def test_the_recorded_event_carries_the_message_git_kept(self):
        self.record_commit_event(self.head())
        self.seed_observer()
        self._launch()
        self.commit("feat: the subject git kept\n\nwhy it was done")
        self.observe()
        bodies = [e["content"] for e in self.commit_events()]
        self.assertTrue(any("the subject git kept" in b for b in bodies))


class TestUnreadableCommandOnAnOrdinaryCommit(_ObserverCase):
    """Specimens `d582871c` / `145eed83` — ordinary commits, multi-line command.

    Both left a trace and no event. Conclusion 4 of the audit: their
    `Command: cd ...` label is not a separate class, only what
    `_record_head_moved_trace` reports after taking
    `command.strip().split("\\n", 1)[0][:120]`.

    The reflog is erased here to force the decline deterministically —
    `_a_commit_freshly_landed` vetoes when `head_landing_facts` cannot say HOW
    HEAD moved. The live specimens' own reason for declining was not
    recoverable from the log, and it does not need to be: the point of the
    observer is that the recovery does not depend on WHY the command-attributed
    path declined.
    """

    def test_the_existing_path_leaves_a_trace_and_no_event(self):
        head = self.commit("feat: x")
        self.erase_reflog()
        self.run_hook(MULTILINE_HEREDOC_COMMIT)
        self.assertEqual(self.commit_events(), [])
        traces = self.concerns()
        self.assertEqual(len(traces), 1)
        self.assertEqual(traces[0]["metadata"]["commit_hash"], head)

    def test_the_trace_reports_only_the_first_line_of_the_command(self):
        """Conclusion 4, pinned: the misleading `Command: cd ...` label."""
        self.commit("feat: x")
        self.erase_reflog()
        self.run_hook(MULTILINE_HEREDOC_COMMIT)
        # Split at the label, not searched whole: the trace's own prose opens
        # "A git commit command was issued", so a bare `assertNotIn` for the
        # commit line matches the boilerplate and passes for the wrong reason.
        reported = self.concerns()[0]["content"].split("Command: ", 1)[1]
        self.assertEqual(reported, f"cd {self.repo}")

    def test_the_next_ordinary_bash_records_the_commit_anyway(self):
        self.seed_observer()
        head = self.commit("feat: x")
        self.erase_reflog()
        self.run_hook(MULTILINE_HEREDOC_COMMIT)
        self.observe()
        self.assertIn(head, self.recorded_hashes())


class TestMergeCommit(_MergeCase, _ObserverCase):
    """Specimen `6d380d36` — a real merge commit that left a trace, no event.

    Same class as the case above by the audit's conclusion 4: the command was
    `git -C <repo> merge main --no-edit 2>&1 | tail -40`, so both success
    signals went blind, and the rebuild declined. The reflog is erased for the
    same deterministic reason.
    """

    _MERGE_COMMAND = "git -C {repo} merge side --no-edit 2>&1 | tail -40"

    def _land_a_merge(self) -> str:
        self.diverge()
        result = self.merge("side", "--no-edit")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.parent_count(), 2)
        return self.head()

    def test_the_existing_path_leaves_a_trace_and_no_event(self):
        head = self._land_a_merge()
        self.erase_reflog()
        self.run_hook(self._MERGE_COMMAND)
        self.assertEqual(self.merge_events(), [])
        self.assertEqual(self.concerns()[0]["metadata"]["commit_hash"], head)

    def test_the_next_ordinary_bash_records_the_merge(self):
        self.seed_observer()
        head = self._land_a_merge()
        self.erase_reflog()
        self.run_hook(self._MERGE_COMMAND)
        self.observe()
        self.assertIn(head, self.recorded_hashes())


class TestTruncatedStdoutIsTheWorkingControl(_MergeCase, _ObserverCase):
    """Specimen `de7a1ae4` — the case that WORKED, kept as the control.

    A real merge whose stdout was piped through `tail -20`, so git's
    `[branch hash] msg` line never reached the hook. `rebuild_at_head`
    recovered it correctly and recorded event `87846f423070`. If this goes red,
    the rebuild regressed — do not "fix" it by leaning on the observer, which
    would hide the regression behind a second recording path.
    """

    def test_the_rebuild_records_the_merge_without_the_observer(self):
        self.diverge()
        result = self.merge("side", "--no-edit")
        self.assertEqual(result.returncode, 0, result.stderr)
        head = self.head()
        self.run_hook("git merge side --no-edit 2>&1 | tail -20", stdout="(truncated)")
        events = self.merge_events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["metadata"]["commit_hash"], head)


class TestFastForwardStaysRefused(_MergeCase, _ObserverCase):
    """Specimen `c835c4c0` — a fast-forward ONTO a merge commit.

    `_a_commit_freshly_landed`'s merge arm refuses it on purpose: the parent
    count is 2, but the reflog detail is `fast-forward`, not `merge made by`.
    The fast-forwarding command did not create those commits, so recording them
    AS ITS WORK would fabricate. This refusal is the CORRECT outcome and is
    pinned as such — it is not on the list of things the observer changes.
    """

    def _fast_forward_onto_a_merge(self) -> str:
        base = self.head()
        self.git("checkout", "-q", "-b", "side")
        self.commit("side work", path="src/side.py", content="side")
        self.git("checkout", "-q", "-b", "other", base)
        self.commit("other work", path="src/other.py", content="other")
        self.assertEqual(self.merge("side", "--no-edit").returncode, 0)
        merged = self.head()
        self.git("checkout", "-q", "main")
        self.assertEqual(self.merge("other", "--ff-only").returncode, 0)
        self.assertEqual(self.head(), merged)
        self.assertEqual(self.parent_count(), 2)
        return merged

    def test_the_command_attributed_path_refuses_to_claim_it(self):
        head = self._fast_forward_onto_a_merge()
        self.run_hook("git merge --ff-only other 2>&1 | tail -40")
        self.assertEqual(self.merge_events(), [])
        self.assertEqual(self.concerns()[0]["metadata"]["commit_hash"], head)


class TestTrailerResolvesThroughTheObserver(_ObserverCase):
    """AC4: a trailer's resolution asserted BY A TEST, not by inspection.

    This is the whole point of recording the commit at all. `metadata.resolves`
    is the only channel a `Resolves-Event:` trailer travels, so a commit with no
    event leaves every id it named silently open — and the commit message reads
    as if they were closed.
    """

    def test_a_trailer_on_an_observed_commit_closes_its_target(self):
        concern_id = self.seed_concern()
        self.seed_observer()
        self.commit(f"fix: close it\n\nResolves-Event: {concern_id}")
        self.observe()
        resolutions = compute_resolutions(self._read_events())
        self.assertIn(concern_id, resolutions["resolved_concern_ids"])

    def test_the_trailer_is_stripped_from_the_recorded_body(self):
        concern_id = self.seed_concern()
        self.seed_observer()
        self.commit(f"fix: close it\n\nResolves-Event: {concern_id}")
        self.observe()
        self.assertNotIn("Resolves-Event", self.commit_events()[0]["content"])


if __name__ == "__main__":
    unittest.main()
