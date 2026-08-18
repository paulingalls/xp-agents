#!/usr/bin/env python3
"""No preload side effect survives a call the gate beside this hook refuses.

Split out of `test_preload_injection.py` at the 500-line cap: these classes
share a fixture with each other (a real gate marker plus a preload that spends
it) and none with the delivery tests they left behind, which fake the preload
precisely so nothing is spent.

The property is one the injecting handler cannot observe. `pre_tool_skill.py`
sits on the same PreToolUse entry and can BLOCK the invocation; hooks on one
entry run in parallel. So the handler computes the same verdict itself and
declines to run the preload at all — which is the only place the side effect
can be stopped, because none of the consumes can move to PostToolUse: each
unblocks an operation the skill performs during its OWN run.
"""

import ast
import stat
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

import markers
import pre_tool_skill
import preload_injection
import skill_preload_map
from conftest import _HookTestCase


def _spending_preload(path: Path, gate: Path) -> Path:
    """A preload that SPENDS `gate` by running, and prints state.

    Local rather than shared with the delivery suite's `_write_script`, which
    the sibling shell-read suite also keeps its own copy of: that helper takes
    an arbitrary body, and the whole point here is that there is exactly one
    body — spend the gate, print state — so "the gate survived" and "nothing
    was injected" are one observation made twice. The preload never started.
    """
    path.write_text(f'#!/bin/sh\nrm -f "{gate}"\necho "STATE=here"\n', encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return path


class TestARefusedCallRunsNoPreload(_HookTestCase):
    """A call the gate beside this handler will REFUSE must leave no residue.

    `pre_tool_skill.py` sits on the same PreToolUse entry and can block the
    invocation; hooks on one entry run in parallel, so this handler cannot
    OBSERVE the refusal. It computes the same verdict itself instead, from the
    same two shipped predicates, and declines to run the preload at all.

    That matters because several preloads mutate shared state BY RUNNING —
    `/xp-accept` consumes the mark-done gate, `/xp-assign` consumes the assign
    Write gate, `/xp-review-plan` deletes `.plan-awaiting-review`. None of those
    consumes can move to PostToolUse: each unblocks an operation the skill
    performs during its OWN run. So the only place to stop the side effect is
    before the preload starts.

    Each specimen below asserts BOTH halves — the gate marker survives AND
    nothing is injected. Either alone passes on a broken half: a handler that
    ran the preload and discarded its output would satisfy the second, and one
    that injected a stale cache would satisfy the first.
    """

    def setUp(self):
        super().setUp()
        self.work = Path(self.smm_dir) / "work"
        self.work.mkdir()
        # A REAL directory with the teammate path segment in it. A nonexistent
        # cwd makes `subprocess.run` raise and the handler inject nothing, so a
        # made-up path passes the refusal tests without the guard existing.
        self.teammate_cwd = Path(self.smm_dir) / "worktree-story-001"
        self.teammate_cwd.mkdir()
        # A real gate marker, written through the production helper so the
        # filename is the one the shipped preload would consume.
        self.gate = markers.marker_path(Path(self.smm_dir), markers.ASSIGN_PENDING)
        markers.marker_write(Path(self.smm_dir), markers.ASSIGN_PENDING, "story-001")
        # Stands in for any mutating preload — see `_spending_preload`.
        self._fake = patch.object(
            skill_preload_map,
            "resolve_preload",
            return_value=skill_preload_map.PreloadInvocation(
                argv=[str(_spending_preload(self.work / "fake_preload.sh", self.gate))]
            ),
        )

    def _run(self, payload: dict) -> str | None:
        with self._fake:
            return preload_injection.run(payload)

    def test_a_blocked_teammate_leaves_the_gate_intact_and_gets_nothing(self):
        """The shipped refusal: a live CLI teammate invoking a lead-owned skill.

        Before this guard the teammate's blocked /xp-assign still ran the
        preload, which consumed the LEAD's assign gate.
        """
        output = self._run(
            {
                "tool_input": {"skill": "xp-agents:xp-assign"},
                "cwd": str(self.teammate_cwd),
            }
        )
        self.assertIsNone(output, "a refused call must receive no context either")
        self.assertTrue(self.gate.exists(), "the refused call consumed the gate")

    def test_a_lead_driving_story_close_with_no_accept_evidence_gets_nothing(self):
        """The second shipped refusal, and it is not a teammate one.

        `accept_evidence_block_reason` blocks /xp-story-close when no story is
        in `closing` — here there is no sprint at all.
        """
        output = self._run(
            {
                "tool_input": {"skill": "xp-agents:xp-story-close"},
                "cwd": str(self.work),
            }
        )
        self.assertIsNone(output)
        self.assertTrue(self.gate.exists())

    def test_the_lead_still_gets_its_injection_and_still_spends_the_gate(self):
        """The allowed direction, so the fix is not a blunt disable.

        Without this the guard could be `return None` and every test above
        would still pass, having broken the whole mechanism.
        """
        output = self._run(
            {"tool_input": {"skill": "xp-agents:xp-assign"}, "cwd": str(self.work)}
        )
        self.assertEqual(output, "STATE=here\n")
        self.assertFalse(self.gate.exists(), "the allowed call did not run the preload")

    def test_a_second_lead_invocation_is_not_starved(self):
        """Consumed exactly once, and the retry still gets state.

        The first-harness leg takes no claim by design; a guard that started
        taking one — or that cached its verdict — would leave the second call
        blind, which is the failure this handler's docstring reasons about.
        """
        first = self._run(
            {"tool_input": {"skill": "xp-agents:xp-assign"}, "cwd": str(self.work)}
        )
        second = self._run(
            {"tool_input": {"skill": "xp-agents:xp-assign"}, "cwd": str(self.work)}
        )
        self.assertEqual(first, "STATE=here\n")
        self.assertEqual(second, "STATE=here\n")

    def test_the_verdict_is_the_shipped_predicate_not_a_second_spelling(self):
        """One verdict, two callers. A reimplementation here would drift from
        `pre_tool_skill`'s own gate silently — this handler would start running
        preloads for calls that ARE refused, or refusing ones that are not."""
        payload = {
            "tool_input": {"skill": "xp-agents:xp-assign"},
            "cwd": str(self.teammate_cwd),
        }
        with patch.object(
            pre_tool_skill, "teammate_block_reason", return_value=None
        ) as shipped:
            output = self._run(payload)
        shipped.assert_called()
        self.assertEqual(
            output,
            "STATE=here\n",
            "the guard did not consult the shipped predicate — neutralizing it "
            "left the call refused anyway",
        )


class TestTheGuardPrecedesTheClaim(unittest.TestCase):
    """Placement, pinned structurally because it has no runtime observable.

    Claiming for a call that will be refused starves the user's retry after they
    clear the gate — the exact failure `run()`'s docstring reasons about for the
    other leg. Today only the SHELL-READ leg claims, and that leg carries no
    refusal to detect (both predicates key on `tool_input.skill`, which harness
    2's payload does not carry), so no fixture can make a refused call reach
    `_take_claim` and the ordering cannot be observed at runtime. It is still
    the property that must hold if a future change ever claims on both legs, so
    it is asserted over the AST of `run()` rather than left to a comment.
    """

    def _call_order(self) -> list[str]:
        source = Path(preload_injection.__file__).read_text(encoding="utf-8")
        run_fn = next(
            node
            for node in ast.parse(source).body
            if isinstance(node, ast.FunctionDef) and node.name == "run"
        )
        calls = [
            (node, node.func)
            for node in ast.walk(run_fn)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        ]
        # Sorted by position: `ast.walk` is breadth-first, so its own order
        # reflects nesting depth rather than the order the code runs in — and
        # the claim IS more deeply nested than the guard, which is exactly the
        # shape that would make a depth-ordered pin pass no matter what.
        calls.sort(key=lambda pair: (pair[0].lineno, pair[0].col_offset))
        return [func.id for _call, func in calls]

    def test_the_refusal_check_is_reached_before_any_claim(self):
        order = self._call_order()
        self.assertIn("_refused_by_a_gate", order, "the guard left run()")
        self.assertIn("_take_claim", order, "the claim left run()")
        self.assertLess(order.index("_refused_by_a_gate"), order.index("_take_claim"))


if __name__ == "__main__":
    unittest.main()
