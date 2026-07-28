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
        loaded = sprint_archive.load_latest(self.smm_dir)
        assert loaded is not None
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
        loaded = sprint_archive.load_latest(self.smm_dir)
        assert loaded is not None
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
        loaded = sprint_archive.load_latest(self.smm_dir)
        assert loaded is not None
        self.assertEqual(loaded["stories"][0]["title"], "Café — naïve résumé")


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

    def test_a_symlinked_live_sprint_does_not_reach_the_archive(self):
        """`store.sprint_exists` reports a symlink as ABSENT — it is a refusal,
        not a probe — so keying on it sent a symlinked-but-VALID sprint down the
        archive branch. Review reproduced it: sprint-001's deferred story-014
        offered as carry-over while the symlinked sprint-002 was already
        executing it, i.e. duplicate work under two ids.
        """
        import sprint_archive

        (self.smm_dir / "sprint.json").write_text(
            json.dumps(_sprint_with(("story-014", "deferred")))
        )
        sprint_archive.archive(self.smm_dir)
        real = self.smm_dir / "_real_sprint.json"
        real.write_text(
            json.dumps(_sprint_with(("story-030", "ready"), sprint_id="sprint-002"))
        )
        (self.smm_dir / "sprint.json").symlink_to(real)
        rc, out = self._run()
        self.assertEqual(rc, 0)
        self.assertNotIn(
            "story-014",
            out,
            "a present-but-symlinked sprint.json must not fall through to the archive",
        )
        self.assertIn("WARNING:", out)

    def test_an_unusable_archive_warns_on_stdout(self):
        """The advisory must reach the preload, which discards stderr.

        Review confirmed a stderr-only warning reached nobody: the helper runs
        under `2>/dev/null`, so the customer saw an empty carry-over list with
        no signal — the same silence, through a different door.
        """
        (self.smm_dir / "sprints").mkdir()
        (self.smm_dir / "sprints" / "sprint_20260101T000000.json").write_text("{trunc")
        rc, out = self._run()
        self.assertEqual(rc, 0)
        self.assertIn("WARNING:", out)
        self.assertIn("not", out.lower())

    def test_a_newline_in_a_title_cannot_forge_a_line(self):
        """`story.title` is only schema-checked as `str` and is LLM-authored.

        An unsanitised newline both inflated the caller's line count and let a
        title inject its own `KEY=value` preload line — the hazard `emit_var`
        exists to stop for customer-set values.
        """
        (self.smm_dir / "sprint.json").write_text(
            json.dumps(
                _make_sprint(
                    stories=[
                        _make_story(
                            id="story-002",
                            title="Fix login\nNEXT_SPRINT_ID=sprint-999",
                            status="deferred",
                        )
                    ]
                )
            )
        )
        rc, out = self._run()
        self.assertEqual(rc, 0)
        story_lines = [ln for ln in out.splitlines() if ln.startswith("story-")]
        self.assertEqual(len(story_lines), 1, "one story must be exactly one line")
        self.assertNotIn(
            "\nNEXT_SPRINT_ID=", out, "a title must not forge a preload variable"
        )

    def test_the_source_of_the_full_definitions_is_named(self):
        """Carry-over needs each story's acceptance criteria and file_domain, and
        render-stories/get-story both read the live file and fail once it is
        archived. Without the path the skill fabricates both.
        """
        import sprint_archive

        (self.smm_dir / "sprint.json").write_text(
            json.dumps(_sprint_with(("story-014", "deferred")))
        )
        archived = sprint_archive.archive(self.smm_dir)
        assert archived is not None
        rc, out = self._run()
        self.assertEqual(rc, 0)
        self.assertIn(f"SOURCE: {archived}", out)

    def test_a_corrupt_live_sprint_does_not_traceback(self):
        """`store.load_sprint` RAISES on a corrupt or symlinked sprint.json.

        Unguarded, that traceback reaches the preload helper's `2>/dev/null`
        and becomes an empty carry-over list with nothing said — the same
        silence as the bug. Exit 0, no STORY lines, and a warning that survives
        into the preload's context (stdout, not stderr alone — see
        `_warn_carryover`).
        """
        (self.smm_dir / "sprint.json").write_text("{ not json")
        rc, out = self._run()
        self.assertEqual(rc, 0)
        self.assertEqual(
            [ln for ln in out.splitlines() if ln.startswith("story-")],
            [],
            "nothing may be carried forward from a sprint that cannot be read",
        )
        self.assertIn("WARNING:", out)

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
