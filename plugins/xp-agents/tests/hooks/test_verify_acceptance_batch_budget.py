#!/usr/bin/env python3
"""The batch-total budget bounding the UNATTENDED --sprint run.

The per-command bound is 2h so a genuinely slow acceptance suite passes
comfortably. But it is PER COMMAND, so a sprint with eight verify-bearing items
can run ~16h — unattended, inside sprint close. Bounding the batch instead of
tightening the item keeps both properties: a slow suite still gets its two
hours, and the whole run still cannot go overnight.

Own file, not folded into the --sprint suite: that suite is at 394 lines and
these cases would push it through the size band (the trap the hardening suite
was split out to avoid). These also pin ONE property — how the batch as a whole
is bounded — across the resolver, the runner, the matrix and BOTH readers of the
verify event, so keeping them together is cohesion, not convenience.

NO TEST HERE SLEEPS. The smallest live budget an int env var can express is 1s,
so every over-budget case would otherwise have to burn real wall-clock in the
commit-time suite — against the recorded convention that commit-time tests
assert structural invariants rather than wall-clock, and flaky under `-n auto`.
The deadline cases script `_now` explicitly and run `_run_sprint` in-process.
"""

import argparse
import contextlib
import io
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

import close_verify_gate
import sprint_store
import verify_acceptance
from _bases import _HookTestCase
from conftest import make_sprint_dict, verify_events


def _clock(*ticks: float):
    """A scripted `_now`: yields each tick in turn, then repeats the last.

    Repeating rather than exhausting is deliberate — the number of clock reads
    is an implementation detail (one per surviving loop iteration), and a test
    that broke when that count changed would be pinning the implementation
    instead of the behaviour.
    """
    seq = list(ticks)

    def now() -> float:
        return seq.pop(0) if len(seq) > 1 else seq[0]

    return now


class TestBatchBudgetResolver(unittest.TestCase):
    """`_batch_budget` deliberately does NOT reuse `_subprocess_env._env_int`,
    and the divergence is the whole opt-out.

    For a PER-COMMAND timeout a non-positive value is nonsense — `timeout=0`
    makes the runner raise before the command has run at all — so `_env_int`
    correctly folds zero and negatives into the default. For a batch TOTAL,
    non-positive is the only way to say "do not bound my batch": a project whose
    honest sprint verify runs eight hours needs that door, and without it the
    only escape from a false stop is `--force-close`, which bypasses the entire
    acceptance gate rather than this one bound.

    Unset is NOT that door. An opt-in budget would leave the unbounded batch in
    place for everyone who never set the variable — shipped and inert.
    """

    def _budget(self, raw: str) -> int | None:
        with patch.dict(os.environ, {"VERIFY_BATCH_TIMEOUT_S": raw}):
            return verify_acceptance._batch_budget()

    def _unset(self) -> int | None:
        with patch.dict(os.environ):
            os.environ.pop("VERIFY_BATCH_TIMEOUT_S", None)
            return verify_acceptance._batch_budget()

    def test_positive_override_is_honoured(self):
        self.assertEqual(self._budget("60"), 60)

    def test_default_is_four_hours(self):
        # 2x the per-command bound, so no single pathological item can exhaust
        # the batch on its own. Mutation: raise it to match _cmd_timeout and one
        # long item false-stops the whole batch.
        self.assertEqual(self._unset(), 14400)
        self.assertEqual(
            verify_acceptance._DEFAULT_BATCH_TIMEOUT_S,
            2 * verify_acceptance._DEFAULT_CMD_TIMEOUT_S,
        )

    def test_unset_gives_the_default_and_never_disables(self):
        """The ships-inert mutation. If unset returned None the 16h batch
        survives untouched for every project that never sets the variable —
        which is every project, on upgrade."""
        self.assertIsNotNone(self._unset())

    def test_zero_disables_the_budget(self):
        """The documented opt-out, and the divergence from `_env_int`."""
        self.assertIsNone(self._budget("0"))

    def test_negative_disables_the_budget(self):
        self.assertIsNone(self._budget("-1"))

    def test_unparseable_falls_back_to_the_default(self):
        """Unparseable is not consent to run unbounded — it is a typo."""
        self.assertEqual(
            self._budget("not-a-number"), verify_acceptance._DEFAULT_BATCH_TIMEOUT_S
        )

    def test_the_per_command_resolver_is_left_alone(self):
        """AC2's counterpart at the resolver level: the attended path's bound
        keeps `_env_int` semantics, where zero must NOT disable."""
        with patch.dict(os.environ, {"VERIFY_CMD_TIMEOUT_S": "0"}):
            self.assertEqual(
                verify_acceptance._cmd_timeout(),
                verify_acceptance._DEFAULT_CMD_TIMEOUT_S,
            )


