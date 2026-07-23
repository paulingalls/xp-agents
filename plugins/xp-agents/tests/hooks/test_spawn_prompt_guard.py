#!/usr/bin/env python3
"""Tests for the two legs that stop a teammate spawning on a STALE prompt.

Story ids repeat every sprint. A prompt file is keyed on the teammate name
(``worktree-story-003``), nothing invalidates it, and spawn never checked that
the prompt it was about to feed a teammate belonged to the story it was
spawning — so a sprint-116 ``story-003`` prompt sitting at the path where
sprint-117's ``story-003`` spawns from would launch a teammate on the WRONG
story, plausibly and silently.

Two legs, tested here:

1. Structural — the sprint id joins the project token in the prompt/log
   namespace, so a prompt from another sprint cannot be AT the path.
2. Behavioural — spawn asserts the prompt names the story's BRANCH before it
   takes a single side effect. The branch, not the story id: both sprints'
   prompts contain the string ``story-003``; only the slug
   (``-perf-timers`` vs ``-tools-remember-what-was-adopted``) tells them apart,
   so an id check passes on the stale prompt that IS the bug.

Path-namespacing that predates the sprint token (project scoping, the
--print-* queries) stays in test_spawn_teammate_logging.py; the runner's own
token sanitation is unit-tested in test_teammate_runner_paths.py.
"""

import io
import shutil
import sys
import unittest
import uuid
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import teammate_runner

# Imported for its side effect as well as its symbols: conftest installs the
# suite-wide backstop that makes launching the real `claude` binary impossible.
# Under `unittest discover` — what CI runs — conftest loads ONLY because a test
# module imports it, and this module drives spawn_teammate.main(), whose tail is
# the real spawn.
from conftest import _s, _sprint_json

# The two same-numbered stories from the real collision (concern aba1dfed04b0):
# a sprint-116 story-003 prompt was found sitting exactly where sprint-117's
# story-003 was about to spawn from. Both prompts say "story-003".
_STALE_BRANCH = "paulingalls/story-003-perf-timers"
_LIVE_BRANCH = "paulingalls/story-003-tools-remember-what-was-adopted"
_NAME = "worktree-story-003"


class _SpawnGuardTestCase(unittest.TestCase):
    """A temp SMM dir under a UNIQUE project token, with an optional sprint.

    The project token is the smm dir's parent name, and it keys a real
    directory — a fixed token would let two tests (or two `pytest -n auto`
    workers) share, and then delete, one another's prompt files.

    The namespace this mints is contained by conftest, which points the log root
    at a disposable dir for the whole session (see `teammate_runner._log_root`),
    so the code under test can mkdir for real without stranding anything in the
    shared /tmp root. Removing our own subtree here is still worth the line —
    unique token → the whole subtree is ours → the session root stays small — but
    it is now tidiness, not the thing standing between the suite and a leak.
    """

    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.project_id = f"proj-{uuid.uuid4().hex[:12]}"
        self.smm_dir = Path(self._tmp.name) / self.project_id / "smm"
        self.smm_dir.mkdir(parents=True)
        self.addCleanup(
            shutil.rmtree,
            teammate_runner._log_root() / self.project_id,
            ignore_errors=True,
        )

    def tearDown(self):
        self._tmp.cleanup()

    def _write_sprint(self, sprint_id: str) -> None:
        (self.smm_dir / "sprint.json").write_text(
            _sprint_json(
                [_s("story-003", "Tools remember what was adopted", "in-progress")],
                sprint_id=sprint_id,
                started="2026-07-11",
            )
        )

    def _plant_prompt(self, body: str) -> Path:
        """Write *body* to the deterministic prompt path spawn will resolve."""
        import spawn_teammate

        path = spawn_teammate.project_prompt_path(
            self.smm_dir,
            _NAME,
            sprint_id=spawn_teammate.resolve_sprint_id(self.smm_dir),
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body)
        return path

    def _spawn(self, *extra: str) -> str:
        """Drive spawn_teammate.main() with the spawn stubbed. Returns stderr."""
        import spawn_teammate

        self.create_worktree = MagicMock(return_value="/tmp/wt")
        self.stdin_seen = ""

        def capture(cmd, *, cwd=None, env=None, stdin=None, name=None, **kw):
            # What reached the teammate's stdin is the assertion target; False is
            # run_with_tee's "downstream stdout stayed open" (not stdout_broken).
            self.stdin_seen = stdin.read() if stdin is not None else ""
            return False

        self.run_with_tee = MagicMock(side_effect=capture)
        err = io.StringIO()
        with (
            patch.object(spawn_teammate, "create_worktree", self.create_worktree),
            patch.object(spawn_teammate, "run_with_tee", self.run_with_tee),
            redirect_stderr(err),
        ):
            spawn_teammate.main(
                ["--name", _NAME, "--smm-dir", str(self.smm_dir), *extra]
            )
        return err.getvalue()


