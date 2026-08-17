#!/usr/bin/env python3
"""Pin: Step 4b's full-review prescription states its own cost bound.

story-012. `scripts/_close_pipeline_review.md` Step 4b prescribes the broad
multi-agent correctness pass to every close mode above threshold and, before
this story, said nothing about scale — a customer run reached roughly a
hundred agents. The fix is prose-only, next to the launch line: what drives
scale, what the caller controls, a directive not to raise the tier, the
positional-argument trap, and "invoke the named workflow, never a
hand-authored substitute".

These pins prove the four claims are *stated* in the Step 4b section — they
cannot prove an orchestrating agent actually honors them. The mitigation this
story ships is prose guidance, not an enforced limit; the unbounded-fan-out
risk is narrowed, not closed.
"""

import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from conftest import _slice

_PLUGIN_ROOT = Path(__file__).parent.parent
_REVIEW_PATH = _PLUGIN_ROOT / "scripts" / "_close_pipeline_review.md"

_START_MARKER = "### Step 4b: Full code review (conditional)"
# Empty DELIBERATELY, per `_slice`'s contract: Step 4b is the LAST section
# of the review reference, so the region runs to EOF. A non-empty tuple
# naming the old `### Step 5` end marker would raise instead — Step 5 moved
# to `_close_pipeline_shared.md` when the reference was split by mode.
_END_MARKERS: tuple[str, ...] = ()

# Digit-carrying substrings that legitimately belong in the Step 4b section
# on its own (heading + step cross-references + its own ordered list), none
# of which are a review-cost cap. Order matters: longer/more-specific
# patterns are stripped before the bare "Step 4" fallback so it doesn't eat
# the digit out of "Step 4b" or "Step 4.5" first.
_ALLOWED_DIGIT_PATTERNS = (
    re.compile(r"Step 4b"),
    re.compile(r"Step 4\.5"),
    re.compile(r"Step 5c"),
    re.compile(r"Step 4\b"),
    re.compile(r"^\d+\.\s", re.MULTILINE),  # ordered-list item markers
    re.compile(r"python3"),  # the interpreter name, not a cap
)


def _strip_allowed_digits(section: str) -> str:
    stripped = section
    for pattern in _ALLOWED_DIGIT_PATTERNS:
        stripped = pattern.sub("", stripped)
    return stripped


def _stray_digit_matches(section: str) -> list[str]:
    """Digits left over after removing every allowed reference.

    Any survivor is a numeric literal that isn't a step/list marker —
    exactly the shape a copied-out review cap (finder count, candidate
    cap, report cap) would take.
    """
    return re.findall(r"\d+", _strip_allowed_digits(section))


