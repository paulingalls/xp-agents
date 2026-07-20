#!/usr/bin/env python3
"""Tests for _common.py — event/arg bookkeeping helpers.

Split from test_common.py (pure move, no test-body edits). Covers
parse_append_sh_args, uncommitted_event_count, current_session_start_index,
and current_session_start_ts.
Sibling groups: hook I/O (test_common_io.py), persistence
(test_common_persistence.py), stdlib import policy (test_common_stdlib.py).
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import _common
from conftest import make_event

# Explicit `from event_schema import EVENT_TYPE_*` so a future constant rename
# fails at test collection (NameError) instead of silently changing a
# make_event(...) call's behavior.
from event_schema import (
    EVENT_TYPE_COMMIT,
    EVENT_TYPE_CONCERN,
    EVENT_TYPE_DEBT,
    EVENT_TYPE_DECISION,
    EVENT_TYPE_DISCOVERY,
    EVENT_TYPE_GOAL,
    EVENT_TYPE_QUESTION,
    EVENT_TYPE_RETROSPECTIVE,
    EVENT_TYPE_SESSION_STARTED,
    EVENT_TYPE_SESSION_SUMMARY,
    EVENT_TYPE_STATUS,
    PRIORITY_ASSUMED,
)


class TestParseAppendShArgs(unittest.TestCase):
    """Unit tests for _common.parse_append_sh_args.

    All `cmd = "...--type X..."` strings below are subprocess CLI fixtures
    that exercise the parser — the literal `--type X` must appear inside the
    shell argv string regardless of whether EVENT_TYPE_* constants exist.
    Parsed-result assertions still use EVENT_TYPE_* so a constant rename
    fails loudly.
    """

    def test_returns_empty_for_non_append_sh(self):
        self.assertEqual(_common.parse_append_sh_args("ls -la"), {})
        self.assertEqual(_common.parse_append_sh_args("git commit -m hi"), {})
        self.assertEqual(_common.parse_append_sh_args(""), {})

    def test_parses_basic_flags(self):
        cmd = "bash /p/append.sh --type decision --topic foo --content bar"
        self.assertEqual(
            _common.parse_append_sh_args(cmd),
            {"type": EVENT_TYPE_DECISION, "topic": "foo", "content": "bar"},
        )

    def test_parses_quoted_values(self):
        cmd = (
            'bash /p/append.sh --type decision --content "multi word text" '
            "--topic 'api-style'"
        )
        self.assertEqual(
            _common.parse_append_sh_args(cmd),
            {
                "type": EVENT_TYPE_DECISION,
                "content": "multi word text",
                "topic": "api-style",
            },
        )

    def test_parses_metadata_json(self):
        cmd = (
            "bash /p/append.sh --type decision --content x "
            """--metadata '{"resolves":["abc123"]}'"""
        )
        result = _common.parse_append_sh_args(cmd)
        self.assertEqual(result["metadata"], '{"resolves":["abc123"]}')

    def test_boolean_flag_followed_by_flag(self):
        """--flag --next-flag value treats first as boolean (empty value)."""
        cmd = "bash /p/append.sh --dry-run --type decision --content x"
        result = _common.parse_append_sh_args(cmd)
        self.assertEqual(result["dry-run"], "")
        self.assertEqual(result["type"], EVENT_TYPE_DECISION)
        self.assertEqual(result["content"], "x")

    def test_trailing_boolean_flag(self):
        cmd = "bash /p/append.sh --type decision --dry-run"
        result = _common.parse_append_sh_args(cmd)
        self.assertEqual(result["type"], EVENT_TYPE_DECISION)
        self.assertEqual(result["dry-run"], "")

    def test_malformed_shlex_returns_empty(self):
        # Unclosed quote breaks shlex.split — must not raise.
        self.assertEqual(_common.parse_append_sh_args('append.sh --type "x'), {})

    def test_ignores_embedded_append_sh_in_quoted_content(self):
        """append.sh as a substring of a --content value still reads args after
        the *real* append.sh token — not inside the quoted message."""
        cmd = "bash /p/append.sh --type concern --content 'see append.sh docs'"
        result = _common.parse_append_sh_args(cmd)
        self.assertEqual(result["type"], EVENT_TYPE_CONCERN)
        self.assertEqual(result["content"], "see append.sh docs")

    def test_rejects_sibling_filename_ending_in_append_sh(self):
        """A script named `fake-append.sh` must not be treated as the plugin's
        append.sh. The token check matches the filename, not a suffix."""
        cmd = "bash /tmp/fake-append.sh --type decision --content x"
        self.assertEqual(_common.parse_append_sh_args(cmd), {})


class TestUncommittedEventCount(unittest.TestCase):
    """uncommitted_event_count counts only probe-resolvable types
    (concern/debt/discovery) newer than the most recent commit event.
    Orchestration noise (status/goal/retrospective/session_summary/etc.)
    is excluded so the honesty signal isn't drowned by routine bookkeeping."""

    def _ev(self, etype: str, **kw) -> dict:
        kw.setdefault("ts", "2026-05-08T10:00:00+00:00")
        if etype == EVENT_TYPE_CONCERN:
            kw.setdefault("severity", "medium")
            kw.setdefault("files", ["a.py"])
        if etype == EVENT_TYPE_DEBT:
            kw.setdefault("files", ["a.py"])
        if etype == EVENT_TYPE_DISCOVERY:
            kw.setdefault("references", ["aaaaaaaaaaaa"])
        if etype == EVENT_TYPE_QUESTION:
            kw.setdefault("priority", PRIORITY_ASSUMED)
        if etype == EVENT_TYPE_COMMIT:
            kw.setdefault("files", ["a.py"])
            kw.setdefault(
                "metadata",
                {"action": "commit_success", "commit_hash": "a" * 40},
            )
        return make_event(etype, content=f"{etype} event", **kw)

    def test_returns_zero_for_empty_list(self):
        self.assertEqual(_common.uncommitted_event_count([]), 0)

    def test_counts_post_commit_concern_debt_discovery(self):
        events = [
            self._ev(EVENT_TYPE_COMMIT),
            self._ev(EVENT_TYPE_CONCERN),
            self._ev(EVENT_TYPE_DEBT),
            self._ev(EVENT_TYPE_DISCOVERY),
        ]
        self.assertEqual(_common.uncommitted_event_count(events), 3)

    def test_excludes_orchestration_noise_post_commit(self):
        """status/goal/retrospective/session_summary/question excluded as noise."""
        events = [
            self._ev(EVENT_TYPE_COMMIT),
            self._ev(EVENT_TYPE_STATUS, working_on=[]),
            self._ev(EVENT_TYPE_GOAL),
            self._ev(EVENT_TYPE_RETROSPECTIVE),
            self._ev(EVENT_TYPE_SESSION_SUMMARY),
            self._ev(EVENT_TYPE_QUESTION),
            self._ev(EVENT_TYPE_DECISION, topic="x"),
        ]
        self.assertEqual(_common.uncommitted_event_count(events), 0)

    def test_excludes_pre_commit_concerns(self):
        """A concern that lands BEFORE the last commit doesn't count."""
        events = [
            self._ev(EVENT_TYPE_CONCERN),
            self._ev(EVENT_TYPE_COMMIT),
        ]
        self.assertEqual(_common.uncommitted_event_count(events), 0)

    def test_no_commit_means_all_actionable_events_count(self):
        """When events.jsonl has no commit yet, every concern/debt/discovery
        is counted (none are commit-anchored)."""
        events = [
            self._ev(EVENT_TYPE_STATUS, working_on=[]),
            self._ev(EVENT_TYPE_CONCERN),
            self._ev(EVENT_TYPE_DEBT),
        ]
        self.assertEqual(_common.uncommitted_event_count(events), 2)

    def test_mixed_post_commit_only_actionable_count(self):
        """1 commit + 5 noise + 2 concerns + 1 debt + 1 discovery = 4."""
        events = [
            self._ev(EVENT_TYPE_COMMIT),
            self._ev(EVENT_TYPE_STATUS, working_on=[]),
            self._ev(EVENT_TYPE_GOAL),
            self._ev(EVENT_TYPE_CONCERN),
            self._ev(EVENT_TYPE_RETROSPECTIVE),
            self._ev(EVENT_TYPE_DEBT),
            self._ev(EVENT_TYPE_SESSION_SUMMARY),
            self._ev(EVENT_TYPE_CONCERN),
            self._ev(EVENT_TYPE_DECISION, topic="x"),
            self._ev(EVENT_TYPE_DISCOVERY),
        ]
        self.assertEqual(_common.uncommitted_event_count(events), 4)


