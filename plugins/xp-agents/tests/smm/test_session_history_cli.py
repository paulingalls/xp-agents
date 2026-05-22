#!/usr/bin/env python3
"""Tests for smm/session_history_cli.py — render + validate subcommands.

The CLI is the canonical front-end for session_history.json reads.
Covers: render output shape, --limit param, staleness annotation when
events.jsonl carries session_started boundary anchors, fail-quiet on
missing history, fail-loud on corrupt history, validate subcommand exit
codes.
"""

import json
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import session_history
from conftest import _SMMTestCase, make_event, make_session_history_entry
from event_schema import EVENT_TYPE_SESSION_STARTED

_PLUGIN_ROOT = Path(__file__).resolve().parent.parent.parent
_CLI = _PLUGIN_ROOT / "smm" / "session_history_cli.py"


def _save(smm_dir: Path, entries: list[dict]) -> None:
    session_history.save_history(
        smm_dir,
        {"version": session_history.SCHEMA_VERSION, "entries": entries},
    )


def _seed_session_started(smm_dir: Path, ts: str) -> None:
    """Append a session_started boundary anchor so the CLI's staleness scan
    sees it."""
    event = make_event(EVENT_TYPE_SESSION_STARTED, content="started", ts=ts)
    path = smm_dir / "events.jsonl"
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(event) + "\n")


def _run(*args: str, smm_dir: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(_CLI), "--smm-dir", str(smm_dir), *args],
        capture_output=True,
        text=True,
        check=False,
    )


class TestRenderSubcommand(_SMMTestCase):
    def test_missing_history_exits_zero_with_empty_stdout(self):
        result = _run("render", smm_dir=self.smm_dir)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")

    def test_one_entry_renders_block(self):
        _save(
            self.smm_dir,
            [
                make_session_history_entry(
                    ts="2026-05-10T10:00:00+00:00",
                    summary="Shipped Track 1 CLI.",
                )
            ],
        )
        result = _run("render", smm_dir=self.smm_dir)
        self.assertEqual(result.returncode, 0)
        self.assertIn("### LAST_SESSION", result.stdout)
        self.assertIn("Shipped Track 1 CLI.", result.stdout)

    def test_limit_one_renders_only_latest(self):
        _save(
            self.smm_dir,
            [
                make_session_history_entry(
                    ts="2026-05-08T10:00:00+00:00", summary="Older."
                ),
                make_session_history_entry(
                    ts="2026-05-10T10:00:00+00:00", summary="Newer."
                ),
            ],
        )
        result = _run("render", "--limit", "1", smm_dir=self.smm_dir)
        self.assertEqual(result.returncode, 0)
        self.assertNotIn("Older.", result.stdout)
        self.assertIn("Newer.", result.stdout)

    def test_default_limit_renders_last_two(self):
        _save(
            self.smm_dir,
            [
                make_session_history_entry(
                    ts="2026-05-06T10:00:00+00:00", summary="Oldest."
                ),
                make_session_history_entry(
                    ts="2026-05-08T10:00:00+00:00", summary="Middle."
                ),
                make_session_history_entry(
                    ts="2026-05-10T10:00:00+00:00", summary="Newest."
                ),
            ],
        )
        result = _run("render", smm_dir=self.smm_dir)
        self.assertNotIn("Oldest.", result.stdout)
        self.assertIn("Middle.", result.stdout)
        self.assertIn("Newest.", result.stdout)

    def test_stale_entry_renders_inline_annotation(self):
        _save(
            self.smm_dir,
            [
                make_session_history_entry(
                    ts="2026-05-10T10:00:00+00:00", summary="Old summary."
                )
            ],
        )
        # Three session_started anchors after the entry — each is a session
        # that began without a new summary being written.
        _seed_session_started(self.smm_dir, "2026-05-10T10:00:30+00:00")
        _seed_session_started(self.smm_dir, "2026-05-11T09:00:00+00:00")
        _seed_session_started(self.smm_dir, "2026-05-12T09:00:00+00:00")

        result = _run("render", smm_dir=self.smm_dir)
        self.assertEqual(result.returncode, 0)
        self.assertIn("### LAST_SESSION (stale", result.stdout)
        self.assertIn("3 sessions", result.stdout)

    def test_fresh_entry_renders_no_annotation(self):
        _save(
            self.smm_dir,
            [
                make_session_history_entry(
                    ts="2026-05-10T10:00:00+00:00", summary="Fresh summary."
                )
            ],
        )
        # The entry's own session started before the summary; no later
        # session has begun, so the entry is fresh.
        _seed_session_started(self.smm_dir, "2026-05-10T09:00:00+00:00")

        result = _run("render", smm_dir=self.smm_dir)
        self.assertEqual(result.returncode, 0)
        self.assertIn("### LAST_SESSION", result.stdout)
        self.assertNotIn("(stale", result.stdout)

    def test_corrupt_history_exits_nonzero_loudly(self):
        # CLI is fail-loud on corrupt — the kickoff preload wraps the call
        # so a crashed CLI does not block kickoff.
        path = self.smm_dir / session_history.SESSION_HISTORY_FILENAME
        path.write_text("{not valid json", encoding="utf-8")

        result = _run("render", smm_dir=self.smm_dir)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Error loading session_history", result.stderr)


class TestValidateSubcommand(_SMMTestCase):
    def test_missing_history_validates_ok(self):
        # load_history returns empty on missing file — empty docs are valid.
        result = _run("validate", smm_dir=self.smm_dir)
        self.assertEqual(result.returncode, 0)

    def test_valid_history_exits_zero(self):
        _save(
            self.smm_dir,
            [
                make_session_history_entry(
                    ts="2026-05-10T10:00:00+00:00", summary="Valid."
                )
            ],
        )
        result = _run("validate", smm_dir=self.smm_dir)
        self.assertEqual(result.returncode, 0)

    def test_corrupt_history_exits_nonzero_with_stderr(self):
        path = self.smm_dir / session_history.SESSION_HISTORY_FILENAME
        path.write_text("{not valid json", encoding="utf-8")

        result = _run("validate", smm_dir=self.smm_dir)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Validation failed", result.stderr)


if __name__ == "__main__":
    unittest.main()
