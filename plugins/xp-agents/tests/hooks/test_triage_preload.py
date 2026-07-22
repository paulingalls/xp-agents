#!/usr/bin/env python3
"""Tests for triage_preload: scan events for unresolved items."""

import sys
import unittest
from pathlib import Path

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


class TestDeferredDigest(_SMMTestCase):
    """Story-002. An item the LEAD ALREADY DEFERRED earns a shorter form.

    Not a smaller version of the 400-char excerpt — an INDEX ENTRY. The 400-char
    bound exists so the lead can triage an item FROM THE BLOCK; a digested item
    has already been triaged, so its line only has to be recognisable, with the
    id that retrieves the whole thing. Cutting the FULL items to 60 would repeat
    story-013's mistake (mid-WHY cuts on items the lead has not yet judged).

    Fixtures defer through the REAL writer, so they cannot encode an intent
    shape the writer does not produce.
    """

    # Long enough that the 400-char excerpt and the 60-char digest line are
    # unmistakably different renderings of the same item.
    _LONG = (
        "Simplicity: the kickoff triage block is read at every session start, "
        "and its cost is dominated by item count rather than by per-item "
        "length, so the lever is which items earn a full line. " * 3
    )

    def _defer(self, event_id: str, times: int = 1) -> None:
        for _ in range(times):
            triage_event(self.smm_dir, "triage-defer", event_id)

    def test_deferred_item_moves_into_a_digest_sub_block(self):
        deferred = make_event(EVENT_TYPE_DEBT, content=self._LONG)
        self._write_events([deferred])
        self._defer(deferred["id"])

        output = triage_preload.run(self.smm_dir)
        self.assertIn("#### Deferred earlier — 1 item", output)
        self.assertIn(f"[id: {deferred['id']}]", output)
        self.assertIn("DEFERRED x1", output)
        # An index entry, not the 400-char excerpt.
        self.assertNotIn(self._LONG[:200], output)
        self.assertIn(self._LONG[:40], output)

    def test_every_open_item_id_survives_the_digest(self):
        """The honesty invariant. A 'collapse' that silently dropped an item
        would be indistinguishable, to the lead, from the item having been
        fixed — the laundering this milestone exists to end. This is the
        assertion that catches it."""
        items = [
            make_event(EVENT_TYPE_DEBT, content=f"Debt {i}: {self._LONG}")
            for i in range(3)
        ] + [
            make_event(EVENT_TYPE_CONCERN, content=f"Concern {i}: {self._LONG}")
            for i in range(3)
        ]
        self._write_events(items)
        for item in items[:2] + items[3:5]:
            self._defer(item["id"])

        output = triage_preload.run(self.smm_dir)
        for item in items:
            self.assertIn(f"[id: {item['id']}]", output)
        # The header count is PER SECTION, not global: 4 deferred items split
        # 2-and-2 across Open Debts and Open Concerns read as "2 items" twice.
        # A global count would say "4 items" in both, overstating each section.
        self.assertEqual(output.count("#### Deferred earlier — 2 items"), 2)
        self.assertNotIn("— 4 items", output)

    def test_digest_line_says_nothing_that_reads_as_resolved(self):
        deferred = make_event(EVENT_TYPE_DEBT, content=self._LONG)
        self._write_events([deferred])
        self._defer(deferred["id"])

        line = next(
            ln
            for ln in triage_preload.run(self.smm_dir).splitlines()
            if deferred["id"] in ln
        )
        for word in ("resolved", "fixed", "closed", "done", "dropped", "no longer"):
            self.assertNotIn(word, line.lower(), f"digest line implies closure: {line}")

    def test_block_shrinks_by_at_least_40_percent_once_the_lead_defers(self):
        """AC1, measured on the same fixture through the real writer: render,
        defer everything, render again."""
        items = [
            make_event(EVENT_TYPE_CONCERN, content=f"Concern {i}: {self._LONG}")
            for i in range(10)
        ]
        self._write_events(items)
        before = len(triage_preload.run(self.smm_dir))

        for item in items:
            self._defer(item["id"])
        after = len(triage_preload.run(self.smm_dir))

        self.assertLessEqual(
            after,
            before * 0.6,
            f"block went {before} -> {after} chars; AC1 requires >= 40% smaller",
        )

    def test_undeferred_item_keeps_its_full_excerpt_byte_for_byte(self):
        """AC1's other half. The digest is earned by the lead's own deferral;
        an item they have not judged loses nothing."""
        untouched = make_event(EVENT_TYPE_DEBT, content=f"Untouched: {self._LONG}")
        deferred = make_event(EVENT_TYPE_DEBT, content=f"Deferred: {self._LONG}")
        self._write_events([untouched, deferred])

        def _line_for(event_id: str) -> str:
            return next(
                ln
                for ln in triage_preload.run(self.smm_dir).splitlines()
                if event_id in ln
            )

        before = _line_for(untouched["id"])
        self._defer(deferred["id"])
        self.assertEqual(before, _line_for(untouched["id"]))


class TestDigestContractWithItsReader(_SMMTestCase):
    """Both sides of the digest contract, pinned together.

    The sub-block is a contract between this renderer and the prose that acts on
    it: xp-work-selection Step 3 auto-resolves a MAYBE ADDRESSED concern WITHOUT
    ASKING, and a drop is terminal — so it has to know that a digest line is an
    index excerpt and fetch the full text first. Rename the header on one side
    only and the instruction silently stops matching anything.
    """

    _SKILL = (
        Path(__file__).parent.parent.parent
        / "skills"
        / "xp-work-selection"
        / "SKILL.md"
    )

    def _rendered_header(self) -> str:
        item = make_event(EVENT_TYPE_CONCERN, content="Some concern")
        self._write_events([item])
        triage_event(self.smm_dir, "triage-defer", item["id"])
        return next(
            ln
            for ln in triage_preload.run(self.smm_dir).splitlines()
            if ln.startswith("####")
        )

    def test_skill_prose_names_the_header_the_renderer_emits(self):
        header = self._rendered_header()
        marker = header.split("—")[0].strip()
        self.assertIn(marker, self._SKILL.read_text())

    def test_header_carries_a_runnable_retrieval_command(self):
        """The digest's whole honesty claim is that the id retrieves the whole
        item, so the command it names must be the runnable one."""
        header = self._rendered_header()
        self.assertIn("python3 ${CLAUDE_PLUGIN_ROOT}/smm/smm_cli.py", header)
        self.assertIn("get-event <id>", header)


if __name__ == "__main__":
    unittest.main()
