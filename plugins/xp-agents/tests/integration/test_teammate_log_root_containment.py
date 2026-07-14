#!/usr/bin/env python3
"""The suite never writes into the REAL teammate log root.

A spawn writes a teammate's prompt and tee-log under
`<log-root>/<project-id>/<sprint-id>/` and mkdirs that namespace itself. The
project id is derived from the SMM dir's parent, so a test driving a spawn
against a temp SMM dir mints a real directory keyed on a throwaway token.
Against the real root — a shared `/tmp/xp-agents-teammates` — nothing ever
removed those: 668 stranded dirs had piled up, and ten suites across three base
classes still mint one on every run.

The containment is a REDIRECT, not a sweep. `teammate_runner._log_root()` honors
`XP_TEAMMATE_LOG_ROOT`, and conftest points it at a disposable dir for the whole
session, so test writes cannot land in the shared root in the first place. The
sweep alternative — each base rmtree'ing its token back out of the real root —
deletes a path it merely DERIVED rather than owns, so a single leaked `SMM_DIR`
turns the suite's own teardown into `rm -rf` of a live project's teammate logs.
Containment has no such failure mode: there is nothing to delete.

Two assertions, and the second is the one with teeth:

1. The real root gains nothing across a child run of every spawn-driving suite.
2. The redirected root GAINED tokens during that same run.

(2) exists because (1) alone is vacuous — it passes just as happily if the spawns
stopped minting namespaces at all, if the suite list rotted, or if the child
errored out before doing any work. Proving the writes happened AND landed in the
sandbox is what makes (1) evidence of containment rather than of absence.
"""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from importlib.util import find_spec
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

import teammate_runner

_TESTS = Path(__file__).parent.parent

# The real, shared root — what `_log_root()` resolves to with no override, i.e.
# what a user's machine uses. Nothing the suite does may appear under it.
_REAL_ROOT = teammate_runner._DEFAULT_LOG_DIR / "xp-agents-teammates"


def _tokens(root: Path) -> set[str]:
    return {p.name for p in root.iterdir()} if root.is_dir() else set()


@unittest.skipUnless(
    find_spec("pytest"), "needs pytest to drive the child suite (CI runs unittest)"
)
class TestTheSuiteNeverWritesToTheRealLogRoot(unittest.TestCase):
    """Drive every spawn-minting suite in a child, and watch both roots."""

    # Every suite measured to mint a namespace, across all three base classes —
    # `_IntegrationTestCase` (temp SMM under a per-class plugin-data dir) and the
    # hook bases (bare `mkdtemp` SMM dirs, whose token is the system temp dir's
    # own name). An earlier cut of this pin named only the three integration
    # suites and reported the leak fixed while these seven kept minting.
    #
    # Listed, not globbed, because a glob over `tests/` would collect THIS file
    # and recurse. A list can rot — so the sandbox-was-written assertion below is
    # what keeps a stale list honest: drop the spawning suites and it goes red.
    _SPAWN_SUITES = (
        "hooks/test_no_test_can_spawn_a_real_agent.py",
        "hooks/test_spawn_prompt_guard.py",
        "hooks/test_spawn_teammate.py",
        "hooks/test_spawn_teammate_args.py",
        "hooks/test_spawn_teammate_effort.py",
        "hooks/test_spawn_teammate_logging.py",
        "hooks/test_spawn_teammate_markers.py",
        "hooks/test_spawn_teammate_pipeline.py",
        "hooks/test_spawn_teammate_write_door.py",
        "integration/test_assign.py",
        "integration/test_assign_team.py",
        "integration/test_spawn_teammate_promote.py",
    )

    def test_spawn_suites_write_only_to_the_redirected_root(self):
        sandbox = Path(tempfile.mkdtemp(prefix="xp-agents-log-root-pin-"))
        self.addCleanup(shutil.rmtree, sandbox, ignore_errors=True)

        # Aim the child at a root we can inspect. conftest honors an inherited
        # value precisely so this pin can see what the child minted.
        env = os.environ.copy()
        env["XP_TEAMMATE_LOG_ROOT"] = str(sandbox)

        before = _tokens(_REAL_ROOT)
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "-q"]
            + [str(_TESTS / s) for s in self._SPAWN_SUITES],
            capture_output=True,
            text=True,
            timeout=600,
            env=env,
        )
        self.assertEqual(result.returncode, 0, result.stdout[-3000:])
        stranded = _tokens(_REAL_ROOT) - before

        # Teeth: the child really did mint namespaces, so the clean real root
        # below means "contained", not "nothing happened".
        self.assertTrue(
            _tokens(sandbox / "xp-agents-teammates"),
            "no teammate namespace was minted under the redirected root — either "
            "the spawn suites stopped driving a spawn (this list is stale) or the "
            f"redirect is not wired; either way the check below proves nothing. "
            f"child stdout:\n{result.stdout[-2000:]}",
        )

        self.assertEqual(
            stranded,
            set(),
            f"{len(stranded)} namespace(s) leaked into the REAL log root "
            f"{_REAL_ROOT}: {sorted(stranded)}. Spawn paths must resolve their "
            "root through teammate_runner._log_root(), which conftest redirects "
            "for the test session — never a hardcoded /tmp.",
        )


if __name__ == "__main__":
    unittest.main()
