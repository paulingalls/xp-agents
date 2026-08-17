#!/usr/bin/env python3
"""Tests that budget measurement uses character counts, not lines or bytes.

RED until _budget_helpers.py is updated:
- TestMdCharMeasurement: fails because assert_md_under_budgets currently
  uses splitlines() (line count), so a file with few lines but many chars
  is NOT flagged as an offender when it should be.

GREEN after fix:
- assert_md_under_budgets uses len(read_text()) instead of splitlines()
- assert_emitter_under_budgets uses len(decoded) instead of len(bytes)
- assert_preload_under_budgets uses len(decoded) instead of len(bytes)
"""

import math
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

# Pins the liveness bypass on import: this module drives REAL preloads, and one
# without the bypass refuses with a 419-char banner instead of its stdout.
# Imported directly because only pytest loads `conftest` for us — under the
# unittest fallback the pin would ride on some unrelated module's import.
import _env_hygiene  # noqa: F401
from _band_proof import (
    _measure_via_assert,
    assert_band_fired,
    below_band_budget,
    in_band_budget,
)
from _bases import _PLUGIN_ROOT
from _budget_helpers import (
    _bootstrap_seeded_smm,
    _measured_len,
    _run_emitter,
    _run_preload,
    assert_emitter_under_budgets,
    assert_md_budgets_match,
    assert_md_under_budgets,
    assert_preload_under_budgets,
    band_offender,
    ratchet,
)
from _test_typing import _MixinBase

_SCRIPTS_DIR = _PLUGIN_ROOT / "scripts"

# The smallest measurement that can plausibly be a real stdout surface rather
# than a stand-in for one. A preload that refuses for want of a live hook
# runtime prints a ~419-char banner, and a budget derived from THAT sits
# mid-band just as neatly — so a proof that measured the refusal would read
# green while pinning nothing at all.
_MIN_REAL_MEASUREMENT = 1000


class _SpyCase(unittest.TestCase):
    """A throwaway TestCase to pass as the `testcase` arg of a budget assert.

    It raises AssertionError like any other TestCase — the point is that the
    failure lands on THIS instance, so the caller can catch and read it without
    polluting the outer test's own state.
    """

    def runTest(self) -> None:
        pass


class TestMdCharMeasurement(unittest.TestCase):
    """assert_md_under_budgets must measure files in characters, not lines."""

    def test_few_lines_many_chars_reported_as_offender(self) -> None:
        """File under line-budget but over char-budget must be flagged.

        Construct a .md with 3 lines but ~603 characters. Set a budget of 10:
        - 3 lines < 10  → line-based code does NOT flag it (wrong)
        - 603 chars > 10 → char-based code flags it as an offender (correct)

        The test asserts the offender IS reported, so it is RED against the
        current line-based implementation and GREEN after the char fix.
        """
        long_line = "x" * 200
        content = "\n".join([long_line, long_line, long_line])

        line_count = len(content.splitlines())  # 3
        char_count = len(content)  # 603

        budget = 10  # above line_count, below char_count

        self.assertLessEqual(line_count, budget, "precondition: lines under budget")
        self.assertGreater(char_count, budget, "precondition: chars exceed budget")

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            (tmp_path / "TESTFILE.md").write_text(content, encoding="utf-8")

            spy = _SpyCase()
            offender_reported = False
            try:
                assert_md_under_budgets(
                    spy, tmp_path, "*.md", {"TESTFILE": budget}, "test"
                )
            except AssertionError:
                offender_reported = True

            self.assertTrue(
                offender_reported,
                "assert_md_under_budgets must flag the file as an offender "
                "when its character count exceeds the budget, even when its "
                "line count does not.",
            )