class _BatchRunTestCase(_HookTestCase):
    """Drives `_run_sprint` IN-PROCESS with a scripted clock.

    The suite's other batch tests shell out via `run_cli`, which cannot reach a
    patched clock across the process boundary — and the only alternative there
    is a real ≥1s sleep per case. In-process with `patch.object` is the same
    shape `test_verify_acceptance_sprint.py` already uses to patch
    `_common.append_safe`.
    """

    def _seed(self, commands: list[str | None]) -> None:
        """One story; each entry is a commanded AC, or None for a manual block."""
        acs: list[dict] = [
            {"description": f"c{i}", "surface": "cli", "command": cmd}
            for i, cmd in enumerate(commands)
            if cmd is not None
        ]
        story = {
            "id": "story-001",
            "title": "Story story-001",
            "status": "done",
            "dependencies": [],
            "milestone_ref": "",
            "design_sources": "",
            "context": "ctx",
            "file_domain": ["src/a.py — x"],
            "interface_contracts": [],
            "acceptance_criteria": acs,
        }
        if any(c is None for c in commands):
            # A command-less acceptance_execution is the N/A sentinel — never
            # shelled, so it must never consume budget nor report as skipped.
            story["acceptance_execution"] = {"type": "manual", "steps": ["look"]}
        sprint = make_sprint_dict(sprint_id="sprint-093", stories=[story])
        sprint_store.save_sprint(self.smm_dir, sprint, enforce_budget=False)

    def _run(self, now, **env: str) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with patch.dict(os.environ, env):
            if "VERIFY_BATCH_TIMEOUT_S" not in env:
                os.environ.pop("VERIFY_BATCH_TIMEOUT_S", None)
            with (
                patch.object(verify_acceptance, "_now", now),
                contextlib.redirect_stdout(out),
                contextlib.redirect_stderr(err),
            ):
                rc = verify_acceptance._run_sprint(self.smm_dir)
        return rc, out.getvalue(), err.getvalue()

    def _event(self) -> dict:
        events = verify_events(self._read_events())
        self.assertEqual(len(events), 1, events)
        return events[0]


class TestBatchStopsBeforeTheNextItemStarts(_BatchRunTestCase):
    """AC1. The budget decides which items START; it never kills a running one.

    Killing mid-flight would attribute the batch's exhaustion to whichever item
    happened to be running — the misattribution the separate-bounds decision
    exists to avoid, and the reason the per-command bound stays the only thing
    that ever kills a command.
    """

    def test_later_items_are_skipped_and_named(self):
        self._seed(["true", "true", "true"])
        # Deadline is 0 + 14400. The clock is inside budget for the first
        # item and past it for the rest.
        rc, out, _ = self._run(_clock(0, 0, 20000))
        self.assertEqual(rc, verify_acceptance._EXIT_OK)
        self.assertEqual(out.count("[PASS]"), 1, out)
        self.assertEqual(out.count("[SKIP]"), 2, out)

    def test_an_already_blown_budget_never_STARTS_the_first_item(self):
        """The discriminating case for before-vs-after.

        Checking the deadline AFTER running an item gives the same skip counts
        on a batch that goes over midway — so that mutation survives every
        count-based assertion. It only shows up here: with the budget already
        blown at the first check, a before-check runs NOTHING. The marker file
        proves the command never executed, rather than inferring it from a row.
        """
        marker = Path(self.smm_dir) / "ran.marker"
        self._seed([f"touch {marker}"])
        self._run(_clock(0, 20000))
        self.assertFalse(marker.exists(), "the command must never have started")

    def test_skipped_items_are_not_reported_as_failures(self):
        """Skipped is a THIRD outcome. Folding it into `failing` would say the
        item ran and lost, which is the misattribution in a different place."""
        self._seed(["true", "true", "true"])
        self._run(_clock(0, 0, 20000))
        meta = self._event()["metadata"]
        self.assertEqual(meta["failing"], [], meta)
        self.assertEqual(meta["skipped_count"], 2, meta)
        self.assertTrue(all(r.get("skipped") for r in meta["skipped"]), meta)

    def test_a_skipped_batch_gates_the_close_as_red(self):
        """Five of eight green and three unknown is not a verified sprint. Red
        is also the only encoding available — the status set is enforced at
        append time, so an `incomplete` status would be rejected on write."""
        self._seed(["true", "true", "true"])
        self._run(_clock(0, 0, 20000))
        self.assertEqual(
            self._event()["metadata"]["verify_status"],
            verify_acceptance.VERIFY_STATUS_RED,
        )

    def test_stderr_names_the_lever(self):
        """The re-run is deterministic — it stops at the same place — so a gate
        with no visible escape reads as a bug rather than a budget."""
        self._seed(["true", "true", "true"])
        _, _, err = self._run(_clock(0, 0, 20000))
        self.assertIn("VERIFY_BATCH_TIMEOUT_S", err)
        self.assertIn("14400", err)


