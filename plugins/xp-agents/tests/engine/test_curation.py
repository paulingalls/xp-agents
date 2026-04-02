#!/usr/bin/env python3
"""Tests for curation data preparation and retro history extraction.

Helper function tests (bulk append, atomic writes) in test_append_helpers.py.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))
import materialize
from conftest import _SMMTestCase, make_event


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
            "sprint",
        ):
            self.assertIn(key, result)
        for pillar in ("intent", "constraints", "risks", "wisdom"):
            self.assertEqual(result["current_smm"][pillar], [])
        for key in ("intent_count", "constraints_count", "risks_count", "wisdom_count"):
            self.assertEqual(result["health"][key], 0)
        # Sprint key present with empty structure
        sprint = result["sprint"]
        self.assertEqual(sprint["sprint_id"], "")
        self.assertEqual(sprint["stories_by_status"]["ready"], 0)

    def test_no_watermark_all_events_new(self):
        """Without watermark, all events appear in new_since_last_curation."""
        events = [
            make_event("customer_input", content="Build an API"),
            make_event("decision", topic="db", content="Use Postgres"),
            make_event("concern", content="No tests yet"),
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
            make_event("goal", content="Ship v1"),
            make_event("decision", topic="auth", content="Use JWT"),
            make_event("convention", topic="api", content="REST only"),
        ]
        new_events = [
            make_event("customer_input", content="Add password reset"),
            make_event("concern", content="Empty catch block"),
        ]
        self._write_events(old_events + new_events)
        materialize.write_curation_watermark(
            self.smm_dir, len(old_events), "xp-housekeeping"
        )
        result = materialize.prepare_curation_data(self.smm_dir)
        new = result["new_since_last_curation"]
        self.assertEqual(len(new["customer_inputs"]), 1)
        self.assertEqual(new["customer_inputs"][0]["content"], "Add password reset")
        self.assertEqual(len(new["concerns"]), 1)
        # Old decisions should NOT be in new
        self.assertEqual(len(new["decisions"]), 0)

    def test_current_smm_intent(self):
        """current_smm.intent contains unresolved goals and open intents."""
        events = [
            make_event("goal", content="Ship v1"),
            make_event("customer_intent", content="Add RBAC", intent_status="open"),
        ]
        self._write_events(events)
        result = materialize.prepare_curation_data(self.smm_dir)
        intents = result["current_smm"]["intent"]
        self.assertEqual(len(intents), 2)

    def test_current_smm_constraints(self):
        """current_smm.constraints = all unresolved decisions + conventions."""
        events = [
            make_event("decision", topic="db", content="Use Postgres"),
            make_event("decision", topic="hash", content="Use bcrypt"),
            make_event("convention", topic="api", content="REST only"),
        ]
        self._write_events(events)
        result = materialize.prepare_curation_data(self.smm_dir)
        constraints = result["current_smm"]["constraints"]
        self.assertEqual(len(constraints), 3)
        contents = [c["content"] for c in constraints]
        self.assertIn("Use Postgres", contents)
        self.assertIn("Use bcrypt", contents)
        self.assertIn("REST only", contents)

    def test_current_smm_risks(self):
        """current_smm.risks = unresolved concerns + assumptions + debt + questions."""
        events = [
            make_event("concern", content="No tests"),
            make_event("assumption", content="Users prefer REST"),
            make_event("debt", content="Legacy code", files=["old.py"]),
            make_event("question", content="Which DB?", priority="\U0001f534"),
        ]
        self._write_events(events)
        result = materialize.prepare_curation_data(self.smm_dir)
        risks = result["current_smm"]["risks"]
        self.assertEqual(len(risks), 4)

    def test_resolved_items_excluded_from_current_smm(self):
        """Resolved goals/concerns/debt excluded from current_smm."""
        goal = make_event("goal", content="Ship v1")
        concern = make_event("concern", content="Old bug")
        resolver_g = make_event(
            "status", content="Done", working_on=[], metadata={"resolves": [goal["id"]]}
        )
        resolver_c = make_event(
            "status",
            content="Fixed",
            working_on=[],
            metadata={"resolves": [concern["id"]]},
        )
        self._write_events([goal, concern, resolver_g, resolver_c])
        result = materialize.prepare_curation_data(self.smm_dir)
        self.assertEqual(len(result["current_smm"]["intent"]), 0)
        self.assertEqual(len(result["current_smm"]["risks"]), 0)

    def test_resolved_assumption_excluded_from_risks(self):
        """Resolved assumptions are excluded from current_smm.risks."""
        assumption = make_event("assumption", content="API returns JSON")
        resolver = make_event(
            "status",
            content="Verified",
            working_on=[],
            metadata={"resolves": [assumption["id"]]},
        )
        self._write_events([assumption, resolver])
        result = materialize.prepare_curation_data(self.smm_dir)
        risk_ids = {r["id"] for r in result["current_smm"]["risks"]}
        self.assertNotIn(assumption["id"], risk_ids)

    def test_aging_counts_sessions(self):
        """Aging dict maps risk IDs to session count since creation."""
        concern = make_event(
            "concern", content="No tests", ts="2026-01-01T00:00:00+00:00"
        )
        sessions = [
            make_event(
                "session_end",
                content=f"end {i}",
                ts=f"2026-03-{i + 1:02d}T00:00:00+00:00",
            )
            for i in range(4)
        ]
        self._write_events([concern, *sessions])
        result = materialize.prepare_curation_data(self.smm_dir)
        self.assertEqual(result["aging"][concern["id"]], 4)

    def test_resolutions_after_watermark(self):
        """Resolutions after watermark appear in new_since_last_curation."""
        concern = make_event("concern", content="Bug")
        resolver = make_event(
            "status",
            content="Fixed",
            working_on=[],
            metadata={"resolves": [concern["id"]]},
        )
        self._write_events([concern, resolver])
        materialize.write_curation_watermark(self.smm_dir, 1, "xp-housekeeping")
        result = materialize.prepare_curation_data(self.smm_dir)
        self.assertIn(concern["id"], result["new_since_last_curation"]["resolutions"])

    def test_health_counts(self):
        """Health section counts items in each pillar."""
        events = [
            make_event("goal", content="G1"),
            make_event("goal", content="G2"),
            make_event("customer_intent", content="I1", intent_status="open"),
            make_event("decision", topic="db", content="Use PG"),
            make_event("convention", topic="api", content="REST"),
            make_event("concern", content="C1"),
            make_event("assumption", content="A1"),
        ]
        self._write_events(events)
        result = materialize.prepare_curation_data(self.smm_dir)
        self.assertEqual(result["health"]["intent_count"], 3)
        self.assertEqual(result["health"]["constraints_count"], 2)
        self.assertEqual(result["health"]["risks_count"], 2)

    # -- Step 4: retro_history + team --

    def test_resolved_concerns_excluded_from_new_since(self):
        """Resolved concerns should not appear in new_since_last_curation."""
        c1 = make_event("concern", content="Lint error in foo.py")
        c2 = make_event("concern", content="Real design concern")
        resolver = make_event(
            "status",
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
        c1 = make_event("concern", content="Lint error")
        c2 = make_event("concern", content="Test failure")
        resolver = make_event(
            "status",
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
            "retrospective",
            content="Retro 1",
            ts="2026-01-01T00:00:00+00:00",
            keep=[{"content": "Good tests"}],
            fix=[{"content": "Slow deploys"}],
        )
        r1["try"] = [{"content": "Split commits"}]
        r2 = make_event(
            "retrospective",
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
            "retrospective",
            content="Retro 1",
            ts="2026-01-01T00:00:00+00:00",
            keep=[{"content": "ok"}],
            fix=[{"content": "Bad deploys"}],
        )
        r1["try"] = [{"content": "Use CI"}, {"content": "Split commits"}]
        r2 = make_event(
            "retrospective",
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
                "retrospective",
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

    def test_team_scenario_multiple_agents(self):
        """Events from multiple agents all feed into curation data."""
        events = [
            make_event("customer_input", content="Input from A", agent_id="agent-a"),
            make_event(
                "decision",
                topic="db",
                content="Use PG",
                agent_id="agent-a",
            ),
            make_event("concern", content="No tests", agent_id="agent-b"),
        ]
        self._write_events(events)
        result = materialize.prepare_curation_data(self.smm_dir)
        new = result["new_since_last_curation"]
        self.assertEqual(len(new["customer_inputs"]), 1)
        self.assertEqual(len(new["decisions"]), 1)
        self.assertEqual(len(new["concerns"]), 1)

    # -- Sprint data --

    _SPRINT_MD = """\
