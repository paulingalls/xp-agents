#!/usr/bin/env python3
"""Tests for scripts/pre_tool_echo_gate.py — echo-enforcement PreToolUse hook.

Contract:
- When no .pending-render-* marker exists for the calling agent, the hook
  returns None without reading the transcript (fast path).
- When a marker exists and the transcript's assistant text contains every
  required phrase (e.g. "Shared Mental Model" + "Curated View"), the marker
  is consumed (deleted) and the hook returns None. Markdown and em-dash
  are NOT required — the gate is a "did you forget?" reminder, not a
  format enforcer.
- When a marker exists but at least one required phrase is absent from
  assistant text, the hook raises BlockedError.
- Only role=='assistant' text blocks are scanned. tool_use and tool_result
  blocks are NOT scanned — tool output containing the required phrases
  does not clear the marker.
- Recursion: when input_data.agent_type starts with 'xp-', the hook returns
  None immediately (our own agent hooks never trigger the gate).
- Per-agent isolation: each agent sees only its own .pending-render-*-{agent_id}
  marker. Another agent's marker does not block the current agent.
- Fail-open: missing transcript_path OR unreadable transcript file → None.
"""

import json
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
from conftest import _HookTestCase, _make_write_input

_SMM_SIG = marker_names.RENDER_SMM_SIGNATURE
_RETRO_SIG = marker_names.RENDER_RETRO_SIGNATURE


def _write_transcript(path: Path, entries: list[dict]) -> None:
    """Write a JSONL transcript with the given entries."""
    path.write_text("\n".join(json.dumps(e) for e in entries) + "\n", encoding="utf-8")


def _assistant_entry(text_blocks: list[str]) -> dict:
    return {
        "message": {
            "role": "assistant",
            "content": [{"type": "text", "text": t} for t in text_blocks],
        }
    }


def _assistant_with_tool_result(result_text: str) -> dict:
    """Assistant entry whose content includes a tool_result block carrying
    the given text — tool_result must NOT clear the gate."""
    return {
        "message": {
            "role": "assistant",
            "content": [
                {"type": "tool_use", "id": "t1", "name": "Bash"},
                {"type": "tool_result", "id": "t1", "content": result_text},
            ],
        }
    }


def _user_entry(text: str) -> dict:
    return {
        "message": {
            "role": "user",
            "content": [{"type": "text", "text": text}],
        }
    }


class TestEchoGateNoMarker(_HookTestCase):
    """With no pending markers, the gate returns None immediately."""

    def test_no_marker_skips_fast(self):
        transcript = self.smm_dir / "transcript.jsonl"
        # Intentionally do NOT write the transcript — the fast path should
        # return before trying to read it.
        result = pre_tool_echo_gate.run(
            _make_write_input(transcript_path=str(transcript)),
            smm_dir=self.smm_dir,
        )
        self.assertIsNone(result)


class TestEchoGateXpRecursion(_HookTestCase):
    """xp-* agents skip the gate to prevent recursion."""

    def test_xp_agent_skips_even_with_marker(self):
        markers.marker_write(
            self.smm_dir, markers.PENDING_RENDER_SMM, _SMM_SIG + "\n", "main"
        )
        result = pre_tool_echo_gate.run(
            _make_write_input(agent_type="xp-housekeeping"),
            smm_dir=self.smm_dir,
        )
        self.assertIsNone(result)
        # Marker must remain (xp agent didn't consume it).
        self.assertTrue(
            markers.marker_exists(self.smm_dir, markers.PENDING_RENDER_SMM, "main")
        )


