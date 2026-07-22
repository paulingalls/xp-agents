#!/usr/bin/env python3
"""Doctrine-prose pins for xp-plan-reviewer's review rules and final message.

Debt 5e180220db1a: the forked subagent's terminating message previously only
nudged the next step (e.g. "run /xp-assign"), so the main agent couldn't see
concerns/assumptions/blocking-questions without digging into events.jsonl.

The fix is prose-only — extend the agent prompt to require the reviewer to
end its reply with an enumerated summary covering all four. This test pins
the doctrine so a later edit can't silently strip the requirement (same
shape as test_sequential_pins.py).

Code↔spec link (one-directional, per feedback_declarative_skill_prose): this
file is the canonical pin for `agents/xp-plan-reviewer.md`'s `## Final Message`
section + the four block headings `Concerns` / `Assumptions` /
`Blocking questions` / `Next step`, and for the §2c real-behavior rule inside
`### 2. TDD Ordering`. The agent prose stays declarative and does NOT point
back at this test path — keep the pointer here, not there.
"""

import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from conftest import _PLUGIN_ROOT, _slice, assert_project_agnostic

_PLAN_REVIEWER_MD = _PLUGIN_ROOT / "agents" / "xp-plan-reviewer.md"

# Substring markers — match the formatter-stable text, not the bold markup
# (same rationale as test_sequential_pins.MARKER). Each marker must appear
# WITHIN the Final Message section, not just anywhere in the file: words
# like "Assumptions" (section 6 header) and "Blocking questions" (prose
# at lines 33/75/77) already appear elsewhere, so a file-wide substring
# check would let an individual-bullet gutting of Final Message slip
# through. Scoping the search to the section catches partial-deletion
# regressions, not just wholesale heading removal.
_REQUIRED_MARKERS = (
    "Concerns",
    "Assumptions",
    "Blocking questions",
    "Next step",
)

_FINAL_MESSAGE_HEADING = "## Final Message"

# §2c "real behavior, not reachability" lives inside the TDD Ordering section.
_TDD_HEADING = "### 2. TDD Ordering"

# The bar §2c sets, pinned verbatim (lowercased at compare time): a plan must
# name a check that flips state across the change, not one built to pass.
_RED_TEST_PHRASE = "fails before the change and passes after"

# What passes review today when only reachability is checked.
_INERT_TOKENS = ("inert", "no-op", "fail-open")


