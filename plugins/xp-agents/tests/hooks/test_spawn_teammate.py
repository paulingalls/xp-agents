#!/usr/bin/env python3
"""Tests for spawn_teammate.py — CLI teammate launcher.

Covers: cleanup_existing, create_worktree, build_command, parse_args.
"""

import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from conftest import _IntegrationTestCase


class TestBuildCommand(unittest.TestCase):
    """build_command constructs correct claude -p arguments."""

    def test_basic_command_flags(self):
        """Command includes --name, --dangerously-skip-permissions, --output-format."""
        import spawn_teammate

        cmd = spawn_teammate.build_command(name="teammate-step-1")
        self.assertIn("claude", cmd[0])
        self.assertIn("-p", cmd)
        self.assertIn("--name", cmd)
        idx = cmd.index("--name")
        self.assertEqual(cmd[idx + 1], "teammate-step-1")
        self.assertIn("--dangerously-skip-permissions", cmd)
        self.assertIn("--output-format", cmd)
        idx = cmd.index("--output-format")
        self.assertEqual(cmd[idx + 1], "stream-json")
        self.assertIn("--verbose", cmd)

    def test_includes_allowed_tools(self):
        """Command includes --allowedTools with expected tools."""
        import spawn_teammate

        cmd = spawn_teammate.build_command(name="teammate-step-1")
        self.assertIn("--allowedTools", cmd)
        idx = cmd.index("--allowedTools")
        tools = cmd[idx + 1]
        for tool in ("Read", "Write", "Edit", "Bash", "Grep", "Glob", "Skill"):
            self.assertIn(tool, tools)

    def test_no_plugin_dir_flag(self):
        """Command does not include --plugin-dir (teammate inherits via SMM_DIR env)."""
        import spawn_teammate

        cmd = spawn_teammate.build_command(name="teammate-step-1")
        self.assertNotIn("--plugin-dir", cmd)

    def test_no_input_file_flag(self):
        """Command does not include --input-file (prompt piped via stdin)."""
        import spawn_teammate

        cmd = spawn_teammate.build_command(name="teammate-step-1")
        self.assertNotIn("--input-file", cmd)


class TestStoryIdArg(unittest.TestCase):
    """--story-id CLI arg for story attribution."""

    def test_story_id_optional(self):
        """--story-id defaults to None when not provided."""
        import spawn_teammate

        args = spawn_teammate.parse_args(
            ["--name", "t1", "--smm-dir", "/smm", "--prompt-file", "/p.txt"]
        )
        self.assertIsNone(args.story_id)

    def test_story_id_accepted(self):
        """--story-id is accepted and stored."""
        import spawn_teammate

        args = spawn_teammate.parse_args(
            [
                "--name",
                "t1",
                "--smm-dir",
                "/smm",
                "--prompt-file",
                "/p.txt",
                "--story-id",
                "story-001",
            ]
        )
        self.assertEqual(args.story_id, "story-001")


class TestBranchArg(unittest.TestCase):
    """--branch CLI arg for story branch checkout."""

    def test_branch_arg_optional(self):
        """--branch defaults to None when not provided."""
        import spawn_teammate

        args = spawn_teammate.parse_args(
            ["--name", "t1", "--smm-dir", "/smm", "--prompt-file", "/p.txt"]
        )
        self.assertIsNone(args.branch)

    def test_branch_arg_accepted(self):
        """--branch is accepted and stored."""
        import spawn_teammate

        args = spawn_teammate.parse_args(
            [
                "--name",
                "t1",
                "--smm-dir",
                "/smm",
                "--prompt-file",
                "/p.txt",
                "--branch",
                "paulingalls/story-001-schema-store",
            ]
        )
        self.assertEqual(args.branch, "paulingalls/story-001-schema-store")


