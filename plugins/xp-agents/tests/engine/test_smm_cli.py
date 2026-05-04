#!/usr/bin/env python3
"""Tests for smm_cli.py CLI behaviors.

Contract:
- `render` prints render_markdown(smm) to stdout.
- `section`, `has-section`, `save`, `get-event` behave as documented.
"""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from conftest import _SMMTestCase, make_event, run_cli

_CLI = Path(__file__).parent.parent.parent / "smm" / "smm_cli.py"

_SMM_SIGNATURE = "# Shared Mental Model \u2014 Curated View"


def _seed_smm(smm_dir: Path) -> None:
    """Write a minimal valid SMM file so load_smm returns real content."""
    import smm_store
    from smm_schema import empty_smm

    data = empty_smm()
    smm_store.save_smm(smm_dir, data)


class TestRenderOutput(_SMMTestCase):
    """render prints markdown to stdout."""

    def test_render_prints_signature_header(self):
        _seed_smm(self.smm_dir)
        result = run_cli(_CLI, ["render"], self.smm_dir)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(_SMM_SIGNATURE, result.stdout)

    def test_render_without_seeded_smm(self):
        result = run_cli(_CLI, ["render"], self.smm_dir)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(_SMM_SIGNATURE, result.stdout)


class TestGetEvent(_SMMTestCase):
    """get-event retrieves individual events from events.jsonl."""

    def _append_event(self, event_type: str = "status", content: str = "test") -> str:
        """Append an event and return its ID."""
        event = make_event(event_type, content=content)
        events_file = self.smm_dir / "events.jsonl"
        with events_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event) + "\n")
        return event["id"]

    def test_get_event_exact_match(self):
        """get-event with full ID prints event JSON."""
        event_id = self._append_event(content="exact match test")
        result = run_cli(_CLI, ["get-event", event_id], self.smm_dir)
        self.assertEqual(result.returncode, 0, result.stderr)
        parsed = json.loads(result.stdout)
        self.assertEqual(parsed["id"], event_id)
        self.assertEqual(parsed["content"], "exact match test")

    def test_get_event_prefix_match(self):
        """get-event with 6-char prefix resolves to full event."""
        event_id = self._append_event(content="prefix test")
        prefix = event_id[:6]
        result = run_cli(_CLI, ["get-event", prefix], self.smm_dir)
        self.assertEqual(result.returncode, 0, result.stderr)
        parsed = json.loads(result.stdout)
        self.assertEqual(parsed["id"], event_id)

    def test_get_event_not_found(self):
        """get-event with nonexistent ID returns exit 1."""
        self._append_event()
        result = run_cli(_CLI, ["get-event", "000000000000"], self.smm_dir)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("not found", result.stderr.lower())

    def test_get_event_ambiguous_prefix(self):
        """get-event with prefix matching multiple events returns exit 1."""
        # Write two events sharing a 4-char prefix but different full IDs.
        shared = "abcd"
        for suffix in ["00000001", "00000002"]:
            event = make_event("status", content="ambig")
            event["id"] = shared + suffix
            events_file = self.smm_dir / "events.jsonl"
            with events_file.open("a", encoding="utf-8") as f:
                f.write(json.dumps(event) + "\n")
        result = run_cli(_CLI, ["get-event", shared], self.smm_dir)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ambiguous", result.stderr.lower())


class TestSmmCliHelp(_SMMTestCase):
    def test_help_contains_examples(self):
        result = run_cli(_CLI, ["--help"], self.smm_dir)
        self.assertEqual(result.returncode, 0)
        self.assertIn("Examples:", result.stdout)