class TestEchoGateSignaturePresent(_HookTestCase):
    """Signature present in assistant text consumes the marker."""

    def test_smm_signature_echoed_consumes_marker(self):
        markers.marker_write(
            self.smm_dir, markers.PENDING_RENDER_SMM, _SMM_SIG + "\n", "main"
        )
        transcript = self.smm_dir / "transcript.jsonl"
        _write_transcript(
            transcript,
            [
                _user_entry("Run housekeeping."),
                _assistant_entry(
                    [f"Here is the rendered SMM:\n\n{_SMM_SIG}\n\n## Intent\n- Ship\n"]
                ),
            ],
        )
        result = pre_tool_echo_gate.run(
            _make_write_input(transcript_path=str(transcript)),
            smm_dir=self.smm_dir,
        )
        self.assertIsNone(result)
        self.assertFalse(
            markers.marker_exists(self.smm_dir, markers.PENDING_RENDER_SMM, "main")
        )

    def test_retro_signature_echoed_consumes_marker(self):
        markers.marker_write(
            self.smm_dir, markers.PENDING_RENDER_RETRO, _RETRO_SIG + "\n", "main"
        )
        transcript = self.smm_dir / "transcript.jsonl"
        _write_transcript(
            transcript,
            [
                _assistant_entry([f"Retro:\n{_RETRO_SIG}\n## Keep\n- pair review\n"]),
            ],
        )
        result = pre_tool_echo_gate.run(
            _make_write_input(transcript_path=str(transcript)),
            smm_dir=self.smm_dir,
        )
        self.assertIsNone(result)
        self.assertFalse(
            markers.marker_exists(self.smm_dir, markers.PENDING_RENDER_RETRO, "main")
        )


class TestEchoGateSignatureMissing(_HookTestCase):
    """Signature absent from assistant text blocks the tool call."""

    def test_signature_missing_raises_blocked_error(self):
        markers.marker_write(
            self.smm_dir, markers.PENDING_RENDER_SMM, _SMM_SIG + "\n", "main"
        )
        transcript = self.smm_dir / "transcript.jsonl"
        _write_transcript(
            transcript,
            [
                _user_entry("Run housekeeping."),
                _assistant_entry(["OK I'll get on that."]),
            ],
        )
        with self.assertRaises(_common.BlockedError) as ctx:
            pre_tool_echo_gate.run(
                _make_write_input(transcript_path=str(transcript)),
                smm_dir=self.smm_dir,
            )
        self.assertIn("Unechoed render", str(ctx.exception))
        # Marker must remain so the next tool call can still clear it.
        self.assertTrue(
            markers.marker_exists(self.smm_dir, markers.PENDING_RENDER_SMM, "main")
        )


class TestEchoGatePlainTextPhrases(_HookTestCase):
    """Loose check: plain-text phrases clear the gate even without markdown.

    The gate looks for two distinctive phrases, not the exact markdown line.
    If the agent echoes the SMM with a paraphrased intro, a different
    heading level, an en-dash, or straight ASCII punctuation, the phrases
    still match and the marker clears. Purpose of the gate is to remind
    the agent if it forgot — not to police exact formatting.
    """

    def test_smm_phrases_without_markdown_clear_marker(self):
        markers.marker_write(
            self.smm_dir, markers.PENDING_RENDER_SMM, _SMM_SIG + "\n", "main"
        )
        transcript = self.smm_dir / "transcript.jsonl"
        _write_transcript(
            transcript,
            [
                _assistant_entry(
                    [
                        "Here's the Shared Mental Model, Curated View "
                        "from the housekeeper: intent, constraints, risks..."
                    ]
                ),
            ],
        )
        result = pre_tool_echo_gate.run(
            _make_write_input(transcript_path=str(transcript)),
            smm_dir=self.smm_dir,
        )
        self.assertIsNone(result)
        self.assertFalse(
            markers.marker_exists(self.smm_dir, markers.PENDING_RENDER_SMM, "main")
        )

    def test_retro_phrases_without_markdown_clear_marker(self):
        markers.marker_write(
            self.smm_dir, markers.PENDING_RENDER_RETRO, _RETRO_SIG + "\n", "main"
        )
        transcript = self.smm_dir / "transcript.jsonl"
        _write_transcript(
            transcript,
            [
                _assistant_entry(
                    [
                        "Rendering the XP Retrospective (Keep / Fix / Try) "
                        "from the analyst..."
                    ]
                ),
            ],
        )
        result = pre_tool_echo_gate.run(
            _make_write_input(transcript_path=str(transcript)),
            smm_dir=self.smm_dir,
        )
        self.assertIsNone(result)
        self.assertFalse(
            markers.marker_exists(self.smm_dir, markers.PENDING_RENDER_RETRO, "main")
        )

    def test_smm_only_one_phrase_still_blocks(self):
        """Drive-by mention of just 'Shared Mental Model' doesn't clear."""
        markers.marker_write(
            self.smm_dir, markers.PENDING_RENDER_SMM, _SMM_SIG + "\n", "main"
        )
        transcript = self.smm_dir / "transcript.jsonl"
        _write_transcript(
            transcript,
            [
                _assistant_entry(
                    ["Let me update the Shared Mental Model for sprint-006."]
                ),
            ],
        )
        with self.assertRaises(_common.BlockedError):
            pre_tool_echo_gate.run(
                _make_write_input(transcript_path=str(transcript)),
                smm_dir=self.smm_dir,
            )
        self.assertTrue(
            markers.marker_exists(self.smm_dir, markers.PENDING_RENDER_SMM, "main")
        )


