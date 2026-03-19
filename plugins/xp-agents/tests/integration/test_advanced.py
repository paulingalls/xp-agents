#!/usr/bin/env python3
"""Integration tests: advanced scenarios (scaling, concurrency, maintenance).

Tests for compaction reinjection, large event logs, concurrent agent writes,
worktree sharing, empty project, watermark isolation, compact, repair, migrate,
quality gate, load context, curation, save SMM, coordination, and retro preload.
"""

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from conftest import _IntegrationTestCase, make_event


class TestCompactionReinjection(_IntegrationTestCase):
    """M7: After compaction, session_start re-injects full SMM."""

    def test_compact_reinjects_smm(self):
        """Seed → materialize → backup → truncate → session_start."""
        # 1. Seed events and materialize
        self._seed_events(
            [
                make_event(
                    "decision",
                    content="Use PostgreSQL",
                    topic="database",
                ),
                make_event("status", content="Working on DB"),
            ]
        )

        # 2. Run pre_compact to create backup
        self._run_script(
            "pre_compact.py",
            {"session_id": "compact-test"},
        )
        backups_dir = self.smm_dir / "backups"
        self.assertTrue(backups_dir.exists())

        # 3. Truncate events.jsonl (simulate compaction)
        (self.smm_dir / "events.jsonl").write_text("")

        # 4. Session start with compact source re-injects
        r = self._run_script(
            "session_start.py",
            {"session_id": "compact-test", "source": "compact"},
        )
        self.assertEqual(r.returncode, 0)
        output = json.loads(r.stdout)
        ctx = output["hookSpecificOutput"]["additionalContext"]
        # Should have SMM context (materialized from empty log)
        self.assertIn("Resume immediately", ctx)
        self.assertIn("smm-protocol", ctx)


class TestLargeEventLog(_IntegrationTestCase):
    """M7: 1000+ events — scripts complete without error."""

    def test_pre_tool_use_with_1000_events(self):
        """pre_tool_use.py completes with 1000 events."""
        self._seed_events([make_event(content=f"event-{i}") for i in range(1000)])
        result = self._run_script(
            "pre_tool_use.py",
            {
                "session_id": "stress",
                "tool_name": "Write",
                "tool_input": {"file_path": "src/app.ts"},
                "agent_id": "main",
                "cwd": str(self.tmpdir),
            },
        )
        self.assertEqual(result.returncode, 0)
        # Output should be valid JSON if non-empty
        if result.stdout.strip():
            output = json.loads(result.stdout)
            self.assertIn("hookSpecificOutput", output)

    def test_retrospective_with_1000_events(self):
        """retrospective.py handles large event set."""
        self._seed_events([make_event(content=f"event-{i}") for i in range(1000)])
        result = self._run_script(
            "retrospective.py",
            {"session_id": "stress", "source": "startup"},
        )
        self.assertEqual(result.returncode, 0)
        # Should produce retro output (1000 >> threshold of 5)
        output = json.loads(result.stdout)
        ctx = output["hookSpecificOutput"]["additionalContext"]
        self.assertIn("xp-retrospective", ctx)


class TestConcurrentAgentWrites(_IntegrationTestCase):
    """M7: Multiple agents writing events concurrently."""

    def test_concurrent_writes_no_corruption(self):
        """5 workers each run subagent lifecycle — no corruption."""
        from concurrent.futures import ThreadPoolExecutor

        def agent_lifecycle(agent_num: int) -> bool:
            """Run subagent_start → post_tool_use → subagent_stop."""
            aid = f"agent-{agent_num}"
            r1 = self._run_script(
                "subagent_start.py",
                {"session_id": "conc", "agent_id": aid},
            )
            r2 = self._run_script(
                "post_tool_use.py",
                {
                    "session_id": "conc",
                    "tool_name": "Write",
                    "tool_input": {
                        "file_path": f"src/f{agent_num}.ts",
                        "content": "x",
                    },
                    "tool_response": {"success": True},
                    "cwd": str(self.tmpdir),
                    "agent_id": aid,
                },
            )
            r3 = self._run_script(
                "subagent_stop.py",
                {
                    "session_id": "conc",
                    "agent_id": aid,
                    "last_assistant_message": "Done",
                },
            )
            return all(r.returncode in (0, 2) for r in (r1, r2, r3))

        with ThreadPoolExecutor(max_workers=5) as pool:
            futures = [pool.submit(agent_lifecycle, i) for i in range(5)]
            results = [f.result() for f in futures]

        self.assertTrue(all(results), "All agent lifecycles succeeded")

        # Verify no corruption: all events parse as valid JSON
        events = self._read_events()
        # At least 10 events (5 agents x 2 events each minimum)
        self.assertGreaterEqual(len(events), 10)
        # All events have required fields
        for e in events:
            self.assertIn("id", e)
            self.assertIn("type", e)
            self.assertIn("ts", e)
        # No duplicate IDs
        ids = [e["id"] for e in events]
        self.assertEqual(len(ids), len(set(ids)), "Duplicate IDs")


