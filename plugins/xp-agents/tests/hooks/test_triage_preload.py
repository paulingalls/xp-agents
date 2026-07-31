#!/usr/bin/env python3
"""Tests for triage_preload: scan events for unresolved items."""

import sys
import unittest
from pathlib import Path
from typing import ClassVar

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))
sys.path.insert(
    0,
    str(
        Path(__file__).parent.parent.parent / "skills" / "xp-work-selection" / "scripts"
    ),
)

import triage_preload
from conftest import _SMMTestCase, adopt_try_event, make_event, triage_event
from event_schema import (
    EVENT_TYPE_COMMIT,
    EVENT_TYPE_CONCERN,
    EVENT_TYPE_DEBT,
    EVENT_TYPE_QUESTION,
    EVENT_TYPE_STATUS,
)


class TestFormatTriageSection(unittest.TestCase):
    """format_triage_section produces markdown triage output."""

    def test_formats_with_aging(self):
        item = make_event(
            EVENT_TYPE_DEBT,
            content="Fix auth",
            ts="2026-01-01T00:00:00+00:00",
        )
        session_ends = [
            "2026-02-01T00:00:00+00:00",
            "2026-03-01T00:00:00+00:00",
        ]
        result = triage_preload.format_triage_section(
            "Open Debts", [item], session_ends
        )
        self.assertIn("### Open Debts:", result)
        self.assertIn(f"[id: {item['id']}]", result)
        self.assertIn("Fix auth", result)
        self.assertIn("2 sessions old", result)

    def test_singular_session(self):
        item = make_event(
            EVENT_TYPE_DEBT,
            content="Fix it",
            ts="2026-01-01T00:00:00+00:00",
        )
        session_ends = ["2026-02-01T00:00:00+00:00"]
        result = triage_preload.format_triage_section(
            "Open Debts", [item], session_ends
        )
        self.assertIn("1 session old", result)

    def test_empty_items_returns_empty(self):
        result = triage_preload.format_triage_section("Open Debts", [], [])
        self.assertEqual(result, "")

    def test_zero_age(self):
        item = make_event(
            EVENT_TYPE_DEBT,
            content="Fresh",
            ts="2026-04-01T00:00:00+00:00",
        )
        result = triage_preload.format_triage_section("Open Debts", [item], [])
        self.assertIn("0 sessions old", result)


class TestRun(_SMMTestCase):
    """run() produces complete triage output from events."""

    def test_outputs_all_three_sections(self):
        d = make_event(EVENT_TYPE_DEBT, content="A debt item")
        c = make_event(EVENT_TYPE_CONCERN, content="A concern item")
        q = make_event(EVENT_TYPE_QUESTION, content="A question item")
        self._write_events([d, c, q])

        output = triage_preload.run(self.smm_dir)
        self.assertIn("### Open Debts:", output)
        self.assertIn("### Open Concerns:", output)
        self.assertIn("### Open Questions:", output)

    def test_excludes_resolved_events(self):
        d = make_event(EVENT_TYPE_DEBT, content="Resolved debt")
        resolver = make_event(
            EVENT_TYPE_STATUS,
            content="Fixed",
            metadata={"resolves": [d["id"]]},
        )
        self._write_events([d, resolver])

        output = triage_preload.run(self.smm_dir)
        self.assertNotIn("Resolved debt", output)

    def test_empty_events_returns_empty(self):
        output = triage_preload.run(self.smm_dir)
        self.assertEqual(output, "")

    def test_omits_empty_sections(self):
        d = make_event(EVENT_TYPE_DEBT, content="Only debt")
        self._write_events([d])

        output = triage_preload.run(self.smm_dir)
        self.assertIn("### Open Debts:", output)
        self.assertNotIn("### Open Concerns:", output)
        self.assertNotIn("### Open Questions:", output)

    def test_includes_event_ids(self):
        d = make_event(EVENT_TYPE_DEBT, content="Track me")
        self._write_events([d])

        output = triage_preload.run(self.smm_dir)
        self.assertIn(f"[id: {d['id']}]", output)


