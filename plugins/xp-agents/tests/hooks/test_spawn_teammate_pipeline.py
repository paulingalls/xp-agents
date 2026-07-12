#!/usr/bin/env python3
"""Tests for spawn_teammate.py prompt + stdout pipeline.

Covers _worktree_preamble (stdin prefix) and run_with_tee (stdout
mirroring + nonzero-exit propagation).

Why a separate file: test_spawn_teammate.py grew past the project's
500-line budget after the watchdog split. The preamble + tee tests are
a cohesive pipeline subset that splits cleanly along feature lines.
"""

import subprocess
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


class TestWorktreePreamble(unittest.TestCase):
    """_worktree_preamble injects worktree-context guidance ahead of the
    teammate prompt body, so the teammate sees the path-rerooting rule
    before any potentially misleading absolute paths the lead embedded.
    """

    def test_preamble_includes_worktree_path(self):
        """The actual worktree path appears verbatim in the preamble."""
        import spawn_teammate

        text = spawn_teammate._worktree_preamble("/some/wt/path")
        self.assertIn("/some/wt/path", text)

    def test_preamble_instructs_path_rerooting(self):
        """Preamble names the rule (re-root absolute paths to the worktree)."""
        import spawn_teammate

        text = spawn_teammate._worktree_preamble("/some/wt/path")
        self.assertIn("worktree", text.lower())
        self.assertIn("RELATIVE", text)
        self.assertIn("Re-root", text)

    def test_preamble_distinguishes_smm_from_worktree(self):
        """Preamble exempts the SMM dir from the re-rooting rule."""
        import spawn_teammate

        text = spawn_teammate._worktree_preamble("/some/wt/path")
        self.assertIn("SMM", text)
        self.assertIn("OUTSIDE", text)

    def test_preamble_derives_main_repo_from_worktree_layout(self):
        """main_repo path is derived from wt_path's <repo>/.claude/worktrees/<name>
        layout — not hardcoded to any platform-specific prefix."""
        import spawn_teammate

        text = spawn_teammate._worktree_preamble(
            "/some/repo/.claude/worktrees/worktree-story-005"
        )
        # main_repo is wt_path.parent.parent.parent
        self.assertIn("/some/repo", text)
        # No macOS-specific assumption baked in.
        self.assertNotIn("/Users/", text)

    def test_preamble_lands_first_in_stdin(self):
        """main() prepends the preamble before the prompt body in stdin."""
        import tempfile
        from unittest.mock import patch

        import spawn_teammate

        captured = {}
        wt = "/tmp/repo/.claude/worktrees/worktree-story-005"

        def capture_tee(cmd, *, cwd=None, env=None, stdin=None, name=None, **kw):
            assert stdin is not None
            captured["stdin_text"] = stdin.read()

        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("PROMPT_BODY_MARKER")
            prompt_path = f.name

        try:
            with (
                patch.object(spawn_teammate, "create_worktree", return_value=wt),
                patch.object(spawn_teammate, "run_with_tee", side_effect=capture_tee),
            ):
                spawn_teammate.main(
                    [
                        "--name",
                        "worktree-story-005",
                        "--smm-dir",
                        "/tmp/smm",
                        "--prompt-file",
                        prompt_path,
                    ]
                )
        finally:
            Path(prompt_path).unlink(missing_ok=True)

        text = captured["stdin_text"]
        # Preamble at position 0, prompt body strictly after.
        expected_preamble = spawn_teammate._worktree_preamble(wt)
        self.assertTrue(
            text.startswith(expected_preamble),
            "stdin must begin with the preamble verbatim",
        )
        self.assertIn("PROMPT_BODY_MARKER", text)
        self.assertLess(text.index(wt), text.index("PROMPT_BODY_MARKER"))

    def test_unlink_preserved_after_spawn(self):
        """The original prompt file is still removed after main() runs."""
        import tempfile
        from unittest.mock import patch

        import spawn_teammate

        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("body")
            prompt_path = f.name

        try:
            with (
                patch.object(spawn_teammate, "create_worktree", return_value="/tmp/wt"),
                # return_value=False → clean run (stdout not broken); the prompt
                # is consumed and unlinked. A bare Mock would default-return a
                # truthy value, misreading as stdout_broken and preserving it.
                patch.object(spawn_teammate, "run_with_tee", return_value=False),
            ):
                spawn_teammate.main(
                    [
                        "--name",
                        "worktree-story-005",
                        "--smm-dir",
                        "/tmp/smm",
                        "--prompt-file",
                        prompt_path,
                    ]
                )
            self.assertFalse(Path(prompt_path).exists())
        finally:
            Path(prompt_path).unlink(missing_ok=True)

    def test_prompt_file_preserved_on_failure(self):
        """When run_with_tee raises CalledProcessError, the original
        prompt file must survive so the orchestrator can re-spawn the
        teammate without reconstructing the prompt."""
        import tempfile
        from unittest.mock import patch

        import spawn_teammate

        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("body")
            prompt_path = f.name

        try:
            with (
                patch.object(spawn_teammate, "create_worktree", return_value="/tmp/wt"),
                patch.object(
                    spawn_teammate,
                    "run_with_tee",
                    side_effect=subprocess.CalledProcessError(2, ["fake"]),
                ),
                self.assertRaises(subprocess.CalledProcessError),
            ):
                spawn_teammate.main(
                    [
                        "--name",
                        "worktree-story-005",
                        "--smm-dir",
                        "/tmp/smm",
                        "--prompt-file",
                        prompt_path,
                    ]
                )
            self.assertTrue(
                Path(prompt_path).exists(),
                "prompt_file must survive subprocess failure for re-spawn",
            )
        finally:
            Path(prompt_path).unlink(missing_ok=True)


