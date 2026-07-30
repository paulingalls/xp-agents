#!/usr/bin/env python3
"""The commit gate's own discoverability check.

`lefthook install` writes `.git/hooks/pre-commit` (or sets `core.hooksPath`);
nothing runs that automatically, and nothing used to tell anyone to run it.
CLAUDE.md claimed "all tests run on every commit via lefthook" as if it were a
property of the repo — it cost a full sprint of ungated commits before that
gap was caught. `hooks_installed` below is the load-bearing check: it fails
loud, naming `make setup`, whenever a clone hasn't had setup run.

The rest of this file pins the lefthook.yml/pyrightconfig.json surfaces this
story touches, the same way test_lefthook_perf_gate.py pins the perf tier: a
single dropped word (`stage_fixed`, the widened pyright glob, the ruff-format
sequencing) would silently void the design while every other test stays
green. Bound to reality, not to word-presence, per that same file's approach —
reused here via its text-parsing helpers rather than re-implemented.

Text-level, not YAML-parsed: the plugin is stdlib-only and PyYAML is
unavailable.
"""

import glob as glob_module
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))
from _repo_fixtures import init_repo
from conftest import _PLUGIN_ROOT
from test_lefthook_perf_gate import REPO_ROOT, _command_body, _hook

PYRIGHT_CONFIG = REPO_ROOT / "pyrightconfig.json"
README = REPO_ROOT / "README.md"
CLAUDE_MD = REPO_ROOT / "CLAUDE.md"
MAKEFILE = REPO_ROOT / "Makefile"

# The five skills/*/scripts dirs that pyrightconfig.json's `extraPaths` already
# names but `include` (the set pyright actually type-checks) does not.
SKILLS_SCRIPT_DIRS = (
    "plugins/xp-agents/skills/xp-accept/scripts",
    "plugins/xp-agents/skills/xp-end-session/scripts",
    "plugins/xp-agents/skills/xp-quality-review/scripts",
    "plugins/xp-agents/skills/xp-sprint-review/scripts",
    "plugins/xp-agents/skills/xp-work-selection/scripts",
)

# Surfaces that ship to user projects — a user's project may not use lefthook,
# or any hook runner, at all, so this story's own check must never appear here.
SHIPPED_DIRS = tuple(
    _PLUGIN_ROOT / d for d in ("scripts", "smm", "agents", "skills", "hooks")
)
SHIPPED_GUIDE_FILES = tuple(
    _PLUGIN_ROOT / f for f in ("XP_VALUES.md", "PROCESS_GUIDE.md", "TEAMMATE_GUIDE.md")
)


def _ci_active() -> bool:
    """True under CI, where hooks are irrelevant — the same commands run
    directly (see .github/workflows/tests.yml). A plain function rather than
    an inline `os.environ.get("CI")` at the skip-decorator call site:
    `skipIf`/`skipUnless` bind their condition at import time, so a test that
    sets `CI` mid-run and asserts a skip can only prove anything by calling
    this function directly — never by re-evaluating the decorator.
    """
    return bool(os.environ.get("CI"))


def _git(repo_root: Path, *args: str) -> str | None:
    result = subprocess.run(
        ["git", *args], cwd=repo_root, capture_output=True, text=True
    )
    return result.stdout.strip() if result.returncode == 0 else None


def hooks_installed(repo_root: Path) -> bool:
    """True once `lefthook install` (or an equivalent) has wired a commit hook.

    Resolved through git itself, never a bare `.git/hooks` join: a worktree
    checkout keeps `.git` as a FILE pointing at a shared common dir, so a
    naive join silently checks a path that never exists there even when the
    real (shared) hooks are installed. Either mechanism is sufficient:
    `core.hooksPath` pointing somewhere, or a `pre-commit` file in the
    resolved hooks dir.
    """
    if _git(repo_root, "config", "--get", "core.hooksPath"):
        return True
    common_dir = _git(repo_root, "rev-parse", "--git-common-dir")
    if not common_dir:
        return False
    common_path = Path(common_dir)
    if not common_path.is_absolute():
        common_path = repo_root / common_path
    return (common_path / "hooks" / "pre-commit").is_file()


