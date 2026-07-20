#!/usr/bin/env python3
"""staged_lint gate branch A/B/C behavior: in-place, stdin-piped, blocked.

Split from test_lint.py to keep files under the 500-line cap. `_StagedGitRepo`
lives in `_lint_test_helpers.py` because it is also used by
test_lint_staged_gate_edge_cases.py — a shared base, not a duplicate.
"""

import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import _common
import lint_check
import staged_lint
from _lint_test_helpers import _StagedGitRepo
from conftest import _mock_ruff_result


class _LinterCallRecorder(_StagedGitRepo):
    """Intercept the LINTER while letting the gate's git reads run for real.

    `patch("lint_check.subprocess.run")` binds `run` on the shared subprocess
    module, so it also intercepts staged_lint's index reads — delegate anything
    git-shaped to the real runner and record only the linter invocations.
    """

    def _run_gate(self, paths: list[str], *, exit_code: int = 0, output: str = ""):
        real_run = subprocess.run
        calls: list[dict] = []

        def _capture(cmd, **kwargs):
            if cmd and cmd[0] == "git":
                return real_run(cmd, **kwargs)
            calls.append({"cmd": list(cmd), "kwargs": kwargs})
            return _mock_ruff_result(returncode=exit_code, stdout=output)

        with (
            patch("lint_check.shutil.which", return_value="/usr/bin/ruff"),
            patch("lint_check.subprocess.run", side_effect=_capture),
        ):
            advisories = staged_lint.staged_lint_gate(paths, str(self.repo))
        return advisories, calls