class TestCurrentSessionStartIndex(unittest.TestCase):
    """current_session_start_index re-anchors on SESSION_STARTED (the first
    event of the current session). Returns that anchor's own index — no +1 —
    so the slice events[idx:] includes the anchor. With no anchor, returns 0
    for short logs and a positive tail cap (len-200) for long ones."""

    def _ev(self, etype: str) -> dict:
        return {"type": etype, "ts": "2026-05-08T10:00:00+00:00"}

    def test_empty_events_returns_zero(self):
        self.assertEqual(_common.current_session_start_index([]), 0)

    def test_no_anchor_short_log_returns_zero(self):
        events = [self._ev(EVENT_TYPE_STATUS) for _ in range(10)]
        self.assertEqual(_common.current_session_start_index(events), 0)

    def test_no_anchor_long_log_engages_tail_cap(self):
        events = [self._ev(EVENT_TYPE_STATUS) for _ in range(250)]
        self.assertEqual(_common.current_session_start_index(events), 50)

    def test_single_anchor_returns_its_own_index(self):
        events = [self._ev(EVENT_TYPE_STATUS) for _ in range(5)]
        events.insert(3, self._ev(EVENT_TYPE_SESSION_STARTED))
        self.assertEqual(_common.current_session_start_index(events), 3)

    def test_two_anchors_returns_most_recent(self):
        events = [self._ev(EVENT_TYPE_STATUS) for _ in range(10)]
        events[2] = self._ev(EVENT_TYPE_SESSION_STARTED)
        events[7] = self._ev(EVENT_TYPE_SESSION_STARTED)
        self.assertEqual(_common.current_session_start_index(events), 7)


