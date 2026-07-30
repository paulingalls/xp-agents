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

# `band_offender` renders "<name>: <actual> chars, <pct>% of budget <budget>".
# Parsed rather than string-matched against a literal like "99.0" so a
# one-character drift in the measured surface cannot break the proof.
_BAND_PCT_RE = re.compile(r"(\d+\.\d)% of budget")


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
    match = _BAND_PCT_RE.search(message)
    if match is None:
        testcase.fail(f"no band percentage to read in: {message!r}")
    pct = float(match.group(1))
    testcase.assertGreaterEqual(pct, 98.0, f"{pct}% is below the band")
    testcase.assertLessEqual(pct, 100.0, f"{pct}% is a breach, not the band")
