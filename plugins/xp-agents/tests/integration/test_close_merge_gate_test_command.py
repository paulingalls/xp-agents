#!/usr/bin/env python3
"""Close-pipeline TEST_COMMAND preload wiring.

Split out of the original test_close_merge_gate.py (which grew past
the 500-line cap). This file keeps the TEST_COMMAND preload emission
tests — story-close + free-close preloads emit a `TEST_COMMAND=...`
line sourced from `system_context.stack.test_command`, plus the
CLOSE_START_TS emission the Step 6 auto-merge gate depends on.

The SKILL.md auto-merge override section itself lives in
test_close_merge_gate.py. The deterministic Step 6 count-concerns CLI
realistic E2E tests live in
test_close_merge_gate_count_concerns_e2e.py.

Per-mode shared-content preload emission tests live in
test_close_preloads_emit_shared.py.
"""

import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from _bases import _PLUGIN_ROOT

_TEST_COMMAND_PRELOADS = {
    "story": _PLUGIN_ROOT / "skills" / "xp-story-close" / "scripts" / "preload.sh",
    "free": _PLUGIN_ROOT / "skills" / "xp-free-close" / "scripts" / "preload.sh",
}


class TestStoryFreePreloadEmitsTestCommand(unittest.TestCase):
    """Story-close + free-close preloads emit a `TEST_COMMAND=...` line
    sourced from `system_context.stack.test_command`. The auto-merge
    override (Step 6) reads this to decide whether the deterministic
    test gate can fire — empty TEST_COMMAND means fall through to the
    confirm prompt.

    Tests use _IntegrationTestCase fixtures (fresh tmp SMM per test)
    to control whether system_context.json exists and what it contains.
    """

    def _run_preload(self, preload_path: Path, smm_dir: Path) -> str:
        env = dict(os.environ)
        env["CLAUDE_PLUGIN_DATA"] = str(smm_dir.parent.parent)
        env["SMM_DIR"] = str(smm_dir)
        result = subprocess.run(
            ["bash", str(preload_path)],
            cwd=smm_dir,
            capture_output=True,
            text=True,
            env=env,
        )
        return result.stdout

    def _make_smm(self, sc_data: dict | None) -> Path:
        # Mirror _IntegrationTestCase's SMM-dir convention: deep nested
        # path under a tmp root so init.sh resolves it cleanly.
        tmp = Path(tempfile.mkdtemp())
        smm_dir = tmp / "data" / "proj" / "smm"
        smm_dir.mkdir(parents=True)
        (smm_dir / "events.jsonl").write_text("")
        if sc_data is not None:
            (smm_dir / "system_context.json").write_text(json.dumps(sc_data))
        return smm_dir

    def test_emits_test_command_when_set(self):
        # When system_context.stack.test_command is set, the preload
        # surfaces it verbatim so the auto-merge override can run it.
        sc = {
            "product": "x",
            "architecture_overview": "x",
            "stack": {"languages": ["Python"], "test_command": "pytest -n auto"},
            "modules": [],
            "conventions": [],
            "principles": [],
            "project_specific": [],
        }
        for mode, preload in _TEST_COMMAND_PRELOADS.items():
            with self.subTest(mode=mode):
                smm = self._make_smm(sc)
                stdout = self._run_preload(preload, smm)
                self.assertIn(
                    "TEST_COMMAND=pytest -n auto",
                    stdout,
                    f"{mode}-close preload must emit TEST_COMMAND=<stack.test_command>",
                )

    def test_emits_empty_test_command_when_unset(self):
        # When stack.test_command is absent, TEST_COMMAND= is empty.
        # The auto-merge override falls through to confirm prompt on
        # empty — never guesses pytest/npm/cargo.
        sc = {
            "product": "x",
            "architecture_overview": "x",
            "stack": {"languages": ["Python"]},
            "modules": [],
            "conventions": [],
            "principles": [],
            "project_specific": [],
        }
        for mode, preload in _TEST_COMMAND_PRELOADS.items():
            with self.subTest(mode=mode):
                smm = self._make_smm(sc)
                stdout = self._run_preload(preload, smm)
                self.assertIn(
                    "TEST_COMMAND=\n",
                    stdout,
                    f"{mode}-close preload must emit empty TEST_COMMAND= "
                    f"when stack.test_command is unset",
                )

    def test_emits_empty_test_command_when_no_system_context(self):
        # Graceful: missing system_context.json → empty TEST_COMMAND.
        # Plugins ship to repos that may not have run /xp-system-context
        # yet; preload must not fail, just emit empty.
        for mode, preload in _TEST_COMMAND_PRELOADS.items():
            with self.subTest(mode=mode):
                smm = self._make_smm(sc_data=None)
                stdout = self._run_preload(preload, smm)
                self.assertIn(
                    "TEST_COMMAND=\n",
                    stdout,
                    f"{mode}-close preload must emit empty TEST_COMMAND= "
                    f"when system_context.json is missing",
                )

    def test_emits_close_start_ts_iso_timestamp(self):
        # The auto-merge override's count-classifications invocation
        # bounds events by --since-ts <CLOSE_START_TS>. Pin that the
        # preload emits a CLOSE_START_TS line with an ISO 8601-shaped
        # value (YYYY-MM-DDTHH:MM:SS...) so lexicographic comparison
        # against event ts values works. Format match doesn't need to
        # be exact: assert leading 4-digit year, T separator, and a
        # +00:00 / Z trailer.
        iso_pattern = re.compile(
            r"^CLOSE_START_TS=\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}.*(\+00:00|Z)$",
            re.MULTILINE,
        )
        for mode, preload in _TEST_COMMAND_PRELOADS.items():
            with self.subTest(mode=mode):
                smm = self._make_smm(sc_data=None)
                stdout = self._run_preload(preload, smm)
                self.assertRegex(
                    stdout,
                    iso_pattern,
                    f"{mode}-close preload must emit CLOSE_START_TS=<ISO 8601 "
                    f"UTC timestamp> for the auto-merge gate's --since-ts "
                    f"bound",
                )


if __name__ == "__main__":
    unittest.main()
