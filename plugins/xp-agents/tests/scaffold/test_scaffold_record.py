#!/usr/bin/env python3
"""Tests for scaffold_post.record_scaffold — system_context flip + decision event."""

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import scaffold_apply
from _branching_fixtures import GIT_ENV
from _helpers import valid_system_context
from event_helpers import events_of_type
from event_schema import EVENT_TYPE_DECISION
from scaffold_post import record_scaffold


class _RecordTestBase(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = Path(tempfile.mkdtemp(prefix="scaffold-record-test-"))
        self.smm_dir = Path(tempfile.mkdtemp(prefix="scaffold-record-smm-"))
        ctx = valid_system_context(
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

    def _seed_commit(self) -> str:
        """Seed a [chore] Scaffold commit in self.repo and return its SHA.

        Tests that don't directly exercise the gate still need to pass
        ``commit_sha`` (now required) to drive past the 3-stage check —
        any flip / decision / save-error scenario downstream needs a
        real seeded commit so the gate clears.
        """
        return _seed_scaffold_commit(self.repo)


class TestRecordScaffoldRequiresCommitSha(_RecordTestBase):
    """commit_sha is required so future entry points cannot silently bypass
    the HEAD-advancement gate. Concern 7e8e6fd50730."""

    def test_record_scaffold_without_commit_sha_raises(self) -> None:
        with self.assertRaises(TypeError):
            record_scaffold(  # type: ignore[call-arg]
                self._snap(),
                smm_dir=self.smm_dir,
                surface="browser",
                verify_cmd="npx playwright test",
                concern_id=None,
                agent_id="test-agent",
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
            commit_sha=self._seed_commit(),
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
            commit_sha=self._seed_commit(),
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
            commit_sha=self._seed_commit(),
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
            commit_sha=self._seed_commit(),
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
            commit_sha=self._seed_commit(),
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
                commit_sha=self._seed_commit(),
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
            commit_sha=self._seed_commit(),
        )
        self.assertTrue(result.ok, result.reason)
        self.assertIsNotNone(result.decision_event_id)
        events = _events(self.smm_dir)
        decisions = events_of_type(events, EVENT_TYPE_DECISION)
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
            commit_sha=self._seed_commit(),
        )
        self.assertTrue(result.ok)
        self.assertIsNone(result.decision_event_id)
        events = _events(self.smm_dir)
        decisions = events_of_type(events, EVENT_TYPE_DECISION)
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
            commit_sha=self._seed_commit(),
        )
        self.assertTrue(result.ok)
        self.assertIsNone(result.decision_event_id)
        events = _events(self.smm_dir)
        decisions = events_of_type(events, EVENT_TYPE_DECISION)
        self.assertEqual(decisions, [])


class TestRecordScaffoldCommitShaGate(_RecordTestBase):
    """When commit_sha is supplied, record_scaffold refuses to flip the
    surface unless the commit actually exists in snap.repo_root.

    Closes the atomicity gap surfaced by the close-reviewer: previously,
    apply-record could flip system_context.acceptance_surfaces[*] to
    'covered' even if apply-commit had failed silently, leaving a state
    that lied about the on-disk reality.
    """

    def test_missing_commit_sha_returns_failure(self) -> None:
        # No git repo init in self.repo, so any sha is missing.
        result = record_scaffold(
            self._snap(),
            smm_dir=self.smm_dir,
            surface="browser",
            verify_cmd="npx playwright test",
            concern_id=None,
            agent_id="test-agent",
            commit_sha="deadbeefcafe",
        )
        self.assertFalse(result.ok)
        self.assertIn("deadbeefcafe", result.reason or "")
        # system_context untouched.
        ctx = self._ctx()
        browser = next(s for s in ctx["acceptance_surfaces"] if s["name"] == "browser")
        self.assertEqual(browser["status"], "gap")

    def test_decision_event_carries_snapshot_id_and_commit_sha(self) -> None:
        head = _seed_scaffold_commit(self.repo)
        result = record_scaffold(
            self._snap(),
            smm_dir=self.smm_dir,
            surface="browser",
            verify_cmd="npx playwright test",
            concern_id="abc123def456",
            agent_id="test-agent",
            commit_sha=head,
        )
        self.assertTrue(result.ok, result.reason)
        events = _events(self.smm_dir)
        decision = events_of_type(events, EVENT_TYPE_DECISION)[0]
        self.assertEqual(decision["metadata"]["snapshot_id"], "testid")
        self.assertEqual(decision["metadata"]["commit_sha"], head)


