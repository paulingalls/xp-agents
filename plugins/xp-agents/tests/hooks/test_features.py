#!/usr/bin/env python3
"""Tests for feature-specific functionality: auto-resolve, retro digest,
save retrospective, save SMM, coordination, prompt nuggets, compact log.

Split from the monolithic test_hooks.py.
"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import _common
import lint_check
import pre_tool_use
from conftest import _HookTestCase, _make_bash_input, _make_write_input, make_event

# ===========================================================================
# Auto-resolve test concerns
# ===========================================================================


class TestAutoResolveTestConcerns(_HookTestCase):
    """Tests for auto-resolve of test-failure concerns."""

    def _run_bash(self, command, stdout="", **kw):
        import bash_post_tool

        data = _make_bash_input(command=command, stdout=stdout, **kw)
        bash_post_tool.run(data, smm_dir=self.smm_dir)

    def test_passing_resolves_prior_failure_concern(self):
        """Seed failure concern, pass tests, verify resolution."""
        concern = make_event(
            "concern",
            content="Test failures detected: 2 failed (pytest)",
            severity="high",
        )
        self._write_events([concern])
        self._run_bash(
            "python3 -m unittest test.py",
            stdout="Ran 5 tests in 0.1s\n\nOK",
        )
        events = self._read_events()
        resolutions = [e for e in events if e.get("metadata", {}).get("resolves")]
        self.assertEqual(len(resolutions), 1)
        self.assertIn(
            concern["id"],
            resolutions[0]["metadata"]["resolves"],
        )

    def test_passing_resolves_multiple_concerns(self):
        """Two different failure concerns should both be resolved."""
        c1 = make_event(
            "concern",
            content="Test failures detected: 2 failed (pytest)",
            severity="high",
        )
        c2 = make_event(
            "concern",
            content="Test run failed: 1 error",
            severity="high",
        )
        self._write_events([c1, c2])
        self._run_bash(
            "python3 -m unittest test.py",
            stdout="Ran 5 tests in 0.1s\n\nOK",
        )
        events = self._read_events()
        all_resolved_ids = []
        for e in events:
            all_resolved_ids.extend(e.get("metadata", {}).get("resolves", []))
        self.assertIn(c1["id"], all_resolved_ids)
        self.assertIn(c2["id"], all_resolved_ids)

    def test_no_resolve_when_no_prior_concerns(self):
        """Clean state, no resolution events."""
        self._run_bash(
            "python3 -m unittest test.py",
            stdout="Ran 5 tests in 0.1s\n\nOK",
        )
        events = self._read_events()
        resolutions = [e for e in events if e.get("metadata", {}).get("resolves")]
        self.assertEqual(len(resolutions), 0)

    def test_skip_already_resolved_concerns(self):
        """No duplicate resolutions."""
        concern = make_event(
            "concern",
            content="Test failures detected: 1 failed (pytest)",
            severity="high",
        )
        resolver = make_event(
            "status",
            content="Test concern resolved",
            working_on=[],
            metadata={"resolves": [concern["id"]]},
        )
        self._write_events([concern, resolver])
        self._run_bash(
            "python3 -m unittest test.py",
            stdout="Ran 5 tests in 0.1s\n\nOK",
        )
        events = self._read_events()
        new_resolutions = [
            e
            for e in events[2:]  # skip seeded events
            if e.get("metadata", {}).get("resolves")
        ]
        self.assertEqual(len(new_resolutions), 0)

    def test_failing_tests_no_auto_resolve(self):
        """Still-failing tests should not resolve anything."""
        concern = make_event(
            "concern",
            content="Test failures detected: 2 failed (pytest)",
            severity="high",
        )
        self._write_events([concern])
        self._run_bash(
            "python3 -m unittest test.py",
            stdout="Ran 5 tests in 0.1s\n\nFAILED (failures=1)",
        )
        events = self._read_events()
        resolutions = [e for e in events if e.get("metadata", {}).get("resolves")]
        self.assertEqual(len(resolutions), 0)

    def test_stop_gate_ignores_resolution_events(self):
        """Resolution events should not confuse the TDD stop gate."""
        import tdd_stop_gate

        concern = make_event(
            "concern",
            content="Test failures detected: 1 failed (pytest)",
            severity="high",
        )
        resolver = make_event(
            "status",
            content="Test concern resolved: 1 concern auto-resolved",
            working_on=[],
            metadata={"resolves": [concern["id"]]},
        )
        pass_status = make_event(
            "status",
            content="Tests: 5 passed, 0 failed (pytest)",
            working_on=[],
        )
        self._write_events([concern, resolver, pass_status])
        result = tdd_stop_gate.run({"session_id": "t"}, smm_dir=self.smm_dir)
        self.assertIsNone(result)


class TestAutoResolveLintConcerns(_HookTestCase):
    """Tests for auto-resolve of lint concerns when lint passes."""

    def setUp(self):
        super().setUp()
        self._lint_tmpdir = Path(tempfile.mkdtemp())
        (self._lint_tmpdir / "ruff.toml").touch()

    def tearDown(self):
        import shutil as sh

        sh.rmtree(self._lint_tmpdir, ignore_errors=True)
        super().tearDown()

    def _normalized(self, rel_path: str) -> str:
        """Return the normalized absolute path lint_check will use."""
        return _common.normalize_path(rel_path, str(self._lint_tmpdir))

    def _run_lint_clean(self, file_path="src/app.py"):
        """Run lint_check with a clean lint result for file_path."""
        with (
            patch(
                "lint_check.shutil.which",
                return_value="/usr/bin/ruff",
            ),
            patch("lint_check.run_linter", return_value=None),
        ):
            lint_check.run(
                _make_write_input(
                    tool_input={
                        "file_path": file_path,
                        "content": "x",
                    },
                    cwd=str(self._lint_tmpdir),
                ),
                smm_dir=self.smm_dir,
            )

    def test_lint_pass_resolves_concern_for_same_file(self):
        """Seed lint concern for src/app.py, pass lint -> resolved."""
        norm = self._normalized("src/app.py")
        concern = make_event(
            "concern",
            content=f"Lint errors in {norm}:\nE302 expected 2 blank lines",
            severity="medium",
        )
        self._write_events([concern])
        self._run_lint_clean("src/app.py")
        events = self._read_events()
        resolutions = [e for e in events if e.get("metadata", {}).get("resolves")]
        self.assertEqual(len(resolutions), 1)
        self.assertIn(
            concern["id"],
            resolutions[0]["metadata"]["resolves"],
        )

    def test_lint_pass_no_resolve_for_different_file(self):
        """Lint concern for src/other.py not resolved by src/app.py."""
        norm_other = self._normalized("src/other.py")
        concern = make_event(
            "concern",
            content=f"Lint errors in {norm_other}:\nE302",
            severity="medium",
        )
        self._write_events([concern])
        self._run_lint_clean("src/app.py")
        events = self._read_events()
        resolutions = [e for e in events if e.get("metadata", {}).get("resolves")]
        self.assertEqual(len(resolutions), 0)

    def test_no_lint_concerns_no_resolution(self):
        """No lint concerns in events -> no resolution events."""
        self._run_lint_clean("src/app.py")
        events = self._read_events()
        resolutions = [e for e in events if e.get("metadata", {}).get("resolves")]
        self.assertEqual(len(resolutions), 0)

    def test_already_resolved_not_re_resolved(self):
        """Already-resolved lint concern not re-resolved."""
        norm = self._normalized("src/app.py")
        concern = make_event(
            "concern",
            content=f"Lint errors in {norm}:\nE302",
            severity="medium",
        )
        resolver = make_event(
            "status",
            content="Lint concern resolved",
            working_on=[],
            metadata={"resolves": [concern["id"]]},
        )
        self._write_events([concern, resolver])
        self._run_lint_clean("src/app.py")
        events = self._read_events()
        new_resolutions = [
            e
            for e in events[2:]  # skip seeded events
            if e.get("metadata", {}).get("resolves")
        ]
        self.assertEqual(len(new_resolutions), 0)


# ===========================================================================
# Retro digest tests
# ===========================================================================


class TestRetroDigest(_HookTestCase):
    """Tests for retrospective digest helpers."""

    def setUp(self):
        super().setUp()
        (self.smm_dir / "retrospectives").mkdir()

    def test_digest_signal_events(self):
        """Decisions/concerns in signal_events, status excluded."""
        import retrospective

        events = [
            make_event("decision", content="Use REST", topic="api"),
            make_event("concern", content="Slow tests", severity="medium"),
            make_event("status", content="Wrote file", working_on=["f.py"]),
            make_event("status", content="More work", working_on=["g.py"]),
            make_event("customer_input", content="Please fix"),
        ]
        self._write_events(events)
        digest = retrospective._build_retro_digest(events, 0)
        signal_types = {e["type"] for e in digest["signal_events"]}
        self.assertIn("decision", signal_types)
        self.assertIn("concern", signal_types)
        self.assertIn("customer_input", signal_types)
        self.assertNotIn("status", signal_types)

    def test_digest_status_summary(self):
        """Correct counts for file_writes/test_runs/other."""
        import retrospective

        events = [
            make_event(
                "status",
                content="Wrote to src/app.ts",
                working_on=["src/app.ts"],
            ),
            make_event(
                "status",
                content="Wrote to src/util.ts",
                working_on=["src/util.ts"],
            ),
            make_event(
                "status",
                content="Tests: 5 passed, 0 failed (pytest)",
                working_on=[],
            ),
            make_event(
                "status",
                content="Thinking about design",
                working_on=[],
            ),
        ]
        self._write_events(events)
        digest = retrospective._build_retro_digest(events, 0)
        ss = digest["status_summary"]
        self.assertEqual(ss["total"], 4)
        self.assertEqual(ss["file_writes"], 2)
        self.assertEqual(ss["test_runs"], 1)
        self.assertEqual(ss["other"], 1)

    def test_digest_concern_groups_dedup(self):
        """3 identical failure concerns -> 1 group with count=3."""
        import retrospective

        events = [
            make_event(
                "concern",
                content="Test failures detected: 2 failed (pytest)",
                severity="high",
            )
            for _ in range(3)
        ]
        self._write_events(events)
        digest = retrospective._build_retro_digest(events, 0)
        groups = digest["concern_groups"]
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["count"], 3)

    def test_digest_concern_groups_unique(self):
        """3 different concerns -> 3 groups with count=1."""
        import retrospective

        events = [
            make_event("concern", content="Slow tests", severity="medium"),
            make_event("concern", content="Missing docs", severity="low"),
            make_event(
                "concern",
                content="Security issue",
                severity="high",
            ),
        ]
        self._write_events(events)
        digest = retrospective._build_retro_digest(events, 0)
        groups = digest["concern_groups"]
        self.assertEqual(len(groups), 3)
        for g in groups:
            self.assertEqual(g["count"], 1)

    def test_digest_preserves_event_ids(self):
        """All signal event IDs present."""
        import retrospective

        events = [
            make_event("decision", content="Use REST", topic="api"),
            make_event("concern", content="Slow", severity="low"),
        ]
        self._write_events(events)
        digest = retrospective._build_retro_digest(events, 0)
        signal_ids = {e["id"] for e in digest["signal_events"]}
        for e in events:
            self.assertIn(e["id"], signal_ids)

    def test_normalize_concern_strips_numbers(self):
        """Numbers normalized for consistent grouping."""
        import retrospective

        k1 = retrospective._normalize_concern_content(
            "Test failures detected: 2 failed (pytest)"
        )
        k2 = retrospective._normalize_concern_content(
            "Test failures detected: 5 failed (pytest)"
        )
        self.assertEqual(k1, k2)

    def test_retro_input_uses_digest(self):
        """_build_retro_input should include digest keys."""
        import retrospective

        events = [
            make_event("decision", content="Use REST", topic="api"),
            make_event(
                "status",
                content="Wrote to f.py",
                working_on=["f.py"],
            ),
            make_event(
                "status",
                content="Tests: 5 passed, 0 failed",
                working_on=[],
            ),
            make_event("concern", content="Slow", severity="low"),
            make_event("customer_input", content="Fix it"),
        ]
        self._write_events(events)
        retro_input = retrospective._build_retro_input(events, 0, [])
        self.assertIn("digest", retro_input)
        digest = retro_input["digest"]
        self.assertIn("signal_events", digest)
        self.assertIn("status_summary", digest)
        self.assertIn("concern_groups", digest)


# ===========================================================================
# save_retrospective.py tests
# ===========================================================================


class TestSaveRetrospective(_HookTestCase):
    """Tests for save_retrospective.py helper script."""

    def setUp(self):
        super().setUp()
        # Create retrospectives directory (init.sh normally does this)
        (self.smm_dir / "retrospectives").mkdir(exist_ok=True)

    def _valid_kft(self) -> dict:
        return {
            "keep": [
                {
                    "content": "TDD discipline held",
                    "event_refs": ["abc123"],
                    "values": ["Feedback"],
                }
            ],
            "fix": [
                {
                    "content": "Navigator silent",
                    "event_refs": ["def456"],
                    "xp_value": "Communication",
                }
            ],
            "try": [
                {
                    "content": "Investigate navigator pipeline",
                    "event_refs": ["ghi789"],
                }
            ],
        }

    def test_valid_kft_creates_event_and_file(self):
        import save_retrospective

        result = save_retrospective.run(self._valid_kft(), smm_dir=self.smm_dir)
        self.assertIsNotNone(result)
        self.assertIn("event_id", result)
        self.assertIn("retro_file", result)

        # Verify event in events.jsonl
        events = self._read_events()
        retro_events = [e for e in events if e["type"] == "retrospective"]
        self.assertEqual(len(retro_events), 1)
        ev = retro_events[0]
        self.assertEqual(len(ev["keep"]), 1)
        self.assertEqual(ev["keep"][0]["content"], "TDD discipline held")
        self.assertEqual(len(ev["fix"]), 1)
        self.assertEqual(ev["fix"][0]["xp_value"], "Communication")
        self.assertEqual(len(ev["try"]), 1)
        self.assertEqual(ev["try"][0]["content"], "Investigate navigator pipeline")
        self.assertIn("1 keeps, 1 fixes, 1 tries", ev["content"])

        # Verify retrospective file exists
        retro_file = Path(result["retro_file"])
        self.assertTrue(retro_file.exists())
        retro_data = json.loads(retro_file.read_text())
        self.assertIn("keep", retro_data)
        self.assertIn("fix", retro_data)
        self.assertIn("try", retro_data)
        self.assertIn("timestamp", retro_data)

    def test_missing_content_field_errors(self):
        import save_retrospective

        bad_kft = {"keep": [{"event_refs": ["abc"]}], "fix": [], "try": []}
        result = save_retrospective.run(bad_kft, smm_dir=self.smm_dir)
        self.assertIsNone(result)
        # No event should be written
        events = self._read_events()
        retro_events = [e for e in events if e["type"] == "retrospective"]
        self.assertEqual(len(retro_events), 0)

    def test_empty_arrays_succeeds(self):
        import save_retrospective

        empty_kft = {"keep": [], "fix": [], "try": []}
        result = save_retrospective.run(empty_kft, smm_dir=self.smm_dir)
        self.assertIsNotNone(result)

        events = self._read_events()
        retro_events = [e for e in events if e["type"] == "retrospective"]
        self.assertEqual(len(retro_events), 1)
        self.assertIn("0 keeps, 0 fixes, 0 tries", retro_events[0]["content"])

    def test_invalid_json_stdin(self):
        """When called as main with invalid JSON on stdin, should exit 1."""
        import save_retrospective

        result = save_retrospective.run(None, smm_dir=self.smm_dir)
        self.assertIsNone(result)

    def test_optional_analysis_notes(self):
        import save_retrospective

        kft = self._valid_kft()
        kft["analysis_notes"] = "Cross-session trend: navigator silent for 4 retros"
        result = save_retrospective.run(kft, smm_dir=self.smm_dir)
        self.assertIsNotNone(result)

        retro_file = Path(result["retro_file"])
        retro_data = json.loads(retro_file.read_text())
        self.assertEqual(
            retro_data["analysis_notes"],
            "Cross-session trend: navigator silent for 4 retros",
        )


# ---------------------------------------------------------------------------
# save_smm.py tests (M2)
# ---------------------------------------------------------------------------


class TestSaveSMM(_HookTestCase):
    """Tests for save_smm.py helper script."""

    def setUp(self):
        super().setUp()
        # Add skill scripts to path so we can import save_smm
        skill_scripts = (
            Path(__file__).parent.parent.parent
            / "skills"
            / "xp-housekeeping"
            / "scripts"
        )
        if str(skill_scripts) not in sys.path:
            sys.path.insert(0, str(skill_scripts))

    def test_writes_smm_file(self):
        """save_smm.run() writes markdown content to SHARED_MENTAL_MODEL.md."""
        import save_smm

        content = "# Shared Mental Model\n\n## Intent\n- Ship v1\n"
        save_smm.run(content, smm_dir=self.smm_dir)
        smm_file = self.smm_dir / "SHARED_MENTAL_MODEL.md"
        self.assertTrue(smm_file.exists())
        self.assertEqual(smm_file.read_text(), content)

    def test_updates_curation_watermark(self):
        """save_smm.run() updates .curation-watermark with event count."""
        import save_smm

        # Seed some events
        self._write_events(
            [
                make_event("goal", content="Ship v1"),
                make_event("concern", content="No tests"),
            ]
        )
        save_smm.run("# SMM\n", smm_dir=self.smm_dir)
        import materialize as _mat

        wm = _mat.read_curation_watermark(self.smm_dir)
        self.assertEqual(wm["event_count"], 2)
        self.assertEqual(wm["agent_id"], "xp-housekeeping")

    def test_overwrites_existing_smm(self):
        """save_smm.run() overwrites an existing SHARED_MENTAL_MODEL.md."""
        import save_smm

        smm_file = self.smm_dir / "SHARED_MENTAL_MODEL.md"
        smm_file.write_text("old content")
        save_smm.run("new content", smm_dir=self.smm_dir)
        self.assertEqual(smm_file.read_text(), "new content")

    def test_file_permissions(self):
        """Written SMM file has mode 0o600."""
        import save_smm

        save_smm.run("# SMM\n", smm_dir=self.smm_dir)
        smm_file = self.smm_dir / "SHARED_MENTAL_MODEL.md"
        mode = smm_file.stat().st_mode & 0o777
        self.assertEqual(mode, 0o600)

    def test_empty_content_writes_empty_file(self):
        """Empty string input produces an empty file."""
        import save_smm

        save_smm.run("", smm_dir=self.smm_dir)
        smm_file = self.smm_dir / "SHARED_MENTAL_MODEL.md"
        self.assertTrue(smm_file.exists())
        self.assertEqual(smm_file.read_text(), "")


# ===========================================================================
# Coordination tests
# ===========================================================================


class TestCoordination(_HookTestCase):
    """Test coordination file helpers: update, read, clear."""

    def test_update_creates_file(self):
        """update_coordination creates .coordination.json if missing."""
        _common.update_coordination(self.smm_dir, "main", ["src/a.ts"])
        coord_file = self.smm_dir / ".coordination.json"
        self.assertTrue(coord_file.exists())

    def test_update_adds_agent_entry(self):
        """Entry has working_on list and updated timestamp."""
        _common.update_coordination(self.smm_dir, "main", ["src/a.ts"])
        data = _common.read_coordination(self.smm_dir)
        self.assertIn("main", data)
        self.assertEqual(data["main"]["working_on"], ["src/a.ts"])
        self.assertIn("updated", data["main"])

    def test_update_overwrites_previous(self):
        """Latest update replaces previous working_on."""
        _common.update_coordination(self.smm_dir, "main", ["src/a.ts"])
        _common.update_coordination(self.smm_dir, "main", ["src/b.ts"])
        data = _common.read_coordination(self.smm_dir)
        self.assertEqual(data["main"]["working_on"], ["src/b.ts"])

    def test_read_returns_empty_on_missing(self):
        """read_coordination returns {} when file doesn't exist."""
        data = _common.read_coordination(self.smm_dir)
        self.assertEqual(data, {})

    def test_read_ignores_stale_entries(self):
        """Entries older than max_age_seconds are excluded."""
        from datetime import datetime, timedelta, timezone

        old_time = (datetime.now(timezone.utc) - timedelta(minutes=45)).isoformat()
        coord_file = self.smm_dir / ".coordination.json"
        coord_file.write_text(
            json.dumps(
                {
                    "stale-agent": {
                        "working_on": ["src/old.ts"],
                        "updated": old_time,
                    }
                }
            )
        )
        data = _common.read_coordination(self.smm_dir)
        self.assertEqual(data, {})

    def test_read_keeps_fresh_entries(self):
        """Entries within max_age_seconds are kept."""
        _common.update_coordination(self.smm_dir, "main", ["src/a.ts"])
        data = _common.read_coordination(self.smm_dir)
        self.assertIn("main", data)

    def test_clear_removes_agent(self):
        """clear_coordination_agent removes the agent's entry."""
        _common.update_coordination(self.smm_dir, "main", ["src/a.ts"])
        _common.clear_coordination_agent(self.smm_dir, "main")
        data = _common.read_coordination(self.smm_dir)
        self.assertNotIn("main", data)

    def test_clear_preserves_others(self):
        """Clearing one agent doesn't affect other agents."""
        _common.update_coordination(self.smm_dir, "main", ["src/a.ts"])
        _common.update_coordination(self.smm_dir, "agent-2", ["src/b.ts"])
        _common.clear_coordination_agent(self.smm_dir, "main")
        data = _common.read_coordination(self.smm_dir)
        self.assertNotIn("main", data)
        self.assertIn("agent-2", data)

    def test_clear_noop_on_missing_file(self):
        """clear_coordination_agent is a no-op if file doesn't exist."""
        _common.clear_coordination_agent(self.smm_dir, "main")
        # Should not raise

    def test_corrupted_file_returns_empty(self):
        """read_coordination returns {} on invalid JSON."""
        coord_file = self.smm_dir / ".coordination.json"
        coord_file.write_text("not json{{{")
        data = _common.read_coordination(self.smm_dir)
        self.assertEqual(data, {})


