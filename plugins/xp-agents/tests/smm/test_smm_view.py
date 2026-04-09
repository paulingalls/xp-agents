#!/usr/bin/env python3
"""Tests for smm_view: pure rendering of curated SMM to markdown."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))
import smm_schema
import smm_view


def _entry(content, source="seed", **extra):
    """Build a valid entry with a fresh id."""
    import uuid

    e = {
        "id": str(uuid.uuid4()),
        "content": content,
        "source": source,
        "ts": "2026-04-09T02:15:28+00:00",
    }
    e.update(extra)
    return e


class TestRenderMarkdown(unittest.TestCase):
    """render_markdown produces four-pillar markdown from a dict."""

    def test_empty_renders_four_pillars(self):
        result = smm_view.render_markdown(smm_schema.empty_smm())
        self.assertIn("## Intent", result)
        self.assertIn("## Constraints", result)
        self.assertIn("## Risks", result)
        self.assertIn("## Wisdom", result)

    def test_empty_pillars_have_no_bullets(self):
        result = smm_view.render_markdown(smm_schema.empty_smm())
        for line in result.splitlines():
            self.assertFalse(line.startswith("- "))

    def test_intent_goal_rendered(self):
        smm = smm_schema.empty_smm()
        smm["intent"] = [_entry("Ship v1", type="goal")]
        result = smm_view.render_markdown(smm)
        self.assertIn("Ship v1", result)

    def test_intent_customer_intent_rendered(self):
        smm = smm_schema.empty_smm()
        smm["intent"] = [_entry("Add RBAC", type="customer_intent")]
        result = smm_view.render_markdown(smm)
        self.assertIn("Add RBAC", result)

    def test_constraint_rendered(self):
        smm = smm_schema.empty_smm()
        smm["constraints"] = [_entry("Use REST", type="decision")]
        result = smm_view.render_markdown(smm)
        self.assertIn("Use REST", result)

    def test_risk_rendered(self):
        smm = smm_schema.empty_smm()
        smm["risks"] = [_entry("Auth fragile", type="concern", severity="problem")]
        result = smm_view.render_markdown(smm)
        self.assertIn("Auth fragile", result)

    def test_wisdom_rendered_plain(self):
        smm = smm_schema.empty_smm()
        smm["wisdom"] = [_entry("Commit after green")]
        result = smm_view.render_markdown(smm)
        self.assertIn("- Commit after green", result)

    def test_render_with_sprint_section(self):
        smm = smm_schema.empty_smm()
        sprint = {
            "sprint_id": "sprint-001",
            "goal": "Ship auth",
            "stories_by_status": {
                "ready": 1,
                "in_progress": 1,
                "done": 0,
                "deferred": 0,
            },
            "blockers": [],
            "stories": [],
        }
        result = smm_view.render_markdown(smm, sprint=sprint)
        self.assertIn("## Sprint", result)
        self.assertIn("sprint-001", result)
        self.assertIn("Ship auth", result)

    def test_render_without_sprint_omits_section(self):
        result = smm_view.render_markdown(smm_schema.empty_smm())
        self.assertNotIn("## Sprint", result)

    def test_multiple_entries_per_pillar(self):
        smm = smm_schema.empty_smm()
        smm["wisdom"] = [
            _entry("TDD always"),
            _entry("Small commits"),
        ]
        result = smm_view.render_markdown(smm)
        self.assertIn("TDD always", result)
        self.assertIn("Small commits", result)


class TestExtractPillar(unittest.TestCase):
    """extract_pillar returns a single pillar section as markdown."""

    def test_extract_intent(self):
        smm = smm_schema.empty_smm()
        smm["intent"] = [_entry("Ship v1", type="goal")]
        result = smm_view.extract_pillar(smm, "intent")
        self.assertIn("## Intent", result)
        self.assertIn("Ship v1", result)

    def test_extract_excludes_other_pillars(self):
        smm = smm_schema.empty_smm()
        smm["intent"] = [_entry("Ship v1", type="goal")]
        smm["wisdom"] = [_entry("TDD always")]
        result = smm_view.extract_pillar(smm, "intent")
        self.assertNotIn("Wisdom", result)
        self.assertNotIn("TDD always", result)

    def test_extract_missing_pillar_returns_empty(self):
        smm = smm_schema.empty_smm()
        result = smm_view.extract_pillar(smm, "nonexistent")
        self.assertEqual(result, "")

    def test_extract_empty_pillar_returns_header(self):
        smm = smm_schema.empty_smm()
        result = smm_view.extract_pillar(smm, "intent")
        self.assertIn("## Intent", result)


class TestExtractPillars(unittest.TestCase):
    """extract_pillars returns multiple pillar sections concatenated."""

    def test_extract_two_pillars(self):
        smm = smm_schema.empty_smm()
        smm["intent"] = [_entry("Ship v1", type="goal")]
        smm["constraints"] = [_entry("Use REST", type="decision")]
        result = smm_view.extract_pillars(smm, {"intent", "constraints"})
        self.assertIn("Intent", result)
        self.assertIn("Ship v1", result)
        self.assertIn("Constraints", result)
        self.assertIn("Use REST", result)

    def test_extract_pillars_excludes_others(self):
        smm = smm_schema.empty_smm()
        smm["intent"] = [_entry("Ship v1", type="goal")]
        smm["wisdom"] = [_entry("TDD always")]
        result = smm_view.extract_pillars(smm, {"intent"})
        self.assertNotIn("TDD always", result)

    def test_extract_pillars_wraps_in_header(self):
        smm = smm_schema.empty_smm()
        result = smm_view.extract_pillars(smm, {"intent"})
        self.assertIn("# Shared Mental Model", result)


if __name__ == "__main__":
    unittest.main()
