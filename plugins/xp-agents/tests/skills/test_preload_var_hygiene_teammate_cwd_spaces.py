#!/usr/bin/env python3
"""TEAMMATE_CWD space-preserving emit path (story-007).

Split from test_preload_var_hygiene.py at the commit that pushed it
past the 500-line target — keeps each suite single-responsibility.

TEAMMATE_CWD is a filesystem path a close/review skill feeds to
`git -C <path>` — a worktree under a dir with consecutive spaces must
survive verbatim. Both the story-close and quality-review preloads route it
through emit_path_var (strip_framing, space-preserving), NOT emit_var
(`flat`, which collapses runs and would target a non-existent directory).
"""

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from _bases import _PLUGIN_ROOT
from _branching_fixtures import seed_sprint_with_stories
from conftest import _extract_preload_var, _IntegrationTestCase

_BASE = _PLUGIN_ROOT / "skills" / "_preload_base.sh"
_SCHEDULE_PRELOAD = _PLUGIN_ROOT / "skills" / "xp-schedule" / "scripts" / "preload.sh"
_STORY_CLOSE_PRELOAD = (
    _PLUGIN_ROOT / "skills" / "xp-story-close" / "scripts" / "preload.sh"
)
_QR_PRELOAD = _PLUGIN_ROOT / "skills" / "xp-quality-review" / "scripts" / "preload.sh"
_ACCEPT_PRELOAD = _PLUGIN_ROOT / "skills" / "xp-accept" / "scripts" / "preload.sh"


def _init_spaced_repo(base: Path) -> "tuple[Path, Path, dict]":
    """Git-init a repo under an ancestor dir whose name has CONSECUTIVE spaces,
    init its SMM via init.sh, and return (repo, smm_dir, env). Mirrors the real
    macOS trigger for the TEAMMATE_CWD path-collapse bug: a checkout under e.g.
    `/Users/John  Doe/proj`. The double space is ABOVE `.claude/worktrees/`, so
    the teammate-worktree marker substring still matches while the path a close
    skill hands to `git -C` carries the run of spaces."""
    repo = base / "host  dir" / "proj"
    repo.mkdir(parents=True)
    env = os.environ.copy()
    for var in (
        "SMM_DIR",
        "GIT_DIR",
        "GIT_WORK_TREE",
        "GIT_COMMON_DIR",
        "GIT_INDEX_FILE",
        "XP_TEAMMATE_NAME",
    ):
        env.pop(var, None)
    env["XP_AGENTS_DATA"] = str(base / "plugin-data")
    for args in (
        ["git", "init", "-b", "main"],
        ["git", "config", "user.email", "test@test.com"],
        ["git", "config", "user.name", "Test"],
    ):
        subprocess.run(args, cwd=repo, env=env, capture_output=True, check=True)
    (repo / "README").write_text("init")
    subprocess.run(
        ["git", "add", "README"], cwd=repo, env=env, capture_output=True, check=True
    )
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=repo,
        env=env,
        capture_output=True,
        check=True,
    )
    init_sh = _PLUGIN_ROOT / "smm" / "init.sh"
    r = subprocess.run(
        ["bash", str(init_sh)],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    smm_dir = Path(r.stdout.strip())
    env["SMM_DIR"] = str(smm_dir)
    return repo, smm_dir, env


class TestTeammateCwdPathSpaces(_IntegrationTestCase):
    """TEAMMATE_CWD is a filesystem path a close/review skill feeds to
    `git -C <path>` — a worktree under a dir with consecutive spaces must
    survive verbatim. Both the story-close and quality-review preloads route it
    through emit_path_var (strip_framing, space-preserving), NOT emit_var
    (`flat`, which collapses runs and would target a non-existent directory).
    Each test reverts red if its preload's routing regresses to emit_var."""

    def test_quality_review_preserves_consecutive_spaces_via_explicit_cwd(self):
        # Explicit-override seam: an explicit TEAMMATE_CWD wins over auto-detect
        # and is emitted directly. It must be a REAL worktree — the preload runs
        # downstream `git -C "$TEAMMATE_CWD"` against the raw path — so use a
        # real worktree whose leaf carries a run of spaces (the leaf is free
        # here: explicit-override skips the name-binding detection).
        subprocess.run(
            ["git", "worktree", "prune"],
            cwd=self.tmpdir,
            env=self._test_env,
            capture_output=True,
        )
        wt = self.tmpdir / ".claude" / "worktrees" / "worktree-story-060  double"
        wt.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["git", "worktree", "add", "-b", "story-060-x", str(wt), "HEAD"],
            cwd=self.tmpdir,
            env=self._test_env,
            capture_output=True,
            check=True,
        )
        env = self._test_env.copy()
        env["TEAMMATE_CWD"] = str(wt)
        result = subprocess.run(
            ["bash", str(_QR_PRELOAD)],
            cwd=str(self.tmpdir),
            env=env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        emitted = self._assert_not_none(
            _extract_preload_var(result.stdout, "TEAMMATE_CWD")
        )
        self.assertEqual(emitted, str(wt))
        self.assertIn(
            "  ", emitted, "the double space in the worktree path is preserved"
        )

    def test_story_close_preserves_consecutive_spaces_in_worktree_path(self):
        base = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, base, ignore_errors=True)
        repo, smm_dir, env = _init_spaced_repo(base)
        seed_sprint_with_stories(smm_dir, [("story-042", "closing")])
        wt = repo / ".claude" / "worktrees" / "worktree-story-042"
        wt.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["git", "worktree", "add", "-b", "worktree-story-042", str(wt), "HEAD"],
            cwd=repo,
            env=env,
            capture_output=True,
            check=True,
        )
        result = subprocess.run(
            ["bash", str(_STORY_CLOSE_PRELOAD)],
            cwd=repo,
            env=env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        emitted = self._assert_not_none(
            _extract_preload_var(result.stdout, "TEAMMATE_CWD")
        )
        self.assertIn(
            "  ", emitted, "the double space in the worktree path is preserved"
        )
        self.assertTrue(
            emitted.endswith("worktree-story-042"),
            f"TEAMMATE_CWD must resolve to the closing story's worktree: {emitted!r}",
        )