# Sprint: Build user management API

- **Sprint ID:** sprint-001
- **Started:** 2026-03-26

## Stories

### story-001: As a user I can register
- **Size:** M
- **Status:** done
- **Dependencies:** none
- **Acceptance Criteria:**
  - E2E: register user

### story-002: As a user I can login
- **Size:** M
- **Status:** in-progress
- **Dependencies:** story-001
- **Acceptance Criteria:**
  - E2E: login flow

### story-003: As an admin I can list users
- **Size:** S
- **Status:** ready
- **Dependencies:** story-002
- **Acceptance Criteria:**
  - E2E: list users
"""

    def test_sprint_key_in_curation_data(self):
        """sprint.md present → sprint key has parsed data."""
        (self.smm_dir / "sprint.md").write_text(self._SPRINT_MD)
        events = [make_event("status", content="Work started")]
        self._write_events(events)
        result = materialize.prepare_curation_data(self.smm_dir)
        sprint = result["sprint"]
        self.assertEqual(sprint["sprint_id"], "sprint-001")
        self.assertEqual(sprint["goal"], "Build user management API")
        self.assertEqual(sprint["started"], "2026-03-26")
        self.assertEqual(sprint["stories_by_status"]["done"], 1)
        self.assertEqual(sprint["stories_by_status"]["in_progress"], 1)
        self.assertEqual(sprint["stories_by_status"]["ready"], 1)

    def test_sprint_key_missing_sprint_md(self):
        """No sprint.md → sprint key has empty structure."""
        events = [make_event("status", content="Work started")]
        self._write_events(events)
        result = materialize.prepare_curation_data(self.smm_dir)
        sprint = result["sprint"]
        self.assertEqual(sprint["sprint_id"], "")
        self.assertEqual(sprint["stories_by_status"]["ready"], 0)

    def test_sprint_key_empty_events(self):
        """Empty events but sprint.md present → sprint data populated."""
        (self.smm_dir / "sprint.md").write_text(self._SPRINT_MD)
        result = materialize.prepare_curation_data(self.smm_dir)
        sprint = result["sprint"]
        self.assertEqual(sprint["sprint_id"], "sprint-001")

    def test_sprint_blockers_in_curation_data(self):
        """Blockers in sprint.md appear in curation data."""
        (self.smm_dir / "sprint.md").write_text(self._SPRINT_MD)
        events = [make_event("status", content="Work started")]
        self._write_events(events)
        result = materialize.prepare_curation_data(self.smm_dir)
        blockers = result["sprint"]["blockers"]
        # story-003 blocked by story-002 (in-progress)
        matching = [b for b in blockers if "story-003" in b]
        self.assertEqual(len(matching), 1)


class TestExtractRetroHistory(_SMMTestCase):
    """Tests for materialize._extract_retro_history."""

    def _retro(self, keep=None, fix=None, try_items=None, ts="2026-01-01"):
        e = make_event("retrospective", ts=ts)
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


if __name__ == "__main__":
    unittest.main()
