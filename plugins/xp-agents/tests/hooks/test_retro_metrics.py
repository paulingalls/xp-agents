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
    DIVERT_REASON_CROSS_STORY,
    DIVERT_REASON_NEWER_THAN_SNAPSHOT,
    DIVERT_REASON_OUTSIDE_FILE_DOMAIN,
    DIVERT_REASON_UNKNOWN,
    DIVERT_REASON_WRONG_TYPE,
    EVENT_TYPE_COMMIT,
    EVENT_TYPE_CONCERN,
    EVENT_TYPE_DEBT,
    EVENT_TYPE_DECISION,
    EVENT_TYPE_DISCOVERY,
    EVENT_TYPE_STATUS,
    METADATA_KEY_PROBE_CANDIDATES,
    STATUS_ACTION_FILE_WRITE,
    STATUS_ACTION_LINT_RESOLVED,
    STATUS_ACTION_QR_COMPLETE,
    STATUS_ACTION_SECURITY_COMPLETE,
    STATUS_ACTION_SIMPLIFY_COMPLETE,
    STATUS_ACTION_TEST_RUN_COMPLETE,
    STATUS_CONTENT_RESOLVES_PROBE,
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


class TestClassifyDivertReason(unittest.TestCase):
    """_classify_divert_reason picks first-match reason for an agent's
    rejected resolves choice (divert), so retros can act on cause not count.

    Precedence: newer-than-snapshot, outside-file-domain, cross-story,
    wrong-type, unknown. Cross-story rarely fires today — spike (decision
    4f62e2ada08d) confirmed 0/84 concern/debt/discovery events carry
    metadata.story_id — kept for forward-compat as teammates start tagging.
    """

    def test_newer_than_snapshot_wins(self):
        import retro_metrics

        rejected = make_event(
            EVENT_TYPE_CONCERN,
            content="Late concern",
            ts="2026-05-01T12:00:00+00:00",
            files=["scripts/x.py"],
        )
        reason = retro_metrics._classify_divert_reason(
            rejected,
            probe_ts="2026-05-01T10:00:00+00:00",
            commit_files=["scripts/x.py"],
            story_id=None,
        )
        self.assertEqual(reason, DIVERT_REASON_NEWER_THAN_SNAPSHOT)

    def test_outside_file_domain(self):
        import retro_metrics

        rejected = make_event(
            EVENT_TYPE_CONCERN,
            content="Auth concern",
            ts="2026-05-01T09:00:00+00:00",
            files=["scripts/auth.py"],
        )
        reason = retro_metrics._classify_divert_reason(
            rejected,
            probe_ts="2026-05-01T10:00:00+00:00",
            commit_files=["scripts/billing.py"],
            story_id=None,
        )
        self.assertEqual(reason, DIVERT_REASON_OUTSIDE_FILE_DOMAIN)

    def test_cross_story_when_story_ids_differ(self):
        import retro_metrics

        rejected = make_event(
            EVENT_TYPE_CONCERN,
            content="Other story concern",
            ts="2026-05-01T09:00:00+00:00",
            files=["scripts/x.py"],
            metadata={"story_id": "story-099"},
        )
        reason = retro_metrics._classify_divert_reason(
            rejected,
            probe_ts="2026-05-01T10:00:00+00:00",
            commit_files=["scripts/x.py"],
            story_id="story-006",
        )
        self.assertEqual(reason, DIVERT_REASON_CROSS_STORY)

    def test_wrong_type_when_not_concern_debt_discovery(self):
        import retro_metrics

        rejected = make_event(
            EVENT_TYPE_DECISION,
            content="Some decision",
            ts="2026-05-01T09:00:00+00:00",
            files=["scripts/x.py"],
        )
        reason = retro_metrics._classify_divert_reason(
            rejected,
            probe_ts="2026-05-01T10:00:00+00:00",
            commit_files=["scripts/x.py"],
            story_id=None,
        )
        self.assertEqual(reason, DIVERT_REASON_WRONG_TYPE)

    def test_unknown_fallback(self):
        """Concern/debt with file overlap, older than probe, no cross-story
        signal — none of the precedence rules fire so reason is unknown.
        Guarantees no divert is silently uncategorized."""
        import retro_metrics

        rejected = make_event(
            EVENT_TYPE_DEBT,
            content="In-domain debt",
            ts="2026-05-01T09:00:00+00:00",
            files=["scripts/x.py"],
        )
        reason = retro_metrics._classify_divert_reason(
            rejected,
            probe_ts="2026-05-01T10:00:00+00:00",
            commit_files=["scripts/x.py"],
            story_id="story-006",
        )
        self.assertEqual(reason, DIVERT_REASON_UNKNOWN)

    def test_discovery_is_valid_type(self):
        """post sprint-064 widening — discovery events are not wrong-type."""
        import retro_metrics

        rejected = make_event(
            EVENT_TYPE_DISCOVERY,
            content="Discovery in domain",
            ts="2026-05-01T09:00:00+00:00",
            files=["scripts/x.py"],
        )
        reason = retro_metrics._classify_divert_reason(
            rejected,
            probe_ts="2026-05-01T10:00:00+00:00",
            commit_files=["scripts/x.py"],
            story_id=None,
        )
        self.assertEqual(reason, DIVERT_REASON_UNKNOWN)

    def test_absent_event_returns_unknown(self):
        """Block-fix (concern f23270ea5b70): when the rejected ID has no
        backing event in events_by_id (`events_by_id.get(...) or {}` yields
        `{}`), classifier must return UNKNOWN — NOT WRONG_TYPE. The empty
        dict has no `type`, but "missing event" is genuinely unknown, not
        a vocabulary violation."""
        import retro_metrics

        reason = retro_metrics._classify_divert_reason(
            {},
            probe_ts="2026-05-01T10:00:00+00:00",
            commit_files=["scripts/x.py"],
            story_id="story-006",
        )
        self.assertEqual(reason, DIVERT_REASON_UNKNOWN)

    def test_cross_story_dormant_when_story_id_missing(self):
        """Spike (decision 4f62e2ada08d): metadata.story_id absent on real
        concern events today. When the rejected event lacks story_id, the
        cross-story rule must NOT fire — fall through to wrong-type / unknown."""
        import retro_metrics

        rejected = make_event(
            EVENT_TYPE_CONCERN,
            content="No story tag",
            ts="2026-05-01T09:00:00+00:00",
            files=["scripts/x.py"],
        )
        reason = retro_metrics._classify_divert_reason(
            rejected,
            probe_ts="2026-05-01T10:00:00+00:00",
            commit_files=["scripts/x.py"],
            story_id="story-006",
        )
        self.assertEqual(reason, DIVERT_REASON_UNKNOWN)


