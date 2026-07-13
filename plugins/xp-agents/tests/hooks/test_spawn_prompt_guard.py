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
    directory under /tmp — a fixed token would let two tests (or two `pytest
    -n auto` workers) share, and then delete, one another's prompt files.

    That uniqueness is also why the /tmp namespace must be torn down here: the
    code under test mkdir's `_LOG_ROOT/<project>/<sprint>` for real, and a token
    that is never reused means every run of every test would otherwise strand a
    fresh directory under /tmp forever. Unique token → the whole subtree is ours
    → remove it wholesale (which subsumes the individual prompt files in it).
    """

    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.project_id = f"proj-{uuid.uuid4().hex[:12]}"
        self.smm_dir = Path(self._tmp.name) / self.project_id / "smm"
        self.smm_dir.mkdir(parents=True)
        self.addCleanup(
            shutil.rmtree,
            teammate_runner._LOG_ROOT / self.project_id,
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


if __name__ == "__main__":
    unittest.main()