class TestSprintScopedNamespace(_SpawnGuardTestCase):
    """LEG 1 — the sprint id joins the project token in the /tmp namespace.

    teammate_runner._project_dir already argues this case one level down: names
    and story ids repeat across PROJECTS, so a flat path collides. They repeat
    across SPRINTS for exactly the same reason, and the same fix applies — a
    stale prompt from another sprint then cannot be at the path at all.
    """

    def test_same_story_id_in_two_sprints_resolves_to_different_paths(self):
        """AC4. The whole collision: story-003 exists in sprint-116 AND in
        sprint-117, and they must not share one prompt file."""
        import spawn_teammate

        self._write_sprint("sprint-116")
        old = spawn_teammate.project_prompt_path(
            self.smm_dir,
            _NAME,
            sprint_id=spawn_teammate.resolve_sprint_id(self.smm_dir),
        )
        self._write_sprint("sprint-117")
        new = spawn_teammate.project_prompt_path(
            self.smm_dir,
            _NAME,
            sprint_id=spawn_teammate.resolve_sprint_id(self.smm_dir),
        )

        self.assertNotEqual(
            old,
            new,
            "two sprints' story-003 prompts resolve to ONE path — the stale "
            "prompt sits exactly where the live spawn reads",
        )
        self.assertIn("sprint-116", str(old))
        self.assertIn("sprint-117", str(new))
        # Still under the per-project token: the sprint EXTENDS the namespace,
        # it does not replace it (two projects' sprint-117 must stay apart).
        self.assertEqual(old.parent.parent.name, self.project_id)
        self.assertEqual(new.parent.parent.name, self.project_id)

    def test_sprint_token_is_required_not_optional(self):
        """RED #1. An OPTIONAL sprint arg means a missed call site silently
        resolves the OLD path — the lead writes to one path and spawn reads
        another, spawning on an EMPTY prompt: worse than the bug being fixed.
        A required keyword turns a missed site into a TypeError."""
        import teammate_runner

        with self.assertRaises(TypeError):
            teammate_runner.project_prompt_path(self.smm_dir, _NAME)  # type: ignore[call-arg]
        with self.assertRaises(TypeError):
            teammate_runner.project_log_dir(self.smm_dir)  # type: ignore[call-arg]

    def test_no_sprint_degrades_to_the_project_namespace(self):
        """AC6. spawn_teammate is used outside sprints (free branch, ad-hoc
        teammate). No sprint.json → no token → the pre-existing project-only
        namespace, not a crash."""
        import spawn_teammate

        self.assertIsNone(spawn_teammate.resolve_sprint_id(self.smm_dir))
        path = spawn_teammate.project_prompt_path(self.smm_dir, _NAME, sprint_id=None)
        self.assertEqual(path.parent.name, self.project_id)
        self.assertEqual(path.name, f"{_NAME}.prompt.txt")

    def test_corrupt_sprint_degrades_rather_than_crashing_the_spawn(self):
        """A sprint.json that no longer parses must not brick every spawn: the
        namespace read is advisory, so it degrades to the project-only path.
        The prompt guard (leg 2) stays loud for both legs of the read."""
        import spawn_teammate

        (self.smm_dir / "sprint.json").write_text("{ not json")
        self.assertIsNone(spawn_teammate.resolve_sprint_id(self.smm_dir))

    def test_log_dir_shares_the_sprint_scoped_namespace(self):
        """One source of truth for the namespace token: the log dir moves with
        the prompt path, as _project_dir's docstring claims."""
        import spawn_teammate

        self._write_sprint("sprint-117")
        token = spawn_teammate.resolve_sprint_id(self.smm_dir)
        log_dir = spawn_teammate.project_log_dir(self.smm_dir, sprint_id=token)
        prompt = spawn_teammate.project_prompt_path(
            self.smm_dir, _NAME, sprint_id=token
        )
        self.assertEqual(prompt.parent, log_dir)
        self.assertEqual(log_dir.name, "sprint-117")

    def test_print_prompt_path_resolves_what_the_spawn_reads(self):
        """AC5 + verification 3. If the query and the spawn disagree, the lead
        writes the prompt to one path and the teammate is fed the other — an
        EMPTY prompt, silently. Drive both: print the path, plant a prompt
        there, then spawn with no --prompt-file and prove that body reaches the
        teammate's stdin."""
        self._write_sprint("sprint-117")

        import spawn_teammate

        out = io.StringIO()
        with redirect_stdout(out):
            spawn_teammate.main(
                ["--print-prompt-path", "--name", _NAME, "--smm-dir", str(self.smm_dir)]
            )
        printed = Path(out.getvalue().strip())
        self.assertIn("sprint-117", str(printed))
        self.assertTrue(printed.parent.is_dir(), "the query must create the dir")

        printed.write_text(f"Story Branch: `{_LIVE_BRANCH}`\nBODY-FROM-PRINTED-PATH")
        self._spawn("--story-id", "story-003", "--branch", _LIVE_BRANCH)
        self.assertIn("BODY-FROM-PRINTED-PATH", self.stdin_seen)

    def test_print_log_path_is_sprint_scoped_too(self):
        """The `tail -f` target the lead is handed must be the file the tee
        actually writes — both move together or the lead tails nothing."""
        self._write_sprint("sprint-117")

        import spawn_teammate

        out = io.StringIO()
        with redirect_stdout(out):
            spawn_teammate.main(
                ["--print-log-path", "--name", _NAME, "--smm-dir", str(self.smm_dir)]
            )
        printed = Path(out.getvalue().strip())
        self.assertEqual(printed.parent.name, "sprint-117")
        self.assertEqual(printed.name, f"{_NAME}.log")

    def test_main_tees_into_the_sprint_scoped_log_dir(self):
        """The resolved log_dir main() hands run_with_tee is the sprint-scoped
        one — not just what --print-log-path claims."""
        self._write_sprint("sprint-117")
        self._plant_prompt(f"Story Branch: `{_LIVE_BRANCH}`\nbody")
        self._spawn("--story-id", "story-003", "--branch", _LIVE_BRANCH)

        log_dir = self.run_with_tee.call_args.kwargs["log_dir"]
        self.assertEqual(Path(log_dir).name, "sprint-117")


