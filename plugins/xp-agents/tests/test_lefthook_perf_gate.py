#!/usr/bin/env python3
"""The retired perf tier's guard: the wall-clock timers must stay retired.

This file used to pin that lefthook kept running the scale timers alone. The tier
is gone — a wall-clock bound measures the machine, not the diff, and serializing
`perf` after `all-tests` only ever controlled the contention that same run
created. A concurrent CLI teammate (a recorded Key Decision of this project) was
invisible to it, and because story close pushes, a blocking timer failed closes
whose diff touched none of it.

The invariants those timers stood in for are asserted structurally now, on WHAT
gets parsed rather than how long it took — TestReadDeltaParseCost and
TestCompactParseCost in tests/engine/test_scale_invariants.py, and
test_repair_single_pass_no_double_parse in tests/engine/test_maintenance.py.

So the guard INVERTS rather than disappearing. Deleting it outright would leave
nothing stopping the tier's return, and the failure it always existed to catch is
unchanged: a gate that runs nothing and reports green. With no `perf` command,
any XP_PERF-gated class would execute nowhere and skip silently — so the
assertion is now that no such class exists, and no such command is declared.

Text-level, not YAML-parsed: the plugin is stdlib-only and PyYAML is not available.
`LEFTHOOK` and `_uncommented` are imported by test_env_strip_mirror.py; both are
part of this module's contract and must survive any rework.
"""

import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from conftest import _PLUGIN_ROOT

# _PLUGIN_ROOT is <repo>/plugins/xp-agents; lefthook.yml lives at the repo root.
REPO_ROOT = _PLUGIN_ROOT.parents[1]
LEFTHOOK = REPO_ROOT / "lefthook.yml"
TESTS_ROOT = _PLUGIN_ROOT / "tests"

# The pre-push command that runs the whole suite under xdist. The name must sort
# BEFORE "perf" — lefthook orders commands alphabetically and `perf` has to run
# last, alone, for its wall-clock bounds to mean anything. Naming this `tests`
# would sort it after `perf` and silently invert that guarantee, which is why
# the name is a named constant rather than a literal spelled at three sites.
_SUITE_COMMAND = "all-tests"

# A class opted into the perf tier, i.e. skipped unless XP_PERF is set. Any file
# holding one of these runs ONLY from lefthook's perf command; if that command
# does not name the file, the timers inside it execute nowhere.
XP_PERF_GATE = re.compile(r"""skipUnless\(\s*os\.environ\.get\(\s*["']XP_PERF["']""")


def _top_level_block(text: str, name: str) -> str:
    """Return the lines under top-level key `name:`, up to the next top-level key.

    Top-level comments do not end a block — a `# ...` line at column 0 between
    two commands is prose, not the next key, and truncating there would drop
    real commands from the block and turn these assertions into false reds.
    """
    lines = text.splitlines()
    try:
        start = next(i for i, line in enumerate(lines) if line.startswith(f"{name}:"))
    except StopIteration:
        raise AssertionError(f"lefthook.yml has no top-level '{name}:' block") from None

    body = []
    for line in lines[start + 1 :]:
        if line and not line[0].isspace() and not line.startswith("#"):
            break  # next top-level key
        body.append(line)
    return "\n".join(body)


def _uncommented(block: str) -> str:
    """Strip full-line comments — prose about `parallel` is not a `parallel:` key."""
    return "\n".join(
        line for line in block.splitlines() if not line.lstrip().startswith("#")
    )


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip())


def _command_names(block: str) -> list[str]:
    """Names of the commands declared under this hook's `commands:` key."""
    names: list[str] = []
    lines = [line for line in block.splitlines() if line.strip()]
    commands_indent: int | None = None
    name_indent: int | None = None
    for line in lines:
        if line.strip() == "commands:":
            commands_indent = _indent(line)
            continue
        if commands_indent is None:
            continue
        if _indent(line) <= commands_indent:
            break  # left the commands: mapping
        if name_indent is None:
            name_indent = _indent(line)
        if _indent(line) == name_indent and line.strip().endswith(":"):
            names.append(line.strip()[:-1])
    return names


def _command_body(block: str, name: str) -> str:
    """The lines nested under command `name:` within this hook's block."""
    lines = block.splitlines()
    for i, line in enumerate(lines):
        if line.strip() != f"{name}:":
            continue
        indent = _indent(line)
        body = []
        for nxt in lines[i + 1 :]:
            if not nxt.strip():
                continue
            if _indent(nxt) <= indent:
                break
            body.append(nxt)
        return "\n".join(body)
    return ""