class TestRecordScaffoldHeadAdvancementGate(_RecordTestBase):
    """Step 8/9 atomicity: record_scaffold refuses unless HEAD points at
    commit_sha AND the HEAD commit subject starts with ``[chore] Scaffold ``.

    Closes the gap where HEAD might be the scaffold commit's sha (existence
    check passed) but the user has since added another commit on top, OR the
    sha exists but is some unrelated commit. In both cases the surface flip
    would lie about what landed.
    """

    def _seed_with_advanced_head(self) -> str:
        """Seed a scaffold commit, then advance HEAD with an unrelated commit.

        Returns the scaffold commit's SHA — HEAD now points past it. Drives
        the head-mismatch leg of the 3-stage gate.
        """
        scaffold_sha = _seed_scaffold_commit(self.repo)
        (self.repo / "extra.txt").write_text("unrelated\n", encoding="utf-8")
        subprocess.run(
            ["git", "add", "extra.txt"],
            cwd=self.repo,
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "unrelated change"],
            cwd=self.repo,
            capture_output=True,
            check=True,
            env=GIT_ENV,
        )
        return scaffold_sha

    def test_head_mismatch_returns_failure(self) -> None:
        """Commit exists but HEAD has advanced past it (user added a commit)."""
        scaffold_sha = self._seed_with_advanced_head()

        result = record_scaffold(
            self._snap(),
            smm_dir=self.smm_dir,
            surface="browser",
            verify_cmd="npx playwright test",
            concern_id="abc123def456",
            agent_id="test-agent",
            commit_sha=scaffold_sha,
        )

        self.assertFalse(result.ok)
        self.assertIn("HEAD", result.reason or "")
        # Surface stays gap; no decision event recorded.
        ctx = self._ctx()
        browser = next(s for s in ctx["acceptance_surfaces"] if s["name"] == "browser")
        self.assertEqual(browser["status"], "gap")
        events = _events(self.smm_dir)
        self.assertFalse(events_of_type(events, EVENT_TYPE_DECISION))

    def test_head_mismatch_reason_uses_git_short_sha(self) -> None:
        """The HEAD-mismatch diagnostic should use 7-char (git short) SHAs.

        Concerns 2124f5892191 + 4ba371517f90: scaffold_post used [:12] in
        user-facing reasons while branching.py uses git's standard [:7].
        Mixed conventions across the same plugin's user-facing strings is
        confusing — git users expect 7-hex short shas.
        """
        scaffold_sha = self._seed_with_advanced_head()

        result = record_scaffold(
            self._snap(),
            smm_dir=self.smm_dir,
            surface="browser",
            verify_cmd="npx playwright test",
            concern_id="abc123def456",
            agent_id="test-agent",
            commit_sha=scaffold_sha,
        )

        self.assertFalse(result.ok)
        reason = result.reason or ""
        # Positive: SHA appears at all (guards against a refactor that
        # silently drops the SHA from the diagnostic). Negative: not the
        # 12-char form (the actual regression signal — [:7] is a prefix of
        # [:12], so without this the [:12] form would also pass `[:7] in`).
        self.assertIn(scaffold_sha[:7], reason)
        self.assertNotIn(scaffold_sha[:12], reason)

    def test_subject_mismatch_returns_failure(self) -> None:
        """HEAD == commit_sha but subject is not '[chore] Scaffold ...'."""
        from _helpers import init_git_with_seed

        # init_git_with_seed creates a commit with subject "[chore] seed" —
        # passes existence check but fails the scaffold-subject prefix check.
        init_git_with_seed(self.repo, "README", "seed\n")
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=self.repo,
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout.strip()

        result = record_scaffold(
            self._snap(),
            smm_dir=self.smm_dir,
            surface="browser",
            verify_cmd="npx playwright test",
            concern_id="abc123def456",
            agent_id="test-agent",
            commit_sha=head,
        )

        self.assertFalse(result.ok)
        self.assertIn("[chore] Scaffold", result.reason or "")
        ctx = self._ctx()
        browser = next(s for s in ctx["acceptance_surfaces"] if s["name"] == "browser")
        self.assertEqual(browser["status"], "gap")


def _seed_scaffold_commit(repo: Path) -> str:
    """Init a git repo with a single ``[chore] Scaffold ...`` commit; return HEAD sha.

    The HEAD-advancement gate requires the scaffold commit's subject to start
    with ``[chore] Scaffold ``; tests in this module that exercise the happy
    path use this helper instead of generic seed helpers (whose subjects
    don't satisfy the gate).
    """
    from _helpers import init_git_identity

    init_git_identity(repo)
    (repo / "README").write_text("seed\n", encoding="utf-8")
    subprocess.run(["git", "add", "README"], cwd=repo, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "[chore] Scaffold acceptance browser via playwright"],
        cwd=repo,
        capture_output=True,
        check=True,
        env=GIT_ENV,
    )
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        capture_output=True,
        text=True,
        timeout=5,
    ).stdout.strip()


if __name__ == "__main__":
    unittest.main()