class TestWorktreeSharing(_IntegrationTestCase):
    """M7: Main repo + worktree share same SMM directory."""

    def _cleanup_worktree(self, wt_dir: Path, repo_dir: str):
        """Remove worktree and directory — safe to call even if already gone."""
        if Path(repo_dir).exists():
            subprocess.run(
                ["git", "worktree", "remove", "--force", str(wt_dir)],
                cwd=repo_dir,
                capture_output=True,
            )
        if wt_dir.exists():
            shutil.rmtree(wt_dir)

    def test_worktree_shares_project_id(self):
        """Git worktree derives same SMM path as main repo."""
        # Create worktree in a separate temp directory (not inside repo)
        wt_dir = Path(tempfile.mkdtemp())
        shutil.rmtree(wt_dir)  # git worktree add needs non-existent path
        r_branch = subprocess.run(
            ["git", "worktree", "add", str(wt_dir)],
            cwd=self.tmpdir,
            capture_output=True,
            text=True,
        )
        if r_branch.returncode != 0:
            self.skipTest(f"git worktree add failed: {r_branch.stderr}")

        # Ensure cleanup even if assertions fail (pass repo_dir as
        # string since self.tmpdir may be removed by tearDown first)
        self.addCleanup(self._cleanup_worktree, wt_dir, str(self.tmpdir))

        # Init SMM from both locations
        init_sh = Path(__file__).parent.parent.parent / "smm" / "init.sh"
        r_main = subprocess.run(
            ["bash", str(init_sh)],
            cwd=self.tmpdir,
            capture_output=True,
            text=True,
        )
        r_wt = subprocess.run(
            ["bash", str(init_sh)],
            cwd=wt_dir,
            capture_output=True,
            text=True,
        )

        self.assertEqual(r_main.returncode, 0)
        self.assertEqual(r_wt.returncode, 0)
        smm_main = r_main.stdout.strip()
        smm_wt = r_wt.stdout.strip()
        self.assertEqual(
            smm_main,
            smm_wt,
            "Main and worktree should share SMM dir",
        )

        # Seed events from main, verify visible from worktree
        events_file = Path(smm_main) / "events.jsonl"
        event = make_event(content="from main repo")
        events_file.write_text(json.dumps(event, ensure_ascii=False) + "\n")

        # Read from worktree
        content = events_file.read_text()
        self.assertIn("from main repo", content)


class TestEmptyProject(_IntegrationTestCase):
    """M7: Fresh git repo, no events — graceful degradation."""

    def test_session_start_empty_project(self):
        """session_start with no events — marker written, no SMM in context."""
        # Clear events (setUp created SMM with empty events.jsonl)
        (self.smm_dir / "events.jsonl").write_text("")
        result = self._run_script(
            "session_start.py",
            {"session_id": "empty", "source": "startup"},
        )
        self.assertEqual(result.returncode, 0)
        output = json.loads(result.stdout)
        ctx = output["hookSpecificOutput"]["additionalContext"]
        # No SMM or goal nudge (handled by /xp-session-review)
        self.assertNotIn("<smm-context>", ctx)
        self.assertNotIn("xp-goal-collection", ctx)
        # Marker file written
        self.assertTrue((self.smm_dir / ".needs-session-review").exists())
        # No crash
        self.assertIn("Resume immediately", ctx)

    def test_pre_tool_use_empty_project(self):
        """pre_tool_use with no events — no crash."""
        (self.smm_dir / "events.jsonl").write_text("")
        result = self._run_script(
            "pre_tool_use.py",
            {
                "session_id": "empty",
                "tool_name": "Write",
                "tool_input": {"file_path": "src/app.ts"},
                "agent_id": "main",
                "cwd": str(self.tmpdir),
            },
        )
        self.assertEqual(result.returncode, 0)


class TestWatermarkIsolation(_IntegrationTestCase):
    """Verify watermark lifecycle under compaction."""

    def test_compact_resets_watermarks(self):
        """After compact, orphaned watermarks removed, prompt-nugget preserved."""
        # Create watermarks
        (self.smm_dir / ".watermark-alice").write_text("5")
        (self.smm_dir / ".watermark-bob").write_text("3")
        (self.smm_dir / ".watermark-prompt-nugget").write_text("10")

        # Seed some sessions
        events = []
        for s in range(3):
            events.extend(
                [
                    make_event(
                        content=f"s{s}-e{i}", ts=f"2026-03-{s + 1:02d}T00:00:00+00:00"
                    )
                    for i in range(3)
                ]
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

        # Write curation watermark so compaction runs
        sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))
        from materialize import write_curation_watermark

        write_curation_watermark(self.smm_dir, len(events), "xp-housekeeping")

        # Run compact via subprocess
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

        # Orphaned watermarks should be gone
        self.assertFalse((self.smm_dir / ".watermark-alice").exists())
        self.assertFalse((self.smm_dir / ".watermark-bob").exists())
        # Prompt-nugget preserved (with updated value)
        self.assertTrue((self.smm_dir / ".watermark-prompt-nugget").exists())


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


