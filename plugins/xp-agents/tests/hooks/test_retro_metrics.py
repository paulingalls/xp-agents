#!/usr/bin/env python3
"""Tests for retro_metrics.py: resolves link rate and lifecycle
classification (the pure metric helpers).

Digest-construction tests live in test_retro_metrics_digest.py;
both split from the original test_retro_metrics.py for the 500-line cap.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from conftest import make_event
from event_schema import (
    EVENT_TYPE_COMMIT,
    EVENT_TYPE_STATUS,
    STATUS_ACTION_FILE_WRITE,
    STATUS_ACTION_LINT_RESOLVED,
    STATUS_ACTION_QR_COMPLETE,
    STATUS_ACTION_SECURITY_COMPLETE,
    STATUS_ACTION_SIMPLIFY_COMPLETE,
    STATUS_ACTION_TEST_RUN_COMPLETE,
)


class TestDirectTrailerCount(unittest.TestCase):
    """New methodology: count code commits with metadata.resolves directly."""

    def _code_commit(
        self, resolves: list[str], ts: str, agent_id: str = "main"
    ) -> dict:
        return make_event(
            EVENT_TYPE_COMMIT,
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

    def test_story_commits_excluded_from_denominator(self):
        """metadata.story_id-tagged commits do the story's work and aren't
        expected to carry Resolves-Event trailers — the story IS the unit
        of resolution. Counting them structurally floors the rate. Must
        be filtered out of both numerator and denominator."""
        import retro_metrics

        story_event = make_event(
            EVENT_TYPE_COMMIT,
            content="story-007: implement X",
            ts="2026-04-05T13:00:00+00:00",
            files=["scripts/x.py"],
            metadata={
                "code_commit": True,
                "commit_hash": "story-sha",
                "story_id": "story-007",
                # no resolves trailer — story commits aren't expected to
            },
        )
        events = [
            self._code_commit(["aaa"], "2026-04-05T10:00:00+00:00"),
            self._code_commit(["bbb"], "2026-04-05T11:00:00+00:00"),
            story_event,
        ]
        result = retro_metrics._compute_resolves_link_rate(events, "2026-04-01")
        self.assertEqual(result["resolves_trailer_total"], 2)
        self.assertEqual(result["resolves_trailer_hits"], 2)
        self.assertAlmostEqual(result["resolves_link_rate"], 1.0, places=6)

    def test_free_session_without_trailer_excluded(self):
        """metadata.is_free_session==True with NO trailer = exploration
        commit. Excluded — exploration has nothing to resolve, can't be
        expected to carry a trailer, mustn't drag the rate."""
        import retro_metrics

        free_event = make_event(
            EVENT_TYPE_COMMIT,
            content="explore",
            ts="2026-04-05T13:00:00+00:00",
            files=["scripts/x.py"],
            metadata={
                "code_commit": True,
                "commit_hash": "free-sha",
                "is_free_session": True,
                # no resolves trailer — exploration
            },
        )
        events = [
            self._code_commit(["aaa"], "2026-04-05T10:00:00+00:00"),
            self._code_commit(["bbb"], "2026-04-05T11:00:00+00:00"),
            free_event,
        ]
        result = retro_metrics._compute_resolves_link_rate(events, "2026-04-01")
        self.assertEqual(result["resolves_trailer_total"], 2)
        self.assertEqual(result["resolves_trailer_hits"], 2)
        self.assertAlmostEqual(result["resolves_link_rate"], 1.0, places=6)

    def test_free_session_with_trailer_included(self):
        """metadata.is_free_session==True WITH a trailer = concrete fix.
        Included — rewards the good behavior visibly in the rate. Story
        commits stay excluded (story IS the unit); only free commits get
        the conditional-include treatment."""
        import retro_metrics

        # 1 main commit, no trailer → 1 denom hit, 0 numerator hit
        main_no_trailer = make_event(
            EVENT_TYPE_COMMIT,
            content="cross-cutting fixup",
            ts="2026-04-05T10:00:00+00:00",
            files=["scripts/x.py"],
            metadata={"code_commit": True, "commit_hash": "main-sha"},
        )
        # 1 free commit, WITH trailer → 1 denom hit, 1 numerator hit
        free_with_trailer = make_event(
            EVENT_TYPE_COMMIT,
            content="free: fix concern X",
            ts="2026-04-05T11:00:00+00:00",
            files=["scripts/y.py"],
            metadata={
                "code_commit": True,
                "commit_hash": "free-sha",
                "is_free_session": True,
                "resolves": ["concern-id-123"],
            },
        )
        result = retro_metrics._compute_resolves_link_rate(
            [main_no_trailer, free_with_trailer], "2026-04-01"
        )
        self.assertEqual(result["resolves_trailer_total"], 2)
        self.assertEqual(result["resolves_trailer_hits"], 1)
        self.assertAlmostEqual(result["resolves_link_rate"], 0.5, places=6)

    def test_merge_commits_excluded_from_denominator(self):
        """metadata.is_merge==True commits are emitted by close_common's
        merge-gap helper and must not dilute the rate — they aggregate
        already-counted story commits and carry no Resolves trailer."""
        import retro_metrics

        merge_event = make_event(
            EVENT_TYPE_COMMIT,
            content="Merge story-001",
            ts="2026-04-05T13:00:00+00:00",
            files=["scripts/x.py"],
            metadata={
                "code_commit": True,
                "commit_hash": "merge-sha",
                "is_merge": True,
                # no resolves trailer
            },
        )
        events = [
            self._code_commit(["aaa"], "2026-04-05T10:00:00+00:00"),
            self._code_commit(["bbb"], "2026-04-05T11:00:00+00:00"),
            merge_event,
        ]
        result = retro_metrics._compute_resolves_link_rate(events, "2026-04-01")
        self.assertEqual(result["resolves_trailer_total"], 2)
        self.assertEqual(result["resolves_trailer_hits"], 2)
        self.assertAlmostEqual(result["resolves_link_rate"], 1.0, places=6)

    def test_escape_hatch_commits_excluded_from_denominator(self):
        """[release]/[chore]/[sprint-direct] commits bypass the review/
        resolution discipline by design (version bump + CHANGELOG, chores),
        so they carry no meaningful Resolves trailer and must not dilute the
        rate — same false-positive class as merge HEADs."""
        import retro_metrics

        release_event = make_event(
            EVENT_TYPE_COMMIT,
            content="[release] xp-agents 3.6.0 — guardrails",
            ts="2026-04-05T13:00:00+00:00",
            files=["scripts/x.py"],
            metadata={
                "code_commit": True,
                "commit_hash": "rel-sha",
                # no resolves trailer, no story_id, not free-session
            },
        )
        events = [
            self._code_commit(["aaa"], "2026-04-05T10:00:00+00:00"),
            self._code_commit(["bbb"], "2026-04-05T11:00:00+00:00"),
            release_event,
        ]
        result = retro_metrics._compute_resolves_link_rate(events, "2026-04-01")
        self.assertEqual(result["resolves_trailer_total"], 2)
        self.assertEqual(result["resolves_trailer_hits"], 2)
        self.assertAlmostEqual(result["resolves_link_rate"], 1.0, places=6)

    def test_story_cadence_commit_without_story_id_included(self):
        """metadata.review_cadence=="story" is deliberately NOT a denominator
        filter — the inverse of honesty_signals.review_required_commits, which
        DOES exempt story-cadence commits. Review cadence gates WHEN review
        happens; the Resolves-Event trailer is orthogonal — a non-story code
        commit closing a concern must carry the trailer regardless of cadence.
        Story-mode story work is already excluded by story_id; a non-story
        story-cadence commit is a real code commit and belongs in the rate.

        This pins the asymmetry: applying the v3.8.2 story-cadence exemption
        pattern here (filtering on review_cadence) would silently drop this
        commit and inflate the rate. Pairs with
        test_retrospective_signals.test_story_cadence_commits_excluded_from_review_required."""
        import retro_metrics

        story_cadence_no_trailer = make_event(
            EVENT_TYPE_COMMIT,
            content="cross-cutting fix on sprint base",
            ts="2026-04-05T13:00:00+00:00",
            files=["scripts/x.py"],
            metadata={
                "code_commit": True,
                "commit_hash": "cadence-sha",
                "review_cadence": "story",
                # no story_id, no trailer, not merge/escape-hatch/free —
                # a genuine code commit that SHOULD carry a trailer.
            },
        )
        events = [
            self._code_commit(["aaa"], "2026-04-05T10:00:00+00:00"),
            self._code_commit(["bbb"], "2026-04-05T11:00:00+00:00"),
            story_cadence_no_trailer,
        ]
        result = retro_metrics._compute_resolves_link_rate(events, "2026-04-01")
        self.assertEqual(result["resolves_trailer_total"], 3)
        self.assertEqual(result["resolves_trailer_hits"], 2)
        self.assertAlmostEqual(result["resolves_link_rate"], 2 / 3, places=6)


