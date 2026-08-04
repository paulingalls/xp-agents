#!/usr/bin/env python3
"""The analyzer's surface-authoring prose — the only writer of `paths`/`command`.

Extracted from `test_system_analyzer_prompt.py`, which sat at 468 lines against
a recorded ceiling of 468 — zero headroom — while story-018 needed to add pins
here. The band ratchet forbids growth, so extraction was the only legal move;
this group was the cohesive one, sharing no fixture with the maxlength-sync and
update-mode tests it left behind.

WHY THIS PROSE IS LOAD-BEARING. Nothing populates `acceptance_surfaces[].paths`
or `.command` except a human confirming a proposal this prompt asks for. Delete
the prose and the whole 014-018 chain is permanently dormant — the
shipped-but-inert shape this repo has paid for repeatedly. So these are pins on
a mechanism, not style checks on wording.

AND IT IS A CONSENT MECHANISM. Declaring `paths` switches a close gate from
"run the whole suite" to "run these commands" before an UNATTENDED merge, and
narrowing carries a residual risk no code can remove: a change whose blast
radius lands in a surface the selection did not pick can auto-merge green,
caught only at sprint close. Blast radius is undecidable language-agnostically,
so the answer is informed consent — the person opting in must be told before
they opt in. These tests are what keep them told.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

_ANALYZER = Path(__file__).parent.parent.parent / "agents" / "xp-system-analyzer.md"


class TestSurfaceAuthoringPrompt(unittest.TestCase):
    """story-017 AC4/AC5. Nothing populates surface `paths`/`command` unless
    the analyzer proposes them, so this prose is the only thing standing
    between the whole 014-017 chain and permanent dormancy.
    """

    def setUp(self) -> None:
        self.md = _ANALYZER.read_text()

    def test_it_proposes_and_confirms_rather_than_inferring(self) -> None:
        self.assertIn("only what they confirm", self.md)

    def test_it_says_why_a_guessed_command_is_dangerous(self) -> None:
        """A rule without its reason gets trimmed by the next editor."""
        self.assertIn("auto-merge", self.md)

    def test_it_proposes_a_residue_surface(self) -> None:
        """Without a command-less surface over the unclaimed paths, the
        all-or-nothing veto means narrowing never fires and every declared
        command is inert."""
        self.assertIn("residue surface", self.md)

    def test_the_residue_surface_carries_no_command(self) -> None:
        self.assertIn("no `command`", self.md)


class TestNarrowingIsAnInformedChoice(unittest.TestCase):
    """story-018 AC6/AC7, answering concerns 93c3a7f51618 and 7011f2040970.

    Declaring `paths` switches a gate that MERGES WITHOUT ASKING from "run the
    whole suite" to "run these commands". Two residual risks survive that no
    code can remove, because both are undecidable language-agnostically:

    1. The veto proves PATH coverage, not REGRESSION coverage. A change whose
       blast radius lands in a surface the selection did not pick auto-merges
       green at story close, and is caught only at sprint close, which keeps
       the full command deliberately.
    2. Collapse swaps N surface commands for `stack.test_command`, ASSUMING it
       covers every surface. A multi-harness project (browser=playwright,
       cli=pytest) whose test_command runs only one of them tests LESS after
       collapsing than before.

    So the answer is consent, not analysis: the person opting in has to be told
    before they opt in, and this prose is the only place they are told.
    """

    def setUp(self) -> None:
        self.md = _ANALYZER.read_text()

    def test_it_requires_evidence_of_independence_before_proposing(self) -> None:
        """Narrowing across coupled surfaces is where risk 1 actually bites, so
        `paths` is proposed only where independence was observed."""
        self.assertIn("independen", self.md.lower())

    def test_it_declines_out_loud_rather_than_staying_silent(self) -> None:
        """A silent non-proposal is indistinguishable from not having looked."""
        self.assertIn("decline", self.md.lower())

    def test_it_states_that_a_cross_surface_break_can_auto_merge(self) -> None:
        """Risk 1, in the sentence the customer confirms against. Mutation:
        drop it -> red, and the opt-in stops being informed."""
        self.assertIn("sprint close", self.md)

    def test_it_states_the_collapse_fallback_assumption(self) -> None:
        """Risk 2. `stack.test_command` is what a full selection collapses TO
        and what the gate falls back to, so it must cover every surface."""
        self.assertIn("cover every surface", self.md)


if __name__ == "__main__":
    unittest.main()
