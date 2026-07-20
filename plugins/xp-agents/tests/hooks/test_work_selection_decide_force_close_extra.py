#!/usr/bin/env python3
"""Tests for work_selection_decide.py — extended FORCE-CLOSE gate coverage:
mixed legacy/modern history reconciliation, survival across compaction (via
the durable adoption ledger), lane scoping, and the CLI surface for the
force-* flags.

Split from test_work_selection_decide.py to stay under the file-size budget.
Core gate behavior lives in test_work_selection_decide_force_close_gate.py.
Shared base TestCase (`_ForceCloseTestCase`) lives in
_work_selection_decide_helpers.py.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(
    0,
    str(
        Path(__file__).parent.parent.parent / "skills" / "xp-work-selection" / "scripts"
    ),
)

import adoption_store
from _work_selection_decide_helpers import _ForceCloseTestCase
from conftest import make_event
from event_schema import EVENT_TYPE_DEBT, EVENT_TYPE_DECISION
from work_selection_filters import _FORCE_CLOSE_THRESHOLD


class TestForceCloseGateMixedHistory(_ForceCloseTestCase):
    """A real SMM log at migration time holds BOTH shapes: deferrals written
    before the routing change (metadata.resolves) and after (references).
    Neither leg alone reaches the threshold — only counting both does.
    """

    def _seed_mixed(self, try_ref_id: str, legacy: int, modern: int) -> None:
        events = [self._defer_event(i, try_ref_id, "resolves") for i in range(legacy)]
        events += [
            self._defer_event(legacy + i, try_ref_id, "references")
            for i in range(modern)
        ]
        self._write_events(events)

    def test_mixed_legacy_and_new_history_reaches_threshold(self):
        self._seed_mixed("aaaaaaaaaaaa", legacy=2, modern=1)
        with self.assertRaises(ValueError) as ctx:
            self.mod.run(
                action="defer",
                smm_dir=self.smm_dir,
                content="Defer once more [refs: aaaaaaaaaaaa]",
            )
        self.assertIn("FORCE-CLOSE", str(ctx.exception))
        self.assertEqual(len(self._read_events()), 3)

    def test_mixed_history_below_threshold_still_allowed(self):
        self._seed_mixed("aaaaaaaaaaaa", legacy=1, modern=1)
        self.mod.run(
            action="defer",
            smm_dir=self.smm_dir,
            content="Defer again [refs: aaaaaaaaaaaa]",
        )
        self.assertEqual(self._last_event()["metadata"]["disposition"], "deferred")

    def test_one_event_carrying_both_shapes_counts_once(self):
        """A deferral naming the Try in both fields is still ONE deferral."""
        events = []
        for i in range(3):
            event = self._defer_event(i, "aaaaaaaaaaaa", "resolves")
            event["references"] = ["aaaaaaaaaaaa"]
            events.append(event)
        self._write_events(events)
        # 3 events, double-linked — the gate must see 3, not 6, and refuse.
        with self.assertRaises(ValueError) as ctx:
            self.mod.run(
                action="defer",
                smm_dir=self.smm_dir,
                content="Defer once more [refs: aaaaaaaaaaaa]",
            )
        self.assertIn("have 3 prior deferrals", str(ctx.exception))


class TestForceCloseGateSurvivesCompaction(_ForceCloseTestCase):
    """The gate must not forget what compaction erased.

    A deferral is a `status` event, and compaction archives those — so the Try
    whose deferrals are OLD ENOUGH to have aged out of `events.jsonl` is exactly
    the long-carried Try the gate exists to catch. Counting the live log alone
    reads ZERO for it and waves the 4th plain defer straight through: the gate
    silently disarms on its own target population, for a reason (a compaction)
    that has nothing to do with the Try.

    The durable ledger is the memory that outlives the log — `adoption_store`
    exists for this, and carries `defer_count` for this. `intent` already reads
    it. The gate did not, so the milestone that made the memory durable left the
    mechanism that most needs it still amnesiac.
    """

    TRY_ID = "aaaaaaaaaaaa"

    def _remember(self, count: int, target_id: str | None = None) -> None:
        """Seed the ledger as `compact._fold_adoption_ledger` would have, then
        leave the live log EMPTY — the post-compaction state."""
        adoption_store.save_adoption(
            self.smm_dir,
            {
                "version": adoption_store.SCHEMA_VERSION,
                "entries": [
                    {
                        "target_id": target_id or self.TRY_ID,
                        "lane": adoption_store.LANE_RETRO,
                        "intent": "deferred",
                        "intent_by": "b" * 12,
                        "intent_ts": "2026-01-01T00:00:00+00:00",
                        "defer_count": count,
                    }
                ],
            },
        )

    def test_deferrals_archived_out_of_the_log_still_fire_the_gate(self):
        self._remember(_FORCE_CLOSE_THRESHOLD)
        with self.assertRaises(ValueError) as ctx:
            self.mod.run(
                action="defer",
                smm_dir=self.smm_dir,
                content=f"Defer once more [refs: {self.TRY_ID}]",
            )
        self.assertIn("FORCE-CLOSE", str(ctx.exception))

    def test_below_the_threshold_the_remembered_count_still_allows_a_defer(self):
        """The control: the ledger must not make the gate trigger-happy either."""
        self._remember(_FORCE_CLOSE_THRESHOLD - 1)
        self.mod.run(
            action="defer",
            smm_dir=self.smm_dir,
            content=f"Carry it once more [refs: {self.TRY_ID}]",
        )
        self.assertEqual(self._last_event()["metadata"]["disposition"], "deferred")

    def test_log_and_ledger_are_maxed_not_summed(self):
        """The two sources count OVERLAPPING windows — the ledger's snapshot
        includes deferrals the log can still see. Summing double-counts them and
        force-closes a Try deferred only twice; the max never double-counts and
        never regresses. Same reconciliation `intent._build_intent_map` makes.
        """
        self._remember(2)
        self._seed_prior_defers(self.TRY_ID, 2, "references")
        self.mod.run(
            action="defer",
            smm_dir=self.smm_dir,
            content=f"Third carry [refs: {self.TRY_ID}]",
        )
        self.assertEqual(self._last_event()["metadata"]["disposition"], "deferred")

    def test_another_trys_remembered_count_does_not_leak(self):
        """The ledger is keyed by target id; a different Try's memory is not
        this Try's."""
        self._remember(_FORCE_CLOSE_THRESHOLD + 2, target_id="bbbbbbbbbbbb")
        self.mod.run(
            action="defer",
            smm_dir=self.smm_dir,
            content=f"A different Try [refs: {self.TRY_ID}]",
        )
        self.assertEqual(self._last_event()["metadata"]["disposition"], "deferred")


