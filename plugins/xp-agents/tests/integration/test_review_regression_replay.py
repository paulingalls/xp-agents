#!/usr/bin/env python3
"""Cross-language regression-replay capstone for the per-increment review floor.

The review floor must work on diffs in ANY language — not just Python.
Sprint-103's regex classifier leaked Python-only coverage three times before
being abandoned. Sprint-113 removed the classifier entirely: the reviewer
(xp-code-reviewer §1c) self-triages risk from the diff + its injected
Constraints pillar, and it is language-agnostic LLM judgment. What must stay
structurally cross-language is preload.sh's INPUT to the reviewer — and THIS
test makes that guarantee permanent.

The test exercises preload.sh against synthesized fixture diffs in Python (the
two known v3.11 regression shapes), TypeScript, Rust, and a mix of other
languages. It does NOT invoke the live reviewer subagent — that path is
nondeterministic and expensive. Instead it asserts preload.sh's `## Changed
Files` block + diff dump surface every fixture path regardless of language
extension, so the reviewer's INPUT is cross-language and no per-extension
gating can silently leak Python-only coverage back in.

Fixtures use generic CS vocabulary (state-field, latch, marker, lock,
async coordination) only — no xp-agents internal surface names.
"""

import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from _bases import _IntegrationTestCase
from conftest import _PLUGIN_ROOT

_PRELOAD = _PLUGIN_ROOT / "skills" / "xp-quality-review" / "scripts" / "preload.sh"


# --- Fixture corpus -----------------------------------------------------
# All fixtures use generic CS vocabulary — no xp-agents internal names.
# The two Python regressions are shape-replicas of d69748e92ad1 (latch
# returned forever, no fall-through) and 8e0264cfcf43 (marker set without
# a paired drain in the consumer).

PY_REGRESSION_LATCH_NO_CLEAR = """\
def should_defer(state):
    # State-machine latch: defer while mid_cycle is set.
    if state.get("mid_cycle"):
        return None  # BUG: unbounded latch, no age bound or fall-through
    return False
"""

PY_REGRESSION_MARKER_NO_DRAIN = """\
def is_deferred(state):
    # Predicate guarding a downstream gate.
    if state.get("asking_user"):
        return True
    if state.get("active_teammates"):
        return True
    # BUG: missing in_flight marker check — downstream gate fires while
    # another flow is mid-execution.
    return False
"""

TS_LATCH_NO_CLEAR = """\
export function shouldDefer(state: State): boolean | null {
  // Async coordination: latch on mid-cycle flag.
  if (state.midCycle) {
    return null; // BUG: unbounded latch, no clear path
  }
  return false;
}
"""

RS_MARKER_NO_DRAIN = """\
pub fn is_deferred(state: &State) -> bool {
    let _guard = state.lock.lock().unwrap();
    if state.asking_user { return true; }
    if state.active_teammates { return true; }
    // BUG: missing in_flight marker check — gate fires while another
    // flow holds the lock elsewhere.
    false
}
"""

COSMETIC_PY = "# typo fix in module docstring\n"
COSMETIC_TS = "// typo fix in module header\n"
COSMETIC_RS = "// typo fix in module header\n"


