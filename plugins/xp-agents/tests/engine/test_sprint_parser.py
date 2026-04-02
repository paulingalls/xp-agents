#!/usr/bin/env python3
"""Tests for sprint_parser.parse_sprint_data().

Covers: full parsing, empty/None/malformed input, status counting,
blocker detection, and multiple blockers.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))
from sprint_parser import parse_sprint_data

_SAMPLE_SPRINT = """\
# Sprint: Build user management REST API with auth

- **Sprint ID:** sprint-001
- **Started:** 2026-03-26

## Stories

### story-001: As a user I can register with email/password
- **Size:** M
- **Status:** done
- **Dependencies:** none
- **Acceptance Criteria:**
  - POST /register creates user with hashed password
  - Duplicate email returns 409
  - E2E: register then verify user exists in DB

### story-002: As a user I can authenticate with JWT tokens
- **Size:** M
- **Status:** in-progress
- **Dependencies:** story-001
- **Acceptance Criteria:**
  - JWT tokens validated on protected routes
  - Invalid tokens return 401
  - E2E: register then login then access protected route

### story-003: As an admin I can list all users
- **Size:** S
- **Status:** ready
- **Dependencies:** story-001
- **Acceptance Criteria:**
  - GET /admin/users returns paginated list
  - Requires admin role
  - E2E: create users then list then verify count

### story-004: As a user I can reset my password
- **Size:** M
- **Status:** ready
- **Dependencies:** story-002
- **Acceptance Criteria:**
  - POST /reset-password sends email
  - E2E: request reset then verify token

### story-005: As an admin I can deactivate accounts
- **Size:** S
- **Status:** deferred
- **Dependencies:** story-003
- **Acceptance Criteria:**
  - DELETE /admin/users/:id soft-deletes
  - E2E: deactivate then verify login fails
"""

_EMPTY_SPRINT = {
    "sprint_id": "",
    "goal": "",
    "started": "",
    "stories_by_status": {
        "ready": 0,
        "in_progress": 0,
        "done": 0,
        "deferred": 0,
    },
    "blockers": [],
}


class TestParseSprintData(unittest.TestCase):
    """Tests for parse_sprint_data()."""

    def test_full_parse(self):
        """Full sprint.md parses all header fields correctly."""
        result = parse_sprint_data(_SAMPLE_SPRINT)
        self.assertEqual(result["sprint_id"], "sprint-001")
        self.assertEqual(result["goal"], "Build user management REST API with auth")
        self.assertEqual(result["started"], "2026-03-26")

    def test_none_input(self):
        """None input returns empty structure."""
        self.assertEqual(parse_sprint_data(None), _EMPTY_SPRINT)

    def test_empty_string(self):
        """Empty string returns empty structure."""
        self.assertEqual(parse_sprint_data(""), _EMPTY_SPRINT)

    def test_malformed_content(self):
        """Garbage content returns empty structure without raising."""
        result = parse_sprint_data("this is not a sprint file\nrandom text\n")
        self.assertEqual(result, _EMPTY_SPRINT)

    def test_status_counting(self):
        """Counts stories by status correctly."""
        result = parse_sprint_data(_SAMPLE_SPRINT)
        counts = result["stories_by_status"]
        self.assertEqual(counts["done"], 1)
        self.assertEqual(counts["in_progress"], 1)
        self.assertEqual(counts["ready"], 2)
        self.assertEqual(counts["deferred"], 1)

    def test_blocker_detection(self):
        """Story depending on non-done story is a blocker."""
        result = parse_sprint_data(_SAMPLE_SPRINT)
        # story-004 depends on story-002 which is in-progress
        blocker_texts = result["blockers"]
        matching = [b for b in blocker_texts if "story-004" in b and "story-002" in b]
        self.assertEqual(len(matching), 1)

    def test_no_blocker_when_dependency_done(self):
        """Story depending on done story is NOT a blocker."""
        result = parse_sprint_data(_SAMPLE_SPRINT)
        # story-003 depends on story-001 which is done
        blocker_texts = result["blockers"]
        matching = [b for b in blocker_texts if "story-003" in b and "story-001" in b]
        self.assertEqual(len(matching), 0)

    def test_dependencies_none_no_blocker(self):
        """Story with 'Dependencies: none' produces no blocker."""
        result = parse_sprint_data(_SAMPLE_SPRINT)
        # story-001 has Dependencies: none
        blocker_texts = result["blockers"]
        matching = [b for b in blocker_texts if "story-001" in b]
        self.assertEqual(len(matching), 0)

    def test_multiple_blockers(self):
        """Multiple stories can be blocked simultaneously."""
        result = parse_sprint_data(_SAMPLE_SPRINT)
        # story-004 blocked by story-002 (in-progress)
        # story-005 blocked by story-003 (ready, not done)
        self.assertGreaterEqual(len(result["blockers"]), 2)


if __name__ == "__main__":
    unittest.main()
