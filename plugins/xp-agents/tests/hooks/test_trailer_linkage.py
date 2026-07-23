#!/usr/bin/env python3
"""End-to-end pins for Resolves-Event trailer linkage (debt 67173cfeb320).

These tests drive a REAL git repository and let the hook shell out. The
existing bash-commit suite patches `commits.get_head_commit_hash`,
`get_commit_message_body`, and `get_committed_files`, and only ever exercises a
non-`-q`, `-m` command — which is exactly why three real-world command forms
broke this session with zero test signal:

  git -C <abs> commit -q -F -      (heredoc on stdin)  -> no event recorded
  git -C "$WT" commit -q -m ...    (quoted shell var)  -> wrong repo resolved
  git commit -m ...                (no -q)             -> worked

Leg A is a recording bug. Leg B is a lookup bug: a trailer naming an id absent
from the live event log resolves nothing, silently.
"""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import _common
import bash_post_tool
from conftest import _HookTestCase, _make_bash_input
from event_helpers import events_of_type
from event_schema import EVENT_TYPE_COMMIT, EVENT_TYPE_CONCERN, EVENT_TYPE_DEBT


def _git(cwd: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True, check=True
    )
    return proc.stdout.strip()


class _RealGitRepoTestCase(_HookTestCase):
    """A real git repo (and optionally a real worktree) the hook can shell into."""

    def setUp(self):
        super().setUp()
        self.repo = Path(tempfile.mkdtemp(prefix="story-004-repo-"))
        self.addCleanup(lambda: subprocess.run(["rm", "-rf", str(self.repo)]))
        _git(self.repo, "init", "-q", "-b", "main")
        _git(self.repo, "config", "user.email", "t@example.com")
        _git(self.repo, "config", "user.name", "T")
        _git(self.repo, "config", "commit.gpgsign", "false")
        (self.repo / "seed.py").write_text("x = 1\n")
        _git(self.repo, "add", "-A")
        _git(self.repo, "commit", "-q", "-m", "seed")

    def _stage(self, rel: str, cwd: Path | None = None) -> None:
        target = cwd or self.repo
        (target / rel).write_text("y = 2\n")
        _git(target, "add", "-A")

    def _head(self, cwd: Path | None = None) -> str:
        return _git(cwd or self.repo, "rev-parse", "HEAD")

    def _run_hook(self, command: str, *, stdout: str = "", cwd: Path | None = None):
        return bash_post_tool.run(
            _make_bash_input(command=command, stdout=stdout, cwd=str(cwd or self.repo)),
            smm_dir=self.smm_dir,
        )

    def _commit_events(self) -> list[dict]:
        return events_of_type(self._read_events(), EVENT_TYPE_COMMIT)

    def _concerns(self) -> list[dict]:
        return events_of_type(self._read_events(), EVENT_TYPE_CONCERN)


class TestQuietCommitRecording(_RealGitRepoTestCase):
    """Leg A: `-q` removes the `[branch hash]` stdout signal, so the fallback
    must confirm the commit from the command + HEAD's body."""

    def test_quiet_heredoc_dash_F_commit_is_recorded(self):
        """story-003's teammate form. `extract_commit_message` parses only -m,
        so the fallback could not confirm an -F/stdin message and no commit
        event was written."""
        self._stage("a.py")
        subprocess.run(
            ["git", "-C", str(self.repo), "commit", "-q", "-F", "-"],
            input="feat: heredoc bodied commit\n",
            text=True,
            check=True,
        )
        command = (
            f"git -C {self.repo} commit -q -F - <<'EOF'\n"
            "feat: heredoc bodied commit\nEOF"
        )
        self._run_hook(command)
        events = self._commit_events()
        self.assertEqual(len(events), 1, "expected exactly one commit event")
        self.assertEqual(
            events[0]["metadata"]["commit_hash"], self._head(), "wrong commit_hash"
        )

    def test_quiet_chained_heredoc_dash_F_commit_is_recorded(self):
        """AC-5 / story-005's literal command (concern 1e6186970e01):
        `git add -A && git commit -q -F - <<'EOF' && git show --stat HEAD`.
        The pre-fix pattern demanded the newline immediately after the
        opening delimiter; the trailing `&& git show --stat HEAD` broke that,
        `extract_commit_message` returned None, and NO commit event was
        recorded even though the commit landed."""
        self._stage("a.py")
        subprocess.run(
            ["git", "-C", str(self.repo), "commit", "-q", "-F", "-"],
            input="feat: chained heredoc bodied commit\n",
            text=True,
            check=True,
        )
        command = (
            f"git add -A && git -C {self.repo} commit -q -F - <<'EOF' && "
            "git show --stat HEAD\n"
            "feat: chained heredoc bodied commit\nEOF"
        )
        self._run_hook(command)
        events = self._commit_events()
        self.assertEqual(len(events), 1, "expected exactly one commit event")
        self.assertEqual(
            events[0]["metadata"]["commit_hash"], self._head(), "wrong commit_hash"
        )

    def test_plain_commit_still_records_exactly_one_event(self):
        """Regression guard for the `git commit -m` path that already worked."""
        self._stage("b.py")
        subprocess.run(
            ["git", "-C", str(self.repo), "commit", "-m", "feat: plain"], check=True
        )
        self._run_hook(f'git -C {self.repo} commit -m "feat: plain"')
        self.assertEqual(len(self._commit_events()), 1)