class TestReviewRegressionReplay(_IntegrationTestCase):
    """Capstone: cross-language reviewer-input plumbing."""

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _stage_fixture(self, relpath: str, content: str) -> None:
        """Write a fixture file into the temp repo and git-add it."""
        path = self.tmpdir / relpath
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        subprocess.run(
            ["git", "add", relpath],
            cwd=self.tmpdir,
            check=True,
            capture_output=True,
        )

    def _run_qr_preload(self):
        """Invoke xp-quality-review/scripts/preload.sh, return stdout text."""
        result = self._run_preload(_PRELOAD)
        self.assertEqual(
            result.returncode,
            0,
            f"preload.sh exited {result.returncode}: stderr={result.stderr}",
        )
        return result.stdout

    # ------------------------------------------------------------------
    # Tests — preload integration replay (per-language)
    # ------------------------------------------------------------------

    def test_python_regression_latch_no_clear_surfaces_in_preload(self):
        """Shape-replica of d69748e92ad1 (stop-gate latch-off) surfaces in preload.

        Per-increment preload emits `## Changed Files` (full path list) and a
        stat-only `dump_diff` summary. The reviewer sees this — sufficient to
        identify the file as a Python state-machine candidate and read further
        content itself.
        """
        self._stage_fixture("module.py", PY_REGRESSION_LATCH_NO_CLEAR)
        out = self._run_qr_preload()
        self.assertIn("## Changed Files", out)
        self.assertIn("module.py", out)
        # Stat line surfaces in dump_diff section.
        self.assertRegex(out, r"module\.py\s*\|\s*\d+\s*\+")

    def test_python_regression_marker_no_drain_surfaces_in_preload(self):
        """Shape-replica of 8e0264cfcf43 (marker-no-drain) surfaces in preload."""
        self._stage_fixture("module.py", PY_REGRESSION_MARKER_NO_DRAIN)
        out = self._run_qr_preload()
        self.assertIn("## Changed Files", out)
        self.assertIn("module.py", out)
        self.assertRegex(out, r"module\.py\s*\|\s*\d+\s*\+")

    def test_typescript_state_machine_surfaces_cross_language(self):
        """Seeded TypeScript regression — load-bearing cross-language guard.

        Sprint-103's regex classifier would have skipped this (no .py suffix).
        The current pipeline must surface the diff to the reviewer: the path
        appears in both the diff stat AND the `## Changed Files` block — no
        language-extension gating.
        """
        self._stage_fixture("module.ts", TS_LATCH_NO_CLEAR)
        out = self._run_qr_preload()
        self.assertIn("## Changed Files", out)
        self.assertIn("module.ts", out)
        # The .ts path appears in dump_diff stat (proves no .py suffix gating).
        self.assertRegex(out, r"module\.ts\s*\|\s*\d+\s*\+")

    def test_rust_state_machine_surfaces_cross_language(self):
        """Seeded Rust regression — completes the cross-language proof triplet."""
        self._stage_fixture("module.rs", RS_MARKER_NO_DRAIN)
        out = self._run_qr_preload()
        self.assertIn("## Changed Files", out)
        self.assertIn("module.rs", out)
        self.assertRegex(out, r"module\.rs\s*\|\s*\d+\s*\+")

    def test_cosmetic_low_risk_diffs_surface_per_language(self):
        """Cosmetic diffs in all 3 languages surface — preload doesn't filter risk."""
        self._stage_fixture("readme.py", COSMETIC_PY)
        self._stage_fixture("readme.ts", COSMETIC_TS)
        self._stage_fixture("readme.rs", COSMETIC_RS)
        out = self._run_qr_preload()
        for path in ("readme.py", "readme.ts", "readme.rs"):
            self.assertIn(
                path,
                out,
                f"preload must surface cosmetic fixture {path!r} (no language filter)",
            )

    def test_preload_does_not_filter_on_file_suffix(self):
        """Anti-leak guard: every language extension surfaces — including those
        not named in the original design (Go, Java).

        The reviewer (LLM judgment) judges risk; the preload does not
        pre-filter. A future change that adds per-extension gating here would
        fail this test loudly.
        """
        self._stage_fixture("a.py", "x = 1\n")
        self._stage_fixture("b.ts", "const x = 1;\n")
        self._stage_fixture("c.rs", "fn x() {}\n")
        self._stage_fixture("d.go", "package main\nfunc x() {}\n")
        self._stage_fixture("e.java", "class X {}\n")
        out = self._run_qr_preload()
        for path in ("a.py", "b.ts", "c.rs", "d.go", "e.java"):
            self.assertIn(
                path,
                out,
                f"preload must surface {path!r} — language extension gating is a leak",
            )


if __name__ == "__main__":
    unittest.main()