class TestHooksInstalledDetection(unittest.TestCase):
    """Proves hooks_installed both ways — the real clone (already set up)
    can only ever exercise the True branch, so a temp repo carries the red."""

    def test_fresh_repo_reports_not_installed(self):
        with tempfile.TemporaryDirectory() as td:
            init_repo(td)
            self.assertFalse(hooks_installed(Path(td)))

    def test_core_hooks_path_counts_as_installed(self):
        with tempfile.TemporaryDirectory() as td:
            init_repo(td)
            subprocess.run(
                ["git", "config", "core.hooksPath", "/tmp/whatever-hooks"],
                cwd=td,
                capture_output=True,
                check=True,
            )
            self.assertTrue(hooks_installed(Path(td)))

    def test_pre_commit_file_counts_as_installed(self):
        with tempfile.TemporaryDirectory() as td:
            init_repo(td)
            hooks_dir = Path(td) / ".git" / "hooks"
            (hooks_dir / "pre-commit").write_text("#!/bin/sh\nexit 0\n")
            self.assertTrue(hooks_installed(Path(td)))


class TestCiSkipPredicate(unittest.TestCase):
    """skipIf binds at import time, so the only way to prove the predicate
    reacts to CI is to call it directly rather than toggle env and re-check
    the class's skip state."""

    def test_ci_active_true_when_env_set(self):
        with mock.patch.dict(os.environ, {"CI": "true"}):
            self.assertTrue(_ci_active())

    def test_ci_active_false_when_env_unset(self):
        env = dict(os.environ)
        env.pop("CI", None)
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertFalse(_ci_active())


@unittest.skipIf(
    _ci_active(),
    "hooks are irrelevant in CI — the same commands run directly there",
)
class TestCommitGateIsSetUp(unittest.TestCase):
    def test_pre_commit_hook_is_installed_in_this_clone(self):
        self.assertTrue(
            hooks_installed(REPO_ROOT),
            "No commit hook is installed in this clone, so ruff, pyright, "
            "pytest, the secret scan, and the review-cycle gate are all "
            "silent on every commit. Run `make setup` once, then commit "
            "again.",
        )


class TestPyrightGlobCoversTestsTree(unittest.TestCase):
    """lefthook's pyright command takes no file args — the glob only decides
    WHETHER it runs, not what it checks. A glob scoped to scripts/smm alone
    means a tests-only commit never triggers the type checker at all."""

    def test_glob_matches_scripts_smm_and_tests(self):
        pyright_body = _command_body(_hook("pre-commit"), "pyright")
        self.assertTrue(pyright_body, "pre-commit must define a pyright command")
        glob_match = re.search(r'glob:\s*"([^"]+)"', pyright_body)
        self.assertIsNotNone(glob_match, "pyright command must declare a glob")
        pattern = glob_match.group(1)  # pyright: ignore[reportOptionalMemberAccess]

        matched = set(glob_module.glob(pattern, root_dir=REPO_ROOT, recursive=True))
        self.assertTrue(
            any(m.startswith("plugins/xp-agents/tests/") for m in matched),
            f"pyright glob {pattern!r} matches nothing under tests/ — a "
            "tests-only commit would never trigger the type checker.",
        )
        self.assertTrue(
            any(m.startswith("plugins/xp-agents/scripts/") for m in matched),
            f"pyright glob {pattern!r} regressed: no longer matches scripts/.",
        )
        self.assertTrue(
            any(m.startswith("plugins/xp-agents/smm/") for m in matched),
            f"pyright glob {pattern!r} regressed: no longer matches smm/.",
        )


class TestPyrightConfigIncludesSkillsScripts(unittest.TestCase):
    def test_all_five_skills_script_dirs_are_included_and_exist(self):
        config = json.loads(PYRIGHT_CONFIG.read_text(encoding="utf-8"))
        include = config.get("include", [])
        extra_paths = config.get("extraPaths", [])
        for d in SKILLS_SCRIPT_DIRS:
            self.assertIn(
                d, include, f"{d} must be added to pyrightconfig.json's include"
            )
            self.assertIn(
                d,
                extra_paths,
                f"{d} must stay in extraPaths — adding to include must not move it out",
            )
            self.assertTrue(
                (REPO_ROOT / d).is_dir(),
                f"pyrightconfig.json names {d}, which does not exist",
            )


