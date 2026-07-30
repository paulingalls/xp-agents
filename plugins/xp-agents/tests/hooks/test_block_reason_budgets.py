#!/usr/bin/env python3
"""Budgets for gate block/nudge reasons — the surface with no bound at all.

Every other injected surface in this plugin is budgeted: SKILL.md bodies,
agent definitions, the three guides, preload stdout, and (as of story-004)
`description:` frontmatter. Gate reasons were the gap. They reach a context
window on every fire, and nothing stopped them growing.

**This module bounds; it does not trim.** Story-004 measured the surface and
then read it. The measurement first: the eight scripts hold 48,648 chars, but
9,169 of those are docstrings — developer-facing, never injected — and only
~1,969 chars are actual reason prose. An earlier regex that counted ``\"\"\"``
blocks put the figure at ~32KB and was wrong by more than an order of
magnitude, which is why the budget below is calibrated rather than cut.

Then the reading: each surviving reason already names the cause that makes it
actionable, which is the bar `pre_tool_bash`'s worktree reason sets — it spends
348 chars to name the failure chain (a poisoned cwd makes the trailer-extract
read the wrong HEAD, so the Resolves-Event auto-link silently breaks), the fix,
and why the path must be literal rather than a shell variable. Shortening that
buys a few hundred bytes on one gate's fire and costs the reader the reason the
gate exists. The audit's verdict is therefore "already minimal", recorded here
rather than asserted by shrinking something that should not shrink.

A budget calibrated to current size passes the moment it is written, which
proves nothing on its own. Two things carry the weight instead:
`TestExtractorIsNotVacuous` fails if the extractor silently stops finding
prose (the failure mode that would make every budget trivially satisfiable),
and `TestBudgetCanFail` mutates a real reason to prove the bound bites.
"""

import ast
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from conftest import _PLUGIN_ROOT

_SCRIPTS_DIR = _PLUGIN_ROOT / "scripts"

# The hooks whose stdout/stderr reaches a context window: block reasons,
# nudges, and gate advisories. hook_io.py carries none today (its long strings
# are all docstrings) but owns the emit path, so it stays declared — a reason
# added there must land under a budget rather than arriving unbounded.
GATE_SCRIPTS: tuple[str, ...] = (
    "hook_io.py",
    "kickoff_gate.py",
    "pre_tool_bash.py",
    "pre_tool_plan_mode.py",
    "pre_tool_write.py",
    "task_completed.py",
    "teammate_idle.py",
    "teammate_stop_gate.py",
)

# round(chars * 1.125 / 10) * 10 over the measured reason prose, matching every
# sibling budget module. Headroom is ~11%, not 0% — a gate that gains a clause
# should not need a budget bump to say something true.
REASON_BUDGETS: dict[str, int] = {
    # Zero, deliberately: hook_io.py emits no reason prose today. Adding one
    # must be a considered bump here, not an unbounded arrival.
    "hook_io.py": 0,
    "kickoff_gate.py": 270,
    "pre_tool_bash.py": 1170,
    "pre_tool_plan_mode.py": 480,
    "pre_tool_write.py": 720,
    "task_completed.py": 70,
    "teammate_idle.py": 60,
    "teammate_stop_gate.py": 210,
}

# Minimum prose each script must still carry. Guards the direction a budget
# cannot: a gate whose reason was deleted outright sails under its cap.
MIN_REASON_CHARS: dict[str, int] = {
    "hook_io.py": 0,
    "kickoff_gate.py": 200,
    "pre_tool_bash.py": 880,
    "pre_tool_plan_mode.py": 360,
    "pre_tool_write.py": 540,
    "task_completed.py": 50,
    "teammate_idle.py": 45,
    "teammate_stop_gate.py": 155,
}

_MIN_PROSE_LEN = 25


def _docstrings(tree: ast.AST) -> set[str]:
    found = set()
    for node in ast.walk(tree):
        if isinstance(
            node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
        ):
            text = ast.get_docstring(node, clean=False)
            if text:
                found.add(text)
    return found


