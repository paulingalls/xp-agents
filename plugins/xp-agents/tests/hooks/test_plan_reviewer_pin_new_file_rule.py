#!/usr/bin/env python3
"""Pin: NEW-file rejection rule-loop simulation + xp-plan discovery-pass pin.

Sprint-012 story-003 shipped a planning gap where a story description
implied a new file/module but `file_domain` never enumerated the path
(concern 73cfb6b97049). `TestPlanReviewerNewFileRule` drives a deterministic
in-memory simulation of the agent body's prose rule (see
test_plan_reviewer_pin_body.py's `test_body_lists_new_file_verbs` and
`test_body_directs_new_file_path_rejection` for the prose pins that keep
this rule visible to the LLM at review time).

`TestPlanSkillDiscoveryPassPin` is a separate concern: it pins the
xp-plan SKILL.md discovery-pass step (story-005, retro 7fbdca46a558 /
decision e2ea588d7d38) that grep-unions call-sites into a milestone's
footprint before sprint stories are written.

Split from test_plan_reviewer_pin.py by test-class grouping. See
test_plan_reviewer_pin_body.py for the xp-plan-reviewer.md agent-body
prose pins (TestPlanReviewerPin).
"""

import re
import unittest
from pathlib import Path

from conftest import _split_frontmatter_body, triage

# Verbs the agent body documents — kept at module scope so the body pin in
# test_plan_reviewer_pin_body.py's test_body_lists_new_file_verbs and the
# rule-loop pin below share a single source of truth. A drift between the
# two verb lists would be a real bug, not test noise.
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
        # the canonical `TestPlanReviewerPin` pattern in
        # test_plan_reviewer_pin_body.py.
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