class TestQualityGatePendingSubagents(_IntegrationTestCase):
    def _seed_simplify_tracker(self, loop_id: str) -> None:
        """Write simplify tracker so quality gate can fire."""
        tracker = self.smm_dir / ".simplify-main.json"
        tracker.write_text(json.dumps({"loop_id": loop_id}))

    def test_quality_gate_lets_pending_through_blocks_after_complete(self):
        """Full subprocess: pending subagent passes, completed blocks."""
        ci = make_event("customer_input", content="build feature")
        self._seed_events(
            [
                ci,
                make_event(
                    "status",
                    content="wrote",
                    working_on=["src/app.ts"],
                ),
                make_event(
                    "status",
                    agent_id="explorer-1",
                    content="Subagent explorer-1 started",
                    working_on=[],
                ),
            ]
        )
        self._seed_simplify_tracker(ci["id"])

        # Run 1: pending subagent → no output (pass through)
        r1 = self._run_script(
            "quality_review_gate.py",
            {"session_id": "int-test", "agent_id": "main"},
        )
        self.assertEqual(r1.returncode, 0)
        self.assertEqual(r1.stdout.strip(), "")

        # Add completion event
        self._seed_events(
            [
                ci,
                make_event(
                    "status",
                    content="wrote",
                    working_on=["src/app.ts"],
                ),
                make_event(
                    "status",
                    agent_id="explorer-1",
                    content="Subagent explorer-1 started",
                    working_on=[],
                ),
                make_event(
                    "status",
                    agent_id="explorer-1",
                    content="Subagent explorer-1 completed",
                    working_on=[],
                ),
            ]
        )

        # Run 2: all completed → blocks with quality review
        r2 = self._run_script(
            "quality_review_gate.py",
            {"session_id": "int-test", "agent_id": "main"},
        )
        self.assertEqual(r2.returncode, 0)
        d2 = json.loads(r2.stdout)
        self.assertEqual(d2["decision"], "block")
        self.assertIn("/xp-quality-review", d2["reason"])


class TestLoadContext(_IntegrationTestCase):
    def _run_load_context(self) -> subprocess.CompletedProcess:
        """Run load_context.sh as a subprocess."""
        script = (
            Path(__file__).parent.parent.parent
            / "skills"
            / "xp-housekeeping"
            / "scripts"
            / "load_context.sh"
        )
        return subprocess.run(
            ["bash", str(script)],
            capture_output=True,
            text=True,
            cwd=self.tmpdir,
        )

    def _assert_output_file_exists(
        self, result: subprocess.CompletedProcess, prefix: str
    ) -> str:
        """Assert stdout has one line with prefix pointing to existing file."""
        self.assertEqual(result.returncode, 0, result.stderr)
        lines = result.stdout.strip().splitlines()
        matched = [line for line in lines if line.startswith(prefix)]
        self.assertEqual(len(matched), 1, f"Expected one {prefix} line, got: {lines}")
        path = matched[0].split("=", 1)[1]
        self.assertTrue(Path(path).exists(), f"File does not exist: {path}")
        return path

    def test_outputs_smm_file_path(self):
        """load_context.sh outputs SMM_FILE= with correct path."""
        # Pre-create curated SMM (housekeeping writes this, not load_context)
        smm_file = self.smm_dir / "SHARED_MENTAL_MODEL.md"
        smm_file.write_text("# Shared Mental Model\n## Intent\n")
        result = self._run_load_context()
        self._assert_output_file_exists(result, "SMM_FILE=")

    def test_outputs_guide_file_path(self):
        """load_context.sh outputs GUIDE_FILE= pointing to existing file."""
        result = self._run_load_context()
        self._assert_output_file_exists(result, "GUIDE_FILE=")


