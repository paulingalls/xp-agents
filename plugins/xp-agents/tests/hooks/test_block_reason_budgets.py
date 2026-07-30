#!/usr/bin/env python3
"""Budgets for gate block/nudge reasons — the surface with no bound at all.

Every other injected surface in this plugin is budgeted: SKILL.md bodies,
agent definitions, the three guides, preload stdout, and (as of story-004)
`description:` frontmatter. Gate reasons were the gap. They reach a context
window on every fire, and nothing stopped them growing. `test_injection_budgets`
is the near neighbour but not a substitute: it measures each emitter's stdout on
an empty SMM — the *no-trigger* path — and says so. The prose bounded here only
exists once a gate actually fires, so nothing over there constrains it.

**This module bounds; it does not trim.** Story-004 measured the surface and
then read it. The measurement first, over the eight scripts it opened with:
48,648 chars, of which 9,169 are docstrings — developer-facing, never injected.
An earlier regex that counted ``\"\"\"`` blocks put the injected figure at ~32KB
and was wrong by more than an order of magnitude, which is why the budgets below
are calibrated rather than cut.

Then the reading: each surviving reason already names the cause that makes it
actionable, which is the bar `pre_tool_bash`'s worktree reason sets — it spends
348 chars to name the failure chain (a poisoned cwd makes the trailer-extract
read the wrong HEAD, so the Resolves-Event auto-link silently breaks), the fix,
and why the path must be literal rather than a shell variable. Shortening that
buys a few hundred bytes on one gate's fire and costs the reader the reason the
gate exists. The audit's verdict is therefore "already minimal", recorded here
rather than asserted by shrinking something that should not shrink.

**The declared set is curated, and cannot be discovered.** Sibling budget
modules end with a surface scan (`discover_emitter_scripts`,
`discover_preload_scripts`) that fails when a new surface ships unbudgeted. No
such scan is possible here: `reason_strings` reads string literals, and 89 of
this plugin's scripts carry at least one — mostly CLI usage and stderr text that
never reaches a context window. Requiring a budget for all of them would bound
the wrong thing. So `GATE_SCRIPTS` below is hand-maintained, and keeping it
current is a review responsibility rather than an assertion. A new hook that can
block, nudge, or advise belongs in it.

A budget calibrated to current size passes the moment it is written, which
proves nothing on its own. Two things carry the weight instead:
`TestExtractorIsNotVacuous` fails if the extractor silently stops finding
prose (the failure mode that would make every budget trivially satisfiable),
and `TestBudgetCanFail` re-measures a real script with one extra reason spliced
in, proving the bound bites on prose the extractor actually reads.
"""

import ast
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from conftest import _PLUGIN_ROOT

# Every module that can put a block reason, a nudge, or a gate advisory in front
# of an agent — hook entry points plus the helper modules they dispatch into,
# because that is where most of the prose actually lives (`pre_tool_bash.py`
# holds 1,040 chars; the three `pre_tool_bash_*` helpers it imports hold 2,370
# between them). Keys are plugin-root-relative: `story_done_gate` sits under
# `smm/`, not `scripts/`. hook_io.py carries no reason prose today (its long
# strings are all docstrings) but owns the emit path, so it stays declared — a
# reason added there must land under a budget rather than arriving unbounded.
GATE_SCRIPTS: tuple[str, ...] = (
    "scripts/bash_failure.py",
    "scripts/close_cycle_stop_gate.py",
    "scripts/close_verify_gate.py",
    "scripts/hook_io.py",
    "scripts/housekeeping_stop_gate.py",
    "scripts/kickoff_gate.py",
    "scripts/lead_gates.py",
    "scripts/post_tool_exit_plan.py",
    "scripts/pre_tool_bash.py",
    "scripts/pre_tool_bash_branch_delete.py",
    "scripts/pre_tool_bash_commit_gates.py",
    "scripts/pre_tool_bash_reviewer_guard.py",
    "scripts/pre_tool_plan_mode.py",
    "scripts/pre_tool_skill.py",
    "scripts/pre_tool_write.py",
    "scripts/review_cycle_done.py",
    "scripts/session_end_warning.py",
    "scripts/sprint_stop_gate.py",
    "scripts/subagent_stop.py",
    "scripts/task_completed.py",
    "scripts/tdd_stop_gate.py",
    "scripts/teammate_idle.py",
    "scripts/teammate_stop_gate.py",
    "scripts/trailer_gate.py",
    "smm/story_done_gate.py",
)

