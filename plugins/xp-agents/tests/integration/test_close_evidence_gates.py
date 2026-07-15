#!/usr/bin/env python3
"""Capstone integration test for Milestone 4: the three close gates compose.

Milestone 4 shipped three independent gate stories, each fixing one door
in the close pipeline:

- Gate A (story-001) — close_common.py `diff-command` emits
  `git diff <target>...<source>`, the MERGED range, never the PR head.
- Gate B (story-002) — close_cycle_stop_gate blocks Stop until
  reviewer-completion evidence exists (a subagent_complete status event
  with metadata.agent_type=xp-close-reviewer emitted AFTER the latest
  close_started); subagent_stop's xp-close-reviewer handler emits that
  evidence and releases the gate.
- Gate C (story-003) — pre_tool_skill refuses a lead's raw /xp-story-close
  invocation unless the accept-in-flight marker is armed.

The milestone's done-condition is that all three compose on the merged
sprint tip: closing a story is refused without accept evidence (Gate C),
proceeds only once reviewer evidence exists (Gate B), and reviews exactly
the range that gets merged even if local HEAD moves after the PR push
(Gate A). Each subtest below drives one gate through its real subprocess
entrypoint against the merged code — this file makes no assertions about
gate internals, only about the observable behavior at the composed
boundary.
"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import _branching_fixtures as _bf
import markers
from conftest import _MARKERS_PY, _IntegrationTestCase, _make_skill_input, run_cli
from event_schema import EVENT_TYPE_STATUS


def _close_started_event(event_id: str) -> dict:
    return {
        "id": event_id,
        "type": EVENT_TYPE_STATUS,
        "ts": "2026-05-05T15:00:00+00:00",
        "agent": "main",
        "content": "Close started",
        "metadata": {"action": "close_started"},
        "working_on": [],
    }


def _close_reviewer_complete_event(event_id: str) -> dict:
    return {
        "id": event_id,
        "type": EVENT_TYPE_STATUS,
        "ts": "2026-05-05T17:00:00+00:00",
        "agent": "xp-cr-1",
        "content": "Subagent complete",
        "metadata": {"action": "subagent_complete", "agent_type": "xp-close-reviewer"},
        "working_on": [],
    }


class TestCloseGatesCompose(_IntegrationTestCase):
    """Cross-cutting proof the three Milestone 4 close gates compose."""

    def test_gate_c_story_close_refused_without_accept_evidence(self):
        """AC1: /xp-story-close is refused without accept evidence, then
        allowed once the ACCEPT_IN_FLIGHT marker is armed (Gate C)."""
        skill_input = _make_skill_input("xp-story-close", cwd="/home/user/project")

        result = self._run_script("pre_tool_skill.py", skill_input)
        self.assertEqual(result.returncode, 0, result.stderr)
        parsed = json.loads(result.stdout)
        self.assertEqual(parsed["decision"], "block")
        self.assertIn("/xp-accept", parsed["reason"])

        markers.marker_write(self.smm_dir, markers.ACCEPT_IN_FLIGHT, "1")
        result = self._run_script("pre_tool_skill.py", skill_input)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "")

    def test_gate_b_close_cycle_blocks_then_releases_on_reviewer_evidence(self):
        """AC2: close-cycle gate blocks without reviewer-completion evidence
        and releases once it exists; the real subagent_stop emission path
        composes with the gate's read path (Gate B)."""
        cli_result = run_cli(_MARKERS_PY, ["write", "CLOSE_CYCLE_ACTIVE"], self.smm_dir)
        self.assertEqual(cli_result.returncode, 0, cli_result.stderr)

        log = [_close_started_event("closestart001")]
        self._seed_events(log)

        blocked = self._run_script(
            "close_cycle_stop_gate.py", {"agent_id": "main", "agent_type": "main"}
        )
        self.assertEqual(blocked.returncode, 0, blocked.stderr)
        parsed_block = json.loads(blocked.stdout)
        self.assertEqual(parsed_block["decision"], "block")
        self.assertIn("xp-close-reviewer", parsed_block["reason"])

        log.append(_close_reviewer_complete_event("reviewerdone1"))
        self._seed_events(log)

        released = self._run_script(
            "close_cycle_stop_gate.py", {"agent_id": "main", "agent_type": "main"}
        )
        self.assertEqual(released.returncode, 0, released.stderr)
        self.assertEqual(released.stdout.strip(), "")

        # Prove the real emission composes: reset the marker, then let the
        # actual xp-close-reviewer subagent_stop handler emit its own
        # completion evidence and consume the marker.
        run_cli(_MARKERS_PY, ["write", "CLOSE_CYCLE_ACTIVE"], self.smm_dir)
        self._seed_events([_close_started_event("closestart002")])

        result = self._run_script(
            "subagent_stop.py",
            {
                "session_id": "int",
                "agent_id": "xp-cr-1",
                "agent_type": "xp-close-reviewer",
                "last_assistant_message": "done",
            },
        )
        self.assertEqual(result.returncode, 0, result.stderr)

        events = self._read_events()
        self.assertTrue(
            any(
                e.get("metadata", {}).get("action") == "subagent_complete"
                and e.get("metadata", {}).get("agent_type") == "xp-close-reviewer"
                for e in events
            ),
            "subagent_stop must emit reviewer-completion evidence",
        )
        self.assertFalse(
            markers.marker_exists(self.smm_dir, markers.CLOSE_CYCLE_ACTIVE),
            "subagent_stop must consume CLOSE_CYCLE_ACTIVE on xp-close-reviewer",
        )

    def test_gate_a_diff_range_ends_at_merged_commit_post_push_fix(self):
        """AC3: local HEAD moving after the PR push doesn't change the
        emitted diff range — it still ends at the merged commit, and
        executing the emitted command surfaces the post-push fix
        (Gate A: reviewed == merged)."""
        with tempfile.TemporaryDirectory() as td:
            _bf.init_repo(td)
            _bf.make_commit(td, "feature-x", "orig.txt", "original\n", "story work")

            (Path(td) / "reviewer_fix.txt").write_text("POST_PUSH_FIX\n")
            subprocess.run(
                ["git", "add", "reviewer_fix.txt"],
                cwd=td,
                capture_output=True,
                check=True,
            )
            subprocess.run(
                ["git", "commit", "-m", "close-time reviewer fix"],
                cwd=td,
                capture_output=True,
                check=True,
                env=_bf.GIT_ENV,
            )

            close_common = self.scripts_dir / "close_common.py"
            result = subprocess.run(
                [
                    sys.executable,
                    str(close_common),
                    "diff-command",
                    "--target",
                    "main",
                    "--source",
                    "feature-x",
                ],
                cwd=td,
                capture_output=True,
                text=True,
                env=_bf.GIT_ENV,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            emitted = result.stdout.strip()
            self.assertEqual(emitted, "git diff main...feature-x")
            self.assertNotIn("gh pr diff", emitted)
            self.assertNotIn("HEAD", emitted)

            executed = subprocess.run(
                emitted.split(),
                cwd=td,
                capture_output=True,
                text=True,
                env=_bf.GIT_ENV,
            )
            self.assertEqual(executed.returncode, 0, executed.stderr)
            self.assertIn("POST_PUSH_FIX", executed.stdout)


if __name__ == "__main__":
    unittest.main()
