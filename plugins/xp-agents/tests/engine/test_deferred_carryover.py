#!/usr/bin/env python3
"""Deferred stories must survive sprint-close's archive.

`/xp-sprint-close --archive-sprint` MOVES sprint.json into sprints/, and
`/xp-sprint-start`'s preload read its deferred stories from that live file — so
between those two skills the carry-over list was empty, and sprint-start's own
instruction ("Include deferred stories from the previous sprint, renumbered")
had no data behind it. Verified against the real close: 4 deferred before the
archive, 0 after.

The fallback is deliberately narrow: it fires ONLY when sprint.json is absent.
Once a new sprint exists, the live file is authoritative and a resurrected
carry-over list would re-offer stories the new sprint already took on.
"""

import argparse
import json
import sys
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from _cli_helpers import make_story_dict as _make_story
from conftest import _SMMTestCase
from conftest import make_sprint_dict as _make_sprint


def _sprint_with(*status_pairs: tuple[str, str], sprint_id: str = "sprint-001") -> dict:
    """A sprint whose stories are (id, status) — titles derived from the id."""
    return _make_sprint(
        sprint_id=sprint_id,
        stories=[
            _make_story(id=sid, title=f"Work for {sid}", status=status)
            for sid, status in status_pairs
        ],
    )


class TestLatestArchivedSprint(_SMMTestCase):
    def test_no_sprints_dir_returns_none(self):
        import sprint_archive

        self.assertIsNone(sprint_archive.load_latest(self.smm_dir))

    def test_reads_the_only_archive(self):
        import sprint_archive

        (self.smm_dir / "sprint.json").write_text(
            json.dumps(_sprint_with(("story-001", "deferred")))
        )
        sprint_archive.archive(self.smm_dir)
        loaded = sprint_archive.load_latest(self.smm_dir)
        assert loaded is not None
        self.assertEqual(loaded["sprint_id"], "sprint-001")

    def test_newest_archive_wins(self):
        import sprint_archive

        for sid in ("sprint-001", "sprint-002", "sprint-003"):
            (self.smm_dir / "sprint.json").write_text(
                json.dumps(_sprint_with(("story-001", "done"), sprint_id=sid))
            )
            sprint_archive.archive(self.smm_dir)
        loaded = sprint_archive.load_latest(self.smm_dir)
        assert loaded is not None
        self.assertEqual(
            loaded["sprint_id"],
            "sprint-003",
            "the most recently archived sprint is the previous one",
        )

    def test_malformed_archive_is_skipped_for_a_readable_older_one(self):
        """A truncated newest archive must not hide a readable predecessor.

        archive_json clears its O_EXCL claim on a failed move, but a tree that
        was interrupted some other way can still hold a 0-byte or partial file,
        and returning None there would silently lose a carry-over list that IS
        on disk.
        """
        import sprint_archive

        (self.smm_dir / "sprint.json").write_text(
            json.dumps(_sprint_with(("story-007", "deferred")))
        )
        sprint_archive.archive(self.smm_dir)
        (self.smm_dir / "sprints" / "sprint_29991231T235959.json").write_text("{trunc")
        loaded = sprint_archive.load_latest(self.smm_dir)
        assert loaded is not None
        self.assertEqual(loaded["sprint_id"], "sprint-001")

    def test_all_archives_malformed_returns_none(self):
        import sprint_archive

        (self.smm_dir / "sprints").mkdir()
        (self.smm_dir / "sprints" / "sprint_20260101T000000.json").write_text("nope")
        self.assertIsNone(sprint_archive.load_latest(self.smm_dir))

    def test_a_json_object_that_is_not_a_sprint_is_skipped(self):
        """Parseable JSON is not the same as a usable sprint.

        `list_stories` indexes `sprint["stories"]` and `s["status"]`, so
        returning any old dict here moves the failure downstream into a
        KeyError that the preload's `2>/dev/null` turns back into the silent
        empty list this whole fix exists to end. Schema-validate instead.
        """
        import sprint_archive

        (self.smm_dir / "sprint.json").write_text(
            json.dumps(_sprint_with(("story-005", "deferred")))
        )
        sprint_archive.archive(self.smm_dir)
        (self.smm_dir / "sprints" / "sprint_29991231T235959.json").write_text(
            json.dumps({"sprint_id": "sprint-999", "stories": [{"nope": True}]})
        )
        loaded = sprint_archive.load_latest(self.smm_dir)
        assert loaded is not None
        self.assertEqual(
            loaded["sprint_id"],
            "sprint-001",
            "a schema-invalid newest archive must not hide a valid predecessor",
        )

    def test_stories_not_a_list_is_skipped(self):
        import sprint_archive

        (self.smm_dir / "sprints").mkdir()
        (self.smm_dir / "sprints" / "sprint_20260101T000000.json").write_text(
            json.dumps({"sprint_id": "sprint-001", "stories": "not-a-list"})
        )
        self.assertIsNone(sprint_archive.load_latest(self.smm_dir))


