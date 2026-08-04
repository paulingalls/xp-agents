#!/usr/bin/env python3
"""Tests for verify_acceptance.py --sprint batch mode + --query-verify-status.

Milestone 6 reruns every verify-bearing acceptance item across the sprint and
gates close on green. story-001 builds the primitive:

- ``--sprint`` iterates all stories, gathers per-AC verify objects (by surface)
  plus story-level acceptance_execution, runs each command, prints a
  surface-grouped PASS/FAIL matrix, and emits a deterministic
  ``sprint``/``action=verify`` event whose metadata carries verify_status +
  the failing items.
- ``--query-verify-status`` reads the last such event for the current sprint
  and reports red/green/none (the reader the sprint-close gate consumes).

The green/red signal is script-emitted (not reviewer prose) so the close gate
reads a deterministic event and never recomputes.
"""

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

import sprint_store
import verify_acceptance
from _bases import _HookTestCase
from conftest import make_sprint_dict, run_cli, verify_events

_VERIFY_ACCEPTANCE = (
    Path(__file__).parent.parent.parent / "scripts" / "verify_acceptance.py"
)


def _story(
    story_id: str,
    *,
    acceptance_criteria,
    acceptance_execution=None,
    status: str = "done",
) -> dict:
    story = {
        "id": story_id,
        "title": f"Story {story_id}",
        "status": status,
        "dependencies": [],
        "milestone_ref": "",
        "design_sources": "",
        "context": "ctx",
        "file_domain": [f"src/{story_id}.py — x"],
        "interface_contracts": [],
        "acceptance_criteria": acceptance_criteria,
    }
    if acceptance_execution is not None:
        story["acceptance_execution"] = acceptance_execution
    return story


class _SprintCLITestCase(_HookTestCase):
    def _seed(self, stories: list[dict]) -> None:
        sprint = make_sprint_dict(sprint_id="sprint-093", stories=stories)
        sprint_store.save_sprint(self.smm_dir, sprint, enforce_budget=False)

    def _run(self, *args: str):
        return run_cli(_VERIFY_ACCEPTANCE, list(args), self.smm_dir)

    def _verify_events(self) -> list[dict]:
        return verify_events(self._read_events())


class TestFailingItemsCapped(_SprintCLITestCase):
    def test_failing_list_capped_but_count_is_true_total(self):
        # metadata is not budget-checked, and failing[] grows with failure
        # count — cap the stored detail while keeping the true count + status.
        cap = verify_acceptance._MAX_FAILING_ITEMS
        n = cap + 5
        self._seed(
            [
                _story(
                    "story-001",
                    acceptance_criteria=[
                        {"description": f"f{i}", "surface": "cli", "command": "false"}
                        for i in range(n)
                    ],
                ),
            ]
        )
        result = self._run("--sprint")
        self.assertEqual(result.returncode, 0, result.stderr)
        meta = self._verify_events()[0]["metadata"]
        self.assertEqual(meta["verify_status"], "red")
        self.assertEqual(len(meta["failing"]), cap, "stored failing[] must be capped")
        # The human-readable count reflects the TRUE total, not the cap.
        self.assertIn(f"{n} failing", self._verify_events()[0]["content"])


class TestSprintEnvPropagation(_SprintCLITestCase):
    def test_smm_dir_visible_in_sprint_subprocess(self):
        # Sprint-mode parallel: _run_sprint must also forward SMM_DIR into
        # each AC subprocess. The story-mode test covers _run_commands;
        # this covers _run_sprint's separate call site.
        # See test_verify_acceptance.test_smm_dir_visible_in_subprocess for
        # the same env-strip rationale.
        self._seed(
            [
                _story(
                    "story-001",
                    acceptance_criteria=[
                        {
                            "description": "needs SMM_DIR",
                            "surface": "cli",
                            "command": 'test -n "$SMM_DIR"',
                        },
                    ],
                ),
            ]
        )
        env_no_smm = {k: v for k, v in os.environ.items() if k != "SMM_DIR"}
        with patch.dict(os.environ, env_no_smm, clear=True):
            result = self._run("--sprint")
        self.assertEqual(result.returncode, 0, result.stderr)
        meta = self._verify_events()[0]["metadata"]
        self.assertEqual(
            meta["verify_status"],
            "green",
            "$SMM_DIR not propagated to sprint-mode AC subprocess; "
            f"failing={meta.get('failing')!r}",
        )


class TestSprintBatchMatrix(_SprintCLITestCase):
    def test_matrix_grouped_by_surface_with_pass_fail(self):
        self._seed(
            [
                _story(
                    "story-001",
                    acceptance_criteria=[
                        "a manual string AC",
                        {"description": "ok", "surface": "cli", "command": "true"},
                        {"description": "bad", "surface": "cli", "command": "false"},
                    ],
                ),
                _story(
                    "story-002",
                    acceptance_criteria=["string only"],
                    acceptance_execution={"type": "pytest", "command": "true"},
                ),
            ]
        )
        result = self._run("--sprint")
        self.assertEqual(result.returncode, 0, result.stderr)
        out = result.stdout
        # surface buckets: the "cli" per-AC items and the story-level "(story)"
        self.assertIn("cli", out)
        self.assertIn("(story)", out)
        self.assertIn("[PASS]", out)
        self.assertIn("[FAIL]", out)
        self.assertIn("story-001", out)
        self.assertIn("story-002", out)