class TestClassifyLifecycleEvents(unittest.TestCase):
    """_classify_lifecycle_events dispatches on metadata.action for review-cycle
    lifecycle moments — replaces the deleted content-regex fallback."""

    def test_qr_complete_action_increments_quality_reviews(self):
        import retro_metrics

        events = [
            make_event(
                EVENT_TYPE_STATUS,
                content="ignored content",
                metadata={"action": STATUS_ACTION_QR_COMPLETE},
            )
        ]
        counts = retro_metrics._classify_lifecycle_events(events)
        self.assertEqual(counts["quality_reviews"], 1)

    def test_security_complete_action_increments_security_checks(self):
        import retro_metrics

        events = [
            make_event(
                EVENT_TYPE_STATUS,
                content="ignored",
                metadata={"action": STATUS_ACTION_SECURITY_COMPLETE},
            )
        ]
        counts = retro_metrics._classify_lifecycle_events(events)
        self.assertEqual(counts["security_checks"], 1)

    def test_simplify_complete_action_increments_simplifies(self):
        """New counter — no equivalent existed in the regex era."""
        import retro_metrics

        events = [
            make_event(
                EVENT_TYPE_STATUS,
                content="ignored",
                metadata={"action": STATUS_ACTION_SIMPLIFY_COMPLETE},
            )
        ]
        counts = retro_metrics._classify_lifecycle_events(events)
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
                EVENT_TYPE_STATUS,
                content="Wrote to scripts/foo.py",
                metadata={"action": STATUS_ACTION_QR_COMPLETE},
            )
        ]
        counts = retro_metrics._classify_lifecycle_events(events)
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
                EVENT_TYPE_STATUS,
                content="Wrote to scripts/foo.py",
                metadata={
                    "action": STATUS_ACTION_FILE_WRITE,
                    "files": ["scripts/foo.py"],
                },
            )
        ]
        counts = retro_metrics._classify_lifecycle_events(events)
        self.assertEqual(counts["file_writes"], 1)
        self.assertEqual(counts["other"], 0)

    def test_test_run_complete_action_counts(self):
        import retro_metrics

        events = [
            make_event(
                EVENT_TYPE_STATUS,
                content="ignored",
                metadata={"action": STATUS_ACTION_TEST_RUN_COMPLETE},
            )
        ]
        counts = retro_metrics._classify_lifecycle_events(events)
        self.assertEqual(counts["test_runs"], 1)

    def test_lint_resolved_action_counts(self):
        import retro_metrics

        events = [
            make_event(
                EVENT_TYPE_STATUS,
                content="ignored",
                metadata={"action": STATUS_ACTION_LINT_RESOLVED},
            )
        ]
        counts = retro_metrics._classify_lifecycle_events(events)
        self.assertEqual(counts["lint_events"], 1)

    def test_commit_counter_reads_type_commit_events(self):
        """Real commits emit type=commit (not status). The retro commit
        counter must read those directly — closes the meta-irony where a
        doctrine session couldn't count its own commits."""
        import retro_metrics

        events = [
            make_event(
                EVENT_TYPE_COMMIT,
                content="msg",
                files=["scripts/x.py"],
                metadata={"commit_hash": "abc", "code_commit": True},
            ),
            make_event(
                EVENT_TYPE_COMMIT,
                content="msg2",
                files=["scripts/y.py"],
                metadata={"commit_hash": "def", "code_commit": True},
            ),
        ]
        counts = retro_metrics._classify_lifecycle_events(events)
        self.assertEqual(counts["commits"], 2)


if __name__ == "__main__":
    unittest.main()
