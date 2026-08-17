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
        """Drive a hook as a real subprocess with the shims ahead on PATH.

        The exit code is checked because a hook that dies mid-run spawns
        nothing, and every "zero spawns" assertion below reads an empty log as
        "correctly declined to run". 0 (allow) and 2 (block) are the only codes
        these hooks are allowed to produce; 1 is an unhandled traceback, which
        the harness would also read as non-blocking.
        """
        result = self._run_script_with_env(
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
        self.assertIn(
            result.returncode,
            (0, 2),
            f"{script} exited {result.returncode} — it crashed rather than "
            f"running the lint leg, so any count below is read off an empty "
            f"log: {result.stderr}",
        )
        return result

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


class TestTheStagedGateRunsOncePerGroup(_LintedRepoCase):
    """The commit-time leg, through a real process.

    story-001's grouping is proved in units with `subprocess.run` patched. This
    asserts the same property where the process boundary is real: N files
    sharing one config produce ONE linter process, not N.
    """

    def test_one_spawn_covers_every_staged_file_in_the_group(self):
        self._touch_and_stage(*_PY_FILES)
        self._run_hook("pre_tool_bash.py", "git commit -m 'touch python'")

        spawns = self._spawns("ruff")
        self.assertEqual(
            len(spawns),
            1,
            f"expected one ruff process for {len(_PY_FILES)} files in one "
            f"config group, got {len(spawns)}: {spawns}",
        )
        argv = spawns[0]
        for name in _PY_FILES:
            self.assertIn(
                name,
                argv,
                f"the single batch skipped {name} — one process is only correct "
                f"if it covers the whole group: {argv}",
            )

    def test_the_other_group_is_untouched_when_only_one_is_staged(self):
        """A count of one proves batching only if the other group ran zero.

        Without this, a regression that ran every linter over every file on
        every commit would still show one ruff spawn and pass above.
        """
        self._touch_and_stage(*_PY_FILES)
        self._run_hook("pre_tool_bash.py", "git commit -m 'touch python'")

        self.assertEqual(
            self._spawns("npx"),
            [],
            "eslint ran for a commit that staged no TypeScript",
        )


class TestPostCommitResolutionRunsOnceAndClearsTheGroup(_LintedRepoCase):
    """story-002's AC 5, deferred here on the record.

    story-002 shipped the batching with its E2E explicitly owed to this story,
    after its plan review caught a claim that the existing integration suite
    already covered it. It did not — that suite's repo has no linter config.
    This is the debt being paid: one real commit, the real PostToolUse hook as
    a subprocess, one linter process, every concern in the group cleared.
    """

    def _commit_and_resolve(self, *rel_paths: str) -> dict[str, str]:
        ids = self._seed_lint_concerns(*rel_paths)
        self._touch_and_stage(*rel_paths)
        git_in(self.repo, "commit", "-m", "fix the lint")
        self._clear_spawns()
        self._run_hook("bash_post_tool.py", "git commit -m 'fix the lint'")
        return ids

    def test_one_spawn_resolves_every_concern_in_the_group(self):
        ids = self._commit_and_resolve(*_PY_FILES)

        spawns = self._spawns("ruff")
        self.assertEqual(
            len(spawns),
            1,
            f"post-commit resolution spawned {len(spawns)} ruff processes for "
            f"{len(_PY_FILES)} files sharing one config: {spawns}",
        )
        resolved = self._resolved_ids()
        for rel, concern_id in ids.items():
            self.assertIn(
                concern_id,
                resolved,
                f"the clean batch did not resolve {rel}'s concern — one process "
                f"is only correct if it vouches for the whole group",
            )

    def test_a_file_with_no_open_concern_spawns_nothing(self):
        """The honest bound is zero, not one.

        story-002's second filter drops paths carrying no unresolved lint
        concern, which is most commits. Without this the spawn count above
        could be read as "resolution always costs one process".
        """
        self._touch_and_stage(*_PY_FILES)
        git_in(self.repo, "commit", "-m", "no concerns outstanding")
        self._clear_spawns()
        self._run_hook("bash_post_tool.py", "git commit -m 'no concerns outstanding'")

        self.assertEqual(
            self._spawns("ruff"),
            [],
            "a linter ran for a commit with no lint concern to resolve",
        )


class TestTwoConfigsDoNotLeakIntoEachOther(_LintedRepoCase):
    """AC 3: each group runs once, and one group's verdict stays its own.

    The counting here is not symmetric with the clean cases, and the asymmetry
    is the contract rather than an accident. A CLEAN group is one batch. A
    FINDINGS group is 1 + N: the batch says only that something is wrong
    somewhere, and a batch's exit code names no file, so `_resolve_group` falls
    back to one run per file to learn which of them are individually clean.
    """

    def _commit_both_groups(self) -> dict[str, str]:
        py_rel = list(_PY_FILES)
        ts_rel = [f"apps/web/{name}" for name in _TS_FILES]
        ids = self._seed_lint_concerns(*py_rel, *ts_rel)
        self._touch_and_stage(*py_rel, *ts_rel)
        git_in(self.repo, "commit", "-m", "touch both ecosystems")
        self._clear_spawns()
        self._run_hook("bash_post_tool.py", "git commit -m 'touch both ecosystems'")
        return ids

    def test_each_config_runs_once_over_only_its_own_files(self):
        self._commit_both_groups()

        ruff_spawns = self._spawns("ruff")
        npx_spawns = self._spawns("npx")
        self.assertEqual(len(ruff_spawns), 1, f"ruff: {ruff_spawns}")
        self.assertEqual(len(npx_spawns), 1, f"eslint: {npx_spawns}")

        for name in _TS_FILES:
            self.assertIn(
                name,
                npx_spawns[0],
                f"eslint's single batch skipped {name} — one process is only "
                f"correct if it covers the whole group: {npx_spawns}",
            )
            self.assertNotIn(
                name,
                ruff_spawns[0],
                f"ruff's batch carried a TypeScript file ({name}) — the groups "
                f"are keyed on (linter, config) and must not blend: {ruff_spawns}",
            )
        for name in _PY_FILES:
            self.assertIn(
                name,
                ruff_spawns[0],
                f"ruff's single batch skipped {name}: {ruff_spawns}",
            )
            self.assertNotIn(
                name,
                npx_spawns[0],
                f"eslint's batch carried a Python file ({name}): {npx_spawns}",
            )

    def test_a_dirty_group_does_not_stop_the_clean_group_resolving(self):
        """The leak this AC is actually about.

        The eslint shim reports findings; ruff stays clean. The Python
        concerns must still clear, and the TypeScript ones must not — a shared
        verdict would show up as either all-or-nothing.
        """
        self._write_shim("npx", clean=False)
        ids = self._commit_both_groups()
        resolved = self._resolved_ids()

        for name in _PY_FILES:
            self.assertIn(
                ids[name],
                resolved,
                f"{name}'s concern stayed open because the OTHER group had "
                f"findings — one group's verdict leaked into the other's",
            )
        for name in _TS_FILES:
            self.assertNotIn(
                ids[f"apps/web/{name}"],
                resolved,
                f"{name}'s concern was resolved although its linter reported "
                f"findings — the batch vouched for a file it never cleared",
            )

    def test_the_dirty_group_falls_back_to_one_run_per_file(self):
        """1 + N, and why: a batch's exit code names no file.

        This is also what proves the dirty shim reached `findings` at all. A
        shim that exited non-zero WITHOUT output would classify `unverified`,
        whose arm resolves nothing and re-runs nothing — and the assertion
        above would still pass, having tested none of this.
        """
        self._write_shim("npx", clean=False)
        self._commit_both_groups()

        npx_spawns = self._spawns("npx")
        self.assertEqual(
            len(npx_spawns),
            1 + len(_TS_FILES),
            f"expected one batch plus one run per file in the findings group, "
            f"got {len(npx_spawns)}: {npx_spawns}",
        )


if __name__ == "__main__":
    unittest.main()