class TestAllStringSkip(_SprintCLITestCase):
    def test_no_verify_items_emits_no_event_exit_0(self):
        self._seed(
            [
                _story("story-001", acceptance_criteria=["manual 1", "E2E: manual 2"]),
                _story("story-002", acceptance_criteria=["manual 3"]),
            ]
        )
        result = self._run("--sprint")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self._verify_events(), [])

    def test_query_status_none_when_no_event(self):
        self._seed([_story("story-001", acceptance_criteria=["manual"])])
        result = self._run("--query-verify-status")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("none", result.stdout)


class TestMixedRedEventAndQuery(_SprintCLITestCase):
    def _seed_mixed(self) -> None:
        self._seed(
            [
                _story(
                    "story-001",
                    acceptance_criteria=[
                        "manual",
                        {"description": "ok", "surface": "cli", "command": "true"},
                        {"description": "bad", "surface": "cli", "command": "false"},
                    ],
                ),
                _story(
                    "story-002",
                    acceptance_criteria=["string"],
                    acceptance_execution={"type": "pytest", "command": "true"},
                ),
            ]
        )

    def test_sprint_emits_red_event_listing_exact_failing_item(self):
        self._seed_mixed()
        result = self._run("--sprint")
        self.assertEqual(result.returncode, 0, result.stderr)
        events = self._verify_events()
        self.assertEqual(len(events), 1, events)
        meta = events[0]["metadata"]
        self.assertEqual(meta["verify_status"], "red")
        failing = meta["failing"]
        self.assertEqual(len(failing), 1, failing)
        item = failing[0]
        self.assertEqual(item["story"], "story-001")
        self.assertEqual(item["command"], "false")
        self.assertNotEqual(item["returncode"], 0)
        self.assertEqual(item["surface"], "cli")

    def test_query_status_reports_red_after_red_sprint(self):
        self._seed_mixed()
        self._run("--sprint")
        result = self._run("--query-verify-status")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("red", result.stdout)
        self.assertIn("false", result.stdout)


class TestDeferredStorySkipped(_SprintCLITestCase):
    """A deferred story's deliverable is intentionally absent, so running its
    acceptance produces a false RED that blocks the close of legitimately
    shipped work (hit live closing sprint-121). --sprint must skip deferred
    stories entirely — not gather, not run, not report them."""

    def test_deferred_story_not_gathered_and_no_red(self):
        self._seed(
            [
                _story(
                    "story-deferred",
                    status="deferred",
                    acceptance_criteria=["prose"],
                    acceptance_execution={"type": "pytest", "command": "false"},
                ),
                _story(
                    "story-shipped",
                    acceptance_criteria=["prose"],
                    acceptance_execution={"type": "pytest", "command": "true"},
                ),
            ]
        )
        result = self._run("--sprint")
        self.assertEqual(result.returncode, 0, result.stderr)
        # The deferred story's failing command must never run — sprint stays green.
        self.assertNotIn("story-deferred", result.stdout)
        events = self._verify_events()
        self.assertEqual(len(events), 1, events)
        meta = events[0]["metadata"]
        self.assertEqual(
            meta["verify_status"],
            "green",
            f"deferred story leaked in; failing={meta.get('failing')!r}",
        )

    def test_deferred_per_ac_verify_also_skipped(self):
        # Object-shaped per-AC verify items on a deferred story must be skipped too.
        self._seed(
            [
                _story(
                    "story-deferred",
                    status="deferred",
                    acceptance_criteria=[
                        {"description": "bad", "surface": "cli", "command": "false"},
                    ],
                ),
            ]
        )
        result = self._run("--sprint")
        self.assertEqual(result.returncode, 0, result.stderr)
        # No verify-bearing item remains → no event emitted at all.
        self.assertEqual(self._verify_events(), [])


