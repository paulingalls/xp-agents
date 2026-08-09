#!/usr/bin/env python3
"""Run-identifying attribution shared by both test-failure concern producers.

story-002: `bash_post_tool` (parsed counts) and `bash_failure` (non-zero exit,
counts often unavailable) must stamp the SAME keys, or a scoped run and a
full-suite run keep rendering identically at kickoff. story-001 built the
behavior inside `bash_post_tool`; this pins it in the shared module both
producers import, so the two cannot drift.

The omit-don't-fabricate rules are the point. A missing count is honest; a
zero is a lie that reads as a green run, and a total summed from two
independent regex scans (the `allow_scan_fallback` path) is worse still —
plausible fiction nothing looks wrong about.
"""

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import run_attribution
from event_metadata import (
    METADATA_KEY_CWD,
    METADATA_KEY_TEST_COUNT,
    METADATA_KEY_TEST_ERRORS,
    METADATA_KEY_TEST_FAILED,
)


class TestHomeRelativeCwd(unittest.TestCase):
    """`$HOME` collapses to `~`; anything outside it stays absolute.

    Moved verbatim from bash_post_tool._collapse_home_cwd (story-001). The
    guards are deliberate and each one is pinned below.
    """

    def test_home_prefix_collapses(self):
        with patch.dict(os.environ, {"HOME": "/Users/dev"}):
            self.assertEqual(
                run_attribution.home_relative_cwd("/Users/dev/src/proj"),
                "~/src/proj",
            )

    def test_home_itself_collapses_to_bare_tilde(self):
        with patch.dict(os.environ, {"HOME": "/Users/dev"}):
            self.assertEqual(run_attribution.home_relative_cwd("/Users/dev"), "~")

    def test_path_outside_home_stays_absolute(self):
        # A container mount or /tmp has no home to strip, and that is exactly
        # the case where the full path is the only attribution available.
        with patch.dict(os.environ, {"HOME": "/Users/dev"}):
            self.assertEqual(
                run_attribution.home_relative_cwd("/tmp/container-mount"),
                "/tmp/container-mount",
            )

    def test_prefix_collision_is_not_collapsed(self):
        # /Users/develop merely STARTS with /Users/dev — the `home + os.sep`
        # guard is what excludes it. Without it this would yield "~elop".
        with patch.dict(os.environ, {"HOME": "/Users/dev"}):
            self.assertEqual(
                run_attribution.home_relative_cwd("/Users/develop/src"),
                "/Users/develop/src",
            )

    def test_trailing_slash_on_home_still_collapses(self):
        # posixpath.expanduser rstrips '/' from the resolved home.
        with patch.dict(os.environ, {"HOME": "/Users/dev/"}):
            self.assertEqual(
                run_attribution.home_relative_cwd("/Users/dev/src"), "~/src"
            )

    def test_root_home_leaves_paths_absolute(self):
        # HOME=/ makes `home + os.sep` == '//', which matches nothing. Safe
        # (paths stay absolute) rather than collapsing every path to '~'.
        with patch.dict(os.environ, {"HOME": "/"}):
            self.assertEqual(run_attribution.home_relative_cwd("/srv/app"), "/srv/app")

    def test_unset_home_does_not_raise(self):
        # os.path.expanduser falls back to the pwd database and returns '~'
        # unchanged if that fails — it never raises, unlike Path.home().
        env = {k: v for k, v in os.environ.items() if k != "HOME"}
        with patch.dict(os.environ, env, clear=True):
            self.assertIsInstance(run_attribution.home_relative_cwd("/srv/app"), str)


class TestRunAttributionMetadata(unittest.TestCase):
    """Only keys the caller could honestly fill."""

    def test_full_shape_from_the_parsed_producer(self):
        with patch.dict(os.environ, {"HOME": "/Users/dev"}):
            meta = run_attribution.run_attribution_metadata(
                "/Users/dev/wt", failed=2, total=23, errors=1
            )
        self.assertEqual(meta[METADATA_KEY_CWD], "~/wt")
        self.assertEqual(meta[METADATA_KEY_TEST_FAILED], 2)
        self.assertEqual(meta[METADATA_KEY_TEST_COUNT], 23)
        self.assertEqual(meta[METADATA_KEY_TEST_ERRORS], 1)

    def test_zero_errors_omitted_not_recorded(self):
        meta = run_attribution.run_attribution_metadata(
            "/tmp/x", failed=2, total=23, errors=0
        )
        self.assertNotIn(METADATA_KEY_TEST_ERRORS, meta)

    def test_failed_without_total_is_the_degraded_producer_shape(self):
        # bash_failure records no total: on the scan-fallback path passed and
        # failed come from two independent last-match scans, so their sum is
        # not a denominator anyone should trust.
        meta = run_attribution.run_attribution_metadata("/tmp/x", failed=2)
        self.assertEqual(meta[METADATA_KEY_TEST_FAILED], 2)
        self.assertNotIn(METADATA_KEY_TEST_COUNT, meta)

    def test_no_counts_leaves_only_the_checkout(self):
        meta = run_attribution.run_attribution_metadata("/tmp/x")
        self.assertEqual(meta, {METADATA_KEY_CWD: "/tmp/x"})

    def test_absent_cwd_omits_the_key_rather_than_defaulting(self):
        meta = run_attribution.run_attribution_metadata(None, failed=2)
        self.assertNotIn(METADATA_KEY_CWD, meta)
        self.assertEqual(meta[METADATA_KEY_TEST_FAILED], 2)

    def test_empty_cwd_omits_the_key(self):
        # The hook payload default is "." elsewhere; an empty string must not
        # become a recorded attribution of nowhere.
        self.assertNotIn(METADATA_KEY_CWD, run_attribution.run_attribution_metadata(""))

    def test_zero_failed_is_recorded_not_dropped(self):
        # 0 is a real observation here, distinct from None. Falsy-zero must
        # not be swallowed the way an absent count is.
        meta = run_attribution.run_attribution_metadata("/tmp/x", failed=0, total=23)
        self.assertEqual(meta[METADATA_KEY_TEST_FAILED], 0)
        self.assertEqual(meta[METADATA_KEY_TEST_COUNT], 23)

    def test_nothing_known_yields_an_empty_block(self):
        self.assertEqual(run_attribution.run_attribution_metadata(None), {})


if __name__ == "__main__":
    unittest.main()