class TestCarryoverCommand(_SMMTestCase):
    """`sprint_cli.py list-carryover` — the single reader the preload uses."""

    def _run(self) -> tuple[int, str]:
        """Exit code and stdout of `list-carryover` against this test's SMM."""
        import sprint_cli_query

        buf = StringIO()
        with redirect_stdout(buf):
            rc = sprint_cli_query._cmd_list_carryover(
                argparse.Namespace(smm_dir=self.smm_dir)
            )
        return rc, buf.getvalue()

    def test_live_sprint_deferred_stories_are_listed(self):
        (self.smm_dir / "sprint.json").write_text(
            json.dumps(
                _sprint_with(
                    ("story-001", "done"),
                    ("story-002", "deferred"),
                    ("story-003", "deferred"),
                )
            )
        )
        rc, out = self._run()
        self.assertEqual(rc, 0)
        self.assertIn("story-002", out)
        self.assertIn("story-003", out)
        self.assertNotIn("story-001", out)

    def test_deferred_survive_the_archive(self):
        """THE BUG: this is empty before the fix and correct after."""
        import sprint_archive

        (self.smm_dir / "sprint.json").write_text(
            json.dumps(
                _sprint_with(
                    ("story-014", "deferred"),
                    ("story-016", "deferred"),
                    ("story-015", "done"),
                )
            )
        )
        sprint_archive.archive(self.smm_dir)
        self.assertFalse((self.smm_dir / "sprint.json").exists())
        rc, out = self._run()
        self.assertEqual(rc, 0)
        self.assertIn("story-014", out)
        self.assertIn("story-016", out)
        self.assertNotIn("story-015", out)

    def test_a_live_sprint_shadows_the_archive(self):
        """The narrowing that stops a carried story being offered twice."""
        import sprint_archive

        (self.smm_dir / "sprint.json").write_text(
            json.dumps(_sprint_with(("story-014", "deferred")))
        )
        sprint_archive.archive(self.smm_dir)
        (self.smm_dir / "sprint.json").write_text(
            json.dumps(_sprint_with(("story-020", "ready"), sprint_id="sprint-002"))
        )
        rc, out = self._run()
        self.assertEqual(rc, 0)
        self.assertNotIn(
            "story-014",
            out,
            "sprint-002 already exists; its own list is authoritative",
        )

    def test_no_sprint_and_no_archive_is_silent_and_green(self):
        rc, out = self._run()
        self.assertEqual(rc, 0, "a first-ever sprint-start must not see an error")
        self.assertEqual(out.strip(), "")

    def test_a_corrupt_live_sprint_does_not_traceback(self):
        """`store.load_sprint` RAISES on a corrupt or symlinked sprint.json.

        Unguarded, that traceback reaches the preload helper's `2>/dev/null`
        and becomes an empty carry-over list with nothing said — the same
        silence as the bug. Exit 0 with no stdout, and say why on stderr.
        """
        (self.smm_dir / "sprint.json").write_text("{ not json")
        rc, out = self._run()
        self.assertEqual(rc, 0)
        self.assertEqual(out.strip(), "")

    def test_a_corrupt_live_sprint_does_not_fall_back_to_the_archive(self):
        """Absence is the trigger, not unreadability.

        Falling back here would print a PREVIOUS sprint's deferred stories
        while the current sprint.json is merely damaged — inventing carry-over
        for a sprint that may already have taken those stories on.
        """
        import sprint_archive

        (self.smm_dir / "sprint.json").write_text(
            json.dumps(_sprint_with(("story-014", "deferred")))
        )
        sprint_archive.archive(self.smm_dir)
        (self.smm_dir / "sprint.json").write_text("{ not json")
        rc, out = self._run()
        self.assertEqual(rc, 0)
        self.assertNotIn("story-014", out)

    def test_archived_sprint_with_no_deferred_prints_nothing(self):
        import sprint_archive

        (self.smm_dir / "sprint.json").write_text(
            json.dumps(_sprint_with(("story-001", "done")))
        )
        sprint_archive.archive(self.smm_dir)
        rc, out = self._run()
        self.assertEqual(rc, 0)
        self.assertEqual(out.strip(), "")


class TestPreloadUsesTheCarryoverReader(_SMMTestCase):
    """The preload must not read carry-over from the live file any more."""

    def test_preload_calls_list_carryover(self):
        skills = Path(__file__).parent.parent.parent / "skills"
        preload = (skills / "xp-sprint-start/scripts/preload.sh").read_text()
        base = (skills / "_preload_base.sh").read_text()

        self.assertIn("sprint_list_carryover", preload)
        self.assertNotIn(
            "sprint_count_status deferred",
            preload,
            "reading the live file is the bug; the archive-aware reader replaces it",
        )
        self.assertNotIn(
            "sprint_list_stories --status deferred",
            preload,
            "the live-file list is the other half of the same bug",
        )
        # Both halves, or the helper name could drift off the CLI command it
        # is supposed to reach and the preload would silently emit nothing.
        self.assertIn("sprint_list_carryover()", base)
        self.assertIn("list-carryover", base)