def reason_strings(path: Path) -> list[str]:
    """Prose this script can emit into a context window.

    Docstrings are excluded: they are read by developers, never injected. An
    f-string is reconstructed once, with its literal parts joined and its
    interpolations rendered as ``{}`` — the pieces are NOT also counted
    separately, or a two-part f-string would score roughly double its true
    cost. Anything under 25 chars or without a space is a key, a flag or a
    sentinel rather than prose.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docs = _docstrings(tree)
    inside_fstring: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr):
            for part in ast.walk(node):
                if part is not node:
                    inside_fstring.add(id(part))

    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr):
            text = "".join(
                v.value
                if isinstance(v, ast.Constant) and isinstance(v.value, str)
                else "{}"
                for v in node.values
            ).strip()
        elif (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and id(node) not in inside_fstring
            and node.value not in docs
        ):
            text = node.value.strip()
        else:
            continue
        if len(text) >= _MIN_PROSE_LEN and " " in text:
            found.append(text)
    return found


def reason_chars(path: Path) -> int:
    return sum(len(s) for s in reason_strings(path))


class TestExtractorIsNotVacuous(unittest.TestCase):
    """A silent extractor makes every budget below trivially satisfiable.

    The story-001 lesson: a scan that stops matching must fail loudly rather
    than report green over nothing.
    """

    def test_every_declared_script_exists(self):
        for name in GATE_SCRIPTS:
            self.assertTrue(
                (_SCRIPTS_DIR / name).is_file(), f"{name} named but not present"
            )

    def test_budget_and_floor_keys_cover_every_script(self):
        self.assertEqual(sorted(REASON_BUDGETS), sorted(GATE_SCRIPTS))
        self.assertEqual(sorted(MIN_REASON_CHARS), sorted(GATE_SCRIPTS))

    def test_extractor_finds_a_known_reason(self):
        """Bound to a real string, so a broken extractor cannot pass silently."""
        found = reason_strings(_SCRIPTS_DIR / "teammate_stop_gate.py")
        self.assertIn(
            "Review cycle complete. Commit your changes before stopping.", found
        )

    def test_extractor_excludes_docstrings(self):
        """hook_io.py is 5893 chars, 1675 of them docstring, and emits no
        reason prose. If it scores non-zero the docstring filter has broken."""
        self.assertEqual(reason_chars(_SCRIPTS_DIR / "hook_io.py"), 0)


class TestReasonBudgets(unittest.TestCase):
    def test_no_gate_exceeds_its_reason_budget(self):
        over = [
            f"{n}: {reason_chars(_SCRIPTS_DIR / n)}/{REASON_BUDGETS[n]}"
            for n in GATE_SCRIPTS
            if reason_chars(_SCRIPTS_DIR / n) > REASON_BUDGETS[n]
        ]
        self.assertFalse(over, f"gate reason prose over budget: {over}")

    def test_no_gate_lost_its_reason(self):
        """The other direction: a budget alone rewards deleting the cause."""
        under = [
            f"{n}: {reason_chars(_SCRIPTS_DIR / n)} < {MIN_REASON_CHARS[n]}"
            for n in GATE_SCRIPTS
            if reason_chars(_SCRIPTS_DIR / n) < MIN_REASON_CHARS[n]
        ]
        self.assertFalse(
            under,
            "gate(s) lost reason prose — a block that no longer names its "
            f"cause is not actionable: {under}",
        )


class TestBudgetCanFail(unittest.TestCase):
    """Proves the bound bites, since calibrating to current size means the
    budget test above passes on first write and would pass equally if the
    comparison were inverted."""

    def test_added_prose_breaches_the_budget(self):
        name = "teammate_idle.py"
        actual = reason_chars(_SCRIPTS_DIR / name)
        headroom = REASON_BUDGETS[name] - actual
        self.assertGreater(headroom, 0, "budget must leave headroom")
        # One more sentence of the size these gates actually use.
        self.assertGreater(
            actual + 60,
            REASON_BUDGETS[name],
            f"{name}: a 60-char reason added on top of {actual} must breach "
            f"{REASON_BUDGETS[name]}, or the budget is not bounding anything",
        )


if __name__ == "__main__":
    unittest.main()
