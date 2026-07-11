#!/usr/bin/env python3
"""Tests for spawn_teammate.py — CLI teammate launcher.

Covers: build_command flag shape, --name pass-through, worktree cleanup,
story-assignment env wiring, mechanical promote on clean exit, and the
no-sys.path.insert guard. CLI argument plumbing (--story-id / --branch /
--model / --plugin-dir parse_args + flow-through) lives in
test_spawn_teammate_args.py; prompt + stdout pipeline tests live in
test_spawn_teammate_pipeline.py; liveness watchdog tests live in
test_spawn_teammate_watchdog.py.
"""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from _bases import _AssertNotNoneMixin
from conftest import _IntegrationTestCase, _SMMTestCase, dead_pid, live_pid


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

    def test_omits_plugin_dir_when_not_provided(self):
        """No --plugin-dir when none is passed."""
        import spawn_teammate

        cmd = spawn_teammate.build_command(name="teammate-step-1")
        self.assertNotIn("--plugin-dir", cmd)

    def test_includes_plugin_dir_when_provided(self):
        """--plugin-dir <path> is appended when given, so the headless
        teammate session loads the xp-agents plugin (and its skills, agents,
        and hooks). Without it the worktree session loads none of them —
        project-scoped marketplace enablement is not applied there."""
        import spawn_teammate

        cmd = spawn_teammate.build_command(
            name="teammate-step-1", plugin_dir="/plugins/xp-agents"
        )
        self.assertIn("--plugin-dir", cmd)
        idx = cmd.index("--plugin-dir")
        self.assertEqual(cmd[idx + 1], "/plugins/xp-agents")

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

    def test_omits_model_flag_when_not_provided(self):
        """No --model flag when model is None — teammate inherits the
        claude -p default model."""
        import spawn_teammate

        cmd = spawn_teammate.build_command(name="teammate-step-1")
        self.assertNotIn("--model", cmd)

    def test_includes_model_flag_when_provided(self):
        """--model <name> is appended when a model is passed, so a delegated
        teammate can run on a chosen tier (e.g. sonnet)."""
        import spawn_teammate

        cmd = spawn_teammate.build_command(name="teammate-step-1", model="sonnet")
        self.assertIn("--model", cmd)
        idx = cmd.index("--model")
        self.assertEqual(cmd[idx + 1], "sonnet")


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
                patch.object(spawn_teammate, "run_with_tee", return_value=False),
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
        run_with_tee_return: bool = False,
        report_exists: bool = False,
    ) -> list[tuple[str, str, str, str]]:
        """Run spawn_teammate.main with stubbed worktree+subprocess+sprint
        and return the captured update_story_status_if calls as
        (smm_dir, story_id, expected, new) tuples.

        story_id=None omits --story-id (ad-hoc teammate).
        cas_return controls what the patched CAS returns (True=updated,
        False=expected mismatch — actual already advanced past expected).
        run_with_tee_side_effect raises if you want rc!=0 simulation.
        run_with_tee_return is run_with_tee's stdout_broken flag (True means
        the downstream stdout pipe broke).
        report_exists pre-writes the teammate report file so a broken stdout is
        recognised as a benign late pipe-close (the filter wrote its report
        before exiting) rather than a filter that died before finishing.

        Also records self._prompt_existed_after: whether main() left the prompt
        file on disk (the in-progress ⇒ prompt-preserved-for-re-spawn invariant).
        """
        from unittest.mock import patch

        import spawn_teammate
        import worktree

        prompt_path = self._make_prompt_file()
        captured_calls: list[tuple[str, str, str, str]] = []
        name = "worktree-story-001" if story_id else "worktree-foo"

        if report_exists:
            worktree.teammate_report_path(self.smm_dir, name).write_text("done")

        def fake_cas(smm_dir, sid, *, expected, new):
            captured_calls.append((str(smm_dir), sid, expected, new))
            return cas_return

        argv = [
            "--name",
            name,
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
                    return_value=run_with_tee_return,
                ),
                patch.object(
                    spawn_teammate.sprint_store,
                    "update_story_status_if",
                    side_effect=fake_cas,
                ),
            ):
                spawn_teammate.main(argv)
            self._prompt_existed_after = Path(prompt_path).exists()
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
            self._run_promote(
                run_with_tee_side_effect=subprocess.CalledProcessError(2, ["fake"])
            )

    def test_does_not_promote_when_filter_died_before_report(self):
        """Filter death with NO report (stdout_broken=True, report absent) leaves
        the story in-progress: the filter that owns report/completion/
        coordination-clear never finished, so a promote to reviewing would hand
        the lead an unwritten report over stale state. The prompt is preserved
        for re-spawn."""
        captured = self._run_promote(run_with_tee_return=True, report_exists=False)
        self.assertEqual(
            captured,
            [],
            f"CAS must be skipped when the filter died pre-report, got: {captured!r}",
        )
        self.assertTrue(
            self._prompt_existed_after,
            "prompt must be preserved for re-spawn when the story stays in-progress",
        )

    def test_promotes_when_stdout_broke_but_report_written(self):
        """A stdout break AFTER the report was written is a benign late
        pipe-close (the filter writes its report, then exits and closes the
        pipe ~0.1s later). The run succeeded, so it must promote — and unlink
        the now-consumed prompt."""
        captured = self._run_promote(run_with_tee_return=True, report_exists=True)
        self.assertEqual(
            captured,
            [(str(self.smm_dir), "story-001", "in-progress", "reviewing")],
            f"a late pipe-close after a written report must promote, got: {captured!r}",
        )
        self.assertFalse(
            self._prompt_existed_after,
            "prompt must be unlinked when we promote (run succeeded)",
        )

    def test_unlinks_prompt_on_clean_promote(self):
        """A clean run (no stdout break) unlinks the consumed prompt file."""
        self._run_promote()
        self.assertFalse(
            self._prompt_existed_after,
            "prompt must be unlinked after a clean promote",
        )

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


