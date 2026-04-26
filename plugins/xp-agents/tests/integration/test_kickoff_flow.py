#!/usr/bin/env python3
"""E2E: preload → SubagentStart handler → render CLI marker → echo-gate clear.

Exercises the two inline-agent paths that will drive kickoff after story-002
(xp-retrospective and xp-housekeeper), wiring them together to verify the
full chain: handler advertises SMM_DIR + data-file paths, the render CLI
drops the .pending-render-* marker carrying the signature, and the echo
gate consumes the marker only when the signature appears in an assistant
text block (not a tool_result).
"""

import json
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import _common
import marker_names
import markers
import pre_tool_echo_gate
import subagent_start
from conftest import _IntegrationTestCase, _make_write_input, write_smm_fixture

_SMM_CLI = Path(__file__).parent.parent.parent / "smm" / "smm_cli.py"
_RETRO_CLI = Path(__file__).parent.parent.parent / "smm" / "retro_cli.py"


def _write_transcript(path: Path, entries: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(e) for e in entries) + "\n", encoding="utf-8")


def _assistant_entry(text_blocks: list[str]) -> dict:
    return {
        "message": {
            "role": "assistant",
            "content": [{"type": "text", "text": t} for t in text_blocks],
        }
    }


def _assistant_with_tool_result(text: str) -> dict:
    return {
        "message": {
            "role": "assistant",
            "content": [
                {"type": "tool_use", "id": "t1", "name": "Bash"},
                {"type": "tool_result", "id": "t1", "content": text},
            ],
        }
    }


class TestKickoffFlowE2E(_IntegrationTestCase):
    """Full inline-agent chain for retro and housekeeper kickoff steps."""

    AGENT_ID = "main"

    def setUp(self):
        super().setUp()
        write_smm_fixture(
            self.smm_dir,
            intent=[("Ship v1", "goal")],
            constraints=[("Python 3.10+ only", "convention")],
            risks=[("Auth fragile", "concern", "problem")],
            wisdom=["TDD always"],
        )

    def _run_cli(self, cli_path: Path, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["python3", str(cli_path), "--smm-dir", str(self.smm_dir), *args],
            capture_output=True,
            text=True,
            cwd=self.tmpdir,
            env=self._test_env,
        )

    def _gate(self, transcript: Path) -> None:
        pre_tool_echo_gate.run(
            _make_write_input(agent_id=self.AGENT_ID, transcript_path=str(transcript)),
            smm_dir=self.smm_dir,
        )

    def test_retrospective_chain(self):
        """Retro handler → retro_cli render → echo-gate clears on signature."""
        # SessionStart would have written .retro-input.json; fake it.
        (self.smm_dir / _common.RETRO_INPUT_FILENAME).write_text("{}")
        retro_path = self.smm_dir / "retrospectives" / "2026-04-18.json"
        retro_path.parent.mkdir(exist_ok=True)
        retro_path.write_text(
            json.dumps({"keep": [{"content": "pair review"}], "fix": [], "try": []})
        )

        ctx = subagent_start.run(
            {
                "session_id": "t",
                "agent_id": self.AGENT_ID,
                "agent_type": "xp-agents:xp-retrospective",
            },
            smm_dir=self.smm_dir,
        )
        self.assertIsNotNone(ctx)
        self.assertIn(f"SMM_DIR={self.smm_dir}", ctx)
        self.assertIn(f"RETRO_INPUT={self.smm_dir / _common.RETRO_INPUT_FILENAME}", ctx)

        result = self._run_cli(
            _RETRO_CLI, "render", str(retro_path), "--agent-id", self.AGENT_ID
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(marker_names.RENDER_RETRO_SIGNATURE, result.stdout)
        self.assertTrue(
            markers.marker_exists(
                self.smm_dir, markers.PENDING_RENDER_RETRO, self.AGENT_ID
            )
        )

        transcript = self.smm_dir / "transcript.jsonl"
        _write_transcript(
            transcript,
            [
                _assistant_entry(
                    [
                        "Here is the retrospective:\n\n"
                        + marker_names.RENDER_RETRO_SIGNATURE
                        + "\n## Keep\n- pair review\n"
                    ]
                )
            ],
        )
        self._gate(transcript)
        self.assertFalse(
            markers.marker_exists(
                self.smm_dir, markers.PENDING_RENDER_RETRO, self.AGENT_ID
            )
        )

    def test_housekeeper_chain(self):
        """Housekeeper handler → smm_cli render → echo-gate clears on signature."""
        ctx = subagent_start.run(
            {
                "session_id": "t",
                "agent_id": self.AGENT_ID,
                "agent_type": "xp-agents:xp-housekeeper",
            },
            smm_dir=self.smm_dir,
        )
        self.assertIsNotNone(ctx)
        curation_file = self.smm_dir / ".curation-input.json"
        self.assertTrue(curation_file.exists())
        self.assertIn(f"SMM_DIR={self.smm_dir}", ctx)
        self.assertIn(f"CURATION_INPUT={curation_file}", ctx)

        result = self._run_cli(_SMM_CLI, "render", "--agent-id", self.AGENT_ID)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(marker_names.RENDER_SMM_SIGNATURE, result.stdout)
        self.assertTrue(
            markers.marker_exists(
                self.smm_dir, markers.PENDING_RENDER_SMM, self.AGENT_ID
            )
        )

        transcript = self.smm_dir / "transcript.jsonl"
        _write_transcript(
            transcript,
            [
                _assistant_entry(
                    [
                        f"Here is the curated SMM:\n\n"
                        f"{marker_names.RENDER_SMM_SIGNATURE}\n## Intent\n- Ship v1\n"
                    ]
                )
            ],
        )
        self._gate(transcript)
        self.assertFalse(
            markers.marker_exists(
                self.smm_dir, markers.PENDING_RENDER_SMM, self.AGENT_ID
            )
        )

    def test_tool_result_signature_does_not_clear_gate(self):
        """Counter-test: signature only in tool_result leaves the marker pending."""
        markers.marker_write(
            self.smm_dir,
            markers.PENDING_RENDER_SMM,
            marker_names.RENDER_SMM_SIGNATURE + "\n",
            self.AGENT_ID,
        )
        transcript = self.smm_dir / "transcript.jsonl"
        _write_transcript(
            transcript,
            [
                _assistant_with_tool_result(
                    "CLI output:\n"
                    + marker_names.RENDER_SMM_SIGNATURE
                    + "\n## Intent\n- Ship\n"
                ),
                _assistant_entry(["Done, moving on."]),
            ],
        )
        result = pre_tool_echo_gate.run(
            _make_write_input(agent_id=self.AGENT_ID, transcript_path=str(transcript)),
            smm_dir=self.smm_dir,
        )
        self.assertIsInstance(result, str)
        assert result is not None
        self.assertIn("Unechoed render", result)
        self.assertTrue(
            markers.marker_exists(
                self.smm_dir, markers.PENDING_RENDER_SMM, self.AGENT_ID
            )
        )


if __name__ == "__main__":
    unittest.main()
