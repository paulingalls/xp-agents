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
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

from _count_concerns_fixtures import _CLI, _concern
from conftest import _SMMTestCase, run_cli


class TestCorruptLinesFailClosed(_SMMTestCase):
    """A line the counter cannot parse is counted, not skipped."""

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
        # every future --since-ts-scoped count non-zero. A raw "ts"
        # substring recoverable from the unparseable line and provably
        # older than --since-ts is positive evidence the line is out of
        # scope, so it must be excluded rather than added to the floor.
        valid = _concern("high", ts="2026-05-02T00:00:00+00:00")
        # truncated write — looks like an object, embeds an old ts
        corrupt_old = '{"ts": "2026-01-01T00:00:00+00:00", "type": "concern", "severi'
        self.events_file.write_text(json.dumps(valid) + "\n" + corrupt_old + "\n")
        result = run_cli(
            _CLI,
            ["count-concerns", "--since-ts", "2026-05-01T00:00:00+00:00"],
            self.smm_dir,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "1")
        self.assertIn("provably out of scope", result.stderr)

    def test_corrupt_line_with_no_extractable_ts_still_counted(self) -> None:
        # Floor preserved: no ts substring is recoverable at all, so the
        # line must still count even though --since-ts is provided —
        # extraction only ever narrows the floor with positive evidence,
        # never loosens it for genuinely unscopable corruption.
        self.events_file.write_text("{completely garbled, no ts field}\n")
        result = run_cli(
            _CLI,
            ["count-concerns", "--since-ts", "2026-05-01T00:00:00+00:00"],
            self.smm_dir,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "1")
        self.assertIn("fail closed", result.stderr)

    def test_corrupt_line_with_recent_embedded_ts_still_counted(self) -> None:
        # A corrupt line whose embedded ts falls WITHIN (or after) the
        # scoped window must still count — the exclusion only fires on
        # provable out-of-window evidence, not merely because a ts was
        # found.
        corrupt_recent = '{"ts": "2026-05-02T00:00:00+00:00", "type": "conce'
        self.events_file.write_text(corrupt_recent + "\n")
        result = run_cli(
            _CLI,
            ["count-concerns", "--since-ts", "2026-05-01T00:00:00+00:00"],
            self.smm_dir,
        )
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