class TestRunWithTee(unittest.TestCase):
    """run_with_tee mirrors claude -p stdout to <log_dir>/<name>.log
    so a hung teammate can be inspected without aborting the run.
    """

    def setUp(self):
        import tempfile

        self.log_dir = Path(tempfile.mkdtemp())

    def _fake_popen(self, lines: list[str], returncode: int = 0):
        from unittest.mock import MagicMock

        fake = MagicMock()
        fake.stdout = iter(lines)
        fake.returncode = returncode
        return fake

    def test_tees_stdout_to_log_file(self):
        """Each line streamed from the subprocess is mirrored to the log file."""
        from unittest.mock import patch

        import spawn_teammate

        with patch(
            "spawn_teammate.subprocess.Popen",
            return_value=self._fake_popen(["line1\n", "line2\n"]),
        ):
            spawn_teammate.run_with_tee(
                ["fake"],
                cwd=".",
                env={},
                stdin=None,
                name="teammate-foo",
                log_dir=self.log_dir,
            )
        log = (self.log_dir / "teammate-foo.log").read_text()
        self.assertIn("line1\nline2\n", log)
        self.assertIn("spawn teammate-foo", log)

    def test_respawn_appends_does_not_truncate(self):
        """A second spawn with the same name preserves the prior run's log —
        forensic value would be lost if the first run hung and the kill+respawn
        truncated the only record of where it stuck."""
        from unittest.mock import patch

        import spawn_teammate

        with patch(
            "spawn_teammate.subprocess.Popen",
            return_value=self._fake_popen(["first-run-line\n"]),
        ):
            spawn_teammate.run_with_tee(
                ["fake"],
                cwd=".",
                env={},
                stdin=None,
                name="teammate-foo",
                log_dir=self.log_dir,
            )
        with patch(
            "spawn_teammate.subprocess.Popen",
            return_value=self._fake_popen(["second-run-line\n"]),
        ):
            spawn_teammate.run_with_tee(
                ["fake"],
                cwd=".",
                env={},
                stdin=None,
                name="teammate-foo",
                log_dir=self.log_dir,
            )
        log = (self.log_dir / "teammate-foo.log").read_text()
        self.assertIn("first-run-line", log)
        self.assertIn("second-run-line", log)
        # Order matters: prior-run output must precede current-run output,
        # otherwise a regression that truncates+rewrites could still pass.
        self.assertLess(log.index("first-run-line"), log.index("second-run-line"))

    def test_proceeds_without_log_when_dir_unwritable(self):
        """Unwritable log dir does NOT abort the spawn — degrades gracefully."""
        from unittest.mock import patch

        import spawn_teammate

        bad_dir = Path("/proc/no-such-dir-here-x")  # unwritable
        with patch(
            "spawn_teammate.subprocess.Popen",
            return_value=self._fake_popen(["x\n"]),
        ):
            spawn_teammate.run_with_tee(
                ["fake"],
                cwd=".",
                env={},
                stdin=None,
                name="teammate-foo",
                log_dir=bad_dir,
            )
        # No exception raised; that's the contract.

    def test_nonzero_exit_raises_called_process_error(self):
        """Subprocess returncode != 0 surfaces as CalledProcessError so the
        spawn caller sees a real failure (matches the prior subprocess.run
        check=True semantics)."""
        from unittest.mock import patch

        import spawn_teammate

        with (
            patch(
                "spawn_teammate.subprocess.Popen",
                return_value=self._fake_popen(["x\n"], returncode=2),
            ),
            self.assertRaises(subprocess.CalledProcessError),
        ):
            spawn_teammate.run_with_tee(
                ["fake"],
                cwd=".",
                env={},
                stdin=None,
                name="teammate-foo",
                log_dir=self.log_dir,
            )


if __name__ == "__main__":
    unittest.main()