class TestForceCloseLaneScoping(_ForceCloseTestCase):
    """The gate counts deferrals of the TRY, not deferrals of things the Try
    merely mentions — and it must keep counting the untagged deferrals written
    before the lane tag existed.

    Three legs, load-bearing in opposite directions. Drop the lane check and a
    *debt's* deferral inflates a Try's count toward a FORCE-CLOSE it never
    earned. Drop the try-target scoping and another *Try's* deferral does the
    same thing through a debt they both cite — same bag, one lane over. Drop the
    untagged leg and pre-tag deferrals stop counting, zeroing those Tries' counts
    and disarming the gate on exactly the long-carried Tries it exists to catch.
    """

    TRY_ID = "2b15e8490179"

    def test_triage_defer_of_a_cited_debt_does_not_inflate_the_count(self):
        """Story test 3. The Try's ref bag holds the debt ids its prose cites,
        and the triage lane now links its deferrals in that same `references`
        field. A debt's deferral is not the Try's.

        Live pair this reproduces: Try 2b15e8490179's bag holds debt
        9ec0731f5597, which already carries triage-defer 181cb8fa2316.
        """
        debt = make_event(EVENT_TYPE_DEBT, content="The debt the Try cites")
        self._write_events([debt])
        for _ in range(_FORCE_CLOSE_THRESHOLD + 1):
            self.mod.run(
                action="triage-defer",
                smm_dir=self.smm_dir,
                content="",
                event_id=debt["id"],
            )
        # The Try itself has NEVER been deferred; only the debt it cites has.
        self.mod.run(
            action="defer",
            smm_dir=self.smm_dir,
            content=f"Carry the Try [refs: {self.TRY_ID}, {debt['id']}]",
        )
        event = self._last_event()
        self.assertEqual(event["metadata"]["disposition"], "deferred")
        self.assertIn(self.TRY_ID, event["references"])

    def test_defer_of_another_try_citing_the_same_debt_does_not_inflate(self):
        """The SAME bag leak, one lane over. The lane check stops a *debt's*
        deferral from counting; it does nothing about another *Try's* deferral
        reaching this Try through a shared cited id, because both events are
        retro-lane and both bags hold the debt.

        This Try has NEVER been deferred. Only the other one has.
        """
        debt = make_event(EVENT_TYPE_DEBT, content="The debt BOTH Tries cite")
        self._write_events([debt])
        other_try = "3c3c3c3c3c3c"
        for _ in range(_FORCE_CLOSE_THRESHOLD):
            self.mod.run(
                action="defer",
                smm_dir=self.smm_dir,
                content=f"Carry the OTHER Try [refs: {other_try}, {debt['id']}]",
            )
        self.mod.run(
            action="defer",
            smm_dir=self.smm_dir,
            content=f"Carry THIS Try [refs: {self.TRY_ID}, {debt['id']}]",
        )
        event = self._last_event()
        self.assertEqual(event["metadata"]["disposition"], "deferred")
        self.assertIn(self.TRY_ID, event["references"])

    def test_legacy_untagged_defer_still_counts(self):
        """Story test 3b. Every retro deferral written before the lane tag
        existed carries no `metadata.action`; a bare
        `action == retro_try_disposition` gate would exclude all of them and
        disarm this gate on the Tries carried longest. The plugin ships to
        installs whose logs hold exactly this shape, which is why the fixture
        builds it explicitly rather than reading one off this repo's log — this
        repo has none (its untagged deferrals are all unlinked triage-defers).
        """
        self._seed_prior_defers(self.TRY_ID, _FORCE_CLOSE_THRESHOLD, "references")
        seeded = self._read_events()
        self.assertTrue(
            all("action" not in e["metadata"] for e in seeded),
            "fixture must be UNTAGGED or this test proves nothing",
        )
        with self.assertRaises(ValueError) as ctx:
            self.mod.run(
                action="defer",
                smm_dir=self.smm_dir,
                content=f"Carry it again [refs: {self.TRY_ID}]",
            )
        self.assertIn("FORCE-CLOSE", str(ctx.exception))

    def test_tagged_retro_defers_count(self):
        """The forward path: deferrals the writer tags today reach the gate."""
        for _ in range(_FORCE_CLOSE_THRESHOLD):
            self.mod.run(
                action="defer",
                smm_dir=self.smm_dir,
                content=f"Carry it [refs: {self.TRY_ID}]",
            )
        with self.assertRaises(ValueError) as ctx:
            self.mod.run(
                action="defer",
                smm_dir=self.smm_dir,
                content=f"Carry it again [refs: {self.TRY_ID}]",
            )
        self.assertIn("FORCE-CLOSE", str(ctx.exception))


