#!/usr/bin/env python3
"""The suite reaps the temp namespaces it mints.

A spawn writes a teammate's prompt and tee-log under
`/tmp/xp-agents-teammates/<project-id>/<sprint-id>/`, and `spawn_teammate` mkdirs
that namespace itself. Tests that drive a spawn against a temp SMM dir therefore
create a REAL directory under a REAL /tmp root — and nothing ever removed it.

Measured before this story: 542 stranded directories, and a full suite run left 4
more behind, every run, forever. Small in bytes; a slow leak in a shared namespace,
and one per project PER SPRINT in real use.

The fix belongs to the BASE that mints the token, not to each test that happens to
trip it. `test_spawn_prompt_guard` already reaps its own; copying that line into
every future spawn test is how the leak came back the last two times.

This pin is a subprocess count, not a unit assertion, because the thing being
asserted is a property of the whole run: what is left on disk AFTER teardown. A test
that checked its own cleanup from inside the class could not see a `tearDownClass`
that never fires.
"""

import shutil
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

import teammate_runner

_TESTS = Path(__file__).parent.parent


def _tokens() -> set[str]:
    root = teammate_runner._LOG_ROOT
    if not root.is_dir():
        return set()
    return {p.name for p in root.iterdir()}


class TestTheSuiteLeavesNoTempDirsBehind(unittest.TestCase):
    """Run the suites that drive a spawn, and count what they strand."""

    # The three measured leakers. Named rather than globbed: a glob would silently
    # cover a file that stops leaking, and quietly stop covering one that starts.
    _SPAWN_SUITES = (
        "integration/test_assign.py",
        "integration/test_assign_team.py",
        "integration/test_spawn_teammate_promote.py",
    )

    def test_a_spawn_suite_strands_nothing(self):
        before = _tokens()

        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                *[str(_TESTS / s) for s in self._SPAWN_SUITES],
            ],
            capture_output=True,
            text=True,
            timeout=600,
        )
        self.assertEqual(result.returncode, 0, result.stdout[-2000:])

        stranded = _tokens() - before
        # Reap whatever this pin itself surfaced, so a RED run does not add to the
        # very pile it is measuring.
        for name in stranded:
            shutil.rmtree(teammate_runner._LOG_ROOT / name, ignore_errors=True)

        self.assertEqual(
            stranded,
            set(),
            f"{len(stranded)} temp namespace(s) stranded under "
            f"{teammate_runner._LOG_ROOT}. The base that mkdirs the token must "
            f"reap it — see _IntegrationTestCase.",
        )


if __name__ == "__main__":
    unittest.main()
