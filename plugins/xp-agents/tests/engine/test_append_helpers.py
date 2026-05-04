#!/usr/bin/env python3
"""Tests for _append_impl helper functions: bulk append, atomic writes, build_event.

Split from test_curation.py — covers TestBulkAppend, TestWriteAtomic,
TestBuildEvent, TestStripAnsi, TestReplaceEventsFile.
"""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))
import _append_impl
from conftest import _SMMTestCase, make_event
from event_schema import EVENT_TYPE_CUSTOMER_INPUT, EVENT_TYPE_STATUS


class TestBulkAppend(_SMMTestCase):
    """Tests for bulk_append() — multi-event atomic writes."""

    def test_bulk_append_empty_noop(self):
        """Empty list should not touch events.jsonl or acquire lock."""
        _append_impl.bulk_append(self.smm_dir, [])
        content = (self.smm_dir / "events.jsonl").read_text()
        self.assertEqual(content, "")

    def test_bulk_append_multiple_events(self):
        """Three valid events should all appear in events.jsonl."""
        events = [
            make_event(EVENT_TYPE_STATUS, content=f"Status {i}", working_on=[])
            for i in range(3)
        ]
        _append_impl.bulk_append(self.smm_dir, events)
        lines = (self.smm_dir / "events.jsonl").read_text().strip().split("\n")
        self.assertEqual(len(lines), 3)
        for i, line in enumerate(lines):
            parsed = json.loads(line)
            self.assertEqual(parsed["id"], events[i]["id"])

    def test_bulk_append_strips_ansi(self):
        """ANSI escape codes should be stripped from content."""
        event = make_event(
            EVENT_TYPE_STATUS,
            content="\x1b[31mRed text\x1b[0m",
            working_on=[],
        )
        _append_impl.bulk_append(self.smm_dir, [event])
        lines = (self.smm_dir / "events.jsonl").read_text().strip().split("\n")
        parsed = json.loads(lines[0])
        self.assertEqual(parsed["content"], "Red text")

    def test_bulk_append_validates_all_before_write(self):
        """If any event is invalid, none should be written."""
        good = make_event(EVENT_TYPE_STATUS, content="OK", working_on=[])
        bad = {"type": EVENT_TYPE_STATUS, "content": "no id"}  # missing required fields
        with self.assertRaises(ValueError):
            _append_impl.bulk_append(self.smm_dir, [good, bad])
        content = (self.smm_dir / "events.jsonl").read_text()
        self.assertEqual(content, "")

    def test_bulk_append_rejects_over_budget(self):
        """Over-budget event should raise ValueError, no events written."""
        over = make_event(EVENT_TYPE_STATUS, content="x" * 201, working_on=[])
        with self.assertRaises(ValueError) as ctx:
            _append_impl.bulk_append(self.smm_dir, [over])
        self.assertIn("budget", str(ctx.exception).lower())
        content = (self.smm_dir / "events.jsonl").read_text()
        self.assertEqual(content, "")

    def test_bulk_append_appends_to_existing(self):
        """bulk_append should append, not overwrite existing events."""
        existing = make_event(EVENT_TYPE_CUSTOMER_INPUT, content="First")
        _append_impl.append_event(self.smm_dir, existing)
        new_events = [
            make_event(EVENT_TYPE_STATUS, content="Second", working_on=[]),
        ]
        _append_impl.bulk_append(self.smm_dir, new_events)
        lines = (self.smm_dir / "events.jsonl").read_text().strip().split("\n")
        self.assertEqual(len(lines), 2)


