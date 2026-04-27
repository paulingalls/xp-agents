#!/usr/bin/env python3
"""Tests for scaffold_post — build_commit_message + commit_scaffold orchestrator."""

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import scaffold_apply
from _helpers import init_git_with_seed, run_git
from scaffold_post import build_commit_message, commit_scaffold


class TestBuildCommitMessage(unittest.TestCase):
    def _msg(
        self,
        *,
        surface: str = "browser",
        tool: str = "playwright",
        tool_version: str = "1.51.0",
        verify_cmd: str = "npx playwright test tests/acceptance/example.spec.ts",
        files_created: list[str] | None = None,
        files_modified: list[str] | None = None,
        concern_id: str | None = None,
        category: str = "acceptance",
    ) -> str:
        if files_created is None:
            files_created = ["tests/acceptance/example.spec.ts", "playwright.config.ts"]
        if files_modified is None:
            files_modified = [".gitignore", "package.json"]
        return build_commit_message(
            surface=surface,
            tool=tool,
            tool_version=tool_version,
            verify_cmd=verify_cmd,
            files_created=files_created,
            files_modified=files_modified,
            concern_id=concern_id,
            category=category,
        )

    def test_subject_uses_doctrine_format(self) -> None:
        msg = self._msg()
        first = msg.splitlines()[0]
        self.assertEqual(first, "[chore] Scaffold acceptance browser via playwright")

    def test_subject_substitutes_surface_and_tool(self) -> None:
        msg = self._msg(surface="api", tool="pytest")
        first = msg.splitlines()[0]
        self.assertEqual(first, "[chore] Scaffold acceptance api via pytest")

    def test_subject_uses_category_param(self) -> None:
        msg = self._msg(surface="http_ws", tool="supertest", category="contract")
        first = msg.splitlines()[0]
        self.assertEqual(first, "[chore] Scaffold contract http_ws via supertest")

    def test_subject_category_defaults_to_acceptance(self) -> None:
        msg = self._msg(surface="browser", tool="playwright")
        first = msg.splitlines()[0]
        self.assertEqual(first, "[chore] Scaffold acceptance browser via playwright")

    def test_includes_tool_version_trailer(self) -> None:
        msg = self._msg(tool_version="2.0.0-beta.1")
        self.assertIn("Tool-version: 2.0.0-beta.1", msg)

    def test_includes_files_created_trailer(self) -> None:
        msg = self._msg(files_created=["a.ts", "b/c.ts"])
        self.assertIn("Files-created: a.ts, b/c.ts", msg)

    def test_includes_files_modified_trailer(self) -> None:
        msg = self._msg(files_modified=[".gitignore", "package.json"])
        self.assertIn("Files-modified: .gitignore, package.json", msg)

    def test_omits_files_created_when_empty(self) -> None:
        msg = self._msg(files_created=[])
        self.assertNotIn("Files-created:", msg)

    def test_omits_files_modified_when_empty(self) -> None:
        msg = self._msg(files_modified=[])
        self.assertNotIn("Files-modified:", msg)

    def test_includes_verification_trailer(self) -> None:
        msg = self._msg(verify_cmd="pytest tests/acceptance")
        self.assertIn("Verification: pytest tests/acceptance", msg)

    def test_resolves_event_trailer_with_concern_id(self) -> None:
        msg = self._msg(concern_id="abc123def456")
        lines = msg.splitlines()
        self.assertIn("Resolves-Event: abc123def456", lines)

    def test_resolves_event_trailer_none_when_concern_omitted(self) -> None:
        msg = self._msg(concern_id=None)
        lines = msg.splitlines()
        self.assertIn("Resolves-Event: none", lines)

    def test_resolves_event_is_last_trailer(self) -> None:
        """Resolves-Event is the canonical last trailer per doctrine."""
        msg = self._msg(concern_id="abc123def456")
        non_empty = [line for line in msg.splitlines() if line.strip()]
        self.assertEqual(non_empty[-1], "Resolves-Event: abc123def456")

    def test_subject_separated_from_trailers_by_blank_line(self) -> None:
        """git interpret-trailers needs a blank line between subject and trailers."""
        msg = self._msg()
        lines = msg.split("\n")
        self.assertTrue(lines[0].startswith("[chore] Scaffold"))
        self.assertEqual(lines[1], "")
        self.assertTrue(lines[2].startswith("Tool-version:"))


def _setup_git_repo(repo: Path) -> None:
    """git init + identity + initial README commit so branch creation has a base."""
    init_git_with_seed(repo, "README", "seed\n")