class TestProbeDivertDetailsReason(unittest.TestCase):
    """Integration: probe_divert_details[i]['reason'] is set per divert tuple.
    Wires _classify_divert_reason into _compute_probe_adoption."""

    def _probe(self, candidates: list[str], ts: str, agent_id: str = "main") -> dict:
        return make_event(
            EVENT_TYPE_STATUS,
            content=f"{STATUS_CONTENT_RESOLVES_PROBE}: {len(candidates)} candidates",
            ts=ts,
            agent_id=agent_id,
            metadata={METADATA_KEY_PROBE_CANDIDATES: candidates},
        )

    def _commit(
        self,
        resolves: list[str],
        ts: str,
        files: list[str],
        agent_id: str = "main",
        story_id: str | None = None,
    ) -> dict:
        meta: dict = {
            "code_commit": True,
            "commit_hash": "abc",
            "resolves": resolves,
        }
        if story_id is not None:
            meta["story_id"] = story_id
        return make_event(
            EVENT_TYPE_COMMIT,
            content="Work",
            ts=ts,
            files=files,
            agent_id=agent_id,
            metadata=meta,
        )

    def test_divert_records_outside_file_domain_reason(self):
        import retro_metrics

        rejected = make_event(
            EVENT_TYPE_CONCERN,
            content="Auth concern",
            ts="2026-04-05T09:00:00+00:00",
            files=["scripts/auth.py"],
        )
        events = [
            rejected,
            self._probe(["other-id"], "2026-04-05T10:00:00+00:00"),
            self._commit(
                [rejected["id"]],
                "2026-04-05T11:00:00+00:00",
                files=["scripts/billing.py"],
            ),
        ]
        result = retro_metrics._compute_resolves_link_rate(events, "2026-04-01")
        self.assertEqual(result["probe_divert"], 1)
        details = result["probe_divert_details"]
        self.assertEqual(len(details), 1)
        self.assertEqual(details[0]["reason"], DIVERT_REASON_OUTSIDE_FILE_DOMAIN)

    def test_multi_id_divert_picks_latest_by_ts(self):
        """Concern 2a6cccba21d9: when multiple resolves IDs are not in the
        candidate set, attribute the divert to the LATEST rejected event by
        ts (most recent context the agent had), not min(id) which is
        alphabetic over hex IDs and semantically meaningless. The earlier
        rejected event sits in the file domain (would classify as
        UNKNOWN); the LATER rejected event is outside the file domain
        (classifies as OUTSIDE_FILE_DOMAIN). The reason that surfaces
        must be OUTSIDE_FILE_DOMAIN — the agent's most-recent pick."""
        import retro_metrics

        # IDs forced so alphabetic min() picks the EARLY event (in-domain
        # → UNKNOWN); switching to latest-by-ts must pick the LATE event
        # (out-of-domain → OUTSIDE_FILE_DOMAIN). Without forcing IDs the
        # test passes by random-hex luck.
        early_rejected = make_event(
            EVENT_TYPE_CONCERN,
            id="aaaaaaaaaaaa",
            content="Early concern in domain",
            ts="2026-04-05T09:00:00+00:00",
            files=["scripts/x.py"],
        )
        late_rejected = make_event(
            EVENT_TYPE_CONCERN,
            id="bbbbbbbbbbbb",
            content="Late concern outside domain",
            ts="2026-04-05T09:30:00+00:00",
            files=["scripts/auth.py"],
        )
        events = [
            early_rejected,
            late_rejected,
            self._probe(["other-id"], "2026-04-05T10:00:00+00:00"),
            self._commit(
                [early_rejected["id"], late_rejected["id"]],
                "2026-04-05T11:00:00+00:00",
                files=["scripts/x.py"],
            ),
        ]
        result = retro_metrics._compute_resolves_link_rate(events, "2026-04-01")
        details = result["probe_divert_details"]
        self.assertEqual(len(details), 1)
        self.assertEqual(details[0]["reason"], DIVERT_REASON_OUTSIDE_FILE_DOMAIN)

    def test_divert_records_newer_than_snapshot_reason(self):
        import retro_metrics

        # Rejected concern is created AFTER the probe fired — agent picked
        # something the probe never saw.
        rejected = make_event(
            EVENT_TYPE_CONCERN,
            content="Late concern",
            ts="2026-04-05T10:30:00+00:00",
            files=["scripts/x.py"],
        )
        events = [
            self._probe(["other-id"], "2026-04-05T10:00:00+00:00"),
            rejected,
            self._commit(
                [rejected["id"]],
                "2026-04-05T11:00:00+00:00",
                files=["scripts/x.py"],
            ),
        ]
        result = retro_metrics._compute_resolves_link_rate(events, "2026-04-01")
        details = result["probe_divert_details"]
        self.assertEqual(len(details), 1)
        self.assertEqual(details[0]["reason"], DIVERT_REASON_NEWER_THAN_SNAPSHOT)


if __name__ == "__main__":
    unittest.main()
