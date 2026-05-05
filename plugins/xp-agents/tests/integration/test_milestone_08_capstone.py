#!/usr/bin/env python3
"""M-8 capstone: cross-cutting acceptance test for stories 001-003.

Sprint-062 / M-8 fixes close-cycle frictions from sprint-061. Four stories
ship the underlying changes; this capstone exercises the three behavioral
ones end-to-end:

  - story-001: verify_acceptance.py CLI runs multi-command sprint AC
  - story-002: pre_tool_bash warns on `cd <wt> && git ...` patterns
  - story-003: trailer-extract resolves HEAD from worktree path, not orchestrator

Story-004 (doctrine bullets in skills + TEAMMATE_GUIDE) is doc-only and
verified by the pin tests in test_plugin_integrity.py — not exercised here
because there's no behavior to drive through hooks.

The capstone fixtures a real git worktree under tmpdir/.claude/worktrees/
(reusing pre_tool_bash.WORKTREE_PATH_FRAGMENT so matcher and fixture share
the same convention), opens a concern with a known event id, drives the
bash hook pipeline for both commit shapes (cd-then-git AND git -C), and
asserts the full chain — warning emission, trailer extraction, concern
auto-resolution, and the verify_acceptance CLI exit-code semantics.
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

import pre_tool_bash  # for WORKTREE_PATH_FRAGMENT — story-002 export
from conftest import _IntegrationTestCase, cleanup_test_worktrees

_PLUGIN_ROOT = Path(__file__).parent.parent.parent
_VERIFY_ACCEPTANCE = _PLUGIN_ROOT / "scripts" / "verify_acceptance.py"


class TestMilestone08Capstone(_IntegrationTestCase):
    """End-to-end M-8 acceptance composing all four prior stories."""

    # ------------------------------------------------------------------
    # Fixture: real worktree under WORKTREE_PATH_FRAGMENT
    # ------------------------------------------------------------------

    def _make_capstone_worktree(self, name: str = "worktree-cap") -> Path:
        """Create a worktree at <tmpdir>/<WORKTREE_PATH_FRAGMENT>/<name>.

        Reuses story-002's WORKTREE_PATH_FRAGMENT so the matcher's path
        convention and this fixture cannot drift apart.
        """
        wt_root = self.tmpdir / pre_tool_bash.WORKTREE_PATH_FRAGMENT
        wt_root.mkdir(parents=True, exist_ok=True)
        wt_path = wt_root / name
        branch = f"capstone/{name}"
        subprocess.run(
            ["git", "worktree", "add", "-b", branch, str(wt_path)],
            cwd=self.tmpdir,
            capture_output=True,
            check=True,
        )
        # Per-worktree user.email/user.name isn't inherited from the parent
        # repo's local config in all git versions; set explicitly.
        for k, v in (("user.email", "test@test.com"), ("user.name", "Test")):
            subprocess.run(
                ["git", "-C", str(wt_path), "config", k, v],
                capture_output=True,
                check=True,
            )
        return wt_path

    def _open_concern(self, content: str = "auth bypass risk") -> str:
        """Append a concern event; return its event id."""
        append_sh = _PLUGIN_ROOT / "smm" / "append.sh"
        result = subprocess.run(
            [
                "bash",
                str(append_sh),
                "--smm-dir",
                str(self.smm_dir),
                "--type",
                "concern",
                "--agent",
                "test",
                "--severity",
                "medium",
                "--content",
                content,
            ],
            capture_output=True,
            text=True,
            check=True,
            env=self._test_env,
        )
        return result.stdout.strip()

    def tearDown(self):
        cleanup_test_worktrees(self.tmpdir, prefix="worktree-")
        super().tearDown()

    # ------------------------------------------------------------------
    # Shared helpers for AC1/AC2 — both shapes commit + resolve the same way,
    # only the bash command shape and warning expectation differ.
    # ------------------------------------------------------------------

    def _commit_with_trailer(
        self, wt_path: Path, file_name: str, summary: str, concern_id: str
    ) -> str:
        """Make a real commit in the worktree with a Resolves-Event trailer.

        Uses `git -C` for fixture setup so the test setup itself never trips
        the cd-pattern matcher — only the bash command we drive through the
        hook should trigger it.
        """
        (wt_path / file_name).write_text(file_name)
        subprocess.run(
            ["git", "-C", str(wt_path), "add", file_name],
            capture_output=True,
            check=True,
        )
        commit_msg = f"{summary}\n\nResolves-Event: {concern_id}\n"
        subprocess.run(
            ["git", "-C", str(wt_path), "commit", "-m", commit_msg],
            capture_output=True,
            check=True,
        )
        return subprocess.run(
            ["git", "-C", str(wt_path), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()

    def _bash_input(self, command: str, *, stdout: str = "") -> dict:
        return {
            "session_id": "cap",
            "tool_name": "Bash",
            "tool_input": {"command": command},
            "tool_response": {"stdout": stdout},
            "cwd": str(self.tmpdir),
            "agent_id": "main",
        }

    def _assert_concern_auto_resolved(self, concern_id: str, worktree_sha: str):
        events = self._read_events()
        resolutions = [
            e
            for e in events
            if concern_id in (e.get("metadata", {}).get("resolves") or [])
        ]
        self.assertGreater(
            len(resolutions),
            0,
            f"Expected auto-resolution event for {concern_id}; got {events}",
        )
        # The recorded commit SHA must match the worktree HEAD (story-003).
        commit_shas = [e.get("metadata", {}).get("commit_hash") for e in resolutions]
        self.assertIn(
            worktree_sha,
            commit_shas,
            f"Expected worktree SHA {worktree_sha} in {commit_shas} — "
            "trailer-extract is reading the wrong cwd",
        )

    def _run_capstone_shape(
        self,
        wt_name: str,
        file_name: str,
        summary: str,
        bash_command_template: str,
        *,
        expect_warning: bool,
    ):
        """Drive one commit-shape end-to-end through pre+post hooks.

        `bash_command_template` accepts `{wt}` and `{cid}` placeholders.
        Asserts: (1) pre_tool_bash warning matches expectation; (2) post-hook
        records concern resolution with the worktree's SHA.
        """
        wt_path = self._make_capstone_worktree(wt_name)
        concern_id = self._open_concern(f"{wt_name} capstone concern")
        worktree_sha = self._commit_with_trailer(
            wt_path, file_name, summary, concern_id
        )
        command = bash_command_template.format(wt=wt_path, cid=concern_id)

        pre_result = self._run_script("pre_tool_bash.py", self._bash_input(command))
        self.assertEqual(pre_result.returncode, 0, f"stderr: {pre_result.stderr}")
        if expect_warning:
            # AC1: cd-shape — warning text mentions git -C and trailer impact.
            self.assertIn("git -C", pre_result.stdout)
            self.assertIn("trailer", pre_result.stdout)
        else:
            # AC2: git -C shape — matcher must NOT fire.
            self.assertNotIn("Avoid `cd <worktree>", pre_result.stdout)

        post_result = self._run_script(
            "bash_post_tool.py",
            self._bash_input(command, stdout=f"[capstone xyz] {summary}\n"),
        )
        self.assertEqual(post_result.returncode, 0, f"stderr: {post_result.stderr}")
        self._assert_concern_auto_resolved(concern_id, worktree_sha)

    # ------------------------------------------------------------------
    # AC1: cd-then-git shape — warning fires AND trailer auto-resolves
    # ------------------------------------------------------------------

    def test_cd_then_git_warns_and_auto_resolves(self):
        self._run_capstone_shape(
            wt_name="worktree-cap-cd",
            file_name="feature.txt",
            summary="feat: capstone cd-shape",
            bash_command_template=(
                "cd {wt} && git commit -m '...Resolves-Event: {cid}' && cd -"
            ),
            expect_warning=True,
        )

    # ------------------------------------------------------------------
    # AC2: git -C shape — auto-resolves WITHOUT warning
    # ------------------------------------------------------------------

    def test_git_dash_C_auto_resolves_without_warning(self):
        self._run_capstone_shape(
            wt_name="worktree-cap-dashC",
            file_name="feature2.txt",
            summary="feat: capstone dash-C",
            bash_command_template=("git -C {wt} commit -m '...Resolves-Event: {cid}'"),
            expect_warning=False,
        )

    # ------------------------------------------------------------------
    # AC3: verify_acceptance.py honors commands: list[str] (story-001)
    # ------------------------------------------------------------------

    def test_verify_acceptance_multi_command_pass_and_fail(self):
        # Two-command story — both pass → exit 0; one fails → non-zero.
        sprint_data = {
            "sprint_id": "cap",
            "goal": "capstone",
            "started": "2026-05-05",
            "milestone": "M-8 capstone",
            "stories": [
                {
                    "id": "story-cap-pass",
                    "title": "Two passing commands",
                    "status": "in-progress",
                    "dependencies": [],
                    "milestone_ref": "",
                    "design_sources": "",
                    "context": "",
                    "file_domain": [],
                    "interface_contracts": [],
                    "acceptance_criteria": [],
                    "acceptance_execution": {
                        "type": "bash",
                        "commands": ["true", "true"],
                    },
                },
                {
                    "id": "story-cap-fail",
                    "title": "One passing, one failing",
                    "status": "in-progress",
                    "dependencies": [],
                    "milestone_ref": "",
                    "design_sources": "",
                    "context": "",
                    "file_domain": [],
                    "interface_contracts": [],
                    "acceptance_criteria": [],
                    "acceptance_execution": {
                        "type": "bash",
                        "commands": ["true", "false"],
                    },
                },
            ],
        }
        # Write sprint.json into a temp SMM dir so the orchestrator's real
        # sprint.json is never touched.
        cap_smm_dir = Path(tempfile.mkdtemp())
        try:
            (cap_smm_dir / "sprint.json").write_text(json.dumps(sprint_data))

            # All-green story → exit 0
            ok = subprocess.run(
                [
                    "python3",
                    str(_VERIFY_ACCEPTANCE),
                    "--story",
                    "story-cap-pass",
                    "--smm-dir",
                    str(cap_smm_dir),
                ],
                capture_output=True,
                text=True,
            )
            self.assertEqual(
                ok.returncode, 0, f"all-green exited non-zero: {ok.stderr}"
            )

            # Mixed story → non-zero, names the failing command in stderr.
            fail = subprocess.run(
                [
                    "python3",
                    str(_VERIFY_ACCEPTANCE),
                    "--story",
                    "story-cap-fail",
                    "--smm-dir",
                    str(cap_smm_dir),
                ],
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(fail.returncode, 0, "first-red must exit non-zero")
            # Tighter than `assertIn("false")` alone — guards against the
            # substring matching unrelated traceback text.
            self.assertIn("command failed", fail.stderr)
            self.assertIn("false", fail.stderr)
        finally:
            shutil.rmtree(cap_smm_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
