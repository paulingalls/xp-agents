#!/usr/bin/env python3
"""Tests for resolves_probe.py — pure probe-candidate extraction module."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import unittest

import _common
import resolves_probe
from conftest import _HookTestCase, _ProbeTestHelpers, make_event
from event_schema import (
    METADATA_KEY_PROBE_CANDIDATES,
    STATUS_CONTENT_RESOLVES_PROBE,
)


class TestFindProbeCandidates(_HookTestCase):
    """find_probe_candidates returns open concerns matching commit files."""

    def _seed_concern(self, content: str, files: list[str]) -> str:
        concern = make_event("concern", content=content, files=files)
        _common.append_safe(self.smm_dir, concern)
        return concern["id"]

    def test_empty_commit_files_returns_empty(self):
        self._seed_concern("Auth leaks", ["scripts/auth.py"])
        result = resolves_probe.find_probe_candidates(
            self.smm_dir, [], [], cwd=str(self.smm_dir)
        )
        self.assertEqual(result, [])

    def test_no_matching_concerns_returns_empty(self):
        self._seed_concern("Other bug", ["scripts/foo.py"])
        result = resolves_probe.find_probe_candidates(
            self.smm_dir, ["README.md"], [], cwd=str(self.smm_dir)
        )
        self.assertEqual(result, [])

    def test_caps_at_five_candidates(self):
        cids = [
            self._seed_concern(f"Concern {i}", ["scripts/auth.py"]) for i in range(7)
        ]
        result = resolves_probe.find_probe_candidates(
            self.smm_dir, ["scripts/auth.py"], [], cwd=str(self.smm_dir)
        )
        self.assertEqual(len(result), 5)
        self.assertEqual([c["id"] for c in result], cids[:5])

    def test_filters_already_resolved_via_resolves_arg(self):
        cid_skip = self._seed_concern("Skip me", ["scripts/auth.py"])
        cid_keep = self._seed_concern("Keep me", ["scripts/auth.py"])
        result = resolves_probe.find_probe_candidates(
            self.smm_dir, ["scripts/auth.py"], [cid_skip], cwd=str(self.smm_dir)
        )
        ids = [c["id"] for c in result]
        self.assertIn(cid_keep, ids)
        self.assertNotIn(cid_skip, ids)


class TestBuildNudgeLines(unittest.TestCase):
    """build_nudge_lines formats auto-link nudge text for each candidate."""

    def test_empty_candidates_returns_empty_list(self):
        self.assertEqual(resolves_probe.build_nudge_lines([]), [])

    def test_nudge_includes_id_content_and_trailer(self):
        candidate = {"id": "abc123def456", "content": "Auth middleware leaks tokens"}
        lines = resolves_probe.build_nudge_lines([candidate])
        self.assertEqual(len(lines), 1)
        self.assertIn("abc123def456", lines[0])
        self.assertIn("Auth middleware leaks tokens", lines[0])
        self.assertIn("Resolves-Event: abc123def456", lines[0])

    def test_nudge_truncates_long_content_to_80_chars(self):
        long_content = "x" * 200
        candidate = {"id": "abc", "content": long_content}
        lines = resolves_probe.build_nudge_lines([candidate])
        # The content is sliced to 80 chars in the nudge text.
        self.assertIn("x" * 80, lines[0])
        self.assertNotIn("x" * 81, lines[0])

    def test_nudge_handles_missing_content(self):
        candidate = {"id": "abc", "content": None}
        lines = resolves_probe.build_nudge_lines([candidate])
        self.assertEqual(len(lines), 1)
        self.assertIn("abc", lines[0])

    def test_nudge_shows_debt_type_for_debt_events(self):
        candidate = {"id": "abc123def456", "type": "debt", "content": "Legacy code"}
        lines = resolves_probe.build_nudge_lines([candidate])
        self.assertIn("debt abc123def456", lines[0])
        self.assertNotIn("concern abc123def456", lines[0])

    def test_nudge_shows_concern_type_for_concern_events(self):
        candidate = {"id": "abc123def456", "type": "concern", "content": "Bug found"}
        lines = resolves_probe.build_nudge_lines([candidate])
        self.assertIn("concern abc123def456", lines[0])


class TestEmitProbeStatus(_ProbeTestHelpers, _HookTestCase):
    """emit_probe_status writes a probe status event to events.jsonl."""

    def test_no_event_when_no_candidates(self):
        resolves_probe.emit_probe_status(self.smm_dir, [], "agent")
        self.assertEqual(self._probes(), [])

    def test_event_written_when_candidates_exist(self):
        candidates = [
            {"id": "abc", "content": "first"},
            {"id": "def", "content": "second"},
        ]
        resolves_probe.emit_probe_status(self.smm_dir, candidates, "main")
        probes = self._probes()
        self.assertEqual(len(probes), 1)
        self.assertEqual(
            probes[0]["content"], f"{STATUS_CONTENT_RESOLVES_PROBE}: 2 candidates"
        )
        self.assertEqual(
            probes[0]["metadata"][METADATA_KEY_PROBE_CANDIDATES], ["abc", "def"]
        )


if __name__ == "__main__":
    unittest.main()