class TestCheckWorkingOnOverlapCoordination(_HookTestCase):
    """Test overlap detection using .coordination.json."""

    def test_no_overlap(self):
        """No conflict when agents work on different files."""
        _common.update_coordination(self.smm_dir, "other", ["src/b.ts"])
        result = pre_tool_use.check_working_on_overlap(
            self.smm_dir, "main", "src/a.ts", "/project"
        )
        self.assertIsNone(result)

    def test_overlap_detected(self):
        """Conflict detected when another agent works on the same file."""
        _common.update_coordination(self.smm_dir, "other", ["src/app.ts"])
        result = pre_tool_use.check_working_on_overlap(
            self.smm_dir, "main", "src/app.ts", "/project"
        )
        self.assertIsNotNone(result)
        self.assertIn("other", result)

    def test_self_overlap_ignored(self):
        """No conflict when the same agent works on the same file."""
        _common.update_coordination(self.smm_dir, "main", ["src/app.ts"])
        result = pre_tool_use.check_working_on_overlap(
            self.smm_dir, "main", "src/app.ts", "/project"
        )
        self.assertIsNone(result)

    def test_stale_entry_ignored(self):
        """Stale coordination entries don't trigger conflicts."""
        from datetime import datetime, timedelta, timezone

        old_time = (datetime.now(timezone.utc) - timedelta(minutes=45)).isoformat()
        coord_file = self.smm_dir / ".coordination.json"
        coord_file.write_text(
            json.dumps(
                {
                    "other": {
                        "working_on": ["src/app.ts"],
                        "updated": old_time,
                    }
                }
            )
        )
        result = pre_tool_use.check_working_on_overlap(
            self.smm_dir, "main", "src/app.ts", "/project"
        )
        self.assertIsNone(result)

    def test_empty_working_on(self):
        """Agent with empty working_on doesn't trigger conflict."""
        _common.update_coordination(self.smm_dir, "other", [])
        result = pre_tool_use.check_working_on_overlap(
            self.smm_dir, "main", "src/app.ts", "/project"
        )
        self.assertIsNone(result)

    def test_cleared_agent_no_conflict(self):
        """After clearing, agent no longer causes conflicts."""
        _common.update_coordination(self.smm_dir, "other", ["src/app.ts"])
        _common.clear_coordination_agent(self.smm_dir, "other")
        result = pre_tool_use.check_working_on_overlap(
            self.smm_dir, "main", "src/app.ts", "/project"
        )
        self.assertIsNone(result)