def _write_branching_strategy(smm_dir: Path, stage: int) -> None:
    smm_dir.mkdir(parents=True, exist_ok=True)
    (smm_dir / "system_context.json").write_text(
        json.dumps({"branching_strategy": {"stage": stage}}),
        encoding="utf-8",
    )


class _CommitScaffoldTestBase(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = Path(tempfile.mkdtemp(prefix="scaffold-commit-test-"))
        self.smm_dir = Path(tempfile.mkdtemp(prefix="scaffold-commit-smm-"))
        _setup_git_repo(self.repo)
        # Pre-seed a created file so write_files would have written it.
        (self.repo / "tests").mkdir()
        (self.repo / "tests" / "example.spec.ts").write_text(
            "test();\n", encoding="utf-8"
        )

    def tearDown(self) -> None:
        shutil.rmtree(self.repo, ignore_errors=True)
        shutil.rmtree(self.smm_dir, ignore_errors=True)

    def _snap(self) -> scaffold_apply.ApplySnapshot:
        plan = {
            "surface": "browser",
            "tool": "playwright",
            "tool_version": "1.51.0",
            "files_to_create": [
                {"path": "tests/example.spec.ts", "description": "spec"},
            ],
            "files_to_modify": [],
            "install_cmds": [],
            "verify_cmd": "pytest tests/",
            "branch_name": "scaffold/test",
        }
        return scaffold_apply.ApplySnapshot(
            snapshot_id="testid",
            snapshot_dir=self.smm_dir / "snap",
            repo_root=self.repo,
            plan=plan,
        )


class TestCommitScaffoldStageZero(_CommitScaffoldTestBase):
    def test_stage_0_commits_on_current_head(self) -> None:
        _write_branching_strategy(self.smm_dir, 0)
        result = commit_scaffold(
            self._snap(),
            smm_dir=self.smm_dir,
            stage=0,
            surface="browser",
            tool="playwright",
            tool_version="1.51.0",
            concern_id=None,
        )
        self.assertTrue(result.ok, result.reason)
        self.assertEqual(result.branch, "main")
        head = run_git(["git", "rev-parse", "HEAD"], self.repo).stdout.strip()
        self.assertEqual(result.sha, head)

    def test_stage_0_subject_uses_doctrine_format(self) -> None:
        _write_branching_strategy(self.smm_dir, 0)
        commit_scaffold(
            self._snap(),
            smm_dir=self.smm_dir,
            stage=0,
            surface="browser",
            tool="playwright",
            tool_version="1.51.0",
            concern_id=None,
        )
        log = run_git(["git", "log", "-1", "--format=%s"], self.repo)
        subject = log.stdout.strip()
        self.assertEqual(subject, "[chore] Scaffold acceptance browser via playwright")

    def test_stage_0_resolves_event_in_body(self) -> None:
        _write_branching_strategy(self.smm_dir, 0)
        commit_scaffold(
            self._snap(),
            smm_dir=self.smm_dir,
            stage=0,
            surface="browser",
            tool="playwright",
            tool_version="1.51.0",
            concern_id="abc123def456",
        )
        body = run_git(["git", "log", "-1", "--format=%B"], self.repo).stdout
        self.assertIn("Resolves-Event: abc123def456", body)


class TestCommitScaffoldStageOne(_CommitScaffoldTestBase):
    def test_stage_1_creates_scaffold_branch(self) -> None:
        _write_branching_strategy(self.smm_dir, 1)
        # Move off main so protected-branch refusal does not trigger.
        run_git(["git", "checkout", "-b", "feature/work"], self.repo)
        result = commit_scaffold(
            self._snap(),
            smm_dir=self.smm_dir,
            stage=1,
            surface="browser",
            tool="playwright",
            tool_version="1.51.0",
            concern_id=None,
        )
        self.assertTrue(result.ok, result.reason)
        self.assertTrue(
            result.branch.endswith("/scaffold-browser"), f"branch={result.branch!r}"
        )
        current = run_git(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"], self.repo
        ).stdout.strip()
        self.assertEqual(current, result.branch)

    def test_stage_1_refuses_on_protected_branch(self) -> None:
        _write_branching_strategy(self.smm_dir, 1)
        # Default branch is main (protected at stage 1+).
        result = commit_scaffold(
            self._snap(),
            smm_dir=self.smm_dir,
            stage=1,
            surface="browser",
            tool="playwright",
            tool_version="1.51.0",
            concern_id=None,
        )
        self.assertFalse(result.ok)
        self.assertIn("main", result.reason or "")
        # No commit was created.
        oneline = run_git(["git", "log", "--oneline"], self.repo).stdout.strip()
        self.assertEqual(len(oneline.splitlines()), 1)


if __name__ == "__main__":
    unittest.main()