class TestPromptNamesTheBranch(_SpawnGuardTestCase):
    """LEG 2 — spawn refuses a prompt written for a DIFFERENT story.

    Leg 1 makes a cross-sprint stale prompt unreachable by construction. This
    leg is the assertion that does not depend on the path being right: whatever
    prompt is at the resolved path, it must name the story we are spawning
    before we act on it. It fires on a re-used prompt within one sprint too, and
    it is the only leg that survives someone passing --prompt-file by hand.

    Against the BRANCH, not the story id. Both prompts below contain the string
    "story-003" — an id check passes on the stale one, and the stale one IS the
    bug. Only the slug tells them apart.
    """

    def _refusal(self, *extra: str) -> str:
        """Spawn expecting a refusal; return the message. Fails if it spawned."""
        with self.assertRaises(SystemExit) as caught:
            self._spawn(*extra)
        self.create_worktree.assert_not_called()
        self.run_with_tee.assert_not_called()
        return str(caught.exception)

    def test_refuses_a_prompt_whose_story_id_matches_but_slug_does_not(self):
        """AC1/AC3 — THE case. Plant the sprint-116 story-003 prompt (perf
        timers) exactly where sprint-117's story-003 (tools remember what was
        adopted) is about to spawn from, and prove it is refused.

        A test that planted a different story ID would prove nothing: the ids
        are identical. That is the entire point of this story.
        """
        self._write_sprint("sprint-117")
        stale = self._plant_prompt(
            f"# story-003 — Perf timers\n\n**Story Branch:** `{_STALE_BRANCH}`\n"
            "Add timing instrumentation to the event append path.\n"
        )
        self.assertIn("story-003", stale.read_text(), "fixture must share the id")

        msg = self._refusal("--story-id", "story-003", "--branch", _LIVE_BRANCH)

        # Names BOTH the story and the stale prompt path (AC1).
        self.assertIn("story-003", msg)
        self.assertIn(str(stale), msg)
        self.assertIn(_LIVE_BRANCH, msg)

    def test_the_stale_prompt_is_left_alone_never_silently_regenerated(self):
        """A silent rewrite would paper over the collision the lead must see —
        story-005's lesson. The refusal leaves the file exactly as found."""
        self._write_sprint("sprint-117")
        body = f"**Story Branch:** `{_STALE_BRANCH}`\n"
        stale = self._plant_prompt(body)

        self._refusal("--story-id", "story-003", "--branch", _LIVE_BRANCH)

        self.assertEqual(stale.read_text(), body, "the stale prompt was rewritten")

    def test_the_refusal_precedes_every_side_effect(self):
        """Verification 2 / RED #2. 'Before Popen' is NOT early enough: main()'s
        real order is create_worktree → claim_in_place_marker →
        write_story_assignment → read(prompt). A guard where the prompt is USED
        still leaves an orphan worktree, a clobbered name-keyed
        .story-assignment, and a claimed marker behind on a spawn we refuse.

        The prompt read is pure, so it goes FIRST. Here the in-place path is
        driven (it claims the marker AND writes the assignment), and a
        pre-existing assignment for ANOTHER story stands in for the live holder
        whose attribution must not be redirected.
        """
        import in_place_marker
        import worktree

        self._write_sprint("sprint-117")
        self._plant_prompt(f"**Story Branch:** `{_STALE_BRANCH}`\n")

        assignment = worktree.story_assignment_path(self.smm_dir, _NAME)
        assignment.write_text("story-B")

        self._refusal("--story-id", "story-003", "--branch", _LIVE_BRANCH, "--in-place")

        self.assertEqual(
            assignment.read_text(),
            "story-B",
            "the refused spawn overwrote a name-keyed .story-assignment",
        )
        self.assertFalse(
            in_place_marker.in_place_marker_path(self.smm_dir, _NAME).exists(),
            "the refused spawn claimed the in-place name",
        )
        # create_worktree is asserted not-called by _refusal, so no worktree
        # was cut and no branch was checked out for a spawn that never ran.

    def test_a_prompt_written_for_this_story_spawns_normally(self):
        """AC2 — no false refusal. The guard is worthless if it also blocks the
        prompt the lead just wrote."""
        self._write_sprint("sprint-117")
        self._plant_prompt(
            f"# story-003\n\n**Story Branch:** `{_LIVE_BRANCH}`\n\n"
            "BODY-FOR-THIS-STORY\n"
        )

        self._spawn("--story-id", "story-003", "--branch", _LIVE_BRANCH)

        self.create_worktree.assert_called_once()
        self.assertIn("BODY-FOR-THIS-STORY", self.stdin_seen)

    def test_without_a_branch_it_falls_back_to_the_id_and_says_it_is_weaker(self):
        """--in-place (and any pre-branch stage) has no --branch to assert on.
        Fall back to the story id, but SAY that the check is weaker there rather
        than implying a guarantee it cannot make: two sprints' story-003 prompts
        both contain 'story-003', so this leg alone cannot separate them — leg
        1's sprint-scoped path is what does."""
        self._write_sprint("sprint-117")
        self._plant_prompt("a prompt for some other story entirely\n")

        msg = self._refusal("--story-id", "story-003", "--in-place")

        self.assertIn("story-003", msg)
        self.assertRegex(msg, r"(?i)weak|only a story.ID check|cannot tell")

    def test_an_empty_branch_degrades_to_the_id_check_it_does_not_disable_it(self):
        """An EMPTY --branch must read as "no branch", never as "a branch that
        every prompt contains" — `"" in text` is True for all text, so the wrong
        null-check here (`branch if branch is not None else story_id`) silently
        turns the strong check into no check at all, on the one input that is
        most likely to arrive by accident.

        Not hypothetical: a lead composing `--branch "$VAR"` in a second Bash
        call hands the spawn an empty value, because shell state does not persist
        across calls — the exact accident that made --prompt-file optional (see
        parse_args). The guard must still refuse the stale prompt, on the id."""
        self._write_sprint("sprint-117")
        self._plant_prompt("a prompt for some other story entirely\n")

        msg = self._refusal("--story-id", "story-003", "--branch", "")

        self.assertIn("story-003", msg)

    def test_the_id_fallback_accepts_a_prompt_that_names_the_story(self):
        """The weak check still passes the prompt that names its story — it is a
        weaker guarantee, not a broken one."""
        self._write_sprint("sprint-117")
        self._plant_prompt("Story: story-003\nIN-PLACE-BODY\n")

        self._spawn("--story-id", "story-003", "--in-place")

        self.assertIn("IN-PLACE-BODY", self.stdin_seen)

    def test_an_ad_hoc_teammate_with_no_story_is_not_gated(self):
        """No --branch and no --story-id: an ad-hoc teammate outside a sprint.
        There is nothing to assert the prompt against, so it is taken as-is —
        the guard must not invent a target and refuse every free spawn."""
        self._plant_prompt("free-form ad-hoc prompt\n")

        self._spawn()

        self.assertIn("free-form ad-hoc prompt", self.stdin_seen)

    def test_a_missing_prompt_is_refused_loudly_not_spawned_empty(self):
        """The failure mode the required sprint token exists to prevent, caught
        again at the last line of defence: no prompt at the resolved path means
        the teammate would be fed an EMPTY prompt. Name the path and refuse,
        before any side effect."""
        self._write_sprint("sprint-117")
        # Nothing planted.

        msg = self._refusal("--story-id", "story-003", "--branch", _LIVE_BRANCH)

        self.assertIn("story-003", msg)
        self.assertIn(f"{_NAME}.prompt.txt", msg)


