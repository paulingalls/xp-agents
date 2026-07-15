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
"""

import re
import unittest
from pathlib import Path

from conftest import _split_frontmatter_body, triage

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


# Verbs the agent body documents — kept at module scope so the body pin
# above and the rule-loop pin below share a single source of truth. A
# drift between the verb list pinned in test_body_lists_new_file_verbs
# and the list used by the rule loop here would be a real bug, not
# test noise.
_NEW_FILE_VERBS: tuple[str, ...] = (
    "extract",
    "introduce",
    "add module",
    "create helper",
)

# Path-like tokens carry an extension (.ts/.py/.tsx/.md/.sh/...) and at
# least one '/' — same shape the agent body's example list uses
# (`apps/server/src/required-env.ts`, `scripts/foo.py`).
_PATH_TOKEN_RE = re.compile(r"(?:[\w-]+/)+[\w.-]+\.\w+")

# NEW-file context tokens — when a verb fires, one of these (or a
# path-like token) must co-occur in the same sentence to confirm the
# verb is talking about a file/module, not a value/data/concept.
# Mirrors §10c's "verb + context token" requirement.
_NEW_FILE_CONTEXT_TOKENS: tuple[str, ...] = ("module", "helper", "file", "to its own")


def _has_new_file_intent(description: str) -> bool:
    """Whole-word verb + NEW-file context token (or path-like) in same sentence.

    Mirrors §10c: bare-substring matches of `extract`/`introduce` on their
    own ("extract value from X", "introduce backwards-incompatible change")
    MUST NOT trigger — they need a co-occurring file/module/helper/path
    token in the same sentence.
    """
    desc_lower = description.lower()
    for sentence in re.split(r"[.!?]\s+", desc_lower):
        for verb in _NEW_FILE_VERBS:
            if not re.search(rf"\b{re.escape(verb)}\b", sentence):
                continue
            if any(t in sentence for t in _NEW_FILE_CONTEXT_TOKENS):
                return True
            if _PATH_TOKEN_RE.search(sentence):
                return True
    return False


def _flagged_missing_paths(description: str, file_domain: list[str]) -> list[str]:
    """Apply the NEW-file rejection rule to a (description, domain) pair.

    Mirrors the agent body's prose rule deterministically: when the
    description has a verb+context pair (whole-word verb co-occurring
    with a NEW-file context token in the same sentence), every path-like
    token in the description must appear in the (em-dash-stripped)
    file_domain. Tokens absent from the domain are returned in
    description order.

    Kept in this test module on purpose — the agent prompt is the
    canonical specification; this is a pin, not a runtime helper. If the
    rule grows beyond what one regex captures, it moves to a real module
    and this helper becomes a thin re-export.
    """
    if not _has_new_file_intent(description):
        return []
    domain_paths = triage.extract_file_domain_paths(file_domain)
    return [p for p in _PATH_TOKEN_RE.findall(description) if p not in domain_paths]


class TestPlanReviewerNewFileRule(unittest.TestCase):
    """Drive the NEW-file rule against an in-memory synthesized plan.

    Three milestone fixtures stand in for a synthesized execution plan:
    one ('real') has the implied path enumerated in file_domain — the
    rule must NOT flag; one ('missing') omits the implied path — the
    rule MUST flag and the assertEqual failure message names the
    missing path; one ('plain') has no new-file verb at all — must
    not flag regardless of domain shape.

    No SMM dependency, no subprocess, no pytest --collect-only. A future
    rule regression fires this test directly with the missing path in
    its assertion message — contrast test_execution_plan_ac_sync.py,
    which checks pytest's returncode in a child process (slower, opaquer).
    """

    def test_loop_flags_missing_fixture_naming_the_path(self):
        path = "apps/server/src/required-env.ts"
        extract_desc = f"extract REQUIRED_ENV to its own module at {path}"
        synthesized_plan = {
            "milestones": [
                {
                    "name": "Real: REQUIRED_ENV extracted, path enumerated",
                    "story": {
                        "description": extract_desc,
                        "file_domain": [path, "apps/server/src/index.ts"],
                    },
                    "expected_missing": [],
                },
                {
                    "name": "Missing: REQUIRED_ENV extracted, path omitted",
                    "story": {
                        "description": extract_desc,
                        "file_domain": ["apps/server/src/index.ts"],
                    },
                    "expected_missing": [path],
                },
                {
                    "name": "Plain: no new-file verb, no flag regardless",
                    "story": {
                        "description": "tighten an existing handler",
                        "file_domain": ["apps/server/src/index.ts"],
                    },
                    "expected_missing": [],
                },
                {
                    "name": "Em-dash domain entry: suffix stripped before compare",
                    "story": {
                        "description": extract_desc,
                        "file_domain": [f"{path} — new module"],
                    },
                    "expected_missing": [],
                },
                {
                    "name": "False positive: bare 'extract' no context — must NOT flag",
                    "story": {
                        "description": "extract value from request body for validation",
                        "file_domain": ["apps/server/src/index.ts"],
                    },
                    "expected_missing": [],
                },
                {
                    "name": "False positive: 'introduce' no file ctx — must NOT flag",
                    "story": {
                        "description": "introduce a backwards-incompatible API change",
                        "file_domain": ["apps/server/src/api.ts"],
                    },
                    "expected_missing": [],
                },
            ],
        }

        for milestone in synthesized_plan["milestones"]:
            story = milestone["story"]
            actual_missing = _flagged_missing_paths(
                story["description"],
                story["file_domain"],
            )
            self.assertEqual(
                actual_missing,
                milestone["expected_missing"],
                f"NEW-file rule loop regression on fixture milestone "
                f"{milestone['name']!r}: expected missing="
                f"{milestone['expected_missing']!r}, got {actual_missing!r} "
                f"(file_domain={story['file_domain']!r})",
            )


_PLAN_SKILL_PATH = (
    Path(__file__).parent.parent.parent / "skills" / "xp-plan" / "SKILL.md"
)


class TestPlanSkillDiscoveryPassPin(unittest.TestCase):
    """xp-plan SKILL.md MUST document the discovery-pass step (story-005).

    Sprint-067 logged file_domain drift on ALL 5 stories — 4th consecutive
    sprint with structural drift (retro Try 7fbdca46a558). The agreed
    response (decision e2ea588d7d38, Path A): planning grows a discovery
    pass that grep call-sites of symbols defined in declared change_zones
    and unions them into the milestone's footprint, so the planner sees the
    real impact before sprint stories are written.

    These pins keep the prose visible to the LLM at planning time. A
    future trim that drops the discovery instruction would silently
    re-open the structural drift; the test then fires on the missing
    keyword.
    """

    @classmethod
    def setUpClass(cls):
        # Split frontmatter from body — frontmatter `description` mentions
        # of "discovery"/"call-sites" would false-pass an `assertIn` on the
        # full file text without the agent ever reading the prose. Mirrors
        # the canonical `TestPlanReviewerPin` pattern in this same file.
        _, cls.body = _split_frontmatter_body(_PLAN_SKILL_PATH.read_text())
        cls.body_lower = cls.body.lower()

    def test_skill_file_exists(self):
        self.assertTrue(
            _PLAN_SKILL_PATH.is_file(),
            f"missing skill file: {_PLAN_SKILL_PATH}",
        )

    def test_body_documents_discovery_pass(self):
        # The literal "discovery" token anchors the step — grep-findable
        # by both reviewers and a future regression.
        self.assertIn(
            "discovery",
            self.body_lower,
            "xp-plan SKILL.md must document a 'discovery' step so the "
            "planner unions grepped call-sites into the milestone footprint "
            "(retro 7fbdca46a558, decision e2ea588d7d38)",
        )

    def test_body_directs_grep_call_sites(self):
        # Pin the mechanism: grep call-sites of declared symbols. Without
        # this the discovery step is a name without a method.
        self.assertIn(
            "call-sites",
            self.body_lower,
            "xp-plan SKILL.md discovery step must direct the agent to grep "
            "call-sites of declared symbols (the retro-agreed mechanism)",
        )

    def test_body_pairs_discovery_with_change_zones_or_file_domain(self):
        # Discovery must feed back into the planning artifact — either
        # change_zones (milestone-level) or file_domain (story-level).
        # Pin via OR so a phrasing that picks one doesn't break the test.
        has_change_zones = "change_zones" in self.body_lower
        has_file_domain = "file_domain" in self.body_lower
        self.assertTrue(
            has_change_zones or has_file_domain,
            "xp-plan SKILL.md discovery step must name the planning "
            "artifact it unions into (change_zones or file_domain) — "
            "found neither token near the discovery prose",
        )


if __name__ == "__main__":
    unittest.main()
