#!/usr/bin/env python3
"""Tests for the xp-end-session skill scaffold (story-003 of sprint-070).

Pins SKILL.md frontmatter shape, body step structure, and preload.sh
end-to-end behavior against an empty SMM and a seeded SMM.
"""

import json
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import event_schema
from _bases import _PLUGIN_ROOT, _IntegrationTestCase
from _md_helpers import _split_frontmatter_body
from conftest import make_event

_SKILL_DIR = _PLUGIN_ROOT / "skills" / "xp-end-session"
_SKILL_MD = _SKILL_DIR / "SKILL.md"
_PRELOAD_SH = _SKILL_DIR / "scripts" / "preload.sh"


class TestEndSessionSkillMd(unittest.TestCase):
    """Static checks on SKILL.md — no SMM needed."""

    def test_skill_md_frontmatter_parses(self):
        text = _SKILL_MD.read_text()
        frontmatter, body = _split_frontmatter_body(text)
        self.assertNotEqual(frontmatter, "", "SKILL.md must have YAML frontmatter")
        self.assertIn("name: xp-end-session", frontmatter)
        self.assertRegex(
            frontmatter, r"description:\s*\S", "frontmatter must have a description"
        )
        self.assertIn("AskUserQuestion", frontmatter)
        self.assertIn("Bash", frontmatter)
        self.assertIn("Read", frontmatter)
        self.assertIn("# End Session", body)

    def test_skill_md_has_four_documented_steps_in_order(self):
        _, body = _split_frontmatter_body(_SKILL_MD.read_text())
        positions = [m.start() for m in re.finditer(r"^## Step \d", body, re.MULTILINE)]
        self.assertEqual(
            len(positions),
            4,
            f"expected 4 ## Step headings, found {len(positions)}",
        )
        # Confirm strict 1→2→3→4 ordering by looking at the digit on each line.
        digits = re.findall(r"^## Step (\d)", body, re.MULTILINE)
        self.assertEqual(digits, ["1", "2", "3", "4"])


class TestEndSessionPreload(_IntegrationTestCase):
    """Subprocess tests on preload.sh against tmp SMM."""

    def test_preload_runs_against_empty_smm(self):
        r = self._run_preload(_PRELOAD_SH)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("SMM_DIR=", r.stdout)
        self.assertIn("### CANDIDATES", r.stdout)
        self.assertIn("### OPEN_QUESTIONS", r.stdout)
        self.assertIn("### LIKELY_ADDRESSED", r.stdout)
        self.assertIn("### UNCOMMITTED", r.stdout)
        # Count is 0 when events.jsonl is empty.
        self.assertRegex(r.stdout, r"### UNCOMMITTED\s*\n0\s*")

    def test_preload_runs_against_seeded_smm(self):
        # 1 concern likely-addressed by a commit + 1 open question +
        # 3 status events after the commit. Expected:
        #   OPEN_QUESTIONS contains the question id
        #   LIKELY_ADDRESSED contains the concern id
        #   UNCOMMITTED == 4 (1 question + 3 status)
        events = [
            make_event(
                event_schema.EVENT_TYPE_CONCERN,
                id="dddddddddddd",
                content="bug in a.py",
                ts="2026-05-08T15:00:00+00:00",
                files=["a.py"],
                severity="medium",
            ),
            make_event(
                event_schema.EVENT_TYPE_COMMIT,
                id="cccccccccccc",
                content="fix(auth): patch a.py",
                ts="2026-05-08T15:01:00+00:00",
                files=["a.py"],
            ),
            make_event(
                event_schema.EVENT_TYPE_QUESTION,
                id="qqqqqqqqqqqq",
                content="open?",
                ts="2026-05-08T15:02:00+00:00",
                priority=event_schema.PRIORITY_ASSUMED,
            ),
        ]
        for i in range(3):
            events.append(
                make_event(
                    event_schema.EVENT_TYPE_STATUS,
                    id=f"st0{i:09d}",
                    content=f"work {i}",
                    ts=f"2026-05-08T15:03:{i:02d}+00:00",
                    working_on=["a.py"],
                )
            )
        events_file = self.smm_dir / "events.jsonl"
        events_file.write_text("".join(json.dumps(e) + "\n" for e in events))
        r = self._run_preload(_PRELOAD_SH)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("qqqqqqqqqqqq", r.stdout)
        self.assertIn("dddddddddddd", r.stdout)
        # Last commit at index 1; total events = 6; uncommitted = 4.
        self.assertRegex(r.stdout, r"### UNCOMMITTED\s*\n4\s*")


if __name__ == "__main__":
    unittest.main()
