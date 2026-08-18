#!/usr/bin/env python3
"""What the catch-up observer may NOT claim, and what has to survive for it to
claim anything at all.

Split from `test_commit_observer.py` at the 500-line cap, along the line the
two halves already fall on. That file pins what the observer DOES — the cheap
common path, the range walk, the loud declines. This one pins the boundary of
the claim itself:

* the object formats it can even read HEAD in (AC4) — silently unreadable, the
  whole module never runs;
* how long its last-seen marker lives (AC2) — deleted too early, every range is
  seeded over instead of walked;
* and where a story_id may come from (AC1) — the observer watched no command
  run, so only what the commit object carries is a claim it can support.
"""

import shutil
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import cleanup_teammate
import commit_event
import git_head
import markers
import merged_range
import session_end
import worktree
from _observer_case import _ObserverCase
from conftest import SPRINT_IN_PROGRESS


class _Sha256Case(_ObserverCase):
    """The same observer, over a repository whose object names are 64 hex.

    The repo is torn down and rebuilt rather than parameterised into the
    shared fixture: `_commit_repo_case` backs the other commit suites and is
    outside this story's domain.

    Guarded on the capability, never assumed: a git that cannot create a
    SHA-256 repository SKIPS with that named as the reason. A silent pass here
    would be a green test proving nothing at all.
    """

    def setUp(self):
        super().setUp()
        shutil.rmtree(self.repo)
        self.repo.mkdir()
        probe = subprocess.run(
            ["git", "init", "-q", "-b", "main", "--object-format=sha256", "."],
            cwd=self.repo,
            capture_output=True,
            text=True,
        )
        if probe.returncode != 0:
            self.skipTest(
                "this git cannot create a SHA-256 repository: "
                f"`git init --object-format=sha256` failed ({probe.stderr.strip()})"
            )
        self.git("config", "user.email", "t@t.com")
        self.git("config", "user.name", "T")
        self.commit("init", path="README.md", content="init")


class TestANonSha1ObjectFormat(_Sha256Case):
    """AC4. A repository whose object names are not 40 hex must not make this
    module silently never run.

    Asserted against a REAL SHA-256 repo rather than against the pattern,
    because the pattern is the thing being edited: what broke was
    `read_head` returning None for a perfectly good HEAD, which took the whole
    observer down without a single trace — the exact silence it exists to
    remove.
    """

    def test_head_is_readable(self):
        self.assertEqual(git_head.read_head(str(self.repo)), self.head())

    def test_a_commit_is_recorded(self):
        self.seed_observer()
        landed = self.commit("feat: x")
        self.assertEqual(len(landed), 64)
        self.observe()
        self.assertEqual(self.recorded_hashes(), [landed])


class TestTheObjectNamePredicate(unittest.TestCase):
    """Widening a validator is the direction that silently starts accepting
    garbage, so the refusals are pinned beside the acceptances — and the two
    sites are pinned as ONE object, which is what makes "both move together or
    neither does" structural rather than a promise."""

    def test_both_widths_are_accepted(self):
        self.assertTrue(git_head._OBJECT_NAME_RE.match("a" * 40))
        self.assertTrue(git_head._OBJECT_NAME_RE.match("a" * 64))

    def test_neither_width_is_accepted_off_by_one(self):
        for length in (39, 41, 63, 65):
            with self.subTest(length=length):
                self.assertIsNone(git_head._OBJECT_NAME_RE.match("a" * length))

    def test_the_range_parser_shares_the_one_predicate(self):
        """`assertIs` alone would be vacuous: `re.compile` memoises on the
        pattern STRING, so two modules compiling the same source text already
        hand back the same object. The width assertion is what makes this
        bite — a second site left at 40 hex fails it whether or not the
        objects happen to coincide."""
        self.assertIs(
            getattr(merged_range, "_OBJECT_NAME_RE", None),
            git_head._OBJECT_NAME_RE,
        )
        self.assertTrue(merged_range._OBJECT_NAME_RE.match("a" * 64))


class TestTheMarkerOutlivesTheSession(_ObserverCase):
    """The last-seen marker is keyed by a CHECKOUT, not by an agent, and a
    checkout outlives every session that visits it.

    Deleted at session end, the next session cold-starts: it seeds over
    whatever HEAD it now finds and reconciles nothing, so a commit that landed
    after a session's last Bash — the backgrounded case this module exists
    for, run last in a session — is unrecoverable, and every resolve trailer
    on it stays silently open.
    """

    def _end_session(self) -> None:
        session_end.run({"cwd": str(self.repo)}, smm_dir=self.smm_dir)

    def test_a_head_move_after_the_last_bash_is_still_reconciled(self):
        """The half that matters — the marker is only a means to this."""
        self.seed_observer()
        self._end_session()
        landed = self.commit("feat: x")
        self.observe()
        self.assertEqual(self.recorded_hashes(), [landed])

    def test_session_end_leaves_the_marker_where_it_stood(self):
        self.seed_observer()
        head = self.head()
        self._end_session()
        self.assertEqual(self.marker(), {"head": head})