class TestStoryAssignmentFile(_IntegrationTestCase):
    """spawn_teammate writes .story-assignment-{name} to SMM dir."""

    def test_writes_story_assignment_when_provided(self):
        """Story assignment file written with correct content."""
        import spawn_teammate
        import worktree

        name = "teammate-step-1"
        assignment = worktree.story_assignment_path(self.smm_dir, name)
        spawn_teammate.write_story_assignment(self.smm_dir, name, "story-001")
        self.assertTrue(assignment.exists())
        self.assertEqual(assignment.read_text().strip(), "story-001")

    def test_no_file_when_story_id_none(self):
        """No story assignment file created when story_id is None."""
        import spawn_teammate
        import worktree

        name = "teammate-step-2"
        assignment = worktree.story_assignment_path(self.smm_dir, name)
        spawn_teammate.write_story_assignment(self.smm_dir, name, None)
        self.assertFalse(assignment.exists())


class TestStoryAssignmentSubprocess(unittest.TestCase):
    """write_story_assignment must work when only scripts/ is on sys.path."""

    def test_write_story_assignment_isolated_import(self):
        """Reproduce: spawn_teammate adds only scripts/ to sys.path.

        worktree.write_story_assignment imports _append_impl from smm/.
        Without smm/ on sys.path, this raises ModuleNotFoundError.
        """
        scripts_dir = str(Path(__file__).parent.parent.parent / "scripts")
        r = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "import sys, tempfile\n"
                    f"sys.path.insert(0, {scripts_dir!r})\n"
                    "import worktree\n"
                    "from pathlib import Path\n"
                    "td = tempfile.mkdtemp()\n"
                    "worktree.write_story_assignment(Path(td), 'test', 'story-001')\n"
                    "print((Path(td) / '.story-assignment-test').read_text())\n"
                    "import shutil; shutil.rmtree(td)\n"
                ),
            ],
            capture_output=True,
            text=True,
        )
        self.assertEqual(r.returncode, 0, f"Failed: {r.stderr}")
        self.assertEqual(r.stdout.strip(), "story-001")


class TestTeammateIdRemoved(unittest.TestCase):
    """TEAMMATE_ID env var should not be set."""

    def test_no_teammate_id_in_env_setup(self):
        """spawn_teammate source code should not set TEAMMATE_ID."""
        import inspect

        import spawn_teammate

        source = inspect.getsource(spawn_teammate.main)
        self.assertNotIn("TEAMMATE_ID", source)


class TestTeammateNameEnvVar(unittest.TestCase):
    """spawn_teammate sets XP_TEAMMATE_NAME env var for teammate detection."""

    def test_env_includes_xp_teammate_name(self):
        """XP_TEAMMATE_NAME is set to the name passed via --name."""
        import tempfile
        from unittest.mock import patch

        import spawn_teammate

        captured_env = {}

        def capture_tee(cmd, *, cwd=None, env=None, stdin=None, name=None, **kw):
            if env and "XP_TEAMMATE_NAME" in env:
                captured_env.update(env)

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
                        "/tmp/smm",
                        "--prompt-file",
                        prompt_path,
                    ]
                )
            self.assertEqual(captured_env.get("XP_TEAMMATE_NAME"), "worktree-story-001")
        finally:
            Path(prompt_path).unlink(missing_ok=True)


class TestNamePassThrough(unittest.TestCase):
    """spawn_teammate uses --name as-is (no prefix transformation)."""

    def test_name_used_directly_in_main(self):
        """--name worktree-story-001 flows through without transformation."""
        import tempfile
        from unittest.mock import patch

        import spawn_teammate

        captured_name = {}

        def capture_create(name, cwd, *, branch=None):
            captured_name["value"] = name
            return "/tmp/wt"

        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("test prompt")
            prompt_path = f.name

        try:
            with (
                patch.object(
                    spawn_teammate, "create_worktree", side_effect=capture_create
                ),
                patch.object(spawn_teammate, "run_with_tee"),
            ):
                spawn_teammate.main(
                    [
                        "--name",
                        "worktree-story-001",
                        "--smm-dir",
                        "/tmp/smm",
                        "--prompt-file",
                        prompt_path,
                    ]
                )
            self.assertEqual(captured_name["value"], "worktree-story-001")
        finally:
            Path(prompt_path).unlink(missing_ok=True)


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
                patch.object(spawn_teammate, "run_with_tee"),
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


