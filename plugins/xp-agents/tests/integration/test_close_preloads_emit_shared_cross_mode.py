#!/usr/bin/env python3
"""Cross-mode CLOSE_START_TS emission check for every close-skill preload.

Split out of `test_close_preloads_emit_shared.py` (which grew past the
500-line cap). See that file for the per-mode shared-pipeline-content
assertions; this sibling covers the one check that spans all four
close preloads at once rather than parametrizing per mode class.
"""

import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from _bases import _PLUGIN_ROOT

_ALL_CLOSE_PRELOADS = {
    "story": _PLUGIN_ROOT / "skills" / "xp-story-close" / "scripts" / "preload.sh",
    "sprint": _PLUGIN_ROOT / "skills" / "xp-sprint-close" / "scripts" / "preload.sh",
    "plan": _PLUGIN_ROOT / "skills" / "xp-plan-close" / "scripts" / "preload.sh",
    "free": _PLUGIN_ROOT / "skills" / "xp-free-close" / "scripts" / "preload.sh",
}


class TestAllClosePreloadsEmitCloseStartTs(unittest.TestCase):
    """Every close-skill preload must emit CLOSE_START_TS=<ISO 8601>.

    The shared Step 6 abort-default count-concerns invocation references
    `<CLOSE_START_TS>` as a value "from the preload values at the top of
    this context" — for that promise to hold, every close preload (not
    just story/free) must emit it. Sprint/plan-close hit the same Step 6
    block in the shared pipeline AND apply Step 4.5 (Security Review),
    which writes concerns the Step 6 count then filters by since-ts.
    """

    def _run_preload(self, preload_path: Path, smm_dir: Path) -> str:
        env = dict(os.environ)
        env["XP_AGENTS_DATA"] = str(smm_dir.parent.parent)
        env["SMM_DIR"] = str(smm_dir)
        result = subprocess.run(
            ["bash", str(preload_path)],
            cwd=smm_dir,
            capture_output=True,
            text=True,
            env=env,
        )
        return result.stdout

    def _make_smm(self) -> Path:
        tmp = Path(tempfile.mkdtemp())
        smm_dir = tmp / "data" / "proj" / "smm"
        smm_dir.mkdir(parents=True)
        (smm_dir / "events.jsonl").write_text("")
        return smm_dir

    def test_every_close_preload_emits_iso_close_start_ts(self):
        iso_pattern = re.compile(
            r"^CLOSE_START_TS=\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}.*(\+00:00|Z)$",
            re.MULTILINE,
        )
        for mode, preload in _ALL_CLOSE_PRELOADS.items():
            with self.subTest(mode=mode):
                smm = self._make_smm()
                stdout = self._run_preload(preload, smm)
                self.assertRegex(
                    stdout,
                    iso_pattern,
                    f"{mode}-close preload must emit CLOSE_START_TS=<ISO 8601 "
                    f"UTC timestamp> for the shared Step 6 abort-default "
                    f"count-concerns --since-ts bound",
                )


class TestEveryClosePreloadCarriesTheCycleIdRelease(unittest.TestCase):
    """Every close mode must be told to release its cycle-id marker.

    The preload writes the id and the appender reads it to tag concerns raised
    during the cycle. The SessionStart sweep is only the abandonment backstop:
    IN-session, a marker left behind outlives its close, so later concerns get
    the finished cycle's id — and because the next close mints a DIFFERENT id,
    the Step 6 count then EXCLUDES them. Several closes per session is the
    normal case, so the consume is required, not tidiness.

    One leg in the shared pipeline covers all four modes, which is exactly why
    this is asserted across all four rather than per mode: a consume that
    reached only three would leave one mode silently mis-scoping.
    """

    _RELEASE_CALL = "consume CLOSE_CYCLE_ID"

    def test_every_close_preload_emits_the_release_step(self):
        driver = TestAllClosePreloadsEmitCloseStartTs()
        for mode, preload in _ALL_CLOSE_PRELOADS.items():
            with self.subTest(mode=mode):
                smm = driver._make_smm()
                stdout = driver._run_preload(preload, smm)
                self.assertIn(
                    self._RELEASE_CALL,
                    stdout,
                    f"{mode}-close must be instructed to consume the "
                    f"cycle-id marker at the end of the cycle",
                )
                self.assertIn(
                    "markers.py",
                    stdout,
                    f"{mode}-close's release step must drive the marker CLI "
                    f"rather than deleting a path by hand",
                )

    def test_the_release_runs_on_the_abort_path_too(self):
        shared = _PLUGIN_ROOT / "scripts" / "_close_pipeline_shared.md"
        text = shared.read_text()
        release_idx = text.find(self._RELEASE_CALL)
        self.assertGreater(release_idx, -1, "shared pipeline must release the id")
        # The abort branch ends the close without merging, and a cycle that
        # ended is a cycle whose id must stop tagging concerns — the abandoned
        # close is exactly when a stale id does the most damage, since the
        # operator stays in the session to fix what the gate found.
        instruction = text[release_idx - 600 : release_idx + 600].lower()
        self.assertIn(
            "abort",
            instruction,
            "the release step must say it also runs when the user aborts — "
            "otherwise an aborted close leaves its id tagging every later "
            "concern in the session",
        )


if __name__ == "__main__":
    unittest.main()
