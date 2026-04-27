#!/usr/bin/env python3
"""Tests for scaffold_post.record_scaffold — system_context flip + decision event."""

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import scaffold_apply
from scaffold_post import record_scaffold


def _valid_system_context(surfaces: list[dict]) -> dict:
    return {
        "product": "Test product.",
        "architecture_overview": "Test architecture.",
        "stack": {"languages": ["Python"]},
        "modules": [{"name": "core", "purpose": "Core", "path": "src/core"}],
        "conventions": ["Use type hints"],
        "key_decisions": [{"topic": "lang", "decision": "Use Python"}],
        "sources": ["CLAUDE.md"],
        "project_specific": [],
        "acceptance_surfaces": surfaces,
    }


class _RecordTestBase(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = Path(tempfile.mkdtemp(prefix="scaffold-record-test-"))
        self.smm_dir = Path(tempfile.mkdtemp(prefix="scaffold-record-smm-"))
        ctx = _valid_system_context(
            [
                {
                    "name": "browser",
                    "signals": ["next.js"],
                    "harness": "playwright",
                    "status": "gap",
                },
                {
                    "name": "api",
                    "signals": ["fastapi"],
                    "harness": "pytest",
                    "status": "covered",
                },
            ]
        )
        (self.smm_dir / "system_context.json").write_text(
            json.dumps(ctx), encoding="utf-8"
        )

    def tearDown(self) -> None:
        shutil.rmtree(self.repo, ignore_errors=True)
        shutil.rmtree(self.smm_dir, ignore_errors=True)

    def _snap(self) -> scaffold_apply.ApplySnapshot:
        return scaffold_apply.ApplySnapshot(
            snapshot_id="testid",
            snapshot_dir=self.smm_dir / "snap",
            repo_root=self.repo,
            plan={
                "surface": "browser",
                "tool": "playwright",
                "tool_version": "1.51.0",
                "files_to_create": [],
                "files_to_modify": [],
                "install_cmds": [],
                "verify_cmd": "npx playwright test",
                "branch_name": "scaffold/test",
            },
        )

    def _ctx(self) -> dict:
        return json.loads(
            (self.smm_dir / "system_context.json").read_text(encoding="utf-8")
        )


class TestRecordScaffoldSurfaceFlip(_RecordTestBase):
    def test_flips_matching_surface_to_covered(self) -> None:
        result = record_scaffold(
            self._snap(),
            smm_dir=self.smm_dir,
            surface="browser",
            verify_cmd="npx playwright test tests/acceptance",
            concern_id=None,
            agent_id="test-agent",
        )
        self.assertTrue(result.ok, result.reason)
        ctx = self._ctx()
        browser = next(s for s in ctx["acceptance_surfaces"] if s["name"] == "browser")
        self.assertEqual(browser["status"], "covered")
        self.assertEqual(
            browser["acceptance_template_command"],
            "npx playwright test tests/acceptance",
        )

    def test_other_surfaces_unchanged(self) -> None:
        record_scaffold(
            self._snap(),
            smm_dir=self.smm_dir,
            surface="browser",
            verify_cmd="npx playwright test",
            concern_id=None,
            agent_id="test-agent",
        )
        ctx = self._ctx()
        api = next(s for s in ctx["acceptance_surfaces"] if s["name"] == "api")
        self.assertEqual(api["status"], "covered")
        self.assertNotIn("acceptance_template_command", api)

    def test_preserves_other_surface_fields(self) -> None:
        record_scaffold(
            self._snap(),
            smm_dir=self.smm_dir,
            surface="browser",
            verify_cmd="npx playwright test",
            concern_id=None,
            agent_id="test-agent",
        )
        ctx = self._ctx()
        browser = next(s for s in ctx["acceptance_surfaces"] if s["name"] == "browser")
        self.assertEqual(browser["harness"], "playwright")
        self.assertEqual(browser["signals"], ["next.js"])

    def test_unknown_surface_returns_failure(self) -> None:
        result = record_scaffold(
            self._snap(),
            smm_dir=self.smm_dir,
            surface="nonexistent",
            verify_cmd="any cmd",
            concern_id=None,
            agent_id="test-agent",
        )
        self.assertFalse(result.ok)
        self.assertIn("nonexistent", result.reason or "")
        # system_context untouched.
        ctx = self._ctx()
        browser = next(s for s in ctx["acceptance_surfaces"] if s["name"] == "browser")
        self.assertEqual(browser["status"], "gap")

    def test_missing_system_context_returns_failure(self) -> None:
        # Erase the system_context.json laid down by setUp.
        (self.smm_dir / "system_context.json").unlink()
        result = record_scaffold(
            self._snap(),
            smm_dir=self.smm_dir,
            surface="browser",
            verify_cmd="npx playwright test",
            concern_id=None,
            agent_id="test-agent",
        )
        self.assertFalse(result.ok)
        # Caller should be steered to /xp-system-context, not silent no-op.
        self.assertIn("system_context", result.reason or "")
        self.assertIn("xp-system-context", result.reason or "")


class TestRecordScaffoldSaveFailure(_RecordTestBase):
    def test_save_oserror_is_caught_into_record_result(self) -> None:
        # The store layer's atomic-write can raise OSError (e.g. read-only
        # filesystem). record_scaffold must surface that as
        # RecordResult(ok=False) rather than letting the exception escape
        # — silently corrupting the caller's flow into a half-state where
        # files were written but the surface flip was lost.
        from unittest.mock import patch

        with patch(
            "scaffold_post.system_context_store.save_system_context",
            side_effect=OSError("disk full"),
        ):
            result = record_scaffold(
                self._snap(),
                smm_dir=self.smm_dir,
                surface="browser",
                verify_cmd="npx playwright test",
                concern_id=None,
                agent_id="test-agent",
            )
        self.assertFalse(result.ok)
        self.assertIn("disk full", result.reason or "")
        # Mutation rolled back? No — record_scaffold mutates ctx in
        # memory; the on-disk file is untouched because save failed
        # before atomic-rename. Assert disk state is the original.
        ctx = self._ctx()
        browser = next(s for s in ctx["acceptance_surfaces"] if s["name"] == "browser")
        self.assertEqual(browser["status"], "gap")


def _events(smm_dir: Path) -> list[dict]:
    log = smm_dir / "events.jsonl"
    if not log.exists():
        return []
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]


