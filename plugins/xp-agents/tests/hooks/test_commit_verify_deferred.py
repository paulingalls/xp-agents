#!/usr/bin/env python3
"""Tests for the [verify-deferred] debt escape (story-002 / Milestone 5).

When a commit message is prefixed [verify-deferred] <rationale> and the
in-progress story still has untouched verify paths, bash_post_tool records a
`debt` event carrying the rationale and the deferred paths. A plain commit,
or a [verify-deferred] commit that actually touched everything, records none.
"""

import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import _common
import bash_post_tool
import sprint_store
import verify_deferred
from _bases import _PLUGIN_ROOT, _TempRepoTestCase
from _commit_helpers import patch_commits
from conftest import _HookTestCase, _make_bash_input, make_sprint_dict, make_story_dict
from event_helpers import events_of_type

_VERIFY_DEFERRED = _PLUGIN_ROOT / "scripts" / "verify_deferred.py"


class TestVerifyDeferredDebt(_HookTestCase):
    def _save_in_progress_story(self):
        story = make_story_dict(
            id="story-001",
            status="in-progress",
            acceptance_execution={"type": "pytest", "command": "pytest tests/x.py"},
        )
        sprint = make_sprint_dict(stories=[story])
        sprint_store.save_sprint(self.smm_dir, sprint, enforce_budget=False)

    def _commit(self, body, untouched):
        with (
            patch_commits(
                files=["plugins/xp-agents/scripts/x.py"], body=body, head_sha="def456"
            ),
            patch("branching.get_story_base_branch", return_value="base"),
            patch("verify_paths.untouched_verify_paths", return_value=untouched),
        ):
            bash_post_tool.run(
                _make_bash_input(
                    command=f"git commit -m '{body}'",
                    stdout="[main def456] msg\n 1 file changed",
                ),
                smm_dir=self.smm_dir,
            )
        return events_of_type(self._read_events(), _common.DEBT)

    def test_verify_deferred_records_debt(self):
        self._save_in_progress_story()
        debts = self._commit(
            "[verify-deferred] shipping under deadline", ["tests/x.py"]
        )
        self.assertEqual(len(debts), 1)
        self.assertIn("shipping under deadline", debts[0]["content"])
        self.assertEqual(debts[0]["files"], ["tests/x.py"])

    def test_deferred_rationale_excludes_trailers(self):
        self._save_in_progress_story()
        body = (
            "[verify-deferred] shipping under deadline\n\n"
            "Resolves-Event: abc123\n"
            "Co-Authored-By: Claude <noreply@anthropic.com>"
        )
        debts = self._commit(body, ["tests/x.py"])
        self.assertEqual(len(debts), 1)
        self.assertIn("shipping under deadline", debts[0]["content"])
        self.assertNotIn("Co-Authored-By", debts[0]["content"])
        self.assertNotIn("Resolves-Event", debts[0]["content"])

    def test_rationale_ending_in_a_refs_span_keeps_its_link(self):
        """The rationale must be parsed from the body the BUILDER derived, not
        from the commit event's stored `content`.

        `_common.make_event` runs `event_builder.extract_refs_suffix` on
        content: a trailing `[refs: <id>]` span is removed and its ids routed
        into the event's links. So the event's content is NOT the
        trailer-stripped body any more, and reading it back drops the span
        before the debt is built — the debt then records no link to the id the
        author named.
        """
        self._save_in_progress_story()
        debts = self._commit(
            "[verify-deferred] deadline [refs: a1b2c3d4e5f6]", ["tests/x.py"]
        )
        self.assertEqual(len(debts), 1)
        self.assertEqual(debts[0].get("references"), ["a1b2c3d4e5f6"])
        self.assertIn("deadline", debts[0]["content"])

    def test_plain_commit_records_no_debt(self):
        self._save_in_progress_story()
        debts = self._commit("ordinary work", ["tests/x.py"])
        self.assertEqual(debts, [])

    def test_deferred_but_all_touched_records_no_debt(self):
        self._save_in_progress_story()
        debts = self._commit("[verify-deferred] but I did touch it", [])
        self.assertEqual(debts, [])


class TestBranchHasVerifyDeferred(_TempRepoTestCase):
    """branch_has_verify_deferred is the single source of the [verify-deferred]
    marker check — the story-close preload calls it (CLI) instead of a
    duplicate bash grep, so parse_verify_deferred's regex is authoritative."""

    def _git(self, *args: str) -> None:
        subprocess.run(
            ["git", *args],
            cwd=self.tmpdir,
            capture_output=True,
            check=True,
            env=self._test_env,
        )

    def _commit(self, message: str) -> None:
        (self.tmpdir / "f.txt").write_text(message)
        self._git("add", "f.txt")
        self._git("commit", "-m", message)

    def _head(self) -> str:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=self.tmpdir,
            capture_output=True,
            text=True,
            check=True,
            env=self._test_env,
        ).stdout.strip()

    def test_true_when_deferred_commit_in_range(self):
        self._commit("seed")
        base = self._head()
        self._commit("[verify-deferred] shipping under deadline")
        self.assertTrue(
            verify_deferred.branch_has_verify_deferred(str(self.tmpdir), base)
        )

    def test_false_when_no_deferred_commit_in_range(self):
        self._commit("seed")
        base = self._head()
        self._commit("ordinary work")
        self.assertFalse(
            verify_deferred.branch_has_verify_deferred(str(self.tmpdir), base)
        )

    def test_false_on_git_failure(self):
        self.assertFalse(
            verify_deferred.branch_has_verify_deferred(
                str(self.tmpdir), "no-such-ref-xyz"
            )
        )

    def test_cli_prints_true_false(self):
        self._commit("seed")
        base = self._head()
        self._commit("[verify-deferred] reason")
        result = subprocess.run(
            [
                sys.executable,
                str(_VERIFY_DEFERRED),
                "has-verify-deferred",
                "--cwd",
                str(self.tmpdir),
                "--base",
                base,
            ],
            capture_output=True,
            text=True,
            env=self._test_env,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "true")


class TestBranchHasVerifyDeferredHeadArg(_TempRepoTestCase):
    """`head=` selects the range end. Its own repo (separate class) because
    the test detaches HEAD; sharing TestBranchHasVerifyDeferred's per-class
    repo would pollute that class's alphabetically-next method."""

    def _git(self, *args: str) -> None:
        subprocess.run(
            ["git", *args],
            cwd=self.tmpdir,
            capture_output=True,
            check=True,
            env=self._test_env,
        )

    def _commit(self, message: str) -> None:
        (self.tmpdir / "f.txt").write_text(message)
        self._git("add", "f.txt")
        self._git("commit", "-m", message)

    def _head(self) -> str:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=self.tmpdir,
            capture_output=True,
            text=True,
            check=True,
            env=self._test_env,
        ).stdout.strip()

    def test_head_arg_walks_base_to_named_ref(self):
        # The close-gate backstop checks target..source from the target branch,
        # so it must pass head=<source>, not rely on HEAD (=target).
        self._commit("seed")
        base = self._head()
        self._git("checkout", "-b", "feat")
        self._commit("[verify-deferred] on feat")
        self._git("checkout", base)
        # Default head=HEAD (=base): the deferred commit is out of range.
        self.assertFalse(
            verify_deferred.branch_has_verify_deferred(str(self.tmpdir), base)
        )
        # head="feat": the deferred commit is seen.
        self.assertTrue(
            verify_deferred.branch_has_verify_deferred(
                str(self.tmpdir), base, head="feat"
            )
        )


if __name__ == "__main__":
    unittest.main()
