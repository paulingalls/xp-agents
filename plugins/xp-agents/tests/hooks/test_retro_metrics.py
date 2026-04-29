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
from event_schema import (
    STATUS_ACTION_FILE_WRITE,
    STATUS_ACTION_LINT_RESOLVED,
    STATUS_ACTION_QR_COMPLETE,
    STATUS_ACTION_SECURITY_COMPLETE,
    STATUS_ACTION_SECURITY_TRIAGE_COMPLETE,
    STATUS_ACTION_SECURITY_TRIAGE_STARTED,
    STATUS_ACTION_SIMPLIFY_COMPLETE,
    STATUS_ACTION_TEST_RUN_COMPLETE,
)


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
    def _probe_event(candidate_ids: list[str], ts: str, agent_id: str = "main") -> dict:
        return make_event(
            "status",
            content=f"resolves_probe_shown: {len(candidate_ids)} candidates",
            ts=ts,
            agent_id=agent_id,
            metadata={"probe_candidates": candidate_ids},
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


class TestClassifyStatusActions(unittest.TestCase):
    """_classify_status_events dispatches on metadata.action for review-cycle
    lifecycle moments (sprint-041 / story-004 — replaces content-regex match)."""

    def test_qr_complete_action_increments_quality_reviews(self):
        import retro_metrics

        events = [
            make_event(
                "status",
                content="ignored content",
                metadata={"action": STATUS_ACTION_QR_COMPLETE},
            )
        ]
        counts = retro_metrics._classify_status_events(events)
        self.assertEqual(counts["quality_reviews"], 1)

    def test_security_complete_action_increments_security_checks(self):
        import retro_metrics

        events = [
            make_event(
                "status",
                content="ignored",
                metadata={"action": STATUS_ACTION_SECURITY_COMPLETE},
            )
        ]
        counts = retro_metrics._classify_status_events(events)
        self.assertEqual(counts["security_checks"], 1)

    def test_security_triage_actions_increment_security_checks(self):
        """Both started and complete triage actions count toward security_checks
        (preserves legacy regex semantics; double-counts a single triage run)."""
        import retro_metrics

        events = [
            make_event(
                "status",
                content="ignored",
                metadata={"action": STATUS_ACTION_SECURITY_TRIAGE_STARTED},
            ),
            make_event(
                "status",
                content="ignored",
                metadata={"action": STATUS_ACTION_SECURITY_TRIAGE_COMPLETE},
            ),
        ]
        counts = retro_metrics._classify_status_events(events)
        self.assertEqual(counts["security_checks"], 2)

    def test_simplify_complete_action_increments_simplifies(self):
        """New counter — no equivalent existed in the regex era."""
        import retro_metrics

        events = [
            make_event(
                "status",
                content="ignored",
                metadata={"action": STATUS_ACTION_SIMPLIFY_COMPLETE},
            )
        ]
        counts = retro_metrics._classify_status_events(events)
        self.assertEqual(counts["simplifies"], 1)

    def test_action_dispatch_wins_over_content_regex(self):
        """Doctrine invariant: when metadata.action is present and recognized,
        consumers must NOT also content-match. A status event whose content
        would otherwise hit a regex bucket (e.g. 'Wrote to foo.py') but whose
        action is qr_complete must count as a quality_review only — not a
        file_write — and must NOT be double-counted."""
        import retro_metrics

        events = [
            make_event(
                "status",
                content="Wrote to scripts/foo.py",
                metadata={"action": STATUS_ACTION_QR_COMPLETE},
            )
        ]
        counts = retro_metrics._classify_status_events(events)
        self.assertEqual(counts["quality_reviews"], 1)
        self.assertEqual(counts["file_writes"], 0)
        self.assertEqual(counts["other"], 0)


class TestClassifyM2ToolActions(unittest.TestCase):
    """sprint-042 M2: tool-action discriminators dispatch via metadata.action;
    legacy content regexes stay as fallback; commit counter reads type=commit."""

    def test_file_write_action_increments_file_writes_once(self):
        """metadata.action=file_write increments file_writes — and the regex
        branch must NOT also fire (no double-count even if content matches)."""
        import retro_metrics

        events = [
            make_event(
                "status",
                content="Wrote to scripts/foo.py",
                metadata={
                    "action": STATUS_ACTION_FILE_WRITE,
                    "files": ["scripts/foo.py"],
                },
            )
        ]
        counts = retro_metrics._classify_status_events(events)
        self.assertEqual(counts["file_writes"], 1)
        self.assertEqual(counts["other"], 0)

    def test_test_run_complete_action_counts(self):
        import retro_metrics

        events = [
            make_event(
                "status",
                content="ignored",
                metadata={"action": STATUS_ACTION_TEST_RUN_COMPLETE},
            )
        ]
        counts = retro_metrics._classify_status_events(events)
        self.assertEqual(counts["test_runs"], 1)

    def test_lint_resolved_action_counts(self):
        import retro_metrics

        events = [
            make_event(
                "status",
                content="ignored",
                metadata={"action": STATUS_ACTION_LINT_RESOLVED},
            )
        ]
        counts = retro_metrics._classify_status_events(events)
        self.assertEqual(counts["lint_events"], 1)

    def test_commit_counter_reads_type_commit_events(self):
        """Real commits emit type=commit (not status). The retro commit
        counter must read those directly — closes the meta-irony where a
        doctrine session couldn't count its own commits."""
        import retro_metrics

        events = [
            make_event(
                "commit",
                content="msg",
                files=["scripts/x.py"],
                metadata={"commit_hash": "abc", "code_commit": True},
            ),
            make_event(
                "commit",
                content="msg2",
                files=["scripts/y.py"],
                metadata={"commit_hash": "def", "code_commit": True},
            ),
        ]
        counts = retro_metrics._classify_status_events(events)
        self.assertEqual(counts["commits"], 2)


if __name__ == "__main__":
    unittest.main()