class TestStep4bCostBoundProse(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = _REVIEW_PATH.read_text()
        cls.section = _slice(cls.text, _START_MARKER, _END_MARKERS)

    def test_file_exists(self):
        self.assertTrue(_REVIEW_PATH.is_file(), f"missing: {_REVIEW_PATH}")

    # --- AC-1: what drives scale + what the caller controls ---------------
    def test_states_scale_driver_and_caller_lever(self):
        self.assertRegex(
            self.section,
            r"(?i)candidate locations",
            "Step 4b must say verification scales with distinct candidate "
            "locations, not just finder count",
        )
        self.assertRegex(
            self.section,
            r"(?i)diff range",
            "Step 4b must name the diff range as the scale driver",
        )
        self.assertRegex(
            self.section,
            r"(?i)close's own range",
            "Step 4b must tell the caller to pass the close's own range, "
            "not a wider one",
        )

    # --- AC-2: directive not to raise the tier -----------------------------
    def test_directs_against_raising_the_tier(self):
        self.assertRegex(
            self.section,
            r"(?is)do not\s+raise\s+it",
            "Step 4b must directively tell the caller not to raise the tier",
        )
        self.assertRegex(
            self.section,
            r"(?i)finder agents",
            "Step 4b must state the consequence of raising the tier: more "
            "finder agents",
        )
        self.assertRegex(
            self.section,
            r"(?is)sweep\s+pass",
            "Step 4b must state the consequence of raising the tier: an "
            "extra sweep pass",
        )
        # The directive must not be phrased as a factual claim about which
        # tier is smallest — that ordering lives in a regenerated script and
        # would silently turn into a lie if it's ever reordered.
        self.assertNotRegex(
            self.section,
            r"(?i)smallest",
            "the tier directive must not claim which tier is 'smallest' — "
            "state the rule as a directive, not a fact about the ordering",
        )

    # --- AC-3: positional token trap ---------------------------------------
    def test_states_positional_token_trap(self):
        self.assertRegex(
            self.section,
            r"(?i)first word",
            "Step 4b must say the tier token is positional (the first word of args)",
        )
        self.assertRegex(
            self.section,
            r"(?is)does\s+not error",
            "Step 4b must say an unrecognised tier token does not error",
        )
        self.assertRegex(
            self.section,
            r"(?i)default tier",
            "Step 4b must say an unrecognised token falls back to the default tier",
        )
        self.assertRegex(
            self.section,
            r"(?is)absorbed into the diff\s+range",
            "Step 4b must say the stray word gets absorbed into the diff "
            "range, corrupting the review target",
        )

    # --- AC-4 companion: invoke the named launcher, never a substitute ----
    def test_directs_against_substitute_fanout(self):
        self.assertRegex(
            self.section,
            r"(?i)named skill",
            "Step 4b must direct the caller to invoke the named skill rather "
            "than authoring a substitute",
        )
        self.assertRegex(
            self.section,
            r"(?is)hand-authored\s+substitute",
            "Step 4b must name the actual runaway mechanism: a "
            "hand-authored substitute fan-out",
        )

    # --- AC-1 placement: alongside the invocation it prescribes ------------
    def test_bound_sits_alongside_the_launch_line(self):
        launch_pos = self.section.index('Skill(skill: "code-review"')
        bound_pos = self.section.index("Cost bound")
        self.assertLess(
            launch_pos,
            bound_pos,
            "the cost-bound prose must follow the launch line it describes",
        )
        # And it must not have fallen so far away that an unrelated step
        # heading (there are none inside this slice, but the ordered-list
        # items 2/3 are the nearest landmark) sits between them.
        wait_pos = self.section.index("**Wait**")
        self.assertLess(
            bound_pos,
            wait_pos,
            "the cost-bound prose must sit between the launch line and the "
            "next list item, not drift past it",
        )

    # --- Ordered list survives the insertion --------------------------------
    def test_ordered_list_still_has_all_three_items_in_order(self):
        # A top-level paragraph inserted after item 1 would terminate the
        # list and restart items 2-3 as a fresh "1." / "2." — corrupting the
        # launch -> wait -> consume sequence the orchestrator follows.
        #
        # THREE items, not four: the manual arm was item 1 until the built-in
        # became a Skill. `review_cycle_done` routes a `code-review` Skill to
        # the simplify target at launch (pinned in
        # tests/hooks/test_review_cycle_done.py), so arming by hand as well put
        # TWO writers on one review.
        positions = [
            self.section.index(marker)
            for marker in (
                '1. Launch `Skill(skill: "code-review"',
                "2. **Wait**",
                '3. `Skill(skill: "xp-quality-review")`',
            )
        ]
        self.assertEqual(
            positions,
            sorted(positions),
            "the launch -> wait -> consume list must stay intact and in "
            "order after the cost-bound insertion",
        )

    # --- The second writer that double-counted every close ------------------
    def test_does_not_arm_the_marker_by_hand_as_well(self):
        """One review, one `simplify_complete`.

        The launcher's own PostToolUse arms the review-cycle marker — that is
        `review_cycle_done`'s `code-review` routing, pinned in
        tests/hooks/test_review_cycle_done.py. Step 4b used to ALSO instruct a
        manual `review_flag_cli.py ... simplify_done`, which was right while the
        launcher was a Workflow (a Workflow completion never reaches a
        PostToolUse:Skill|Agent hook) and became a double-write the moment it
        was not.

        `retro_metrics._classify_lifecycle_events` increments with no dedup, so
        the retro reported two simplifies per review. Measured on this repo's
        own SMM before the fix: `simplify_complete` at 20:14:37 (the manual arm)
        and again at 20:18:32 (the hook, on the Skill launch), for one review.
        """
        self.assertNotIn(
            "review_flag_cli",
            self.section,
            "Step 4b must not arm the review-cycle marker by hand: the "
            "launcher's own PostToolUse already does, and two writers "
            "double-count the review in the retro",
        )

    # --- AC-4: no copied-out internal numbers -------------------------------
    def test_no_stray_numeric_literals_beyond_step_markers(self):
        stray = _stray_digit_matches(self.section)
        self.assertEqual(
            stray,
            [],
            f"Step 4b section carries numeric literal(s) beyond its own "
            f"step/list markers: {stray!r} — these are the command's "
            f"internal caps, which live in a script regenerated outside "
            f"this repo and drift silently; relay the shape of the bound, "
            f"not a copied number",
        )

    def test_stray_digit_guard_actually_bites(self):
        """Don't-pin, not a coverage claim: proves the allowlist isn't so
        broad it would wave a real cap through. Without this positive
        control the guard above could ship inert."""
        injected = self.section + "\nVerification spawns at most 25 agents.\n"
        stray = _stray_digit_matches(injected)
        self.assertIn(
            "25",
            stray,
            "the stray-digit guard failed to catch an injected cap-shaped "
            "literal — its allowlist is too broad to be a real drift guard",
        )


if __name__ == "__main__":
    unittest.main()
