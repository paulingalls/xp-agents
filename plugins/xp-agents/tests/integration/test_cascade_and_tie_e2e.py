#!/usr/bin/env python3
"""E2E test for sprint-006 M2: retire domain_accuracy; fix multi-way ties.

Cross-story integration test that exercises BOTH:
- story-001 (sizing_metrics retires domain_accuracy/in_domain_files/out_of_domain_files;
  emits informational cascade_size in per-story sizing_analysis dicts).
- story-002 (_resolve_story_id returns None on multi-way domain-overlap ties so
  cross-cutting commits aggregate at sprint level instead of polluting one story).

Written as part of the adopted-retro-Try-4 front-loading discipline: main agent
lands this E2E in a separate post-merge commit after both teammate stories merge,
giving an instant feedback signal the moment the last teammate's PR lands.
"""

import json
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from conftest import _IntegrationTestCase, _s, _sprint_json, make_event


class TestCascadeAndTieE2E(_IntegrationTestCase):
    def test_cross_cutting_commit_ties_and_cascade_size_surfaces(self):
        """Sprint with two in-progress stories on disjoint domains; cross-cutting
        commit touches one file from each domain (a multi-way tie). Assert:

        1. story-002 fix: commit event metadata has NO story_id.
        2. story-001 fix: sizing_analysis per_story dicts carry cascade_size and
           do NOT carry the retired keys (domain_accuracy, in_domain_files,
           out_of_domain_files).
        """
        (self.smm_dir / "sprint.json").write_text(
            _sprint_json(
                [
                    _s(
                        "story-001",
                        "Auth",
                        "M",
                        "in-progress",
                        file_domain=["scripts/auth.py \u2014 login"],
                    ),
                    _s(
                        "story-002",
                        "UI",
                        "M",
                        "in-progress",
                        file_domain=["src/ui.py \u2014 layout"],
                    ),
                ],
                sprint_id="sprint-006",
                started="2026-04-19",
                goal="retire domain_accuracy; fix cross-cutting tie",
            )
        )

        (self.tmpdir / "scripts").mkdir(exist_ok=True)
        (self.tmpdir / "scripts" / "auth.py").write_text("# auth\n")
        (self.tmpdir / "src").mkdir(exist_ok=True)
        (self.tmpdir / "src" / "ui.py").write_text("# ui\n")
        subprocess.run(
            ["git", "add", "scripts/auth.py", "src/ui.py"],
            cwd=self.tmpdir,
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "Cross-cutting infra change"],
            cwd=self.tmpdir,
            capture_output=True,
            check=True,
        )

        result = self._run_script(
            "bash_post_tool.py",
            {
                "session_id": "e2e-tie",
                "tool_name": "Bash",
                "tool_input": {"command": "git commit -m 'Cross-cutting infra change'"},
                "tool_response": {
                    "stdout": (
                        "[main deadbe0] Cross-cutting infra change\n 2 files changed"
                    )
                },
                "cwd": str(self.tmpdir),
                "agent_id": "main",
            },
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)

        events = self._read_events()
        commits = [e for e in events if e.get("type") == "commit"]
        self.assertEqual(len(commits), 1)
        commit_meta = commits[0].get("metadata") or {}
        self.assertNotIn(
            "story_id",
            commit_meta,
            "multi-way tie should NOT attribute commit to any single story "
            f"(got metadata={commit_meta})",
        )

        self._seed_events(
            [
                make_event(
                    "sprint",
                    content="sprint-006 end",
                    metadata={"sprint_id": "sprint-006", "action": "end"},
                ),
            ]
        )
        retro_result = self._run_script(
            "retrospective.py",
            {"session_id": "e2e-tie", "source": "startup"},
        )
        self.assertEqual(retro_result.returncode, 0, msg=retro_result.stderr)

        retro_input = json.loads((self.smm_dir / ".retro-input.json").read_text())
        sizing = retro_input.get("sizing_analysis") or {}
        per_story = sizing.get("per_story") or []
        self.assertEqual(len(per_story), 2)

        retired_keys = (
            "domain_accuracy",
            "in_domain_files",
            "out_of_domain_files",
        )
        for story in per_story:
            self.assertIn(
                "cascade_size",
                story,
                f"story {story.get('id')} missing cascade_size: {list(story)}",
            )
            for retired in retired_keys:
                self.assertNotIn(
                    retired,
                    story,
                    f"retired key {retired!r} still on {story.get('id')}",
                )
            self.assertEqual(story["commits"], 0)
            self.assertEqual(story["cascade_size"], 0)


if __name__ == "__main__":
    unittest.main()
