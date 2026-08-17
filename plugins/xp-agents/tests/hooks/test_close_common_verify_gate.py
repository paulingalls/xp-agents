#!/usr/bin/env python3
"""Tests for close_common.py merge --verify-gate (the deterministic backstop).

cmd_merge gains an optional verify-gate that RE-DERIVES the close gate signal
and refuses the merge before it happens — defending against an LLM that skips
the SKILL prose gate. Two gates, both fail closed:

- `touch` (story-close): refuse when the story declares acceptance-test paths
  that no commit on target..source touched, unless a [verify-deferred] commit
  defers. Self-derived from sprint.json + git (no SKILL-passed verdict).
- `acceptance` (sprint-close): refuse when the last sprint-verify event is red,
  unless --force-verify (the SKILL passes it only on the --force-close path).

Absent --verify-gate the merge is unchanged (plan/free close inert).
"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import _branching_fixtures as _bf
from _bases import _PLUGIN_ROOT
from event_schema import EVENT_TYPE_SPRINT, SPRINT_ACTION_VERIFY

_CLOSE_COMMON = _PLUGIN_ROOT / "scripts" / "close_common.py"


def _run(args: list[str], cwd: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(_CLOSE_COMMON), *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        env=_bf.GIT_ENV,
    )


def _make_smm(td: str) -> Path:
    smm = Path(td) / "smm"
    smm.mkdir()
    (smm / "events.jsonl").touch()
    (smm / "events.lock").touch()
    return smm


def _seed_story_sprint(smm: Path, command: str = "pytest acc_test.py") -> None:
    story = {
        "id": "story-001",
        "title": "t",
        "status": "done",
        "dependencies": [],
        "milestone_ref": "",
        "design_sources": "",
        "context": "",
        "file_domain": [],
        "interface_contracts": [],
        "acceptance_criteria": [],
        "acceptance_execution": {"type": "pytest", "command": command},
    }
    (smm / "sprint.json").write_text(
        json.dumps(
            {
                "sprint_id": "sprint-001",
                "goal": "g",
                "started": "2026-05-21",
                "milestone": "",
                "stories": [story],
            }
        )
    )


def _seed_verify_event(smm: Path, status: str) -> None:
    event = {
        "id": "aaaaaaaaaaaa",
        "ts": "2026-05-21T00:00:00+00:00",
        "type": EVENT_TYPE_SPRINT,
        "agent_id": "verify-acceptance",
        "content": "Sprint verify",
        "schema_version": 1,
        "metadata": {
            "sprint_id": "sprint-001",
            "action": SPRINT_ACTION_VERIFY,
            "verify_status": status,
            "failing": [{"story": "story-001", "command": "false", "returncode": 1}]
            if status == "red"
            else [],
        },
    }
    (smm / "events.jsonl").write_text(json.dumps(event) + "\n")


def _merge_acceptance(td: str, main: str, smm: Path, *extra: str):
    """The acceptance gate's merge invocation — one spelling, four callers.

    Four copies of the same fourteen-element list is how one of them ends up
    naming a different gate or a different branch and passes for the wrong
    reason.
    """
    return _run(
        [
            "merge",
            "--cwd",
            td,
            "--source",
            "feat",
            "--target",
            main,
            "--verify-gate",
            "acceptance",
            "--smm-dir",
            str(smm),
            *extra,
        ]
    )


def _merge_touch(td: str, source: str, main: str, smm: Path):
    """The touch gate's merge invocation — same reason as `_merge_acceptance`.

    Six inline copies of this list is how one ends up naming `acceptance`
    and passing for the wrong reason.
    """
    return _run(
        [
            "merge",
            "--cwd",
            td,
            "--source",
            source,
            "--target",
            main,
            "--verify-gate",
            "touch",
            "--smm-dir",
            str(smm),
        ]
    )


class TestMergeVerifyTouchGate(unittest.TestCase):
    def test_refuses_when_declared_path_untouched_and_not_deferred(self):
        with tempfile.TemporaryDirectory() as td:
            _bf.init_repo(td)
            main = _bf.get_current_branch(td)
            smm = _make_smm(td)
            _seed_story_sprint(smm)
            _bf.make_commit(td, "u/story-001-x", "other.py", "x", "wip")
            result = _merge_touch(td, "u/story-001-x", main, smm)
            self.assertEqual(result.returncode, 1, result.stdout)
            self.assertIn("acc_test.py", result.stderr)
            self.assertTrue(_bf.branch_exists(td, "u/story-001-x"))
            merges = subprocess.run(
                ["git", "log", "--merges", "--oneline"],
                cwd=td,
                capture_output=True,
                text=True,
                env=_bf.GIT_ENV,
            ).stdout
            self.assertEqual(merges.strip(), "", "no merge on refusal")

    def test_passes_when_a_commit_touches_the_path(self):
        with tempfile.TemporaryDirectory() as td:
            _bf.init_repo(td)
            main = _bf.get_current_branch(td)
            smm = _make_smm(td)
            _seed_story_sprint(smm)
            _bf.make_commit(td, "u/story-001-y", "acc_test.py", "x", "add acc test")
            result = _merge_touch(td, "u/story-001-y", main, smm)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(_bf.branch_exists(td, "u/story-001-y"))

    def test_refuses_when_the_declared_path_is_only_staged(self):
        # A merge carries commits, not the index. story-006 taught the
        # COMMIT-TIME nudge to count staged files as coverage; if that ever
        # reaches this gate, a story merges with its acceptance test staged
        # and never committed. The other direction — an unrelated dirty
        # index must not silently defer the refusal either.
        with tempfile.TemporaryDirectory() as td:
            _bf.init_repo(td)
            main = _bf.get_current_branch(td)
            smm = _make_smm(td)
            _seed_story_sprint(smm)
            _bf.make_commit(td, "u/story-001-s", "other.py", "x", "wip")
            (Path(td) / "acc_test.py").write_text("x")
            subprocess.run(
                ["git", "add", "acc_test.py"],
                cwd=td,
                capture_output=True,
                check=True,
                env=_bf.GIT_ENV,
            )
            result = _merge_touch(td, "u/story-001-s", main, smm)
            self.assertEqual(result.returncode, 1, result.stdout)
            # Assert the GATE's wording, not just exit 1: a staged file also
            # makes `git merge` itself fail ("local changes would be
            # overwritten"), which is exit 1 naming acc_test.py for a
            # completely different reason. A laxer assertion here passes
            # whether or not the gate held.
            self.assertIn("merge refused", result.stderr)
            self.assertIn("acc_test.py", result.stderr)
            self.assertTrue(_bf.branch_exists(td, "u/story-001-s"))

    def test_passes_when_verify_deferred_commit_present(self):
        with tempfile.TemporaryDirectory() as td:
            _bf.init_repo(td)
            main = _bf.get_current_branch(td)
            smm = _make_smm(td)
            _seed_story_sprint(smm)
            _bf.make_commit(
                td, "u/story-001-z", "other.py", "x", "[verify-deferred] deadline"
            )
            result = _merge_touch(td, "u/story-001-z", main, smm)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(_bf.branch_exists(td, "u/story-001-z"))

    def test_refuses_when_sprint_json_is_corrupt(self):
        # Corrupt sprint.json must fail HARD: the gate can't verify the
        # declared paths, so it refuses rather than silently passing.
        with tempfile.TemporaryDirectory() as td:
            _bf.init_repo(td)
            main = _bf.get_current_branch(td)
            smm = _make_smm(td)
            (smm / "sprint.json").write_text("{ not valid json")
            _bf.make_commit(td, "u/story-001-c", "other.py", "x", "wip")
            result = _merge_touch(td, "u/story-001-c", main, smm)
            self.assertEqual(result.returncode, 1, result.stdout)
            self.assertIn("corrupt", result.stderr.lower())
            self.assertTrue(_bf.branch_exists(td, "u/story-001-c"))
            merges = subprocess.run(
                ["git", "log", "--merges", "--oneline"],
                cwd=td,
                capture_output=True,
                text=True,
                env=_bf.GIT_ENV,
            ).stdout
            self.assertEqual(merges.strip(), "", "no merge on corrupt sprint")

    def test_passes_when_branch_story_absent_from_valid_sprint(self):
        # A valid sprint that simply lacks the branch's story is ABSENCE,
        # not corruption — the gate fails open and the merge proceeds.
        with tempfile.TemporaryDirectory() as td:
            _bf.init_repo(td)
            main = _bf.get_current_branch(td)
            smm = _make_smm(td)
            _seed_story_sprint(smm)  # holds only story-001
            _bf.make_commit(td, "u/story-999-x", "other.py", "x", "wip")
            result = _merge_touch(td, "u/story-999-x", main, smm)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(_bf.branch_exists(td, "u/story-999-x"))

    def test_passes_when_story_declares_no_verify_paths(self):
        with tempfile.TemporaryDirectory() as td:
            _bf.init_repo(td)
            main = _bf.get_current_branch(td)
            smm = _make_smm(td)
            # No acceptance_execution → no declared paths → nothing to gate.
            (smm / "sprint.json").write_text(
                json.dumps(
                    {
                        "sprint_id": "sprint-001",
                        "goal": "g",
                        "started": "2026-05-21",
                        "milestone": "",
                        "stories": [
                            {
                                "id": "story-001",
                                "title": "t",
                                "status": "done",
                                "dependencies": [],
                                "milestone_ref": "",
                                "design_sources": "",
                                "context": "",
                                "file_domain": [],
                                "interface_contracts": [],
                                "acceptance_criteria": [],
                            }
                        ],
                    }
                )
            )
            _bf.make_commit(td, "u/story-001-q", "other.py", "x", "wip")
            result = _merge_touch(td, "u/story-001-q", main, smm)
            self.assertEqual(result.returncode, 0, result.stderr)


class TestMergeVerifyAcceptanceGate(unittest.TestCase):
    def _setup_unverified(self, td: str) -> str:
        """A verify-bearing sprint with no verify event at all."""
        _bf.init_repo(td)
        main = _bf.get_current_branch(td)
        _seed_story_sprint(_make_smm(td))
        _bf.make_commit(td, "feat", "f.txt", "x", "feature")
        return main

    def _setup_red(self, td: str) -> str:
        """The same sprint, plus a recorded RED verify run."""
        main = self._setup_unverified(td)
        _seed_verify_event(Path(td) / "smm", "red")
        return main

    def test_refuses_on_red_without_force(self):
        with tempfile.TemporaryDirectory() as td:
            main = self._setup_red(td)
            smm = Path(td) / "smm"
            result = _merge_acceptance(td, main, smm)
            self.assertEqual(result.returncode, 1, result.stdout)
            self.assertTrue(_bf.branch_exists(td, "feat"))

    def test_force_verify_bypasses_red(self):
        with tempfile.TemporaryDirectory() as td:
            main = self._setup_red(td)
            smm = Path(td) / "smm"
            result = _merge_acceptance(td, main, smm, "--force-verify")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(_bf.branch_exists(td, "feat"))

    def test_refuses_with_clean_message_when_sprint_json_is_corrupt(self):
        # Parity with the touch gate: a corrupt sprint.json must produce a
        # clean refusal string, not a raw traceback. Both block the merge.
        with tempfile.TemporaryDirectory() as td:
            _bf.init_repo(td)
            main = _bf.get_current_branch(td)
            smm = _make_smm(td)
            (smm / "sprint.json").write_text("{ not valid json")
            _bf.make_commit(td, "feat", "f.txt", "x", "feature")
            result = _merge_acceptance(td, main, smm)
            self.assertEqual(result.returncode, 1, result.stdout)
            self.assertIn("corrupt", result.stderr.lower())
            self.assertNotIn("Traceback", result.stderr)
            self.assertTrue(_bf.branch_exists(td, "feat"))

    def test_refuses_when_verify_bearing_work_was_never_verified(self):
        """No event is not the same as nothing to gate.

        This case used to PASS on a sprint carrying a verify-bearing
        `acceptance_execution`, so what it pinned was "never verified merges
        green". The rerun runs under a tool bound SMALLER than its own, so a
        long acceptance suite is killed before it can append: this silence is
        the shape of a lost run, not of a clean one.
        """
        with tempfile.TemporaryDirectory() as td:
            main = self._setup_unverified(td)
            result = _merge_acceptance(td, main, Path(td) / "smm")
            self.assertEqual(result.returncode, 1, result.stdout)
            self.assertIn("no verify run", result.stderr)
            self.assertTrue(_bf.branch_exists(td, "feat"))

    def test_force_verify_bypasses_never_verified(self):
        """`--force-close` stays the one documented override, or the new
        refusal is a wall rather than a gate."""
        with tempfile.TemporaryDirectory() as td:
            main = self._setup_unverified(td)
            smm = Path(td) / "smm"
            result = _merge_acceptance(td, main, smm, "--force-verify")
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_passes_when_there_is_nothing_verify_bearing(self):
        """All-prose acceptance has no run to be missing. The MANUAL shape,
        where the predicate broke, is pinned on `verify_report` elsewhere."""
        with tempfile.TemporaryDirectory() as td:
            main = self._setup_unverified(td)
            smm = Path(td) / "smm"
            sprint = json.loads((smm / "sprint.json").read_text())
            del sprint["stories"][0]["acceptance_execution"]
            (smm / "sprint.json").write_text(json.dumps(sprint))
            result = _merge_acceptance(td, main, smm)
            self.assertEqual(result.returncode, 0, result.stderr)


class TestMergeVerifyGateMisconfig(unittest.TestCase):
    """--verify-gate without --smm-dir refuses — never silently no-ops (which
    would invisibly disable the backstop)."""

    def test_verify_gate_without_smm_dir_refuses(self):
        with tempfile.TemporaryDirectory() as td:
            _bf.init_repo(td)
            main = _bf.get_current_branch(td)
            _bf.make_commit(td, "u/story-001-x", "other.py", "x", "wip")
            result = _run(
                [
                    "merge",
                    "--cwd",
                    td,
                    "--source",
                    "u/story-001-x",
                    "--target",
                    main,
                    "--verify-gate",
                    "touch",
                ]
            )
            self.assertEqual(result.returncode, 1, result.stdout)
            self.assertIn("--smm-dir", result.stderr)
            self.assertTrue(_bf.branch_exists(td, "u/story-001-x"))


class TestMergeNoGateInert(unittest.TestCase):
    """No --verify-gate → merge behaves exactly as before (plan/free close)."""

    def test_untouched_story_merges_without_gate_flag(self):
        with tempfile.TemporaryDirectory() as td:
            _bf.init_repo(td)
            main = _bf.get_current_branch(td)
            smm = _make_smm(td)
            _seed_story_sprint(smm)
            _bf.make_commit(td, "u/story-001-x", "other.py", "x", "wip")
            # Same untouched-path setup as the refusal test, but no gate flag.
            result = _run(
                ["merge", "--cwd", td, "--source", "u/story-001-x", "--target", main]
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(_bf.branch_exists(td, "u/story-001-x"))


if __name__ == "__main__":
    unittest.main()