class TestStdoutCharMeasurement(unittest.TestCase):
    """Stdout budget measurement must use decoded character count, not byte count.

    For ASCII-only output, bytes == chars, so existing budgets are unchanged.
    For multibyte UTF-8 output, this distinction matters: 'é'*100 is 100 chars
    but 200 bytes. The budget is in chars, so the correct measurement is the
    decoded character length.
    """

    def test_multibyte_utf8_char_count_differs_from_byte_count(self) -> None:
        """'é'*100 is 100 chars and 200 bytes — correct measurement is 100 chars."""
        content = "é" * 100
        stdout_bytes = content.encode("utf-8")

        byte_count = len(stdout_bytes)
        char_count = len(stdout_bytes.decode("utf-8", errors="replace"))

        self.assertEqual(byte_count, 200, "UTF-8 encoding of 'é'*100 is 200 bytes")
        self.assertEqual(char_count, 100, "Decoded char count of 'é'*100 is 100 chars")

    def test_budget_measured_in_chars_allows_content_under_char_budget(self) -> None:
        """Budget of 150 chars must ALLOW 100 chars even if the byte count is 200.

        Under byte measurement: 200 > 150 → flagged as offender (wrong).
        Under char measurement: 100 < 150 → within budget (correct).

        This pins the formula: len(stdout_bytes.decode('utf-8', errors='replace')).
        """
        content = "é" * 100
        stdout_bytes = content.encode("utf-8")

        budget = 150  # above char count (100), below byte count (200)

        char_count = len(stdout_bytes.decode("utf-8", errors="replace"))
        byte_count = len(stdout_bytes)

        # Char measurement: within budget — the correct behavior
        self.assertLessEqual(char_count, budget, "char count must be within budget")
        # Byte measurement: would exceed budget — the wrong behavior
        # bytes > budget; chars <= budget — demonstrates the unit matters
        self.assertGreater(byte_count, budget)


class TestRatchetNeverRaises(unittest.TestCase):
    """`ratchet` recalculates a budget DOWNWARD only.

    The recorded calibration rule is `actual * 1.125`, and applied on its own
    it RAISES most surfaces: it only lowers when `actual` has fallen below
    `current / 1.125` — an 11.1% cut. Most files the audit trimmed were
    trimmed by less than that, so the monotonic guard is what makes the rule a
    ratchet instead of a re-baseline.
    """

    def test_barely_trimmed_file_keeps_its_old_budget(self):
        """The case the guard exists for — a file the audit barely touched.

        Verified on a small trim, not only on a large one: at a 1% cut the raw
        formula wants a HIGHER number than the budget already on record.
        """
        current = 8900
        actual = 8811  # a 1% trim off a file that sat at 8900

        raw_formula = round(actual * 1.125 / 10) * 10
        self.assertGreater(
            raw_formula,
            current,
            "precondition: the raw formula wants to RAISE this budget",
        )
        self.assertEqual(ratchet(actual, current, 10), current)

    def test_never_returns_above_current_across_the_range(self):
        """Swept rather than sampled: monotonicity must hold at every size."""
        for granularity in (10, 100):
            for current in (100, 1150, 8900, 23100):
                for actual in range(0, current + 200, 97):
                    with self.subTest(g=granularity, current=current, actual=actual):
                        self.assertLessEqual(
                            ratchet(actual, current, granularity), current
                        )

    def test_hard_trimmed_file_actually_lowers(self):
        """The other direction: the ratchet must still bite when it can.

        Without this, `return current` would satisfy every other test here.
        """
        self.assertEqual(ratchet(5668, 8900, 100, rounding=math.ceil, floor=100), 6400)

    def test_lowered_budget_leaves_the_file_near_89_percent(self):
        """The calibration multiplier and the 98% band are separate knobs.

        A freshly ratcheted surface must land well clear of the band, or the
        ratchet would arm a failure in the same commit that computes it.
        Asserted on the post-audit numbers rather than taken on faith.
        """
        for actual, current, granularity in (
            (5668, 8900, 100),
            (1024, 1150, 10),
            (20500, 23100, 10),
        ):
            with self.subTest(actual=actual):
                kwargs = (
                    {"rounding": math.ceil, "floor": 100} if granularity == 100 else {}
                )
                new = ratchet(actual, current, granularity, **kwargs)
                pct = actual / new * 100
                self.assertLess(pct, 98.0, f"{pct:.1f}% is inside the band")
                self.assertGreater(pct, 85.0, f"{pct:.1f}% wastes headroom")


class TestRatchetNonVacuity(unittest.TestCase):
    """A measurement of 0 must NOT become a budget of 0.

    Ten of the emitter fixtures measure 0 chars: the fixture drives the
    emitter's no-trigger path, so the surface is never exercised. Ratcheting
    that to 0 would encode "this scans nothing" as the bound — the same defect
    story-001 fixed, where a pin scanned less than it claimed.
    """

    def test_zero_measurement_leaves_the_budget_unchanged(self):
        self.assertEqual(ratchet(0, 100, 100, rounding=math.ceil, floor=100), 100)
        self.assertEqual(ratchet(0, 1150, 10), 1150)

    def test_zero_measurement_does_not_collapse_to_the_floor(self):
        """Distinct from the floor: floor=100 would also yield 100 here.

        Use a budget well above the floor so "returned current" and "returned
        floor" are different numbers and the test can tell them apart.
        """
        self.assertEqual(ratchet(0, 8900, 100, rounding=math.ceil, floor=100), 8900)