class TestBranchBFeedsStagedBytesOnStdin(_LinterCallRecorder):
    """Where the index and the tree DIVERGE, the bytes to judge are not on disk.

    They are piped to the linter, which is told the path they belong to — so the
    file is judged at its REAL location without a copy existing anywhere. This is
    the case materialization was invented for, and it is why the hybrid beats a
    fast-path-only design: it fixes that case rather than conceding it.

    Per-file rather than batched, which is the honest cost: stdin carries one
    file. Divergence is rare (a partial add, an edit-after-add), so the cost is
    bounded by how rare it is, and the ~99% case stays batched.
    """

    def _stage_then_dirty(self) -> None:
        target = self.repo / "app.py"
        target.write_text("STAGED_CONTENT = 1\n")
        self._git("add", "app.py")
        target.write_text("WORKING_TREE_CONTENT = 2\n")

    def test_the_staged_bytes_are_piped_not_the_working_tree(self) -> None:
        self._stage_then_dirty()

        _advisories, calls = self._run_gate(["app.py"])

        self.assertEqual(len(calls), 1)
        self.assertEqual(
            calls[0]["kwargs"].get("input"),
            b"STAGED_CONTENT = 1\n",
            "the linter must be fed the bytes the COMMIT carries",
        )

    def test_the_linter_is_told_the_real_path_those_bytes_belong_to(self) -> None:
        """The whole point: no temp file, and the path the linter resolves
        `./util` and filename-keyed rules against is the real one."""
        self._stage_then_dirty()

        _advisories, calls = self._run_gate(["app.py"])

        cmd = calls[0]["cmd"]
        self.assertIn("--stdin-filename", cmd)
        self.assertEqual(cmd[cmd.index("--stdin-filename") + 1], "app.py")
        for arg in cmd:
            self.assertNotIn("tmp", arg, f"a temp path leaked into the argv: {arg}")

    def test_the_bytes_are_piped_as_bytes(self) -> None:
        """A staged blob may not be UTF-8, so `staged_blob_bytes` hands back raw
        bytes — which cannot be `input=` to a text-mode process. This branch runs
        binary and decodes the OUTPUT itself; a text-mode run would raise
        TypeError on the first non-UTF-8 blob and block a commit unfixably."""
        self._stage_then_dirty()

        _advisories, calls = self._run_gate(["app.py"])

        self.assertIsInstance(calls[0]["kwargs"].get("input"), bytes)
        self.assertNotEqual(calls[0]["kwargs"].get("text"), True)

    def test_a_non_utf8_staged_blob_does_not_crash_the_gate(self) -> None:
        target = self.repo / "app.py"
        target.write_bytes(b"# \xff\xfe not utf-8\nx = 1\n")
        self._git("add", "app.py")
        target.write_bytes(b"y = 2\n")

        _advisories, calls = self._run_gate(["app.py"])

        self.assertEqual(
            calls[0]["kwargs"].get("input"), b"# \xff\xfe not utf-8\nx = 1\n"
        )

    def _run_gate_with_bytes(self, paths: list[str], *, stdout: bytes, code: int):
        """Branch B runs the linter in BINARY mode, so its stdout is bytes —
        `_mock_ruff_result` is typed for the text-mode callers."""
        real_run = subprocess.run

        def _capture(cmd, **kwargs):
            if cmd and cmd[0] == "git":
                return real_run(cmd, **kwargs)
            return type(
                "R", (), {"returncode": code, "stdout": stdout, "stderr": b""}
            )()

        with (
            patch("lint_check.shutil.which", return_value="/usr/bin/ruff"),
            patch("lint_check.subprocess.run", side_effect=_capture),
        ):
            return staged_lint.staged_lint_gate(paths, str(self.repo))

    def test_findings_name_the_file_even_when_the_linter_will_not(self) -> None:
        """A linter fed stdin may name its input `(stdin)` instead of the path it
        was told — MEASURED: prettier 3 `--check --stdin-filepath x.js` prints
        exactly `(stdin)` and exits 1. Branch B is per-file, so the gate KNOWS
        which file the run was for, and must say so: a finding the agent cannot
        locate is this story's own scar (a report against a path that is not the
        file). The gate never reads the linter's words — it only labels them."""
        self._stage_then_dirty()

        with self.assertRaises(_common.BlockedError) as ctx:
            self._run_gate_with_bytes(["app.py"], stdout=b"(stdin)\n", code=1)

        self.assertIn("app.py", ctx.exception.args[0])
        self.assertIn("(stdin)", ctx.exception.args[0], "the linter's own words")

    def test_linter_output_is_decoded_leniently(self) -> None:
        """The linter's own bytes are not guaranteed UTF-8 either (it echoes the
        source line it flagged). Findings must survive a bad byte, not raise."""
        target = self.repo / "app.py"
        target.write_text("import os\n")
        self._git("add", "app.py")
        target.write_text("x = 1\n")

        real_run = subprocess.run

        # Not _mock_ruff_result: this branch runs the linter in BINARY mode, so
        # its stdout is bytes, and that fixture is typed for the text-mode
        # callers. Faking bytes here is the point of the test.
        def _capture(cmd, **kwargs):
            if cmd and cmd[0] == "git":
                return real_run(cmd, **kwargs)
            return type(
                "R",
                (),
                {"returncode": 1, "stdout": b"app.py:1:1: F401 \xff\n", "stderr": b""},
            )()

        with (
            patch("lint_check.shutil.which", return_value="/usr/bin/ruff"),
            patch("lint_check.subprocess.run", side_effect=_capture),
            self.assertRaises(_common.BlockedError) as ctx,
        ):
            staged_lint.staged_lint_gate(["app.py"], str(self.repo))

        self.assertIn("F401", ctx.exception.args[0])

    def test_a_spent_budget_says_what_to_do_about_it(self) -> None:
        """This branch costs a process per file, so a commit with many divergent
        files can spend the shared budget — and a spent budget BLOCKS.

        Normally that is the one `unverified` cause nobody can act on: you cannot
        make a linter faster. Here they can, and the message has to say so. The
        file is only on this expensive path because its staged bytes differ from
        the file on disk; re-staging it stops the divergence and routes it back
        through the shared batch. An unfixable gate gets switched off — which is
        the one outcome worse than a quiet one.
        """
        run = lint_check.run_linter_stdin(
            "ruff",
            "app.py",
            b"x = 1\n",
            cwd=str(self.repo),
            budget_s=0,
            root=str(self.repo),
        )

        self.assertEqual(run.status, "unverified", "a spent budget is not a pass")
        self.assertIn(
            "git add app.py", run.output, "name the remedy, not just the cause"
        )


