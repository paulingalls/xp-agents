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

from conftest import _IntegrationTestCase, _SMMTestCase


def _raise_called_process_error(*_args, **_kwargs):
    """Side-effect callable that simulates a non-zero subprocess exit."""
    raise subprocess.CalledProcessError(2, ["fake"])


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

    def test_includes_partial_messages_flag(self):
        """--include-partial-messages enables per-token streaming so the
        liveness watchdog sees mtime ticks during real model output;
        without it, only block-completion events fire (1-4 lines per
        message) and legitimate text/tool_use generation looks identical
        to a hang."""
        import spawn_teammate

        cmd = spawn_teammate.build_command(name="teammate-step-1")
        self.assertIn("--include-partial-messages", cmd)


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
                    side_effect=_raise_called_process_error,
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


class TestMechanicalPromote(_SMMTestCase):
    """Story-004: spawn_teammate.main() promotes the story to `reviewing`
    after a clean teammate exit (rc=0). On rc!=0 the teammate stays
    `in-progress` for debug. The promote is mechanical — no LLM
    judgment, no prompt-template instruction; the wrapper does it.

    Story-002 (sprint-068): the get_story → update_story_status pair
    was replaced with a single atomic update_story_status_if CAS —
    these tests assert against the CAS callsite, not the legacy pair.
    """

    def _make_prompt_file(self):
        import tempfile

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".prompt.txt", delete=False
        ) as f:
            f.write("body")
            return f.name

    def _run_promote(
        self,
        *,
        story_id: str | None = "story-001",
        cas_return: bool = True,
        run_with_tee_side_effect=None,
    ) -> list[tuple[str, str, str, str]]:
        """Run spawn_teammate.main with stubbed worktree+subprocess+sprint
        and return the captured update_story_status_if calls as
        (smm_dir, story_id, expected, new) tuples.

        story_id=None omits --story-id (ad-hoc teammate).
        cas_return controls what the patched CAS returns (True=updated,
        False=expected mismatch — actual already advanced past expected).
        run_with_tee_side_effect raises if you want rc!=0 simulation.
        """
        from unittest.mock import patch

        import spawn_teammate

        prompt_path = self._make_prompt_file()
        captured_calls: list[tuple[str, str, str, str]] = []

        def fake_cas(smm_dir, sid, *, expected, new):
            captured_calls.append((str(smm_dir), sid, expected, new))
            return cas_return

        argv = [
            "--name",
            "worktree-story-001" if story_id else "worktree-foo",
            "--smm-dir",
            str(self.smm_dir),
            "--prompt-file",
            prompt_path,
        ]
        if story_id is not None:
            argv += ["--story-id", story_id]

        try:
            with (
                patch.object(spawn_teammate, "create_worktree", return_value="/tmp/wt"),
                patch.object(
                    spawn_teammate,
                    "run_with_tee",
                    side_effect=run_with_tee_side_effect,
                ),
                patch.object(
                    spawn_teammate.sprint_store,
                    "update_story_status_if",
                    side_effect=fake_cas,
                ),
            ):
                spawn_teammate.main(argv)
        finally:
            Path(prompt_path).unlink(missing_ok=True)

        return captured_calls

    def test_promotes_to_reviewing_on_rc_0(self):
        """Successful teammate (rc=0) triggers a single CAS in-progress→reviewing."""
        captured = self._run_promote()
        self.assertEqual(
            captured,
            [(str(self.smm_dir), "story-001", "in-progress", "reviewing")],
            f"expected single CAS call (in-progress→reviewing), got: {captured!r}",
        )

    def test_cas_returns_false_does_not_raise(self):
        """When the CAS sees actual!=expected (concurrent advance to
        done/deferred), spawn_teammate accepts the no-op silently — the
        caller's job was 'try to promote', not 'demand promotion'.
        Pins close-reviewer concern 3ba0b6237c65 end-to-end."""
        captured = self._run_promote(cas_return=False)
        self.assertEqual(
            captured,
            [(str(self.smm_dir), "story-001", "in-progress", "reviewing")],
            "CAS must still be invoked even when it returns False",
        )

    def test_does_not_promote_on_rc_nonzero(self):
        """Failed teammate (rc!=0) leaves story in-progress for debug —
        the CAS is never invoked because the exception propagates first."""
        with self.assertRaises(subprocess.CalledProcessError):
            self._run_promote(run_with_tee_side_effect=_raise_called_process_error)

    def test_does_not_promote_when_story_id_absent(self):
        """No --story-id → no CAS attempted (ad-hoc teammates without
        sprint context just exit cleanly)."""
        captured = self._run_promote(story_id=None)
        self.assertEqual(captured, [], f"unexpected CAS without story-id: {captured!r}")