class TestInPlaceMarker(unittest.TestCase):
    """spawn_teammate --in-place writes a lifetime-scoped in-place marker that
    commit_handling requires before trusting XP_TEAMMATE_NAME (debt 06ddcc2c8e4d).
    """

    def _run(self, name_arg, smm_dir, *, in_place):
        """Run main() with run_with_tee patched to capture marker presence
        DURING the child run. Returns (marker_present_during_run: bool)."""
        import tempfile
        from unittest.mock import patch

        import spawn_teammate
        import worktree

        seen = {}

        def capture_tee(cmd, *, cwd=None, env=None, stdin=None, name=None, **kw):
            # Check against the closed-over name (a str), not the callback's
            # name kwarg (typed str | None) — the marker is name-keyed.
            seen["during"] = worktree.in_place_marker_exists(smm_dir, name_arg)

        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("test prompt")
            prompt_path = f.name

        argv = [
            "--name",
            name_arg,
            "--smm-dir",
            str(smm_dir),
            "--prompt-file",
            prompt_path,
        ]
        if in_place:
            argv.append("--in-place")
        try:
            with (
                patch.object(spawn_teammate, "create_worktree", return_value="/tmp/wt"),
                patch.object(spawn_teammate, "run_with_tee", side_effect=capture_tee),
            ):
                spawn_teammate.main(argv)
        finally:
            Path(prompt_path).unlink(missing_ok=True)
        return seen.get("during", False)

    def test_in_place_marker_present_during_run_absent_after(self):
        """Marker is live while the in-place child runs, gone once it exits."""
        import tempfile

        import worktree

        with tempfile.TemporaryDirectory() as d:
            smm_dir = Path(d)
            during = self._run("worktree-story-001", smm_dir, in_place=True)
            self.assertTrue(during, "marker must be present during the in-place run")
            self.assertFalse(
                worktree.in_place_marker_exists(smm_dir, "worktree-story-001"),
                "marker must be removed after the in-place run (lifetime-scoped)",
            )

    def test_worktree_mode_writes_no_in_place_marker(self):
        """A normal worktree spawn never writes the in-place marker."""
        import tempfile

        with tempfile.TemporaryDirectory() as d:
            smm_dir = Path(d)
            during = self._run("worktree-story-001", smm_dir, in_place=False)
            self.assertFalse(
                during, "worktree spawns must not write the in-place marker"
            )

    def test_in_place_marker_removed_when_child_run_fails(self):
        """The lifetime-scoped marker is removed by the finally even when the
        child run raises (watchdog SIGTERM/SIGKILL → run_with_tee raises
        CalledProcessError, rc!=0 recovery). Only a SIGKILL of spawn_teammate
        ITSELF leaks the marker — a normal child failure must not."""
        import tempfile
        from unittest.mock import patch

        import spawn_teammate
        import worktree

        with tempfile.TemporaryDirectory() as d:
            smm_dir = Path(d)
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".txt", delete=False
            ) as f:
                f.write("test prompt")
                prompt_path = f.name

            def boom(*a, **kw):
                raise subprocess.CalledProcessError(1, ["claude"])

            argv = [
                "--name",
                "worktree-story-001",
                "--smm-dir",
                str(smm_dir),
                "--prompt-file",
                prompt_path,
                "--in-place",
            ]
            try:
                with (
                    patch.object(
                        spawn_teammate, "create_worktree", return_value="/tmp/wt"
                    ),
                    patch.object(spawn_teammate, "run_with_tee", side_effect=boom),
                    self.assertRaises(subprocess.CalledProcessError),
                ):
                    spawn_teammate.main(argv)
            finally:
                Path(prompt_path).unlink(missing_ok=True)

            self.assertFalse(
                worktree.in_place_marker_exists(smm_dir, "worktree-story-001"),
                "marker must be removed even when the child run fails",
            )