class TestForceCloseCli(_ForceCloseTestCase):
    """End-to-end CLI argparse coverage for the new flags."""

    def test_cli_plain_defer_at_threshold_exits_nonzero(self):
        self._seed_prior_defers("aaaaaaaaaaaa", 3)
        code = self._run_main(
            [
                "defer",
                "--smm-dir",
                str(self.smm_dir),
                "--content",
                "Plain defer [refs: aaaaaaaaaaaa]",
            ]
        )
        self.assertNotEqual(code, 0)

    def test_cli_force_adopt_at_threshold_persists_decision(self):
        self._seed_prior_defers("aaaaaaaaaaaa", 3)
        code = self._run_main(
            [
                "defer",
                "--smm-dir",
                str(self.smm_dir),
                "--content",
                "Adopt now [refs: aaaaaaaaaaaa]",
                "--force-adopt",
                "retro-try-cli-forced",
            ]
        )
        self.assertEqual(code, 0)
        self.assertEqual(self._last_event()["type"], EVENT_TYPE_DECISION)

    def test_cli_force_drop_at_threshold_persists_drop(self):
        self._seed_prior_defers("aaaaaaaaaaaa", 3)
        code = self._run_main(
            [
                "defer",
                "--smm-dir",
                str(self.smm_dir),
                "--content",
                "Drop now [refs: aaaaaaaaaaaa]",
                "--force-drop",
            ]
        )
        self.assertEqual(code, 0)
        self.assertEqual(self._last_event()["metadata"]["disposition"], "dropped")

    def test_cli_force_defer_with_date_persists_defer_until(self):
        self._seed_prior_defers("aaaaaaaaaaaa", 3)
        code = self._run_main(
            [
                "defer",
                "--smm-dir",
                str(self.smm_dir),
                "--content",
                "Hold until [refs: aaaaaaaaaaaa]",
                "--force-defer-with-date",
                "2026-09-01",
            ]
        )
        self.assertEqual(code, 0)
        event = self._last_event()
        self.assertEqual(event["metadata"]["defer_until"], "2026-09-01")

    def test_cli_force_flags_mutually_exclusive(self):
        self._seed_prior_defers("aaaaaaaaaaaa", 3)
        code = self._run_main(
            [
                "defer",
                "--smm-dir",
                str(self.smm_dir),
                "--content",
                "Conflict [refs: aaaaaaaaaaaa]",
                "--force-drop",
                "--force-adopt",
                "retro-try-x",
            ]
        )
        self.assertNotEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
