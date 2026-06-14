#!/usr/bin/env python3
"""Integration tests for the /xp-schedule preload (story-002).

The preload computes the ready frontier (story-001's ready-frontier CLI) and
emits it as preload vars (FRONTIER_IDS / FRONTIER_COUNT / PARALLELIZABLE) for
the skill to consume. The skill then promotes the chosen frontier and sets
execution_mode — the E2E test exercises the documented solo-promote commands.
"""

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from _bases import _PLUGIN_ROOT
from conftest import _extract_preload_var, _IntegrationTestCase
from conftest import make_sprint_dict as _make_sprint
from conftest import make_story_dict as _make_story

_PRELOAD = _PLUGIN_ROOT / "skills" / "xp-schedule" / "scripts" / "preload.sh"
_CLI = _PLUGIN_ROOT / "smm" / "sprint_cli.py"


class TestSchedulePreload(_IntegrationTestCase):
    def _write(self, stories) -> None:
        (self.smm_dir / "sprint.json").write_text(
            json.dumps(_make_sprint(stories=stories))
        )

    def _run(self):
        result = self._run_preload(_PRELOAD)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def test_single_story_frontier(self):
        self._write([_make_story(id="story-001", status="scheduled", dependencies=[])])
        out = self._run()
        self.assertEqual(_extract_preload_var(out, "FRONTIER_COUNT"), "1")
        self.assertEqual(_extract_preload_var(out, "PARALLELIZABLE"), "false")
        self.assertEqual(_extract_preload_var(out, "FRONTIER_IDS"), "story-001")

    def test_disjoint_multi_frontier_parallelizable(self):
        self._write(
            [
                _make_story(
                    id="story-001",
                    status="scheduled",
                    dependencies=[],
                    file_domain=["a.py — x"],
                ),
                _make_story(
                    id="story-002",
                    status="scheduled",
                    dependencies=[],
                    file_domain=["b.py — y"],
                ),
            ]
        )
        out = self._run()
        self.assertEqual(_extract_preload_var(out, "FRONTIER_COUNT"), "2")
        self.assertEqual(_extract_preload_var(out, "PARALLELIZABLE"), "true")

    def test_overlapping_multi_frontier_not_parallelizable(self):
        self._write(
            [
                _make_story(
                    id="story-001",
                    status="scheduled",
                    dependencies=[],
                    file_domain=["shared.py — x"],
                ),
                _make_story(
                    id="story-002",
                    status="scheduled",
                    dependencies=[],
                    file_domain=["shared.py — y"],
                ),
            ]
        )
        out = self._run()
        self.assertEqual(_extract_preload_var(out, "PARALLELIZABLE"), "false")

    def test_empty_frontier(self):
        self._write([_make_story(id="story-001", status="done", dependencies=[])])
        out = self._run()
        self.assertEqual(_extract_preload_var(out, "FRONTIER_COUNT"), "0")

    def test_e2e_solo_promote_sets_mode_and_in_progress(self):
        """AC5 E2E: preload then the documented solo-promote commands leave the
        frontier story in-progress with execution_mode=solo."""
        self._write([_make_story(id="story-001", status="scheduled", dependencies=[])])
        out = self._run()
        first = _extract_preload_var(out, "FRONTIER_IDS")
        assert first is not None
        self.assertEqual(first, "story-001")
        env = self._test_env
        subprocess.run(
            [
                sys.executable,
                str(_CLI),
                "--smm-dir",
                str(self.smm_dir),
                "edit-story",
                first,
            ],
            input='{"execution_mode":"solo"}',
            text=True,
            capture_output=True,
            check=True,
            env=env,
        )
        subprocess.run(
            [
                sys.executable,
                str(_CLI),
                "--smm-dir",
                str(self.smm_dir),
                "update-story",
                first,
                "in-progress",
            ],
            capture_output=True,
            text=True,
            check=True,
            env=env,
        )
        story = json.loads(
            subprocess.run(
                [
                    sys.executable,
                    str(_CLI),
                    "--smm-dir",
                    str(self.smm_dir),
                    "get-story",
                    first,
                ],
                capture_output=True,
                text=True,
                check=True,
                env=env,
            ).stdout
        )
        self.assertEqual(story["status"], "in-progress")
        self.assertEqual(story["execution_mode"], "solo")