class TestTriageIntentAnnotation(_SMMTestCase):
    """AC3. A triage-adopted item is ANNOTATED as adopted and is STILL OFFERED.

    Annotating rather than filtering is the whole design. Filtering would make
    the item vanish from the kickoff list, which is indistinguishable from having
    been fixed — laundering the item exactly the way this story exists to stop.
    The user needs to see "you already said you'd do this", not silence.

    Fixtures go through the real triage writer, so they cannot encode a shape the
    writer does not produce.
    """

    def _triaged_debt(self, action: str, times: int = 1) -> dict:
        debt = make_event(EVENT_TYPE_DEBT, content="Ship the retry budget")
        self._write_events([debt])
        for _ in range(times):
            triage_event(self.smm_dir, action, debt["id"])
        return debt

    def test_adopted_debt_is_annotated_and_still_offered(self):
        debt = self._triaged_debt("triage-adopt")
        output = triage_preload.run(self.smm_dir)
        self.assertIn("Ship the retry budget", output)  # STILL OFFERED
        self.assertIn(f"[id: {debt['id']}]", output)
        self.assertIn("ADOPTED", output)
        # And at FULL length. The digest is earned by DEFERRAL only; shrinking
        # an item the lead just committed to would shorten exactly the item
        # they are most likely to act on next.
        self.assertNotIn("#### Deferred earlier", output)

    def test_deferred_debt_is_annotated_and_still_offered(self):
        debt = self._triaged_debt("triage-defer", times=2)
        output = triage_preload.run(self.smm_dir)
        self.assertIn("Ship the retry budget", output)  # STILL OFFERED
        self.assertIn(f"[id: {debt['id']}]", output)
        self.assertIn("DEFERRED", output)
        self.assertIn("2", output)  # the defer count

    def test_dropped_debt_is_gone_because_a_drop_really_does_close_it(self):
        """The contrast that makes the other two mean something: a DROP is
        terminal, so the item leaves the list. Adopt and defer do not."""
        debt = self._triaged_debt("triage-drop")
        output = triage_preload.run(self.smm_dir)
        self.assertNotIn(f"[id: {debt['id']}]", output)

    def test_untriaged_debt_carries_no_annotation(self):
        debt = make_event(EVENT_TYPE_DEBT, content="Never triaged")
        self._write_events([debt])
        output = triage_preload.run(self.smm_dir)
        self.assertIn("Never triaged", output)
        self.assertNotIn("ADOPTED", output)
        self.assertNotIn("DEFERRED", output)

    def test_a_cited_debt_is_not_annotated_as_adopted(self):
        """The bag leak, at the surface a human actually reads. A retro Try's
        adoption references the debt ids the Try's prose CITES. If the triage
        lane read that bag, this debt would be labelled ADOPTED because some Try
        mentioned it — a lie told directly to the user.
        """
        debt = make_event(EVENT_TYPE_DEBT, content="Merely cited by a Try")
        self._write_events([debt])
        adopt_try_event(self.smm_dir, "aa11bb22cc33", cites=[debt["id"]])
        output = triage_preload.run(self.smm_dir)
        self.assertIn("Merely cited by a Try", output)
        self.assertNotIn("ADOPTED", output)


class TestFormatWithOverlap(unittest.TestCase):
    """format_triage_section annotates concerns with commit overlap."""

    def test_annotated_concern_shows_maybe_addressed(self):
        concern = make_event(
            EVENT_TYPE_CONCERN,
            content="Auth bug",
            files=["scripts/auth.py"],
            ts="2026-01-01T00:00:00+00:00",
        )
        commit = make_event(
            EVENT_TYPE_COMMIT,
            content="Fix token leak in auth",
            files=["scripts/auth.py"],
            ts="2026-01-02T00:00:00+00:00",
        )
        overlap = {concern["id"]: [commit]}
        result = triage_preload.format_triage_section(
            "Open Concerns", [concern], [], commit_overlap=overlap
        )
        self.assertIn("MAYBE ADDRESSED", result)
        self.assertIn("Fix token leak", result)

    def test_no_annotation_without_overlap(self):
        concern = make_event(
            EVENT_TYPE_CONCERN,
            content="Auth bug",
            ts="2026-01-01T00:00:00+00:00",
        )
        result = triage_preload.format_triage_section("Open Concerns", [concern], [])
        self.assertNotIn("MAYBE ADDRESSED", result)


