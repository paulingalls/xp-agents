#!/usr/bin/env python3
"""Tests for bun's dual shape in scripts/verify_paths.py.

bun is a hybrid: a package-script launcher (`bun run test`, `bun test:unit`)
AND a direct runner naming spec files as positionals (`bun test a.test.ts`).
Before this module, every bun command collapsed to the whole-tree sentinel —
see docs/ideas/1-VERIFY_GATE_COVERAGE.md §1. Split from
test_verify_paths_command_parsing.py's jest cluster shape (:138-200) because
this is a new, previously-uncovered command family, not an extension of an
existing cluster.

The second class of tests here (`TestChainedCommandRegressionPins`) is a
deliberate departure from the source doc's "anchor after the literal `test`
token" rule: that rule was prototyped only against bun-only shapes, and
applied to all positional frameworks it drops the proof path on a chained
command like `npx jest a.test.js && npm run build`. These pins PASS today —
they exist so a later attempt at the broader anchor rule gets a red instead
of a silent fail-open. Decision recorded in the SMM (topic
`bun-extractor-anchor`).
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

import verify_paths


class TestBunDirectRunnerPositional(unittest.TestCase):
    def test_bun_test_single_spec_positional(self):
        self.assertEqual(
            verify_paths.classify_path_strategy("bun test packages/db/src/x.test.ts"),
            "positional",
        )
        self.assertEqual(
            verify_paths._extract_paths_from_command(
                "bun test packages/db/src/x.test.ts"
            ),
            {"packages/db/src/x.test.ts"},
        )

    def test_bun_test_two_specs(self):
        self.assertEqual(
            verify_paths._extract_paths_from_command(
                "bun test pkg/x.test.ts pkg/y.test.ts"
            ),
            {"pkg/x.test.ts", "pkg/y.test.ts"},
        )

    def test_cd_prefix_rebases_bun_spec(self):
        self.assertEqual(
            verify_paths._extract_paths_from_command(
                "cd packages/db && bun test src/x.test.ts"
            ),
            {"packages/db/src/x.test.ts"},
        )

    def test_bun_config_flag_binary_skip_keeps_spec(self):
        # `--config` is skipped as a flag, its value `bunfig.toml` is
        # (wrongly, but harmlessly) consumed as "the binary" and discarded —
        # it never appears as a path, and the real spec still extracts.
        paths = verify_paths._extract_paths_from_command(
            "bun --config bunfig.toml test a.test.ts"
        )
        self.assertEqual(paths, {"a.test.ts"})
        self.assertNotIn("bunfig.toml", paths)

    def test_two_leading_flags_still_yield_no_false_path(self):
        """A single-flag skip leaves the SECOND flag in the binary slot, so
        its path-shaped value lands in the scanned region and is extracted.

        `--bail --config bunfig.toml` is the shape: skip one flag, consume
        `--config` as "the binary", and `bunfig.toml` is then a plain
        positional. A false positive demands a file that can never be
        touched — strictly worse than the sentinel — so the skip has to
        consume EVERY leading flag, not just the first.
        """
        paths = verify_paths._extract_paths_from_command(
            "bun --bail --config bunfig.toml test a.test.ts"
        )
        self.assertEqual(paths, {"a.test.ts"})
        self.assertNotIn("bunfig.toml", paths)


class TestBunScriptAliasWholeTree(unittest.TestCase):
    def test_bun_run_test_whole_tree(self):
        self.assertEqual(
            verify_paths.classify_path_strategy("bun run test"), "whole_tree"
        )
        self.assertEqual(
            verify_paths._extract_paths_from_command("bun run test"), {"."}
        )

    def test_bun_colon_script_whole_tree(self):
        self.assertEqual(
            verify_paths.classify_path_strategy("bun test:unit"), "whole_tree"
        )
        self.assertEqual(
            verify_paths._extract_paths_from_command("bun test:unit"), {"."}
        )

    def test_bun_filter_run_test_whole_tree(self):
        self.assertEqual(
            verify_paths.classify_path_strategy("bun --filter @legacy/db run test"),
            "whole_tree",
        )
        self.assertEqual(
            verify_paths._extract_paths_from_command(
                "bun --filter @legacy/db run test"
            ),
            {"."},
        )


class TestBunFilterFlagNeverReadAsPath(unittest.TestCase):
    def test_bun_filter_test_sentinel_no_package_name(self):
        # Positional strategy (bun IS the direct binary here), but the
        # package name after --filter must never surface as a path — a false
        # positive is worse than the sentinel: it demands a file that can
        # never be touched.
        self.assertEqual(
            verify_paths.classify_path_strategy("bun --filter @legacy/db test"),
            "positional",
        )
        paths = verify_paths._extract_paths_from_command("bun --filter @legacy/db test")
        self.assertEqual(paths, {"."})
        self.assertNotIn("@legacy/db", paths)


class TestBunDocumentedLimitations(unittest.TestCase):
    def test_bun_space_form_coverage_flag_extracts_sentinel(self):
        # Deliberate, documented limitation: a space-form bare flag (no `=`)
        # consumes the following token as its value, same as
        # `npx jest --coverage a.test.js`. Not a regression to "fix".
        self.assertEqual(
            verify_paths._extract_paths_from_command("bun test --coverage a.test.ts"),
            {"."},
        )

    def test_bun_bareword_filter_pattern_falls_to_sentinel(self):
        # bun positionals are filter PATTERNS, not strict paths — a
        # bare-word pattern (no `/` or `.`) is not path-shaped.
        self.assertEqual(
            verify_paths._extract_paths_from_command("bun test loginFlow"),
            {"."},
        )


class TestChainedCommandRegressionPins(unittest.TestCase):
    """These pass today. They pin the rejected "anchor after `test`" rule's
    failure mode so it can never be silently reintroduced: applied to
    chained commands (not bun-only), it drops the first command's proof path
    when a later `run`/`test` token appears downstream of `&&`.
    """

    def test_jest_then_npm_run_build_keeps_jest_path(self):
        self.assertEqual(
            verify_paths._extract_paths_from_command(
                "npx jest src/a.test.js && npm run build"
            ),
            {"src/a.test.js"},
        )

    def test_vitest_then_npm_run_lint_keeps_vitest_path(self):
        self.assertEqual(
            verify_paths._extract_paths_from_command(
                "npx vitest tests/a.test.ts && npm run lint"
            ),
            {"tests/a.test.ts"},
        )

    def test_jest_then_playwright_keeps_both_paths(self):
        self.assertEqual(
            verify_paths._extract_paths_from_command(
                "npx jest src/a.test.js && npx playwright test e2e/b.spec.ts"
            ),
            {"src/a.test.js", "e2e/b.spec.ts"},
        )


if __name__ == "__main__":
    unittest.main()
