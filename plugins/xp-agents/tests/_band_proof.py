#!/usr/bin/env python3
"""Shared reading of a band-wiring proof's failure message.

A wiring proof drives a REAL surface into the 98% band with a fabricated
budget — at or above 98% of it and still under it — because that is the one
region only `band_offender` reports. A breach check cannot: it needs the
surface to be over its cap.

Asserting that "something raised" is not enough there, and the gap is not
theoretical — it is the defect these proofs exist to close:

* the public budget asserts also raise when the surface's subprocess exits
  non-zero, so a broken fixture reads as a caught failure;
* a preload that refuses for want of a live hook runtime prints a short
  banner that measures well under every budget, so a proof could pass while
  measuring the refusal rather than the surface;
* a breach check still reports an over-cap surface, so a proof calibrated a
  little too high survives the very mutation it should catch.

So a proof reads the message: it must name the surface, carry a band
percentage, and that percentage must land inside the band. Shared because
four call sites need the identical reading and each lives in its own host
module.
"""

import re
import unittest

_BAND_LINE = r": (\d+) chars, (\d+\.\d)% of budget (\d+)"


def _band_line_re(surface: str) -> re.Pattern[str]:
    """`band_offender`'s line for THIS surface: "<name>: <n> chars, <pct>% ...".

    Anchored to the surface's own line because the public asserts report every
    offender they found, so an unanchored search would read whichever came
    first. Counts are parsed rather than string-matched against a literal like
    "99.0" so a one-character drift in the surface cannot break the proof.
    """
    return re.compile(re.escape(surface) + _BAND_LINE)


def in_band_budget(actual: int) -> int:
    """A budget that puts `actual` mid-band: >= 98% of it, still under it.

    ~1% above the measurement, so the surface lands near 99% and roughly a
    percent of drift either way cannot flip the verdict — up into a breach
    (over cap, which a bare breach check would also catch) or down out of the
    band (which nothing catches). The band is only 2% wide, and the surfaces
    driven here are measured by a separate bootstrap from the one the assert
    runs, so the slack is what makes the proof stable rather than lucky.
    """
    return actual + max(2, actual // 100)


def below_band_budget(actual: int) -> int:
    """A budget generous enough that `actual` sits below the band (~91%).

    The passing twin of every proof: it is what shows the proof above reports
    the BAND and not a breach.
    """
    return actual + max(10, actual // 10)


def assert_band_fired(
    testcase: unittest.TestCase, error: BaseException, surface: str
) -> None:
    """The failure names `surface` and reports a band percentage in [98, 100]."""
    message = str(error)
    testcase.assertIn(surface, message, f"failure does not name {surface}")
    testcase.assertNotIn(
        "subprocess rc=",
        message,
        "the surface never ran — this proof would pass with no band at all",
    )
    testcase.assertIn("% of budget", message, "not a band_offender line")
    match = _band_line_re(surface).search(message)
    if match is None:
        testcase.fail(f"no band line for {surface} to read in: {message!r}")
    actual, pct, budget = int(match[1]), float(match[2]), int(match[3])
    testcase.assertGreaterEqual(pct, 98.0, f"{pct}% is below the band")
    # Read off the counts, not the rendered percentage: a breach only a few
    # chars over an 8,000-char budget renders as "100.0%", so a `pct <= 100`
    # test would accept the one case this proof must reject — a surface
    # calibrated high enough that a bare cap check reports it too.
    testcase.assertLessEqual(
        actual,
        budget,
        f"{actual} chars is over budget {budget} ({pct}%) — a breach a bare "
        "cap check reports too, so this is not proof the band is wired",
    )


def _measure_via_assert(assert_at_budget, surface: str) -> int:
    """Measure a surface by asking the ASSERT what it sees.

    A parallel bootstrap is not a safe proxy: `assert_*_under_budgets` runs
    every surface through ONE seeded SMM in a fixed order, so earlier state
    reaches later surfaces. The gap was 184 chars on `subagent_start.py`,
    hidden only because unnormalized checkout paths inflated the assert's side
    back into the band by coincidence; fixing that dropped this proof to 89%.
    A proof of an assert must not measure by a second route.
    """
    try:
        assert_at_budget(1)
    except AssertionError as exc:
        match = _band_line_re(surface).search(str(exc))
        if match is not None:
            return int(match[1])
        raise AssertionError(
            f"no band line for {surface} to measure from: {exc}"
        ) from exc
    raise AssertionError(
        f"{surface} did not breach a budget of 1 — it produced no measurable "
        "stdout, so neither band leg would prove anything"
    )
