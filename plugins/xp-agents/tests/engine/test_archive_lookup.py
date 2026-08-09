#!/usr/bin/env python3
"""Resolving an event that compaction moved into `backups/`.

`archive.py` states the invariant this rests on: the file under `backups/` is
not a convenience copy, it is the ONLY copy of what was removed. An event id
stays citable forever — later events reference it in `references` and
`metadata.resolves` — so a lookup that stops at the live log reports DELETION
where there was only relocation.

That gap produced an hour of wrong diagnosis and two retracted events in this
project's own log: `get-event` said "not found" for an id sitting in
`backups/archive-20260808T235557.jsonl`, and the absence was read as a silent
write failure in the CLI that had in fact written it correctly.

Two properties below are not stylistic:

  * ORDER IS BY MTIME, not by filename. `backups/` mixes `archive-*`,
    legacy `events-*` and `pre-repair-*`, plus `-N` collision suffixes, so a
    lexical sort is not chronological. A pre-repair backup is a whole-file
    copy, so one id genuinely lives in several archives and the order decides
    which version a reader gets.
  * PARSING IS TOLERANT. Repair archives hold malformed lines BY
    CONSTRUCTION — dropping them is why the backup exists — so a per-line
    `json.loads` would raise on exactly the files most likely to hold a
    recovered id.
"""

import json
import os
import subprocess
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import archive
from conftest import _SMMTestCase


def _event(event_id: str, content: str = "archived decision") -> dict:
    return {
        "id": event_id,
        "ts": "2026-08-08T22:23:28.508514+00:00",
        "type": "decision",
        "agent_id": "main",
        "content": content,
        "topic": "retro-try-one-slug-per-subject",
    }


class TestFindInArchives(_SMMTestCase):
    def setUp(self):
        super().setUp()
        self.backups = self.smm_dir / "backups"
        self.backups.mkdir(exist_ok=True)

    def _write(self, name: str, events: list[dict], *, mtime: float | None = None):
        path = self.backups / name
        path.write_text("".join(json.dumps(e) + "\n" for e in events))
        if mtime is not None:
            os.utime(path, (mtime, mtime))
        return path

    def test_archived_id_resolves(self):
        self._write("archive-20260808T235557.jsonl", [_event("2a4d54679a7f")])
        found = self._assert_not_none(
            archive.find_in_archives(self.backups, "2a4d54679a7f")
        )
        path, event = found
        self.assertEqual(event["topic"], "retro-try-one-slug-per-subject")
        self.assertEqual(path.name, "archive-20260808T235557.jsonl")

    def test_missing_id_returns_none(self):
        self._write("archive-20260808T235557.jsonl", [_event("2a4d54679a7f")])
        self.assertIsNone(archive.find_in_archives(self.backups, "ffffffffffff"))

    def test_absent_backups_dir_returns_none(self):
        # A project that has never compacted has no backups/ at all.
        self.assertIsNone(
            archive.find_in_archives(self.smm_dir / "nope", "2a4d54679a7f")
        )

    def test_malformed_lines_do_not_abort_the_scan(self):
        # Exactly the shape of a pre-repair backup: the bad lines are WHY the
        # file exists, and the recovered id sits behind them.
        path = self.backups / "pre-repair-20260808T235557.jsonl"
        path.write_text(
            "{not json at all\n"
            + json.dumps(_event("2a4d54679a7f"))
            + "\n"
            + "also not json\n"
        )
        found = self._assert_not_none(
            archive.find_in_archives(self.backups, "2a4d54679a7f")
        )
        self.assertEqual(found[1]["id"], "2a4d54679a7f")

    def test_newest_by_mtime_wins_across_mixed_prefixes(self):
        # `pre-repair-*` sorts BEFORE `archive-*` lexically while being the
        # newer file, so a filename sort would return the stale copy.
        now = time.time()
        self._write(
            "archive-20260808T235557.jsonl",
            [_event("2a4d54679a7f", content="stale copy")],
            mtime=now - 100,
        )
        self._write(
            "pre-repair-20260101T000000.jsonl",
            [_event("2a4d54679a7f", content="newest copy")],
            mtime=now,
        )
        found = self._assert_not_none(
            archive.find_in_archives(self.backups, "2a4d54679a7f")
        )
        self.assertEqual(found[1]["content"], "newest copy")

    def test_non_jsonl_files_are_ignored(self):
        (self.backups / "notes.txt").write_text("2a4d54679a7f\n")
        self.assertIsNone(archive.find_in_archives(self.backups, "2a4d54679a7f"))


class TestGetEventCliFallback(_SMMTestCase):
    """The wiring, not the helper: `get-event` must reach the archive.

    Driven as a subprocess because the contract under test is the CLI's —
    stdout stays a clean event document so `| python3 -c` readers keep
    working, and the archive provenance goes to stderr.
    """

    _CLI = Path(__file__).parent.parent.parent / "smm" / "smm_cli.py"

    def _run(self, event_id: str):
        return subprocess.run(
            [
                sys.executable,
                str(self._CLI),
                "--smm-dir",
                str(self.smm_dir),
                "get-event",
                event_id,
            ],
            capture_output=True,
            text=True,
        )

    def test_archived_event_is_returned_with_provenance_on_stderr(self):
        (self.smm_dir / "events.jsonl").write_text("")
        backups = self.smm_dir / "backups"
        backups.mkdir(exist_ok=True)
        (backups / "archive-20260808T235557.jsonl").write_text(
            json.dumps(_event("2a4d54679a7f")) + "\n"
        )
        result = self._run("2a4d54679a7f")
        self.assertEqual(result.returncode, 0, result.stderr)
        # stdout parses as the event alone — no provenance mixed in.
        self.assertEqual(
            json.loads(result.stdout)["topic"], "retro-try-one-slug-per-subject"
        )
        self.assertIn("archive-20260808T235557.jsonl", result.stderr)

    def test_genuinely_absent_id_still_errors(self):
        (self.smm_dir / "events.jsonl").write_text("")
        result = self._run("ffffffffffff")
        self.assertEqual(result.returncode, 1)
        self.assertIn("not found", result.stderr.lower())


if __name__ == "__main__":
    unittest.main()
