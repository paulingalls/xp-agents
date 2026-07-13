#!/usr/bin/env python3
"""Tests for curation data preparation and retro history extraction.

Helper function tests (bulk append, atomic writes) in test_append_helpers.py.
"""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))
import materialize
import smm_cli
import smm_store
from conftest import _SMMTestCase, make_event, write_smm_fixture
from event_schema import (
    EVENT_TYPE_CONCERN,
    EVENT_TYPE_CONVENTION,
    EVENT_TYPE_CUSTOMER_INPUT,
    EVENT_TYPE_DECISION,
    EVENT_TYPE_GOAL,
    EVENT_TYPE_RETROSPECTIVE,
    EVENT_TYPE_SESSION_STARTED,
    EVENT_TYPE_STATUS,
)


class TestPrepareCurationData(_SMMTestCase):
    """Tests for prepare_curation_data()."""

    # -- Step 2: Fresh project --

    def test_fresh_project_empty(self):
        """Empty events.jsonl returns valid structure with empty fields."""
        result = materialize.prepare_curation_data(self.smm_dir)
        for key in (
            "current_smm",
            "new_since_last_curation",
            "retro_history",
            "aging",
            "health",
            "recent_summaries",
        ):
            self.assertIn(key, result)
        for pillar in ("intent", "constraints", "risks", "wisdom"):
            self.assertEqual(result["current_smm"][pillar], [])
        for key in ("intent_count", "constraints_count", "risks_count", "wisdom_count"):
            self.assertEqual(result["health"][key], 0)
        self.assertEqual(result["recent_summaries"], [])

    def test_recent_summaries_populated_from_session_history(self):
        """When session_history.json exists, prepare_curation_data surfaces
        the last 1-2 entries with pre-computed staleness so the housekeeper
        can ground pillar curation in recent narrative."""
        import session_history

        session_history.save_history(
            self.smm_dir,
            {
                "version": session_history.SCHEMA_VERSION,
                "entries": [
                    {
                        "ts": "2026-05-09T10:00:00+00:00",
                        "summary": "Earlier session.",
                        "carry_forward": [],
                    },
                    {
                        "ts": "2026-05-10T10:00:00+00:00",
                        "summary": "Most recent session.",
                        "carry_forward": [],
                    },
                ],
            },
        )
        result = materialize.prepare_curation_data(self.smm_dir)
        summaries = result["recent_summaries"]
        # Last 2 entries surface with staleness annotated on each.
        self.assertEqual(len(summaries), 2)
        contents = [e["summary"] for e in summaries]
        self.assertEqual(contents, ["Earlier session.", "Most recent session."])
        for entry in summaries:
            self.assertIn("staleness", entry)
            self.assertIn("status", entry["staleness"])

    def test_no_watermark_all_events_new(self):
        """Without watermark, all events appear in new_since_last_curation."""
        events = [
            make_event(EVENT_TYPE_CUSTOMER_INPUT, content="Build an API"),
            make_event(EVENT_TYPE_DECISION, topic="db", content="Use Postgres"),
            make_event(EVENT_TYPE_CONCERN, content="No tests yet"),
        ]
        self._write_events(events)
        result = materialize.prepare_curation_data(self.smm_dir)
        new = result["new_since_last_curation"]
        self.assertEqual(len(new["customer_inputs"]), 1)
        self.assertEqual(len(new["decisions"]), 1)
        self.assertEqual(len(new["concerns"]), 1)

    # -- Step 3: Mature project --

    def test_watermark_splits_old_new(self):
        """Events after watermark go to new_since; older events feed current_smm."""
        old_events = [
            make_event(EVENT_TYPE_GOAL, content="Ship v1"),
            make_event(EVENT_TYPE_DECISION, topic="auth", content="Use JWT"),
            make_event(EVENT_TYPE_CONVENTION, topic="api", content="REST only"),
        ]
        new_events = [
            make_event(EVENT_TYPE_CUSTOMER_INPUT, content="Add password reset"),
            make_event(EVENT_TYPE_CONCERN, content="Empty catch block"),
        ]
        self._write_events(old_events + new_events)
        materialize.write_curation_watermark(
            self.smm_dir, len(old_events), "xp-housekeeper"
        )
        result = materialize.prepare_curation_data(self.smm_dir)
        new = result["new_since_last_curation"]
        self.assertEqual(len(new["customer_inputs"]), 1)
        self.assertEqual(new["customer_inputs"][0]["content"], "Add password reset")
        self.assertEqual(len(new["concerns"]), 1)
        # Old decisions should NOT be in new
        self.assertEqual(len(new["decisions"]), 0)

    def test_current_smm_from_json_file(self):
        """current_smm is loaded verbatim from shared_mental_model.json."""
        write_smm_fixture(
            self.smm_dir,
            intent=[("Ship v1", "goal"), ("Add RBAC", "customer_intent")],
        )
        result = materialize.prepare_curation_data(self.smm_dir)
        intents = result["current_smm"]["intent"]
        self.assertEqual(len(intents), 2)
        contents = [e["content"] for e in intents]
        self.assertIn("Ship v1", contents)
        self.assertIn("Add RBAC", contents)

    def test_current_smm_constraints_from_file(self):
        """current_smm.constraints loaded verbatim from JSON."""
        write_smm_fixture(
            self.smm_dir,
            constraints=[
                ("Use Postgres", "decision"),
                ("Use bcrypt", "decision"),
                ("REST only", "convention"),
            ],
        )
        result = materialize.prepare_curation_data(self.smm_dir)
        constraints = result["current_smm"]["constraints"]
        self.assertEqual(len(constraints), 3)
        contents = [c["content"] for c in constraints]
        self.assertIn("Use Postgres", contents)
        self.assertIn("Use bcrypt", contents)
        self.assertIn("REST only", contents)

    def test_current_smm_risks_from_file(self):
        """current_smm.risks loaded verbatim from JSON."""
        write_smm_fixture(
            self.smm_dir,
            risks=[
                ("No tests", "concern", "problem"),
                ("Users prefer REST", "assumption", "uncertainty"),
                ("Legacy code", "debt", "debt"),
                ("Which DB?", "question", "uncertainty"),
            ],
        )
        result = materialize.prepare_curation_data(self.smm_dir)
        risks = result["current_smm"]["risks"]
        self.assertEqual(len(risks), 4)

    def test_resolutions_is_list_not_dict(self):
        """F1: resolutions should be a list of IDs, not a dict."""
        concern = make_event(EVENT_TYPE_CONCERN, content="Old bug")
        resolver = make_event(
            EVENT_TYPE_STATUS,
            content="Fixed",
            working_on=[],
            metadata={"resolves": [concern["id"]]},
        )
        self._write_events([concern, resolver])
        result = materialize.prepare_curation_data(self.smm_dir)
        resolutions = result["new_since_last_curation"]["resolutions"]
        self.assertIsInstance(resolutions, list)
        self.assertIn(concern["id"], resolutions)

    def test_empty_new_since_resolutions_is_list(self):
        """F1: _empty_new_since returns resolutions as [] not {}."""
        result = materialize._empty_new_since()
        self.assertIsInstance(result["resolutions"], list)
        self.assertEqual(result["resolutions"], [])

    def test_resolutions_surfaced_in_new_since(self):
        """Resolutions appear in new_since_last_curation for housekeeper to act on.

        The deterministic filtering that previously lived in prepare_curation_data
        moves to the housekeeper LLM — we assert the data it needs is available.
        """
        concern = make_event(EVENT_TYPE_CONCERN, content="Old bug")
        resolver = make_event(
            EVENT_TYPE_STATUS,
            content="Fixed",
            working_on=[],
            metadata={"resolves": [concern["id"]]},
        )
        self._write_events([concern, resolver])
        result = materialize.prepare_curation_data(self.smm_dir)
        self.assertIn(concern["id"], result["new_since_last_curation"]["resolutions"])

    def test_aging_keyed_on_entry_ts(self):
        """Aging uses entry.ts from the JSON file, not source event ts."""
        write_smm_fixture(
            self.smm_dir,
            risks=[("Old concern", "concern", "problem")],
        )
        # The fixture uses ts "2026-01-01T00:00:00+00:00" — add 4
        # session_started boundary anchors after it.
        sessions = [
            make_event(
                EVENT_TYPE_SESSION_STARTED,
                content=f"start {i}",
                ts=f"2026-03-{i + 1:02d}T00:00:00+00:00",
            )
            for i in range(4)
        ]
        self._write_events(sessions)
        result = materialize.prepare_curation_data(self.smm_dir)
        # The fixture generated a random UUID, so look up by content
        risk_id = next(
            r["id"]
            for r in result["current_smm"]["risks"]
            if r["content"] == "Old concern"
        )
        self.assertEqual(result["aging"][risk_id], 4)

    def test_resolutions_after_watermark(self):
        """Resolutions after watermark appear in new_since_last_curation."""
        concern = make_event(EVENT_TYPE_CONCERN, content="Bug")
        resolver = make_event(
            EVENT_TYPE_STATUS,
            content="Fixed",
            working_on=[],
            metadata={"resolves": [concern["id"]]},
        )
        self._write_events([concern, resolver])
        materialize.write_curation_watermark(self.smm_dir, 1, "xp-housekeeper")
        result = materialize.prepare_curation_data(self.smm_dir)
        self.assertIn(concern["id"], result["new_since_last_curation"]["resolutions"])

    def test_health_counts(self):
        """Health section counts items in each pillar of current_smm."""
        write_smm_fixture(
            self.smm_dir,
            intent=[
                ("G1", "goal"),
                ("G2", "goal"),
                ("I1", "customer_intent"),
            ],
            constraints=[
                ("Use PG", "decision"),
                ("REST", "convention"),
            ],
            risks=[
                ("C1", "concern", "problem"),
                ("A1", "assumption", "uncertainty"),
            ],
        )
        result = materialize.prepare_curation_data(self.smm_dir)
        self.assertEqual(result["health"]["intent_count"], 3)
        self.assertEqual(result["health"]["constraints_count"], 2)
        self.assertEqual(result["health"]["risks_count"], 2)

    # -- Step 4: retro_history + team --

    def test_resolved_concerns_excluded_from_new_since(self):
        """Resolved concerns should not appear in new_since_last_curation."""
        c1 = make_event(EVENT_TYPE_CONCERN, content="Lint error in foo.py")
        c2 = make_event(EVENT_TYPE_CONCERN, content="Real design concern")
        resolver = make_event(
            EVENT_TYPE_STATUS,
            content="Fixed",
            working_on=[],
            metadata={"resolves": [c1["id"]]},
        )
        self._write_events([c1, c2, resolver])
        result = materialize.prepare_curation_data(self.smm_dir)
        new = result["new_since_last_curation"]
        concern_ids = {c["id"] for c in new["concerns"]}
        self.assertNotIn(c1["id"], concern_ids)
        self.assertIn(c2["id"], concern_ids)

    def test_resolved_concern_count_in_new_since(self):
        """Resolved concerns should be counted in new_since_last_curation."""
        c1 = make_event(EVENT_TYPE_CONCERN, content="Lint error")
        c2 = make_event(EVENT_TYPE_CONCERN, content="Test failure")
        resolver = make_event(
            EVENT_TYPE_STATUS,
            content="Fixed both",
            working_on=[],
            metadata={"resolves": [c1["id"], c2["id"]]},
        )
        self._write_events([c1, c2, resolver])
        result = materialize.prepare_curation_data(self.smm_dir)
        self.assertEqual(result["new_since_last_curation"]["resolved_concern_count"], 2)

    def test_retro_history_latest_tries(self):
        """latest_tries from most recent retrospective."""
        r1 = make_event(
            EVENT_TYPE_RETROSPECTIVE,
            content="Retro 1",
            ts="2026-01-01T00:00:00+00:00",
            keep=[{"content": "Good tests"}],
            fix=[{"content": "Slow deploys"}],
        )
        r1["try"] = [{"content": "Split commits"}]
        r2 = make_event(
            EVENT_TYPE_RETROSPECTIVE,
            content="Retro 2",
            ts="2026-02-01T00:00:00+00:00",
            keep=[{"content": "TDD held"}],
            fix=[{"content": "Big commits"}],
        )
        r2["try"] = [{"content": "Add lint"}, {"content": "Grep before remove"}]
        self._write_events([r1, r2])
        result = materialize.prepare_curation_data(self.smm_dir)
        self.assertIn("Add lint", result["retro_history"]["latest_tries"])
        self.assertIn("Grep before remove", result["retro_history"]["latest_tries"])
        self.assertNotIn("Split commits", result["retro_history"]["latest_tries"])

    def test_retro_history_adopted_tries(self):
        """Tries from earlier retros not in any fix list are adopted."""
        r1 = make_event(
            EVENT_TYPE_RETROSPECTIVE,
            content="Retro 1",
            ts="2026-01-01T00:00:00+00:00",
            keep=[{"content": "ok"}],
            fix=[{"content": "Bad deploys"}],
        )
        r1["try"] = [{"content": "Use CI"}, {"content": "Split commits"}]
        r2 = make_event(
            EVENT_TYPE_RETROSPECTIVE,
            content="Retro 2",
            ts="2026-02-01T00:00:00+00:00",
            keep=[{"content": "ok"}],
            fix=[{"content": "Split commits"}],
        )  # "Split commits" appeared as fix
        r2["try"] = [{"content": "Add lint"}]
        self._write_events([r1, r2])
        result = materialize.prepare_curation_data(self.smm_dir)
        adopted = result["retro_history"]["adopted_tries"]
        # "Use CI" was tried in r1 and never appeared as a fix — adopted
        self.assertIn("Use CI", adopted)
        # "Split commits" was tried in r1 but appeared as a fix in r2 — NOT adopted
        self.assertNotIn("Split commits", adopted)

    def test_retro_history_recurring_fixes(self):
        """Fix items appearing in 3+ retros are recurring."""
        retros = []
        for i in range(3):
            r = make_event(
                EVENT_TYPE_RETROSPECTIVE,
                content=f"Retro {i}",
                ts=f"2026-0{i + 1}-01T00:00:00+00:00",
                keep=[{"content": "ok"}],
                fix=[{"content": "Big commits"}, {"content": f"Unique {i}"}],
            )
            r["try"] = [{"content": "try something"}]
            retros.append(r)
        self._write_events(retros)
        result = materialize.prepare_curation_data(self.smm_dir)
        self.assertIn("Big commits", result["retro_history"]["recurring_fixes"])
        self.assertNotIn("Unique 0", result["retro_history"]["recurring_fixes"])

    def test_resolved_risk_by_item_id(self):
        """Risks whose id appears in resolutions are marked resolved: True."""
        write_smm_fixture(
            self.smm_dir,
            risks=[("Stale risk", "concern", "problem")],
        )
        risk_id = smm_store.load_smm(self.smm_dir)["risks"][0]["id"]
        resolver = make_event(
            EVENT_TYPE_STATUS,
            content="Fixed the risk",
            working_on=[],
            metadata={"resolves": [risk_id]},
        )
        self._write_events([resolver])
        result = materialize.prepare_curation_data(self.smm_dir)
        risk = result["current_smm"]["risks"][0]
        self.assertTrue(risk.get("resolved", False))

    def test_resolved_risk_by_source_event_id(self):
        """Risks whose source_event_id appears in resolutions are marked resolved."""
        source_id = "abc123def456"
        data = {
            "intent": [],
            "constraints": [],
            "risks": [
                {
                    "id": "aaa111bbb222",
                    "content": "Old concern",
                    "source": "curated",
                    "ts": "2026-01-01T00:00:00+00:00",
                    "type": EVENT_TYPE_CONCERN,
                    "severity": "problem",
                    "source_event_id": source_id,
                }
            ],
            "wisdom": [],
        }
        smm_store.save_smm(self.smm_dir, data)
        resolver = make_event(
            EVENT_TYPE_STATUS,
            content="Fixed",
            working_on=[],
            metadata={"resolves": [source_id]},
        )
        self._write_events([resolver])
        result = materialize.prepare_curation_data(self.smm_dir)
        risk = result["current_smm"]["risks"][0]
        self.assertTrue(risk.get("resolved", False))

    def test_unresolved_risk_no_resolved_flag(self):
        """Risks not in resolutions should NOT have resolved flag."""
        write_smm_fixture(
            self.smm_dir,
            risks=[("Open risk", "concern", "problem")],
        )
        self._write_events([make_event(EVENT_TYPE_STATUS, content="Unrelated")])
        result = materialize.prepare_curation_data(self.smm_dir)
        risk = result["current_smm"]["risks"][0]
        self.assertFalse(risk.get("resolved", False))

    def test_resolved_risk_does_not_mutate_persisted_smm(self):
        """Annotation must not modify the on-disk SMM."""
        write_smm_fixture(
            self.smm_dir,
            risks=[("Risk to resolve", "concern", "problem")],
        )
        risk_id = smm_store.load_smm(self.smm_dir)["risks"][0]["id"]
        resolver = make_event(
            EVENT_TYPE_STATUS,
            content="Fixed",
            working_on=[],
            metadata={"resolves": [risk_id]},
        )
        self._write_events([resolver])
        materialize.prepare_curation_data(self.smm_dir)
        persisted = smm_store.load_smm(self.smm_dir)
        self.assertFalse(persisted["risks"][0].get("resolved", False))

    def test_team_scenario_multiple_agents(self):
        """Events from multiple agents all feed into curation data."""
        events = [
            make_event(
                EVENT_TYPE_CUSTOMER_INPUT, content="Input from A", agent_id="agent-a"
            ),
            make_event(
                EVENT_TYPE_DECISION,
                topic="db",
                content="Use PG",
                agent_id="agent-a",
            ),
            make_event(EVENT_TYPE_CONCERN, content="No tests", agent_id="agent-b"),
        ]
        self._write_events(events)
        result = materialize.prepare_curation_data(self.smm_dir)
        new = result["new_since_last_curation"]
        self.assertEqual(len(new["customer_inputs"]), 1)
        self.assertEqual(len(new["decisions"]), 1)
        self.assertEqual(len(new["concerns"]), 1)