class TestWriteAtomic(_SMMTestCase):
    """Tests for _append_impl.write_text_atomic() and write_json_atomic()."""

    def test_write_text_creates_file(self):
        """write_text_atomic creates a new file with expected content."""
        target = self.smm_dir / "hello.txt"
        _append_impl.write_text_atomic(target, "hello world")
        self.assertEqual(target.read_text(), "hello world")

    def test_write_text_overwrites(self):
        """write_text_atomic overwrites existing file with latest content."""
        target = self.smm_dir / "overwrite.txt"
        _append_impl.write_text_atomic(target, "first")
        _append_impl.write_text_atomic(target, "second")
        self.assertEqual(target.read_text(), "second")

    def test_write_text_permissions(self):
        """write_text_atomic sets file permissions to 0o600."""
        target = self.smm_dir / "perms.txt"
        _append_impl.write_text_atomic(target, "secret")
        mode = target.stat().st_mode & 0o777
        self.assertEqual(mode, 0o600)

    def test_write_text_no_temp_files(self):
        """write_text_atomic leaves no .tmp files behind."""
        target = self.smm_dir / "clean.txt"
        _append_impl.write_text_atomic(target, "data")
        tmp_files = list(self.smm_dir.glob("*.tmp"))
        self.assertEqual(tmp_files, [])

    def test_write_json_roundtrip(self):
        """write_json_atomic writes JSON that round-trips correctly."""
        target = self.smm_dir / "data.json"
        data = {"key": "value", "count": 42, "nested": {"a": [1, 2, 3]}}
        _append_impl.write_json_atomic(target, data)
        loaded = json.loads(target.read_text())
        self.assertEqual(loaded, data)


class TestBuildEvent(_SMMTestCase):
    """Tests for _append_impl.build_event."""

    def _namespace(self, **kwargs):
        import argparse

        defaults = {
            "type": EVENT_TYPE_STATUS,
            "agent": "main",
            "content": "test",
            "references": None,
            "metadata": None,
            "working_on": None,
            "topic": None,
            "priority": None,
            "severity": None,
            "files": None,
            "intent_status": None,
            "duration_seconds": None,
            "event_count": None,
            "unresolved_items": None,
            "keep": None,
            "fix": None,
            "try_items": None,
        }
        defaults.update(kwargs)
        return argparse.Namespace(**defaults)

    def test_basic_fields(self):
        event = _append_impl.build_event(self._namespace())
        self.assertEqual(event["type"], "status")
        self.assertEqual(event["agent_id"], "main")
        self.assertEqual(event["content"], "test")
        self.assertIn("id", event)
        self.assertIn("ts", event)

    def test_status_defaults_working_on(self):
        event = _append_impl.build_event(self._namespace(type="status"))
        self.assertEqual(event["working_on"], [])

    def test_decision_includes_topic(self):
        event = _append_impl.build_event(self._namespace(type="decision", topic="auth"))
        self.assertEqual(event["topic"], "auth")

    def test_concern_includes_severity(self):
        event = _append_impl.build_event(
            self._namespace(type="concern", severity="high")
        )
        self.assertEqual(event["severity"], "high")

    def test_concern_includes_files(self):
        event = _append_impl.build_event(
            self._namespace(type="concern", files='["scripts/foo.py"]')
        )
        self.assertEqual(event["files"], ["scripts/foo.py"])

    def test_concern_files_omitted_when_unset(self):
        event = _append_impl.build_event(self._namespace(type="concern"))
        self.assertNotIn("files", event)

    def test_concern_auto_extract_simple_filename(self):
        event = _append_impl.build_event(
            self._namespace(type="concern", content="broken in foo.py at line 10")
        )
        self.assertEqual(event["files"], ["foo.py"])

    def test_concern_auto_extract_path(self):
        event = _append_impl.build_event(
            self._namespace(type="concern", content="scripts/bar.py:42 leaks")
        )
        self.assertEqual(event["files"], ["scripts/bar.py"])

    def test_concern_auto_extract_dedupes_and_preserves_order(self):
        event = _append_impl.build_event(
            self._namespace(
                type="concern",
                content="touch a.py then b.md then a.py again",
            )
        )
        self.assertEqual(event["files"], ["a.py", "b.md"])

    def test_concern_explicit_files_wins_over_extract(self):
        event = _append_impl.build_event(
            self._namespace(
                type="concern",
                content="see baz.py for context",
                files='["other.py"]',
            )
        )
        self.assertEqual(event["files"], ["other.py"])

    def test_concern_no_paths_in_content_omits_files(self):
        event = _append_impl.build_event(
            self._namespace(type="concern", content="general design issue")
        )
        self.assertNotIn("files", event)

    def test_concern_auto_extract_captures_leading_slash_absolute_path(self):
        # Per close-reviewer concern 78ab5a70ca1b: `\b` at the regex start
        # was dropping the leading `/` from absolute paths, leaving the
        # downstream worktree.normalize_path resolving against cwd and
        # missing the actual target. Fixed via `(?<![\w/])` lookbehind.
        event = _append_impl.build_event(
            self._namespace(
                type="concern", content="leak in /abs/repo/scripts/auth.py:42"
            )
        )
        self.assertEqual(event["files"], ["/abs/repo/scripts/auth.py"])

    def test_concern_auto_extract_recognizes_non_python_extensions(self):
        # Per close-reviewer concern 87e022ad0693: the original pattern
        # only matched .py/.md/.sh/.json/.yaml/.yml/.toml/.jsonl —
        # near-zero recall for projects in JS/TS/Rust/Go/Ruby/etc. Pin a
        # representative sample of the expanded alternation so a future
        # narrowing fails loudly.
        event = _append_impl.build_event(
            self._namespace(
                type="concern",
                content="auth.ts:10 leaks; see also lib/foo.rs and main.go",
            )
        )
        self.assertEqual(event["files"], ["auth.ts", "lib/foo.rs", "main.go"])

    def test_concern_skips_paths_inside_urls(self):
        event = _append_impl.build_event(
            self._namespace(
                type="concern",
                content="see https://example.com/docs/page.py and e.g. context",
            )
        )
        self.assertNotIn("files", event)

    def test_metadata_parsed(self):
        event = _append_impl.build_event(
            self._namespace(metadata='{"notes": "from plan review"}')
        )
        self.assertEqual(event["metadata"], {"notes": "from plan review"})


