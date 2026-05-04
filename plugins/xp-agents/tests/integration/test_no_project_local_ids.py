#!/usr/bin/env python3
"""Plugin code stays project-generic — no milestone IDs or spike numbers.

Constraint f7920cf86da0: no shipped .md/script under
plugins/xp-agents/{scripts,skills,smm,agents}/ may reference
project-local milestone IDs (M-N) or spike numbers (spike-N) — those
are this project's history, not vocabulary other projects share.

story-NNN / sprint-NNN are intentionally NOT matched: low-numbered
forms (story-001..story-008) are used pedagogically in CLI help and
docstring examples; distinguishing pedagogy from history via regex
alone produces false positives. Historical refs to specific sprints
(e.g., sprint-058) are addressed by manual sweep, not pattern test.
"""

import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from conftest import _PLUGIN_ROOT

_PROJECT_LOCAL_ID = re.compile(r"\b(M-\d+|spike-\d+)\b")
_SHIPPED_DIRS = ("scripts", "skills", "smm", "agents")
_SHIPPED_EXTS = frozenset({".py", ".md", ".sh", ".json"})


class TestNoProjectLocalIDsInPluginCode(unittest.TestCase):
    def test_no_project_local_ids_in_shipped_code(self):
        offenders: list[str] = []
        for d in _SHIPPED_DIRS:
            base = _PLUGIN_ROOT / d
            if not base.exists():
                continue
            for path in base.rglob("*"):
                if not path.is_file() or path.suffix not in _SHIPPED_EXTS:
                    continue
                text = path.read_text(encoding="utf-8")
                for line_no, line in enumerate(text.splitlines(), 1):
                    if _PROJECT_LOCAL_ID.search(line):
                        rel = path.relative_to(_PLUGIN_ROOT)
                        offenders.append(f"{rel}:{line_no}: {line.strip()[:100]}")
        self.assertFalse(
            offenders,
            "Project-local IDs (M-N, spike-N) in shipped plugin code "
            "(violates constraint f7920cf86da0):\n" + "\n".join(offenders[:30]),
        )


if __name__ == "__main__":
    unittest.main()