class TestExtractRetroHistory(_SMMTestCase):
    """Tests for materialize._extract_retro_history."""

    def _retro(self, keep=None, fix=None, try_items=None, ts="2026-01-01"):
        e = make_event(EVENT_TYPE_RETROSPECTIVE, ts=ts)
        if keep:
            e["keep"] = [{"content": k} for k in keep]
        if fix:
            e["fix"] = [{"content": f} for f in fix]
        if try_items:
            e["try"] = [{"content": t} for t in try_items]
        return e

    def test_empty_returns_empty(self):
        result = materialize._extract_retro_history([])
        self.assertEqual(result["latest_tries"], [])
        self.assertEqual(result["recurring_fixes"], [])
        self.assertEqual(result["adopted_tries"], [])

    def test_latest_tries_from_most_recent(self):
        retros = [
            self._retro(try_items=["old try"], ts="2026-01-01"),
            self._retro(try_items=["new try"], ts="2026-01-02"),
        ]
        result = materialize._extract_retro_history(retros)
        self.assertEqual(result["latest_tries"], ["new try"])

    def test_recurring_fixes_at_three(self):
        retros = [
            self._retro(fix=["same fix"], ts="2026-01-01"),
            self._retro(fix=["same fix"], ts="2026-01-02"),
            self._retro(fix=["same fix"], ts="2026-01-03"),
        ]
        result = materialize._extract_retro_history(retros)
        self.assertIn("same fix", result["recurring_fixes"])

    def test_non_recurring_fix_excluded(self):
        retros = [
            self._retro(fix=["rare fix"], ts="2026-01-01"),
            self._retro(fix=["rare fix"], ts="2026-01-02"),
        ]
        result = materialize._extract_retro_history(retros)
        self.assertEqual(result["recurring_fixes"], [])

    def test_adopted_tries(self):
        retros = [
            self._retro(try_items=["worked"], ts="2026-01-01"),
            self._retro(ts="2026-01-02"),  # no fix about "worked" = adopted
        ]
        result = materialize._extract_retro_history(retros)
        self.assertIn("worked", result["adopted_tries"])

    def test_adopted_tries_capped_at_10(self):
        """F3: adopted_tries capped at 10 most recent."""
        retros = []
        for i in range(4):
            retros.append(
                self._retro(
                    try_items=[f"try-{i}-a", f"try-{i}-b", f"try-{i}-c"],
                    ts=f"2026-01-{i + 1:02d}",
                )
            )
        # Latest retro (excluded from adopted — only earlier retros count)
        retros.append(self._retro(try_items=["latest"], ts="2026-01-05"))
        result = materialize._extract_retro_history(retros)
        # 4 retros x 3 tries = 12 adopted, should be capped to 10
        self.assertLessEqual(len(result["adopted_tries"]), 10)
        # Most recent adopted tries should be kept (from later retros)
        self.assertIn("try-3-c", result["adopted_tries"])
        self.assertIn("try-3-b", result["adopted_tries"])


