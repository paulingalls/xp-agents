#!/usr/bin/env python3
"""`count-concerns` on a line it cannot parse: fail CLOSED.

Split from `test_smm_cli_count_concerns.py` (640 lines). A corrupt line could be
hiding a high-severity concern, so it counts rather than being skipped — and the
timestamp window still applies to it where one can be extracted, which is the
only part of this that is not obvious. Grouped away from the severity/cycle
filters because the question is different: not "does the filter match" but "what
does the counter do when it cannot tell".
"""

import json
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

from _count_concerns_fixtures import _CLI, _close_started, _concern
from conftest import _SMMTestCase, run_cli

# The floor these tests measure against is the WINDOW's, not the flag's, and the
# window is read off the gated cycle's own close_started. `story` mode is the one
# that keeps the narrow, CLOSE_START_TS-shaped bound these fixtures describe, so
# every test that means to reach the extraction predicate at all has to seed one
# — without it the mode is unreadable, the floor drops (fail closed), and
# `_provably_out_of_window` returns False before ever looking at the line.
_CYCLE = "ccc111222333"
_WINDOW_START = "2026-05-01T00:00:00+00:00"


class TestCorruptLinesFailClosed(_SMMTestCase):
    """A line the counter cannot parse is counted, not skipped."""

    def _write(self, *lines: str) -> None:
        """Write a story-close's close_started event, then `lines` verbatim."""
        self.events_file.write_text(
            "".join(
                f"{line}\n"
                for line in (
                    json.dumps(_close_started(_CYCLE, "story", _WINDOW_START)),
                    *lines,
                )
            )
        )

    def _scoped(self) -> subprocess.CompletedProcess:
        return run_cli(
            _CLI,
            ["count-concerns", "--cycle-id", _CYCLE, "--since-ts", _WINDOW_START],
            self.smm_dir,
        )

    def test_malformed_line_counts_as_potential_concern(self) -> None:
        # A corrupt line could be hiding a high-severity concern — fail
        # closed by counting it, rather than fail-open by skipping it.
        valid = _concern("high")
        self.events_file.write_text(
            json.dumps(valid) + "\n" + "{not valid json}\n" + "\n"
        )
        result = run_cli(_CLI, ["count-concerns"], self.smm_dir)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "2")
        self.assertIn("fail closed", result.stderr)
        self.assertIn("unparseable", result.stderr)

    def test_corrupt_line_with_old_embedded_ts_excluded_when_scoped(self) -> None:
        # Concern a11e9132e5bc / debt 7e8219afe702: a corrupt line from
        # BEFORE this close cycle's window must not permanently force
        # every future scoped count non-zero. A raw "ts" substring
        # recoverable from the unparseable line and provably older than the
        # window floor is positive evidence the line is out of scope, so it
        # must be excluded rather than added to the floor.
        #
        # Now seeds a story-mode close_started and scopes by cycle: the floor
        # is the WINDOW's, and only a readable close mode yields one. The pin's
        # intent is preserved under the new rule rather than dropped — an
        # unscoped invocation has no floor, so it would never reach the
        # extraction predicate at all.
        self._write(
            json.dumps(_concern("high", ts="2026-05-02T00:00:00+00:00")),
            # truncated write — looks like an object, embeds an old ts
            '{"ts": "2026-01-01T00:00:00+00:00", "type": "concern", "severi',
        )
        result = self._scoped()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "1")
        self.assertIn("provably out of scope", result.stderr)

    def test_corrupt_line_with_no_extractable_ts_still_counted(self) -> None:
        # Floor preserved: no ts substring is recoverable at all, so the
        # line must still count even though the window HAS a floor —
        # extraction only ever narrows the floor with positive evidence,
        # never loosens it for genuinely unscopable corruption.
        self._write("{completely garbled, no ts field}")
        result = self._scoped()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "1")
        self.assertIn("fail closed", result.stderr)

    def test_corrupt_line_with_recent_embedded_ts_still_counted(self) -> None:
        # A corrupt line whose embedded ts falls WITHIN (or after) the
        # scoped window must still count — the exclusion only fires on
        # provable out-of-window evidence, not merely because a ts was
        # found.
        self._write('{"ts": "2026-05-02T00:00:00+00:00", "type": "conce')
        result = self._scoped()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "1")
        self.assertIn("fail closed", result.stderr)

    def test_corrupt_line_with_old_ts_still_counted_without_since_ts(self) -> None:
        # Without --since-ts there is no window to prove exclusion
        # against — the floor must hold unconditionally, matching the
        # pre-existing unscoped fail-closed behavior.
        corrupt_old = '{"ts": "2026-01-01T00:00:00+00:00", "type": "conce'
        self.events_file.write_text(corrupt_old + "\n")
        result = run_cli(_CLI, ["count-concerns"], self.smm_dir)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "1")
        self.assertIn("fail closed", result.stderr)


if __name__ == "__main__":
    unittest.main()