# round(chars * 1.125 / 10) * 10 over the measured reason prose, matching every
# sibling budget module. Headroom is ~11%, not 0% — a gate that gains a clause
# should not need a budget bump to say something true.
REASON_BUDGETS: dict[str, int] = {
    "scripts/bash_failure.py": 60,
    "scripts/close_cycle_stop_gate.py": 890,
    "scripts/close_verify_gate.py": 840,
    # Zero, deliberately: hook_io.py emits no reason prose today. Adding one
    # must be a considered bump here, not an unbounded arrival.
    "scripts/hook_io.py": 0,
    "scripts/housekeeping_stop_gate.py": 530,
    "scripts/kickoff_gate.py": 270,
    "scripts/lead_gates.py": 730,
    "scripts/post_tool_exit_plan.py": 300,
    "scripts/pre_tool_bash.py": 1170,
    "scripts/pre_tool_bash_branch_delete.py": 470,
    "scripts/pre_tool_bash_commit_gates.py": 1490,
    "scripts/pre_tool_bash_reviewer_guard.py": 700,
    "scripts/pre_tool_plan_mode.py": 480,
    "scripts/pre_tool_skill.py": 1150,
    "scripts/pre_tool_write.py": 720,
    "scripts/review_cycle_done.py": 960,
    "scripts/session_end_warning.py": 100,
    "scripts/sprint_stop_gate.py": 230,
    "scripts/subagent_stop.py": 350,
    "scripts/task_completed.py": 70,
    "scripts/tdd_stop_gate.py": 110,
    "scripts/teammate_idle.py": 60,
    "scripts/teammate_stop_gate.py": 210,
    "scripts/trailer_gate.py": 310,
    "smm/story_done_gate.py": 710,
}

# Minimum prose each script must still carry — round(chars * 0.85 / 10) * 10, so
# a gate has ~15% of shrink room before the floor bites. Guards the direction a
# budget cannot: a gate whose reason was deleted outright sails under its cap.
MIN_REASON_CHARS: dict[str, int] = {
    "scripts/bash_failure.py": 40,
    "scripts/close_cycle_stop_gate.py": 670,
    "scripts/close_verify_gate.py": 640,
    "scripts/hook_io.py": 0,
    "scripts/housekeeping_stop_gate.py": 400,
    "scripts/kickoff_gate.py": 200,
    "scripts/lead_gates.py": 550,
    "scripts/post_tool_exit_plan.py": 230,
    "scripts/pre_tool_bash.py": 880,
    "scripts/pre_tool_bash_branch_delete.py": 360,
    "scripts/pre_tool_bash_commit_gates.py": 1130,
    "scripts/pre_tool_bash_reviewer_guard.py": 530,
    "scripts/pre_tool_plan_mode.py": 360,
    "scripts/pre_tool_skill.py": 870,
    "scripts/pre_tool_write.py": 540,
    "scripts/review_cycle_done.py": 720,
    "scripts/session_end_warning.py": 80,
    "scripts/sprint_stop_gate.py": 170,
    "scripts/subagent_stop.py": 270,
    "scripts/task_completed.py": 50,
    "scripts/tdd_stop_gate.py": 80,
    "scripts/teammate_idle.py": 45,
    "scripts/teammate_stop_gate.py": 155,
    "scripts/trailer_gate.py": 240,
    "smm/story_done_gate.py": 540,
}

_MIN_PROSE_LEN = 25


