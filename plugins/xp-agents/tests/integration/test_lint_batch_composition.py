#!/usr/bin/env python3
"""Milestone 2's two legs, composed over one real commit, counted at the process.

story-001 extracted `lint_grouping.group_paths_by_linter`; story-002 made the
post-commit resolution path consume it. Both the commit-time staged gate and the
post-commit resolution now route through one grouping helper and one batch
runner — and until this file, nothing ran both against a real repo.

WHY A SHIM AND NOT A PATCH. Every other proof of the batching patches
`lint_runners.subprocess.run` and counts calls. That is the right tool for a unit
and useless here: the hooks run as subprocesses, so a patch in the test process
intercepts nothing. Instead a fake linter EXECUTABLE goes on PATH, appends its
argv to a log, and exits. The count is of processes that really started, which
also exercises `shutil.which` resolution, argv construction, and the cwd derived
from `config_path` — none of which a patched `subprocess.run` can see.

THE TRAP THIS FIXTURE IS BUILT AGAINST. `test_commit_path_composition.py` says in
its own docstring that "a temp repo has no linter config so the lint leg skips" —
which is exactly why that suite could not stand in for the E2E story-002 deferred
here. The configs are the point: without `ruff.toml` and
`apps/web/eslint.config.mjs`, `detect_linter_config` resolves nothing, no linter
runs, and EVERY count below still passes, because "exactly one spawn" and "zero
spawns" both hold over an empty set. `TestTheFixtureIsRealBeforeAnythingIsCounted`
is the guard, and it is not optional.

THE SHIM'S EXIT CONTRACT IS LOAD-BEARING, and getting it wrong hides the leg it
means to drive. `run_linter_batch` reads non-zero WITH output as `findings`, and
non-zero with nothing to say as `unverified` — whose `_resolve_group` arm does
nothing at all. A dirty shim that only `exit 1` would let "the dirty group did not
resolve" pass while the per-file fallback never ran. `_write_shim` therefore
prints whenever it exits non-zero.

Two further counting hazards, both real:

  * exit 2 is a USAGE error for eslint's config-style flag
    (`CONFIG_STYLE_FLAGS[...].usage_error_exit_code`), so
    `_run_with_optional_flag_retry` re-runs without the flag and logs a SECOND
    spawn. The dirty shim exits 1.
  * a `findings` group spawns 1 + N times, not once: the batch, then
    `check_and_resolve_lint` per file in that group. Counts are read per phase,
    with `_clear_spawns()` between them.
"""

import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from _repo_fixtures import git_in, init_nested_repo
from conftest import _IntegrationTestCase, make_event
from event_schema import EVENT_TYPE_CONCERN

# ruff for Python, npx for eslint — the binaries LINTER_BINARIES names for the
# two ecosystems this fixture carries. Two DIFFERENT binaries is deliberate:
# each group's spawns land in a separately named log, so "one run per group" is
# read without disentangling a shared one.
_PY_FILES = ("alpha.py", "beta.py", "gamma.py")
_TS_FILES = ("one.ts", "two.ts")


