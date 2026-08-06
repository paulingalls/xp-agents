#!/usr/bin/env python3
"""Tests for concerns.detect_conflicts — pattern 2: assumption contradicted.

Split from test_common_conflicts.py (pure move, no test-body edits).
Sibling patterns: overlap (1), convention (3), stale_question (4),
superseded (5) each live in their own test_common_conflicts_<pattern>.py.

Every case that expects a contradiction DECLARES the refutation, through the
shared `refutes_metadata` fixture — one home for the shape across the four
suites that seed one. A bare reference is not a refutation; see
TestReferenceIsNotRefutation at the bottom for why, and for the three measured
shapes it fires on.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import concerns
from conftest import _HookTestCase, make_event, refutes_metadata

# Explicit `from event_schema import EVENT_TYPE_*` so a future constant rename
# fails at test collection (NameError) instead of silently changing a
# make_event(...) call's behavior.
from event_schema import (
    EVENT_TYPE_ASSUMPTION,
    EVENT_TYPE_CONCERN,
    EVENT_TYPE_DISCOVERY,
    EVENT_TYPE_STATUS,
    METADATA_KEY_REFUTES,
    METADATA_KEY_RESOLVES,
    METADATA_KEY_SUPERSEDES,
)


class TestDetectConflictsCommon(_HookTestCase):
    def test_without_file_path_runs_other_patterns(self):
        """Patterns 2-5 still run when file_path=None."""
        a = make_event(EVENT_TYPE_ASSUMPTION, content="API is REST")
        d = make_event(
            EVENT_TYPE_DISCOVERY,
            content="Actually GraphQL",
            references=[a["id"]],
            metadata=refutes_metadata(a),
        )
        found = concerns.detect_conflicts([a, d], "main")
        self.assertTrue(any("contradict" in c["content"].lower() for c in found))

    def test_assumption_contradicted_concern_references_assumption(self):
        """Flag concern references the assumption event it flags (WEAK link)."""
        a = make_event(EVENT_TYPE_ASSUMPTION, content="API is REST")
        d = make_event(
            EVENT_TYPE_DISCOVERY,
            content="Actually GraphQL",
            references=[a["id"]],
            metadata=refutes_metadata(a),
        )
        found = concerns.detect_conflicts([a, d], "main")
        flag = next(c for c in found if "contradict" in c["content"].lower())
        self.assertEqual(flag.get("references"), [a["id"]])

    def test_assumption_contradicted_within_budget(self):
        """Assumption contradicted concern must stay within the concern budget
        (read from the schema below, so a budget change cannot strand it)."""
        from event_schema import get_required_budget

        a = make_event(EVENT_TYPE_ASSUMPTION, content="x" * 300)
        d = make_event(
            EVENT_TYPE_DISCOVERY,
            content="y" * 300,
            references=[a["id"]],
            metadata=refutes_metadata(a),
        )
        found = concerns.detect_conflicts([a, d], "main")
        flag = next(c for c in found if "contradict" in c["content"].lower())
        budget = get_required_budget("concern")
        self.assertLessEqual(
            len(flag["content"]),
            budget,
            f"concern content {len(flag['content'])} exceeds {budget}",
        )

    def test_multiple_discoveries_contradicting_same_assumption_emit_once(self):
        """N discoveries against one assumption → one concern, not N.

        Models the legacy-project pattern where 27 teammate agents each
        emitted a contradiction concern against assumption 210fe2885dec.
        Dedup must key on references, not content (which varies per
        discovery snippet).
        """
        a = make_event(EVENT_TYPE_ASSUMPTION, content="namespace shape will reconcile")
        d1 = make_event(
            EVENT_TYPE_DISCOVERY,
            content="packages/shared re-exports flat",
            references=[a["id"]],
            metadata=refutes_metadata(a),
        )
        d2 = make_event(
            EVENT_TYPE_DISCOVERY,
            content="createFieldCrypto exported at top",
            references=[a["id"]],
            metadata=refutes_metadata(a),
        )
        d3 = make_event(
            EVENT_TYPE_DISCOVERY,
            content="encryption barrel has the type",
            references=[a["id"]],
            metadata=refutes_metadata(a),
        )
        found = concerns.detect_conflicts([a, d1, d2, d3], "main")
        contradicts = [c for c in found if "contradict" in c["content"].lower()]
        self.assertEqual(
            len(contradicts),
            1,
            f"expected 1 contradiction concern (dedup by refs), got {len(contradicts)}",
        )
        self.assertEqual(contradicts[0].get("references"), [a["id"]])

    def test_resolved_assumption_contradiction_not_reraised(self):
        """A resolved contradiction stops re-firing — the events are immutable,
        so re-raising (and escalating) every scan is pure noise. Mirrors the
        superseded-decision `already_accepted_topics` suppression: a prior
        RESOLVED concern referencing the assumption marks it acknowledged."""
        a = make_event(EVENT_TYPE_ASSUMPTION, content="alias_run splits cleanly")
        prior = make_event(
            EVENT_TYPE_CONCERN,
            content="Assumption contradicted: 'alias_run...' — by discovery.",
            references=[a["id"]],
        )
        resolver = make_event(
            EVENT_TYPE_STATUS,
            content="Triage: dropped — superseded by the discovery",
            working_on=[],
            metadata={METADATA_KEY_RESOLVES: [prior["id"]]},
        )
        d = make_event(
            EVENT_TYPE_DISCOVERY,
            content="Supersedes the assumption: never shipped",
            references=[a["id"]],
            metadata=refutes_metadata(a),
        )
        found = concerns.detect_conflicts([a, prior, resolver, d], "main")
        contradicts = [c for c in found if "contradict" in c["content"].lower()]
        self.assertEqual(
            len(contradicts),
            0,
            f"resolved contradiction must not re-raise, got {len(contradicts)}",
        )

    def test_resolved_multi_ref_contradiction_not_reraised(self):
        """A resolved contradiction whose concern references the assumption
        ALONGSIDE other ids still marks the assumption acknowledged.

        Guards the flat resolved-ref-id set: a whole-set tuple keyed on
        (assumption, extra) would never match the single-assumption probe,
        re-firing the exact noise this suppression removes."""
        a = make_event(EVENT_TYPE_ASSUMPTION, content="alias_run splits cleanly")
        other = make_event(EVENT_TYPE_DISCOVERY, content="unrelated context")
        prior = make_event(
            EVENT_TYPE_CONCERN,
            content="Assumption contradicted: 'alias_run...' — by discovery.",
            references=[a["id"], other["id"]],
        )
        resolver = make_event(
            EVENT_TYPE_STATUS,
            content="Triage: dropped — superseded by the discovery",
            working_on=[],
            metadata={METADATA_KEY_RESOLVES: [prior["id"]]},
        )
        d = make_event(
            EVENT_TYPE_DISCOVERY,
            content="Supersedes the assumption: never shipped",
            references=[a["id"]],
            metadata=refutes_metadata(a),
        )
        found = concerns.detect_conflicts([a, other, prior, resolver, d], "main")
        contradicts = [c for c in found if "contradict" in c["content"].lower()]
        self.assertEqual(
            len(contradicts),
            0,
            "multi-ref resolved contradiction must mark the assumption "
            f"acknowledged, got {len(contradicts)}",
        )

    def test_empty_string_in_resolves_does_not_blanket_suppress(self):
        """A discovery with metadata.resolves=[''] must NOT suppress the
        contradiction — empty-string startswith-matches everything, which
        would silently mute a real conflict."""
        a = make_event(EVENT_TYPE_ASSUMPTION, content="API is REST")
        d = make_event(
            EVENT_TYPE_DISCOVERY,
            content="Actually GraphQL",
            references=[a["id"]],
            metadata={METADATA_KEY_RESOLVES: [""], **refutes_metadata(a)},
        )
        found = concerns.detect_conflicts([a, d], "main")
        contradicts = [c for c in found if "contradict" in c["content"].lower()]
        self.assertEqual(len(contradicts), 1)

    def test_supersedes_metadata_on_discovery_skips_contradiction(self):
        """A discovery that structurally declares metadata.supersedes of the
        assumption never raises the contradiction — supersession is the
        intended forward mechanism, not an unresolved conflict.

        Declares the refutation TOO, so supersession is the only thing that can
        explain the silence. Without it the case passes on the trigger alone and
        the suppression it names goes unexercised.
        """
        a = make_event(EVENT_TYPE_ASSUMPTION, content="API is REST")
        d = make_event(
            EVENT_TYPE_DISCOVERY,
            content="Actually GraphQL — supersedes the REST assumption",
            references=[a["id"]],
            metadata={METADATA_KEY_SUPERSEDES: [a["id"]], **refutes_metadata(a)},
        )
        found = concerns.detect_conflicts([a, d], "main")
        contradicts = [c for c in found if "contradict" in c["content"].lower()]
        self.assertEqual(len(contradicts), 0)

    def test_resolves_metadata_on_discovery_skips_contradiction(self):
        """Symmetric with supersedes: metadata.resolves on the discovery is a
        STRONG link that cascade-closes the assumption, so re-flagging it as an
        open contradiction would contradict the link hierarchy."""
        a = make_event(EVENT_TYPE_ASSUMPTION, content="API is REST")
        d = make_event(
            EVENT_TYPE_DISCOVERY,
            content="Actually GraphQL",
            references=[a["id"]],
            metadata={METADATA_KEY_RESOLVES: [a["id"]], **refutes_metadata(a)},
        )
        found = concerns.detect_conflicts([a, d], "main")
        contradicts = [c for c in found if "contradict" in c["content"].lower()]
        self.assertEqual(len(contradicts), 0)

    def test_no_duplicate_assumption_contradicted(self):
        """Should not re-generate concern if one already exists for same conflict."""
        a = make_event(EVENT_TYPE_ASSUMPTION, content="API is REST")
        d = make_event(
            EVENT_TYPE_DISCOVERY,
            content="Actually GraphQL",
            references=[a["id"]],
            metadata=refutes_metadata(a),
        )
        existing_concern = make_event(
            EVENT_TYPE_CONCERN,
            content="Assumption contradicted: 'API is REST' "
            "contradicted by discovery 'Actually GraphQL'.",
        )
        events = [a, d, existing_concern]
        found = concerns.detect_conflicts(events, "main")
        contradiction_concerns = [
            c for c in found if "contradict" in c["content"].lower()
        ]
        self.assertEqual(len(contradiction_concerns), 0)


class TestReferenceIsNotRefutation(_HookTestCase):
    """A reference is a link; only a DECLARED refutation is a contradiction.

    `references` is mandatory and non-empty on every discovery
    (event_schema.validate_event), so it cannot carry the claim "this refutes
    that" — a field every discovery must fill says nothing about any one of
    them. Reading it as a refutation filed three high-severity false concerns in
    this project's own log, in two distinct modes, both reproduced below from
    the measured shapes.

    All three shapes go through the SAME `detect_conflicts` call so the trigger
    itself is what is under test. A declared-refutation case ALONE would pass
    identically with the old bare-reference trigger left in place.
    """

    def _contradictions(self, events: list[dict]) -> list[dict]:
        found = concerns.detect_conflicts(events, "main")
        return [c for c in found if "contradict" in c["content"].lower()]

    def test_a_confirming_discovery_raises_nothing(self):
        """Mode (a), measured: an assumption that a headless run writes a
        rollout log, "contradicted" by a discovery proving that it DOES.

        The discovery references the assumption because the schema requires it
        to reference something and this is what it is about. Confirmation and
        refutation are indistinguishable at the reference — which is why the
        signal has to be declared, and why sentiment in the content text is not
        an option (it would not survive another project's prose).
        """
        a = make_event(
            EVENT_TYPE_ASSUMPTION,
            content="a headless exec run writes a rollout session log, so "
            "effective model/effort is readable per run",
        )
        d = make_event(
            EVENT_TYPE_DISCOVERY,
            content="a HEADLESS exec DOES write a rollout log, and it records "
            "the EFFECTIVE model and effort. Verified on this session's runs.",
            references=[a["id"]],
        )
        self.assertEqual(self._contradictions([a, d]), [])

    def test_an_unrelated_discovery_raises_nothing(self):
        """Mode (b), measured twice: assumption and discovery on entirely
        different subjects, linked only because the discovery arose while the
        assumption was open."""
        a = make_event(
            EVENT_TYPE_ASSUMPTION,
            content="the top tier stays entitled to this account for the sprint",
        )
        d = make_event(
            EVENT_TYPE_DISCOVERY,
            content="that tier did NOT delegate in the run: no spawn tool call "
            "appears in its rollout",
            references=[a["id"]],
        )
        self.assertEqual(self._contradictions([a, d]), [])

    def test_a_declared_refutation_still_raises(self):
        """The fail-closed direction, preserved. Narrowing the trigger must not
        delete the detector: a discovery that DECLARES it refutes the assumption
        is still flagged, at high severity, referencing the assumption."""
        a = make_event(EVENT_TYPE_ASSUMPTION, content="API is REST")
        d = make_event(
            EVENT_TYPE_DISCOVERY,
            content="Actually GraphQL",
            references=[a["id"]],
            metadata=refutes_metadata(a),
        )
        found = self._contradictions([a, d])
        self.assertEqual(len(found), 1, found)
        self.assertEqual(found[0]["severity"], "high")
        self.assertEqual(found[0].get("references"), [a["id"]])

    def test_a_declared_refutation_is_prefix_tolerant(self):
        """The short-id convention, in both directions — the same rule declared
        supersession already honors, which is why the matcher is shared rather
        than written twice."""
        a = make_event(EVENT_TYPE_ASSUMPTION, content="API is REST")
        short = make_event(
            EVENT_TYPE_DISCOVERY,
            content="Actually GraphQL",
            references=[a["id"]],
            metadata={METADATA_KEY_REFUTES: [a["id"][:6]]},
        )
        self.assertEqual(len(self._contradictions([a, short])), 1)

        longer = make_event(
            EVENT_TYPE_DISCOVERY,
            content="Actually GraphQL",
            references=[a["id"]],
            metadata={METADATA_KEY_REFUTES: [a["id"] + "extra"]},
        )
        self.assertEqual(len(self._contradictions([a, longer])), 1)

    def test_empty_string_in_refutes_does_not_blanket_match(self):
        """`refutes: ['']` must refute NOTHING. Empty-string startswith-matches
        every id, so a stray entry would flag every open assumption at once —
        the inverse of the bug being fixed, and just as loud."""
        a1 = make_event(EVENT_TYPE_ASSUMPTION, content="API is REST")
        a2 = make_event(EVENT_TYPE_ASSUMPTION, content="storage is Postgres")
        d = make_event(
            EVENT_TYPE_DISCOVERY,
            content="Actually GraphQL",
            references=[a1["id"]],
            metadata={METADATA_KEY_REFUTES: [""]},
        )
        self.assertEqual(self._contradictions([a1, a2, d]), [])

    def test_a_bare_string_refutes_flags_nothing_at_all(self):
        """`refutes: "<id>"` — the brackets dropped — must declare NOTHING.

        Only `metadata.resolves` is type-checked at write time, so this shape
        reaches the matcher. Iterated, a string yields single CHARACTERS, each
        truthy and each a one-char prefix that startswith-matches roughly one id
        in sixteen: the detector flagged the intended assumption AND an
        unrelated one, at high severity — the very false positive narrowing the
        trigger to a declaration was meant to end.

        The unrelated assumption's id is pinned to share `a1`'s first character
        so the character-iteration bug is REACHED here; without that, a passing
        assertion would prove only that the ids happened not to collide.
        """
        a1 = make_event(EVENT_TYPE_ASSUMPTION, content="API is REST")
        a2 = make_event(EVENT_TYPE_ASSUMPTION, content="storage is Postgres")
        a2["id"] = a1["id"][0] + a2["id"][1:]
        self.assertNotEqual(a1["id"], a2["id"])
        d = make_event(
            EVENT_TYPE_DISCOVERY,
            content="Actually GraphQL",
            references=[a1["id"]],
            metadata={METADATA_KEY_REFUTES: a1["id"]},
        )
        self.assertEqual(self._contradictions([a1, a2, d]), [])

    def test_a_non_list_refutes_flags_nothing(self):
        """Same rule, the other shapes JSON permits. A dict iterates its KEYS,
        which lands in the same place; a number is not iterable at all and must
        not raise on a hook path that has to degrade, never crash."""
        a1 = make_event(EVENT_TYPE_ASSUMPTION, content="API is REST")
        for declared in ({a1["id"]: True}, 7, None):
            with self.subTest(declared=declared):
                d = make_event(
                    EVENT_TYPE_DISCOVERY,
                    content="Actually GraphQL",
                    references=[a1["id"]],
                    metadata={METADATA_KEY_REFUTES: declared},
                )
                self.assertEqual(self._contradictions([a1, d]), [])

    def test_a_non_string_entry_beside_a_real_id_is_ignored_not_fatal(self):
        """A well-formed list with one junk entry still refutes what it names.
        Dropping the entry beats raising on a hook that must degrade."""
        a1 = make_event(EVENT_TYPE_ASSUMPTION, content="API is REST")
        d = make_event(
            EVENT_TYPE_DISCOVERY,
            content="Actually GraphQL",
            references=[a1["id"]],
            metadata={METADATA_KEY_REFUTES: [None, 12, a1["id"]]},
        )
        self.assertEqual(len(self._contradictions([a1, d])), 1)

    def test_refuting_an_id_that_is_not_an_assumption_raises_nothing(self):
        """A declaration is not self-certifying: the target must actually be an
        assumption in the log. A discovery refuting a decision id is somebody
        else's pattern, not this one's."""
        other = make_event(EVENT_TYPE_CONCERN, content="unrelated concern")
        d = make_event(
            EVENT_TYPE_DISCOVERY,
            content="Actually GraphQL",
            references=[other["id"]],
            metadata={METADATA_KEY_REFUTES: [other["id"]]},
        )
        self.assertEqual(self._contradictions([other, d]), [])


if __name__ == "__main__":
    unittest.main()
