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

from conftest import _NormalizePathIdentityMixin, make_event
from event_schema import (
    DIVERT_REASON_CROSS_STORY,
    DIVERT_REASON_MISSING_EVENT,
    DIVERT_REASON_NEWER_THAN_SNAPSHOT,
    DIVERT_REASON_OUTSIDE_FILE_DOMAIN,
    DIVERT_REASON_PROBE_SELECTION_MISS,
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
        result = retro_metrics._compute_resolves_link_rate(
            events, "2026-04-01", cwd="/repo"
        )
        self.assertEqual(result["resolves_trailer_total"], 3)
        self.assertEqual(result["resolves_trailer_hits"], 2)
        self.assertAlmostEqual(result["resolves_link_rate"], 2 / 3, places=6)

    def test_no_code_commits_returns_zero(self):
        import retro_metrics

        events = [make_event(content="status only")]
        result = retro_metrics._compute_resolves_link_rate(
            events, "2026-04-01", cwd="/repo"
        )
        self.assertEqual(result["resolves_trailer_total"], 0)
        self.assertEqual(result["resolves_link_rate"], 0.0)

    def test_per_agent_trailer_counts(self):
        import retro_metrics

        events = [
            self._code_commit(["aaa"], "2026-04-05T10:00:00+00:00", "agent-1"),
            self._code_commit([], "2026-04-05T11:00:00+00:00", "agent-1"),
            self._code_commit(["bbb"], "2026-04-05T12:00:00+00:00", "agent-2"),
        ]
        result = retro_metrics._compute_resolves_link_rate(
            events, "2026-04-01", cwd="/repo"
        )
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
        result = retro_metrics._compute_resolves_link_rate(
            events, "2026-04-01", cwd="/repo"
        )
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


class TestClassifyDivertReason(_NormalizePathIdentityMixin, unittest.TestCase):
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
            cwd="/repo",
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
            cwd="/repo",
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
            cwd="/repo",
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
            cwd="/repo",
        )
        self.assertEqual(reason, DIVERT_REASON_WRONG_TYPE)

    def test_probe_selection_miss_when_in_domain_older_valid_type(self):
        """story-005: rejected concern/debt with file overlap, older than
        probe, no cross-story signal — probe should have surfaced this
        but didn't. Sprint-065 had 4/8 diverts in this shape, all
        previously bucketed as UNKNOWN."""
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
            cwd="/repo",
        )
        self.assertEqual(reason, DIVERT_REASON_PROBE_SELECTION_MISS)

    def test_discovery_is_valid_type(self):
        """post sprint-064 widening — discovery events are not wrong-type.
        story-005: in-domain discovery now classifies as PROBE_SELECTION_MISS
        instead of falling through to UNKNOWN."""
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
            cwd="/repo",
        )
        self.assertNotEqual(reason, DIVERT_REASON_WRONG_TYPE)
        self.assertEqual(reason, DIVERT_REASON_PROBE_SELECTION_MISS)

    def test_missing_event_returns_missing_event_bucket(self):
        """story-005 (replaces the f23270ea5b70 block-fix pin): when the
        rejected ID has no backing event in events_by_id (`events_by_id.get(...)
        or {}` yields `{}`), classifier returns MISSING_EVENT — distinct
        from UNKNOWN and from WRONG_TYPE. Sprint-065 had 4/8 diverts in
        this shape (typo / hallucinated / external IDs), all previously
        bucketed as UNKNOWN."""
        import retro_metrics

        reason = retro_metrics._classify_divert_reason(
            {},
            probe_ts="2026-05-01T10:00:00+00:00",
            commit_files=["scripts/x.py"],
            story_id="story-006",
            cwd="/repo",
        )
        self.assertEqual(reason, DIVERT_REASON_MISSING_EVENT)

    def test_cross_story_dormant_when_story_id_missing(self):
        """Spike (decision 4f62e2ada08d): metadata.story_id absent on real
        concern events today. When the rejected event lacks story_id, the
        cross-story rule must NOT fire — fall through to PROBE_SELECTION_MISS
        (in-domain) or UNKNOWN (no file signal)."""
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
            cwd="/repo",
        )
        self.assertNotEqual(reason, DIVERT_REASON_CROSS_STORY)
        # in-domain → PROBE_SELECTION_MISS post-story-005
        self.assertEqual(reason, DIVERT_REASON_PROBE_SELECTION_MISS)

    def test_unknown_fallback_when_no_file_signal(self):
        """True UNKNOWN catch-all: rejected event has no files, so neither
        OUTSIDE_FILE_DOMAIN nor PROBE_SELECTION_MISS can fire. Other
        precedence rules (newer-than-snapshot, cross-story, wrong-type)
        also don't apply. Guarantees the bucket isn't swallowed by the
        new PROBE_SELECTION_MISS rule when there's genuinely no signal."""
        import retro_metrics

        rejected = make_event(
            EVENT_TYPE_DEBT,
            content="No-file debt",
            ts="2026-05-01T09:00:00+00:00",
            files=[],
        )
        reason = retro_metrics._classify_divert_reason(
            rejected,
            probe_ts="2026-05-01T10:00:00+00:00",
            commit_files=["scripts/x.py"],
            story_id="story-006",
            cwd="/repo",
        )
        self.assertEqual(reason, DIVERT_REASON_UNKNOWN)