class TestMechanicalPromote(unittest.TestCase):
    """Story-004: spawn_teammate.main() promotes the story to `reviewing`
    after a clean teammate exit (rc=0). On rc!=0 the teammate stays
    `in-progress` for debug. The promote is mechanical — no LLM
    judgment, no prompt-template instruction; the wrapper does it."""

    def _make_prompt_file(self):
        import tempfile

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".prompt.txt", delete=False
        ) as f:
            f.write("body")
            return f.name

    def test_promotes_to_reviewing_on_rc_0(self):
        """Successful teammate (rc=0) triggers update_story_status to reviewing."""
        from unittest.mock import patch

        import spawn_teammate

        prompt_path = self._make_prompt_file()
        captured_calls = []

        def fake_promote(smm_dir, story_id, status):
            captured_calls.append((str(smm_dir), story_id, status))

        try:
            with (
                patch.object(spawn_teammate, "create_worktree", return_value="/tmp/wt"),
                patch.object(spawn_teammate, "run_with_tee"),  # rc=0 path
                patch.object(
                    spawn_teammate.sprint_store,
                    "update_story_status",
                    side_effect=fake_promote,
                ),
            ):
                spawn_teammate.main(
                    [
                        "--name",
                        "worktree-story-001",
                        "--smm-dir",
                        "/tmp/smm",
                        "--prompt-file",
                        prompt_path,
                        "--story-id",
                        "story-001",
                    ]
                )
        finally:
            Path(prompt_path).unlink(missing_ok=True)

        self.assertEqual(
            captured_calls,
            [("/tmp/smm", "story-001", "reviewing")],
            f"expected single reviewing-promote call, got: {captured_calls!r}",
        )

    def test_does_not_promote_on_rc_nonzero(self):
        """Failed teammate (rc!=0) leaves story in-progress for debug."""
        from unittest.mock import patch

        import spawn_teammate

        prompt_path = self._make_prompt_file()
        captured_calls = []

        def fake_promote(smm_dir, story_id, status):
            captured_calls.append((str(smm_dir), story_id, status))

        def raise_failure(*a, **kw):
            raise subprocess.CalledProcessError(2, ["fake"])

        try:
            with (
                patch.object(spawn_teammate, "create_worktree", return_value="/tmp/wt"),
                patch.object(spawn_teammate, "run_with_tee", side_effect=raise_failure),
                patch.object(
                    spawn_teammate.sprint_store,
                    "update_story_status",
                    side_effect=fake_promote,
                ),
                self.assertRaises(subprocess.CalledProcessError),
            ):
                spawn_teammate.main(
                    [
                        "--name",
                        "worktree-story-001",
                        "--smm-dir",
                        "/tmp/smm",
                        "--prompt-file",
                        prompt_path,
                        "--story-id",
                        "story-001",
                    ]
                )
        finally:
            Path(prompt_path).unlink(missing_ok=True)

        self.assertEqual(
            captured_calls,
            [],
            f"unexpected promote on failure: {captured_calls!r}",
        )

    def test_does_not_promote_when_story_id_absent(self):
        """No --story-id → no promote attempted (ad-hoc teammates without
        sprint context just exit cleanly)."""
        from unittest.mock import patch

        import spawn_teammate

        prompt_path = self._make_prompt_file()
        captured_calls = []

        def fake_promote(smm_dir, story_id, status):
            captured_calls.append((str(smm_dir), story_id, status))

        try:
            with (
                patch.object(spawn_teammate, "create_worktree", return_value="/tmp/wt"),
                patch.object(spawn_teammate, "run_with_tee"),
                patch.object(
                    spawn_teammate.sprint_store,
                    "update_story_status",
                    side_effect=fake_promote,
                ),
            ):
                spawn_teammate.main(
                    [
                        "--name",
                        "worktree-foo",
                        "--smm-dir",
                        "/tmp/smm",
                        "--prompt-file",
                        prompt_path,
                    ]
                )
        finally:
            Path(prompt_path).unlink(missing_ok=True)

        self.assertEqual(
            captured_calls,
            [],
            f"unexpected promote without story-id: {captured_calls!r}",
        )


if __name__ == "__main__":
    unittest.main()
