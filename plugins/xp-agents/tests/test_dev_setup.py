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

# Surfaces that ship to user projects — a user's project may not use lefthook,
# or any hook runner, at all, so this story's own check must never appear here.
SHIPPED_DIRS = tuple(
    _PLUGIN_ROOT / d for d in ("scripts", "smm", "agents", "skills", "hooks")
)
# Globbed, not enumerated: `_pin_helpers.shipped_prose_to_scan` reads the root
# guides the same way, and a hardcoded trio would leave the next guide added
# unscanned with nothing going red.
SHIPPED_GUIDE_FILES = tuple(sorted(_PLUGIN_ROOT.glob("*.md")))


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
    real (shared) hooks are installed. `rev-parse --git-path hooks` answers
    both cases in one call — it returns the shared common dir's hooks in a
    worktree, and honors a `core.hooksPath` override (tilde already expanded)
    everywhere.

    The answer is an EXECUTABLE `pre-commit` in that dir, not the mere
    presence of an override: a global dotfiles `core.hooksPath` with no
    pre-commit in it, or a hook copied around without its exec bit, leaves
    every commit ungated — exactly the state this check exists to catch.
    (`smm/git_hooks.has_executable_hook` applies the same exec-bit rule to
    user projects.)
    """
    hooks_dir = _git(repo_root, "rev-parse", "--git-path", "hooks")
    if not hooks_dir:
        return False
    path = Path(hooks_dir)
    if not path.is_absolute():
        path = repo_root / path
    return os.access(path / "pre-commit", os.X_OK)


def _write_hook(hooks_dir: Path) -> Path:
    hooks_dir.mkdir(parents=True, exist_ok=True)
    hook = hooks_dir / "pre-commit"
    hook.write_text("#!/bin/sh\nexit 0\n")
    hook.chmod(0o755)
    return hook


class TestHooksInstalledDetection(unittest.TestCase):
    """Proves hooks_installed both ways — the real clone (already set up)
    can only ever exercise the True branch, so a temp repo carries the red."""

    def test_fresh_repo_reports_not_installed(self):
        with tempfile.TemporaryDirectory() as td:
            init_repo(td)
            self.assertFalse(hooks_installed(Path(td)))

    def test_core_hooks_path_with_a_hook_counts_as_installed(self):
        with tempfile.TemporaryDirectory() as td:
            init_repo(td)
            override = Path(td) / "custom-hooks"
            _write_hook(override)
            subprocess.run(
                ["git", "config", "core.hooksPath", str(override)],
                cwd=td,
                capture_output=True,
                check=True,
            )
            self.assertTrue(hooks_installed(Path(td)))

    def test_core_hooks_path_without_a_hook_is_not_installed(self):
        """The false-positive this check cannot afford: a global dotfiles
        `core.hooksPath` is set on plenty of developer machines, and it says
        nothing about whether THIS repo's gate was installed. Reporting
        installed there is how a clone commits ungated with a green suite —
        the exact failure the story exists to end."""
        with tempfile.TemporaryDirectory() as td:
            init_repo(td)
            empty = Path(td) / "empty-hooks"
            empty.mkdir()
            subprocess.run(
                ["git", "config", "core.hooksPath", str(empty)],
                cwd=td,
                capture_output=True,
                check=True,
            )
            self.assertFalse(hooks_installed(Path(td)))

    def test_pre_commit_file_counts_as_installed(self):
        with tempfile.TemporaryDirectory() as td:
            init_repo(td)
            _write_hook(Path(td) / ".git" / "hooks")
            self.assertTrue(hooks_installed(Path(td)))

    def test_non_executable_pre_commit_is_not_installed(self):
        """git skips a hook without the exec bit, so a copied-around
        `pre-commit` that lost it gates nothing."""
        with tempfile.TemporaryDirectory() as td:
            init_repo(td)
            hook = _write_hook(Path(td) / ".git" / "hooks")
            hook.chmod(0o644)
            self.assertFalse(hooks_installed(Path(td)))


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
    """The 13 shipped modules under `skills/*/scripts` must be in the set
    pyright CHECKS, not merely in the set it resolves imports against.

    Both configs, and the plugin-local one is the load-bearing half: the
    lefthook command sets `root: plugins/xp-agents/`, so the commit gate runs
    pyright with that as its cwd and reads THAT config — editing only the
    repo-root one (which serves editors opening the repo root) leaves the gate
    checking 779 files while a root-config-only pin reports green over 792.
    Derived from the filesystem rather than a hardcoded tuple, so a sixth
    skill that grows a scripts/ dir cannot slip in unchecked.
    """

    def _assert_covers_skill_scripts(self, config_path: Path, prefix: str):
        config = json.loads(config_path.read_text(encoding="utf-8"))
        include = config.get("include", [])
        extra_paths = config.get("extraPaths", [])
        name = config_path.relative_to(REPO_ROOT)
        for scripts_dir in sorted((_PLUGIN_ROOT / "skills").glob("*/scripts")):
            if not any(scripts_dir.glob("*.py")):
                continue
            entry = prefix + scripts_dir.relative_to(_PLUGIN_ROOT).as_posix()
            self.assertIn(
                entry,
                include,
                f"{entry} must be in {name}'s include — else "
                "its modules are never type-checked",
            )
            self.assertIn(
                entry,
                extra_paths,
                f"{entry} must stay in {name}'s extraPaths — adding to "
                "include must not move it out",
            )

    def test_gate_config_checks_every_skill_scripts_dir(self):
        self._assert_covers_skill_scripts(_PLUGIN_ROOT / "pyrightconfig.json", "")

    def test_repo_root_config_checks_every_skill_scripts_dir(self):
        self._assert_covers_skill_scripts(PYRIGHT_CONFIG, "plugins/xp-agents/")


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
        """LEADS with, not merely mentions: a README line alone is what
        already failed once. Ordering is the assertion — `make setup` has to
        come before the manual pipx steps it replaces, or the reader follows
        the old path and never installs the hook."""
        text = README.read_text(encoding="utf-8")
        section = text.split("## Development setup", 1)
        self.assertEqual(
            len(section), 2, "README must keep a `## Development setup` section"
        )
        body = section[1]
        setup_at = body.find("make setup")
        pipx_at = body.find("pipx install pytest")
        self.assertNotEqual(setup_at, -1, "Development setup must name `make setup`")
        self.assertNotEqual(pipx_at, -1, "Development setup must keep the pipx route")
        self.assertLess(
            setup_at,
            pipx_at,
            "`make setup` must come before the manual pipx steps — it is the "
            "one command that installs the commit hook, and a reader who "
            "stops at the first code block must have run it.",
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

    def test_probe_failure_shows_pytest_own_output(self):
        """The probe answers "does `pytest -n auto` work here?", and a
        COLLECTION error is a different answer from "pytest is missing".
        Swallowing the output reported both as "install pytest", and the dev
        with a broken import then never got the commit gate installed at all —
        exactly what this target exists to close."""
        text = MAKEFILE.read_text(encoding="utf-8")
        self.assertNotIn(
            "--collect-only -q >/dev/null 2>&1",
            text,
            "the probe must not discard pytest's own diagnostics",
        )
        self.assertRegex(
            text,
            r"(?s)setup:.*collect-only.*echo \"\$\$probe\"",
            "the probe's captured output must be echoed on failure",
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