class TestTheRefusalReachesTheLead(_SpawnGuardTestCase):
    """A refusal is only as loud as the pipe it travels down.

    /xp-assign never runs the spawn bare: it runs
    ``spawn_teammate.py ... 2>&1 | teammate_output_filter.py``. That filter now
    surfaces any unrecognised non-JSON line rather than dropping it, but a
    signal it DOES recognise still gets its own dedicated "Spawn failed: ..."
    wording ahead of the generic tiers — so the refusal names itself with a
    token the filter knows, keeping its dedicated phrasing (and the stale
    path, the branch, and the remedy) intact rather than falling back to the
    generic "unrecognized output" wording.

    The unhandled exception this guard replaced carried a "Traceback" the filter
    matches; a clean SystemExit carries nothing. So the refusal names itself with
    a token the filter knows, and this is the pin that keeps the two ends of that
    contract from drifting apart.
    """

    def test_the_filter_surfaces_the_refusal_the_lead_must_act_on(self):
        import teammate_output_filter

        self._write_sprint("sprint-117")
        stale = self._plant_prompt(f"**Story Branch:** `{_STALE_BRANCH}`\n")

        with self.assertRaises(SystemExit) as caught:
            self._spawn("--story-id", "story-003", "--branch", _LIVE_BRANCH)

        # What the shell hands the filter: the refusal on stderr, merged by 2>&1.
        diag = teammate_output_filter.extract_diagnostics(
            str(caught.exception).splitlines()
        )

        self.assertIn(str(stale), diag, "the lead never learns WHICH prompt")
        self.assertIn(_LIVE_BRANCH, diag, "...nor which branch it failed to name")


if __name__ == "__main__":
    unittest.main()
