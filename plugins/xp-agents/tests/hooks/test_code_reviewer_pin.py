#!/usr/bin/env python3
"""Pin: xp-code-reviewer body must direct update-in-place + decision nudge.

Sprint-066 story-003 (M-1 R1 signal-quality hardening) added two prompt
directives the agent must carry every review:

1. **Update-in-place over fresh debt on refactor relocation.** When a debt
   already exists for the same concern and the refactor merely moves the
   anchor file, the reviewer must update the existing event (anchor / files)
   rather than append a near-duplicate debt. Pairs with the advisory text in
   `duplicate_debt_probe.build_advisory_concern`.

2. **Nudge type=decision when a commit introduces a new pattern.** When the
   diff introduces a new architectural pattern, the reviewer must prompt a
   `decision` event so future plan-reviewers detect supersession via the
   pattern #5 (`concerns.py` superseded-decision detector) cycle.

Pinning these in the BODY (not frontmatter) ensures the agent prompt itself
carries the directives at review time. Frontmatter `description` text could
false-pass an `assertIn` against the full file otherwise.
"""

import re
import unittest
from pathlib import Path

from conftest import _split_frontmatter_body

_AGENT_PATH = Path(__file__).parent.parent.parent / "agents" / "xp-code-reviewer.md"


class TestCodeReviewerPin(unittest.TestCase):
    """xp-code-reviewer.md body MUST carry update-in-place + decision nudge."""

    @classmethod
    def setUpClass(cls):
        cls.frontmatter, cls.body = _split_frontmatter_body(_AGENT_PATH.read_text())
        cls.body_lower = cls.body.lower()

    def test_body_directs_update_in_place_on_duplicate_debt(self):
        # The reviewer must prefer updating the existing debt's anchor over
        # appending a fresh near-duplicate debt event. Pin a synonym set so
        # phrasing tweaks survive but a missing directive does not.
        update_synonyms = ("update-in-place", "update in place", "relocate", "anchor")
        self.assertTrue(
            any(token in self.body_lower for token in update_synonyms),
            "xp-code-reviewer body must direct anchor relocation (update the "
            "existing debt's anchor / files in place) on refactor relocation "
            f"rather than append a fresh debt — none of {update_synonyms} found",
        )

    def test_body_names_resolves_link_mechanism(self):
        # The directive is only actionable if the agent knows HOW to retire
        # the older debt. Pin `metadata.resolves` — the universal resolution
        # link consumed by resolution.compute_resolutions for any event type.
        # The earlier `update-item` / `supersedes` framing was wrong:
        # `update-item` operates on shared_mental_model.json pillar items
        # (not events.jsonl events), and `metadata.supersedes` is consumed
        # only by concerns.py pattern #5 on DECISION events sharing a topic.
        self.assertIn(
            "metadata.resolves",
            self.body_lower,
            "xp-code-reviewer body must name `metadata.resolves` (the "
            "universal resolution link) as the mechanism for retiring the "
            "older debt — NOT update-item or supersedes-on-debt",
        )

    def test_body_nudges_decision_event_on_new_pattern(self):
        # When a commit introduces a NEW pattern, the reviewer must nudge a
        # type=decision event so concerns.py pattern #5 can detect future
        # supersession. Pin both 'decision' and 'pattern' near each other.
        self.assertIn(
            "decision",
            self.body_lower,
            "xp-code-reviewer body must mention emitting a `decision` event "
            "as a soft cue for new patterns",
        )
        self.assertIn(
            "pattern",
            self.body_lower,
            "xp-code-reviewer body must mention `pattern` so the new-pattern "
            "decision nudge has a triggering condition",
        )

    def test_decision_nudge_co_locates_with_pattern_trigger(self):
        # A loose `decision` mention elsewhere (e.g., in `Drift Management`)
        # would false-pass test_body_nudges_decision_event_on_new_pattern.
        # Require both tokens within a single ~240-char window so the prompt
        # actually pairs the trigger (new pattern) with the action (decision
        # event) — order-agnostic.
        co_located = re.search(
            r"decision.{0,240}pattern|pattern.{0,240}decision",
            self.body_lower,
            re.DOTALL,
        )
        self.assertIsNotNone(
            co_located,
            "xp-code-reviewer body must co-locate `decision` and `pattern` "
            "(within ~240 chars) so the new-pattern decision nudge reads as "
            "a single directive — not two unrelated mentions",
        )

    def test_decision_nudge_requires_stable_topic(self):
        # concerns.py pattern #5 keys decisions_by_topic by `topic`. A
        # decision event with no topic (or an ad-hoc one-off slug) silently
        # disables the detector — so the nudge MUST instruct the author to
        # set a stable topic, otherwise the directive ships broken-by-design.
        self.assertIn(
            "topic",
            self.body_lower,
            "xp-code-reviewer decision-nudge must instruct setting a stable "
            "`topic` slug — pattern #5 keys supersession detection on topic "
            "and silently no-ops on empty / ad-hoc topics",
        )

    def test_decision_nudge_remains_advisory(self):
        # Per story constraint: the nudge is a SOFT prompt cue, not an
        # enforcement gate. Pin a softener so a future tightening to "MUST"
        # / "REQUIRE" enforcement-language trips this test and forces the
        # author to revisit the constraint.
        softeners = ("nudge", "soft", "cue", "prompt", "consider")
        self.assertTrue(
            any(token in self.body_lower for token in softeners),
            "xp-code-reviewer decision-nudge must read as advisory (one of "
            f"{softeners}) — story-003 constraint forbids it being an "
            "enforcement gate",
        )


if __name__ == "__main__":
    unittest.main()