class TestRecordScaffoldDecisionEvent(_RecordTestBase):
    def test_appends_decision_event_when_concern_id_supplied(self) -> None:
        result = record_scaffold(
            self._snap(),
            smm_dir=self.smm_dir,
            surface="browser",
            verify_cmd="npx playwright test",
            concern_id="abc123def456",
            agent_id="xp-scaffold-acceptance",
        )
        self.assertTrue(result.ok, result.reason)
        self.assertIsNotNone(result.decision_event_id)
        events = _events(self.smm_dir)
        decisions = [e for e in events if e.get("type") == "decision"]
        self.assertEqual(len(decisions), 1)
        decision = decisions[0]
        self.assertEqual(decision["id"], result.decision_event_id)
        self.assertEqual(decision.get("metadata", {}).get("resolves"), ["abc123def456"])
        self.assertTrue(decision.get("topic"))
        self.assertEqual(decision["agent_id"], "xp-scaffold-acceptance")

    def test_no_decision_event_when_concern_id_omitted(self) -> None:
        result = record_scaffold(
            self._snap(),
            smm_dir=self.smm_dir,
            surface="browser",
            verify_cmd="npx playwright test",
            concern_id=None,
            agent_id="xp-scaffold-acceptance",
        )
        self.assertTrue(result.ok)
        self.assertIsNone(result.decision_event_id)
        events = _events(self.smm_dir)
        decisions = [e for e in events if e.get("type") == "decision"]
        self.assertEqual(decisions, [])

    def test_no_decision_event_when_concern_id_is_literal_none_string(self) -> None:
        """Treat 'none' (the Resolves-Event sentinel) as no concern."""
        result = record_scaffold(
            self._snap(),
            smm_dir=self.smm_dir,
            surface="browser",
            verify_cmd="npx playwright test",
            concern_id="none",
            agent_id="xp-scaffold-acceptance",
        )
        self.assertTrue(result.ok)
        self.assertIsNone(result.decision_event_id)
        events = _events(self.smm_dir)
        decisions = [e for e in events if e.get("type") == "decision"]
        self.assertEqual(decisions, [])


if __name__ == "__main__":
    unittest.main()