class TestQuestionCloseWontFix(_SMMTestCase):
    """`question close --won-fix` appends a status event resolving the question.

    Mirrors the disposition pattern used by work_selection_decide.py for
    triage actions, so existing question-aging tooling treats the new
    metadata combination as terminal without further changes.
    """

    def _append_event(self, event: dict) -> None:
        events_file = self.smm_dir / "events.jsonl"
        with events_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event) + "\n")

    def _append_question(self, content: str = "Some open question?") -> str:
        event = make_event("question", content=content)
        self._append_event(event)
        return event["id"]

    def _read_events(self) -> list[dict]:
        import _common

        return _common.read_events_raw(self.smm_dir)

    def test_won_fix_appends_status_event_with_correct_metadata(self):
        qid = self._append_question()
        result = run_cli(
            _CLI,
            [
                "question",
                "close",
                "--won-fix",
                "--event-id",
                qid,
                "--rationale",
                "No longer relevant to current direction",
            ],
            self.smm_dir,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        status_events = [e for e in self._read_events() if e.get("type") == "status"]
        self.assertEqual(len(status_events), 1)
        meta = status_events[0].get("metadata", {})
        self.assertEqual(meta.get("action"), "question_close")
        self.assertEqual(meta.get("disposition"), "wont_fix")
        self.assertEqual(meta.get("resolves"), [qid])

    def test_nonexistent_event_id_returns_nonzero_with_stderr(self):
        result = run_cli(
            _CLI,
            [
                "question",
                "close",
                "--won-fix",
                "--event-id",
                "deadbeef0000",
                "--rationale",
                "test",
            ],
            self.smm_dir,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("not found", result.stderr.lower())

    def test_already_resolved_question_is_noop(self):
        qid = self._append_question()
        first = run_cli(
            _CLI,
            [
                "question",
                "close",
                "--won-fix",
                "--event-id",
                qid,
                "--rationale",
                "first close",
            ],
            self.smm_dir,
        )
        self.assertEqual(first.returncode, 0, first.stderr)
        events_after_first = self._read_events()

        second = run_cli(
            _CLI,
            [
                "question",
                "close",
                "--won-fix",
                "--event-id",
                qid,
                "--rationale",
                "second attempt",
            ],
            self.smm_dir,
        )
        self.assertEqual(second.returncode, 0, second.stderr)
        events_after_second = self._read_events()

        # No additional resolving event was appended.
        resolving = [
            e
            for e in events_after_second
            if e.get("metadata", {}).get("resolves") == [qid]
        ]
        self.assertEqual(len(resolving), 1)
        # Total event count unchanged — events.jsonl uncorrupted.
        self.assertEqual(len(events_after_second), len(events_after_first))

    def test_non_question_event_id_rejected(self):
        # Pointing the closer at a status event (not a question) must error
        # with a type-mismatch message rather than silently appending a bogus
        # resolution. Covers the type-check guard in _cmd_question_close.
        status = make_event("status", content="not a question", working_on=[])
        self._append_event(status)
        result = run_cli(
            _CLI,
            [
                "question",
                "close",
                "--won-fix",
                "--event-id",
                status["id"],
                "--rationale",
                "should fail",
            ],
            self.smm_dir,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("question", result.stderr.lower())

    def test_e2e_aged_question_with_rationale(self):
        qid = self._append_question(content="Should we adopt approach X?")
        # Age the question with 3 unrelated events.
        for i in range(3):
            self._append_event(
                make_event("status", content=f"unrelated event {i}", working_on=[])
            )

        rationale = "Stale — superseded by recent direction"
        result = run_cli(
            _CLI,
            [
                "question",
                "close",
                "--won-fix",
                "--event-id",
                qid,
                "--rationale",
                rationale,
            ],
            self.smm_dir,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        close_events = [
            e
            for e in self._read_events()
            if e.get("type") == "status"
            and e.get("metadata", {}).get("disposition") == "wont_fix"
        ]
        self.assertEqual(len(close_events), 1)
        close = close_events[0]
        self.assertEqual(close["metadata"]["resolves"], [qid])
        self.assertEqual(close["metadata"]["action"], "question_close")
        self.assertIn(rationale, close.get("content", ""))


class TestRiskIdRendering(_SMMTestCase):
    """Risk entries should render with [id] suffix for discoverability."""

    def test_risk_entries_show_id(self):
        """Risk items render as '- content [id]'."""
        import smm_store
        from smm_schema import empty_smm

        data = empty_smm()
        data["risks"] = [
            {
                "id": "aaa111bbb222",
                "content": "Quality gate broken",
                "source": "curated",
                "ts": "2026-01-01T00:00:00+00:00",
                "type": "concern",
                "severity": "problem",
            }
        ]
        smm_store.save_smm(self.smm_dir, data)
        result = run_cli(_CLI, ["render"], self.smm_dir)
        self.assertIn("Quality gate broken [aaa111bbb222]", result.stdout)

    def test_constraint_entries_no_id(self):
        """Non-risk pillar entries should NOT show IDs."""
        import smm_store
        from smm_schema import empty_smm

        data = empty_smm()
        data["constraints"] = [
            {
                "id": "ccc333ddd444",
                "content": "Use Postgres",
                "source": "seed",
                "ts": "2026-01-01T00:00:00+00:00",
                "type": "decision",
            }
        ]
        smm_store.save_smm(self.smm_dir, data)
        result = run_cli(_CLI, ["render"], self.smm_dir)
        self.assertIn("- Use Postgres", result.stdout)
        self.assertNotIn("ccc333ddd444", result.stdout)


if __name__ == "__main__":
    unittest.main()