class TestNoSysPathInsert(unittest.TestCase):
    """Story-002 (sprint-068): spawn_teammate.py must not poke sys.path
    at module load. The marketplace cache layout
    (~/.claude/plugins/cache/xp-agents/xp-agents/<version>/scripts/) was
    never tested with the prior `Path(__file__).resolve().parent` insert,
    and the .resolve() call would dereference any cache-side symlink and
    point smm/ at the wrong location. The fix: rely on Python's
    automatic script-dir-on-sys.path[0] for sibling imports, and import
    a sibling that already arranges smm/ on sys.path as a side effect.
    """

    _SCRIPT = Path(__file__).parent.parent.parent / "scripts" / "spawn_teammate.py"

    def test_source_has_no_sys_path_insert(self):
        """grep-style guard: spawn_teammate.py contains zero
        sys.path.insert lines. Mirrors the acceptance command exactly so a
        regression that adds the line back trips this test before close."""
        source = self._SCRIPT.read_text(encoding="utf-8")
        offending = [ln for ln in source.splitlines() if "sys.path.insert" in ln]
        self.assertEqual(
            offending,
            [],
            f"spawn_teammate.py must not poke sys.path: {offending!r}",
        )

    def test_imports_cleanly_with_only_scripts_on_path(self):
        """Run spawn_teammate.py as a subprocess with --help, with NO
        external sys.path manipulation. Python auto-adds the script's
        parent (scripts/) to sys.path[0]; the script must arrange its
        own access to smm/ without sys.path.insert. argparse's --help
        exits 0 after argv parsing, which only succeeds if every
        top-level import resolved."""
        r = subprocess.run(
            [sys.executable, str(self._SCRIPT), "--help"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(
            r.returncode,
            0,
            f"spawn_teammate.py --help failed (likely an import error):\n"
            f"--- stdout ---\n{r.stdout}\n--- stderr ---\n{r.stderr}",
        )


class TestActivityWatchdog(unittest.TestCase):
    """_ActivityWatchdog terminates a subprocess that goes silent.

    Why this exists: a spawned `claude -p` can block indefinitely inside
    an HTTPS POST to the model API (observed in concern e1a8f7e17d84
    where a teammate produced zero output for 31 minutes overnight).
    The watchdog runs in a thread alongside the run_with_tee main loop,
    which calls .ping() on each line read; if pings stop for longer
    than the timeout, the watchdog terminates the subprocess so the
    main loop sees stdout EOF and the existing CalledProcessError
    recovery path takes over.

    Tests use a tiny FakeProc with terminate/kill/wait counters rather
    than MagicMock — the assertions are about which methods were called
    and in what order, which is easier to verify with explicit fields.
    """

    class _FakeProc:
        """Minimal stand-in for subprocess.Popen."""

        def __init__(
            self,
            *,
            terminate_raises: bool = False,
            wait_raises_timeout: bool = False,
        ):
            self.terminate_calls = 0
            self.kill_calls = 0
            self.wait_calls = 0
            self._terminate_raises = terminate_raises
            self._wait_raises_timeout = wait_raises_timeout

        def terminate(self) -> None:
            self.terminate_calls += 1
            if self._terminate_raises:
                raise OSError("simulated terminate failure")

        def wait(self, timeout: float | None = None) -> int:
            self.wait_calls += 1
            if self._wait_raises_timeout:
                raise subprocess.TimeoutExpired(cmd=["fake"], timeout=timeout or 0)
            return 0

        def kill(self) -> None:
            self.kill_calls += 1

    def _make_watchdog(self, proc, timeout_s: float = 1.0):
        import spawn_teammate

        return spawn_teammate._ActivityWatchdog(
            proc, name="test", timeout_s=timeout_s, poll_interval_s=0.05
        )

    def test_terminates_after_timeout_with_no_ping(self):
        """No pings → watchdog calls proc.terminate() once after timeout
        elapses. This is the core failure-detection path."""
        import time as _t

        proc = self._FakeProc()
        wd = self._make_watchdog(proc, timeout_s=0.3)
        wd.start()
        _t.sleep(0.6)
        wd.stop()
        self.assertEqual(proc.terminate_calls, 1)

    def test_does_not_terminate_when_pinged_within_timeout(self):
        """Steady pings keep the watchdog quiet — covers the legitimate
        long-thinking case where the spawned subprocess is producing
        stream-event lines and the main loop pings on each one."""
        import time as _t

        proc = self._FakeProc()
        wd = self._make_watchdog(proc, timeout_s=0.3)
        wd.start()
        for _ in range(8):
            _t.sleep(0.1)
            wd.ping()
        wd.stop()
        self.assertEqual(proc.terminate_calls, 0)

    def test_stop_prevents_termination(self):
        """Calling .stop() before the timeout fires — the normal
        completion path — must not call terminate()."""
        import time as _t

        proc = self._FakeProc()
        wd = self._make_watchdog(proc, timeout_s=0.3)
        wd.start()
        wd.stop()
        _t.sleep(0.6)
        self.assertEqual(proc.terminate_calls, 0)
        self.assertEqual(proc.kill_calls, 0)

    def test_terminate_failure_does_not_propagate(self):
        """If proc.terminate() raises (e.g. process already exited), the
        watchdog thread must not crash — it has no exception channel
        back to the parent and a crash would leak the silence
        condition."""
        import time as _t

        proc = self._FakeProc(terminate_raises=True)
        wd = self._make_watchdog(proc, timeout_s=0.3)
        wd.start()
        _t.sleep(0.6)
        wd.stop()
        self.assertEqual(proc.terminate_calls, 1)

    def test_escalates_to_kill_when_terminate_does_not_exit(self):
        """SIGTERM may be ignored when the child is blocked in a C-level
        recv() (the suspected hang mode). After a 10s grace, the
        watchdog must escalate to SIGKILL or the recovery never fires."""
        import time as _t

        proc = self._FakeProc(wait_raises_timeout=True)
        wd = self._make_watchdog(proc, timeout_s=0.3)
        wd.start()
        _t.sleep(0.6)
        wd.stop()
        self.assertEqual(proc.terminate_calls, 1)
        self.assertEqual(proc.kill_calls, 1)


if __name__ == "__main__":
    unittest.main()