class TestPlanReviewerFinalMessage(unittest.TestCase):
    """Final-message contract surfaces concerns/assumptions/questions to main."""

    @classmethod
    def setUpClass(cls):
        cls.body = _PLAN_REVIEWER_MD.read_text()
        # Slice from "## Final Message" to the next "## " heading (or EOF)
        # so the marker check only inspects the section that owns the
        # doctrine. Falls back to empty string when the heading is absent
        # — test_final_message_section_present catches that case loudly.
        start = cls.body.find(_FINAL_MESSAGE_HEADING)
        if start == -1:
            cls.final_message_section = ""
        else:
            after = cls.body.find("\n## ", start + len(_FINAL_MESSAGE_HEADING))
            cls.final_message_section = (
                cls.body[start:] if after == -1 else cls.body[start:after]
            )
        # The Next-step options are backtick-delimited literals. Pin the
        # BLOCKING one on its own: a section-wide substring check is vacuous
        # here, because "/xp-assign", "implementation" and "record" all
        # already appear in the sibling clean-plan options and the section
        # intro, so it would stay green even if the blocking option were
        # reverted to demanding another review round.
        cls.blocking_option = next(
            (
                opt
                for opt in re.findall(r"`([^`]+)`", cls.final_message_section)
                if opt.startswith("BLOCKING")
            ),
            "",
        )

    def test_file_exists(self):
        self.assertTrue(
            _PLAN_REVIEWER_MD.is_file(),
            f"agent prompt missing at {_PLAN_REVIEWER_MD}",
        )

    def test_final_message_section_present(self):
        # An explicit return-message section makes the contract checkable;
        # the Output section alone is about the human-readable review body.
        self.assertIn(
            "Final Message",
            self.body,
            "xp-plan-reviewer.md must declare a 'Final Message' section "
            "so the doctrine for the return-to-main reply is discoverable.",
        )

    def test_required_blocks_named(self):
        missing = [m for m in _REQUIRED_MARKERS if m not in self.final_message_section]
        self.assertEqual(
            missing,
            [],
            "xp-plan-reviewer.md Final Message section must name each "
            f"required block; missing: {missing}",
        )

    # --- Next step routes forward, not back into another review round ----
    #
    # The re-review loop was driven from here: the blocking Next-step option
    # read "...then re-review", so every revision re-entered review and the
    # reviewer kept demanding another round. Nothing bounded it. The customer
    # stopped it twice by hand.
    #
    # Scoped to the Final Message section on purpose: §7's re-review-pass
    # guidance is deliberately KEPT — it still governs a second pass someone
    # explicitly asks for. What must go is the reviewer DEMANDING one.
    #
    # What these pins do NOT claim: "record the answer into the plan" is
    # agent-compliance prose, exactly like the "then re-review" it replaces.
    # These tests pin that the INSTRUCTION exists, never that the main agent
    # obeyed it. That trade is deliberate — the only gate that could enforce
    # it would have to read the plan's prose for an answer, which is a worse
    # mechanism than the problem. Don't read a green run here as evidence
    # the answer actually reached implementation.

    def test_blocking_option_is_locatable(self):
        # Guard for the three pins below: they all read blocking_option, so a
        # reformat that stops it parsing would silently vacate them.
        self.assertNotEqual(
            self.blocking_option,
            "",
            "Final Message must still offer a backticked Next-step option "
            "starting with 'BLOCKING' — the pins below key on it.",
        )

    def test_blocking_option_does_not_demand_another_review_round(self):
        self.assertNotIn(
            "re-review",
            self.final_message_section.lower(),
            "The Next-step blocking option must not route a blocking finding "
            "back into another review round — that demand is the loop. An "
            "explicitly requested second pass still works (§7 keeps its "
            "re-review-pass guidance); the reviewer just stops asking for one.",
        )

    def test_blocking_option_records_the_answer_into_the_plan(self):
        # Load-bearing half. Today the user's answer reaches implementation
        # only VIA the second review; drop the second review without this
        # step and the answer is simply lost.
        lowered = self.blocking_option.lower()
        self.assertIn(
            "record",
            lowered,
            "The Next-step blocking option must direct the main agent to "
            "record the AskUserQuestion answer, or dropping the re-review "
            "loses the answer entirely",
        )
        self.assertIn(
            "into the plan",
            lowered,
            "The answer must be recorded INTO THE PLAN — that is what carries "
            "it forward to implementation once the second review is gone",
        )

    def test_blocking_option_routes_forward_to_execution(self):
        lowered = self.blocking_option.lower()
        self.assertIn(
            "/xp-assign",
            lowered,
            "The blocking option must route forward to the teammate-mode "
            "next step, the same destination a clean plan gets",
        )
        self.assertIn(
            "implementation",
            lowered,
            "The blocking option must route forward to implementation in solo "
            "mode, carrying outstanding findings with it",
        )


