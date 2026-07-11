#!/usr/bin/env python3
"""The perf gate's own guard: lefthook.yml must keep running the scale timers alone.

The wall-clock bounds in test_scale_invariants.TestScaleBenchmarks only mean something
when nothing else is competing for the box. That condition lives entirely in
lefthook.yml — `piped` (sequential) rather than `parallel`, and a `perf` command
that opts the timers in with XP_PERF=1 and disables xdist. Every one of those is a
single word that a later edit could drop with no test going red, silently voiding
the design while leaving a suite that still passes. Hence this file.

A guard that only asserts words are PRESENT in the config is nearly vacuous: it
stays green while the config points at a class that no longer exists, or while a
newly-gated timer elsewhere in the tree runs nowhere at all. So the assertions
below bind the config to reality — the `-k` selector must name a class that
exists in the file the command actually runs, and every XP_PERF-gated file in
the tree must be a file this command runs.

Text-level, not YAML-parsed: the plugin is stdlib-only and PyYAML is not available.
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


class TestPrePushSerializesThePerfTier(unittest.TestCase):
    def setUp(self):
        self.block = _hook("pre-push")
        self.perf = _command_body(self.block, "perf")
        self.assertTrue(self.perf, "pre-push must define the `perf` command")

    def test_pre_push_is_piped(self):
        self.assertRegex(
            self.block,
            r"(?m)^\s+piped:\s*true\b",
            "pre-push must be piped: without sequential execution the perf "
            "command races the integration suite's xdist workers — the exact "
            "contention the wall-clock bounds cannot survive.",
        )

    def test_pre_push_is_not_parallel(self):
        self.assertNotRegex(
            self.block,
            r"(?m)^\s+parallel:",
            "pre-push must not set parallel: lefthook rejects piped+parallel "
            "outright ('conflicting options'), which aborts EVERY push in the "
            "repo, and parallel alone re-introduces the contention.",
        )

    def test_perf_command_arms_the_timers_and_runs_them_alone(self):
        self.assertIn(
            "XP_PERF=1", self.perf, "perf command must arm the XP_PERF-gated timers"
        )
        self.assertIn(
            "-p no:xdist",
            self.perf,
            "perf command must disable xdist — the timers have to run alone",
        )

    def test_perf_command_selects_a_class_that_exists(self):
        """The `-k` selector is a string: rename the class and it silently matches
        nothing. pytest exits 5 there, so the push fails — but it fails cryptically,
        at the push, for everyone. Bind the selector to the class here instead."""
        selector = re.search(r"-k\s+(\S+)", self.perf)
        self.assertIsNotNone(selector, "perf command must select the timers with -k")
        name = selector.group(1)  # pyright: ignore[reportOptionalMemberAccess]
        self.assertRegex(
            name, r"^\w+$", "-k selector must be a bare class name, not an expression"
        )

        paths = _test_paths_in(self.perf)
        self.assertTrue(paths, "perf command must name the test file it runs")
        for path in paths:
            self.assertTrue(path.is_file(), f"perf command runs a missing file: {path}")
        self.assertTrue(
            any(f"class {name}" in p.read_text(encoding="utf-8") for p in paths),
            f"perf command selects `-k {name}`, but no class of that name exists in "
            f"{[p.name for p in paths]} — the selector would deselect every test.",
        )

    def test_the_selected_timers_stay_off_the_commit_gate(self):
        """The converse of the check below, and the one that protects the commit
        gate itself. `-k` naming a class that EXISTS is not enough: if the
        XP_PERF skipUnless is ever dropped from it, those wall-clock timers rejoin
        `pytest -n auto` at pre-commit and go red on 16-worker contention alone —
        the exact flakiness this whole tier exists to remove — and no test goes red
        to say so. Bind the selected class to its gate.
        """
        selector = re.search(r"-k\s+(\S+)", self.perf)
        self.assertIsNotNone(selector, "perf command must select the timers with -k")
        name = selector.group(1)  # pyright: ignore[reportOptionalMemberAccess]

        gated = [
            path
            for path in _test_paths_in(self.perf)
            if XP_PERF_GATE.search(
                _decorators_above(path.read_text(encoding="utf-8"), name)
            )
        ]
        self.assertTrue(
            gated,
            f"`class {name}` is what the perf command runs, but it carries no "
            "XP_PERF skipUnless — its wall-clock timers would also run on every "
            "commit under `pytest -n auto`, where contention alone turns them red.",
        )

    def test_every_xp_perf_gated_file_runs_at_the_push_gate(self):
        """An XP_PERF-gated class is skipped everywhere except this one command.
        If a second file grows scale timers and the command does not name it, its
        timers execute nowhere — green, and measuring nothing."""
        run_paths = {p.resolve() for p in _test_paths_in(self.perf)}
        for path in sorted(TESTS_ROOT.rglob("test_*.py")):
            if not XP_PERF_GATE.search(path.read_text(encoding="utf-8")):
                continue
            self.assertIn(
                path.resolve(),
                run_paths,
                f"{path.relative_to(REPO_ROOT)} has XP_PERF-gated timers but the "
                "lefthook `perf` command does not run it — they would never execute. "
                "Add the file to the perf command's run line.",
            )

    def test_perf_runs_after_the_other_pre_push_commands(self):
        """lefthook orders commands alphabetically by name, NOT by file order. perf
        must sort last so a real integration failure surfaces before a perf bound
        does — `piped` stops at the first failure."""
        names = _command_names(self.block)
        self.assertIn("perf", names, "pre-push must declare a `perf` command")
        self.assertGreater(len(names), 1, "pre-push must still run the other suites")
        self.assertEqual(
            "perf",
            max(names),
            f"`perf` must sort last among {sorted(names)} — lefthook runs commands "
            "in alphabetical order by name.",
        )


class TestPreCommitCannotArmTheTimers(unittest.TestCase):
    def test_tests_command_strips_xp_perf(self):
        """An exported XP_PERF=1 in the developer's shell must not re-arm the
        wall-clock bounds on the commit gate, where they run 16-wide."""
        tests = _command_body(_hook("pre-commit"), "tests")
        self.assertTrue(tests, "pre-commit must define the `tests` command")
        self.assertIn("-u XP_PERF", tests, "pre-commit tests must env -u XP_PERF")


if __name__ == "__main__":
    unittest.main()
