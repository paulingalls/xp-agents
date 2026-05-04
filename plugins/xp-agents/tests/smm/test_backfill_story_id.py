#!/usr/bin/env python3
"""Tests for scripts/backfill_story_id.py.

One-shot reconciler for historical SMM events: when a `commit` event's
content carries a `[story-NNN]` Tier-0 prefix but `metadata.story_id`
is missing or set from the older file-overlap fallback, this script
writes the prefix value back. Future commits already get the right
attribution via bash_post_tool's _resolve_story_id Tier-0 logic; this
script corrects the pre-Tier-0 historical record.
"""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import backfill_story_id
from conftest import _SMMTestCase

# Explicit `from event_schema import EVENT_TYPE_*` so a future constant rename
# fails at test collection (NameError) instead of silently changing behavior.
from event_schema import EVENT_TYPE_COMMIT, EVENT_TYPE_STATUS


def _commit_event(content: str, story_id: str | None = None, **extra) -> dict:
    metadata = {
        "code_commit": True,
        "commit_hash": "deadbeef",
        "sprint_id": "sprint-001",
    }
    if story_id is not None:
        metadata["story_id"] = story_id
    metadata.update(extra)
    return {
        "id": "abcd1234",
        "ts": "2026-04-01T00:00:00+00:00",
        "type": EVENT_TYPE_COMMIT,
        "agent_id": "main",
        "schema_version": 1,
        "content": content,
        "files": [],
        "metadata": metadata,
    }


def _write_events(smm_dir: Path, events: list[dict]) -> None:
    (smm_dir / "events.jsonl").write_text(
        "\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8"
    )


def _read_events(smm_dir: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in (smm_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


class TestBackfillReconcile(_SMMTestCase):
    """reconcile() walks events.jsonl and reports/applies story_id fixes."""

    def test_dry_run_does_not_modify_events(self):
        events = [_commit_event("[story-001] Add foo")]
        _write_events(self.smm_dir, events)
        backfill_story_id.reconcile(self.smm_dir, apply=False)
        self.assertEqual(_read_events(self.smm_dir), events)

    def test_apply_sets_missing_story_id_from_prefix(self):
        events = [_commit_event("[story-003] Add foo")]
        _write_events(self.smm_dir, events)
        report = backfill_story_id.reconcile(self.smm_dir, apply=True)
        self.assertEqual(report.changed, 1)
        self.assertEqual(
            _read_events(self.smm_dir)[0]["metadata"]["story_id"], "story-003"
        )

    def test_apply_corrects_wrong_story_id_from_prefix(self):
        events = [_commit_event("[story-001] Refactor", story_id="story-002")]
        _write_events(self.smm_dir, events)
        report = backfill_story_id.reconcile(self.smm_dir, apply=True)
        self.assertEqual(report.changed, 1)
        self.assertEqual(
            _read_events(self.smm_dir)[0]["metadata"]["story_id"], "story-001"
        )

    def test_apply_leaves_matching_story_id_alone(self):
        events = [_commit_event("[story-001] Refactor", story_id="story-001")]
        _write_events(self.smm_dir, events)
        report = backfill_story_id.reconcile(self.smm_dir, apply=True)
        self.assertEqual(report.changed, 0)
        self.assertEqual(
            _read_events(self.smm_dir)[0]["metadata"]["story_id"], "story-001"
        )

    def test_apply_skips_commits_without_prefix(self):
        events = [_commit_event("Tidy up tests")]
        _write_events(self.smm_dir, events)
        report = backfill_story_id.reconcile(self.smm_dir, apply=True)
        self.assertEqual(report.changed, 0)
        self.assertNotIn("story_id", _read_events(self.smm_dir)[0]["metadata"])

    def test_apply_ignores_non_commit_events(self):
        events = [
            {
                "id": "x",
                "ts": "2026-04-01T00:00:00+00:00",
                "type": EVENT_TYPE_STATUS,
                "agent_id": "main",
                "schema_version": 1,
                "content": "[story-001] Working on it",
                "metadata": {},
                "working_on": [],
            }
        ]
        _write_events(self.smm_dir, events)
        report = backfill_story_id.reconcile(self.smm_dir, apply=True)
        self.assertEqual(report.changed, 0)
        # No story_id sneaks in on a non-commit event.
        self.assertEqual(
            _read_events(self.smm_dir)[0].get("metadata", {}).get("story_id"), None
        )

    def test_report_counts_examined_and_with_prefix(self):
        events = [
            _commit_event("[story-001] One"),
            _commit_event("Two"),
            _commit_event("[story-002] Three", story_id="story-002"),
        ]
        _write_events(self.smm_dir, events)
        report = backfill_story_id.reconcile(self.smm_dir, apply=False)
        self.assertEqual(report.commits, 3)
        self.assertEqual(report.with_prefix, 2)
        self.assertEqual(report.changed, 1)

    def test_apply_preserves_other_metadata_fields(self):
        events = [
            _commit_event(
                "[story-001] Add foo",
                story_id="story-002",
                code_file_count=5,
                resolves=["abc123"],
            )
        ]
        _write_events(self.smm_dir, events)
        backfill_story_id.reconcile(self.smm_dir, apply=True)
        meta = _read_events(self.smm_dir)[0]["metadata"]
        self.assertEqual(meta["story_id"], "story-001")
        self.assertEqual(meta["code_file_count"], 5)
        self.assertEqual(meta["resolves"], ["abc123"])
        self.assertEqual(meta["sprint_id"], "sprint-001")


if __name__ == "__main__":
    unittest.main()