class TestPrepareCurationIntegration(_IntegrationTestCase):
    """Integration test for prepare_curation.py preload script."""

    def _run_prepare_curation(self) -> subprocess.CompletedProcess:
        script = (
            Path(__file__).parent.parent.parent
            / "skills"
            / "xp-housekeeping"
            / "scripts"
            / "prepare_curation.py"
        )
        return subprocess.run(
            ["python3", str(script), "--smm-dir", str(self.smm_dir)],
            capture_output=True,
            text=True,
            cwd=self.tmpdir,
        )

    def test_empty_project_returns_valid_json(self):
        """Script outputs valid JSON with expected schema on empty project."""
        result = self._run_prepare_curation()
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        for key in (
            "current_smm",
            "new_since_last_curation",
            "retro_history",
            "aging",
            "health",
        ):
            self.assertIn(key, data)

    def test_with_events_returns_populated_data(self):
        """Script returns populated curation data when events exist."""
        self._seed_events(
            [
                make_event("goal", content="Ship v1"),
                make_event("concern", content="No tests"),
                make_event("customer_input", content="Add auth"),
            ]
        )
        result = self._run_prepare_curation()
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data["health"]["intent_count"], 1)
        self.assertEqual(data["health"]["risks_count"], 1)
        self.assertEqual(len(data["new_since_last_curation"]["customer_inputs"]), 1)


class TestSaveSMMIntegration(_IntegrationTestCase):
    """Integration test for save_smm.py helper script."""

    def _run_save_smm(self, content: str) -> subprocess.CompletedProcess:
        script = (
            Path(__file__).parent.parent.parent
            / "skills"
            / "xp-housekeeping"
            / "scripts"
            / "save_smm.py"
        )
        return subprocess.run(
            ["python3", str(script), "--smm-dir", str(self.smm_dir)],
            input=content,
            capture_output=True,
            text=True,
            cwd=self.tmpdir,
        )

    def test_pipe_markdown_writes_file(self):
        """Pipe four-pillar markdown into save_smm.py, verify file written."""
        content = "# Shared Mental Model\n\n## Intent\n- Ship v1\n"
        result = self._run_save_smm(content)
        self.assertEqual(result.returncode, 0, result.stderr)
        smm_file = self.smm_dir / "SHARED_MENTAL_MODEL.md"
        self.assertTrue(smm_file.exists())
        self.assertEqual(smm_file.read_text(), content)

    def test_watermark_updated_after_save(self):
        """Watermark reflects event count after save."""
        self._seed_events(
            [
                make_event("goal", content="Ship v1"),
                make_event("concern", content="No tests"),
                make_event("decision", topic="db", content="Use PG"),
            ]
        )
        result = self._run_save_smm("# SMM\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        wm_file = self.smm_dir / ".curation-watermark"
        self.assertTrue(wm_file.exists())
        wm = json.loads(wm_file.read_text())
        self.assertEqual(wm["event_count"], 3)


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

    def test_pre_tool_use_detects_overlap(self):
        """PreToolUse blocks when another agent works on the same file."""
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
        result = self._run_script("pre_tool_use.py", pre_input)
        # Should block (exit 2) with conflict message
        self.assertEqual(result.returncode, 2)
        self.assertIn("CONFLICT", result.stderr)
        self.assertIn("agent-2", result.stderr)


class TestRetroPreloadIntegration(_IntegrationTestCase):
    """Verify preload.sh outputs digest but not raw events."""

    def _run_preload(self) -> subprocess.CompletedProcess:
        """Run the retrospective preload.sh script."""
        preload_sh = (
            Path(__file__).parent.parent.parent
            / "skills"
            / "xp-retrospective"
            / "scripts"
            / "preload.sh"
        )
        return subprocess.run(
            ["bash", str(preload_sh)],
            capture_output=True,
            text=True,
            cwd=self.tmpdir,
        )

    def test_preload_excludes_raw_events(self):
        """Preload output must not contain events_since_last_retro."""
        retro_input = {
            "unanalyzed_count": 3,
            "events_since_last_retro": [
                make_event(content=f"raw-event-{i}") for i in range(3)
            ],
            "digest": {
                "signal_events": [make_event("concern", content="test concern")],
                "status_summary": {"total": 2, "samples": []},
                "concern_groups": [],
            },
            "previous_retros": [],
            "event_type_counts": {"status": 2, "concern": 1},
            "session_stats": {"concerns_raised": 1, "concerns_resolved": 0},
        }
        (self.smm_dir / ".retro-input.json").write_text(
            json.dumps(retro_input, ensure_ascii=False)
        )

        result = self._run_preload()
        self.assertEqual(result.returncode, 0, result.stderr)

        output = result.stdout
        # Must contain digest data
        self.assertIn("signal_events", output)
        self.assertIn("test concern", output)
        self.assertIn("unanalyzed_count", output)
        # Must NOT contain raw events array
        self.assertNotIn("events_since_last_retro", output)
        self.assertNotIn("raw-event-", output)

    def test_preload_missing_file(self):
        """Preload gracefully handles missing .retro-input.json."""
        result = self._run_preload()
        self.assertEqual(result.returncode, 0)
        self.assertIn("no .retro-input.json found", result.stdout)


if __name__ == "__main__":
    unittest.main()
