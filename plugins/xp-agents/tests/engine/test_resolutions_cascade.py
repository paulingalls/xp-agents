#!/usr/bin/env python3
"""Tests for cascade resolution (reference-driven closure).

Split from test_resolutions.py — covers TestCascadeResolution,
TestCascadeFixedPointCharacterization.
"""

import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))
import resolution
from conftest import make_event
from event_schema import (
    EVENT_TYPE_ANSWER,
    EVENT_TYPE_CONCERN,
    EVENT_TYPE_DEBT,
    EVENT_TYPE_DECISION,
    EVENT_TYPE_GOAL,
    EVENT_TYPE_QUESTION,
    EVENT_TYPE_STATUS,
)


class TestCascadeResolution(unittest.TestCase):
    """Cascade pass: events whose top-level `references` list points at a
    resolved id are themselves cascade-closed. WEAK link — complements
    metadata.resolves (STRONG).
    """

    def test_concern_cascade_closes_when_referenced_question_answered(self):
        q = make_event(EVENT_TYPE_QUESTION, content="Which DB?")
        flag = make_event(
            EVENT_TYPE_CONCERN,
            content="Stale question: blocking question unanswered",
            references=[q["id"]],
        )
        answer = make_event(EVENT_TYPE_ANSWER, content="Postgres", references=[q["id"]])
        result = resolution.compute_resolutions([q, flag, answer])
        self.assertIn(flag["id"], result["resolved_concern_ids"])
        self.assertEqual(result["concern_resolutions"][flag["id"]], answer)

    def test_concern_cascade_closes_when_referenced_decision_resolved(self):
        decision = make_event(EVENT_TYPE_DECISION, content="Use JWT", topic="auth")
        flag = make_event(
            EVENT_TYPE_CONCERN,
            content="Superseded decision on auth",
            references=[decision["id"]],
        )
        resolver = make_event(
            EVENT_TYPE_STATUS,
            content="Decision explicitly retired",
            working_on=[],
            metadata={"resolves": [decision["id"]]},
        )
        result = resolution.compute_resolutions([decision, flag, resolver])
        self.assertIn(flag["id"], result["resolved_concern_ids"])

    def test_no_cascade_when_target_unresolved(self):
        flag = make_event(
            EVENT_TYPE_CONCERN,
            content="References an event that never resolves",
            references=["deadbeef0000"],
        )
        result = resolution.compute_resolutions([flag])
        self.assertNotIn(flag["id"], result["resolved_concern_ids"])

    def test_cascade_handles_multiple_references_or_semantics(self):
        a = make_event(EVENT_TYPE_QUESTION, content="A?")
        b = make_event(EVENT_TYPE_QUESTION, content="B?")
        flag = make_event(
            EVENT_TYPE_CONCERN,
            content="Flag referencing A and B",
            references=[a["id"], b["id"]],
        )
        # Only A resolves; flag still closes (ANY referenced id resolving is enough).
        answer_a = make_event(
            EVENT_TYPE_ANSWER, content="A answered", references=[a["id"]]
        )
        result = resolution.compute_resolutions([a, b, flag, answer_a])
        self.assertIn(flag["id"], result["resolved_concern_ids"])

    def test_cascade_extends_to_multi_level(self):
        """A two-level flag chain (B → A → resolved root) closes BOTH levels.

        The cascade iterates to a fixed point: A closes referencing the
        resolved question, is fed back into the resolver set, then B closes
        referencing the now-resolved A on the next pass.
        """
        q = make_event(EVENT_TYPE_QUESTION, content="root")
        c_inner = make_event(EVENT_TYPE_CONCERN, content="inner", references=[q["id"]])
        c_outer = make_event(
            EVENT_TYPE_CONCERN, content="outer", references=[c_inner["id"]]
        )
        answer = make_event(EVENT_TYPE_ANSWER, content="answered", references=[q["id"]])
        result = resolution.compute_resolutions([q, c_inner, c_outer, answer])
        # Inner cascades closed (references a resolved question).
        self.assertIn(c_inner["id"], result["resolved_concern_ids"])
        # Outer ALSO cascades closed — the fixed-point loop extends multi-level.
        self.assertIn(c_outer["id"], result["resolved_concern_ids"])

    def test_cascade_two_level_flag_chain_concern_root(self):
        """E2E flag-cascade shape: a root concern resolved via metadata.resolves,
        flag A referencing the root, flag B referencing flag A. Both flags close.

        Mirrors the production shape (retro/reviewer flags wire
        references=[root_id]); the integration E2E pins the single-level case,
        this pins the two-level extension at the engine boundary.
        """
        root = make_event(EVENT_TYPE_CONCERN, content="root concern: stop hook broken")
        resolver = make_event(
            EVENT_TYPE_STATUS,
            content="resolved: stop hook fixed",
            working_on=["hook.py"],
            metadata={"resolves": [root["id"]]},
        )
        flag_a = make_event(
            EVENT_TYPE_CONCERN, content="flag A", references=[root["id"]]
        )
        flag_b = make_event(
            EVENT_TYPE_CONCERN, content="flag B", references=[flag_a["id"]]
        )
        result = resolution.compute_resolutions([root, resolver, flag_a, flag_b])
        resolved = result["resolved_concern_ids"]
        self.assertIn(root["id"], resolved)
        self.assertIn(flag_a["id"], resolved)
        self.assertIn(flag_b["id"], resolved)

    def test_cascade_extends_to_three_levels(self):
        """Three-level chain (C → B → A → resolved root) closes every level."""
        q = make_event(EVENT_TYPE_QUESTION, content="root")
        a = make_event(EVENT_TYPE_CONCERN, content="A", references=[q["id"]])
        b = make_event(EVENT_TYPE_CONCERN, content="B", references=[a["id"]])
        c = make_event(EVENT_TYPE_CONCERN, content="C", references=[b["id"]])
        answer = make_event(EVENT_TYPE_ANSWER, content="answered", references=[q["id"]])
        result = resolution.compute_resolutions([q, a, b, c, answer])
        self.assertIn(a["id"], result["resolved_concern_ids"])
        self.assertIn(b["id"], result["resolved_concern_ids"])
        self.assertIn(c["id"], result["resolved_concern_ids"])

    def test_cascade_cycle_terminates_and_leaves_unresolved(self):
        """A reference cycle (B → A → B) with no path to a resolved root
        terminates without hanging and leaves both events unresolved."""
        a = make_event(EVENT_TYPE_CONCERN, content="A")
        b = make_event(EVENT_TYPE_CONCERN, content="B")
        a["references"] = [b["id"]]
        b["references"] = [a["id"]]
        result = resolution.compute_resolutions([a, b])
        self.assertNotIn(a["id"], result["resolved_concern_ids"])
        self.assertNotIn(b["id"], result["resolved_concern_ids"])

    def test_cascade_does_not_relay_through_enrichment_status(self):
        """KNOWN RISK pin (SMM assumption d0eac70ea560).

        `post_tool_use.py` attaches `references` to status events as semantic
        enrichment (status → related decision). When that decision is resolved,
        the status event itself cascade-closes — but it lands in
        `other_resolutions` and is NOT fed back as a relay. So a substantive
        concern that merely references such an enrichment-resolved status event
        does NOT cascade-close. This preserves single-level behavior as the
        floor: multi-level closure propagates only through genuine flag/tracked
        chains (concern/goal/debt/decision/assumption/question), never through
        ephemeral status hops. Deliberate, tested decision — not an accident.
        """
        decision = make_event(EVENT_TYPE_DECISION, content="Use JWT", topic="auth")
        # Enrichment status: references the decision (mirrors post_tool_use refs).
        status = make_event(
            EVENT_TYPE_STATUS,
            content="Edited auth module",
            working_on=["auth.py"],
            references=[decision["id"]],
        )
        # The decision is explicitly resolved.
        decision_resolver = make_event(
            EVENT_TYPE_STATUS,
            content="Decision retired",
            working_on=[],
            metadata={"resolves": [decision["id"]]},
        )
        # A substantive concern that contextually references the status event.
        concern = make_event(
            EVENT_TYPE_CONCERN,
            content="Substantive concern referencing a status event",
            references=[status["id"]],
        )
        result = resolution.compute_resolutions(
            [decision, status, decision_resolver, concern]
        )
        # The enrichment status itself still cascade-resolves (single-level,
        # unchanged behavior) — it lands in the "other" bucket.
        self.assertIn(status["id"], result["resolved_other_ids"])
        # But the substantive concern does NOT close — no relay through status.
        self.assertNotIn(concern["id"], result["resolved_concern_ids"])

    def test_cascade_self_reference_is_no_op(self):
        flag = make_event(EVENT_TYPE_CONCERN, content="self-ref")
        flag["references"] = [flag["id"]]
        result = resolution.compute_resolutions([flag])
        self.assertNotIn(flag["id"], result["resolved_concern_ids"])

    def test_question_two_hops_from_resolved_root_stays_open(self):
        """A question never cascade-closes, even via a multi-hop reference chain.

        A question whose `references` transitively reach a resolved root (here:
        question → concern → resolved root question) must stay OPEN — it clears
        ONLY via an answer event, metadata.resolves, or AskUserQuestion (the
        blocking-question gate). Auto-closing it via cascade would fabricate a
        customer decision, drop it from the open-questions nudge, and inflate
        retro questions_answered.
        """
        root = make_event(EVENT_TYPE_QUESTION, content="root question")
        answer = make_event(
            EVENT_TYPE_ANSWER, content="answered", references=[root["id"]]
        )
        # A concern one hop from the resolved root (legitimately cascades closed).
        bridge = make_event(
            EVENT_TYPE_CONCERN, content="bridge concern", references=[root["id"]]
        )
        # A genuinely-open question two hops out, pointing at the bridge concern.
        open_q = make_event(
            EVENT_TYPE_QUESTION,
            content="still-open question",
            references=[bridge["id"]],
        )
        result = resolution.compute_resolutions([root, answer, bridge, open_q])
        # Root is answered; bridge concern cascades closed.
        self.assertIn(root["id"], result["answered_question_ids"])
        self.assertIn(bridge["id"], result["resolved_concern_ids"])
        # The second-hop question stays OPEN — questions never cascade-close.
        self.assertNotIn(open_q["id"], result["answered_question_ids"])
        self.assertNotIn(open_q["id"], result["question_answers"])

    def test_question_one_hop_from_resolved_root_stays_open(self):
        """Even a single-hop question does not cascade-close — only the
        main-pass paths (answer / metadata.resolves) clear a question."""
        root = make_event(EVENT_TYPE_DECISION, content="settled", topic="x")
        resolver = make_event(
            EVENT_TYPE_STATUS,
            content="retired",
            working_on=[],
            metadata={"resolves": [root["id"]]},
        )
        q = make_event(
            EVENT_TYPE_QUESTION, content="dependent question", references=[root["id"]]
        )
        result = resolution.compute_resolutions([root, resolver, q])
        self.assertIn(root["id"], result["resolved_decision_ids"])
        self.assertNotIn(q["id"], result["answered_question_ids"])

    def test_cascade_respects_event_type_buckets(self):
        """A goal with references to a resolved event lands in goal_resolutions."""
        q = make_event(EVENT_TYPE_QUESTION, content="root")
        g = make_event(EVENT_TYPE_GOAL, content="dependent goal", references=[q["id"]])
        answer = make_event(EVENT_TYPE_ANSWER, content="resolved", references=[q["id"]])
        result = resolution.compute_resolutions([q, g, answer])
        self.assertIn(g["id"], result["resolved_goal_ids"])
        self.assertNotIn(g["id"], result["resolved_concern_ids"])