class TestInPlaceMarkerRecordsChildPid(_AssertNotNoneMixin, unittest.TestCase):
    """spawn_teammate is a TEE around the real teammate (the `claude` child),
    and a signal to spawn_teammate's pid does NOT propagate to that child — it
    is reparented to init and keeps running. So the marker must record the
    CHILD's pid too, or the liveness probe reaps a live teammate's marker and
    un-suppresses the accept gate mid-flight.

    This is the wiring test: run_with_tee hands the child's pid back via
    on_spawn, and spawn_teammate must fold it into the marker.
    """

    def _run(self, *, in_place: bool, child_pid: int) -> str | None:
        """Drive main() with run_with_tee stubbed to invoke on_spawn (as the
        real one does right after Popen). Returns the marker content observed
        DURING the run, or None if no marker existed."""
        import tempfile
        from unittest.mock import patch

        import spawn_teammate
        import worktree

        name = "worktree-story-001"
        seen: dict[str, str | None] = {}

        def capture_tee(cmd, *, on_spawn=None, **kw):
            if on_spawn is not None:
                on_spawn(child_pid)
            path = worktree.in_place_marker_path(self.smm_dir, name)
            seen["during"] = path.read_text() if path.is_file() else None
            return False

        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("test prompt")
            prompt_path = f.name

        argv = [
            "--name",
            name,
            "--smm-dir",
            str(self.smm_dir),
            "--prompt-file",
            prompt_path,
        ]
        if in_place:
            argv.append("--in-place")
        try:
            with (
                patch.object(spawn_teammate, "create_worktree", return_value="/tmp/wt"),
                patch.object(spawn_teammate, "run_with_tee", side_effect=capture_tee),
            ):
                spawn_teammate.main(argv)
        finally:
            Path(prompt_path).unlink(missing_ok=True)
        return seen.get("during")

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.smm_dir = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_marker_records_both_supervisor_and_child_pids(self):
        """During the run the marker lists BOTH pids, so the episode reads live
        while EITHER is alive."""
        content = self._assert_not_none(self._run(in_place=True, child_pid=424242))
        self.assertEqual(
            content.split(),
            [str(os.getpid()), "424242"],
            "marker must list the supervisor's pid AND the child's",
        )

    def test_live_child_keeps_the_marker_alive_after_the_supervisor_dies(self):
        """End-to-end of the fix: take the marker spawn_teammate actually wrote,
        then simulate the supervisor being SIGKILLed by swapping its (live) pid
        for a dead one. The child is still running, so the episode must still
        read LIVE and the marker must survive.

        Positive control below: same marker, same code path, child dead too."""
        import worktree

        with live_pid() as child:
            self._assert_not_none(self._run(in_place=True, child_pid=child))
            marker = worktree.in_place_marker_path(self.smm_dir, "worktree-story-001")
            marker.write_text(f"{dead_pid()} {child}")

            self.assertTrue(worktree.has_live_in_place_teammate(self.smm_dir))
            self.assertTrue(marker.exists(), "live child must keep its marker")

    def test_control_dead_child_lets_the_marker_go(self):
        """Positive control for the test above. Identical in every way — same
        spawn, same marker file, same probe — except the child is dead rather
        than alive. Proves the "stays live" assertion above tracks the child's
        liveness, and is not just a probe that can never go false.
        """
        import worktree

        self._assert_not_none(self._run(in_place=True, child_pid=dead_pid()))
        marker = worktree.in_place_marker_path(self.smm_dir, "worktree-story-001")
        marker.write_text(f"{dead_pid()} {dead_pid()}")

        self.assertFalse(worktree.has_live_in_place_teammate(self.smm_dir))
        self.assertFalse(marker.exists(), "fully-dead episode must be reaped")

    def test_worktree_spawn_passes_no_on_spawn_callback(self):
        """A worktree spawn writes no in-place marker, so it must not register
        the callback either — nothing to record into."""
        self.assertIsNone(self._run(in_place=False, child_pid=424242))


if __name__ == "__main__":
    unittest.main()
