#!/usr/bin/env python3
"""Tests for materialize._extract_retro_history() and curation-artifact size
bounds (render_markdown insensitivity to raw event budgets, and the
.curation-input.json byte cap).

Split from test_curation.py to keep both files under the 500-line cap.
TestPrepareCurationData lives in test_curation_prepare.py. Helper function
tests (bulk append, atomic writes) in test_append_helpers.py.
"""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))
import materialize
import smm_cli
import smm_store
from conftest import _SMMTestCase, make_event, write_smm_fixture
from event_schema import EVENT_TYPE_CONCERN, EVENT_TYPE_RETROSPECTIVE


class TestExtractRetroHistory(_SMMTestCase):
    """Tests for materialize._extract_retro_history."""

    def _retro(self, keep=None, fix=None, try_items=None, ts="2026-01-01"):
        e = make_event(EVENT_TYPE_RETROSPECTIVE, ts=ts)
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

    def test_adopted_tries_capped_at_10(self):
        """F3: adopted_tries capped at 10 most recent."""
        retros = []
        for i in range(4):
            retros.append(
                self._retro(
                    try_items=[f"try-{i}-a", f"try-{i}-b", f"try-{i}-c"],
                    ts=f"2026-01-{i + 1:02d}",
                )
            )
        # Latest retro (excluded from adopted — only earlier retros count)
        retros.append(self._retro(try_items=["latest"], ts="2026-01-05"))
        result = materialize._extract_retro_history(retros)
        # 4 retros x 3 tries = 12 adopted, should be capped to 10
        self.assertLessEqual(len(result["adopted_tries"]), 10)
        # Most recent adopted tries should be kept (from later retros)
        self.assertIn("try-3-c", result["adopted_tries"])
        self.assertIn("try-3-b", result["adopted_tries"])


class TestRenderMarkdownInsensitiveToEventBudgets(_SMMTestCase):
    """story-013's original AC asked to pin that 'the rendered SMM does not
    grow' as event CONTENT_BUDGETS rise. That pin is NOT a usable guard and
    this test exists to say so explicitly, in code, so the next author
    reading a green render test never mistakes it for evidence the
    kickoff/subagent injection cost stayed flat.

    `smm_cli.render_markdown` takes the already-CURATED `current_smm` dict
    -- it never reads events.jsonl. Curated pillar items carry their own
    independent caps (smm_schema.PILLAR_CONTENT_MAX_LENGTH: Intent 200,
    Constraints 150, Risks 200, Wisdom 150), so raising event
    CONTENT_BUDGETS cannot change render_markdown's output by so much as a
    byte. The real, load-bearing guard for injection cost is
    tests/hooks/test_triage_preload.py -- it operates on raw event content
    before curation, which is where the recurring cost actually lives.
    """

    def test_render_output_identical_regardless_of_raw_event_content(self):
        write_smm_fixture(
            self.smm_dir,
            intent=[("Ship the thing", "goal")],
            risks=[("Auth bug", "concern", "problem")],
        )
        smm = smm_store.load_smm(self.smm_dir)
        baseline = smm_cli.render_markdown(smm)

        # Pin that the baseline actually rendered something. Without this, a
        # future regression that made render_markdown return "" would leave
        # the assertEqual below comparing "" to "" -- passing vacuously, which
        # is precisely the failure mode this class exists to call out.
        self.assertIn("Ship the thing", baseline)
        self.assertIn("Auth bug", baseline)

        # Raw events.jsonl at the new 500-char cap -- render_markdown never
        # looks at this file, so the rendered output cannot move.
        events = [make_event(EVENT_TYPE_CONCERN, content="x" * 500) for _ in range(20)]
        self._write_events(events)
        smm_after_raw_events = smm_store.load_smm(self.smm_dir)
        after = smm_cli.render_markdown(smm_after_raw_events)

        self.assertEqual(
            baseline,
            after,
            "render_markdown output changed after writing raw events -- it "
            "should only ever depend on the curated current_smm argument",
        )


class TestCurationInputSizeBound(_SMMTestCase):
    """The housekeeper's `.curation-input.json` prompt (materialize.
    prepare_curation_data) DOES read raw event content verbatim, unlike
    render_markdown -- by design, the housekeeper needs the full causal
    chain to curate Intent/Constraints/Risks/Wisdom, so this artifact is
    NOT truncated the way the kickoff triage block is (see
    tests/hooks/test_triage_preload.py). This test pins its size at the
    new 500-char cap against a real, stated byte bound so an unrelated
    regression (e.g. duplicated bucketing, an accidental second pass over
    the same events) is caught, rather than asserting a false "stays flat"
    claim this artifact was never designed to satisfy.

    Built against a SYNTHETIC temp SMM (this test case's isolated temp
    dir), never the live SMM, which moves session to session and would
    flake.
    """

    _NUM_ITEMS = 20
    # 20 items * (500-char content + ~150 bytes JSON overhead per item for
    # id/ts/agent_id/type keys) =~ 13,000 bytes for the concerns bucket
    # alone, plus a small fixed overhead for the other (empty) sections.
    # 16,000 leaves headroom for that overhead while still catching a
    # duplication-style regression (which would roughly double the size).
    _MAX_BYTES = 16_000

    def test_curation_input_bounded_at_new_cap(self):
        events = [
            make_event(EVENT_TYPE_CONCERN, content="x" * 500)
            for _ in range(self._NUM_ITEMS)
        ]
        self._write_events(events)

        result = materialize.prepare_curation_data(self.smm_dir)
        size = len(json.dumps(result).encode("utf-8"))

        self.assertLessEqual(
            size,
            self._MAX_BYTES,
            f".curation-input.json is {size} bytes for {self._NUM_ITEMS} "
            f"concerns at the 500-char cap -- expected growth is linear in "
            f"item count and cap; anything past {self._MAX_BYTES} bytes "
            f"suggests an unrelated regression (e.g. duplicated bucketing), "
            f"not the expected cap-driven growth",
        )


if __name__ == "__main__":
    unittest.main()