# ===========================================================================
# Prompt nugget tests
# ===========================================================================


class TestPromptNugget(_HookTestCase):
    """Test prompt nugget delta injection from events."""

    def test_no_events_returns_none(self):
        """No events -> no nugget."""
        import prompt_nugget

        result = prompt_nugget.run(
            {"session_id": "s1", "agent_id": "main"},
            smm_dir=self.smm_dir,
        )
        self.assertIsNone(result)

    def test_xp_agent_skips(self):
        """Recursion prevention for xp-* agents."""
        import prompt_nugget

        self._write_events([make_event("concern", content="Bug found")])
        result = prompt_nugget.run(
            {
                "session_id": "s1",
                "agent_id": "main",
                "agent_type": "xp-quality-review",
            },
            smm_dir=self.smm_dir,
        )
        self.assertIsNone(result)

    def test_shows_new_concern(self):
        """New concern appears in nugget."""
        import prompt_nugget

        self._write_events([make_event("concern", content="No tests for auth module")])
        result = prompt_nugget.run(
            {"session_id": "s1", "agent_id": "main"},
            smm_dir=self.smm_dir,
        )
        self.assertIsNotNone(result)
        self.assertIn("concern", result)
        self.assertIn("No tests for auth module", result)

    def test_shows_new_decision(self):
        """New decision appears in nugget."""
        import prompt_nugget

        self._write_events([make_event("decision", content="Use REST API")])
        result = prompt_nugget.run(
            {"session_id": "s1", "agent_id": "main"},
            smm_dir=self.smm_dir,
        )
        self.assertIsNotNone(result)
        self.assertIn("decision", result)
        self.assertIn("Use REST API", result)

    def test_status_events_excluded(self):
        """Status events are not signal types — excluded from nugget."""
        import prompt_nugget

        self._write_events([make_event("status", content="Working on auth")])
        result = prompt_nugget.run(
            {"session_id": "s1", "agent_id": "main"},
            smm_dir=self.smm_dir,
        )
        self.assertIsNone(result)

    def test_watermark_advances(self):
        """Second call with no new events returns None."""
        import prompt_nugget

        self._write_events([make_event("concern", content="Missing validation")])
        # First call sees the event
        result1 = prompt_nugget.run(
            {"session_id": "s1", "agent_id": "main"},
            smm_dir=self.smm_dir,
        )
        self.assertIsNotNone(result1)
        # Second call — watermark advanced, nothing new
        result2 = prompt_nugget.run(
            {"session_id": "s1", "agent_id": "main"},
            smm_dir=self.smm_dir,
        )
        self.assertIsNone(result2)

    def test_caps_at_five(self):
        """At most 5 items shown even with more new events."""
        import prompt_nugget

        self._write_events(
            [make_event("concern", content=f"Issue {i}") for i in range(8)]
        )
        result = prompt_nugget.run(
            {"session_id": "s1", "agent_id": "main"},
            smm_dir=self.smm_dir,
        )
        self.assertIsNotNone(result)
        self.assertEqual(result.count("[concern]"), 5)


# ===========================================================================
# Compact log tests
# ===========================================================================


class TestCompactLog(_HookTestCase):
    """Test compact_log.py housekeeping script via subprocess."""

    def test_compact_log_subprocess(self):
        """compact_log.py runs as subprocess and prints stats."""
        # Seed events with a curation watermark
        events = [make_event("status", content=f"e{i}") for i in range(5)] + [
            make_event("session_end", content="end", working_on=[])
        ]
        self._write_events(events)

        sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))
        from materialize import write_curation_watermark

        write_curation_watermark(self.smm_dir, len(events), "xp-housekeeping")

        script = (
            Path(__file__).parent.parent.parent
            / "skills"
            / "xp-housekeeping"
            / "scripts"
            / "compact_log.py"
        )
        result = subprocess.run(
            ["python3", str(script), "--smm-dir", str(self.smm_dir)],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("Compacted:", result.stdout)
        self.assertIn("archived", result.stdout)
        self.assertIn("retained", result.stdout)


if __name__ == "__main__":
    unittest.main()
