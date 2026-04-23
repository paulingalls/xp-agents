#!/usr/bin/env python3
"""End-to-end tests for the resolves-trailer feedback loop.

Covers two paths:
- pre_tool_bash emits the resolves_probe_shown status event when a
  commit's staged files overlap an open concern.
- retrospective.py computes resolves_link_rate from code commits with
  Resolves-Event trailers in a sprint window.

The standard integration-test scaffolding (_IntegrationTestCase) gives us
a real temp git repo and a real SMM dir, so commit events flow through
the actual pipeline rather than mocks.
"""

import json
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import security
from conftest import _IntegrationTestCase, _s, _sprint_json, make_event


class TestResolvesLinkFeedbackLoop(_IntegrationTestCase):
    def _seed_commit_gates(self) -> None:
        """Seed markers to bypass commit gates (security triage)."""
        security.write_security_triaged(self.smm_dir, agent_id="main")

    def test_pre_commit_emits_probe_event_on_file_overlap(self):
        """E2E: pre-commit with staged files overlapping concern → probe event."""
        concern = make_event(
            "concern",
            id="abc123def456",
            content="scripts/foo.py is leaking state",
            files=["scripts/foo.py"],
            severity="medium",
        )
        self._seed_events([concern])
        self._seed_commit_gates()

        (self.tmpdir / "scripts").mkdir(exist_ok=True)
        (self.tmpdir / "scripts" / "foo.py").write_text("print('hi')\n")
        subprocess.run(
            ["git", "add", "scripts/foo.py"],
            cwd=self.tmpdir,
            capture_output=True,
            check=True,
        )

        result = self._run_script(
            "pre_tool_bash.py",
            {
                "session_id": "int-test",
                "tool_name": "Bash",
                "tool_input": {"command": "git commit -m 'Add foo module'"},
                "cwd": str(self.tmpdir),
                "agent_id": "main",
            },
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)

        events = self._read_events()
        probes = [
            e
            for e in events
            if e.get("type") == "status"
            and e.get("content", "").startswith("resolves_probe_shown:")
        ]
        self.assertEqual(len(probes), 1)
        metadata = probes[0].get("metadata") or {}
        self.assertEqual(metadata.get("probe_candidates"), ["abc123def456"])

    def test_retro_reports_resolves_link_rate_for_sprint(self):
        """E2E: sprint with code commit + resolves trailer → resolves_link_rate > 0."""
        (self.smm_dir / "sprint.json").write_text(
            _sprint_json(
                [
                    _s(
                        "story-001",
                        "test",
                        "done",
                        file_domain=["scripts/foo.py"],
                    )
                ],
                sprint_id="sprint-e2e",
                started="2026-03-14",
                goal="verify link rate",
            )
        )

        # Seed the sprint window: start, probe, matching commit, end.
        self._seed_events(
            [
                make_event(
                    "sprint",
                    ts="2026-03-14T09:00:00+00:00",
                    content="sprint-e2e start",
                    metadata={"sprint_id": "sprint-e2e", "action": "start"},
                ),
                make_event(
                    "status",
                    ts="2026-03-14T10:00:00+00:00",
                    content="resolves_probe_shown: 1 candidates",
                    metadata={
                        "probe_candidates": ["abc123def456"],
                        "commit_hash": "deadbeef",
                    },
                    working_on=[],
                ),
                make_event(
                    "commit",
                    ts="2026-03-14T10:05:00+00:00",
                    content="fix leak",
                    files=["scripts/foo.py"],
                    metadata={
                        "code_commit": True,
                        "commit_hash": "cafebabe",
                        "resolves": ["abc123def456"],
                        "story_id": "story-001",
                    },
                ),
                make_event(
                    "sprint",
                    ts="2026-03-14T11:00:00+00:00",
                    content="sprint-e2e end",
                    metadata={"sprint_id": "sprint-e2e", "action": "end"},
                ),
            ]
        )

        result = self._run_script(
            "retrospective.py",
            {"session_id": "int-test", "source": "startup"},
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)

        retro_input = json.loads((self.smm_dir / ".retro-input.json").read_text())
        sizing = retro_input.get("sizing_analysis") or {}
        self.assertEqual(sizing.get("resolves_trailer_total"), 1)
        self.assertEqual(sizing.get("resolves_trailer_hits"), 1)
        self.assertEqual(sizing.get("resolves_link_rate"), 1.0)


if __name__ == "__main__":
    unittest.main()