class TestCascadeFixedPointCharacterization(unittest.TestCase):
    """Characterization tests for the cascade fixed-point loop.

    These pin observable behavior of `compute_resolutions` so the loop's
    internals can be reshaped (e.g. iterating a pre-filtered candidate list
    instead of re-scanning every event each pass) without drift. They pass
    both before and after any behavior-preserving change — a test here that
    only goes green *after* a change is evidence of a behavior change.
    """

    @staticmethod
    def _resolved_id_sets(result: dict) -> dict[str, set[str]]:
        """Every `*_ids` set — the membership-level view of a resolution."""
        return {k: v for k, v in result.items() if k.endswith("_ids")}

    def test_shuffled_event_order_yields_same_resolved_ids(self):
        """Cascade membership is invariant under permutation of the cascade tail.

        Only the *cascade* is order-invariant. The main pass builds `by_id`
        incrementally, so a resolver (or an `answer`) that precedes its target
        does not resolve it. The strong-resolution prefix (root question, its
        answer) is therefore held fixed and only the reference-driven tail is
        permuted. Membership, not resolver identity: for non-question buckets
        the main pass assigns rather than setdefaults, so with two events naming
        the same target the later one in list order wins.
        """
        q = make_event(EVENT_TYPE_QUESTION, content="root")
        answer = make_event(EVENT_TYPE_ANSWER, content="answered", references=[q["id"]])
        c1 = make_event(EVENT_TYPE_CONCERN, content="level 1", references=[q["id"]])
        c2 = make_event(EVENT_TYPE_CONCERN, content="level 2", references=[c1["id"]])
        c3 = make_event(EVENT_TYPE_CONCERN, content="level 3", references=[c2["id"]])
        # Enrichment status: cascade-closes into `other`, never relays.
        enrich = make_event(
            EVENT_TYPE_STATUS,
            content="enrichment status",
            working_on=["app.py"],
            references=[q["id"]],
        )
        # A question downstream of a closed concern — must stay open.
        open_q = make_event(
            EVENT_TYPE_QUESTION, content="still open", references=[c1["id"]]
        )
        cyc_a = make_event(EVENT_TYPE_CONCERN, content="cycle A")
        cyc_b = make_event(EVENT_TYPE_CONCERN, content="cycle B")
        cyc_a["references"] = [cyc_b["id"]]
        cyc_b["references"] = [cyc_a["id"]]

        prefix = [q, answer]
        tail = [c1, c2, c3, enrich, open_q, cyc_a, cyc_b]

        baseline = self._resolved_id_sets(resolution.compute_resolutions(prefix + tail))
        # Spot-check the baseline is the shape we think it is.
        self.assertEqual(baseline["answered_question_ids"], {q["id"]})
        self.assertEqual(
            baseline["resolved_concern_ids"], {c1["id"], c2["id"], c3["id"]}
        )
        self.assertIn(enrich["id"], baseline["resolved_other_ids"])
        self.assertNotIn(open_q["id"], baseline["answered_question_ids"])

        rng = random.Random(0)
        for i in range(8):
            permuted = prefix + rng.sample(tail, len(tail))
            with self.subTest(permutation=i):
                self.assertEqual(
                    self._resolved_id_sets(resolution.compute_resolutions(permuted)),
                    baseline,
                )

    def test_deep_chain_of_many_levels_fully_resolves(self):
        """A 50-level chain listed outermost-first — the worst case for the
        pass loop (one level closes per pass). Every level closes, and the
        resolver relayed outward is the innermost root's resolver."""
        depth = 50
        q = make_event(EVENT_TYPE_QUESTION, content="root")
        answer = make_event(EVENT_TYPE_ANSWER, content="answered", references=[q["id"]])
        chain: list[dict] = []
        prev_id = q["id"]
        for level in range(depth):
            link = make_event(
                EVENT_TYPE_CONCERN, content=f"level {level}", references=[prev_id]
            )
            chain.append(link)
            prev_id = link["id"]

        # Outermost first: the innermost link is visited last on every pass.
        events = [q, answer, *reversed(chain)]
        result = resolution.compute_resolutions(events)

        for level, link in enumerate(chain):
            with self.subTest(level=level):
                self.assertIn(link["id"], result["resolved_concern_ids"])
                # The root's resolver propagates unchanged along the chain.
                self.assertEqual(result["concern_resolutions"][link["id"]], answer)

    def test_large_log_with_sparse_references_resolves(self):
        """Several hundred events, a handful carrying `references`. The filler
        events carry no refs and must not affect the outcome."""
        q = make_event(EVENT_TYPE_QUESTION, content="root")
        answer = make_event(EVENT_TYPE_ANSWER, content="answered", references=[q["id"]])
        filler = [
            make_event(EVENT_TYPE_STATUS, content=f"filler {i}", working_on=["app.py"])
            for i in range(300)
        ]
        c1 = make_event(EVENT_TYPE_CONCERN, content="near", references=[q["id"]])
        c2 = make_event(EVENT_TYPE_CONCERN, content="far", references=[c1["id"]])
        d1 = make_event(
            EVENT_TYPE_DEBT, content="debt", files=["x.py"], references=[c2["id"]]
        )

        result = resolution.compute_resolutions([q, answer, *filler, c1, c2, d1])

        self.assertEqual(result["answered_question_ids"], {q["id"]})
        self.assertEqual(result["resolved_concern_ids"], {c1["id"], c2["id"]})
        self.assertEqual(result["resolved_debt_ids"], {d1["id"]})
        # No filler event acquired a resolution.
        for event in filler:
            self.assertNotIn(event["id"], result["resolved_other_ids"])

    def test_other_bucket_closure_does_not_relay_across_passes(self):
        """The `other` non-relay floor holds when the `other` event closes on a
        LATER pass than the chain root.

        List order is chosen so `enrich` cannot close until pass 2 (its
        referenced concern only closes at the tail of pass 1). Once closed it
        sits in `other_resolutions` but never in `resolver_map`, so the concern
        pointing at it stays open. Complements the single-pass pin in
        test_cascade_does_not_relay_through_enrichment_status.
        """
        q = make_event(EVENT_TYPE_QUESTION, content="root")
        answer = make_event(EVENT_TYPE_ANSWER, content="answered", references=[q["id"]])
        inner = make_event(EVENT_TYPE_CONCERN, content="inner", references=[q["id"]])
        enrich = make_event(
            EVENT_TYPE_STATUS,
            content="enrichment status",
            working_on=["app.py"],
            references=[inner["id"]],
        )
        downstream = make_event(
            EVENT_TYPE_CONCERN, content="downstream", references=[enrich["id"]]
        )

        # enrich/downstream precede the events they depend on: pass 1 closes
        # only `inner` (visited last); pass 2 closes `enrich` into `other`.
        result = resolution.compute_resolutions([enrich, downstream, q, answer, inner])

        self.assertIn(inner["id"], result["resolved_concern_ids"])
        self.assertIn(enrich["id"], result["resolved_other_ids"])
        # No relay through the `other` bucket, even across passes.
        self.assertNotIn(downstream["id"], result["resolved_concern_ids"])

    def test_cycle_with_unresolved_and_resolved_branches_terminates(self):
        """A pure A→B→A cycle alongside a resolvable branch: the branch closes,
        the cycle stays open, and the call terminates."""
        cyc_a = make_event(EVENT_TYPE_CONCERN, content="cycle A")
        cyc_b = make_event(EVENT_TYPE_CONCERN, content="cycle B")
        cyc_a["references"] = [cyc_b["id"]]
        cyc_b["references"] = [cyc_a["id"]]

        q = make_event(EVENT_TYPE_QUESTION, content="root")
        answer = make_event(EVENT_TYPE_ANSWER, content="answered", references=[q["id"]])
        branch = make_event(EVENT_TYPE_CONCERN, content="branch", references=[q["id"]])

        result = resolution.compute_resolutions([q, answer, cyc_a, cyc_b, branch])

        self.assertEqual(result["resolved_concern_ids"], {branch["id"]})
        self.assertNotIn(cyc_a["id"], result["resolved_concern_ids"])
        self.assertNotIn(cyc_b["id"], result["resolved_concern_ids"])


if __name__ == "__main__":
    unittest.main()
