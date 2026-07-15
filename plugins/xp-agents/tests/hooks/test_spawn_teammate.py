#!/usr/bin/env python3
"""Tests for spawn_teammate.py — CLI teammate launcher.

Covers: --name pass-through, worktree cleanup, story-assignment env wiring, the
force-drop record + re-spawn supersede (story-003), and the no-sys.path.insert
guard. build_command's flag-shape suite lives in test_teammate_command.py
(co-located with build_command after its move to teammate_command.py); the
mechanical promote-on-clean-exit suite lives in test_spawn_teammate_promote.py;
CLI argument plumbing (--story-id / --branch / --model / --plugin-dir parse_args
+ flow-through) lives in test_spawn_teammate_args.py; prompt + stdout pipeline
tests live in test_spawn_teammate_pipeline.py; the in-place marker lifecycle
lives in test_spawn_teammate_markers.py.
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

import _common
import event_schema
from conftest import _IntegrationTestCase, _SMMTestCase


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

        def capture_create(name, cwd, *, branch=None, smm_dir=None, story_id=None):
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


class TestForceDropRecording(_SMMTestCase):
    """story-003: a re-spawn that force-drops a genuinely-unmerged branch must
    RECORD the drop (a `debt` event), so the mark-done gate can tell an
    abandoned branch (force-dropped) apart from a shipped one (merged, then
    deleted). A successful re-create then SUPERSEDES the record (a `status`
    event carrying metadata.resolves), so the drop no longer signals abandonment.

    Real-git fixtures (like test_worktree_removal.TestRemoveWorktree): the
    force-drop path is git plumbing, not mockable branch state.
    """

    def setUp(self):
        super().setUp()
        import worktree
        from _branching_fixtures import init_repo

        worktree._clear_git_root_cache()
        self.repo = Path(tempfile.mkdtemp())
        init_repo(str(self.repo))
        self.addCleanup(self._cleanup_repo)

    def _cleanup_repo(self):
        import shutil

        import worktree
        from conftest import cleanup_test_worktrees

        cleanup_test_worktrees(self.repo)
        shutil.rmtree(self.repo, ignore_errors=True)
        worktree._clear_git_root_cache()

    # -- fixture helpers ---------------------------------------------------

    def _add_worktree(self, name: str, branch: str | None = None) -> Path:
        """Add a worktree on a NEW branch (branch defaults to the worktree name,
        the same-name shape spawn's no-branch arm owns)."""
        branch = branch or name
        wt_path = self.repo / ".claude" / "worktrees" / name
        wt_path.parent.mkdir(parents=True, exist_ok=True)
        # fmt: off
        add = [
            "git", "-C", str(self.repo), "worktree", "add", "-b", branch, str(wt_path),
        ]
        # fmt: on
        result = subprocess.run(add, capture_output=True, text=True)
        if result.returncode != 0:
            self.skipTest(f"git worktree add failed: {result.stderr}")
        return wt_path

    def _commit_in(self, path: Path, filename: str, message: str) -> str:
        (path / filename).write_text(message)
        subprocess.run(["git", "add", filename], cwd=str(path), capture_output=True)
        env = {
            **os.environ,
            "GIT_AUTHOR_NAME": "Test User",
            "GIT_AUTHOR_EMAIL": "test@test.com",
            "GIT_COMMITTER_NAME": "Test User",
            "GIT_COMMITTER_EMAIL": "test@test.com",
        }
        subprocess.run(
            ["git", "commit", "-m", message],
            cwd=str(path),
            capture_output=True,
            env=env,
        )
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(path),
            capture_output=True,
            text=True,
        ).stdout.strip()

    def _merge_into_main(self, branch: str) -> None:
        subprocess.run(
            ["git", "merge", "--no-ff", branch, "-m", f"merge {branch}"],
            cwd=str(self.repo),
            capture_output=True,
        )

    def _force_drops(self, events: list[dict]) -> list[dict]:
        return [
            e
            for e in events
            if e.get("type") == _common.DEBT
            and (e.get("metadata") or {}).get("action")
            == event_schema.DEBT_ACTION_BRANCH_FORCE_DROPPED
        ]

    def _respawns(self, events: list[dict]) -> list[dict]:
        import spawn_teammate

        return [
            e
            for e in events
            if (e.get("metadata") or {}).get("action") == spawn_teammate._RESPAWN_ACTION
        ]

    # -- tests -------------------------------------------------------------

    def test_force_drop_writes_debt_record(self):
        """AC1: force-dropping an unmerged owns_branch worktree writes exactly one
        force-drop debt record naming the branch, a non-empty tip sha, and the
        story; the branch is gone."""
        import spawn_teammate
        import worktree

        wt = self._add_worktree("worktree-story-003")
        self._commit_in(wt, "f.txt", "unmerged work")

        removal, drop_id = spawn_teammate.cleanup_existing(
            "worktree-story-003",
            str(self.repo),
            owns_branch=True,
            smm_dir=self.smm_dir,
            story_id="story-003",
        )

        self.assertEqual(removal, worktree.BranchRemoval.FORCE_DROPPED_UNMERGED)
        self.assertIsNotNone(drop_id)
        events, _ = _common.load_events_with_resolutions(self.smm_dir)
        drops = self._force_drops(events)
        self.assertEqual(len(drops), 1)
        md = drops[0]["metadata"]
        self.assertEqual(md["branch"], "worktree-story-003")
        self.assertTrue(md["dropped_sha"], "dropped_sha must be captured")
        self.assertEqual(md["story_id"], "story-003")
        self.assertEqual(drops[0]["id"], drop_id)
        self.assertNotEqual(
            0,
            subprocess.run(
                ["git", "rev-parse", "--verify", "worktree-story-003"],
                cwd=str(self.repo),
                capture_output=True,
            ).returncode,
        )

    def test_branch_and_sha_captured_before_removal(self):
        """The record's branch is the HEAD-derived ref (NOT the worktree dir name
        when they diverge) and dropped_sha is the pre-drop tip — both peeked before
        the directory (and its HEAD) vanish."""
        import spawn_teammate

        wt = self._add_worktree(
            "worktree-story-003", branch="paulingalls/story-003-slug"
        )
        sha = self._commit_in(wt, "f.txt", "unmerged work")

        _removal, _drop_id = spawn_teammate.cleanup_existing(
            "worktree-story-003",
            str(self.repo),
            owns_branch=True,
            smm_dir=self.smm_dir,
            story_id="story-003",
        )

        events, _ = _common.load_events_with_resolutions(self.smm_dir)
        md = self._force_drops(events)[0]["metadata"]
        self.assertEqual(md["branch"], "paulingalls/story-003-slug")
        self.assertEqual(md["dropped_sha"], sha)

    def test_merged_delete_writes_no_record(self):
        """AC3: a merged stale branch is DELETED_MERGED (proved, not forced), so no
        force-drop record is written."""
        import spawn_teammate
        import worktree

        wt = self._add_worktree("worktree-story-003")
        self._commit_in(wt, "f.txt", "work")
        self._merge_into_main("worktree-story-003")

        removal, drop_id = spawn_teammate.cleanup_existing(
            "worktree-story-003",
            str(self.repo),
            owns_branch=True,
            smm_dir=self.smm_dir,
            story_id="story-003",
        )

        self.assertEqual(removal, worktree.BranchRemoval.DELETED_MERGED)
        self.assertIsNone(drop_id)
        events, _ = _common.load_events_with_resolutions(self.smm_dir)
        self.assertEqual(self._force_drops(events), [])

    def test_no_smm_dir_records_nothing(self):
        """Back-compat: cleanup_existing without smm_dir still force-drops, it just
        records nothing (existing callers pass no smm_dir)."""
        import spawn_teammate
        import worktree

        wt = self._add_worktree("worktree-story-003")
        self._commit_in(wt, "f.txt", "unmerged work")

        removal, drop_id = spawn_teammate.cleanup_existing(
            "worktree-story-003", str(self.repo), owns_branch=True
        )

        self.assertEqual(removal, worktree.BranchRemoval.FORCE_DROPPED_UNMERGED)
        self.assertIsNone(drop_id)
        events, _ = _common.load_events_with_resolutions(self.smm_dir)
        self.assertEqual(self._force_drops(events), [])

    def test_successful_respawn_supersedes(self):
        """AC (permanent-block guard): create_worktree(branch=None) over a stale
        unmerged worktree drops it (R) then, once the re-add succeeds, supersedes it
        (S with resolves=[R.id]) — so R.id lands in resolved_debt_ids."""
        import spawn_teammate

        wt = self._add_worktree("worktree-story-003")
        self._commit_in(wt, "f.txt", "unmerged work")

        spawn_teammate.create_worktree(
            "worktree-story-003",
            str(self.repo),
            branch=None,
            smm_dir=self.smm_dir,
            story_id="story-003",
        )

        events, resolutions = _common.load_events_with_resolutions(self.smm_dir)
        drops = self._force_drops(events)
        respawns = self._respawns(events)
        self.assertEqual(len(drops), 1)
        self.assertEqual(len(respawns), 1)
        drop_id = drops[0]["id"]
        self.assertEqual(respawns[0]["metadata"]["resolves"], [drop_id])
        self.assertIn(drop_id, resolutions["resolved_debt_ids"])

    def test_recreate_failure_leaves_record_live(self):
        """A re-add that fails AFTER the drop leaves R live (no S) — dropped +
        re-create-failed = abandoned, so the gate keeps blocking."""
        from unittest.mock import patch

        import spawn_teammate

        wt = self._add_worktree("worktree-story-003")
        self._commit_in(wt, "f.txt", "unmerged work")

        real_run = subprocess.run

        def fail_worktree_add(cmd, **kwargs):
            if list(cmd[:3]) == ["git", "worktree", "add"]:
                raise subprocess.CalledProcessError(1, cmd)
            return real_run(cmd, **kwargs)

        with (
            patch.object(
                spawn_teammate.subprocess, "run", side_effect=fail_worktree_add
            ),
            self.assertRaises(subprocess.CalledProcessError),
        ):
            spawn_teammate.create_worktree(
                "worktree-story-003",
                str(self.repo),
                branch=None,
                smm_dir=self.smm_dir,
                story_id="story-003",
            )

        events, resolutions = _common.load_events_with_resolutions(self.smm_dir)
        drops = self._force_drops(events)
        self.assertEqual(len(drops), 1)
        self.assertEqual(self._respawns(events), [])
        self.assertNotIn(drops[0]["id"], resolutions["resolved_debt_ids"])


if __name__ == "__main__":
    unittest.main()