class TestTheMarkerDiesWithTheCheckOut(_ObserverCase):
    """The other direction, and the one easy to lose while fixing the first.

    `cleanup_teammate` passes the worktree NAME, which is exactly the key
    `review_watermark_key` derives for that checkout — so its cleanup call is
    this marker's CORRECT lifetime boundary: the checkout is being destroyed.
    Dropping it would orphan one marker per retired worktree forever, and a
    reused worktree name would then read a dead checkout's last-seen — a bogus
    range, or a loud false decline.
    """

    NAME = "worktree-story-901"

    def _seed_marker(self) -> None:
        markers.marker_write(
            self.smm_dir, markers.LAST_SEEN_HEAD, {"head": "0" * 40}, self.NAME
        )

    def _marker_for_worktree(self) -> dict | str | None:
        return markers.marker_read(self.smm_dir, markers.LAST_SEEN_HEAD, self.NAME)

    def test_worktree_teardown_removes_it(self):
        self._seed_marker()
        with patch(
            "worktree.remove_worktree", return_value=worktree.BranchRemoval.NO_BRANCH
        ):
            self.assertTrue(
                cleanup_teammate.cleanup(
                    self.NAME, str(self.repo), self.smm_dir, "main"
                )
            )
        self.assertIsNone(self._marker_for_worktree())

    def test_a_refused_teardown_keeps_it(self):
        """Non-vacuity: the delete rides the same refusal as every other record
        `cleanup` removes. A branch that gained commits after the merge check
        keeps its worktree's records, this one included."""
        self._seed_marker()
        with patch(
            "worktree.remove_worktree",
            return_value=worktree.BranchRemoval.REFUSED_UNMERGED,
        ):
            self.assertFalse(
                cleanup_teammate.cleanup(
                    self.NAME, str(self.repo), self.smm_dir, "main"
                )
            )
        self.assertEqual(self._marker_for_worktree(), {"head": "0" * 40})


class TestAttributionComesOnlyFromTheCommit(_ObserverCase):
    """AC1. The observer did not watch anything happen, so it may only repeat
    what the commit object itself carries.

    A `git pull` moves HEAD by commits somebody else authored, possibly months
    ago. Tier 2 ("one story in-progress → it is that one") and Tier 2.5 never
    look at the commit at all, so every one of those commits was stamped with
    whatever story happened to be open at observation time — a story_id nothing
    supports, feeding per-story metrics that then read as fact.

    Tier 1 is the non-obvious half. A `.story-assignment` file LOOKS explicit —
    somebody wrote it — but it describes the CHECKOUT's current state, not the
    commit's provenance: a pull into a teammate worktree brings in other
    stories' commits and Tier 1 would stamp every one with this teammate's
    story. The message prefix is the only source that travels WITH the commit,
    which is why the parameter is named `from_commit_only`.
    """

    def _in_progress_sprint(self) -> None:
        (self.smm_dir / "sprint.json").write_text(SPRINT_IN_PROGRESS)

    def _story_ids(self) -> list[str | None]:
        return [e["metadata"].get("story_id") for e in self.commit_events()]

    def test_an_unprefixed_commit_is_not_stamped_with_the_open_story(self):
        """The defect verbatim: the pull shape — commits whose messages carry
        no story tag — observed while a story is in-progress."""
        self._in_progress_sprint()
        self.seed_observer()
        self.commit("chore: a colleague's work, pulled in", path="src/other.py")
        self.observe()
        self.assertEqual(self._story_ids(), [None])

    def test_a_prefixed_commit_is_still_attributed(self):
        """Not a blunt disable. The prefix travels with the commit object, so
        it is a claim the observer CAN support."""
        self._in_progress_sprint()
        self.seed_observer()
        self.commit("[story-001] feat: tagged", path="src/a.py")
        self.observe()
        self.assertEqual(self._story_ids(), ["story-001"])

    def test_a_story_assignment_does_not_attribute_either(self):
        """Tier 1, cut alongside Tier 2 — and the default pinned in the same
        breath, because every existing caller depends on it."""
        import worktree

        self._in_progress_sprint()
        worktree.story_assignment_path(self.smm_dir, "worktree-story-001").write_text(
            "story-001"
        )
        cwd = "/proj/worktree-story-001"
        self.assertEqual(
            commit_event._resolve_story_id(self.smm_dir, cwd, ["src/a.py"]),
            "story-001",
        )
        self.assertIsNone(
            commit_event._resolve_story_id(
                self.smm_dir, cwd, ["src/a.py"], from_commit_only=True
            )
        )


if __name__ == "__main__":
    unittest.main()
