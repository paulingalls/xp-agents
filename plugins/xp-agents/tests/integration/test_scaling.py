#!/usr/bin/env python3
"""Integration tests: scaling, concurrency, and infrastructure scenarios.

Tests for compaction reinjection, large event logs, concurrent agent writes,
worktree sharing, empty project, and watermark isolation.
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
        self.assertIn("xp-smm-protocol", ctx)


class TestLargeEventLog(_IntegrationTestCase):
    """M7: 1000+ events — scripts complete without error."""

    def test_pre_tool_write_with_1000_events(self):
        """pre_tool_write.py completes with 1000 events."""
        self._seed_events([make_event(content=f"event-{i}") for i in range(1000)])
        result = self._run_script(
            "pre_tool_write.py",
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
        self.assertIn("xp-run-retrospective", ctx)


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
            env=self._test_env,
        )
        r_wt = subprocess.run(
            ["bash", str(init_sh)],
            cwd=wt_dir,
            capture_output=True,
            text=True,
            env=self._test_env,
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
        # No SMM or goal nudge (handled by /xp-kickoff)
        self.assertNotIn("<smm-context>", ctx)
        self.assertNotIn("xp-goal-collection", ctx)
        # Marker file written
        self.assertTrue((self.smm_dir / ".needs-kickoff").exists())
        # No crash
        self.assertIn("Resume immediately", ctx)

    def test_pre_tool_write_empty_project(self):
        """pre_tool_write with no events — no crash."""
        (self.smm_dir / "events.jsonl").write_text("")
        result = self._run_script(
            "pre_tool_write.py",
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


if __name__ == "__main__":
    unittest.main()