class TestCurrentSessionStartTs(unittest.TestCase):
    """current_session_start_ts returns the ts of the most recent
    SESSION_STARTED event, or "" when none exists."""

    def _ev(self, etype: str, ts: str) -> dict:
        return {"type": etype, "ts": ts}

    def test_no_anchor_returns_empty_string(self):
        events = [self._ev(EVENT_TYPE_STATUS, "2026-05-08T10:00:00+00:00")]
        self.assertEqual(_common.current_session_start_ts(events), "")

    def test_single_anchor_returns_its_ts(self):
        events = [
            self._ev(EVENT_TYPE_STATUS, "2026-05-08T09:00:00+00:00"),
            self._ev(EVENT_TYPE_SESSION_STARTED, "2026-05-08T10:00:00+00:00"),
        ]
        self.assertEqual(
            _common.current_session_start_ts(events), "2026-05-08T10:00:00+00:00"
        )

    def test_two_anchors_returns_later_ts(self):
        events = [
            self._ev(EVENT_TYPE_SESSION_STARTED, "2026-05-08T10:00:00+00:00"),
            self._ev(EVENT_TYPE_STATUS, "2026-05-08T11:00:00+00:00"),
            self._ev(EVENT_TYPE_SESSION_STARTED, "2026-05-08T12:00:00+00:00"),
        ]
        self.assertEqual(
            _common.current_session_start_ts(events), "2026-05-08T12:00:00+00:00"
        )


if __name__ == "__main__":
    unittest.main()
