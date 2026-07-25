#!/usr/bin/env python3
"""Tests for spawn_teammate.py forensic-log path scoping.

Teammate forensic logs must be namespaced by project so two xp-agents
sessions in different projects that spawn same-named teammates (e.g.
``worktree-story-001``) don't stomp on each other's ``/tmp`` log. Split
out of test_spawn_teammate.py (feature-cohesive; keeps that file under cap).
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

# Imported for its side effect as well as its symbols: conftest installs the
# suite-wide backstop that makes launching the real `claude` binary impossible
# (see test_no_test_can_spawn_a_real_agent.py). Under `unittest discover` — what
# CI runs — conftest loads ONLY because a test module imports it, and this module
# drives spawn_teammate.main(), whose tail is the real spawn.
import conftest  # noqa: F401


class TestProjectScopedLogDir(unittest.TestCase):
    """The project-id is the directory that owns the SMM tree — SMM lives at
    ``{data-root}/{project-id}/smm/``, so ``smm_dir.parent.name``
    is the project-id. main() must route run_with_tee's log_dir there.
    """

    def test_helper_scopes_by_project_id(self):
        """project_log_dir embeds the smm-parent (project-id) so distinct
        projects get distinct dirs while a shared teammate name would still
        collide within a single project."""
        import spawn_teammate

        a = spawn_teammate.project_log_dir("/data/8e1f07eb0759/smm", sprint_id=None)
        b = spawn_teammate.project_log_dir("/data/deadbeefcafe/smm", sprint_id=None)

        self.assertEqual(a.name, "8e1f07eb0759")
        self.assertEqual(b.name, "deadbeefcafe")
        self.assertNotEqual(a, b, "different projects must not share a log dir")

    def test_helper_handles_trailing_slash_and_relative(self):
        """A trailing slash or relative smm-dir still resolves to the
        project-id, never to '' or '.'."""
        import spawn_teammate

        d = spawn_teammate.project_log_dir("/data/8e1f07eb0759/smm/", sprint_id=None)
        self.assertEqual(d.name, "8e1f07eb0759")

    def test_main_passes_project_scoped_log_dir(self):
        """main() forwards a project-scoped log_dir to run_with_tee rather
        than letting it default to the shared /tmp."""
        import tempfile
        from unittest.mock import patch

        import spawn_teammate

        captured = {}

        def capture_tee(cmd, *, cwd=None, env=None, stdin=None, name=None, **kw):
            captured["log_dir"] = kw.get("log_dir")

        smm_dir = "/tmp/plugindata/8e1f07eb0759/smm"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("test prompt")
            prompt_path = f.name

        try:
            with (
                patch.object(spawn_teammate, "create_worktree", return_value="/tmp/wt"),
                patch.object(spawn_teammate, "run_with_tee", side_effect=capture_tee),
            ):
                spawn_teammate.main(
                    [
                        "--name",
                        "worktree-story-001",
                        "--smm-dir",
                        smm_dir,
                        "--prompt-file",
                        prompt_path,
                    ]
                )
            self.assertEqual(
                captured.get("log_dir"),
                spawn_teammate.project_log_dir(smm_dir, sprint_id=None),
                "main() must pass the project-scoped log_dir, not default /tmp",
            )
        finally:
            Path(prompt_path).unlink(missing_ok=True)


class TestPrintLogPath(unittest.TestCase):
    """`--print-log-path` is a pure query: it prints the deterministic
    project-scoped forensic-log path for a teammate name and exits 0 WITHOUT
    spawning. /xp-assign calls it to surface the live `tail -f` target to the
    lead — the path must match run_with_tee's own (`project_log_dir` + name)
    so a tailer watches the same file the tee writes.
    """

    def test_print_log_path_prints_deterministic_path_and_does_not_spawn(self):
        import io
        from contextlib import redirect_stdout
        from unittest.mock import patch

        import spawn_teammate

        smm_dir = "/tmp/plugindata/8e1f07eb0759/smm"
        buf = io.StringIO()
        with (
            patch.object(spawn_teammate, "create_worktree") as mock_wt,
            patch.object(spawn_teammate, "run_with_tee") as mock_tee,
            redirect_stdout(buf),
        ):
            spawn_teammate.main(
                [
                    "--print-log-path",
                    "--name",
                    "worktree-story-005",
                    "--smm-dir",
                    smm_dir,
                ]
            )

        expected = str(
            spawn_teammate.project_log_dir(smm_dir, sprint_id=None)
            / "worktree-story-005.log"
        )
        self.assertEqual(buf.getvalue().strip(), expected)
        # Pure query — no worktree, no spawn.
        mock_wt.assert_not_called()
        mock_tee.assert_not_called()

    def test_print_log_path_needs_no_prompt_file(self):
        """The query short-circuits before the prompt-file requirement, so a
        caller can ask for the path without constructing a prompt."""
        import io
        from contextlib import redirect_stdout
        from unittest.mock import patch

        import spawn_teammate

        buf = io.StringIO()
        with (
            patch.object(spawn_teammate, "create_worktree"),
            patch.object(spawn_teammate, "run_with_tee"),
            redirect_stdout(buf),
        ):
            # No --prompt-file passed; must not raise SystemExit from argparse.
            spawn_teammate.main(
                [
                    "--print-log-path",
                    "--name",
                    "worktree-story-005",
                    "--smm-dir",
                    "/tmp/plugindata/deadbeefcafe/smm",
                ]
            )
        self.assertTrue(buf.getvalue().strip().endswith("worktree-story-005.log"))


class TestProjectScopedPromptPath(unittest.TestCase):
    """Teammate prompt files, like logs, are keyed on the teammate name, which
    repeats across projects. A flat ``/tmp/prompt-<id>.txt`` collides when two
    xp-agents sessions in different projects assign the same story — so the
    prompt path must be namespaced by project-id, co-located with the log.
    """

    def test_prompt_path_scopes_by_project_id(self):
        """project_prompt_path embeds the smm-parent (project-id) so distinct
        projects get distinct prompt paths while a shared teammate name would
        still collide within a single project."""
        import spawn_teammate

        a = spawn_teammate.project_prompt_path(
            "/data/8e1f07eb0759/smm", "worktree-story-001", sprint_id=None
        )
        b = spawn_teammate.project_prompt_path(
            "/data/deadbeefcafe/smm", "worktree-story-001", sprint_id=None
        )

        self.assertEqual(a.parent.name, "8e1f07eb0759")
        self.assertEqual(b.parent.name, "deadbeefcafe")
        self.assertNotEqual(a, b, "different projects must not share a prompt path")
        self.assertEqual(a.name, "worktree-story-001.prompt.txt")

    def test_prompt_path_co_located_with_log(self):
        """The prompt file sits in the same per-project dir as the log, so both
        share the single project-id source of truth."""
        import spawn_teammate

        smm_dir = "/data/8e1f07eb0759/smm"
        prompt = spawn_teammate.project_prompt_path(
            smm_dir, "worktree-story-001", sprint_id=None
        )
        self.assertEqual(
            prompt.parent, spawn_teammate.project_log_dir(smm_dir, sprint_id=None)
        )

    def test_prompt_path_handles_trailing_slash(self):
        """A trailing slash on the smm-dir still resolves to the project-id."""
        import spawn_teammate

        p = spawn_teammate.project_prompt_path(
            "/data/8e1f07eb0759/smm/", "worktree-story-001", sprint_id=None
        )
        self.assertEqual(p.parent.name, "8e1f07eb0759")


class TestPrintPromptPath(unittest.TestCase):
    """`--print-prompt-path` is a pure query: it prints the deterministic
    project-scoped prompt path for a teammate name and exits 0 WITHOUT
    spawning. /xp-assign calls it so the orchestrator writes the prompt to a
    collision-safe location instead of a flat ``/tmp/prompt-<id>.txt``. Unlike
    the log path (which spawn_teammate mkdir's itself before the tee), the
    prompt file is written by an external process before spawn, so the query
    must create the parent dir.
    """

    def test_print_prompt_path_prints_deterministic_path_and_does_not_spawn(self):
        import io
        import tempfile
        from contextlib import redirect_stdout
        from unittest.mock import patch

        import spawn_teammate

        with tempfile.TemporaryDirectory() as tmp:
            smm_dir = str(Path(tmp) / "8e1f07eb0759" / "smm")
            buf = io.StringIO()
            with (
                patch.object(spawn_teammate, "create_worktree") as mock_wt,
                patch.object(spawn_teammate, "run_with_tee") as mock_tee,
                redirect_stdout(buf),
            ):
                spawn_teammate.main(
                    [
                        "--print-prompt-path",
                        "--name",
                        "worktree-story-005",
                        "--smm-dir",
                        smm_dir,
                    ]
                )

            expected = spawn_teammate.project_prompt_path(
                smm_dir, "worktree-story-005", sprint_id=None
            )
            self.assertEqual(buf.getvalue().strip(), str(expected))
            # Pure query — no worktree, no spawn.
            mock_wt.assert_not_called()
            mock_tee.assert_not_called()
            # The parent dir is created so the external writer can write there.
            self.assertTrue(expected.parent.is_dir())

    def test_print_prompt_path_needs_no_prompt_file(self):
        """The query short-circuits before the prompt-file requirement, so a
        caller can ask for the path before constructing the prompt."""
        import io
        import tempfile
        from contextlib import redirect_stdout
        from unittest.mock import patch

        import spawn_teammate

        with tempfile.TemporaryDirectory() as tmp:
            smm_dir = str(Path(tmp) / "deadbeefcafe" / "smm")
            buf = io.StringIO()
            with (
                patch.object(spawn_teammate, "create_worktree"),
                patch.object(spawn_teammate, "run_with_tee"),
                redirect_stdout(buf),
            ):
                # No --prompt-file passed; must not raise SystemExit from argparse.
                spawn_teammate.main(
                    [
                        "--print-prompt-path",
                        "--name",
                        "worktree-story-005",
                        "--smm-dir",
                        smm_dir,
                    ]
                )
            self.assertTrue(
                buf.getvalue().strip().endswith("worktree-story-005.prompt.txt")
            )

    def test_print_prompt_path_raises_on_mkdir_failure(self):
        """The prompt dir is REQUIRED by the external writer (unlike the log dir,
        which run_with_tee degrades around). If its parent cannot be created, the
        query must fail loud with the path-named OSError — NOT swallow it and
        print a path the writer will then fail to write to."""
        import io
        import uuid
        from contextlib import redirect_stdout

        import spawn_teammate

        # Force mkdir failure: occupy the per-project prompt-dir path with a
        # regular FILE, so mkdir(parents=True, exist_ok=True) raises.
        token = f"mkdir-fail-{uuid.uuid4().hex}"
        smm_dir = f"/data/{token}/smm"
        blocker = spawn_teammate.project_prompt_path(
            smm_dir, "x", sprint_id=None
        ).parent
        blocker.parent.mkdir(parents=True, exist_ok=True)
        blocker.write_text("occupied")
        try:
            buf = io.StringIO()
            with self.assertRaises(OSError), redirect_stdout(buf):
                spawn_teammate.main(
                    [
                        "--print-prompt-path",
                        "--name",
                        "worktree-story-005",
                        "--smm-dir",
                        smm_dir,
                    ]
                )
        finally:
            blocker.unlink(missing_ok=True)


class TestSpawnResolvesPromptPath(unittest.TestCase):
    """A real spawn with NO --prompt-file must resolve the deterministic
    project_prompt_path itself. /xp-assign queries --print-prompt-path and
    Writes the prompt there, then spawns in a SEPARATE Bash tool call where a
    threaded shell variable would be empty — so spawn_teammate must derive the
    same path from --name + --smm-dir rather than depend on a passed value.
    """

    def test_real_spawn_reads_deterministic_prompt_path(self):
        import tempfile
        from unittest.mock import patch

        import spawn_teammate

        captured = {}

        def capture_tee(cmd, *, cwd=None, env=None, stdin=None, name=None, **kw):
            captured["stdin"] = stdin.read() if stdin is not None else ""

        with tempfile.TemporaryDirectory() as tmp:
            smm_dir = str(Path(tmp) / "8e1f07eb0759" / "smm")
            name = "worktree-story-007"
            prompt_path = spawn_teammate.project_prompt_path(
                smm_dir, name, sprint_id=None
            )
            prompt_path.parent.mkdir(parents=True, exist_ok=True)
            prompt_path.write_text("DETERMINISTIC PROMPT BODY")

            with (
                patch.object(spawn_teammate, "create_worktree", return_value="/tmp/wt"),
                patch.object(spawn_teammate, "run_with_tee", side_effect=capture_tee),
            ):
                # No --prompt-file: spawn must resolve project_prompt_path itself.
                spawn_teammate.main(["--name", name, "--smm-dir", smm_dir])

            self.assertIn("DETERMINISTIC PROMPT BODY", captured.get("stdin", ""))
            # The consumed prompt is unlinked on a clean run.
            self.assertFalse(prompt_path.exists())


if __name__ == "__main__":
    unittest.main()
