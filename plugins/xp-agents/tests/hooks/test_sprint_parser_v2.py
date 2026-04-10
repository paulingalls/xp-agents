#!/usr/bin/env python3
"""Tests for sprint_parser.py v2: new story fields and milestone header."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from sprint_parser import parse_sprint_data

# Old format — must still parse identically
OLD_FORMAT = """\
# Sprint: Build auth

- **Sprint ID:** sprint-001
- **Started:** 2026-04-01

## Stories

### story-001: Login endpoint
- **Size:** M
- **Status:** in-progress
- **Dependencies:** none
- **Source:** product_spec.md §Auth

**Acceptance Criteria:**
- Users can log in
- E2E: login flow works
"""

# New format with all enhanced fields
NEW_FORMAT = """\
# Sprint: Create system context skill

- **Sprint ID:** sprint-002
- **Started:** 2026-04-10
- **Milestone:** Milestone 1: System Context Skill

## System Context

See: system_context.md

## Stories

### story-001: Save script
- **Size:** S
- **Status:** ready
- **Dependencies:** none
- **Milestone:** execution_plan.md §Milestone 1
- **Design Sources:** docs/design.md §Layer 0

**Context:**
The save script handles atomic writes for both system_context.md
and execution_plan.md via a --type parameter.

**File Domain:**
- `scripts/save_planning_doc.py` — new parameterized save script
- `tests/hooks/test_save_planning_doc.py` — unit tests

**Interface Contracts:**
- `smm/_append_impl.py:write_text_atomic` — read-only, do not modify

**Acceptance Criteria:**
- Writes atomically
- E2E: verify file written

### story-002: Skill definition
- **Size:** M
- **Status:** in-progress
- **Dependencies:** story-001
- **Milestone:** execution_plan.md §Milestone 1
- **Design Sources:** docs/design.md §Layer 0, §/xp-system-context

**Context:**
Forked skill that delegates to subagent for autonomous analysis.

**File Domain:**
- `skills/xp-system-context/SKILL.md` — new forked skill
- `agents/xp-system-context.md` — subagent definition

**Interface Contracts:**
- `scripts/save_planning_doc.py` — from story-001, invoke via Bash

**Acceptance Criteria:**
- Preload detects create/update mode
- E2E: skill writes system_context.md
"""


class TestBackwardCompatibility(unittest.TestCase):
    """Old sprint format must parse identically."""

    def test_old_format_parses(self):
        result = parse_sprint_data(OLD_FORMAT)
        self.assertEqual(result["sprint_id"], "sprint-001")
        self.assertEqual(result["goal"], "Build auth")
        self.assertEqual(len(result["stories"]), 1)

    def test_old_format_no_milestone(self):
        result = parse_sprint_data(OLD_FORMAT)
        self.assertEqual(result.get("milestone", ""), "")

    def test_old_format_stories_have_empty_new_fields(self):
        result = parse_sprint_data(OLD_FORMAT)
        story = result["stories"][0]
        self.assertEqual(story.get("milestone_ref", ""), "")
        self.assertEqual(story.get("design_sources", ""), "")
        self.assertEqual(story.get("context", ""), "")
        self.assertEqual(story.get("file_domain", []), [])
        self.assertEqual(story.get("interface_contracts", []), [])


class TestNewFormatHeader(unittest.TestCase):
    """Sprint-level Milestone field."""

    def test_milestone_parsed(self):
        result = parse_sprint_data(NEW_FORMAT)
        self.assertEqual(result["milestone"], "Milestone 1: System Context Skill")

    def test_sprint_id_parsed(self):
        result = parse_sprint_data(NEW_FORMAT)
        self.assertEqual(result["sprint_id"], "sprint-002")

    def test_goal_parsed(self):
        result = parse_sprint_data(NEW_FORMAT)
        self.assertEqual(result["goal"], "Create system context skill")


class TestNewFormatStories(unittest.TestCase):
    """Per-story enhanced fields."""

    def setUp(self):
        self.result = parse_sprint_data(NEW_FORMAT)
        self.story1 = self.result["stories"][0]
        self.story2 = self.result["stories"][1]

    def test_story_count(self):
        self.assertEqual(len(self.result["stories"]), 2)

    def test_milestone_ref(self):
        self.assertEqual(
            self.story1["milestone_ref"],
            "execution_plan.md §Milestone 1",
        )

    def test_design_sources_single(self):
        self.assertEqual(self.story1["design_sources"], "docs/design.md §Layer 0")

    def test_design_sources_multiple(self):
        self.assertEqual(
            self.story2["design_sources"],
            "docs/design.md §Layer 0, §/xp-system-context",
        )

    def test_context_extracted(self):
        ctx = self.story1["context"]
        self.assertIn("save script handles atomic writes", ctx)
        self.assertIn("--type parameter", ctx)

    def test_context_multiline(self):
        """Context spans multiple lines."""
        ctx = self.story1["context"]
        self.assertGreater(len(ctx.strip().split("\n")), 1)

    def test_file_domain(self):
        fd = self.story1["file_domain"]
        self.assertIsInstance(fd, list)
        self.assertEqual(len(fd), 2)
        self.assertIn("scripts/save_planning_doc.py", fd[0])

    def test_interface_contracts(self):
        ic = self.story1["interface_contracts"]
        self.assertIsInstance(ic, list)
        self.assertEqual(len(ic), 1)
        self.assertIn("write_text_atomic", ic[0])

    def test_story2_file_domain(self):
        fd = self.story2["file_domain"]
        self.assertEqual(len(fd), 2)

    def test_story2_interface_contracts(self):
        ic = self.story2["interface_contracts"]
        self.assertEqual(len(ic), 1)
        self.assertIn("save_planning_doc.py", ic[0])

    def test_existing_fields_still_work(self):
        """Size, status, title, dependencies still parsed."""
        self.assertEqual(self.story1["size"], "S")
        self.assertEqual(self.story1["status"], "ready")
        self.assertEqual(self.story1["title"], "Save script")
        self.assertEqual(self.story2["status"], "in-progress")


class TestNoneAndEmpty(unittest.TestCase):
    """Edge cases."""

    def test_none_returns_empty(self):
        result = parse_sprint_data(None)
        self.assertEqual(result["milestone"], "")

    def test_empty_returns_empty(self):
        result = parse_sprint_data("")
        self.assertEqual(result["milestone"], "")


if __name__ == "__main__":
    unittest.main()
