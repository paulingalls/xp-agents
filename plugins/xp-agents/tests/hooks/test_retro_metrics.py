#!/usr/bin/env python3
"""Tests for retro_metrics.py: resolves link rate, lifecycle classification,
and retro digest construction.

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
    EVENT_TYPE_COMMIT,
    EVENT_TYPE_CONCERN,
    EVENT_TYPE_DEBT,
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


class TestSignalEventsFilter(unittest.TestCase):
    """_build_retro_digest must strip resolved debts from signal_events,
    symmetric with the existing resolved-concern filter. Without this,
    dropped Try chains keep resurfacing because the underlying debt
    stays visible to the retro agent.
    """

    def test_resolved_debts_excluded_from_signal_events(self):
        import resolution
        import retro_metrics

        debt = make_event(EVENT_TYPE_DEBT, content="1Password deploy-key debt")
        dropper = make_event(
            EVENT_TYPE_STATUS,
            content="Drop the debt",
            working_on=[],
            metadata={"disposition": "dropped", "resolves": [debt["id"]]},
        )
        events = [debt, dropper]
        resolutions = resolution.compute_resolutions(events)
        digest = retro_metrics._build_retro_digest(events, 0, resolutions)
        signal_ids = [e["id"] for e in digest["signal_events"]]
        self.assertNotIn(debt["id"], signal_ids)

    def test_unresolved_debts_remain_in_signal_events(self):
        import resolution
        import retro_metrics

        debt = make_event(EVENT_TYPE_DEBT, content="open debt")
        events = [debt]
        resolutions = resolution.compute_resolutions(events)
        digest = retro_metrics._build_retro_digest(events, 0, resolutions)
        signal_ids = [e["id"] for e in digest["signal_events"]]
        self.assertIn(debt["id"], signal_ids)


class TestDroppedTriesRecent(unittest.TestCase):
    """digest.dropped_tries_recent surfaces user-drop events (status with
    disposition=dropped + non-empty metadata.resolves) so the retro agent
    has cross-session memory of prior drops and can avoid re-proposing.
    """

    def _drop(self, *, ts: str, content: str, resolves: list[str] | None) -> dict:
        meta: dict = {"disposition": "dropped"}
        if resolves is not None:
            meta["resolves"] = resolves
        return make_event(
            EVENT_TYPE_STATUS,
            ts=ts,
            content=content,
            working_on=[],
            metadata=meta,
        )

    def test_surfaces_last_10_matching_drops_in_reverse_file_order(self):
        import resolution
        import retro_metrics

        events: list[dict] = []
        for i in range(12):
            events.append(
                self._drop(
                    ts=f"2026-04-{i + 1:02d}T10:00:00+00:00",
                    content=f"drop {i}",
                    resolves=[f"abc{i:09d}"],
                )
            )
        events.append(
            self._drop(
                ts="2026-04-20T10:00:00+00:00",
                content="no resolves drop A",
                resolves=None,
            )
        )
        events.append(
            self._drop(
                ts="2026-04-21T10:00:00+00:00",
                content="empty resolves drop",
                resolves=[],
            )
        )
        resolutions = resolution.compute_resolutions(events)
        digest = retro_metrics._build_retro_digest(events, 0, resolutions)

        # File-order contract: reverse-iterate skips non-matching tail
        # entries, returns the next 10 matches in reverse file-order.
        drops = digest["dropped_tries_recent"]
        contents = [d["content"] for d in drops]
        self.assertEqual(contents, [f"drop {i}" for i in range(11, 1, -1)])

    def test_includes_pre_session_drops(self):
        """Drops at events[:start_idx] (prior sessions) MUST appear —
        proves we scan the full events list, not just `unanalyzed`.
        """
        import resolution
        import retro_metrics

        old_drop = self._drop(
            ts="2026-01-15T10:00:00+00:00",
            content="ancient drop",
            resolves=["deadbeef0001"],
        )
        new_drop = self._drop(
            ts="2026-04-20T10:00:00+00:00",
            content="recent drop",
            resolves=["deadbeef0002"],
        )
        events = [old_drop, new_drop]
        resolutions = resolution.compute_resolutions(events)
        digest = retro_metrics._build_retro_digest(events, 1, resolutions)

        drop_ids = [d["id"] for d in digest["dropped_tries_recent"]]
        self.assertIn(old_drop["id"], drop_ids)
        self.assertIn(new_drop["id"], drop_ids)

    def test_entry_shape_is_slim_with_content_capped(self):
        import resolution
        import retro_metrics

        long_content = "x" * 500
        d = self._drop(
            ts="2026-04-20T10:00:00+00:00",
            content=long_content,
            resolves=["aaaa00000001"],
        )
        events = [d]
        resolutions = resolution.compute_resolutions(events)
        digest = retro_metrics._build_retro_digest(events, 0, resolutions)

        drops = digest["dropped_tries_recent"]
        self.assertEqual(len(drops), 1)
        entry = drops[0]
        self.assertEqual(set(entry.keys()), {"id", "ts", "content"})
        self.assertEqual(len(entry["content"]), 200)

    def test_non_drop_status_events_excluded(self):
        """Status events without disposition=dropped MUST NOT appear."""
        import resolution
        import retro_metrics

        adopted = make_event(
            EVENT_TYPE_STATUS,
            ts="2026-04-20T10:00:00+00:00",
            content="adopt",
            working_on=[],
            metadata={"disposition": "adopted", "resolves": ["aaa00000001a"]},
        )
        deferred = make_event(
            EVENT_TYPE_STATUS,
            ts="2026-04-21T10:00:00+00:00",
            content="defer",
            working_on=[],
            metadata={"disposition": "deferred", "resolves": ["bbb00000001b"]},
        )
        events = [adopted, deferred]
        resolutions = resolution.compute_resolutions(events)
        digest = retro_metrics._build_retro_digest(events, 0, resolutions)

        self.assertEqual(digest["dropped_tries_recent"], [])

    def test_filter_works_with_interleaved_non_drop_events(self):
        # Stress filters with mostly-non-matching events: cap=10 must still
        # return exactly the 3 real drops without polluting the result set.
        import resolution
        import retro_metrics

        events: list[dict] = []
        drop_tss = []
        for i in range(50):
            events.append(
                make_event(
                    EVENT_TYPE_STATUS,
                    ts=f"2026-04-{(i % 28) + 1:02d}T10:00:{i:02d}+00:00",
                    content=f"non-drop {i}",
                    working_on=[],
                )
            )
            if i in (10, 25, 40):
                ts = f"2026-05-{(i // 10) + 1:02d}T10:00:00+00:00"
                drop_tss.append(ts)
                events.append(
                    self._drop(
                        ts=ts,
                        content=f"drop {i}",
                        resolves=[f"deadbeef{i:04d}"],
                    )
                )
        resolutions_map = resolution.compute_resolutions(events)
        digest = retro_metrics._build_retro_digest(events, 0, resolutions_map)

        drops = digest["dropped_tries_recent"]
        self.assertEqual(len(drops), 3)
        self.assertEqual([d["ts"] for d in drops], sorted(drop_tss, reverse=True))


class TestSecurityCloseRan(unittest.TestCase):
    """digest.security_close_ran flags whether a security-bearing close
    (sprint/free/plan) actually ran in this session — sourced from the
    close_started status event emitted by each security-bearing
    close-skill preload. Story-close has no Step 4 security review and
    does NOT emit close_started; its events MUST NOT flip the gate.
    """

    @staticmethod
    def _close_started(close_mode: str, ts: str, cycle_id: str = "cycle-abc") -> dict:
        return make_event(
            EVENT_TYPE_STATUS,
            ts=ts,
            content=f"Close-cycle started: {close_mode}",
            working_on=[],
            metadata={
                "action": "close_started",
                "close_mode": close_mode,
                "close_cycle_id": cycle_id,
            },
        )

    def test_true_on_sprint_close_started(self):
        import resolution
        import retro_metrics

        events = [self._close_started("sprint", "2026-04-20T10:00:00+00:00")]
        resolutions = resolution.compute_resolutions(events)
        digest = retro_metrics._build_retro_digest(events, 0, resolutions)
        self.assertTrue(digest["security_close_ran"])

    def test_true_on_free_close_started(self):
        import resolution
        import retro_metrics

        events = [self._close_started("free", "2026-04-20T10:00:00+00:00")]
        resolutions = resolution.compute_resolutions(events)
        digest = retro_metrics._build_retro_digest(events, 0, resolutions)
        self.assertTrue(digest["security_close_ran"])

    def test_true_on_plan_close_started(self):
        import resolution
        import retro_metrics

        events = [self._close_started("plan", "2026-04-20T10:00:00+00:00")]
        resolutions = resolution.compute_resolutions(events)
        digest = retro_metrics._build_retro_digest(events, 0, resolutions)
        self.assertTrue(digest["security_close_ran"])

    def test_false_on_story_close_only(self):
        """Story-close emits no close_started event. Concern events from
        xp-close-reviewer that happen to carry close_mode='story' MUST
        NOT flip the gate either — the rule is scoped to the security-
        bearing close modes.
        """
        import resolution
        import retro_metrics

        story_reviewer_concern = make_event(
            EVENT_TYPE_CONCERN,
            ts="2026-04-20T10:00:00+00:00",
            content="reviewer finding mid-story-close",
            files=["scripts/x.py"],
            metadata={"close_cycle_id": "cycle-abc", "close_mode": "story"},
        )
        events = [story_reviewer_concern]
        resolutions = resolution.compute_resolutions(events)
        digest = retro_metrics._build_retro_digest(events, 0, resolutions)
        self.assertFalse(digest["security_close_ran"])

    def test_false_when_no_close_started(self):
        import resolution
        import retro_metrics

        ordinary_concern = make_event(
            EVENT_TYPE_CONCERN,
            ts="2026-04-20T10:00:00+00:00",
            content="ordinary concern raised outside close",
            files=["scripts/x.py"],
        )
        events = [ordinary_concern]
        resolutions = resolution.compute_resolutions(events)
        digest = retro_metrics._build_retro_digest(events, 0, resolutions)
        self.assertFalse(digest["security_close_ran"])

    def test_scoped_to_unanalyzed_only(self):
        """close_started in prior-session events MUST NOT trip the flag."""
        import resolution
        import retro_metrics

        old_close_started = self._close_started(
            "sprint", "2026-01-15T10:00:00+00:00", cycle_id="ancient-cycle"
        )
        recent = make_event(
            EVENT_TYPE_CONCERN,
            ts="2026-04-20T10:00:00+00:00",
            content="ordinary concern this session",
            files=["scripts/x.py"],
        )
        events = [old_close_started, recent]
        resolutions = resolution.compute_resolutions(events)
        digest = retro_metrics._build_retro_digest(events, 1, resolutions)
        self.assertFalse(digest["security_close_ran"])


if __name__ == "__main__":
    unittest.main()