class TestBranchCBlocksWhenStdinIsNotAnOption(_StagedGitRepo):
    """Divergent bytes + a linter that reads no stdin = FAIL CLOSED, and say how.

    This branch used to advise and wave the commit through, which reopened the
    exact edit-after-add fail-open the gate exists to close — for every language
    whose linter takes no stdin (Go, C/C++, Dart, Swift, PHP). The reasoning that
    licensed it was that blocking is "a gate nobody can satisfy". That is false,
    and the falseness is the whole point: `git add <path>` satisfies it in one
    command, and for the headline case (staged, then edited on disk) re-staging
    is what the committer MEANT to do anyway. An unreadable file is not a clean
    one — the gate's own doctrine everywhere else.

    Narrow by construction: only a divergent file, only for a stdin-less linter.
    Identical files still lint in place on branch A — ~99% of commits.
    """

    def _stage_then_dirty_a_go_file(self) -> None:
        (self.repo / ".golangci.yml").touch()
        target = self.repo / "main.go"
        target.write_text("package main\nfunc main() { var x int }\n")  # violation
        self._git("add", "main.go")
        target.write_text("package main\nfunc main() {}\n")  # fixed, NOT re-staged

    def test_divergent_file_for_a_stdin_less_linter_blocks(self) -> None:
        """The regression this class is named for: on a Go project, the
        violating STAGED bytes must not reach the commit just because the
        working tree was cleaned up afterwards."""
        self._stage_then_dirty_a_go_file()

        with (
            patch("lint_check.shutil.which", return_value="/usr/bin/golangci-lint"),
            self.assertRaises(_common.BlockedError) as caught,
        ):
            staged_lint.staged_lint_gate(["main.go"], str(self.repo))

        message = str(caught.exception)
        self.assertIn("main.go", message, "the block must name the file")
        self.assertIn("golangci-lint", message, "and the linter that cannot read it")

    def test_the_block_tells_the_committer_how_to_satisfy_it(self) -> None:
        """A gate that blocks without naming its remedy is the unsatisfiable
        gate the old advisory was (wrongly) afraid of."""
        self._stage_then_dirty_a_go_file()

        with (
            patch("lint_check.shutil.which", return_value="/usr/bin/golangci-lint"),
            self.assertRaises(_common.BlockedError) as caught,
        ):
            staged_lint.staged_lint_gate(["main.go"], str(self.repo))

        self.assertIn("git add", str(caught.exception))

    def test_an_IDENTICAL_go_file_still_lints_in_place_and_passes(self) -> None:
        """The loss stays narrow: divergence is the trigger, not the language."""
        (self.repo / ".golangci.yml").touch()
        (self.repo / "main.go").write_text("package main\nfunc main() {}\n")
        self._git("add", "main.go")  # index == working tree

        real_run = subprocess.run

        def _capture(cmd, **kwargs):
            if cmd and cmd[0] == "git":
                return real_run(cmd, **kwargs)
            return _mock_ruff_result(returncode=0, stdout="")

        with (
            patch("lint_check.shutil.which", return_value="/usr/bin/golangci-lint"),
            patch("lint_check.subprocess.run", side_effect=_capture),
        ):
            advisories = staged_lint.staged_lint_gate(["main.go"], str(self.repo))

        self.assertEqual(advisories, [])

    def test_a_project_scoped_linter_still_DEGRADES_rather_than_blocking(self) -> None:
        """The distinction this change must not flatten: clippy exits non-zero
        over whole-crate state the staged diff neither caused nor can fix, so
        blocking on it is genuinely unsatisfiable. `degrade_reason` runs first
        and still wins — divergence never reaches it."""
        (self.repo / "Cargo.toml").touch()
        target = self.repo / "main.rs"
        target.write_text("fn main() { let x = 1; }\n")
        self._git("add", "main.rs")
        target.write_text("fn main() {}\n")  # divergent

        with patch("lint_check.shutil.which", return_value="/usr/bin/cargo"):
            advisories = staged_lint.staged_lint_gate(["main.rs"], str(self.repo))

        self.assertEqual(len(advisories), 1, f"expected one advisory: {advisories}")
        self.assertIn("clippy", advisories[0])