class TestTheBudgetIsABackstopNotAGate(_BatchRunTestCase):
    def test_under_budget_runs_everything_and_records_nothing(self):
        """AC3. A batch nowhere near the budget must be byte-for-byte what it
        was before this story — no skipped key, green, every item run."""
        self._seed(["true", "true", "true"])
        rc, out, err = self._run(_clock(0))
        self.assertEqual(rc, verify_acceptance._EXIT_OK)
        self.assertEqual(out.count("[PASS]"), 3, out)
        meta = self._event()["metadata"]
        self.assertEqual(meta["verify_status"], verify_acceptance.VERIFY_STATUS_GREEN)
        self.assertNotIn("skipped", meta)
        self.assertNotIn("skipped_count", meta)
        self.assertEqual(err, "")

    def test_disabling_the_budget_never_skips_however_long_it_runs(self):
        """AC4 end to end: the opt-out reaches the runner, not just the
        resolver. The clock is absurdly past any budget."""
        self._seed(["true", "true", "true"])
        _, out, _ = self._run(_clock(0, 10**9), VERIFY_BATCH_TIMEOUT_S="0")
        self.assertEqual(out.count("[PASS]"), 3, out)
        self.assertNotIn("[SKIP]", out)

    def test_a_manual_row_neither_consumes_budget_nor_reports_skipped(self):
        """The N/A branch runs BEFORE the deadline check. A manual block is
        never shelled, so it costs no time and cannot be 'not run' — marking it
        skipped would invent a failure out of a row that was never going to
        execute."""
        self._seed([None, "true"])
        _, out, _ = self._run(_clock(0, 20000))
        self.assertIn("[N/A]", out)
        self.assertEqual(out.count("[SKIP]"), 1, out)


class TestBothReadersOfTheVerifyEvent(_BatchRunTestCase):
    """The verify event has TWO consumers, and a fix that reaches one is half a
    fix.

    `_query_verify_status` prints for the operator; `close_verify_gate` refuses
    the merge in-process. Teaching only the CLI reader about skipped items would
    leave the gate refusing with an empty list — correct to refuse, useless
    about why, at the one place a human is being told a merge cannot proceed.
    """

    def _skipped_batch(self) -> None:
        self._seed(["true", "true", "true"])
        self._run(_clock(0, 0, 20000))

    def test_last_verify_carries_the_skipped_items(self):
        """The shared accessor both readers go through. Mutation: drop the
        third element and the gate below has nothing to name."""
        self._skipped_batch()
        status, failing, skipped = verify_acceptance._last_verify(
            self.smm_dir, "sprint-093"
        )
        self.assertEqual(status, verify_acceptance.VERIFY_STATUS_RED)
        self.assertEqual(failing, [])
        self.assertEqual(len(skipped), 2, skipped)

    def test_query_status_prints_the_skipped_items_not_a_bare_red(self):
        self._skipped_batch()
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = verify_acceptance._query_verify_status(self.smm_dir)
        self.assertEqual(rc, verify_acceptance._EXIT_RED)
        self.assertIn("not run", out.getvalue())
        self.assertIn("story-001", out.getvalue())

    def test_query_status_prints_one_line_per_item_not_per_comma(self):
        """The two readers want different SHAPES of the same description — one
        line each, one sentence — so the shared helper returns the items and the
        line reader must never re-split the sentence. A declared command may
        itself contain the separator, and re-splitting would report an item that
        does not exist while truncating the one that does."""
        self._seed(['python3 -c "import sys, os; sys.exit(1)"'])
        self._run(_clock(0))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            verify_acceptance._query_verify_status(self.smm_dir)
        lines = [ln for ln in out.getvalue().splitlines() if ln.startswith("  ")]
        self.assertEqual(len(lines), 1, lines)
        self.assertIn("sys.exit(1)", lines[0])

    def test_the_merge_gate_refusal_names_the_skipped_items(self):
        """The leg the first plan would have shipped broken: the refusal text
        was built from `failing` alone, so a red-because-skipped sprint refused
        with nothing after the colon."""
        self._skipped_batch()
        args = argparse.Namespace(
            verify_gate="acceptance",
            smm_dir=str(self.smm_dir),
            force_verify=False,
            cwd=".",
            target="main",
            source="feat",
        )
        reason = self._assert_not_none(close_verify_gate.verify_gate_block(args))
        self.assertIn("story-001", reason)
        self.assertIn("not run", reason)
        # Distinguishable per criterion, not three identical lines. One story
        # contributing several verify commands is the ordinary case, and a
        # refusal naming it three times leaves the reader guessing which one.
        self.assertIn("ac1", reason)
        self.assertIn("ac2", reason)

    def test_the_merge_gate_still_names_ordinary_failures(self):
        """The discriminating partner: adding skipped must not displace the
        failing items the refusal already reported."""
        self._seed(["false"])
        self._run(_clock(0))
        args = argparse.Namespace(
            verify_gate="acceptance",
            smm_dir=str(self.smm_dir),
            force_verify=False,
            cwd=".",
            target="main",
            source="feat",
        )
        reason = self._assert_not_none(close_verify_gate.verify_gate_block(args))
        self.assertIn("false", reason)
        self.assertNotIn("not run", reason)


if __name__ == "__main__":
    unittest.main()
