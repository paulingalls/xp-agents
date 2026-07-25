#!/usr/bin/env python3
"""Tests for _common.py — SMM read/write persistence and safety.

Split from test_common.py (pure move, no test-body edits). Covers
load_events_with_resolutions, bulk_append_safe (valid/invalid filtering),
write_json_atomic symlink rejection, and get_validated_smm_dir.
Sibling groups: hook I/O (test_common_io.py), stdlib import policy
(test_common_stdlib.py), event/arg bookkeeping (test_common_events.py).
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import _common
from conftest import _HookTestCase, make_event

# Explicit `from event_schema import EVENT_TYPE_*` so a future constant rename
# fails at test collection (NameError) instead of silently changing a
# make_event(...) call's behavior.
from event_schema import (
    EVENT_TYPE_CONCERN,
    EVENT_TYPE_STATUS,
)


class TestLoadEventsWithResolutions(_HookTestCase):
    def test_returns_events_and_resolutions_tuple(self):
        self._write_events(
            [
                make_event(EVENT_TYPE_CONCERN, content="bug found"),
                make_event(EVENT_TYPE_STATUS, content="working"),
            ]
        )
        events, resolutions = _common.load_events_with_resolutions(self.smm_dir)
        self.assertEqual(len(events), 2)
        self.assertIsInstance(resolutions, dict)
        self.assertIn("resolved_concern_ids", resolutions)
        self.assertIn("answered_question_ids", resolutions)

    def test_empty_smm_returns_empty(self):
        events, resolutions = _common.load_events_with_resolutions(self.smm_dir)
        self.assertEqual(events, [])
        self.assertIsInstance(resolutions, dict)

    def test_resolutions_reflect_resolved_concerns(self):
        concern = make_event(EVENT_TYPE_CONCERN, content="test fail")
        resolver = make_event(
            EVENT_TYPE_STATUS, content="fixed", metadata={"resolves": [concern["id"]]}
        )
        self._write_events([concern, resolver])
        _events, resolutions = _common.load_events_with_resolutions(self.smm_dir)
        self.assertIn(concern["id"], resolutions["resolved_concern_ids"])


class TestBulkAppendSafe(_HookTestCase):
    """Tests for _common.bulk_append_safe()."""

    def test_bulk_append_safe_skips_invalid(self):
        """Invalid events filtered, valid ones written."""
        good = make_event(EVENT_TYPE_STATUS, content="OK", working_on=[])
        bad = {"type": EVENT_TYPE_STATUS, "content": "no id"}
        _common.bulk_append_safe(self.smm_dir, [good, bad])
        events = self._read_events()
        # Only valid event written
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["id"], good["id"])

    def test_bulk_append_safe_all_valid(self):
        """All valid events should be written."""
        events_in = [
            make_event(EVENT_TYPE_STATUS, content=f"S{i}", working_on=[])
            for i in range(3)
        ]
        _common.bulk_append_safe(self.smm_dir, events_in)
        events = self._read_events()
        self.assertEqual(len(events), 3)

    def test_bulk_append_safe_empty(self):
        """Empty list should be a no-op."""
        _common.bulk_append_safe(self.smm_dir, [])
        events = self._read_events()
        self.assertEqual(len(events), 0)


class TestWriteJsonAtomicSecurity(_HookTestCase):
    """Security tests for _common.write_json_atomic()."""

    def test_rejects_symlink_target(self):
        target = self.smm_dir / "real-file.json"
        target.write_text("{}")
        link = self.smm_dir / "link.json"
        link.symlink_to(target)
        with self.assertRaises(ValueError):
            _common.write_json_atomic(link, {"evil": True})
        # Original file should be unchanged
        self.assertEqual(target.read_text(), "{}")


class TestGetValidatedSMMDir(_HookTestCase):
    """M13: get_validated_smm_dir combines resolve + validate."""

    def test_valid_smm_dir_returned(self):
        """Explicit valid smm_dir is returned as-is."""
        result = _common.get_validated_smm_dir(self.smm_dir)
        self.assertEqual(result, self.smm_dir)

    def test_invalid_path_returns_none(self):
        """Invalid path returns None."""
        result = _common.get_validated_smm_dir(Path("/nonexistent/smm"))
        self.assertIsNone(result)

    def test_none_input_propagates_unresolvable_as_none(self):
        """When resolution fails (no git repo), the composition returns None.

        Patches resolve_smm_dir rather than manipulating the data-root env:
        _SMMTestCase.setUp pins SMM_DIR, which short-circuits resolution
        before any data root is consulted, so an env-based version of this
        test asserts nothing. `resolve_smm_dir` returning None outside a git
        repo is covered directly by
        test_append_safety.TestResolveSmmDir.test_returns_none_when_not_in_git_repo.
        """
        with patch.object(_common, "resolve_smm_dir", return_value=None):
            self.assertIsNone(_common.get_validated_smm_dir(None))

    def test_none_input_validates_the_resolved_dir(self):
        """A resolved-but-invalid dir must not slip through unvalidated."""
        with patch.object(
            _common, "resolve_smm_dir", return_value=Path("/nonexistent/smm")
        ):
            self.assertIsNone(_common.get_validated_smm_dir(None))


if __name__ == "__main__":
    unittest.main()
