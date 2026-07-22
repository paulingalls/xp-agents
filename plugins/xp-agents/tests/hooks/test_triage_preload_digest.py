#!/usr/bin/env python3
"""Tests for the triage block's DIGEST form: the shorter rendering an item
earns once the lead has deferred it.

Split from test_triage_preload.py by feature (base rendering / aging / commit
overlap stay there) when the two together crossed the 500-line cap.
"""

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
from conftest import _SMMTestCase, make_event, triage_event
from event_schema import EVENT_TYPE_CONCERN, EVENT_TYPE_DEBT


class _DigestTestCase(_SMMTestCase):
    """Fixtures defer through the REAL writer, so they cannot encode an intent
    shape the writer does not produce."""

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

    def _line_for(self, event_id: str) -> str:
        return next(
            ln for ln in triage_preload.run(self.smm_dir).splitlines() if event_id in ln
        )


class TestDeferredDigest(_DigestTestCase):
    """Story-002. An item the LEAD ALREADY DEFERRED earns a shorter form.

    Not a smaller version of the 400-char excerpt — an INDEX ENTRY. The 400-char
    bound exists so the lead can triage an item FROM THE BLOCK; a digested item
    has already been triaged, so its line only has to be recognisable, with the
    id that retrieves the whole thing. Cutting the FULL items to 60 would repeat
    story-013's mistake (mid-WHY cuts on items the lead has not yet judged).
    """

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

        line = self._line_for(deferred["id"])
        for word in ("resolved", "fixed", "closed", "done", "dropped", "no longer"):
            self.assertNotIn(word, line.lower(), f"digest line implies closure: {line}")

    def test_block_shrinks_by_at_least_40_percent_once_the_lead_defers(self):
        """AC1, measured on the same fixture through the real writer: render,
        defer everything, render again.

        This fixture defers EVERYTHING, so it measures the mechanism, not a
        forecast — read it as a floor on the best case, and do not quote it as
        the saving a real project sees. What a real log gets depends entirely on
        what FRACTION of its items the lead has deferred, because an undeferred
        item is untouched by design. Measured live at story close: 34 of 68 open
        items deferred → 31.6% off the whole block, while the same change over
        the population as it stood when the story began (52 items, 35 deferred)
        was 44.5%. Same code, same day; the block grew 16 new undeferred items
        in between. The per-item efficacy is the stable number: 69% off the
        items that digest.
        """
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

        before = self._line_for(untouched["id"])
        self._defer(deferred["id"])
        self.assertEqual(before, self._line_for(untouched["id"]))


class TestDigestExemptions(_DigestTestCase):
    """Two kinds of deferred item keep the full excerpt anyway.

    Both exist because the digest reads the deferral as "the lead has judged
    this and is comfortable carrying it" — and there are two cases where that
    reading is wrong.
    """

    def test_high_severity_deferred_concern_still_renders_full(self):
        """A high-severity concern is the one item a lead most needs the WHY of
        while deciding, deferral or not."""
        concern = make_event(EVENT_TYPE_CONCERN, content=self._LONG, severity="high")
        self._write_events([concern])
        self._defer(concern["id"])

        output = triage_preload.run(self.smm_dir)
        self.assertNotIn("#### Deferred earlier", output)
        self.assertIn(self._LONG[:200], output)
        self.assertIn("DEFERRED x1", output)  # still annotated, just not shrunk

    def test_repeatedly_deferred_item_returns_to_full_length(self):
        """Repeated deferral is evidence of NEGLECT. Left alone the digest
        would invert that signal — the item shrinking as the count grows."""
        carried = make_event(EVENT_TYPE_DEBT, content=f"Carried: {self._LONG}")
        once = make_event(EVENT_TYPE_DEBT, content=f"Once: {self._LONG}")
        self._write_events([carried, once])
        self._defer(carried["id"], times=3)
        self._defer(once["id"])

        self.assertIn("DEFERRED x3", self._line_for(carried["id"]))
        self.assertIn(f"Carried: {self._LONG}"[:200], self._line_for(carried["id"]))
        self.assertNotIn(f"Once: {self._LONG}"[:200], self._line_for(once["id"]))
        self.assertEqual(
            triage_preload.run(self.smm_dir).count("#### Deferred earlier — 1 item"), 1
        )

    def test_two_deferrals_still_digest(self):
        """The boundary, so `>= 3` cannot drift to `>= 2` unnoticed."""
        twice = make_event(EVENT_TYPE_DEBT, content=self._LONG)
        self._write_events([twice])
        self._defer(twice["id"], times=2)

        self.assertIn("#### Deferred earlier", triage_preload.run(self.smm_dir))
        self.assertNotIn(self._LONG[:200], self._line_for(twice["id"]))


class TestInertWithoutDeferrals(_DigestTestCase):
    """No deferral, no change. On a fresh project — and on any project whose
    lead has not triaged yet — the block is what it was before this feature
    existed, byte for byte. Spelled out as a literal rather than as a
    "contains" check, because the point is that NOTHING moved."""

    def test_output_is_byte_identical_when_no_intent_is_recorded(self):
        debt = make_event(EVENT_TYPE_DEBT, content="Ship the retry budget")
        concern = make_event(EVENT_TYPE_CONCERN, content="Auth token leak")
        self._write_events([debt, concern])

        self.assertEqual(
            triage_preload.run(self.smm_dir),
            f"### Open Debts:\n"
            f"- [id: {debt['id']}] Ship the retry budget (0 sessions old)\n"
            f"\n"
            f"### Open Concerns:\n"
            f"- [id: {concern['id']}] Auth token leak (0 sessions old)",
        )


class TestDigestContractWithItsReader(_DigestTestCase):
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
        self._defer(item["id"])
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
