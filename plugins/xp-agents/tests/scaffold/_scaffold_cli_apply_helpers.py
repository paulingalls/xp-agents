#!/usr/bin/env python3
"""Shared base fixture for the scaffold apply-CLI test family.

Split out of `test_scaffold_cli_apply.py` (which grew past the
500-line cap) so `_ApplyCliTestBase` has exactly one home instead of
being duplicated across sibling test modules. Not `test_`-prefixed, so
pytest/unittest discovery does not collect it directly — it is
imported by `test_scaffold_cli_apply.py`, `test_scaffold_cli_apply_commit.py`,
and (unchanged) by `test_scaffold_cli_record.py`.
"""

import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from _bases import _PLUGIN_ROOT
from conftest import _SMMTestCase, run_cli

_CLI = _PLUGIN_ROOT / "scripts" / "scaffold_cli.py"


class _ApplyCliTestBase(_SMMTestCase):
    """Stages a temp repo + apply plan; runs apply-write to produce a snapshot."""

    def setUp(self) -> None:
        super().setUp()
        self._repo = self.smm_dir.parent / f"{self.smm_dir.name}-repo"
        self._repo.mkdir()
        (self._repo / "package.json").write_text('{"name": "demo"}\n', encoding="utf-8")
        self._snapshots: list[Path] = []

    def tearDown(self) -> None:
        for snap in self._snapshots:
            shutil.rmtree(snap, ignore_errors=True)
        shutil.rmtree(self._repo, ignore_errors=True)
        super().tearDown()

    def _track_snapshot(self, payload: dict) -> None:
        snap_dir = payload.get("snapshot_dir")
        if snap_dir:
            self._snapshots.append(Path(snap_dir))

    def _plan(self, **overrides: object) -> dict:
        plan = {
            "surface": "browser",
            "tool": "playwright",
            "tool_version": "1.51.0",
            "files_to_create": [
                {
                    "path": "tests/x.spec.ts",
                    "description": "happy",
                    "body": "x\n",
                }
            ],
            "files_to_modify": [
                {
                    "path": "package.json",
                    "description": "+dep",
                    "body": '{"name": "demo", "added": true}\n',
                }
            ],
            "install_cmds": ["true"],
            "verify_cmd": "true",
            "branch_name": "paul/scaffold-browser-acceptance",
        }
        plan.update(overrides)
        return plan

    def _apply_write(self, plan: dict) -> dict:
        result = run_cli(
            _CLI,
            ["apply-write", "--repo-root", str(self._repo)],
            self.smm_dir,
            stdin_data=json.dumps(plan),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self._track_snapshot(payload)
        return payload