class TestCommandTimeout(_SprintCLITestCase):
    def test_hung_command_marked_failed_with_timeout_output(self):
        # The --sprint path runs unattended at sprint-close; a hung acceptance
        # command must convert to an attributable red, never block forever.
        self._seed(
            [
                _story(
                    "story-001",
                    acceptance_criteria=[
                        {"description": "h", "surface": "cli", "command": "sleep 5"},
                    ],
                ),
            ]
        )
        result = run_cli(
            _VERIFY_ACCEPTANCE,
            ["--sprint"],
            self.smm_dir,
            extra_env={"VERIFY_CMD_TIMEOUT_S": "1"},
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        events = self._verify_events()
        self.assertEqual(len(events), 1, events)
        failing = events[0]["metadata"]["failing"]
        self.assertEqual(len(failing), 1, failing)
        self.assertNotEqual(failing[0]["returncode"], 0)
        self.assertIn("timed out", failing[0]["output"])

    def _run_hung(self, command: str) -> list[dict]:
        self._seed(
            [
                _story(
                    "story-001",
                    acceptance_criteria=[
                        {"description": "h", "surface": "cli", "command": command},
                    ],
                ),
            ]
        )
        result = run_cli(
            _VERIFY_ACCEPTANCE,
            ["--sprint"],
            self.smm_dir,
            extra_env={"VERIFY_CMD_TIMEOUT_S": "1"},
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return self._verify_events()[0]["metadata"]["failing"]

    def test_hung_command_carries_what_it_said_before_the_kill(self):
        # The drained output is usually the only clue to WHY it hung.
        failing = self._run_hung("echo WHYIHUNG >&2; sleep 5")
        self.assertIn("WHYIHUNG", failing[0]["output"])

    def test_chatty_hang_still_names_the_timeout(self):
        # The stored detail is a TAIL slice, so a hung command that talked
        # more than the tail budget must not evict its own "timed out"
        # marker — without it the row reads as an ordinary non-zero exit and
        # the operator has no idea the command never returned.
        chatty = "x" * (verify_acceptance._OUTPUT_TAIL_CHARS * 4)
        failing = self._run_hung(f"printf %s {chatty} >&2; sleep 5")
        output = failing[0]["output"]
        self.assertIn("timed out", output, output[:120])
        self.assertIn("x", output)
        self.assertLessEqual(
            len(output),
            verify_acceptance._OUTPUT_TAIL_CHARS + 60,
            "the tail budget must still bound the stored detail",
        )


class TestEmitConfirmation(_SprintCLITestCase):
    def test_dropped_event_surfaces_error_not_silent_green(self):
        # append_safe swallows validation errors + lock timeouts. If the verify
        # event silently fails to land, --query-verify-status would read it as
        # green and pass a red sprint. _run_sprint must fail loud instead.
        self._seed(
            [
                _story(
                    "story-001",
                    acceptance_criteria=[
                        {"description": "bad", "surface": "cli", "command": "false"},
                    ],
                ),
            ]
        )
        # Replace append_safe with a no-op so the verify event never lands.
        with patch.object(verify_acceptance._common, "append_safe"):
            rc = verify_acceptance._run_sprint(self.smm_dir)
        self.assertEqual(rc, verify_acceptance._EXIT_ERROR)


class TestNeverVerifiedIsNotGreen(_SprintCLITestCase):
    """A missing event has TWO meanings and only one of them is green.

    The rerun reaches production through a harness-bounded tool call, and a run
    killed by that OUTER bound dies before it can append — the inner per-command
    and batch bounds are larger than the caller's, so they never get to convert
    it into a red. Reading the resulting silence as `none` made absence of
    evidence pass as evidence of absence at the one gate that holds the merge.
    """

    def _seed_verify_bearing(self) -> None:
        self._seed(
            [
                _story(
                    "story-001",
                    acceptance_criteria=[
                        {"description": "ok", "surface": "cli", "command": "true"},
                    ],
                ),
            ]
        )

    def test_a_verify_bearing_sprint_with_no_run_reports_unverified(self):
        """Mutation: read `_last_verify` directly -> `none`, exit 0, green."""
        self._seed_verify_bearing()
        result = self._run("--query-verify-status")
        self.assertEqual(result.returncode, verify_acceptance._EXIT_RED)
        self.assertIn(verify_acceptance.VERIFY_REPORT_UNVERIFIED, result.stdout)

    def test_a_run_that_lands_clears_it(self):
        """The refutation partner: `unverified` must not be the answer to
        everything, or the gate is a permanent block rather than a gate."""
        self._seed_verify_bearing()
        self._run("--sprint")
        result = self._run("--query-verify-status")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("green", result.stdout)

    def test_a_sprint_with_nothing_to_verify_is_still_none(self):
        """The other half of the discriminator, already pinned by
        `TestAllStringSkip` and restated here as this class's own control: a
        sprint whose acceptance is all prose has nothing to run, so silence is
        honest and the gate must not invent work for it."""
        self._seed([_story("story-001", acceptance_criteria=["manual"])])
        result = self._run("--query-verify-status")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("none", result.stdout)


class TestQueryStatusGreen(_SprintCLITestCase):
    def test_query_status_green_when_all_pass(self):
        self._seed(
            [
                _story(
                    "story-001",
                    acceptance_criteria=[
                        {"description": "ok", "surface": "cli", "command": "true"},
                    ],
                ),
            ]
        )
        self._run("--sprint")
        result = self._run("--query-verify-status")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("green", result.stdout)


if __name__ == "__main__":
    unittest.main()
