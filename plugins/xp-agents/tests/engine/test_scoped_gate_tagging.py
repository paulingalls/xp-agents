#!/usr/bin/env python3
"""The concrete false abort, and the tag that makes the inference unnecessary.

Split from `test_count_concerns_cycle_isolation.py` (590 lines). Diff relevance
INFERS which concerns belong to a close from the `files` their author happened to
record, so a stale or wrong path silently excludes a concern from the one gate
that exists not to miss it. Tagging is the remedy the inference was only ever a
fallback for, and the e2e is the abort it was written to stop.

Grouped together because they are the two ends of the same argument: what goes
wrong with inference alone, and what removes the need for it.
"""

import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

import markers
from _scoped_gate_fixtures import (
    _APPEND_IMPL,
    _CYCLE,
    _DIFF,
    _OTHER_CYCLE,
    _OUTSIDE_DIFF,
    _WINDOW_START,
    _concern,
    _ScopedGateTestCase,
)
from conftest import run_cli, write_events
from event_schema import METADATA_KEY_CLOSE_CYCLE_ID


class TestStoryThreeFalseAbortE2E(_ScopedGateTestCase):
    """AC#8 — the exact scenario from concern 3542ad2915df.

    story-003's close cycle ran clean, but 964426f13819 (an unrelated open lock
    defect, severity high, untagged, recorded inside the close window, naming a
    file in story-005's domain) pushed the auto-merge gate to
    abort-recommended. With the close diff supplied, the gate stays at 0.
    """

    def setUp(self) -> None:
        super().setUp()
        # 964426f13819's shape, plus the noise a live SMM carries in the same
        # window: a resolved-elsewhere concern in another cycle and one with no
        # file pin at all.
        write_events(
            self.events_file,
            [
                _concern(files=[_OUTSIDE_DIFF]),
                _concern(files=["plugins/xp-agents/scripts/concern_conflicts.py"]),
                _concern(files=["plugins/xp-agents/smm/init.sh"], cycle=_OTHER_CYCLE),
            ],
        )
        self.story_003_diff = [
            "plugins/xp-agents/scripts/preload_liveness.py",
            "plugins/xp-agents/tests/hooks/test_preload_liveness.py",
        ]

    def test_gate_does_not_flip_to_abort_recommended(self) -> None:
        self.assertEqual(self._scoped(self.story_003_diff), "0")

    def test_gate_still_flips_when_the_concern_is_about_this_diff(self) -> None:
        """The other half of the guarantee: narrowing must not disarm the gate
        for a concern that IS about the code being merged."""
        self.assertEqual(
            self._scoped(
                [*self.story_003_diff, "plugins/xp-agents/scripts/concern_conflicts.py"]
            ),
            "1",
        )


class TestTaggingBeatsTheFilesInference(_ScopedGateTestCase):
    """The remedy this file's rule was only ever a fallback for.

    Diff relevance INFERS which concerns belong to a close from the `files` the
    author happened to record, so a stale or wrong path silently excludes a
    concern from the one gate that exists not to miss it. When a close is
    running, the appender records the answer instead — and a recorded answer
    outranks the inference.

    End-to-end on purpose: the concern is written by the real appender CLI (a
    different process from the close, which is the whole difficulty) and read
    by the real count-concerns query the shared Step 6 invokes.
    """

    def _append_concern_naming(self, path: str) -> None:
        result = run_cli(
            _APPEND_IMPL,
            [
                "--type", "concern",
                "--agent", "main",
                "--severity", "high",
                "--content", "Reviewer Block: the gate must still see this",
                "--files", json.dumps([path]),
            ],
            self.smm_dir,
        )  # fmt: skip
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_a_concern_raised_during_the_close_counts_despite_its_files(self) -> None:
        markers.marker_write(self.smm_dir, markers.CLOSE_CYCLE_ID, _CYCLE)
        self._append_concern_naming(_OUTSIDE_DIFF)
        self.assertEqual(
            self._scoped(_DIFF),
            "1",
            "a concern raised DURING this close carries its id, and the tag is "
            "authoritative — the files heuristic must not drop it",
        )

    def test_the_same_concern_outside_a_close_follows_the_files_rule(self) -> None:
        """The control, and AC#6: a concern written with no close running — the
        shape every concern in an existing SMM has — keeps exactly the shipped
        behaviour. The tag narrows the gate; its absence changes nothing."""
        self._append_concern_naming(_OUTSIDE_DIFF)
        self.assertEqual(self._scoped(_DIFF), "0")

    def test_another_sessions_close_does_not_capture_this_concern(self) -> None:
        """Two teammates closing at once against the shared SMM: the concern is
        raised in a session with no close of its own, so it must stay untagged
        rather than being pulled into the neighbour's cycle."""
        with patch.dict(os.environ, {"XP_SESSION_ID": "another-session"}):
            markers.marker_write(self.smm_dir, markers.CLOSE_CYCLE_ID, _CYCLE)
        self._append_concern_naming("plugins/xp-agents/smm/smm_count.py")
        counted = self._count(["--cycle-id", _CYCLE, "--since-ts", _WINDOW_START])
        self.assertEqual(counted, "1", "an untagged concern still counts (fail closed)")
        self.assertIsNone(
            (self._read_events()[-1].get("metadata") or {}).get(
                METADATA_KEY_CLOSE_CYCLE_ID
            ),
            "the neighbour's cycle id must not reach this session's concern",
        )


if __name__ == "__main__":
    unittest.main()


if __name__ == "__main__":
    unittest.main()