class TestInjectionStaysFlatAsCapRises(_SMMTestCase):
    """AC3/AC4. Storage != injection: raising the event write cap (story-013,
    400 -> 500) must NOT raise the kickoff triage block's size in lockstep.
    The full causal chain lives in the SMM; the block shows a bounded
    excerpt plus the event id, so the full text stays one lookup away.

    Built against a SYNTHETIC temp SMM (via _SMMTestCase / _write_events),
    never the live SMM dir, which moves session to session and would flake.

    The bound below is a REAL number, not a "doesn't grow proportionally"
    hand-wave, and it is MEASURED at both ends: 20 items at the 500-char cap
    cost 8,798 bytes with the 400-char excerpt in place, and 10,798 bytes
    emitted verbatim (pre-fix). MAX_BLOCK_BYTES sits between the two, so this
    assertion genuinely FAILS against the pre-fix triage_preload.py and only
    passes once injection excerpts content -- verified by reverting the
    excerpt and watching it go red, not assumed.

    The excerpt is 400 = the PREVIOUS content cap, so injection cost is pinned
    at its pre-story value: the storage raise costs zero extra injected bytes
    and the block loses nothing it used to show. See triage_preload.py.
    """

    _NUM_ITEMS = 20
    # Between the excerpted cost (8,798) and the verbatim cost (10,798).
    _MAX_BLOCK_BYTES = 9500

    def test_block_stays_within_bound_at_new_cap(self):
        events = [
            make_event(EVENT_TYPE_CONCERN, content="x" * 500)
            for _ in range(self._NUM_ITEMS)
        ]
        self._write_events(events)

        output = triage_preload.run(self.smm_dir)
        size = len(output.encode("utf-8"))
        self.assertLessEqual(
            size,
            self._MAX_BLOCK_BYTES,
            f"triage block is {size} bytes for {self._NUM_ITEMS} items at the "
            f"500-char cap -- injection must excerpt content, not emit it verbatim",
        )

    def test_full_content_not_emitted_verbatim(self):
        event = make_event(EVENT_TYPE_DEBT, content="z" * 500)
        self._write_events([event])

        output = triage_preload.run(self.smm_dir)
        self.assertNotIn("z" * 500, output)

    def test_event_id_still_present_for_full_text_lookup(self):
        event = make_event(EVENT_TYPE_CONCERN, content="y" * 500)
        self._write_events([event])

        output = triage_preload.run(self.smm_dir)
        self.assertIn(f"[id: {event['id']}]", output)

    def test_short_content_unaffected(self):
        event = make_event(EVENT_TYPE_DEBT, content="Short debt")
        self._write_events([event])

        output = triage_preload.run(self.smm_dir)
        self.assertIn("Short debt", output)


class TestRunWithOverlap(_SMMTestCase):
    """run() annotates concerns with commit overlap in output."""

    def test_concern_with_overlap_annotated(self):
        concern = make_event(
            EVENT_TYPE_CONCERN,
            content="Auth validation bug",
            files=["scripts/auth.py"],
            ts="2026-01-01T00:00:00+00:00",
        )
        commit = make_event(
            EVENT_TYPE_COMMIT,
            content="Fix auth validation",
            files=["scripts/auth.py"],
            ts="2026-01-02T00:00:00+00:00",
        )
        self._write_events([concern, commit])
        output = triage_preload.run(self.smm_dir)
        self.assertIn("MAYBE ADDRESSED", output)
        self.assertIn("Fix auth validation", output)

    def test_concern_cited_by_commit_id_annotated_without_file_overlap(self):
        """A commit that cites the concern's id in its body (no file
        overlap) still surfaces under MAYBE ADDRESSED — exercises the
        find_addressing_commits id tier wiring."""
        concern = make_event(
            EVENT_TYPE_CONCERN,
            content="Auth validation bug",
            files=["scripts/auth.py"],
            ts="2026-01-01T00:00:00+00:00",
        )
        commit = make_event(
            EVENT_TYPE_COMMIT,
            content=f"Fix landed in helper, closes {concern['id']}",
            files=["scripts/helper.py"],
            ts="2026-01-02T00:00:00+00:00",
        )
        self._write_events([concern, commit])
        output = triage_preload.run(self.smm_dir)
        self.assertIn("MAYBE ADDRESSED", output)
        self.assertIn(concern["id"], output)


