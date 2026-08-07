"""Base test cases for xp-agents test suites.

Two base classes live here:
- `_SMMTestCase` — pure unit-test scaffolding: temp SMM dir per test, env-var
  pin, helper to read/write events. Used by hook tests and engine tests.
- `_IntegrationTestCase` — temp git repo + initialized SMM, used to drive
  hook scripts as subprocesses.

`_TempRepoTestCase` and `cleanup_test_worktrees` moved to `_repo_bases`, and the
path constants to `_paths`, when this file crossed the 500-line ceiling. Both are
re-exported below BY IDENTITY, so `from _bases import _TempRepoTestCase` /
`_PLUGIN_ROOT` (and the conftest spellings) resolve to the same objects as before
— no suite changed, which is what verifies the split.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import TypeVar
from unittest.mock import patch

# Re-exported by identity; see the module docstring.
from _paths import (  # noqa: F401
    _CADENCE_CLI_PY,
    _MARKERS_PY,
    _PLUGIN_ROOT,
    _SCRIPTS_DIR,
    _SMM_DIR,
    _TEAMMATE_CONFIG_CLI_PY,
)
from _repo_bases import _TempRepoTestCase, cleanup_test_worktrees  # noqa: F401
from _test_typing import _MixinBase

_T = TypeVar("_T")


class _AssertNotNoneMixin(_MixinBase):
    """Adds `self._assert_not_none(value)` — a pyright-narrowing variant of
    assertIsNotNone that returns the value typed as ``T`` instead of
    ``T | None``. Replaces the legacy two-line crutch
    ``self.assertIsNotNone(x); assert x is not None`` at call sites.

    Mixin so both `_SMMTestCase` and standalone `unittest.TestCase`
    subclasses (e.g. `tests/hooks/test_branching_push._BasePushTest`)
    can share the helper without restructuring their primary base.

    Inherits from `_test_typing._MixinBase` (TYPE_CHECKING=TestCase /
    runtime=object) — single source of truth for the mixin shim per
    sprint-065 story-020 consolidation.
    """

    def _assert_not_none(self, value: _T | None, msg: str | None = None) -> _T:
        """Assert value is not None and return it narrowed to T.

        Pyright narrows callers via the ``T`` (not ``T | None``)
        return type, so the second ``assert`` line at each site
        becomes unnecessary.
        """
        self.assertIsNotNone(value, msg)
        assert value is not None
        return value


# Make scripts/ importable so we can default-mock commits.get_staged_diff
# below. Mirrors the sys.path discipline every hook test file already does.
sys.path.insert(0, str(_SCRIPTS_DIR))


class _SMMTestCase(_AssertNotNoneMixin, unittest.TestCase):
    """Base test case that creates a temp SMM directory.

    Pins SMM_DIR env var to the temp dir for the test's lifetime, so any
    in-process call that resolves SMM via env (init.sh-style fallback)
    stays inside the test sandbox. Without this, a hook test that calls
    `run(input, smm_dir=None)` would derive SMM via init.sh from the
    test's CWD — which is the developer's project — and write markers
    to the developer's live SMM, blocking subsequent prompts on
    .needs-kickoff. (Caught by `TestNoSmmLeakOnFallback`.)
    """

    def setUp(self):
        self.smm_dir = Path(tempfile.mkdtemp())
        self.events_file = self.smm_dir / "events.jsonl"
        (self.smm_dir / "events.lock").touch()
        self.events_file.touch()
        self._prev_smm_dir = os.environ.get("SMM_DIR")
        os.environ["SMM_DIR"] = str(self.smm_dir)

    def tearDown(self):
        if self._prev_smm_dir is None:
            os.environ.pop("SMM_DIR", None)
        else:
            os.environ["SMM_DIR"] = self._prev_smm_dir
        # A claim in a test keeps its holder lock for the LIFE OF THE PROCESS: a
        # real supervisor then exits, a test worker runs thousands more tests.
        # Imported here, not at module scope: _in_place_helpers imports this
        # module for its path constants.
        from _in_place_helpers import release_in_place_holds

        release_in_place_holds(self.smm_dir)
        shutil.rmtree(self.smm_dir)

    def _write_events(self, events: list[dict]) -> None:
        lines = [json.dumps(e, ensure_ascii=False) for e in events]
        self.events_file.write_text("\n".join(lines) + ("\n" if lines else ""))

    def _write_raw_lines(self, lines: list[str]) -> None:
        self.events_file.write_text("\n".join(lines) + "\n")

    def _read_events(self) -> list[dict]:
        """Read events back from events.jsonl, skipping empty/bad lines."""
        events = []
        for line in self.events_file.read_text().splitlines():
            line = line.strip()
            if line:
                events.append(json.loads(line))
        return events


class _HookTestCase(_SMMTestCase):
    """Hook-test base. Adds a default-clean-diff mock for the Tier 1 commit
    gate so tests that drive `pre_tool_bash.run()` from a non-git cwd
    don't trip its fail-closed branch.

    IMPORTANT: this auto-mocks `commits.get_staged_diff` to "" for
    EVERY hook test. If you are writing a test that needs Tier 1 to
    actually fire (against a planted secret) or to actually fail
    (git failure path), you MUST override the patch — either with a
    per-method `@patch("commits.get_staged_diff", return_value=...)`
    decorator (see TestTier1SecurityScan), or by stopping
    `self._staged_diff_patch` and starting your own. Without an
    override, your test silently bypasses Tier 1 and may pass for
    the wrong reason.
    """

    def setUp(self):
        super().setUp()
        self._staged_diff_patch = patch("commits.get_staged_diff", return_value="")
        self._staged_diff_patch.start()

    def tearDown(self):
        self._staged_diff_patch.stop()
        super().tearDown()


class _IntegrationTestCase(_AssertNotNoneMixin, unittest.TestCase):
    """Base class that creates a temp git repo and inits SMM via init.sh.

    The git repo and SMM directory are created once per class (setUpClass).
    Each test method gets a clean SMM state (events, markers, etc.) via setUp.

    Invariant: test methods sharing a class must not depend on git repo state
    beyond the initial commit. Git mutations (add, commit) from one test are
    visible to subsequent tests in the same class.
    """

    @classmethod
    def setUpClass(cls):
        cls.tmpdir = Path(tempfile.mkdtemp())
        # Pin initial branch to `main` so tests are hermetic across runners
        # whose `init.defaultBranch` may default to `master`.
        subprocess.run(
            ["git", "init", "-b", "main"],
            cwd=cls.tmpdir,
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=cls.tmpdir,
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=cls.tmpdir,
            capture_output=True,
            check=True,
        )
        (cls.tmpdir / "README").write_text("init")
        subprocess.run(
            ["git", "add", "README"],
            cwd=cls.tmpdir,
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "init"],
            cwd=cls.tmpdir,
            capture_output=True,
            check=True,
        )

        cls._plugin_data_dir = Path(tempfile.mkdtemp())
        cls._test_env = os.environ.copy()
        cls._test_env["XP_AGENTS_DATA"] = str(cls._plugin_data_dir)

        init_sh = _PLUGIN_ROOT / "smm" / "init.sh"
        result = subprocess.run(
            ["bash", str(init_sh)],
            cwd=cls.tmpdir,
            capture_output=True,
            text=True,
            check=True,
            env=cls._test_env,
        )
        cls.smm_dir = Path(result.stdout.strip())
        # Inject SMM_DIR into the test env so subsequent subprocess calls
        # skip the init.sh round-trip (init.sh honors $SMM_DIR).
        cls._test_env["SMM_DIR"] = str(cls.smm_dir)
        cls.scripts_dir = _SCRIPTS_DIR
        # Snapshot the initial SMM state so setUp can restore it cheaply
        cls._smm_snapshot: dict[str, bytes] = {}
        for f in cls.smm_dir.iterdir():
            if f.is_file():
                cls._smm_snapshot[f.name] = f.read_bytes()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmpdir, ignore_errors=True)
        shutil.rmtree(cls._plugin_data_dir, ignore_errors=True)

    def setUp(self):
        # Pin os.environ SMM_DIR to this class's sandbox for the whole test.
        # conftest strips SMM_DIR at import, and `_test_env` only carries it to
        # SUBPROCESS hooks; IN-PROCESS code (e.g. worktree.worktree_path, which
        # now derives the out-of-repo worktree base from resolve_smm_dir) would
        # otherwise shell init.sh from the runner's cwd and resolve the REAL
        # project's plugin-data dir — a split brain from the subprocess side and
        # a containment leak. Pinning makes both sides agree on self.smm_dir.
        self._prev_env_smm = os.environ.get("SMM_DIR")
        os.environ["SMM_DIR"] = str(self.smm_dir)
        # Reset SMM state to the post-init snapshot so each test starts clean.
        # Remove files/dirs added by previous tests, restore init.sh originals.
        # Also clean tmpdir (git repo) of files created by previous tests.
        for f in self.tmpdir.iterdir():
            if f.name in (".git", "README"):
                continue
            if f.is_dir():
                shutil.rmtree(f)
            else:
                f.unlink()
        # Mirror the worktree scrub for the git index — without this, a
        # sibling test's blocked-commit (file staged but commit refused)
        # leaves a stale index entry that bleeds into the next test.
        subprocess.run(
            ["git", "reset", "HEAD", "--", "."],
            cwd=self.tmpdir,
            capture_output=True,
        )
        keep = set(self._smm_snapshot) | {"retrospectives"}
        for f in self.smm_dir.iterdir():
            if f.name in keep:
                continue
            if f.is_dir():
                shutil.rmtree(f)
            else:
                f.unlink()
        # Restore snapshotted files (events.jsonl, events.lock, SMM seed, etc.)
        for name, content in self._smm_snapshot.items():
            target = self.smm_dir / name
            if name == "events.jsonl":
                target.write_bytes(b"")  # Always start with empty events
            else:
                target.write_bytes(content)
        # Clear retrospective files from previous tests
        retro_dir = self.smm_dir / "retrospectives"
        if retro_dir.is_dir():
            for f in retro_dir.iterdir():
                f.unlink()

    def _reset_repo_to_main(self) -> None:
        """Force the class-shared repo back onto `main` with a clean tree.

        `setUp` scrubs the worktree and the index but NOT the checked-out
        branch, so a sibling test that checked out a story/free branch leaves
        HEAD there. Any gate that keys on branch SHAPE — the schedule gate's
        free-branch exemption, say — then reads the wrong branch and exempts a
        write it should have blocked, which turns a *block* control into a
        vacuous pass. Cleanup can regress; this makes the starting branch
        deterministic regardless.

        Opt-in rather than folded into `setUp`: only suites that move HEAD
        should pay the two subprocesses.
        """
        for args in (["checkout", "-f", "main"], ["reset", "--hard", "HEAD"]):
            subprocess.run(
                ["git", *args], cwd=self.tmpdir, capture_output=True, check=False
            )

    def tearDown(self):
        # Prune story worktrees so the class-shared git repo's registry
        # stays clean across tests. Without this, a test that creates a
        # worktree at `.claude/worktrees/worktree-story-X` leaks the
        # registry entry into the next test, breaking reuse-by-id.
        # Sprint-069's closing-state capstone worked around this by
        # hand-picking unique ids per test (story-A1/B1/C1...).
        # Fast-path skip when no worktrees were created — most
        # integration tests don't touch `.claude/worktrees/`, so
        # spawning `git worktree list` on every tearDown is wasteful.
        # try/finally so super().tearDown() always runs even if cleanup
        # raises (cleanup_test_worktrees swallows git errors today, but
        # a future change shouldn't be able to skip parent teardown).
        try:
            # Worktrees now live OUT of the repo at {project-id}/worktrees
            # (sibling of the SMM dir), not under .claude/worktrees. Check the
            # out-of-repo dir too so the registry-pruning fast path still fires
            # after the story-024 placement move; keep the legacy in-repo probe
            # for any test that still pins the fallback.
            out_of_repo = self.smm_dir.parent / "worktrees"
            in_repo = self.tmpdir / ".claude" / "worktrees"
            if any(d.is_dir() and any(d.iterdir()) for d in (out_of_repo, in_repo)):
                cleanup_test_worktrees(self.tmpdir, prefix="worktree-")
        finally:
            # Same hold-release as _SMMTestCase.tearDown — and this class does NOT
            # inherit it (its base is unittest.TestCase, not _SMMTestCase), so it
            # needs its own call. It needs it MORE, in fact: `smm_dir` here is
            # CLASS-scoped and reused by every test in the class, while setUp
            # unlinks the lock FILE. A claim left in the registry therefore keys a
            # path the NEXT test will reuse, so `holds_name` answers True for a
            # name this process no longer meaningfully holds — and the next door
            # that trusts it would unlink a marker owned by someone else. Must run
            # before setUp removes the lock files: the release derives names from
            # the locks on disk.
            from _in_place_helpers import release_in_place_holds

            release_in_place_holds(self.smm_dir)
            # Restore the SMM_DIR env the setUp pin overrode so the value never
            # leaks into a following non-integration test on the same worker.
            if self._prev_env_smm is None:
                os.environ.pop("SMM_DIR", None)
            else:
                os.environ["SMM_DIR"] = self._prev_env_smm
            super().tearDown()

    def _run_preload(
        self,
        script_path: Path,
        extra_env: dict | None = None,
        args: list[str] | None = None,
    ) -> subprocess.CompletedProcess:
        """Run a preload.sh script as a subprocess.

        `args` is the preload's own argv — needed since a preload may gate a
        mutation behind an opt-in flag (xp-assign's `--consume-gate`), so the
        bare call and the real skill invocation are DIFFERENT runs to test.
        """
        if not script_path.is_file():
            self.skipTest(f"Preload script not found: {script_path}")
        env = self._test_env.copy()
        if extra_env:
            env.update(extra_env)
        return subprocess.run(
            ["bash", str(script_path), *(args or [])],
            cwd=self.tmpdir,
            capture_output=True,
            text=True,
            env=env,
        )

    def _run_script(
        self, script_name: str, input_data: dict, *, cwd: Path | str | None = None
    ) -> subprocess.CompletedProcess:
        """Run a hook script with JSON on stdin, under the setUp env."""
        return self._run_script_with_env(script_name, input_data, {}, cwd=cwd)

    def _read_events(self) -> list[dict]:
        """Read events from the SMM events.jsonl."""
        events_file = self.smm_dir / "events.jsonl"
        if not events_file.exists():
            return []
        events = []
        for line in events_file.read_text().splitlines():
            line = line.strip()
            if line:
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return events

    def _run_script_with_env(
        self,
        script_name: str,
        input_data: dict,
        env_overrides: dict,
        *,
        cwd: Path | str | None = None,
    ) -> subprocess.CompletedProcess:
        """Run a hook script (name + payload dict) with a custom env.

        Hooks only: a script taking argv, or one fed deliberately malformed
        stdin, cannot be expressed here. Discovery a2afebf947ba classifies the
        hand-rolled sites that stay hand-rolled for those reasons.
        """
        env = self._test_env.copy()
        env.update(env_overrides)
        return subprocess.run(
            ["python3", str(self.scripts_dir / script_name)],
            input=json.dumps(input_data),
            capture_output=True,
            text=True,
            cwd=self.tmpdir if cwd is None else cwd,
            env=env,
        )

    def _seed_events(self, events: list[dict]) -> None:
        """Write seed events to events.jsonl."""
        lines = [json.dumps(e, ensure_ascii=False) for e in events]
        (self.smm_dir / "events.jsonl").write_text(
            "\n".join(lines) + ("\n" if lines else "")
        )

    def _env_with_plugin_root(self) -> dict:
        """Test env with CLAUDE_PLUGIN_ROOT injected.

        append.sh and other plugin scripts resolve sibling modules via
        CLAUDE_PLUGIN_ROOT; subprocesses launched from integration tests
        need it set. Pulled out of test files (was duplicated 3x prior
        to consolidation — debt 94a6b8aaca52).
        """
        env = self._test_env.copy()
        env["CLAUDE_PLUGIN_ROOT"] = str(_PLUGIN_ROOT)
        return env

    def _run_append(self, *args: str) -> subprocess.CompletedProcess:
        """Run smm/append.sh with --smm-dir prefilled.

        Mirror of `_TempRepoTestCase._run_append` for the integration
        flavor (instance method; uses self.smm_dir + self.tmpdir).
        """
        return subprocess.run(
            [
                str(_PLUGIN_ROOT / "smm" / "append.sh"),
                "--smm-dir",
                str(self.smm_dir),
                *args,
            ],
            capture_output=True,
            text=True,
            env=self._env_with_plugin_root(),
            cwd=self.tmpdir,
        )

    def _run_smm_cli(self, *args: str) -> subprocess.CompletedProcess:
        """Run smm/smm_cli.py with --smm-dir prefilled. Sister of _run_append."""
        return subprocess.run(
            [
                "python3",
                str(_PLUGIN_ROOT / "smm" / "smm_cli.py"),
                "--smm-dir",
                str(self.smm_dir),
                *args,
            ],
            capture_output=True,
            text=True,
            env=self._env_with_plugin_root(),
            cwd=self.tmpdir,
        )