def _hook(name: str) -> str:
    return _uncommented(_top_level_block(LEFTHOOK.read_text(encoding="utf-8"), name))


def _test_paths_in(run: str) -> list[Path]:
    """Repo-relative test paths the command actually runs."""
    return [
        REPO_ROOT / token
        for token in run.split()
        if token.startswith("plugins/") and token.endswith(".py")
    ]


def _decorators_above(text: str, class_name: str) -> str:
    """The contiguous decorator lines directly above `class <class_name>`."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if not line.startswith(f"class {class_name}"):
            continue
        above = []
        for prev in reversed(lines[:i]):
            if not prev.strip() or prev.lstrip().startswith("#"):
                continue
            if not prev.startswith("@") and not prev.startswith(" "):
                break  # not part of the decorator block
            above.append(prev)
        return "\n".join(above)
    return ""


class TestThePerfTierStaysRetired(unittest.TestCase):
    def setUp(self):
        self.block = _hook("pre-push")

    def test_pre_push_declares_no_perf_command(self):
        """The tier is retired, not merely unused.

        A `perf` command reappearing is how the false reds come back: it would
        arm wall-clock bounds inside a BLOCKING push gate, where a concurrent
        teammate's load — which the gate cannot see, let alone attribute — fails
        closes whose diff touched none of it.
        """
        self.assertNotIn(
            "perf",
            _command_names(self.block),
            "pre-push declares a `perf` command again. Wall-clock bounds measure "
            "the machine, not the diff; assert what the code touches instead (see "
            "TestCompactParseCost / TestReadDeltaParseCost).",
        )

    def test_no_xp_perf_gated_class_survives_anywhere(self):
        """The inverted sweep, and the reason this file still exists.

        With no command to arm XP_PERF, a gated class runs NOWHERE — it skips in
        every suite, in CI, and at both gates, reporting green while measuring
        nothing. That is the same failure the original guard existed to catch,
        so the premise inverts and the assertion stays.
        """
        offenders = [
            str(path.relative_to(REPO_ROOT))
            for path in sorted(TESTS_ROOT.rglob("test_*.py"))
            if XP_PERF_GATE.search(path.read_text(encoding="utf-8"))
        ]
        self.assertEqual(
            offenders,
            [],
            f"{offenders} carry an XP_PERF skipUnless, but nothing sets XP_PERF "
            "any more — those tests skip everywhere and assert nothing. Either "
            "make them ungated structural assertions, or delete them.",
        )

    def test_pre_push_is_piped(self):
        """Kept, with a new reason. Its original justification — keeping `perf`
        from racing the suite's xdist workers — retired with the tier, so state
        the surviving one rather than leaving a pin whose rationale is gone:
        piped stops at the first failure, and a second command added here later
        must not race this one."""
        self.assertRegex(
            self.block,
            r"(?m)^\s+piped:\s*true\b",
            "pre-push must stay piped — it stops at the first failure, and any "
            "command added beside all-tests must not race it.",
        )

    def test_pre_push_is_not_parallel(self):
        self.assertNotRegex(
            self.block,
            r"(?m)^\s+parallel:",
            "pre-push must not set parallel: lefthook rejects piped+parallel "
            "outright ('conflicting options'), which aborts EVERY push in the repo.",
        )

    def test_pre_push_still_runs_a_suite(self):
        """Vacuity guard. Every assertion above is satisfied by an empty pre-push
        block, so without this the retirement could be 'achieved' by deleting the
        gate entirely."""
        names = _command_names(self.block)
        self.assertIn(
            _SUITE_COMMAND,
            names,
            f"pre-push must still declare `{_SUITE_COMMAND}` — retiring the timers "
            "must not retire the suite.",
        )


class TestTheCommitGateStaysNarrow(unittest.TestCase):
    """Unrelated to the retired tier, and kept as-is.

    The `-u XP_PERF` strips that used to live here went with the variable: once
    nothing sets XP_PERF, stripping it is a no-op whose stated reason ("arms the
    perf tier") describes machinery that no longer exists — and a strip declared
    with a false reason is precisely what the env-strip registry forbids.
    """

    def test_pre_commit_no_longer_runs_the_suite(self):
        """The commit gate runs the staged tests, never the whole tree.

        Pinned as an assertion rather than left implicit: a `tests` command
        reappearing here silently restores a ~7-minute commit gate, which is
        what pushed this project toward batching in the first place.
        """
        self.assertFalse(
            _command_body(_hook("pre-commit"), "tests"),
            "pre-commit must not define a `tests` command — the suite runs on "
            "pre-push. See decision superseding the run-tests-on-every-commit "
            "convention.",
        )


if __name__ == "__main__":
    unittest.main()
