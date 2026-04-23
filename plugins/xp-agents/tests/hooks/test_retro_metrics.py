#!/usr/bin/env python3
"""Tests for retro_metrics.py: resolves link rate and probe adoption rate.

Split from test_retrospective_sprint.py for file size management.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from conftest import make_event


class TestDirectTrailerCount(unittest.TestCase):
    """New methodology: count code commits with metadata.resolves directly."""

    def _code_commit(
        self, resolves: list[str], ts: str, agent_id: str = "main"
    ) -> dict:
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

    def test_two_of_three_commits_have_trailers(self):
        import retro_metrics

        events = [
            self._code_commit(["aaa"], "2026-04-05T10:00:00+00:00"),
            self._code_commit([], "2026-04-05T11:00:00+00:00"),
            self._code_commit(["bbb"], "2026-04-05T12:00:00+00:00"),
        ]
        result = retro_metrics._compute_resolves_link_rate(events, "2026-04-01")
        self.assertEqual(result["resolves_trailer_total"], 3)
        self.assertEqual(result["resolves_trailer_hits"], 2)
        self.assertAlmostEqual(result["resolves_link_rate"], 2 / 3, places=6)

    def test_no_code_commits_returns_zero(self):
        import retro_metrics

        events = [make_event(content="status only")]
        result = retro_metrics._compute_resolves_link_rate(events, "2026-04-01")
        self.assertEqual(result["resolves_trailer_total"], 0)
        self.assertEqual(result["resolves_link_rate"], 0.0)

    def test_per_agent_trailer_counts(self):
        import retro_metrics

        events = [
            self._code_commit(["aaa"], "2026-04-05T10:00:00+00:00", "agent-1"),
            self._code_commit([], "2026-04-05T11:00:00+00:00", "agent-1"),
            self._code_commit(["bbb"], "2026-04-05T12:00:00+00:00", "agent-2"),
        ]
        result = retro_metrics._compute_resolves_link_rate(events, "2026-04-01")
        pa = result["per_agent"]
        self.assertEqual(pa["agent-1"]["resolves_trailer_total"], 2)
        self.assertEqual(pa["agent-1"]["resolves_trailer_hits"], 1)
        self.assertEqual(pa["agent-2"]["resolves_trailer_total"], 1)
        self.assertEqual(pa["agent-2"]["resolves_trailer_hits"], 1)

    def test_commits_before_sprint_start_excluded(self):
        import retro_metrics

        events = [
            self._code_commit(["aaa"], "2026-03-15T10:00:00+00:00"),
            self._code_commit(["bbb"], "2026-04-05T10:00:00+00:00"),
        ]
        result = retro_metrics._compute_resolves_link_rate(events, "2026-04-01")
        self.assertEqual(result["resolves_trailer_total"], 1)
        self.assertEqual(result["resolves_trailer_hits"], 1)


class TestProbeAdoptionRate(unittest.TestCase):
    """probe_adoption_rate: how often agents add trailers when probes are shown."""

    @staticmethod
    def _probe_event(candidate_ids: list[str], ts: str) -> dict:
        return make_event(
            "status",
            content=f"resolves_probe_shown: {len(candidate_ids)} candidates",
            ts=ts,
            metadata={"probe_candidates": candidate_ids},
            working_on=[],
        )

    @staticmethod
    def _code_commit(resolves: list[str], ts: str) -> dict:
        return make_event(
            "commit",
            content="Work",
            ts=ts,
            files=["scripts/x.py"],
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


class TestClassifyStatusQR(unittest.TestCase):
    """_classify_status_events counts quality reviews with varied phrasings."""

    def test_standard_phrasing_counted(self):
        import retro_metrics

        events = [make_event("status", content="Quality review complete. Clean.")]
        counts = retro_metrics._classify_status_events(events)
        self.assertEqual(counts["quality_reviews"], 1)

    def test_qr_abbreviation_counted(self):
        import retro_metrics

        events = [make_event("status", content="QR complete. Fixed: chrome.ts")]
        counts = retro_metrics._classify_status_events(events)
        self.assertEqual(counts["quality_reviews"], 1)


if __name__ == "__main__":
    unittest.main()