class TestRenderMarkdownInsensitiveToEventBudgets(_SMMTestCase):
    """story-013's original AC asked to pin that 'the rendered SMM does not
    grow' as event CONTENT_BUDGETS rise. That pin is NOT a usable guard and
    this test exists to say so explicitly, in code, so the next author
    reading a green render test never mistakes it for evidence the
    kickoff/subagent injection cost stayed flat.

    `smm_cli.render_markdown` takes the already-CURATED `current_smm` dict
    -- it never reads events.jsonl. Curated pillar items carry their own
    independent caps (smm_schema.PILLAR_CONTENT_MAX_LENGTH: Intent 200,
    Constraints 150, Risks 200, Wisdom 150), so raising event
    CONTENT_BUDGETS cannot change render_markdown's output by so much as a
    byte. The real, load-bearing guard for injection cost is
    tests/hooks/test_triage_preload.py -- it operates on raw event content
    before curation, which is where the recurring cost actually lives.
    """

    def test_render_output_identical_regardless_of_raw_event_content(self):
        write_smm_fixture(
            self.smm_dir,
            intent=[("Ship the thing", "goal")],
            risks=[("Auth bug", "concern", "problem")],
        )
        smm = smm_store.load_smm(self.smm_dir)
        baseline = smm_cli.render_markdown(smm)

        # Raw events.jsonl at the new 500-char cap -- render_markdown never
        # looks at this file, so the rendered output cannot move.
        events = [make_event(EVENT_TYPE_CONCERN, content="x" * 500) for _ in range(20)]
        self._write_events(events)
        smm_after_raw_events = smm_store.load_smm(self.smm_dir)
        after = smm_cli.render_markdown(smm_after_raw_events)

        self.assertEqual(
            baseline,
            after,
            "render_markdown output changed after writing raw events -- it "
            "should only ever depend on the curated current_smm argument",
        )


