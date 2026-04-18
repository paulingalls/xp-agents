#!/usr/bin/env python3
"""Integration tests: maintenance, curation, and coordination.

Tests for compact, repair, migrate, quality gate, load context,
prepare curation, save SMM, coordination, and retro preload.
"""

import json
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from conftest import _IntegrationTestCase, make_event

_SMM_CLI = Path(__file__).parent.parent.parent / "smm" / "smm_cli.py"


def _run_save_smm(
    smm_dir: Path, cwd: Path, content: str
) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["python3", str(_SMM_CLI), "--smm-dir", str(smm_dir), "save"],
        input=content,
        capture_output=True,
        text=True,
        cwd=cwd,
    )


class TestCompactIntegration(_IntegrationTestCase):
    """Subprocess-level tests for compact.py."""

    def test_compact_subprocess_run(self):
        """Run compact as subprocess, verify events compacted."""
        events = []
        for s in range(4):
            events.extend(
                [make_event(content=f"s{s}", ts=f"2026-03-{s + 1:02d}T00:00:00+00:00")]
            )
            events.append(
                make_event(
                    "session_end",
                    content=f"end-{s}",
                    working_on=[],
                    ts=f"2026-03-{s + 1:02d}T23:59:59+00:00",
                )
            )
        self._seed_events(events)
        original_count = len(events)

        # Write curation watermark so compaction runs
        sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))
        from materialize import write_curation_watermark

        write_curation_watermark(self.smm_dir, original_count, "xp-housekeeping")

        result = subprocess.run(
            [
                "python3",
                str(Path(__file__).parent.parent.parent / "smm" / "compact.py"),
                "--smm-dir",
                str(self.smm_dir),
            ],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("archived", result.stdout)

        # Fewer events after compaction
        remaining = self._read_events()
        self.assertLess(len(remaining), original_count)

    def test_compact_then_session_start(self):
        """After compact, session_start can still read the log."""
        events = [
            make_event("goal", content="Ship v1"),
            make_event("session_end", content="end", working_on=[]),
        ]
        self._seed_events(events)

        # Compact
        subprocess.run(
            [
                "python3",
                str(Path(__file__).parent.parent.parent / "smm" / "compact.py"),
                "--smm-dir",
                str(self.smm_dir),
            ],
            capture_output=True,
            text=True,
            check=True,
        )

        # Session start should still work
        r = self._run_script(
            "session_start.py",
            {
                "session_id": "post-compact",
                "source": "compact",
            },
        )
        self.assertEqual(r.returncode, 0)
        output = json.loads(r.stdout)
        ctx = output["hookSpecificOutput"]["additionalContext"]
        self.assertIn("Shared Mental Model", ctx)


class TestRepairIntegration(_IntegrationTestCase):
    """Subprocess-level tests for repair.py."""

    def test_repair_corrupted_file(self):
        """Repair a file with bad lines, verify clean output."""
        good = make_event(content="good")
        lines = [json.dumps(good), "bad json {{", '{"missing": "id"}']
        (self.smm_dir / "events.jsonl").write_text("\n".join(lines) + "\n")

        result = subprocess.run(
            [
                "python3",
                str(Path(__file__).parent.parent.parent / "smm" / "repair.py"),
                "--smm-dir",
                str(self.smm_dir),
            ],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("malformed", result.stdout)

        # Verify clean log
        remaining = self._read_events()
        self.assertEqual(len(remaining), 1)
        self.assertEqual(remaining[0]["content"], "good")

    def test_repair_dry_run(self):
        """Dry run reports problems without modifying file."""
        lines = [json.dumps(make_event()), "bad"]
        (self.smm_dir / "events.jsonl").write_text("\n".join(lines) + "\n")

        result = subprocess.run(
            [
                "python3",
                str(Path(__file__).parent.parent.parent / "smm" / "repair.py"),
                "--dry-run",
                "--smm-dir",
                str(self.smm_dir),
            ],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("DRY RUN", result.stdout)

        # File unchanged (still has bad line)
        raw = (self.smm_dir / "events.jsonl").read_text()
        self.assertIn("bad", raw)

    def test_repair_then_materialize(self):
        """After repair, materialize works correctly."""
        good = make_event("goal", content="Ship v1")
        lines = [json.dumps(good), "corrupt line"]
        (self.smm_dir / "events.jsonl").write_text("\n".join(lines) + "\n")

        subprocess.run(
            [
                "python3",
                str(Path(__file__).parent.parent.parent / "smm" / "repair.py"),
                "--smm-dir",
                str(self.smm_dir),
            ],
            capture_output=True,
            text=True,
            check=True,
        )

        # Materialize should work
        r = subprocess.run(
            [
                "python3",
                str(Path(__file__).parent.parent.parent / "smm" / "materialize.py"),
                "--smm-dir",
                str(self.smm_dir),
            ],
            capture_output=True,
            text=True,
        )
        self.assertEqual(r.returncode, 0)


class TestMigrateIntegration(_IntegrationTestCase):
    """Subprocess-level tests for migrate.py."""

    def test_migrate_subprocess_run(self):
        """Run migrate as subprocess."""
        events = [make_event(ts="2026-03-12T00:00:00")]
        self._seed_events(events)

        result = subprocess.run(
            [
                "python3",
                str(Path(__file__).parent.parent.parent / "smm" / "migrate.py"),
                "--smm-dir",
                str(self.smm_dir),
            ],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("migrated", result.stdout)

        # Verify events are v2
        migrated = self._read_events()
        self.assertEqual(migrated[0]["schema_version"], 2)

    def test_migrate_idempotent(self):
        """Running migrate twice produces same result."""
        events = [make_event(ts="2026-03-12T00:00:00")]
        self._seed_events(events)

        for _ in range(2):
            result = subprocess.run(
                [
                    "python3",
                    str(Path(__file__).parent.parent.parent / "smm" / "migrate.py"),
                    "--smm-dir",
                    str(self.smm_dir),
                ],
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0)

        migrated = self._read_events()
        self.assertEqual(len(migrated), 1)
        self.assertEqual(migrated[0]["schema_version"], 2)


# TestLoadContext removed — load_context.sh deleted in M5 cleanup.
# Context loading is now handled by kickoff_done.py (SMM + guide injection).


class TestSaveSMMIntegration(_IntegrationTestCase):
    """Integration test for smm_cli.py save command."""

    def _run_save_smm(self, content: str) -> subprocess.CompletedProcess:
        return _run_save_smm(self.smm_dir, self.tmpdir, content)

    def test_pipe_json_writes_file(self):
        """Pipe JSON into smm_cli.py save, verify file written."""
        import smm_schema

        data = smm_schema.empty_smm()
        content = json.dumps(data)
        result = self._run_save_smm(content)
        self.assertEqual(result.returncode, 0, result.stderr)
        smm_file = self.smm_dir / "shared_mental_model.json"
        self.assertTrue(smm_file.exists())
        written = json.loads(smm_file.read_text())
        self.assertEqual(written, data)

    def test_watermark_updated_after_save(self):
        """Watermark reflects event count after save."""
        import smm_schema

        self._seed_events(
            [
                make_event("goal", content="Ship v1"),
                make_event("concern", content="No tests"),
                make_event("decision", topic="db", content="Use PG"),
            ]
        )
        result = self._run_save_smm(json.dumps(smm_schema.empty_smm()))
        self.assertEqual(result.returncode, 0, result.stderr)
        wm_file = self.smm_dir / ".curation-watermark"
        self.assertTrue(wm_file.exists())
        wm = json.loads(wm_file.read_text())
        self.assertEqual(wm["event_count"], 3)


class TestHousekeepingRoundTripIntegration(_IntegrationTestCase):
    """prepare_curation → hand-crafted merge → smm_cli save → re-prepare flow.

    Exercises the full housekeeping data path that `TestPrepareCurationIntegration`
    (static prepare) and `TestSaveSMMIntegration` (static save) don't chain
    together. Closes the gap that motivated story-003: verifying the
    watermark-driven delta actually resets after save.
    """

    def test_prepare_curation_pipe_save_smm_round_trip(self):
        """prepare → merge → save → re-prepare reflects the saved SMM.

        init.sh seeds the SMM with 7 constraints + 8 wisdom entries. A
        realistic housekeeper merge must preserve those seed entries and
        add new curated content on top — anything else would reproduce
        the exact seed-wipe bug story-003 fixed. This test verifies both
        sides of the contract: save preserves existing pillars AND
        re-prepare reflects the new additions.
        """
        self._seed_events(
            [
                make_event("goal", content="Ship v1"),
                make_event("concern", content="No tests"),
                make_event("decision", topic="db", content="Use PG"),
            ]
        )

        import materialize

        data = materialize.prepare_curation_data(self.smm_dir)
        initial_constraints = data["health"]["constraints_count"]
        initial_wisdom = data["health"]["wisdom_count"]
        self.assertGreater(initial_constraints, 0, "seed should populate constraints")
        self.assertGreater(initial_wisdom, 0, "seed should populate wisdom")
        self.assertEqual(data["health"]["intent_count"], 0)

        smm = data["current_smm"]
        import secrets

        new_intent_id = secrets.token_hex(6)
        smm["intent"].append(
            {
                "id": new_intent_id,
                "content": "Curated: Ship v1",
                "source": "curated",
                "ts": "2026-04-01T00:00:00+00:00",
                "type": "goal",
            }
        )

        save_result = _run_save_smm(self.smm_dir, self.tmpdir, json.dumps(smm))
        self.assertEqual(save_result.returncode, 0, save_result.stderr)
        smm_file = self.smm_dir / "shared_mental_model.json"
        self.assertTrue(smm_file.exists())
        written = json.loads(smm_file.read_text())
        self.assertEqual(len(written["intent"]), 1)
        self.assertEqual(written["intent"][0]["content"], "Curated: Ship v1")
        # Round-trip safety: the id we appended survives the save path unchanged.
        self.assertEqual(written["intent"][0]["id"], new_intent_id)
        # Seed pillars preserved through the save — the invariant story-003 enforces.
        self.assertEqual(len(written["constraints"]), initial_constraints)
        self.assertEqual(len(written["wisdom"]), initial_wisdom)

        wm_file = self.smm_dir / ".curation-watermark"
        self.assertTrue(wm_file.exists())
        wm = json.loads(wm_file.read_text())
        self.assertEqual(wm["event_count"], 3)

        data_b = materialize.prepare_curation_data(self.smm_dir)
        self.assertEqual(data_b["health"]["intent_count"], 1)
        self.assertEqual(data_b["health"]["constraints_count"], initial_constraints)
        self.assertEqual(data_b["health"]["wisdom_count"], initial_wisdom)
        intent_contents = [e["content"] for e in data_b["current_smm"]["intent"]]
        self.assertIn("Curated: Ship v1", intent_contents)


class TestCoordinationIntegration(_IntegrationTestCase):
    """Integration test for .coordination.json lifecycle."""

    def _read_coordination(self) -> dict:
        coord_path = self.smm_dir / ".coordination.json"
        if not coord_path.exists():
            return {}
        return json.loads(coord_path.read_text())

    def test_post_tool_use_updates_coordination(self):
        """PostToolUse:Write creates .coordination.json entry."""
        input_data = {
            "session_id": "s1",
            "tool_name": "Write",
            "tool_input": {"file_path": "src/app.ts", "content": "x"},
            "agent_id": "main",
        }
        result = self._run_script("post_tool_use.py", input_data)
        self.assertEqual(result.returncode, 0, result.stderr)
        coord = self._read_coordination()
        self.assertIn("main", coord)
        self.assertIn("working_on", coord["main"])

    def test_two_agents_both_tracked(self):
        """Two agents writing different files both appear."""
        for agent, file in [
            ("main", "src/a.ts"),
            ("agent-2", "src/b.ts"),
        ]:
            input_data = {
                "session_id": "s1",
                "tool_name": "Write",
                "tool_input": {"file_path": file, "content": "x"},
                "agent_id": agent,
            }
            self._run_script("post_tool_use.py", input_data)
        coord = self._read_coordination()
        self.assertIn("main", coord)
        self.assertIn("agent-2", coord)

    def test_session_end_clears_agent(self):
        """SessionEnd removes agent from .coordination.json."""
        # First, create a coordination entry via PostToolUse
        post_input = {
            "session_id": "s1",
            "tool_name": "Write",
            "tool_input": {"file_path": "src/app.ts", "content": "x"},
            "agent_id": "main",
        }
        self._run_script("post_tool_use.py", post_input)
        coord = self._read_coordination()
        self.assertIn("main", coord)

        # Now end the session
        end_input = {
            "session_id": "s1",
            "reason": "clear",
            "agent_id": "main",
        }
        result = self._run_script("session_end.py", end_input)
        self.assertEqual(result.returncode, 0, result.stderr)
        coord = self._read_coordination()
        self.assertNotIn("main", coord)

    def test_pre_tool_write_detects_overlap(self):
        """PreToolWrite blocks when another agent works on the same file."""
        # Agent-2 writes to src/app.ts
        post_input = {
            "session_id": "s1",
            "tool_name": "Write",
            "tool_input": {"file_path": "src/app.ts", "content": "x"},
            "agent_id": "agent-2",
        }
        self._run_script("post_tool_use.py", post_input)

        # Main tries to Write to same file
        pre_input = {
            "session_id": "s1",
            "tool_name": "Write",
            "tool_input": {
                "file_path": "src/app.ts",
                "content": "y",
            },
            "agent_id": "main",
        }
        result = self._run_script("pre_tool_write.py", pre_input)
        # Should block (exit 2) with conflict message
        self.assertEqual(result.returncode, 2)
        self.assertIn("CONFLICT", result.stderr)
        self.assertIn("agent-2", result.stderr)


if __name__ == "__main__":
    unittest.main()