class TestStripAnsi(_SMMTestCase):
    """Tests for _append_impl._strip_ansi."""

    def test_strips_color_codes(self):
        result = _append_impl._strip_ansi("\033[31mred\033[0m")
        self.assertEqual(result, "red")

    def test_strips_bold(self):
        result = _append_impl._strip_ansi("\033[1mbold\033[0m")
        self.assertEqual(result, "bold")

    def test_passthrough_plain(self):
        result = _append_impl._strip_ansi("no ansi here")
        self.assertEqual(result, "no ansi here")

    def test_empty_string(self):
        result = _append_impl._strip_ansi("")
        self.assertEqual(result, "")


class TestReplaceEventsFile(_SMMTestCase):
    """Tests for _append_impl.replace_events_file."""

    def test_replaces_content(self):
        # Seed initial events
        e1 = make_event(EVENT_TYPE_STATUS, content="old")
        _append_impl.append_event(self.smm_dir, e1)

        # Replace with new events
        e2 = make_event(EVENT_TYPE_STATUS, content="new")
        original = _append_impl.replace_events_file(self.smm_dir, [e2])

        # Original content returned
        self.assertIn("old", original)

        # File now contains only new event
        content = (self.smm_dir / "events.jsonl").read_text()
        self.assertIn("new", content)
        self.assertNotIn("old", content)

    def test_returns_empty_for_missing_file(self):
        e = make_event(EVENT_TYPE_STATUS, content="first")
        original = _append_impl.replace_events_file(self.smm_dir, [e])
        self.assertEqual(original, "")

    def test_atomic_replacement(self):
        """File should contain exactly the replacement events."""
        events = [make_event(EVENT_TYPE_STATUS, content=f"item-{i}") for i in range(3)]
        _append_impl.replace_events_file(self.smm_dir, events)
        lines = (self.smm_dir / "events.jsonl").read_text().strip().split("\n")
        self.assertEqual(len(lines), 3)


if __name__ == "__main__":
    unittest.main()