class TestCurationInputSizeBound(_SMMTestCase):
    """The housekeeper's `.curation-input.json` prompt (materialize.
    prepare_curation_data) DOES read raw event content verbatim, unlike
    render_markdown -- by design, the housekeeper needs the full causal
    chain to curate Intent/Constraints/Risks/Wisdom, so this artifact is
    NOT truncated the way the kickoff triage block is (see
    tests/hooks/test_triage_preload.py). This test pins its size at the
    new 500-char cap against a real, stated byte bound so an unrelated
    regression (e.g. duplicated bucketing, an accidental second pass over
    the same events) is caught, rather than asserting a false "stays flat"
    claim this artifact was never designed to satisfy.

    Built against a SYNTHETIC temp SMM (this test case's isolated temp
    dir), never the live SMM, which moves session to session and would
    flake.
    """

    _NUM_ITEMS = 20
    # 20 items * (500-char content + ~150 bytes JSON overhead per item for
    # id/ts/agent_id/type keys) =~ 13,000 bytes for the concerns bucket
    # alone, plus a small fixed overhead for the other (empty) sections.
    # 16,000 leaves headroom for that overhead while still catching a
    # duplication-style regression (which would roughly double the size).
    _MAX_BYTES = 16_000

    def test_curation_input_bounded_at_new_cap(self):
        events = [
            make_event(EVENT_TYPE_CONCERN, content="x" * 500)
            for _ in range(self._NUM_ITEMS)
        ]
        self._write_events(events)

        result = materialize.prepare_curation_data(self.smm_dir)
        size = len(json.dumps(result).encode("utf-8"))

        self.assertLessEqual(
            size,
            self._MAX_BYTES,
            f".curation-input.json is {size} bytes for {self._NUM_ITEMS} "
            f"concerns at the 500-char cap -- expected growth is linear in "
            f"item count and cap; anything past {self._MAX_BYTES} bytes "
            f"suggests an unrelated regression (e.g. duplicated bucketing), "
            f"not the expected cap-driven growth",
        )


if __name__ == "__main__":
    unittest.main()