class TestQuotedDashCResolvesTheRightRepo(_RealGitRepoTestCase):
    """Leg A: `strip_quoted` deletes the quoted `"$WT"`, so parse_effective_cwd
    silently returns the MAIN checkout — recording the wrong repo's HEAD."""

    def setUp(self):
        super().setUp()
        # Production layout: worktree.list_live_teammate_worktree_paths only
        # recognises `.claude/worktrees/worktree-story-*`.
        self.wt = self.repo / ".claude" / "worktrees" / "worktree-story-001"
        self.wt.parent.mkdir(parents=True, exist_ok=True)
        _git(self.repo, "worktree", "add", "-q", "-b", "story-001", str(self.wt))
        self.addCleanup(lambda: subprocess.run(["rm", "-rf", str(self.wt)]))

    def test_commit_in_quoted_C_path_records_the_worktree_hash(self):
        main_head_before = self._head()
        self._stage("c.py", cwd=self.wt)
        subprocess.run(
            ["git", "-C", str(self.wt), "commit", "-q", "-m", "feat: in worktree"],
            check=True,
        )
        wt_head = self._head(cwd=self.wt)
        self.assertNotEqual(wt_head, main_head_before)

        # The shell expanded $WT; the hook only ever sees the literal text.
        command = 'git -C "$WT" commit -q -m "feat: in worktree"'
        self._run_hook(command, cwd=self.repo)

        events = self._commit_events()
        self.assertEqual(len(events), 1, "commit in a quoted -C path was not recorded")
        self.assertEqual(
            events[0]["metadata"]["commit_hash"],
            wt_head,
            "recorded the main checkout's HEAD instead of the worktree's",
        )

    def test_rejected_main_commit_not_attributed_to_worktree(self):
        """Finding 1: a plain `git commit` in the MAIN checkout that never
        landed (pre-commit rejection — HEAD unchanged, no stdout signal, no
        `-C`) must NEVER be re-attributed to a live worktree whose HEAD subject
        coincidentally equals the attempted message. The worktree scan is gated
        on an unreachable `-C` target; a plain commit has none, so the scan is
        never reached and no event is fabricated against the worktree's hash."""
        # Give the worktree a HEAD subject that collides with the message main
        # will fail to commit.
        self._stage("collide.py", cwd=self.wt)
        subprocess.run(
            ["git", "-C", str(self.wt), "commit", "-q", "-m", "fix parser"],
            check=True,
        )
        wt_head = self._head(cwd=self.wt)
        # Main only *attempts* the same message; the commit never lands (HEAD
        # unchanged, empty stdout as a pre-commit rejection would leave it).
        self._run_hook('git commit -m "fix parser"', cwd=self.repo)
        events = self._commit_events()
        self.assertEqual(
            events,
            [],
            "a rejected main commit fabricated an event; "
            f"worktree hash {wt_head} must not be recorded",
        )


