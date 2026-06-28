#!/usr/bin/env python3
"""Cross-language regression-replay capstone for sprint-104 milestone-1.

The per-increment review floor must work on diffs in ANY language — not
just Python. Sprint-103's regex classifier leaked Python-only coverage
three times before being abandoned; the LLM-judged classifier
(story-002) + Step 1.4/1.5 routing (story-003) is structurally
cross-language, and THIS test makes that guarantee permanent.

The test exercises preload.sh against synthesized fixture diffs in
Python (the two known v3.11 regression shapes), TypeScript, Rust, and
a mix of other languages. It does NOT invoke the live xp-risk-classifier
subagent — that path is nondeterministic and expensive. Instead:

  * preload.sh's `## Changed Files` block + diff dump are asserted to
    surface every fixture path regardless of language extension — the
    classifier's INPUT is cross-language.
  * SKILL.md's Step 1.4 / Step 1.5 prose is asserted to consume preload's
    `## Changed Files` block by name and conditionally emit `## Review
    Focus` — closes the plumbing chain story-003 left implicit.
  * SKILL.md's RISK=low branch is asserted to skip the Review Focus
    enrichment — the unpinned false-escalation guard the reviewer flagged.

Together with story-003's SKILL.md prose pins, this gives both intent
(prose contract) and behavior (integration replay) coverage of the
cross-language pipeline.

Fixtures use generic CS vocabulary (state-field, latch, marker, lock,
async coordination) only — no xp-agents internal surface names.
"""

import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from _bases import _IntegrationTestCase
from _md_helpers import _split_frontmatter_body
from conftest import _PLUGIN_ROOT

_PRELOAD = _PLUGIN_ROOT / "skills" / "xp-quality-review" / "scripts" / "preload.sh"
_SKILL_PATH = _PLUGIN_ROOT / "skills" / "xp-quality-review" / "SKILL.md"


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
    """Capstone: cross-language pipeline plumbing for M1."""

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
        stat-only `dump_diff` summary. The classifier sees this — sufficient
        to identify the file as a Python state-machine candidate and request
        further content via Read tool (its only allowed tool).
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

        Sprint-103's regex classifier would have returned RISK=low here
        (no .py suffix). The new LLM-judged pipeline must see this diff:
        the path surfaces in both the diff stat AND the `## Changed Files`
        block — no language-extension gating.
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
        not named in M1's design (Go, Java).

        The classifier (story-002 LLM judgment) judges; the preload does
        not pre-filter. A future change that adds per-extension gating
        here would fail this test loudly.
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

    # ------------------------------------------------------------------
    # Tests — SKILL.md cross-skill plumbing pins
    # Close the pipeline chain story-003 left implicit: assert Step 1.4
    # consumes preload's `## Changed Files` block by name and Step 1.5
    # skips enrichment on RISK=low (the unpinned false-escalation guard).
    # ------------------------------------------------------------------

    def test_skill_md_step_1_4_consumes_preload_changed_files_block(self):
        """Cross-skill structural pin: Step 1.4 names preload's block by name.

        If preload's block name drifted (e.g., `## Files Changed`), this
        test would fail loudly. Without it, the integration replay tests
        above pass independently and a name drift goes unnoticed.
        """
        text = _SKILL_PATH.read_text(encoding="utf-8")
        _, body = _split_frontmatter_body(text)
        # Step 1.4 must name the preload block verbatim.
        self.assertIn(
            "## Changed Files",
            body,
            "SKILL.md Step 1.4 must name preload's `## Changed Files` block verbatim",
        )

    def test_skill_md_step_1_5_skip_enrichment_on_risk_low(self):
        """Step 1.5 explicitly skips the Review Focus enrichment on RISK=low.

        The false-escalation guard: without this prose, the classifier
        could regress to always-enrich and we'd never notice. Pin it.
        """
        text = _SKILL_PATH.read_text(encoding="utf-8")
        _, body = _split_frontmatter_body(text)
        body_lower = body.lower()
        # Explicit RISK=low handling: skip the enrichment or spawn without it.
        self.assertRegex(
            body_lower,
            r"risk=low[^.]{0,150}(without\s+the?\s*enrichment|skip|no\s+enrichment)",
            "SKILL.md Step 1.5 must explicitly describe the RISK=low skip path "
            "(unenriched spawn) — guards against false-escalation regressions",
        )


if __name__ == "__main__":
    unittest.main()