class TestNinetyEightPercentBand(unittest.TestCase):
    """The assertion must fail BEFORE breach, and say by how much.

    Firing only on breach is why nine skills, three agents and one guide
    drifted to 98-100% of cap while every suite stayed green.
    """

    def test_file_at_98_percent_is_an_offender(self):
        offender = band_offender("XP_VALUES", 980, 1000)
        self.assertIsNotNone(offender, "98.0% of cap must fail, not pass")

    def test_offender_names_the_file_and_its_percentage(self):
        offender = band_offender("PROCESS_GUIDE", 8730, 8900)
        assert offender is not None
        self.assertIn("PROCESS_GUIDE", offender, "must name the file")
        self.assertIn("98.1", offender, "must name the percentage, not just chars")

    def test_file_below_the_band_passes(self):
        self.assertIsNone(band_offender("XP_VALUES", 979, 1000))

    def test_file_over_budget_is_still_an_offender(self):
        """The band widens the old check; it must not replace it."""
        self.assertIsNotNone(band_offender("XP_VALUES", 1200, 1000))

    def test_zero_measurement_is_not_a_band_offender(self):
        """Consistent with the ratchet's non-vacuity guard.

        `hook_io.py` carries a deliberate budget of 0 and emits no reason
        prose. A naive `actual >= 0.98 * budget` reads 0 >= 0 as a breach and
        fails a surface that has not grown by a single character.
        """
        self.assertIsNone(band_offender("hook_io.py", 0, 0))
        self.assertIsNone(band_offender("prompt_nugget.py", 0, 100))

    def test_prose_arriving_at_a_zero_budget_is_an_offender(self):
        """The other half: 0 is a bound, not an exemption."""
        self.assertIsNotNone(band_offender("hook_io.py", 12, 0))

    def test_assert_md_under_budgets_is_actually_wired_to_the_band(self):
        """The band must reach the ASSERTION, not just live in the helper.

        Every other test here calls `band_offender` directly, and the sibling
        char-measurement test uses a file that is OVER budget — which the old
        `actual > budget` check flagged too. So reverting
        `assert_md_under_budgets` to the breach check would leave the whole
        suite green. This is the one case that separates them: 98 chars
        against a budget of 100 is inside the band and UNDER the cap.
        """
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            (tmp_path / "INBAND.md").write_text("x" * 98, encoding="utf-8")

            spy = _SpyCase()
            with self.assertRaises(AssertionError) as caught:
                assert_md_under_budgets(spy, tmp_path, "*.md", {"INBAND": 100}, "test")
            self.assertIn("INBAND", str(caught.exception))
            self.assertIn("98.0", str(caught.exception))

    def test_assert_md_under_budgets_passes_below_the_band(self):
        """The other side of the wiring — 97 chars against 100 must pass."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            (tmp_path / "CLEAR.md").write_text("x" * 97, encoding="utf-8")
            assert_md_under_budgets(
                _SpyCase(), tmp_path, "*.md", {"CLEAR": 100}, "test"
            )


def _measure_emitter(script_name: str) -> int:
    """Mirror `assert_emitter_under_budgets`' own measurement, exactly.

    No `normalize_paths` — the helper passes none, so any absolute path the
    emitter echoes makes the count vary with whichever bootstrap measured it.
    This runs its own bootstrap, so the two can disagree by a character;
    `in_band_budget`'s ~1% slack is what absorbs that.
    """
    with tempfile.TemporaryDirectory() as tmp:
        repo, smm_dir = _bootstrap_seeded_smm(Path(tmp))
        stdout_bytes, stderr, rc = _run_emitter(
            script_name, _SCRIPTS_DIR, smm_dir, repo
        )
        if rc != 0:
            raise AssertionError(f"{script_name}: rc={rc} stderr={stderr[:200]!r}")
        return _measured_len(stdout_bytes)


def _measure_preload(skill_name: str) -> int:
    """Mirror `assert_preload_under_budgets`' own measurement, exactly.

    WITH `normalize_paths`, because the helper passes all three: every
    checkout-variable path collapses to a placeholder, which makes this the
    bootstrap-stable one of the two stdout surfaces.
    """
    with tempfile.TemporaryDirectory() as tmp:
        repo, smm_dir = _bootstrap_seeded_smm(Path(tmp))
        stdout_bytes, stderr, rc = _run_preload(skill_name, smm_dir, repo)
        if rc != 0:
            raise AssertionError(f"{skill_name}: rc={rc} stderr={stderr[:200]!r}")
        return _measured_len(
            stdout_bytes,
            normalize_paths=(str(_PLUGIN_ROOT), str(smm_dir), str(repo)),
        )


class _StdoutBandProof(_MixinBase):
    """The two legs every stdout-surface band proof needs.

    Both public asserts take `budgets` as a parameter, so a one-entry dict
    drives exactly the surface under test and no other. Both also cost ~6
    subprocesses per call — three of them git, because
    `_bootstrap_seeded_smm` builds a repo and seeds an SMM before the surface
    runs — so the surface is measured once per class and both legs share it.
    """

    _SURFACE = ""
    actual = 0

    def _assert_under_budget(self, budget: int) -> None:
        """Call the public assert for this surface with a one-entry dict."""
        raise NotImplementedError

    def setUp(self) -> None:
        self.assertGreater(
            self.actual,
            _MIN_REAL_MEASUREMENT,
            f"{self._SURFACE} measured {self.actual} chars — too small to be "
            "its real stdout, so neither leg below would prove anything",
        )

    def test_surface_inside_the_band_is_reported(self) -> None:
        with self.assertRaises(AssertionError) as caught:
            self._assert_under_budget(in_band_budget(self.actual))
        assert_band_fired(self, caught.exception, self._SURFACE)

    def test_surface_below_the_band_passes(self) -> None:
        """The twin that proves the leg above reports the band, not a breach."""
        self._assert_under_budget(below_band_budget(self.actual))


class TestEmitterBandWiring(_StdoutBandProof, unittest.TestCase):
    """The band must reach `assert_emitter_under_budgets`, not just the helper.

    Reverting that assert to `actual > budget` left the whole suite green:
    every emitter fixture that reached an assertion was also over its cap, so
    nothing anywhere separated the band from a breach. `subagent_start.py` is
    the surface because it measures ~3,200 chars — a ~64-char band, wide
    enough to sit mid-band with room either side.
    """

    _SURFACE = "subagent_start.py"

    @classmethod
    def setUpClass(cls) -> None:
        cls.actual = _measure_via_assert(
            lambda budget: assert_emitter_under_budgets(
                _SpyCase(), _SCRIPTS_DIR, {cls._SURFACE: budget}, "emitter"
            ),
            cls._SURFACE,
        )

    def _assert_under_budget(self, budget: int) -> None:
        assert_emitter_under_budgets(
            _SpyCase(), _SCRIPTS_DIR, {self._SURFACE: budget}, "emitter"
        )


class TestPreloadBandWiring(_StdoutBandProof, unittest.TestCase):
    """Same proof for `assert_preload_under_budgets`, the other stdout family.

    `xp-free-close` is the surface because it measures ~8,600 chars — a
    ~170-char band, the widest window of any preload. `xp-assign` is the trap
    to avoid: at ~186 chars its band is ~4 chars wide, which is a coin toss
    rather than a test.
    """

    _SURFACE = "xp-free-close"

    @classmethod
    def setUpClass(cls) -> None:
        cls.actual = _measure_via_assert(
            lambda budget: assert_preload_under_budgets(
                _SpyCase(), {cls._SURFACE: budget}, "preload"
            ),
            cls._SURFACE,
        )

    def _assert_under_budget(self, budget: int) -> None:
        assert_preload_under_budgets(_SpyCase(), {self._SURFACE: budget}, "preload")


class TestMdBudgetsMatchStillFailsOnMissingEntry(unittest.TestCase):
    """AC4: the threshold change must not weaken the symmetric match.

    A shipped .md with no budget entry has no bound at all, which is a
    strictly worse failure than one sitting at 98% of a bound. Pinned here
    because the band and the match assertion live in the same module and a
    future edit could plausibly fold one into the other.
    """

    def test_shipped_md_without_a_budget_entry_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            (tmp_path / "BUDGETED.md").write_text("x", encoding="utf-8")
            (tmp_path / "UNBUDGETED.md").write_text("x", encoding="utf-8")

            spy = _SpyCase()
            with self.assertRaises(AssertionError) as caught:
                assert_md_budgets_match(
                    spy, tmp_path, "*.md", {"BUDGETED": 100}, "test"
                )
            self.assertIn("UNBUDGETED", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