class TestEchoGateToolResultIgnored(_HookTestCase):
    """Signature appearing only in a tool_result block does NOT clear the gate."""

    def test_tool_result_block_does_not_clear(self):
        markers.marker_write(
            self.smm_dir, markers.PENDING_RENDER_SMM, _SMM_SIG + "\n", "main"
        )
        transcript = self.smm_dir / "transcript.jsonl"
        _write_transcript(
            transcript,
            [
                _user_entry("Run housekeeping."),
                _assistant_with_tool_result(
                    f"SMM output:\n{_SMM_SIG}\n## Intent\n- Ship\n"
                ),
                _assistant_entry(["Done, nothing more to do."]),
            ],
        )
        with self.assertRaises(_common.BlockedError) as ctx:
            pre_tool_echo_gate.run(
                _make_write_input(transcript_path=str(transcript)),
                smm_dir=self.smm_dir,
            )
        self.assertIn("Unechoed render", str(ctx.exception))
        self.assertTrue(
            markers.marker_exists(self.smm_dir, markers.PENDING_RENDER_SMM, "main")
        )


class TestEchoGatePerAgent(_HookTestCase):
    """Markers are per-agent — teammate-a's marker does not block teammate-b."""

    def test_other_agent_marker_does_not_block(self):
        markers.marker_write(
            self.smm_dir, markers.PENDING_RENDER_SMM, _SMM_SIG + "\n", "teammate-a"
        )
        transcript = self.smm_dir / "transcript.jsonl"
        _write_transcript(transcript, [_user_entry("hello")])
        result = pre_tool_echo_gate.run(
            _make_write_input(
                agent_id="teammate-b",
                cwd="/tmp/some-worktree/teammate-b",
                transcript_path=str(transcript),
            ),
            smm_dir=self.smm_dir,
        )
        self.assertIsNone(result)
        # Other agent's marker must remain untouched.
        self.assertTrue(
            markers.marker_exists(
                self.smm_dir, markers.PENDING_RENDER_SMM, "teammate-a"
            )
        )


class TestEchoGateFailOpen(_HookTestCase):
    """Missing or unreadable transcript → fail-open (None)."""

    def test_missing_transcript_path_fails_open(self):
        markers.marker_write(
            self.smm_dir, markers.PENDING_RENDER_SMM, _SMM_SIG + "\n", "main"
        )
        result = pre_tool_echo_gate.run(
            _make_write_input(),  # no transcript_path
            smm_dir=self.smm_dir,
        )
        self.assertIsNone(result)
        # Marker must remain (fail-open does not consume).
        self.assertTrue(
            markers.marker_exists(self.smm_dir, markers.PENDING_RENDER_SMM, "main")
        )

    def test_unreadable_transcript_fails_open(self):
        markers.marker_write(
            self.smm_dir, markers.PENDING_RENDER_SMM, _SMM_SIG + "\n", "main"
        )
        missing = self.smm_dir / "does-not-exist.jsonl"
        result = pre_tool_echo_gate.run(
            _make_write_input(transcript_path=str(missing)),
            smm_dir=self.smm_dir,
        )
        self.assertIsNone(result)
        # Marker must remain (fail-open does not consume).
        self.assertTrue(
            markers.marker_exists(self.smm_dir, markers.PENDING_RENDER_SMM, "main")
        )