class TestRuffFormatFixModeSequencedOutOfParallel(unittest.TestCase):
    def setUp(self):
        self.block = _hook("pre-commit")
        self.ruff_format = _command_body(self.block, "ruff-format")
        self.assertTrue(
            self.ruff_format, "pre-commit must define a ruff-format command"
        )

    def test_pre_commit_is_not_parallel(self):
        self.assertNotRegex(
            self.block,
            r"(?m)^\s+parallel:\s*true\b",
            "pre-commit must not be parallel: true — a concurrent ruff-format "
            "rewrite would race ruff-check/pyright/tests reading the same "
            "files mid-write.",
        )

    def test_pre_commit_is_piped(self):
        self.assertRegex(
            self.block,
            r"(?m)^\s+piped:\s*true\b",
            "pre-commit must be piped: true so nothing runs concurrently "
            "with ruff-format's rewrite.",
        )

    def test_ruff_format_runs_in_fix_mode(self):
        self.assertNotIn(
            "--check", self.ruff_format, "ruff-format must run in FIX mode"
        )
        self.assertRegex(
            self.ruff_format,
            r"run:\s*ruff format\b",
            "ruff-format command must invoke `ruff format`",
        )

    def test_ruff_format_stages_its_rewrite(self):
        self.assertRegex(
            self.ruff_format,
            r"(?m)^\s*stage_fixed:\s*true\b",
            "ruff-format in fix mode without stage_fixed leaves the rewrite "
            "unstaged — worse than the --check it replaces, since the "
            "commit then records unformatted content with no signal.",
        )

    def test_ruff_format_is_sequenced_first(self):
        self.assertRegex(
            self.ruff_format,
            r"(?m)^\s*priority:\s*1\b",
            "ruff-format must set priority: 1 so lefthook runs it before "
            "the other pre-commit commands.",
        )


class TestDevSetupCheckNeverShips(unittest.TestCase):
    """hooks_installed is xp-agents-internal dev-tooling vocabulary — the
    same class of surface name CLAUDE.md's project-agnostic guardrail
    already bans from shipped prose. A user's project may not use lefthook,
    or any hook runner, at all."""

    def test_hooks_installed_does_not_leak_into_shipped_surfaces(self):
        hits = []
        for d in SHIPPED_DIRS:
            if not d.is_dir():
                continue
            for path in d.rglob("*"):
                if not path.is_file():
                    continue
                try:
                    text = path.read_text(encoding="utf-8")
                except (UnicodeDecodeError, OSError):
                    continue
                if "hooks_installed" in text:
                    hits.append(str(path.relative_to(REPO_ROOT)))
        for f in SHIPPED_GUIDE_FILES:
            if f.is_file() and "hooks_installed" in f.read_text(encoding="utf-8"):
                hits.append(str(f.relative_to(REPO_ROOT)))
        self.assertFalse(
            hits, f"hooks_installed leaked into shipped surface(s): {hits}"
        )


class TestGatingClaimsAreConditional(unittest.TestCase):
    def test_claude_md_no_longer_claims_unconditional_gating(self):
        text = CLAUDE_MD.read_text(encoding="utf-8")
        self.assertNotIn(
            "All tests run on every commit via lefthook.",
            text,
            "CLAUDE.md must not claim gating happens automatically — it "
            "requires `make setup` first.",
        )
        self.assertIn(
            "make setup",
            text,
            "CLAUDE.md must name `make setup` as the step that wires up the gate",
        )

    def test_readme_leads_with_make_setup(self):
        text = README.read_text(encoding="utf-8")
        self.assertIn(
            "make setup",
            text,
            "README's Development setup section must lead with `make setup`",
        )


class TestMakefileSetupTarget(unittest.TestCase):
    def test_setup_target_exists(self):
        text = MAKEFILE.read_text(encoding="utf-8")
        self.assertRegex(
            text,
            r"(?m)^setup:",
            "Makefile must declare a `setup` target — the failure message "
            "above names it as the fix.",
        )

    def test_dead_targets_are_gone(self):
        text = MAKEFILE.read_text(encoding="utf-8")
        for dead_path in (
            "plugins/xp-agents/scripts/test_hooks.py",
            "smm/test_smm.py",
            "smm/test_engine.py",
            "scripts/test_integration.py",
        ):
            self.assertNotIn(
                dead_path,
                text,
                f"Makefile still references {dead_path}, removed in an "
                "earlier reorg — these targets error unconditionally",
            )


if __name__ == "__main__":
    unittest.main()
