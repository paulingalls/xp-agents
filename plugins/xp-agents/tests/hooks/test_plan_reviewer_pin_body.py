#!/usr/bin/env python3
"""Pin: xp-plan-reviewer body must guide AC-command/file_domain coherence.

Sprint-065 story-006 shipped with `acceptance_execution.command` pointing at
a probe file that did not exercise the new code — the AC command was green
without testing anything the story added. Per decision 250ba9657966 the fix
is prompt-side: xp-plan-reviewer parses each story's `acceptance_execution`
command(s) and verifies at least one pytest path lives inside (or equals) a
path in the story's `file_domain`. When none intersect, it emits a concern.

This pin keeps the guidance in the agent body (visible to the LLM) — not in
the frontmatter (where literal-text matches in `assertIn` would false-pass
without the agent ever reading it).

Split from test_plan_reviewer_pin.py by test-class grouping: this file
covers the xp-plan-reviewer.md agent-body prose pins (TestPlanReviewerPin).
See test_plan_reviewer_pin_new_file_rule.py for the NEW-file rejection
rule-loop simulation and the xp-plan SKILL.md discovery-pass pin.
"""

import unittest
from pathlib import Path

from conftest import _split_frontmatter_body

_AGENT_PATH = Path(__file__).parent.parent.parent / "agents" / "xp-plan-reviewer.md"


