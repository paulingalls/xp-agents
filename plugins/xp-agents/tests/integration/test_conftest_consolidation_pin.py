#!/usr/bin/env python3
"""Pin: conftest re-exports are the single source of truth for shared fixtures.

Story-016 (sprint-065 burndown). Resolves debt cb25d8f8b62b (split_frontmatter
duplication), concern 102d00cdb802 (_MARKERS_PY duplication), concern
38c0da52a079 (raw sys.path.insert in test_retro_flag_cascade.py).

Three pins:

(a) Exactly one canonical `_split_frontmatter_body` definition under
    plugins/xp-agents/tests/ (excludes scaffold/_helpers.py whose
    `frontmatter_body()` is a deliberately separate copy because the
    scaffold suite has its own conftest path setup).
(b) Exactly one canonical `_MARKERS_PY = ` definition under
    plugins/xp-agents/tests/.
(c) test_retro_flag_cascade.py does not re-introduce the raw
    `sys.path.insert(... "smm")` line that this story removed in favor
    of the conftest re-export. Pin is scoped to that one file rather
    than the whole tree because most other tests still do their own
    smm sys.path.insert today; promoting them is future work, not
    story-016 scope.

Behavior of the re-exports themselves is covered by the existing
test_retro_flag_cascade.py + test_xp_story_close_security_gap.py +
test_close_cycle.py + test_markers_cli.py suites; they continue to pass
after the migration. This pin only enforces the no-duplication invariant
so a future contributor can't silently re-introduce a local copy.
"""

import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from _pin_helpers import files_to_scan

_TESTS_DIR = Path(__file__).parent.parent
_SCAFFOLD_DIR = _TESTS_DIR / "scaffold"

# Candidate test files (test_*.py + _*.py + conftest.py), scaffold/
# excluded because that suite is intentionally isolated.
_CANDIDATES: list[Path] = [
    p
    for p in files_to_scan(_TESTS_DIR, Path(__file__))
    if _SCAFFOLD_DIR not in p.parents
]

# Read each file once, share across tests — keeps the pin under 50ms even
# as the test tree grows.
_FILE_TEXTS: dict[Path, str] = {p: p.read_text(encoding="utf-8") for p in _CANDIDATES}


def _files_matching(pattern: str) -> list[Path]:
    rx = re.compile(pattern, re.MULTILINE)
    return [p for p, text in _FILE_TEXTS.items() if rx.search(text)]


class TestConftestConsolidation(unittest.TestCase):
    def test_single_split_frontmatter_body_definition(self):
        hits = _files_matching(r"^def _split_frontmatter_body\b")
        self.assertEqual(
            len(hits),
            1,
            f"_split_frontmatter_body should be defined exactly once "
            f"(in tests/_md_helpers.py); found in: {[str(p) for p in hits]}",
        )
        self.assertEqual(hits[0].name, "_md_helpers.py")

    def test_single_markers_py_constant_definition(self):
        hits = _files_matching(r"^_MARKERS_PY\s*=\s*")
        self.assertEqual(
            len(hits),
            1,
            f"_MARKERS_PY should be defined exactly once (in tests/_bases.py); "
            f"found in: {[str(p) for p in hits]}",
        )
        self.assertEqual(hits[0].name, "_bases.py")

    def test_retro_flag_cascade_does_not_reintroduce_smm_sys_path_insert(self):
        # Story-016 removed a raw `sys.path.insert(... "smm")` from
        # test_retro_flag_cascade.py in favor of the conftest re-export.
        # Pin only that file: most other tests in the tree still do their
        # own sys.path.insert for smm/scripts, and broadening this pin
        # would assert an invariant that does not hold today (and would
        # silently pass via a broken regex if scoped tree-wide — see
        # commit history before this fix).
        path = _TESTS_DIR / "integration" / "test_retro_flag_cascade.py"
        text = path.read_text(encoding="utf-8")
        # `.*` (not `[^)]*`) is required: real lines look like
        # `sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))`
        # — `[^)]*` would stop at the first `)` from `Path(__file__)`
        # and never reach the `smm` token, vacuously passing.
        rx = re.compile(r"sys\.path\.insert\b.*\bsmm\b")
        self.assertIsNone(
            rx.search(text),
            f"{path.name}: re-introduced raw sys.path.insert for smm/. "
            "Use the conftest re-export (compute_resolutions, "
            "EVENT_TYPE_CONCERN, etc.) instead.",
        )


if __name__ == "__main__":
    unittest.main()
