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

Split at 565 lines: the `list-carryover` command itself is in
test_carryover_command.py. What stays here is the archive READER underneath it,
plus two adjacent guarantees on the same preload path — that the sprint counter
never regresses, and that the preload actually calls the reader rather than
reading the live file.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from _carryover_fixtures import _sprint_with
from conftest import _SMMTestCase


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
        found = sprint_archive.load_latest(self.smm_dir)
        assert found is not None
        archived_path, loaded = found
        self.assertTrue(archived_path.is_file(), "the path returned must exist")
        self.assertEqual(loaded["sprint_id"], "sprint-001")

    def test_newest_archive_wins(self):
        import sprint_archive

        for sid in ("sprint-001", "sprint-002", "sprint-003"):
            (self.smm_dir / "sprint.json").write_text(
                json.dumps(_sprint_with(("story-001", "done"), sprint_id=sid))
            )
            sprint_archive.archive(self.smm_dir)
        found = sprint_archive.load_latest(self.smm_dir)
        assert found is not None
        archived_path, loaded = found
        self.assertTrue(archived_path.is_file(), "the path returned must exist")
        self.assertEqual(
            loaded["sprint_id"],
            "sprint-003",
            "the most recently archived sprint is the previous one",
        )

    def test_an_unusable_newest_archive_raises_rather_than_falling_back(self):
        """REVERSED after review, and the reversal is the point.

        An earlier version skipped a corrupt newest archive and returned the one
        before it, reasoning that the alternative was carrying nothing forward.
        The real alternative is carrying the WRONG list: the review reproduced a
        truncated sprint-002 archive causing sprint-001's deferred story — one
        sprint-002 had already FINISHED — to be offered as carry-over, while
        sprint-002's actual leftover went unmentioned. Substituting older
        history silently is the failure this reader exists to prevent.
        """
        import sprint_archive

        (self.smm_dir / "sprint.json").write_text(
            json.dumps(_sprint_with(("story-007", "deferred")))
        )
        sprint_archive.archive(self.smm_dir)
        (self.smm_dir / "sprints" / "sprint_29991231T235959.json").write_text("{trunc")
        with self.assertRaises(sprint_archive.UnusableArchiveError):
            sprint_archive.load_latest(self.smm_dir)

    def test_no_archive_at_all_is_none_not_an_error(self):
        """The two outcomes must stay distinguishable: absent vs unusable."""
        import sprint_archive

        (self.smm_dir / "sprints").mkdir()
        self.assertIsNone(sprint_archive.load_latest(self.smm_dir))

    def test_a_json_object_that_is_not_a_sprint_is_unusable(self):
        """Parseable JSON is not the same as a usable sprint.

        `list_stories` indexes `sprint["stories"]` and `s["status"]`, so
        returning any old dict moves the failure downstream into a KeyError
        that the preload's `2>/dev/null` turns back into the silent empty list
        this whole fix exists to end. Schema-validate instead.
        """
        import sprint_archive

        (self.smm_dir / "sprints").mkdir()
        (self.smm_dir / "sprints" / "sprint_20260101T000000.json").write_text(
            json.dumps({"sprint_id": "sprint-999", "stories": [{"nope": True}]})
        )
        with self.assertRaises(sprint_archive.UnusableArchiveError):
            sprint_archive.load_latest(self.smm_dir)

    def test_stories_not_a_list_is_unusable(self):
        import sprint_archive

        (self.smm_dir / "sprints").mkdir()
        (self.smm_dir / "sprints" / "sprint_20260101T000000.json").write_text(
            json.dumps({"sprint_id": "sprint-001", "stories": "not-a-list"})
        )
        with self.assertRaises(sprint_archive.UnusableArchiveError):
            sprint_archive.load_latest(self.smm_dir)

    def test_a_stray_filename_never_outranks_a_real_archive(self):
        """`sprint_backup.json` sorts above `sprint_2026...` lexicographically.

        Verified in review: a hand-dropped backup was returned as the newest
        sprint, offering an ancient sprint's deferred stories and omitting the
        real ones. Order only among names archive_json actually writes.
        """
        import sprint_archive

        (self.smm_dir / "sprint.json").write_text(
            json.dumps(_sprint_with(("story-090", "deferred"), sprint_id="sprint-009"))
        )
        sprint_archive.archive(self.smm_dir)
        (self.smm_dir / "sprints" / "sprint_backup.json").write_text(
            json.dumps(_sprint_with(("story-001", "deferred")))
        )
        found = sprint_archive.load_latest(self.smm_dir)
        assert found is not None
        archived_path, loaded = found
        self.assertTrue(archived_path.is_file(), "the path returned must exist")
        self.assertEqual(loaded["sprint_id"], "sprint-009")

    def test_collision_suffix_orders_numerically(self):
        """`-10` is newer than `-9`, and both are newer than the unsuffixed."""
        import sprint_archive

        (self.smm_dir / "sprints").mkdir()
        for name, sid in (
            ("sprint_20260101T000000.json", "sprint-001"),
            ("sprint_20260101T000000-9.json", "sprint-009"),
            ("sprint_20260101T000000-10.json", "sprint-010"),
        ):
            (self.smm_dir / "sprints" / name).write_text(
                json.dumps(_sprint_with(("story-001", "done"), sprint_id=sid))
            )
        found = sprint_archive.load_latest(self.smm_dir)
        assert found is not None
        archived_path, loaded = found
        self.assertTrue(archived_path.is_file(), "the path returned must exist")
        self.assertEqual(loaded["sprint_id"], "sprint-010")

    def test_utf8_archive_reads_regardless_of_locale_default(self):
        """Pinned encoding: a locale-decoded read would raise UnicodeDecodeError
        (a ValueError) and read as corruption in a well-formed file."""
        import sprint_archive

        (self.smm_dir / "sprints").mkdir()
        sprint = _sprint_with(("story-001", "deferred"))
        sprint["stories"][0]["title"] = "Café — naïve résumé"
        (self.smm_dir / "sprints" / "sprint_20260101T000000.json").write_bytes(
            json.dumps(sprint, ensure_ascii=False).encode("utf-8")
        )
        found = sprint_archive.load_latest(self.smm_dir)
        assert found is not None
        archived_path, loaded = found
        self.assertTrue(archived_path.is_file(), "the path returned must exist")
        self.assertEqual(loaded["stories"][0]["title"], "Café — naïve résumé")


