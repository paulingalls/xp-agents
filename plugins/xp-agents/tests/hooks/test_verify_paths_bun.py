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


class TestBunNarrowingRetreatsFailOpen(unittest.TestCase):
    """Every shape bun's positionals cannot be trusted in retreats to the
    sentinel, never to a path no commit can touch.

    bun positionals are substring FILTER PATTERNS, not repo-relative paths, so
    treating a path-shaped token as a proof file demands a file that may not
    exist — and an unsatisfiable required path is strictly worse than the
    sentinel it replaced, because the gate can then never go green. Each case
    below extracted a false path when bun first moved to positional
    extraction; the retreat restores exactly the whole-tree behaviour these
    commands had before, so no retreat can block a merge.
    """

    def test_dotted_filter_pattern_falls_to_sentinel(self):
        # `math.test` is a substring filter that RUNS `src/math.test.ts`; it
        # is not itself a file. Nothing lexical distinguishes it from a real
        # spec except that it carries no directory and no source extension.
        self.assertEqual(
            verify_paths._extract_paths_from_command("bun test math.test"),
            {"."},
        )

    def test_glob_pattern_falls_to_sentinel(self):
        self.assertEqual(
            verify_paths._extract_paths_from_command("bun test src/*.test.ts"),
            {"."},
        )

    def test_working_directory_flag_falls_to_sentinel(self):
        # The spec is relative to `packages/db`, but extraction compares
        # against repo-relative git output, so `src/a.test.ts` would never
        # match the committed `packages/db/src/a.test.ts`.
        self.assertEqual(
            verify_paths._extract_paths_from_command(
                "bun --cwd packages/db test src/a.test.ts"
            ),
            {"."},
        )

    def test_redirect_and_pipe_tail_falls_to_sentinel(self):
        # `test-output.log` is a build artifact, typically gitignored.
        self.assertEqual(
            verify_paths._extract_paths_from_command("bun test 2>&1 | tee out.log"),
            {"."},
        )

    def test_build_chain_never_demands_a_source_file(self):
        # No bun *test* runs here at all: the detector's flag gap spanned
        # `&&` and bound `bun` to the later `npm test`, then extraction
        # demanded the build entrypoint as proof.
        self.assertEqual(
            verify_paths._extract_paths_from_command(
                "bun build ./src/index.ts && npm test"
            ),
            {"."},
        )

    def test_dot_slash_spec_is_normalized(self):
        # bun's own docs use the `./`-prefixed form; git reports paths
        # repo-relative, so the two must be compared in one normal form.
        self.assertEqual(
            verify_paths._extract_paths_from_command("bun test ./src/db/x.test.ts"),
            {"src/db/x.test.ts"},
        )

    def test_the_story_shape_still_extracts(self):
        # The retreat must not swallow what the story exists to gate.
        self.assertEqual(
            verify_paths._extract_paths_from_command(
                "bun test packages/db/src/x.test.ts"
            ),
            {"packages/db/src/x.test.ts"},
        )

    def test_extensionless_directory_spec_still_extracts(self):
        self.assertEqual(
            verify_paths._extract_paths_from_command("bun test packages/db/tests"),
            {"packages/db/tests"},
        )


class TestBunChainedCommands(unittest.TestCase):
    """A chained bun command retreats to the sentinel.

    bun cannot be classified per-chain-segment without also re-homing the
    leading `cd <dir> &&` peel, which is a larger change than a close can
    carry. Until then a chain is not single-segment, so it fails OPEN — the
    behaviour these commands had before bun became positional. That is a
    deliberate coverage cost, not a fail-closed one: `TestChainedCommandRegres
    sionPins` below still pins that jest/vitest/playwright chains keep their
    paths, so the retreat is bun-scoped.
    """

    def test_bun_spec_then_npm_run_build_falls_to_sentinel(self):
        self.assertEqual(
            verify_paths._extract_paths_from_command(
                "bun test src/a.test.ts && npm run build"
            ),
            {"."},
        )

    def test_bun_spec_then_bun_run_build_falls_to_sentinel(self):
        self.assertEqual(
            verify_paths._extract_paths_from_command(
                "bun test src/a.test.ts && bun run build"
            ),
            {"."},
        )

    def test_bun_spec_then_bun_alias_script_falls_to_sentinel(self):
        self.assertEqual(
            verify_paths._extract_paths_from_command(
                "bun test src/a.test.ts && bun test:integration"
            ),
            {"."},
        )

    def test_alias_only_chain_stays_whole_tree(self):
        # No direct segment anywhere: still the sentinel, not a false path.
        self.assertEqual(
            verify_paths.classify_path_strategy("bun run test && npm run lint"),
            "whole_tree",
        )
        self.assertEqual(
            verify_paths._extract_paths_from_command("bun run test && npm run lint"),
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