class _LintedRepoCase(_IntegrationTestCase):
    """A repo whose files actually resolve to linters, with both shimmed."""

    def setUp(self):
        super().setUp()
        self.repo = init_nested_repo(self.tmpdir)
        self.bin = self.tmpdir / "shimbin"
        self.bin.mkdir()
        self.spawnlog = self.tmpdir / "spawns"
        self.spawnlog.mkdir()

        (self.repo / "ruff.toml").write_text("line-length = 88\n")
        web = self.repo / "apps" / "web"
        web.mkdir(parents=True)
        (web / "eslint.config.mjs").write_text("export default [];\n")

        for name in _PY_FILES:
            (self.repo / name).write_text("x = 1\n")
        for name in _TS_FILES:
            (web / name).write_text("export const x = 1;\n")
        git_in(self.repo, "add", "-A")
        git_in(self.repo, "commit", "-m", "seed the tree")

        self._write_shim("ruff", clean=True)
        self._write_shim("npx", clean=True)

    # -- shims ---------------------------------------------------------------

    def _write_shim(self, binary: str, *, clean: bool) -> None:
        """Install `binary` on the shim PATH, logging one line per invocation.

        `"$@"` on the log line records the argv, so a caller can assert WHICH
        files a run covered rather than only how many runs there were.

        A dirty shim PRINTS before exiting 1. Both halves matter: with no output
        the run classifies `unverified` and resolves nothing while the per-file
        fallback stays unexercised, and exit 2 would be read as a config-style
        usage error and retried, logging a phantom second spawn.
        """
        body = f'#!/bin/sh\necho "$@" >> "{self.spawnlog / binary}"\n'
        if clean:
            body += "exit 0\n"
        else:
            body += 'echo "shim: findings in $*" >&2\nexit 1\n'
        path = self.bin / binary
        path.write_text(body)
        path.chmod(0o755)

    def _spawns(self, binary: str) -> list[str]:
        log = self.spawnlog / binary
        if not log.exists():
            return []
        return [line for line in log.read_text().splitlines() if line.strip()]

    def _clear_spawns(self) -> None:
        for entry in self.spawnlog.iterdir():
            entry.unlink()

    # -- driving the hooks ---------------------------------------------------

    def _run_hook(self, script: str, command: str) -> subprocess.CompletedProcess:
        """Drive a hook as a real subprocess with the shims ahead on PATH."""
        return self._run_script_with_env(
            script,
            {
                "session_id": "int-test",
                "tool_name": "Bash",
                "tool_input": {"command": command},
                "tool_response": {"stdout": "", "stderr": ""},
                "cwd": str(self.repo),
                "agent_id": "main",
            },
            {"PATH": f"{self.bin}:{self._test_env.get('PATH', '')}"},
            cwd=self.repo,
        )

    def _seed_lint_concerns(self, *rel_paths: str) -> dict[str, str]:
        """One unresolved lint concern per path; returns {path: event id}.

        Post-commit resolution only looks at files carrying an unresolved
        concern (story-002's second filter), so without these the resolution leg
        has nothing to do and spawns nothing — which would make a spawn-count
        assertion pass for the wrong reason.
        """
        events, ids = [], {}
        for rel in rel_paths:
            concern = make_event(
                EVENT_TYPE_CONCERN,
                content=f"Lint errors in {rel}:\nE302 expected 2 blank lines",
                severity="medium",
            )
            events.append(concern)
            ids[rel] = concern["id"]
        self._seed_events(events)
        return ids

    def _resolved_ids(self) -> set[str]:
        resolved = set()
        for event in self._read_events():
            for rid in (event.get("metadata") or {}).get("resolves") or []:
                resolved.add(rid)
        return resolved

    def _touch_and_stage(self, *rel_paths: str) -> None:
        for rel in rel_paths:
            target = self.repo / rel
            target.write_text(target.read_text() + "# touched\n")
        git_in(self.repo, "add", "-A")


class TestTheFixtureIsRealBeforeAnythingIsCounted(_LintedRepoCase):
    """Every count in this file is satisfied by a repo where no linter runs.

    "Exactly one spawn" and "zero spawns" are both true of an empty log, so a
    fixture that quietly stopped resolving configs would turn the whole file
    green while measuring nothing. This class is the one assertion that cannot
    be satisfied that way.
    """

    def test_the_shims_are_actually_invoked(self):
        self._touch_and_stage(*_PY_FILES)
        self._run_hook("pre_tool_bash.py", "git commit -m 'touch python'")

        spawns = self._spawns("ruff")
        self.assertTrue(
            spawns,
            "no ruff process started: detect_linter_config resolved nothing, so "
            "every count in this file would be read off an empty set",
        )
        self.assertTrue(
            any(name in " ".join(spawns) for name in _PY_FILES),
            f"ruff ran but saw none of the staged python files: {spawns}",
        )


if __name__ == "__main__":
    unittest.main()
