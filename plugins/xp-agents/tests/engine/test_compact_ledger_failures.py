#!/usr/bin/env python3
"""Compaction must not inherit the ledger's failure modes.

Split from `test_compact_adoption.py` (500 lines). `load_adoption` fails LOUD,
and compaction is the only thing that bounds events.jsonl -- so a ledger it
cannot read must not wedge it. The two suites here are the two halves of getting
that right, and the second is the one that was wrong:

  * an UNREADABLE ledger is quarantined and compaction proceeds;
  * a failed ledger WRITE is not a read failure. `record_intents` load-folds-saves
    and both ends raise ValueError, so quarantining on either end destroyed a
    healthy ledger because saving it failed.

Grouped away from the lane-survival tests because those ask whether memory
survives compaction, and these ask whether compaction survives the memory.
"""

import contextlib
import io
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import adoption_store
import compact
from _append_impl import LockTimeoutError
from _compaction_fixtures import _LedgerCompactionTestCase
from conftest import make_event, triage_event
from event_schema import EVENT_TYPE_DEBT


class TestAnUnreadableLedgerCannotWedgeCompaction(_LedgerCompactionTestCase):
    """`load_adoption` fails LOUD, and compaction must not inherit that.

    Compaction is the only thing that bounds `events.jsonl`, and it reaches
    production two ways, both of which an unreadable ledger would break: `main()`
    (SessionEnd + PostCompact) catches only LockTimeoutError, so a ValueError
    escapes as a traceback; `smm_cli.complete_curation` suppresses OSError and
    ValueError, so it no-ops in silence. Either way compaction stops every
    session from then on, and the log grows forever — with no remedy but
    hand-deleting a file the user has never heard of. An unbounded log is a far
    worse failure than a forgotten adoption.
    """

    def _corrupt_case(self, body: str) -> list[dict]:
        (self.smm_dir / adoption_store.ADOPTION_FILENAME).write_text(
            body, encoding="utf-8"
        )
        debt = make_event(
            EVENT_TYPE_DEBT, content="An adopted debt", ts="2026-01-01T00:00:00+00:00"
        )
        self._write_events([debt])
        adopt = triage_event(self.smm_dir, "triage-adopt", debt["id"])
        with contextlib.redirect_stderr(io.StringIO()) as err:
            live = self._compact([debt, adopt, *self._anchors()])
        self.assertIn("adoption ledger", err.getvalue())
        self._assert_archived(live, adopt, "the triage-adopt status event")
        return live

    def test_corrupt_json_is_quarantined_and_the_log_still_compacts(self):
        live = self._corrupt_case("{not json")

        self.assertTrue((self.smm_dir / adoption_store.QUARANTINE_FILENAME).exists())
        self.assertEqual(len(self._ledger()["entries"]), 1, "rebuilt from the log")
        self.assertTrue(self._triage_map(live))

    def test_a_version_from_the_future_does_not_wedge_a_rolled_back_plugin(self):
        """The realistic path to an unreadable ledger: a newer plugin bumps
        SCHEMA_VERSION, the user rolls back, and the older code cannot read what
        the newer one wrote. Rolling back must not stop compaction forever."""
        self._corrupt_case(
            json.dumps({"version": adoption_store.SCHEMA_VERSION + 1, "entries": []})
        )

        self.assertTrue((self.smm_dir / adoption_store.QUARANTINE_FILENAME).exists())
        self.assertEqual(self._ledger()["version"], adoption_store.SCHEMA_VERSION)


class TestAWriteFailureIsNotAReadFailure(_LedgerCompactionTestCase):
    """Quarantine is the remedy for an UNREADABLE ledger. It is not the remedy
    for anything else, and it used to be applied to everything.

    `record_intents` load-folds-saves, and BOTH ends raise ValueError:
    `load_adoption` on a corrupt ledger, `save_adoption` on a schema-invalid
    intent map. From outside they are one exception type. So a save-side failure —
    which is OUR bug, in a map we built, with the ledger on disk perfectly
    healthy and (per `save_adoption`) untouched — took the healthy adoption.json
    and QUARANTINED it, then re-raised out of the un-wrapped retry anyway. The
    cure destroyed the patient and the hook died regardless.

    Naming the fault means reading first: only a failed READ may quarantine.
    """

    def _fold_with_broken_ledger_write(self, failure: Exception) -> tuple[str, dict]:
        """Compact with a HEALTHY ledger on disk and the ledger WRITE failing.

        Returns the fold's stderr and the adopt event, so callers can assert the
        compaction ran to completion via `_assert_archived` — the suite's
        falsifiability guard, and the only honest evidence that the archive and
        the atomic replace were reached.
        """
        debt = make_event(
            EVENT_TYPE_DEBT, content="An adopted debt", ts="2026-01-01T00:00:00+00:00"
        )
        self._write_events([debt])
        adopt = triage_event(self.smm_dir, "triage-adopt", debt["id"])
        adoption_store.save_adoption(self.smm_dir, adoption_store.empty_adoption())
        with (
            patch.object(compact.adoption_store, "record_intents", side_effect=failure),
            contextlib.redirect_stderr(io.StringIO()) as err,
        ):
            live = self._compact([debt, adopt, *self._anchors()])
        self._assert_archived(live, adopt, "the triage-adopt status event")
        return err.getvalue(), adopt

    def test_a_save_failure_does_not_quarantine_a_healthy_ledger(self):
        self._fold_with_broken_ledger_write(
            ValueError("adoption validation failed: bad intent map")
        )
        self.assertFalse(
            (self.smm_dir / adoption_store.QUARANTINE_FILENAME).exists(),
            "a healthy ledger was quarantined for a fault that was not its own",
        )
        self.assertTrue((self.smm_dir / adoption_store.ADOPTION_FILENAME).exists())

    def test_a_save_failure_does_not_abort_the_compaction(self):
        """The ledger is a CACHE of what the log already said. Compaction is the
        only thing that bounds the log. Losing a fold is recoverable; losing
        compaction is not. (`_assert_archived` inside the helper is what proves
        the archive + atomic replace were reached.)"""
        err, _ = self._fold_with_broken_ledger_write(
            ValueError("adoption validation failed: bad intent map")
        )
        self.assertIn("compaction continues", err)

    def test_a_contended_adoption_lock_does_not_abort_the_compaction(self):
        """`LockTimeoutError` is a bare `Exception` subclass, so it slipped
        through `except (OSError, ValueError)` untouched.

        Teammates share one SMM dir and every SessionEnd compacts, so two
        compactions overlapping on `adoption.lock` is ordinary, not exotic. A
        contended lock propagated out of the fold and abandoned the whole pass
        BEFORE the archive and the atomic replace ever ran — the log went
        unbounded because a CACHE was busy.
        """
        err, _ = self._fold_with_broken_ledger_write(
            LockTimeoutError("adoption.lock held by a sibling")
        )
        self.assertIn("compaction continues", err)


if __name__ == "__main__":
    unittest.main()


if __name__ == "__main__":
    unittest.main()
