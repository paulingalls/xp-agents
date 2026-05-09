#!/usr/bin/env python3
"""SKILL.md files stay project-generic — no 12-hex SMM event IDs.

Sprint-074 token audit: shipped SKILL.md prose accumulated references
to specific decision/concern/event IDs (12-hex) over time. This test
catches re-introduction.

Scope: 12-hex IDs only. story-NNN / sprint-NNN are pedagogical
placeholders in JSON template examples and are deliberately not
matched here (mirrors test_no_project_local_ids.py exclusion).
Historical sprint-NNN refs in prose are caught by manual review during
the trim cycle, not by this regex.
"""

import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from conftest import _PLUGIN_ROOT

_HISTORICAL_ID = re.compile(r"\b[0-9a-f]{12}\b")


class TestNoHistoricalIDsInSkills(unittest.TestCase):
    def test_no_12hex_ids_in_skill_md(self):
        skills_dir = _PLUGIN_ROOT / "skills"
        offenders: list[str] = []
        for skill_md in skills_dir.glob("*/SKILL.md"):
            for line_no, line in enumerate(
                skill_md.read_text(encoding="utf-8").splitlines(), 1
            ):
                if _HISTORICAL_ID.search(line):
                    rel = skill_md.relative_to(_PLUGIN_ROOT)
                    offenders.append(f"{rel}:{line_no}: {line.strip()[:100]}")
        self.assertFalse(
            offenders,
            "12-hex IDs (decision/concern/event refs) in shipped SKILL.md "
            "prose:\n" + "\n".join(offenders[:30]),
        )


if __name__ == "__main__":
    unittest.main()