class TestTriageTotalCeiling(unittest.TestCase):
    """The block's TOTAL size must not grow with the number of open items.

    Capping only the expensive 400-char tier makes the surface cheaper per
    item, not bounded: at 162 chars for every remaining line, 91 open items
    cost ~26k and 300 cost ~70k. A budget on that is calibrated to today's
    item count, so ordinary growth later reads as a regression. The tail past
    both tiers collapses to ONE line that states how many are not shown and
    names a runnable command that lists them — nothing vanishes silently,
    which is the laundering this module exists to prevent.
    """

    _ANCHORS: ClassVar[list[str]] = ["2026-02-01T00:00:00+00:00"]

    def _items(self, count: int) -> list[dict]:
        return [
            make_event(
                EVENT_TYPE_CONCERN,
                content="c" * 400,
                ts=f"2026-01-{(i % 28) + 1:02d}T00:00:00+00:00",
            )
            for i in range(count)
        ]

    def test_total_output_does_not_grow_with_item_count(self):
        """The hard bound. 4x the items must not mean 4x the output."""
        small = triage_preload.format_triage_section(
            "Open Concerns", self._items(100), self._ANCHORS
        )
        large = triage_preload.format_triage_section(
            "Open Concerns", self._items(400), self._ANCHORS
        )
        self.assertLessEqual(
            len(large) - len(small),
            200,
            f"section grew {len(large) - len(small)} chars for 300 more items "
            f"({len(small)} -> {len(large)}); the tail is not collapsing, so "
            f"this surface is cheaper per item but still unbounded",
        )

    def test_full_tier_is_capped(self):
        out = triage_preload.format_triage_section(
            "Open Concerns", self._items(100), self._ANCHORS
        )
        full_lines = [ln for ln in out.split("\n") if ln.startswith("- [id: ")]
        self.assertLessEqual(len(full_lines), triage_preload._SECTION_MAX_ITEMS)

    def test_omitted_items_are_counted_and_retrievable(self):
        """An item that vanished reads as fixed. A counted one reads as open."""
        out = triage_preload.format_triage_section(
            "Open Concerns", self._items(100), self._ANCHORS
        )
        shown = len([ln for ln in out.split("\n") if ln.startswith("- [id: ")])
        self.assertIn(f"{100 - shown} further", out)
        self.assertIn("--all", out)

    def test_the_retrieval_path_is_runnable(self):
        """A retrieval path the reader cannot execute is not a retrieval path.

        The command named in the collapse line must be the real script with a
        real flag, not prose — so the flag has to exist on the parser.
        """
        out = triage_preload.format_triage_section(
            "Open Concerns", self._items(100), self._ANCHORS
        )
        command = next(ln for ln in out.split("\n") if "--all" in ln)
        self.assertIn("triage_preload.py", command)
        parser = triage_preload._build_parser()
        self.assertTrue(parser.parse_args(["--smm-dir", "/tmp", "--all"]).all)

    def test_all_renders_every_item(self):
        """`--all` is what makes the collapse honest rather than lossy."""
        items = self._items(100)
        capped = triage_preload.format_triage_section(
            "Open Concerns", items, self._ANCHORS
        )
        full = triage_preload.format_triage_section(
            "Open Concerns", items, self._ANCHORS, uncapped=True
        )
        self.assertGreater(len(full), len(capped))
        for item in items:
            self.assertIn(item["id"], full)

    def test_a_high_severity_item_survives_the_cap(self):
        """Recency alone must not collapse a HIGH-severity item.

        `_digests` already refuses to SHRINK a high-severity item — "the item
        whose WHY the lead most needs in front of them". A cap that ranks by
        recency alone then REMOVES that same item entirely whenever it is old,
        which is strictly worse than the shrink the exemption forbids. On the
        live log this is not hypothetical: 7 of the 10 open high-severity
        concerns sit past index 25 in newest-first order.
        """
        items = self._items(100)
        items[-1]["severity"] = "high"
        oldest_high = items[-1]["id"]
        out = triage_preload.format_triage_section(
            "Open Concerns", items, self._ANCHORS
        )
        self.assertIn(oldest_high, out)


if __name__ == "__main__":
    unittest.main()