class TestPlanReviewerPin(unittest.TestCase):
    """xp-plan-reviewer.md body MUST direct an AC-command/file_domain check."""

    @classmethod
    def setUpClass(cls):
        cls.frontmatter, cls.body = _split_frontmatter_body(_AGENT_PATH.read_text())
        cls.body_lower = cls.body.lower()

    def test_agent_file_exists(self):
        self.assertTrue(
            _AGENT_PATH.is_file(),
            f"missing agent file: {_AGENT_PATH}",
        )

    def test_body_directs_read_of_system_context_rendered(self):
        # Plan-reviewer must Read SYSTEM_CONTEXT_RENDERED when the preload
        # emits it — that's the WHERE layer of the layered read path. Pin
        # the variable name in the body so a refactor that drops the
        # instruction fails loud.
        self.assertIn(
            "SYSTEM_CONTEXT_RENDERED",
            self.body,
            "xp-plan-reviewer body must direct the agent to Read the "
            "SYSTEM_CONTEXT_RENDERED tempfile when present — without it "
            "the reviewer cites the layered read path conceptually but "
            "never sees the WHERE.",
        )

    def test_body_pairs_acceptance_execution_with_file_domain(self):
        # Both literals must appear in the BODY (not just frontmatter) so the
        # agent prompt actually instructs the coherence check at review time.
        # Frontmatter `description` mentions could false-pass an `assertIn` on
        # the full file text — splitting on `---` prevents that escape.
        self.assertIn(
            "acceptance_execution",
            self.body,
            "xp-plan-reviewer body must reference `acceptance_execution` so "
            "the agent knows which story field to parse for AC commands",
        )
        self.assertIn(
            "file_domain",
            self.body,
            "xp-plan-reviewer body must reference `file_domain` so the agent "
            "knows which story field to intersect AC paths against",
        )

    def test_body_describes_intersection_check(self):
        # The pairing alone is not enough — the body must direct the agent to
        # check whether AC paths intersect file_domain. Pin a synonym set so a
        # phrasing tweak doesn't break the pin, but a missing instruction does.
        intersection_synonyms = ("intersect", "inside", "within", "overlap")
        self.assertTrue(
            any(token in self.body_lower for token in intersection_synonyms),
            "xp-plan-reviewer body must direct the agent to check whether "
            "AC pytest paths intersect (or live inside / overlap) the "
            f"story's file_domain — none of {intersection_synonyms} found",
        )

    def test_body_directs_concern_on_mismatch(self):
        # The check is only useful if a mismatch is recorded as a concern —
        # otherwise the AC drift escapes a future review the same way it did
        # in sprint-065 story-006.
        self.assertIn(
            "concern",
            self.body_lower,
            "xp-plan-reviewer body must direct the agent to emit a concern "
            "when AC paths do not intersect file_domain",
        )

    def test_body_covers_unittest_discover(self):
        # The codebase uses `python -m unittest discover -s <path>` as a
        # sequential fallback (see CLAUDE.md Testing). If the guidance only
        # extracts pytest tokens, an AC using unittest discover with a probe
        # path silently escapes the coherence check.
        self.assertIn(
            "unittest discover",
            self.body_lower,
            "xp-plan-reviewer body must include unittest discover in its "
            "AC-path extraction guidance, or unittest-style ACs slip through",
        )

    def test_body_covers_direct_script_invocations(self):
        # Section 10b also covers `python <path>` / `bash <path>` direct
        # script invocations as AC commands. Pin a token from that line so
        # a future trim of the bullet list can't silently drop it (symmetric
        # coverage with the unittest-discover pin above).
        self.assertIn(
            "direct script invocations",
            self.body_lower,
            "xp-plan-reviewer body must include direct script invocations "
            "(python/bash <path>) in its AC-path extraction guidance",
        )

    def test_body_covers_positional_whole_tree_taxonomy(self):
        # §10b now enumerates two runner shapes (positional-path vs
        # whole-tree). Pin both terms so a future trim can't collapse the
        # taxonomy back to the Python-only list and re-open the JS gap.
        self.assertIn(
            "positional-path runners",
            self.body_lower,
            "§10b must name the positional-path runner shape (playwright/jest/"
            "etc. that name their proof file on the CLI)",
        )
        self.assertIn(
            "whole-tree runners",
            self.body_lower,
            "§10b must name the whole-tree runner shape (script aliases / "
            "package-or-scheme runners that name no CLI path)",
        )

    def test_body_directs_non_verifiable_command_concern(self):
        # A recognized test-run that names no proof file (script alias /
        # whole-tree runner) is non-verifiable — the verify-touch gate cannot
        # confirm the story authored its proof. §10b must flag it as a concern
        # recommending the command name the spec, or JS script-alias stories
        # silently escape acceptance-authorship verification.
        self.assertIn(
            "non-verifiable",
            self.body_lower,
            "§10b must flag a test-run command that names no proof file as "
            "non-verifiable and recommend naming the spec",
        )

    # --- NEW-file path rejection ----------------------------------------
    #
    # When a story description contains language implying a new file or
    # module ("extract X to its own module", "introduce a helper", etc.)
    # and `file_domain` does not enumerate the implied path, the agent
    # MUST reject the plan — sprint-012 story-003 shipped a planning gap
    # exactly this way (concern 73cfb6b97049).
    #
    # Pin both halves: the verb vocabulary and the rejection directive.

    def test_body_directs_new_file_path_rejection(self):
        # The body must direct the agent to reject (not merely warn) when
        # a new-file verb appears without the implied path in file_domain.
        self.assertIn(
            "reject",
            self.body_lower,
            "xp-plan-reviewer body must direct the agent to reject the "
            "plan when a NEW-file verb implies a path absent from file_domain",
        )
        # `file_domain` must appear adjacent to the rejection guidance —
        # already pinned globally above, but a NEW-file rule that doesn't
        # name the field it intersects against is dead text.
        self.assertIn(
            "new",
            self.body_lower,
            "xp-plan-reviewer body must use the literal token 'new' (e.g., "
            "'NEW file', 'new module') so the rejection rule is grep-findable",
        )

    def test_body_lists_new_file_verbs(self):
        # Pin every verb the rule must scan for — drift in the verb list
        # is the exact failure mode that lets a future story description
        # slip past the rule. Spec is in execution_plan.json M-1
        # design_details and feature-requests doc §4.
        for verb in ("extract", "introduce", "add module", "create helper"):
            self.assertIn(
                verb,
                self.body_lower,
                f"xp-plan-reviewer body must list the new-file verb {verb!r} "
                "so the agent scans for it; drift in this vocabulary is the "
                "exact failure mode that escaped sprint-012 story-003",
            )

    # --- §10d verify-test coverage in the plan --------------------------
    #
    # M4 (execution_plan.json §Milestone 4): a story can declare an
    # acceptance_execution / per-AC command that runs a test the
    # implementation plan never writes — green-looking plan, missing test.
    # The reviewer must extract verify-bearing test paths and check they
    # appear among the implementation plan's stated file targets/steps,
    # emitting a HIGH-severity concern on a miss. A separate soft heuristic
    # flags unit-shaped story-level commands, recommending behavior shape.

    def test_body_directs_verify_test_path_coverage_in_plan(self):
        # The §10d rule needs a distinct grep anchor so it can't be confused
        # with §10b (which checks AC paths against the sprint file_domain).
        self.assertIn(
            "verify-test coverage",
            self.body_lower,
            "xp-plan-reviewer body must carry a 'verify-test coverage' rule "
            "(gather verify-bearing test paths from acceptance_execution / "
            "per-AC commands and check them against the plan under review)",
        )
        # Must name the IMPLEMENTATION PLAN as the artifact checked against —
        # NOT the sprint file_domain (that's §10b). 'file targets' alone
        # already appears in the execution-mode section, so pin the
        # rule-specific phrase.
        self.assertIn(
            "implementation plan",
            self.body_lower,
            "xp-plan-reviewer §10d must check verify test paths against the "
            "implementation plan's stated file targets/steps — name the "
            "'implementation plan' so it isn't read as the §10b file_domain "
            "check",
        )

    def test_body_directs_high_severity_concern_on_missing_test_path(self):
        # A missing verify test path is a HARD flag — HIGH severity concern.
        # Pin 'high-severity' (hyphenated) so it doesn't false-pass on the
        # frontmatter's 'highest-leverage'.
        self.assertIn(
            "high-severity",
            self.body_lower,
            "xp-plan-reviewer body must direct a HIGH-severity concern when a "
            "declared verify test path is absent from the plan's file targets",
        )

    def test_body_directs_unit_shape_soft_flag(self):
        # The shape heuristic: story-level commands matching unit-shape
        # indicators get a SOFT flag recommending behavior shape (not block).
        self.assertIn(
            "unit-shape",
            self.body_lower,
            "xp-plan-reviewer body must name the 'unit-shape' heuristic for "
            "story-level acceptance commands",
        )
        soft_tokens = ("soft", "recommend")
        self.assertTrue(
            any(token in self.body_lower for token in soft_tokens),
            "xp-plan-reviewer body must mark the shape flag as soft / a "
            "recommendation (not a block)",
        )
        # Must point at the behavior-shaped alternative so the nudge is
        # actionable. Pin 'behavior-shaped' (not bare 'behavior', which
        # appears in §6's 'caller behavior').
        self.assertIn(
            "behavior-shaped",
            self.body_lower,
            "xp-plan-reviewer body must recommend a behavior-shaped "
            "acceptance demo as the alternative to a unit-shaped command",
        )

    # --- §10d pin exemption for declared regression pins -----------------
    #
    # story-005 (risk 0624fc80abd7): a story may mark an existing declared
    # verify path as a deliberate regression pin via
    # `acceptance_execution.pins`. §10d's high-severity "missing plan file
    # target" concern must NOT fire for a pinned path, but the reviewer
    # must still flag a story where EVERY declared verify path is pinned
    # (no authored proof at all).

    def test_body_directs_pin_exemption(self):
        self.assertIn(
            "pins",
            self.body_lower,
            "xp-plan-reviewer body must reference acceptance_execution.pins "
            "so the agent knows a declared verify path can be a deliberate "
            "regression pin",
        )
        self.assertTrue(
            any(
                phrase in self.body_lower
                for phrase in ("pin exemption", "exempt from the", "exempt from §10d")
            ),
            "xp-plan-reviewer body must direct the agent to exempt a pinned "
            "path from the §10d high-severity missing-plan-target concern",
        )

    def test_body_flags_all_paths_pinned(self):
        self.assertTrue(
            any(
                phrase in self.body_lower
                for phrase in ("every declared verify path", "all declared verify path")
            ),
            "xp-plan-reviewer body must flag a story where every declared "
            "verify path is pinned — that story has no authored proof at all",
        )

    def test_body_flags_malformed_pin(self):
        # A pin written in the raw cd-relative form (instead of the required
        # repo-relative post-rebase token) silently no-ops — the exemption
        # never applies. The reviewer must flag this rather than let it pass
        # unnoticed (xp-code-reviewer finding on story-005, decision to close
        # concern 657e9f65db20 via a plan-time fail-loud check).
        self.assertIn(
            "malformed pin",
            self.body_lower,
            "xp-plan-reviewer body must flag a pin that matches none of the "
            "story's extracted verify paths as a malformed/stale pin",
        )

    # --- Trace verification reclassification ----------------------------
    #
    # When the agent verifies a trace and finds no real concern, it must
    # NOT emit a null `type=concern` event (which inflates the unresolved-
    # concern metric). Emit `type=decision` (or `type=status` with
    # category=trace) instead so the trace stays recorded without
    # polluting the concern stream.

    def test_body_directs_trace_reclassification(self):
        # The body must explicitly mention the trace context and direct
        # the agent toward `type=decision` (or `type=status` w/
        # category=trace) — pin both the trigger and the alternative.
        self.assertIn(
            "trace",
            self.body_lower,
            "xp-plan-reviewer body must mention 'trace' so the verification "
            "context is recognized",
        )
        # Decision OR status alternative must be present — pin via OR so a
        # phrasing that picks just one of the two doesn't break the pin,
        # but both-missing does.
        has_decision = "type=decision" in self.body_lower
        has_status_trace = (
            "type=status" in self.body_lower and "category=trace" in self.body_lower
        )
        self.assertTrue(
            has_decision or has_status_trace,
            "xp-plan-reviewer body must direct emitting type=decision (or "
            "type=status with category=trace) for verified-clean traces — "
            "found neither in body",
        )

    def test_body_warns_against_null_concern_for_trace(self):
        # The advisory only sticks if the body explicitly calls out the
        # anti-pattern (null/empty/clean concern) being reclassified — a
        # bare "use type=decision" without the contrast doesn't tell the
        # agent WHEN to apply it.
        self.assertTrue(
            any(
                phrase in self.body_lower
                for phrase in (
                    "null concern",
                    "empty concern",
                    "instead of",
                    "rather than",
                    "not type=concern",
                    "no real concern",
                )
            ),
            "xp-plan-reviewer body must warn against emitting a null/empty "
            "type=concern for trace verifications that find no real concern "
            "(otherwise the reclassification guidance has no trigger)",
        )


if __name__ == "__main__":
    unittest.main()
