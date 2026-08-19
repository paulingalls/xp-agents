#!/usr/bin/env python3
"""The heartbeat survives a real hook pipeline.

The unit suite (tests/hooks/test_heartbeat_writers.py) calls `run()` in
process, which proves the placement but not the plumbing. This drives a hook as
the platform does — a separate `python3`, JSON on stdin, resolving the SMM for
itself — because that is where the failures the feature exists to catch
actually live: an import that only resolves under the test runner's sys.path,
or a heartbeat written somewhere no other process looks.

**Repointed, not deleted.** This used to read the verdict back through the
shipped `hook_liveness.py status` CLI, on the argument that a file on disk is
not the claim — the claim is that a fresh process asking "are hooks running"
gets yes. That CLI is gone with the rest of the verdict reader, but the
property it demonstrated is the one thing that still proves the KEPT write
sites work end to end, so it is asked of the surviving primitive instead: a
fresh process resolves the SMM itself, addresses the same session's marker, and
ages it. If that stops working, `coordination` and `close_cycle_abandonment`
both silently lose their liveness signal.
"""

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from _heartbeat_fixtures import env as _env
from _heartbeat_fixtures import is_beating
from conftest import _IntegrationTestCase

_SESSION = "pipeline-session"


class TestTheHeartbeatSurvivesARealHookProcess(_IntegrationTestCase):
    """One writer, driven as its own process, read back by another."""

    def _run_hook(self, script: str, payload: dict) -> subprocess.CompletedProcess:
        return self._run_script_with_env(
            script, payload, _env(CLAUDE_CODE_SESSION_ID=_SESSION)
        )

    def test_nothing_is_beating_before_any_hook_runs(self):
        """The baseline. Without it the assertion below passes on a marker some
        earlier test left behind, and proves nothing about this pipeline."""
        self.assertIsNone(is_beating(self.smm_dir, _SESSION))

    def test_a_hook_run_as_its_own_process_leaves_a_readable_heartbeat(self):
        result = self._run_hook(
            "user_prompt_log.py",
            {"session_id": _SESSION, "prompt": "hello", "cwd": str(self.tmpdir)},
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIs(
            is_beating(self.smm_dir, _SESSION),
            True,
            "a hook ran in its own process but no other process can address "
            "its heartbeat — the plumbing this suite exists to prove",
        )