class TestCounterDoesNotRegressOnACorruptLiveSprint(_SMMTestCase):
    """Adjacent defect in the same preload path, found by the same review.

    `next_sprint_id` promises the counter can never regress, but it called
    `load_sprint` unguarded — and every caller wraps it in
    `|| echo "sprint-001"`. So a corrupt live sprint.json re-issued an id an
    archived sprint had already used, colliding sprint identity in metrics and
    in `_archived_sprint_ids`. It only became reachable here because
    list-carryover no longer aborts the preload first.
    """

    def test_archives_still_set_the_counter(self):
        import sprint_archive
        import sprint_metrics

        (self.smm_dir / "sprint.json").write_text(
            json.dumps(_sprint_with(("story-001", "done"), sprint_id="sprint-010"))
        )
        sprint_archive.archive(self.smm_dir)
        (self.smm_dir / "sprint.json").write_text("{ not json")
        self.assertEqual(sprint_metrics.next_sprint_id(self.smm_dir), "sprint-011")

    def test_a_symlinked_live_sprint_does_not_regress_the_counter(self):
        import sprint_archive
        import sprint_metrics

        (self.smm_dir / "sprint.json").write_text(
            json.dumps(_sprint_with(("story-001", "done"), sprint_id="sprint-007"))
        )
        sprint_archive.archive(self.smm_dir)
        real = self.smm_dir / "_real.json"
        real.write_text(json.dumps(_sprint_with(("story-001", "done"))))
        (self.smm_dir / "sprint.json").symlink_to(real)
        self.assertEqual(sprint_metrics.next_sprint_id(self.smm_dir), "sprint-008")


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