class TestProbeDivertDetailsReason(_NormalizePathIdentityMixin, unittest.TestCase):
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
        result = retro_metrics._compute_resolves_link_rate(
            events, "2026-04-01", cwd="/repo"
        )
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
        result = retro_metrics._compute_resolves_link_rate(
            events, "2026-04-01", cwd="/repo"
        )
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
        result = retro_metrics._compute_resolves_link_rate(
            events, "2026-04-01", cwd="/repo"
        )
        details = result["probe_divert_details"]
        self.assertEqual(len(details), 1)
        self.assertEqual(details[0]["reason"], DIVERT_REASON_NEWER_THAN_SNAPSHOT)


class TestSprint065DivertScenariosAllNamed(
    _NormalizePathIdentityMixin, unittest.TestCase
):
    """story-005 AC #1, #2, #4: each of the 8 sprint-065 paired-divert
    fixtures must classify into a named (non-UNKNOWN) bucket.

    Sprint-065 retrospective (Try 2b9a624f1335) flagged that all 8
    paired-diverts classified as 'unknown' — uncategorized = blind spot.
    Discovery (a499c0468583) found 4/8 had rejected IDs not in events.jsonl
    (MISSING_EVENT) and 4/8 were in-domain+older+valid-type
    (PROBE_SELECTION_MISS).
    """

    def _scenario(
        self,
        rejected_event: dict | None,
        commit_files: list[str],
        probe_ts: str = "2026-05-06T03:00:00+00:00",
        story_id: str | None = None,
    ) -> str:
        import retro_metrics

        # rejected_event=None reproduces events_by_id miss → empty dict
        rejected = rejected_event if rejected_event is not None else {}
        return retro_metrics._classify_divert_reason(
            rejected,
            probe_ts=probe_ts,
            commit_files=commit_files,
            story_id=story_id,
            cwd="/repo",
        )

    def test_divert_1_id_not_found_classifies_named(self):
        # worktree-story-017: rejected 7692b1b0cfad NOT FOUND in events.jsonl
        reason = self._scenario(
            None,
            ["plugins/xp-agents/agents/xp-plan-reviewer.md"],
            probe_ts="2026-05-06T00:51:49+00:00",
            story_id="story-017",
        )
        self.assertEqual(reason, DIVERT_REASON_MISSING_EVENT)
        self.assertNotEqual(reason, DIVERT_REASON_UNKNOWN)

    def test_divert_2_id_not_found_classifies_named(self):
        # worktree-story-020: rejected fc9b476f2aff NOT FOUND
        reason = self._scenario(
            None,
            ["plugins/xp-agents/tests/conftest.py"],
            probe_ts="2026-05-06T00:54:13+00:00",
            story_id="story-020",
        )
        self.assertEqual(reason, DIVERT_REASON_MISSING_EVENT)
        self.assertNotEqual(reason, DIVERT_REASON_UNKNOWN)

    def test_divert_3_in_domain_older_valid_classifies_named(self):
        # worktree-story-018: e9294fb99156 in domain (lint_check.py), older
        rejected = make_event(
            EVENT_TYPE_CONCERN,
            content="RUFF env-pin scope-shaped cowardice",
            ts="2026-05-06T00:59:33+00:00",
            files=[
                "plugins/xp-agents/scripts/lint_check.py",
                "plugins/xp-agents/tests/integration/test_replace_all_e2e.py",
            ],
        )
        reason = self._scenario(
            rejected,
            [
                "plugins/xp-agents/scripts/lint_check.py",
                "plugins/xp-agents/tests/integration/test_replace_all_e2e.py",
            ],
            probe_ts="2026-05-06T01:03:09+00:00",
            story_id="story-018",
        )
        self.assertEqual(reason, DIVERT_REASON_PROBE_SELECTION_MISS)
        self.assertNotEqual(reason, DIVERT_REASON_UNKNOWN)

    def test_divert_4_id_not_found_classifies_named(self):
        # worktree-story-020: rejected fd291938c7bf NOT FOUND
        reason = self._scenario(
            None,
            ["plugins/xp-agents/tests/hooks/test_lint.py"],
            probe_ts="2026-05-06T01:08:33+00:00",
            story_id="story-020",
        )
        self.assertEqual(reason, DIVERT_REASON_MISSING_EVENT)
        self.assertNotEqual(reason, DIVERT_REASON_UNKNOWN)

    def test_divert_5_in_domain_older_valid_classifies_named(self):
        # worktree-story-020: e9294fb99156 in domain (lint_check.py)
        rejected = make_event(
            EVENT_TYPE_CONCERN,
            content="RUFF env-pin scope-shaped cowardice",
            ts="2026-05-06T00:59:33+00:00",
            files=[
                "plugins/xp-agents/scripts/lint_check.py",
                "plugins/xp-agents/tests/integration/test_replace_all_e2e.py",
            ],
        )
        reason = self._scenario(
            rejected,
            ["plugins/xp-agents/scripts/lint_check.py"],
            probe_ts="2026-05-06T01:21:45+00:00",
            story_id="story-020",
        )
        self.assertEqual(reason, DIVERT_REASON_PROBE_SELECTION_MISS)
        self.assertNotEqual(reason, DIVERT_REASON_UNKNOWN)

    def test_divert_6_in_domain_older_valid_classifies_named(self):
        # main: 77d5d46896f4 in domain (lint_check.py merge-conflict concern)
        rejected = make_event(
            EVENT_TYPE_CONCERN,
            content="Known merge conflict with story-018 on lint_check.py",
            ts="2026-05-06T02:54:26+00:00",
            files=["plugins/xp-agents/scripts/lint_check.py"],
        )
        reason = self._scenario(
            rejected,
            ["plugins/xp-agents/scripts/lint_check.py"],
            probe_ts="2026-05-06T03:03:15+00:00",
            story_id=None,
        )
        self.assertEqual(reason, DIVERT_REASON_PROBE_SELECTION_MISS)
        self.assertNotEqual(reason, DIVERT_REASON_UNKNOWN)

    def test_divert_7_in_domain_older_valid_classifies_named(self):
        # main: 8ee439c41f08 in domain (test_assert_not_none_pin.py AC gap)
        rejected = make_event(
            EVENT_TYPE_CONCERN,
            content="AC #4 verification gap test_assert_not_none_pin",
            ts="2026-05-06T03:23:19+00:00",
            files=["plugins/xp-agents/tests/hooks/test_assert_not_none_pin.py"],
        )
        reason = self._scenario(
            rejected,
            ["plugins/xp-agents/tests/hooks/test_assert_not_none_pin.py"],
            probe_ts="2026-05-06T03:25:45+00:00",
            story_id=None,
        )
        self.assertEqual(reason, DIVERT_REASON_PROBE_SELECTION_MISS)
        self.assertNotEqual(reason, DIVERT_REASON_UNKNOWN)

    def test_divert_8_id_not_found_classifies_named(self):
        # main: rejected 6066b329f860 NOT FOUND
        reason = self._scenario(
            None,
            ["plugins/xp-agents/smm/sprint_store.py"],
            probe_ts="2026-05-06T03:26:32+00:00",
            story_id="story-003",
        )
        self.assertEqual(reason, DIVERT_REASON_MISSING_EVENT)
        self.assertNotEqual(reason, DIVERT_REASON_UNKNOWN)