class TestBranchALintsTheRealPath(_LinterCallRecorder):
    """When the index and the working tree AGREE, the file on disk IS the staged
    blob — so lint it where it lives. No copy, at any depth.

    Every copy breaks something. A temp sibling (random basename) defeats
    filename-keyed rules; a temp subdir keeps the basename but shifts the file
    one level down, so `./util` and `../lib/x` resolve to paths that do not
    exist — and the gate then reports an unresolved import against a real path
    that is provably clean. Both properties hold only at the real path.

    This cannot reintroduce the partial-add fail-open: that hole requires the
    index and the tree to DIVERGE, and this branch only fires when they are
    byte-identical by git's own account.
    """

    def _stage_two_identical_files(self) -> None:
        (self.repo / "app.py").write_text("x = 1\n")
        (self.repo / "util.py").write_text("y = 2\n")
        self._git("add", "app.py", "util.py")

    def test_the_real_paths_are_linted_not_a_copy(self) -> None:
        self._stage_two_identical_files()

        _advisories, calls = self._run_gate(["app.py", "util.py"])

        self.assertEqual(len(calls), 1, "one batched invocation")
        cmd = calls[0]["cmd"]
        self.assertIn("app.py", cmd)
        self.assertIn("util.py", cmd)

    def test_no_temp_directory_is_created_anywhere(self) -> None:
        """The whole story: no copy, so no shifted depth. Assert on the argv,
        which is what the linter actually resolves paths from."""
        self._stage_two_identical_files()

        _advisories, calls = self._run_gate(["app.py", "util.py"])

        for arg in calls[0]["cmd"]:
            self.assertNotIn("tmp", arg, f"a temp segment leaked into the argv: {arg}")
        strays = [p.name for p in self.repo.iterdir() if p.name.startswith("tmp")]
        self.assertEqual(strays, [], f"temp dirs created in the repo: {strays}")

    def test_still_one_subprocess_for_many_paths(self) -> None:
        """Batching is load-bearing, not incidental. A per-file invocation costs
        one process per staged file — 50 spawns on a 50-file commit, inside a
        hook the harness will kill. If it is killed there is no exit 2, so the
        commit lands UNLINTED: the fail-open this gate exists to close."""
        for i in range(12):
            (self.repo / f"mod{i}.py").write_text(f"v{i} = {i}\n")
        self._git("add", ".")

        _advisories, calls = self._run_gate([f"mod{i}.py" for i in range(12)])

        self.assertEqual(len(calls), 1, "12 staged files must cost ONE subprocess")

    def test_no_stdin_is_fed_when_the_index_matches(self) -> None:
        """The file on disk already holds the staged bytes — piping them would
        be a per-file invocation bought for nothing."""
        self._stage_two_identical_files()

        _advisories, calls = self._run_gate(["app.py", "util.py"])

        self.assertIsNone(calls[0]["kwargs"].get("input"))

    def test_the_same_branch_carries_any_language(self) -> None:
        """Language-blindness, re-expressed after materialization died: routing
        is the linter TABLE, not a per-language branch, so a .go file takes the
        identical path. Its linter is unconfigured here, so the observable fact
        is that it is skipped rather than mishandled — no branch inspects the
        extension."""
        (self.repo / "main.go").write_bytes(b"package main\n")
        self._git("add", "main.go")

        advisories, calls = self._run_gate(["main.go"])

        self.assertEqual(advisories, [])
        self.assertEqual(calls, [], "no linter claims .go here — a skip, not a crash")


if __name__ == "__main__":
    unittest.main()
