#!/usr/bin/env python3
"""Tests for retro_metrics probe adoption classification.

Split from test_retro_metrics.py for file size management (test_retro_metrics
crossed the 500-line max when story-006 added selection_reasons coverage).
TestProbeAdoptionRate covers hit/escape/divert/silent classification of
probe→commit pairings, plus divert_details surface (selection_reasons,
agent/ts/candidates/resolves).
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from conftest import make_event
from event_schema import (
    METADATA_KEY_PROBE_CANDIDATES,
    METADATA_KEY_PROBE_SELECTION_REASONS,
    SELECTION_REASON_FILE_OVERLAP,
    SELECTION_REASON_KEYWORD,
    SELECTION_REASON_RECENCY,
    STATUS_CONTENT_RESOLVES_PROBE,
)


class TestProbeAdoptionRate(unittest.TestCase):
    """probe_adoption_rate: how often agents add trailers when probes are shown."""

    @staticmethod
    def _probe_event(
        candidate_ids: list[str],
        ts: str,
        agent_id: str = "main",
        selection_reasons: dict[str, list[str]] | None = None,
    ) -> dict:
        metadata: dict = {METADATA_KEY_PROBE_CANDIDATES: candidate_ids}
        if selection_reasons is not None:
            metadata[METADATA_KEY_PROBE_SELECTION_REASONS] = selection_reasons
        return make_event(
            "status",
            content=(
                f"{STATUS_CONTENT_RESOLVES_PROBE}: {len(candidate_ids)} candidates"
            ),
            ts=ts,
            agent_id=agent_id,
            metadata=metadata,
            working_on=[],
        )

    @staticmethod
    def _code_commit(resolves: list[str], ts: str, agent_id: str = "main") -> dict:
        return make_event(
            "commit",
            content="Work",
            ts=ts,
            files=["scripts/x.py"],
            agent_id=agent_id,
            metadata={
                "code_commit": True,
                "commit_hash": "abc",
                "resolves": resolves,
            },
        )

    def test_probe_followed_by_commit_with_trailer(self):
        import retro_metrics

        events = [
            self._probe_event(["aaa"], "2026-04-05T10:00:00+00:00"),
            self._code_commit(["aaa"], "2026-04-05T10:01:00+00:00"),
        ]
        result = retro_metrics._compute_resolves_link_rate(events, "2026-04-01")
        self.assertEqual(result["probe_adoption_total"], 1)
        self.assertEqual(result["probe_adoption_hits"], 1)
        self.assertAlmostEqual(result["probe_adoption_rate"], 1.0)

    def test_probe_followed_by_commit_without_trailer(self):
        import retro_metrics

        events = [
            self._probe_event(["aaa"], "2026-04-05T10:00:00+00:00"),
            self._code_commit([], "2026-04-05T10:01:00+00:00"),
        ]
        result = retro_metrics._compute_resolves_link_rate(events, "2026-04-01")
        self.assertEqual(result["probe_adoption_total"], 1)
        self.assertEqual(result["probe_adoption_hits"], 0)
        self.assertAlmostEqual(result["probe_adoption_rate"], 0.0)

    def test_no_probes_returns_zero(self):
        import retro_metrics

        events = [
            self._code_commit(["aaa"], "2026-04-05T10:00:00+00:00"),
        ]
        result = retro_metrics._compute_resolves_link_rate(events, "2026-04-01")
        self.assertEqual(result["probe_adoption_total"], 0)
        self.assertAlmostEqual(result["probe_adoption_rate"], 0.0)

    def test_multiple_probes_mixed_adoption(self):
        import retro_metrics

        events = [
            self._probe_event(["aaa"], "2026-04-05T10:00:00+00:00"),
            self._code_commit(["aaa"], "2026-04-05T10:01:00+00:00"),
            self._probe_event(["bbb"], "2026-04-05T11:00:00+00:00"),
            self._code_commit([], "2026-04-05T11:01:00+00:00"),
        ]
        result = retro_metrics._compute_resolves_link_rate(events, "2026-04-01")
        self.assertEqual(result["probe_adoption_total"], 2)
        self.assertEqual(result["probe_adoption_hits"], 1)
        self.assertAlmostEqual(result["probe_adoption_rate"], 0.5)
        self.assertEqual(result["probe_escape"], 1)
        self.assertEqual(result["probe_divert"], 0)
        self.assertEqual(result["probe_silent"], 0)

    def test_miss_classified_as_escape(self):
        """Probe fires; paired commit has empty resolves (Resolves-Event: none)."""
        import retro_metrics

        events = [
            self._probe_event(["aaa"], "2026-04-05T10:00:00+00:00"),
            self._code_commit([], "2026-04-05T10:01:00+00:00"),
        ]
        result = retro_metrics._compute_resolves_link_rate(events, "2026-04-01")
        self.assertEqual(result["probe_adoption_total"], 1)
        self.assertEqual(result["probe_adoption_hits"], 0)
        self.assertEqual(result["probe_escape"], 1)
        self.assertEqual(result["probe_divert"], 0)
        self.assertEqual(result["probe_silent"], 0)

    def test_miss_classified_as_divert(self):
        """Probe candidate [X]; paired commit resolves [Y] — agent picked
        their own ID, not the suggestion."""
        import retro_metrics

        events = [
            self._probe_event(["aaa"], "2026-04-05T10:00:00+00:00"),
            self._code_commit(["bbb"], "2026-04-05T10:01:00+00:00"),
        ]
        result = retro_metrics._compute_resolves_link_rate(events, "2026-04-01")
        self.assertEqual(result["probe_adoption_total"], 1)
        self.assertEqual(result["probe_adoption_hits"], 0)
        self.assertEqual(result["probe_escape"], 0)
        self.assertEqual(result["probe_divert"], 1)
        self.assertEqual(result["probe_silent"], 0)

    def test_divert_emits_diagnostic_detail(self):
        """Each divert must produce a side-by-side record (candidates +
        resolves + agent + ts) so the retro can inspect WHY the agent
        diverted, not just that it happened. Counts alone read as
        'noisy candidates' or 'agent had its own context' — the data to
        decide is in the pairing.
        """
        import retro_metrics

        events = [
            self._probe_event(
                ["aaa", "bbb"], "2026-04-05T10:00:00+00:00", agent_id="paul"
            ),
            self._code_commit(["zzz"], "2026-04-05T10:01:00+00:00", agent_id="paul"),
        ]
        result = retro_metrics._compute_resolves_link_rate(events, "2026-04-01")
        self.assertEqual(result["probe_divert"], 1)
        details = result.get("probe_divert_details")
        self.assertIsNotNone(
            details, "divert classification must surface details for the retro"
        )
        self.assertEqual(len(details), 1)
        d = details[0]
        self.assertEqual(sorted(d["candidates"]), ["aaa", "bbb"])
        self.assertEqual(d["resolves"], ["zzz"])
        self.assertEqual(d["agent_id"], "paul")
        self.assertEqual(d["probe_ts"], "2026-04-05T10:00:00+00:00")
        self.assertEqual(d["commit_ts"], "2026-04-05T10:01:00+00:00")

    def test_divert_details_include_selection_reasons(self):
        """When probe metadata carries probe_selection_reasons, divert_details
        surfaces a {candidate_id: [reasons]} map so the retro can attribute
        the divert to specific selector signals (which one misfired)."""
        import retro_metrics

        reasons = {
            "aaa": [SELECTION_REASON_KEYWORD, SELECTION_REASON_FILE_OVERLAP],
            "bbb": [SELECTION_REASON_RECENCY],
        }
        events = [
            self._probe_event(
                ["aaa", "bbb"],
                "2026-04-05T10:00:00+00:00",
                agent_id="paul",
                selection_reasons=reasons,
            ),
            self._code_commit(["zzz"], "2026-04-05T10:01:00+00:00", agent_id="paul"),
        ]
        result = retro_metrics._compute_resolves_link_rate(events, "2026-04-01")
        details = result["probe_divert_details"]
        self.assertEqual(len(details), 1)
        self.assertEqual(details[0]["selection_reasons"], reasons)

    def test_divert_details_backward_read_old_probe_event(self):
        """Archived probe events written before METADATA_KEY_PROBE_SELECTION_REASONS
        existed must not crash divert_details computation; selection_reasons
        gets {cid: []} for each candidate so consumers see a uniform shape."""
        import retro_metrics

        events = [
            self._probe_event(
                ["aaa", "bbb"], "2026-04-05T10:00:00+00:00", agent_id="paul"
            ),
            self._code_commit(["zzz"], "2026-04-05T10:01:00+00:00", agent_id="paul"),
        ]
        result = retro_metrics._compute_resolves_link_rate(events, "2026-04-01")
        details = result["probe_divert_details"]
        self.assertEqual(len(details), 1)
        self.assertEqual(details[0]["selection_reasons"], {"aaa": [], "bbb": []})

    def test_no_divert_no_details(self):
        """Hits/escapes/silents must not appear in probe_divert_details —
        only diverts do, and only diverts get inspected."""
        import retro_metrics

        events = [
            self._probe_event(["aaa"], "2026-04-05T10:00:00+00:00"),
            self._code_commit(["aaa"], "2026-04-05T10:01:00+00:00"),
        ]
        result = retro_metrics._compute_resolves_link_rate(events, "2026-04-01")
        self.assertEqual(result["probe_divert"], 0)
        self.assertEqual(result.get("probe_divert_details", []), [])

    def test_miss_classified_as_silent(self):
        """Probe fires; no subsequent commit by same agent in the window."""
        import retro_metrics

        events = [
            self._probe_event(["aaa"], "2026-04-05T10:00:00+00:00", agent_id="paul"),
        ]
        result = retro_metrics._compute_resolves_link_rate(events, "2026-04-01")
        self.assertEqual(result["probe_adoption_total"], 1)
        self.assertEqual(result["probe_adoption_hits"], 0)
        self.assertEqual(result["probe_escape"], 0)
        self.assertEqual(result["probe_divert"], 0)
        self.assertEqual(result["probe_silent"], 1)

    def test_strict_pairing_ignores_other_agent_commits(self):
        """Probe by agent A with candidate [X]; only commit referencing X is
        by agent B. Strict pairing → silent (not hit)."""
        import retro_metrics

        events = [
            self._probe_event(["aaa"], "2026-04-05T10:00:00+00:00", agent_id="paul"),
            self._code_commit(["aaa"], "2026-04-05T10:01:00+00:00", agent_id="alice"),
        ]
        result = retro_metrics._compute_resolves_link_rate(events, "2026-04-01")
        self.assertEqual(result["probe_adoption_total"], 1)
        self.assertEqual(result["probe_adoption_hits"], 0)
        self.assertEqual(result["probe_silent"], 1)

    def test_strict_pairing_hit_with_distinct_agents(self):
        """Two agents in window: each probe pairs with its own next commit."""
        import retro_metrics

        events = [
            self._probe_event(["aaa"], "2026-04-05T10:00:00+00:00", agent_id="paul"),
            self._probe_event(["bbb"], "2026-04-05T10:00:30+00:00", agent_id="alice"),
            self._code_commit(["aaa"], "2026-04-05T10:01:00+00:00", agent_id="paul"),
            self._code_commit(["bbb"], "2026-04-05T10:02:00+00:00", agent_id="alice"),
        ]
        result = retro_metrics._compute_resolves_link_rate(events, "2026-04-01")
        self.assertEqual(result["probe_adoption_total"], 2)
        self.assertEqual(result["probe_adoption_hits"], 2)

    def test_two_probes_same_agent_pair_with_distinct_commits(self):
        """Two consecutive probes by the same agent must NOT both pair with
        the same commit. Probe-1 pairs with commit-1, probe-2 pairs with
        commit-2 (or is silent if commit-2 doesn't exist)."""
        import retro_metrics

        events = [
            self._probe_event(["aaa"], "2026-04-05T10:00:00+00:00", agent_id="paul"),
            self._probe_event(["aaa"], "2026-04-05T10:00:30+00:00", agent_id="paul"),
            self._code_commit(["aaa"], "2026-04-05T10:01:00+00:00", agent_id="paul"),
        ]
        result = retro_metrics._compute_resolves_link_rate(events, "2026-04-01")
        self.assertEqual(result["probe_adoption_total"], 2)
        self.assertEqual(result["probe_adoption_hits"], 1)
        self.assertEqual(result["probe_silent"], 1)

    def test_probe_outside_sprint_window_is_excluded(self):
        """Probes before sprint_start_ts must not appear in the denominator."""
        import retro_metrics

        events = [
            self._probe_event(["aaa"], "2026-03-15T10:00:00+00:00"),
            self._code_commit([], "2026-03-15T10:01:00+00:00"),
        ]
        result = retro_metrics._compute_resolves_link_rate(events, "2026-04-01")
        self.assertEqual(result["probe_adoption_total"], 0)
        self.assertEqual(result["probe_escape"], 0)


if __name__ == "__main__":
    unittest.main()
