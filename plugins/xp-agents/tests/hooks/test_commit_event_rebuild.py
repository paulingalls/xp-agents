#!/usr/bin/env python3
"""The HEAD-moved commit-event rebuild.

A `Resolves-Event:` trailer is honored ONLY through a commit event's
`metadata.resolves`. So a commit whose event never gets built silently loses
its trailer — the ids stay open and nothing says so. That happens when both
commit-success signals go blind at once: stdout truncated past the
`[branch hash] msg` line by a large pre-commit run, AND an `-m`/`-F` argument
the hook cannot expand. The recorded case resolved zero of 17 named ids.

These tests run against a REAL temp git repo rather than patched `commits.*`
lookups, because the discriminators the rebuild leans on — committer
timestamp, parent count, reflog action — are properties of git's own history
that a stub would let us assert into existence.
"""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import _common
import bash_post_tool
import markers
from conftest import _HookTestCase, _make_bash_input, compute_resolutions, make_event
from event_helpers import events_of_type
from event_schema import EVENT_TYPE_COMMIT, EVENT_TYPE_CONCERN

_SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"

# Same sub-cap and reasoning as the markers split: 450, not 499, because
# "comfortably under 500" is a judgement a green suite cannot make.
_LINE_SUB_CAP = 450
_CAPPED_FILES = (
    _SCRIPTS_DIR / "commit_handling.py",
    _SCRIPTS_DIR / "commit_event.py",
    _SCRIPTS_DIR / "commit_emit.py",
    _SCRIPTS_DIR / "commits.py",
    Path(__file__).resolve(),
)

# Two shapes of "the hook cannot expand this message". `-F <path>` yields no
# message at all; `"$MSG"` yields the literal variable name, which never
# matches HEAD. Both are real: the recorded incident used a command
# substitution, and `-F -` with a heredoc is the other common spelling.
_UNREADABLE_F = "git commit -F {repo}/.git/MSG-ALREADY-GONE"
_UNREADABLE_VAR = 'git commit -m "$MSG"'


class _RebuildTestCase(_HookTestCase):
    """A real git repo plus a temp SMM, fresh per test."""

    def setUp(self):
        super().setUp()
        self.repo = Path(tempfile.mkdtemp())
        self.git("init", "-q", "-b", "main", ".")
        self.git("config", "user.email", "t@t.com")
        self.git("config", "user.name", "T")
        # An initial commit so `git diff HEAD~1` (get_committed_files) has a
        # parent to diff against — a root commit reports no files at all.
        self.commit("init", path="README.md", content="init")

    def tearDown(self):
        shutil.rmtree(self.repo, ignore_errors=True)
        super().tearDown()

    def git(self, *args: str, env_extra: dict | None = None) -> str:
        env = os.environ.copy()
        if env_extra:
            env.update(env_extra)
        result = subprocess.run(
            ["git", *args],
            cwd=self.repo,
            capture_output=True,
            text=True,
            env=env,
        )
        if result.returncode != 0:
            raise AssertionError(f"git {args!r} failed: {result.stderr}")
        return result.stdout.strip()

    def commit(
        self,
        message: str,
        *,
        path: str = "src/foo.py",
        content: str | None = None,
        age_seconds: int = 0,
    ) -> str:
        """Write `path`, commit `message`, return the new HEAD hash.

        `age_seconds` backdates BOTH dates: the freshness gate reads the
        committer timestamp, and pinning only the author date would leave the
        commit young by the measure that matters.
        """
        target = self.repo / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content if content is not None else message)
        self.git("add", "-A")
        env = None
        if age_seconds:
            stamp = f"{int(self.head_timestamp()) - age_seconds} +0000"
            env = {"GIT_COMMITTER_DATE": stamp, "GIT_AUTHOR_DATE": stamp}
        self.git("commit", "-q", "-m", message, env_extra=env)
        return self.head()

    def head(self) -> str:
        return self.git("rev-parse", "HEAD")

    def head_timestamp(self) -> str:
        return self.git("show", "-s", "--format=%ct", "HEAD")

    def run_hook(self, command: str, stdout: str = "", **overrides):
        return bash_post_tool.run(
            _make_bash_input(
                command=command.format(repo=self.repo),
                stdout=stdout,
                cwd=str(self.repo),
                **overrides,
            ),
            smm_dir=self.smm_dir,
        )

    def commit_events(self) -> list[dict]:
        return events_of_type(self._read_events(), EVENT_TYPE_COMMIT)

    def concerns(self) -> list[dict]:
        return events_of_type(self._read_events(), EVENT_TYPE_CONCERN)


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

    def _seed_concern(self) -> str:
        event = make_event(
            EVENT_TYPE_CONCERN, content="dangling work", files=["src/foo.py"]
        )
        _common.append_safe(self.smm_dir, event)
        return event["id"]

    def test_rebuilt_trailer_closes_the_named_concern(self):
        concern_id = self._seed_concern()
        self.commit(f"fix: close it\n\nResolves-Event: {concern_id}")
        self.run_hook(_UNREADABLE_F)
        resolutions = compute_resolutions(self._read_events())
        self.assertIn(concern_id, resolutions["resolved_concern_ids"])

    def test_trailer_is_stripped_from_the_recorded_body(self):
        concern_id = self._seed_concern()
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
    """AC-6/AC-7 and the reflog discriminators. Recording here would
    fabricate a commit this command never made, and honor a trailer from
    someone else's history — a worse fail-open than the one being fixed."""

    def test_rejection_atop_old_unrecorded_history(self):
        """AC-6: HEAD is old, so the just-run command did not produce it."""
        self.commit("feat: yesterday's work", age_seconds=6 * 3600)
        self.run_hook(_UNREADABLE_F)
        self.assertEqual(self.commit_events(), [])
        self.assertEqual(len(self.concerns()), 1)

    def test_young_merge_head_is_not_a_plain_commit(self):
        """AC-7: a manual `git merge` emits no event of its own, so a fresh
        merge HEAD looks exactly like an unrecorded commit. Recording it
        would take the WHOLE merged branch as `files`, untagged, into the
        resolves-link-rate denominator."""
        self.commit("feat: mainline")
        base = self.git("rev-parse", "HEAD~1")
        self.git("checkout", "-q", "-b", "side", base)
        self.commit("feat: side work", path="src/side.py")
        self.git("checkout", "-q", "main")
        self.git("merge", "-q", "--no-ff", "-m", "Merge side", "side")
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

    def test_missing_reflog_falls_back_to_the_timestamp(self):
        """`core.logAllRefUpdates` can be off, and a fresh clone has no
        reflog at all. Absence must read as "no opinion", not as a veto —
        otherwise the fix does nothing on the repos that lack it."""
        self.commit("feat: x")
        (self.repo / ".git" / "logs" / "HEAD").unlink()
        self.run_hook(_UNREADABLE_F)
        self.assertEqual(len(self.commit_events()), 1)


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