class TestEchoGateDualPending(_HookTestCase):
    """Kickoff drops both retro + SMM markers — exercise both-pending behavior.

    The real workflow renders retrospective and curated SMM in the same turn,
    so both markers can coexist. Verify all three combinations: both echoed,
    one echoed (other blocks), neither echoed (first blocks, no consume).
    """

    def _seed_both_markers(self) -> None:
        markers.marker_write(
            self.smm_dir, markers.PENDING_RENDER_RETRO, _RETRO_SIG + "\n", "main"
        )
        markers.marker_write(
            self.smm_dir, markers.PENDING_RENDER_SMM, _SMM_SIG + "\n", "main"
        )

    def test_both_signatures_echoed_consumes_both(self):
        self._seed_both_markers()
        transcript = self.smm_dir / "transcript.jsonl"
        _write_transcript(
            transcript,
            [
                _assistant_entry(
                    [
                        f"Retro:\n{_RETRO_SIG}\n## Keep\n- pair review\n",
                        f"And SMM:\n{_SMM_SIG}\n## Intent\n- Ship\n",
                    ]
                ),
            ],
        )
        result = pre_tool_echo_gate.run(
            _make_write_input(transcript_path=str(transcript)),
            smm_dir=self.smm_dir,
        )
        self.assertIsNone(result)
        self.assertFalse(
            markers.marker_exists(self.smm_dir, markers.PENDING_RENDER_RETRO, "main")
        )
        self.assertFalse(
            markers.marker_exists(self.smm_dir, markers.PENDING_RENDER_SMM, "main")
        )

    def test_only_retro_echoed_consumes_retro_blocks_on_smm(self):
        self._seed_both_markers()
        transcript = self.smm_dir / "transcript.jsonl"
        _write_transcript(
            transcript,
            [
                _assistant_entry([f"Retro:\n{_RETRO_SIG}\n## Keep\n- pair\n"]),
            ],
        )
        with self.assertRaises(_common.BlockedError) as ctx:
            pre_tool_echo_gate.run(
                _make_write_input(transcript_path=str(transcript)),
                smm_dir=self.smm_dir,
            )
        self.assertIn("SMM", str(ctx.exception))
        # Retro marker consumed (echo verified); SMM marker remains so the
        # next attempt can clear it once the SMM signature is echoed too.
        self.assertFalse(
            markers.marker_exists(self.smm_dir, markers.PENDING_RENDER_RETRO, "main")
        )
        self.assertTrue(
            markers.marker_exists(self.smm_dir, markers.PENDING_RENDER_SMM, "main")
        )

    def test_neither_echoed_blocks_on_first_no_consume(self):
        self._seed_both_markers()
        transcript = self.smm_dir / "transcript.jsonl"
        _write_transcript(
            transcript,
            [
                _assistant_entry(["OK, I'll get to it."]),
            ],
        )
        with self.assertRaises(_common.BlockedError) as ctx:
            pre_tool_echo_gate.run(
                _make_write_input(transcript_path=str(transcript)),
                smm_dir=self.smm_dir,
            )
        # Retro is iterated first, so it is the one cited in the block reason.
        self.assertIn("retrospective", str(ctx.exception))
        # Neither marker should be consumed — block fires before either echo.
        self.assertTrue(
            markers.marker_exists(self.smm_dir, markers.PENDING_RENDER_RETRO, "main")
        )
        self.assertTrue(
            markers.marker_exists(self.smm_dir, markers.PENDING_RENDER_SMM, "main")
        )


if __name__ == "__main__":
    unittest.main()