class TestUnconfirmableCommitFailsLoud(_RealGitRepoTestCase):
    """Leg A: a commit we genuinely could not inspect (path hidden behind an
    unexpanded shell variable) returns None and, rather than vanishing with no
    trace, records a concern — the behavior that made this debt take six
    sessions to diagnose."""

    def test_unconfirmable_commit_records_a_concern_not_silence(self):
        # `$WT` is hidden from the hook (strip_quoted deletes the quoted token),
        # so we truly cannot tell where — if anywhere — the commit landed.
        command = 'git -C "$WT" commit -q -m "feat: nowhere"'
        self._run_hook(command)
        self.assertEqual(self._commit_events(), [], "no commit event should record")
        concerns = self._concerns()
        self.assertTrue(concerns, "an unconfirmable commit must record a concern")
        self.assertIn("commit", concerns[-1]["content"].lower())

    def test_literal_absent_dash_C_path_stays_silent(self):
        """Finding 5: `git -C /nonexistent commit` fails outright — git aborts
        with 'cannot change to <path>' and creates nothing. That is a rejected
        commit, not one we could not inspect, so it must record NEITHER a commit
        event NOR an unconfirmed-commit concern."""
        command = 'git -C /nonexistent/repo commit -q -m "feat: nowhere"'
        self._run_hook(command)
        self.assertEqual(self._commit_events(), [], "no commit event should record")
        self.assertEqual(
            self._concerns(),
            [],
            "a literal-absent -C path is a failed commit, not an unconfirmable one",
        )


class TestTrailerLinkage(_RealGitRepoTestCase):
    """Leg A + Leg B: the trailer must reach metadata.resolves, and an
    unlinkable id must be surfaced rather than silently dropped."""

    def _append_debt(self, content: str) -> str:
        event = _common.make_event(EVENT_TYPE_DEBT, "main", content, files=["seed.py"])
        _common.append_safe(self.smm_dir, event)
        recorded = events_of_type(self._read_events(), EVENT_TYPE_DEBT)
        self.assertEqual(len(recorded), 1, "debt fixture failed to persist")
        return event["id"]

    def _commit_with_trailer(self, subject: str, target_id: str) -> None:
        body = f"{subject}\n\nResolves-Event: {target_id}\n"
        self._stage(f"{subject.split(':')[0]}.py")
        subprocess.run(
            ["git", "-C", str(self.repo), "commit", "-q", "-F", "-"],
            input=body,
            text=True,
            check=True,
        )
        command = f"git -C {self.repo} commit -q -F - <<'EOF'\n{body}EOF"
        self._run_hook(command)

    def test_trailer_on_quiet_commit_populates_metadata_resolves(self):
        debt_id = self._append_debt("perf: the thing is slow")
        self._commit_with_trailer("perf: make it fast", debt_id)
        events = self._commit_events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["metadata"]["resolves"], [debt_id])
        self.assertTrue(events[0]["metadata"]["has_resolves_trailer"])

    def test_trailer_naming_absent_id_records_a_concern(self):
        self._commit_with_trailer("fix: names a ghost", "deadbeef1234")
        self.assertEqual(len(self._commit_events()), 1, "commit still records")
        concerns = self._concerns()
        self.assertTrue(concerns, "an unlinkable trailer must surface a concern")
        self.assertIn("deadbeef1234", concerns[-1]["content"])

    def test_trailer_targeting_retro_try_id_is_not_flagged_unlinkable(self):
        """Finding 4: retrospective try-item ids are valid resolution targets —
        compute_resolutions indexes them into by_id so a disposition can close
        them via metadata.resolves. A commit trailer naming a try id must NOT
        record a spurious 'the link will not resolve' concern just because the
        id is nested rather than top-level."""
        from _event_fixtures import make_retrospective_with_try

        try_id = "a1b2c3d4e5f6"
        retro = make_retrospective_with_try(try_id, "Adopt commit-after-green")
        _common.append_safe(self.smm_dir, retro)

        self._commit_with_trailer("chore: adopt the try", try_id)
        self.assertEqual(len(self._commit_events()), 1, "commit still records")
        unlinkable = [c for c in self._concerns() if "will not resolve" in c["content"]]
        self.assertEqual(
            unlinkable,
            [],
            f"a valid retro-try target was flagged unlinkable: {unlinkable}",
        )

    def test_e2e_debt_then_trailer_resolves_it(self):
        """The whole loop the debt was filed about."""
        import resolution

        debt_id = self._append_debt("perf: quadratic scan")
        self._commit_with_trailer("perf: linearize the scan", debt_id)
        resolved = resolution.compute_resolutions(self._read_events())[
            "resolved_debt_ids"
        ]
        self.assertIn(debt_id, resolved, "trailer did not close the debt")


if __name__ == "__main__":
    unittest.main()