def gate_path(name: str) -> Path:
    return _PLUGIN_ROOT / name


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


def reason_strings_of(source: str) -> list[str]:
    """Prose the given script source can emit into a context window.

    Docstrings are excluded: they are read by developers, never injected. An
    f-string is reconstructed once, with its literal parts joined and its
    interpolations rendered as ``{}`` — the pieces are NOT also counted
    separately, or a two-part f-string would score roughly double its true
    cost. Anything under 25 chars or without a space is a key, a flag or a
    sentinel rather than prose.
    """
    tree = ast.parse(source)
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


def reason_strings(path: Path) -> list[str]:
    return reason_strings_of(path.read_text(encoding="utf-8"))


def reason_chars(path: Path) -> int:
    return sum(len(s) for s in reason_strings(path))


class TestExtractorIsNotVacuous(unittest.TestCase):
    """A silent extractor makes every budget below trivially satisfiable.

    The story-001 lesson: a scan that stops matching must fail loudly rather
    than report green over nothing.
    """

    def test_every_declared_script_exists(self):
        for name in GATE_SCRIPTS:
            self.assertTrue(gate_path(name).is_file(), f"{name} named but not present")

    def test_budget_and_floor_keys_cover_every_script(self):
        self.assertEqual(sorted(REASON_BUDGETS), sorted(GATE_SCRIPTS))
        self.assertEqual(sorted(MIN_REASON_CHARS), sorted(GATE_SCRIPTS))

    def test_extractor_finds_a_known_reason(self):
        """Bound to a real string, so a broken extractor cannot pass silently."""
        found = reason_strings(gate_path("scripts/teammate_stop_gate.py"))
        self.assertIn(
            "Review cycle complete. Commit your changes before stopping.", found
        )

    def test_extractor_excludes_docstrings(self):
        """hook_io.py is 5893 chars, 1675 of them docstring, and emits no
        reason prose. If it scores non-zero the docstring filter has broken."""
        self.assertEqual(reason_chars(gate_path("scripts/hook_io.py")), 0)


class TestReasonBudgets(unittest.TestCase):
    def test_no_gate_exceeds_its_reason_budget(self):
        over = [
            f"{n}: {reason_chars(gate_path(n))}/{REASON_BUDGETS[n]}"
            for n in GATE_SCRIPTS
            if reason_chars(gate_path(n)) > REASON_BUDGETS[n]
        ]
        self.assertFalse(over, f"gate reason prose over budget: {over}")

    def test_no_gate_lost_its_reason(self):
        """The other direction: a budget alone rewards deleting the cause."""
        under = [
            f"{n}: {reason_chars(gate_path(n))} < {MIN_REASON_CHARS[n]}"
            for n in GATE_SCRIPTS
            if reason_chars(gate_path(n)) < MIN_REASON_CHARS[n]
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

    _NAME = "scripts/teammate_idle.py"
    _ADDED_REASON = (
        'BLOCK_REASON = "A spliced reason of roughly the length these gates '
        'actually use in practice."\n'
    )

    def test_added_prose_breaches_the_budget(self):
        actual = reason_chars(gate_path(self._NAME))
        self.assertGreater(
            REASON_BUDGETS[self._NAME] - actual, 0, "budget must leave headroom"
        )
        mutated = gate_path(self._NAME).read_text(encoding="utf-8") + self._ADDED_REASON
        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp) / "mutated.py"
            copy.write_text(mutated, encoding="utf-8")
            mutated_chars = reason_chars(copy)
        self.assertGreater(
            mutated_chars,
            actual,
            "the spliced reason was not counted — the extractor, not the "
            "budget, is what this test would otherwise be proving",
        )
        self.assertGreater(
            mutated_chars,
            REASON_BUDGETS[self._NAME],
            f"{self._NAME}: one added reason on top of {actual} must breach "
            f"{REASON_BUDGETS[self._NAME]}, or the budget bounds nothing",
        )


if __name__ == "__main__":
    unittest.main()
