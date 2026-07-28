#!/usr/bin/env python3
"""Tests for scripts/session_markers.py — the per-session marker lifecycle.

Follows the production move: `session_marker`, `marker_age_seconds` and the
SessionStart sweep set left markers.py, so their tests leave test_markers.py.
The sweep's own behaviour is pinned by its consumers
(test_housekeeping_stop_gate.py, test_session_start_effects.py,
test_teammate_config.py). What is pinned here is the naming rule, the aging
rule, the split itself, and the size cap the split exists to hold.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import markers
import session_markers

_SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"

# The recorded sub-cap is 450, not 499: "comfortably under 500" is a judgement
# a green suite cannot make, and "just under 500" is exactly how markers.py
# reached 498 before this split. Both halves are held so that extracting into a
# sibling which itself busts the cap only defers the next split.
_LINE_SUB_CAP = 450
_CAPPED_MODULES = ("markers.py", "session_markers.py")

# Moved out of markers.py with no re-export shim — call sites were updated
# directly, which is the stated remedy of the debt the split closed.
_MOVED_SYMBOLS = (
    "session_marker",
    "marker_age_seconds",
    "_STALE_SESSION_MARKERS",
    "sweep_stale_session_markers",
)


# ---------------------------------------------------------------------------
# session_marker
# ---------------------------------------------------------------------------


class TestSessionMarker(unittest.TestCase):
    """The naming rule both session-keyed markers share.

    It is a path-safety rule — a session id is untrusted input that would
    otherwise steer a path — so it is pinned here, once, rather than in each
    consumer.
    """

    def test_a_session_id_never_reaches_the_filename(self):
        marker = session_markers.session_marker(".m", "../../etc/passwd\n")
        self.assertRegex(marker.name, r"^\.m-[0-9a-f]{12}$")

    def test_distinct_ids_get_distinct_markers(self):
        self.assertNotEqual(
            session_markers.session_marker(".m", "a").name,
            session_markers.session_marker(".m", "b").name,
        )

    def test_the_same_id_resolves_stably(self):
        # Writer and reader are different processes; an unstable name would
        # make every read miss.
        self.assertEqual(
            session_markers.session_marker(".m", "a").name,
            session_markers.session_marker(".m", "a").name,
        )

    def test_no_usable_id_falls_back_to_the_shared_name(self):
        # A blank or non-str id must NOT key a marker on the hash of a value no
        # reader ever addresses: that file would exist on disk, be invisible to
        # every check, and outlive the sweep that reaps suffixed siblings.
        for value in (None, "", "   ", 17, [], {}):
            with self.subTest(value=value):
                self.assertEqual(session_markers.session_marker(".m", value).name, ".m")

    def test_surrounding_whitespace_does_not_fork_the_name(self):
        self.assertEqual(
            session_markers.session_marker(".m", " a ").name,
            session_markers.session_marker(".m", "a").name,
        )

    def test_result_is_a_json_marker(self):
        for value in ("a", None):
            with self.subTest(value=value):
                marker = session_markers.session_marker(".m", value)
                self.assertEqual(marker.content_type, "json")
                self.assertFalse(marker.agent_scoped)


# ---------------------------------------------------------------------------
# marker_age_seconds
#
# Characterization tests: `marker_age_seconds` had zero direct tests before
# the move — it was reached only through hook_liveness and
# housekeeping_flight — so these pass by design on the first run. They are
# not a red phase and they do not catch a bug; they are the instrument that
# makes the extraction to session_markers.py provable.
# ---------------------------------------------------------------------------


class TestMarkerAgeSeconds(unittest.TestCase):
    """The branches documented in the function's own docstring."""

    def test_usable_timestamp_returns_the_elapsed_seconds(self):
        self.assertEqual(session_markers.marker_age_seconds(1000.0, 400.0), 600.0)
        self.assertEqual(session_markers.marker_age_seconds(1000.0, 400), 600.0)

    def test_non_numeric_timestamp_is_rejected(self):
        # A missing key reads as None, and a corrupt marker can hold any JSON
        # type; none of them can be aged.
        for value in (None, "400.0", [400.0], {"written_at": 400.0}):
            with self.subTest(value=value):
                self.assertIsNone(session_markers.marker_age_seconds(1000.0, value))

    def test_boolean_timestamp_is_rejected(self):
        # bool is an int subclass, so a bare isinstance check would admit it.
        self.assertIsNone(session_markers.marker_age_seconds(1000.0, True))
        self.assertIsNone(session_markers.marker_age_seconds(1000.0, False))

    def test_non_finite_timestamp_is_rejected(self):
        # json.loads admits NaN/Infinity by default, and neither compares
        # True against a staleness threshold, so a fail-closed caller would
        # otherwise read a corrupt marker as fresh.
        self.assertIsNone(session_markers.marker_age_seconds(1000.0, float("nan")))
        self.assertIsNone(session_markers.marker_age_seconds(1000.0, float("inf")))
        self.assertIsNone(session_markers.marker_age_seconds(1000.0, float("-inf")))

    def test_out_of_range_int_returns_none(self):
        # Too large to become a float: the OverflowError is caught and turned
        # into "cannot age this", not propagated to a caller mid-verdict.
        self.assertIsNone(session_markers.marker_age_seconds(1000.0, 10**400))

    def test_negative_age_is_returned_as_is(self):
        # Callers own the bounds; this helper does not clamp a future
        # timestamp to zero.
        self.assertEqual(session_markers.marker_age_seconds(1000.0, 1500.0), -500.0)


# ---------------------------------------------------------------------------
# The split itself
# ---------------------------------------------------------------------------


class TestMarkersSplit(unittest.TestCase):
    """Pin the markers.py / session_markers.py split.

    Without these, the extraction's whole point is unenforced: markers.py can
    creep back over cap with a green suite, and a well-meaning re-export shim
    can quietly restore the coupling the split removed.
    """

    def test_moved_symbols_are_not_re_exported_by_markers(self):
        for name in _MOVED_SYMBOLS:
            with self.subTest(name=name):
                self.assertFalse(
                    hasattr(markers, name),
                    f"markers.{name} is back — call sites resolve it on "
                    f"session_markers, and a shim re-couples the two modules",
                )
                self.assertTrue(
                    hasattr(session_markers, name),
                    f"session_markers.{name} is missing — every call site "
                    f"resolves it there",
                )

    def test_both_modules_stay_under_the_sub_cap(self):
        for name in _CAPPED_MODULES:
            with self.subTest(module=name):
                line_count = len((_SCRIPTS_DIR / name).read_text().splitlines())
                # Non-vacuity: a zero-line read would satisfy any cap, so an
                # emptied file or a wrong path fails here rather than passing.
                self.assertGreater(
                    line_count, 0, f"scanned no lines of {name} — pin is vacuous"
                )
                self.assertLessEqual(
                    line_count,
                    _LINE_SUB_CAP,
                    f"{name} is {line_count} lines, over the {_LINE_SUB_CAP} "
                    f"sub-cap — extract a cohesive group into a sibling module",
                )


if __name__ == "__main__":
    unittest.main()