class TestPlanReviewerRealBehaviorRule(unittest.TestCase):
    """§2c must demand evidence the change alters behavior, not just reachability.

    The reviewer validated REACHABILITY — a fix is wired and called — and
    accepted that as evidence the fix works, so an inert or fail-open change
    passed review; one shipped inert and had to be ripped out. The discipline
    was being applied in this repo only because a project-local memory injected
    it into the reviewer's context, which means every OTHER project using the
    plugin got a reviewer with no real-behavior demand at all. These pins keep
    the rule in the shipped agent, where every project sees it.

    What these pins do NOT claim — the same caveat the Final-Message pins
    above carry, and the one §2c itself is about: they prove the RULE TEXT is
    present and correctly scoped, never that a reviewer reading it flags an
    inert plan. That is reviewer judgment, unobservable from here. Don't read
    a green run as evidence an inert plan would be caught.
    """

    _MISSING_HEADING = (
        f"xp-plan-reviewer.md must keep the '{_TDD_HEADING}' section — "
        "the real-behavior rule belongs beside 2a/2b as a TDD-shape rule"
    )

    @classmethod
    def setUpClass(cls):
        cls.body = _PLAN_REVIEWER_MD.read_text()
        # Fail loud with the real reason rather than letting `_slice` raise a
        # bare "substring not found" for every test in the class. NOT tolerated
        # by falling back to an empty section: the vocabulary scan below would
        # then pass vacuously on a missing rule.
        if _TDD_HEADING not in cls.body:
            raise AssertionError(cls._MISSING_HEADING)
        # Scope to §2 so a passing match proves the rule sits beside the other
        # TDD-ordering rules (2a/2b) rather than anywhere in the 200-line file.
        cls.section = _slice(cls.body, _TDD_HEADING, ("\n### ",))
        cls.section_lower = cls.section.lower()

    def test_tdd_section_present(self):
        self.assertIn(_TDD_HEADING, self.body, self._MISSING_HEADING)

    def test_real_behavior_rule_is_numbered_2c(self):
        self.assertIn(
            "2c",
            self.section,
            "The real-behavior rule must be numbered 2c inside the TDD "
            "Ordering section, beside 2a (tests first) and 2b (commit cadence)",
        )

    def test_demands_a_check_that_fails_before_and_passes_after(self):
        # Canonical phrase — the whole point of the rule. If a rewording is
        # deliberate, update this pin in the same commit.
        self.assertIn(
            _RED_TEST_PHRASE,
            self.section_lower,
            f"§2c must demand a check that {_RED_TEST_PHRASE!r}; without it "
            "the reviewer has no stated bar for evidence that a change "
            "actually alters behavior",
        )

    def test_names_reachability_as_insufficient_evidence(self):
        self.assertIn(
            "reachab",
            self.section_lower,
            "§2c must name reachability explicitly — 'the fix is wired and "
            "called' is the exact evidence the rule rejects",
        )
        self.assertTrue(
            any(token in self.section_lower for token in _INERT_TOKENS),
            "§2c must name the failure it catches (an inert / no-op / "
            f"fail-open change); none of {_INERT_TOKENS} found",
        )

    def test_refactor_carve_out_demands_unchanged_checks(self):
        # A behavior-preserving refactor has no check that flips across it —
        # its proof is existing checks passing UNCHANGED (the same logic §10d's
        # pin exemption encodes). Without this clause §2c's literal reading
        # flags every refactor plan, and a rule that cries wolf on its first
        # day gets ignored. The carve-out is written as a DEMAND (name the
        # checks) rather than an exemption, so "it's just a refactor" can't
        # become the escape hatch an inert fix walks through.
        self.assertIn(
            "refactor",
            self.section_lower,
            "§2c must say what a behavior-preserving refactor owes instead of "
            "a fails-before/passes-after check, or it flags every refactor plan",
        )
        self.assertIn(
            "unchanged",
            self.section_lower,
            "§2c's refactor carve-out must require existing checks to pass "
            "UNCHANGED — that is the refactor's proof, and it is what stops "
            "the carve-out from excusing a behavior change",
        )

    def test_red_run_must_be_performed_not_assumed(self):
        # A plan may assert "this test would fail before the change" without
        # anyone running it. The rule is only real if the red run is performed.
        self.assertIn(
            "not assumed",
            self.section_lower,
            "§2c must require the failing run to be performed, not assumed — "
            "an unrun red claim is the same reasoning-instead-of-evidence "
            "failure the rule exists to catch",
        )

    def test_rule_is_project_agnostic(self):
        # The shared helper owns the "scan RAW, never lowercase" contract —
        # §2c must work for projects in any language and must not name this
        # plugin's internal surfaces.
        assert_project_agnostic(self, self.section, "§2c")


if __name__ == "__main__":
    unittest.main()