class TestFileOverlapNormalization(unittest.TestCase):
    """story-005 AC #3: file-overlap recognizes ./ and absolute paths
    as the same file via worktree.normalize_path (mirrors the canonical
    pattern in resolves_probe._score_candidate and concerns.find_issues
    _for_file). Stub normalize_path so the tests assert the contract
    without needing a real git repo (mirrors the pattern in
    test_resolves_probe.test_file_overlap_uses_worktree_normalize_path).
    """

    def test_dot_slash_path_recognized_as_same_file(self):
        from unittest.mock import patch as patch_

        import retro_metrics

        rejected = make_event(
            EVENT_TYPE_CONCERN,
            content="Concern",
            ts="2026-05-01T09:00:00+00:00",
            files=["./scripts/x.py"],
        )

        def _stub(path, _cwd):
            return path.lstrip("./") if path.startswith("./") else path

        with patch_("worktree.normalize_path", side_effect=_stub):
            reason = retro_metrics._classify_divert_reason(
                rejected,
                probe_ts="2026-05-01T10:00:00+00:00",
                commit_files=["scripts/x.py"],
                story_id=None,
                cwd="/repo",
            )
        # './scripts/x.py' canonicalizes to 'scripts/x.py' → overlap → no
        # OUTSIDE_FILE_DOMAIN. In-domain valid → PROBE_SELECTION_MISS.
        self.assertEqual(reason, DIVERT_REASON_PROBE_SELECTION_MISS)

    def test_absolute_path_recognized_as_same_file(self):
        from unittest.mock import patch as patch_

        import retro_metrics

        rejected = make_event(
            EVENT_TYPE_CONCERN,
            content="Concern",
            ts="2026-05-01T09:00:00+00:00",
            files=["/abs/repo/scripts/x.py"],
        )

        def _stub(path, _cwd):
            return path.split("/abs/repo/", 1)[-1].lstrip("/")

        with patch_("worktree.normalize_path", side_effect=_stub):
            reason = retro_metrics._classify_divert_reason(
                rejected,
                probe_ts="2026-05-01T10:00:00+00:00",
                commit_files=["scripts/x.py"],
                story_id=None,
                cwd="/abs/repo",
            )
        # '/abs/repo/scripts/x.py' canonicalizes to 'scripts/x.py' → overlap.
        self.assertEqual(reason, DIVERT_REASON_PROBE_SELECTION_MISS)


class TestNormalizeFileSetSignatureTightened(unittest.TestCase):
    """story-006 AC #1: _normalize_file_set requires cwd: str — no None
    affordance. Pyright/mypy enforce this statically; the runtime check
    here pins the contract so the affordance can't be reintroduced
    without breaking a test."""

    def test_normalize_file_set_requires_cwd_str(self):
        import inspect

        import retro_metrics

        sig = inspect.signature(retro_metrics._normalize_file_set)
        cwd_param = sig.parameters["cwd"]
        self.assertIs(cwd_param.annotation, str)
        self.assertIs(cwd_param.default, inspect.Parameter.empty)


if __name__ == "__main__":
    unittest.main()
