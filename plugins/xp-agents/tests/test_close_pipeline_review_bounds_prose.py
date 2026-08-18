#!/usr/bin/env python3
"""Pin: Step 4b's full-review prescription states its own cost bound.

story-012. `scripts/_close_pipeline_review.md` Step 4b prescribes the broad
multi-agent correctness pass to every close mode above threshold and, before
this story, said nothing about scale — a customer run reached roughly a
hundred agents. The fix was prose-only, next to the launch line: what drives
scale, what the caller controls, a directive not to raise the tier, and
"invoke the named launcher, never a hand-authored substitute".

WHAT CHANGED WHEN THE PASS BECAME OURS. Two of these pins were properties of a
built-in nobody here controlled, and both are now settled in code rather than
asked for in prose:

  - The positional-token trap is GONE, and its pin with it. `args` is an object,
    so there is no first word to misread, no silent fall to a default tier and
    no stray token absorbed into the diff range. The replacement pin asserts the
    object shape — deleting a warning about a failure that can no longer happen
    is only correct if something checks the shape that replaced it.
  - The fan-out is capped IN THE SCRIPT, and the script says what the cap
    dropped. So the sentence about scale is no longer the mitigation; it is a
    pointer to one. The residual this docstring used to record — "narrowed, not
    closed" — is closed for the primary launcher, and stands for the fallback,
    which is still a built-in whose internals nothing here can bound.

These pins prove the claims are *stated* in the Step 4b section. They cannot
prove an orchestrating agent honors them; the numeric cap is proven in
tests/workflows/code_review_test.js, where it is executable.
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

    # --- AC-3 (replaces the positional trap): the args are an object --------
    def test_states_the_args_are_an_object_with_its_fields_named(self):
        """What the retired trap pin becomes.

        The trap was real for a launcher that parsed a level out of the first
        word of a string. Ours takes an object, so the failure cannot occur —
        and a warning about an impossible failure is worse than no warning,
        because it teaches a shape that is not the one in use. The obligation
        that replaces it is that the object's fields are actually named here:
        `pluginRoot` in particular has no default worth having, since a finder
        that cannot read its angle reviews with no lens at all and still
        returns.
        """
        self.assertRegex(
            self.section,
            r"(?i)args.{0,40}object|object.{0,40}args",
            "Step 4b must say args is an object, not a positional string",
        )
        for field in ("level", "range", "pluginRoot"):
            with self.subTest(field=field):
                self.assertIn(
                    field,
                    self.section,
                    f"Step 4b must name the {field!r} arg field",
                )
        self.assertNotRegex(
            self.section,
            r"(?i)first word",
            "the positional-token trap belonged to a launcher that parsed a "
            "level out of a string; repeating it here documents a failure "
            "this launcher cannot have",
        )

    def test_the_bound_points_at_the_cap_in_the_script(self):
        """The fan-out bound is code now, and the prose has to say so.

        Its predecessor was the whole mitigation and said as much: a customer
        run reached ~100 agents and the answer was a paragraph asking the
        orchestrator to be careful. The paragraph stays — it still governs the
        RANGE, which no script can choose — but the fan-out it could only
        request is now enforced, and a silent truncation is the failure mode
        that matters, since a capped pass reads exactly like a complete one.
        """
        self.assertRegex(
            self.section,
            r"(?is)capped in the script",
            "Step 4b must say the fan-out cap lives in the script rather than "
            "in this prose",
        )
        self.assertRegex(
            self.section,
            r"(?is)cap dropped|dropped.{0,40}cap",
            "Step 4b must say the script reports what the cap dropped — a "
            "truncated review that says nothing reads as a complete one",
        )

    # --- AC-4 companion: invoke the named launcher, never a substitute ----
    def test_directs_against_substitute_fanout(self):
        self.assertRegex(
            self.section,
            r"(?is)shipped\s+script",
            "Step 4b must direct the caller to launch the shipped script "
            "rather than authoring a substitute",
        )
        self.assertRegex(
            self.section,
            r"(?is)named\s+skill",
            "Step 4b must direct the caller to invoke the named skill on the "
            "fallback path rather than authoring a substitute",
        )
        self.assertRegex(
            self.section,
            r"(?is)hand-authored\s+substitute",
            "Step 4b must name the actual runaway mechanism: a "
            "hand-authored substitute fan-out",
        )

    # --- AC-1 placement: alongside the invocation it prescribes ------------
    def test_bound_sits_alongside_the_launch_line(self):
        # Anchored on the PRIMARY launch. It used to be the Skill literal,
        # which now sits in the fallback paragraph BELOW the wait step — an
        # anchor there would assert the bound had drifted to the bottom of the
        # section, which is the opposite of what this checks.
        launch_pos = self.section.index("Workflow({ scriptPath:")
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
    def test_ordered_list_still_has_all_four_items_in_order(self):
        # A top-level paragraph inserted mid-list would terminate it and
        # restart the remainder as a fresh "1." / "2." — corrupting the
        # arm -> launch -> wait -> consume sequence the orchestrator follows.
        #
        # FOUR items again. The arm was dropped when the launcher became a
        # Skill, whose PostToolUse arms at launch; the primary launcher is a
        # Workflow again, which reaches no such hook, so the by-hand arm is
        # back — scoped to this path, with the fallback's own "do not repeat
        # it" pinned separately below.
        positions = [
            self.section.index(marker)
            for marker in (
                "1. **Arm the marker**",
                "2. **Launch it**",
                "3. **Wait**",
                '4. `Skill(skill: "xp-quality-review")`',
            )
        ]
        self.assertEqual(
            positions,
            sorted(positions),
            "the arm -> launch -> wait -> consume list must stay intact and in order",
        )

    # --- The arm is launcher-conditional, which is the whole trap -----------
    def test_arms_the_marker_by_hand_only_on_the_workflow_path(self):
        """One review, one `simplify_complete` — but the arm cannot just be
        deleted now, because the two launchers differ.

        A Workflow completion reaches no `PostToolUse:Skill|Agent` hook, so on
        the primary path nothing arms the marker and the by-hand arm is the
        only writer. The Skill fallback DOES reach one —
        `review_cycle_done` routes a `code-review` Skill to the simplify target
        at launch (pinned in tests/hooks/test_review_cycle_done.py) — so arming
        by hand there as well puts two writers on one review.
        `retro_metrics._classify_lifecycle_events` increments with no dedup, so
        that double-write reported two simplifies per review. Measured on this
        repo's own SMM when it last shipped: `simplify_complete` at 20:14:37
        (the by-hand arm) and again at 20:18:32 (the hook), for one review.

        An unconditional instruction is therefore wrong in BOTH directions —
        omit it and the primary path never defers the close Stop gate; repeat
        it on the fallback and the retro double-counts.
        """
        self.assertIn(
            "review_flag_cli",
            self.section,
            "the Workflow launcher reaches no PostToolUse hook, so Step 4b "
            "must arm the review-cycle marker by hand",
        )
        self.assertRegex(
            self.section,
            r"(?is)arm above is skipped|do not repeat it|must\s+not repeat it",
            "Step 4b must say the by-hand arm is skipped on the Skill "
            "fallback, whose own PostToolUse arms it at launch",
        )

    def test_the_disarm_precedes_the_fallback_launch(self):
        """Ordering, and it is not cosmetic.

        The arm is taken at launch and cleared only by a landed commit, so a
        failed launch leaves it set. Falling back first and disarming after
        would clear the flag the FALLBACK's own PostToolUse had just set,
        putting the close back in the state the disarm exists to escape: a
        `/xp-quality-review` reading self-find while a broad review's findings
        are on their way.
        """
        disarm_pos = self.section.index("--disarm")
        fallback_pos = self.section.index('Skill(skill: "code-review"')
        self.assertLess(
            disarm_pos,
            fallback_pos,
            "Step 4b must disarm BEFORE launching the Skill fallback — after, "
            "the disarm lands on the fallback's own arm",
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
