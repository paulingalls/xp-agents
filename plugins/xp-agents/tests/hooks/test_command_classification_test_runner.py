#!/usr/bin/env python3
"""Tests for command classification: test-runner detection.

Pure parsing tests — no SMM state needed. Split from test_bash_parsing.py
(story-008) when that file crossed the 500-line cap, then split again from
test_command_classification.py (was 510 lines) when IT crossed the cap.
Git-commit detection lives in test_command_classification_git_commit.py.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import test_parsing


class TestIsTestRun(unittest.TestCase):
    def test_pytest(self):
        self.assertEqual(test_parsing.is_test_run("pytest"), "pytest")

    def test_python_m_pytest(self):
        self.assertEqual(test_parsing.is_test_run("python -m pytest"), "pytest")

    def test_python3_m_pytest(self):
        self.assertEqual(test_parsing.is_test_run("python3 -m pytest"), "pytest")

    def test_jest(self):
        self.assertEqual(test_parsing.is_test_run("npx jest"), "jest")

    def test_jest_bare(self):
        self.assertEqual(test_parsing.is_test_run("jest"), "jest")

    def test_go_test(self):
        self.assertEqual(test_parsing.is_test_run("go test ./..."), "go")

    def test_not_test(self):
        self.assertIsNone(test_parsing.is_test_run("ls -la"))

    def test_npm_test(self):
        self.assertEqual(test_parsing.is_test_run("npm test"), "jest")

    def test_bun_run_test_alias(self):
        self.assertEqual(test_parsing.is_test_run("bun run test:e2e:web"), "bun")

    def test_bun_run_test_bare(self):
        self.assertEqual(test_parsing.is_test_run("bun run test"), "bun")

    def test_npm_run_test_alias(self):
        self.assertEqual(test_parsing.is_test_run("npm run test:unit"), "jest")

    def test_pnpm_run_test_alias(self):
        self.assertEqual(test_parsing.is_test_run("pnpm run test:e2e"), "jest")

    def test_pnpm_test_shorthand(self):
        # pnpm v6+ allows `pnpm <script>` without `run`
        self.assertEqual(test_parsing.is_test_run("pnpm test:unit"), "jest")

    def test_yarn_test_alias(self):
        self.assertEqual(test_parsing.is_test_run("yarn test:ci"), "jest")

    def test_yarn_run_test_alias(self):
        self.assertEqual(test_parsing.is_test_run("yarn run test:ci"), "jest")

    def test_playwright_bare(self):
        self.assertEqual(test_parsing.is_test_run("playwright test"), "playwright")

    def test_playwright_npx(self):
        self.assertEqual(test_parsing.is_test_run("npx playwright test"), "playwright")

    def test_playwright_bunx(self):
        self.assertEqual(test_parsing.is_test_run("bunx playwright test"), "playwright")

    def test_playwright_pnpm_exec(self):
        self.assertEqual(
            test_parsing.is_test_run("pnpm exec playwright test"), "playwright"
        )

    def test_playwright_yarn_priority(self):
        # `yarn playwright test` must match playwright, not the yarn script alias.
        self.assertEqual(test_parsing.is_test_run("yarn playwright test"), "playwright")

    def test_not_bun_run_build(self):
        self.assertIsNone(test_parsing.is_test_run("bun run build"))

    def test_not_npm_run_start(self):
        self.assertIsNone(test_parsing.is_test_run("npm run start"))

    def test_not_playwright_install(self):
        self.assertIsNone(test_parsing.is_test_run("playwright install"))


class TestIsTestRunWorkspaceFlags(unittest.TestCase):
    """Workspace runners with intervening flags between runner and `test`.

    Bun/pnpm/yarn/turbo/nx/lerna all permit `<runner> <flags...> [run] <script>`.
    The bounded lazy-quantifier pattern tolerates up to 5 intervening tokens.
    """

    # --- bun --filter (the reported bug) ---

    def test_bun_filter_test(self):
        # Reported: bun --filter @aje-poc/perf-harness test
        self.assertEqual(
            test_parsing.is_test_run("bun --filter @aje-poc/perf-harness test"),
            "bun",
        )

    def test_bun_filter_test_chained_scope(self):
        # Reported: bun --filter aje-poc-astro test:acceptance:live
        self.assertEqual(
            test_parsing.is_test_run("bun --filter aje-poc-astro test:acceptance:live"),
            "bun",
        )

    def test_bun_filter_test_with_double_dash(self):
        # vitest positional file pattern: bun --filter X test -- spawn_test
        self.assertEqual(
            test_parsing.is_test_run(
                "bun --filter @aje-poc/perf-harness test -- spawn_test"
            ),
            "bun",
        )

    # --- pnpm filter ---

    def test_pnpm_filter_test(self):
        self.assertEqual(test_parsing.is_test_run("pnpm --filter mypkg test"), "jest")

    def test_pnpm_filter_short_test(self):
        self.assertEqual(test_parsing.is_test_run("pnpm -F mypkg test"), "jest")

    def test_pnpm_recursive_test(self):
        self.assertEqual(test_parsing.is_test_run("pnpm -r test"), "jest")

    # --- yarn workspaces ---

    def test_yarn_workspace_test(self):
        self.assertEqual(test_parsing.is_test_run("yarn workspace mypkg test"), "jest")

    def test_yarn_workspaces_foreach_run_test(self):
        self.assertEqual(
            test_parsing.is_test_run("yarn workspaces foreach run test"),
            "jest",
        )

    # --- turbo ---

    def test_turbo_run_test(self):
        self.assertEqual(test_parsing.is_test_run("turbo run test"), "turbo")

    def test_turbo_test_shorthand(self):
        self.assertEqual(test_parsing.is_test_run("turbo test"), "turbo")

    def test_turbo_run_test_filter(self):
        self.assertEqual(
            test_parsing.is_test_run("turbo run test --filter=mypkg"),
            "turbo",
        )

    def test_turbo_via_npx(self):
        self.assertEqual(test_parsing.is_test_run("npx turbo test"), "turbo")

    def test_turbo_via_pnpm(self):
        self.assertEqual(test_parsing.is_test_run("pnpm turbo test"), "turbo")

    # --- nx ---

    def test_nx_test_pkg(self):
        self.assertEqual(test_parsing.is_test_run("nx test mypkg"), "nx")

    def test_nx_run_pkg_test(self):
        self.assertEqual(test_parsing.is_test_run("nx run mypkg:test"), "nx")

    def test_nx_run_many_target_test(self):
        self.assertEqual(test_parsing.is_test_run("nx run-many --target=test"), "nx")

    def test_nx_run_many_targets_list(self):
        self.assertEqual(
            test_parsing.is_test_run("nx run-many --targets=test,build"),
            "nx",
        )

    # --- lerna ---

    def test_lerna_run_test(self):
        self.assertEqual(test_parsing.is_test_run("lerna run test"), "jest")

    def test_lerna_run_test_scope(self):
        self.assertEqual(
            test_parsing.is_test_run("lerna run test --scope=mypkg"), "jest"
        )

    # --- npx/bunx/pnpm-exec/yarn-dlx wrappers around runners ---

    def test_bunx_vitest(self):
        self.assertEqual(test_parsing.is_test_run("bunx vitest"), "vitest")

    def test_bunx_jest(self):
        self.assertEqual(test_parsing.is_test_run("bunx jest"), "jest")

    def test_bunx_mocha(self):
        self.assertEqual(test_parsing.is_test_run("bunx mocha"), "mocha")

    def test_pnpm_exec_vitest(self):
        self.assertEqual(test_parsing.is_test_run("pnpm exec vitest"), "vitest")

    def test_yarn_dlx_vitest(self):
        self.assertEqual(test_parsing.is_test_run("yarn dlx vitest"), "vitest")

    # --- direct runners (mocha, node, deno) ---

    def test_mocha_bare(self):
        self.assertEqual(test_parsing.is_test_run("mocha"), "mocha")

    def test_mocha_with_path(self):
        self.assertEqual(test_parsing.is_test_run("mocha test/spec.js"), "mocha")

    def test_npx_mocha(self):
        self.assertEqual(test_parsing.is_test_run("npx mocha"), "mocha")

    def test_node_test(self):
        self.assertEqual(test_parsing.is_test_run("node --test"), "node-test")

    def test_node_test_with_glob(self):
        self.assertEqual(
            test_parsing.is_test_run("node --test test/**/*.js"), "node-test"
        )

    def test_deno_test(self):
        self.assertEqual(test_parsing.is_test_run("deno test"), "deno")

    def test_deno_test_with_path(self):
        self.assertEqual(test_parsing.is_test_run("deno test src/"), "deno")

    # --- direct binary invocations (no npx/bunx prefix) ---

    def test_direct_binary_jest(self):
        self.assertEqual(test_parsing.is_test_run("./node_modules/.bin/jest"), "jest")

    def test_direct_binary_vitest(self):
        self.assertEqual(
            test_parsing.is_test_run("./node_modules/.bin/vitest"), "vitest"
        )

    def test_direct_binary_playwright(self):
        self.assertEqual(
            test_parsing.is_test_run("./node_modules/.bin/playwright test"),
            "playwright",
        )

    def test_direct_binary_mocha(self):
        self.assertEqual(test_parsing.is_test_run("node_modules/.bin/mocha"), "mocha")

    # --- non-JS monorepo flag-tolerance ---

    def test_mvn_with_pl(self):
        # mvn -pl <module> test
        self.assertEqual(test_parsing.is_test_run("mvn -pl core test"), "maven")

    def test_gradle_module_path(self):
        # ./gradlew :module:test
        self.assertEqual(test_parsing.is_test_run("./gradlew :module:test"), "gradle")

    def test_gradle_nested_module_path(self):
        self.assertEqual(
            test_parsing.is_test_run("./gradlew :api:server:test"), "gradle"
        )

    # --- Negative-shape tests (per-runner false-positive guards) ---

    def test_not_bun_filter_build(self):
        self.assertIsNone(test_parsing.is_test_run("bun --filter mypkg build"))

    def test_not_pnpm_filter_lint(self):
        self.assertIsNone(test_parsing.is_test_run("pnpm --filter mypkg lint"))

    def test_not_yarn_workspace_build(self):
        self.assertIsNone(test_parsing.is_test_run("yarn workspace mypkg build"))

    def test_not_turbo_run_lint(self):
        self.assertIsNone(test_parsing.is_test_run("turbo run lint"))

    def test_not_pnpm_exec_helper_test_fixture(self):
        # Reviewer concern: tool whose name contains 'test' shouldn't match.
        self.assertIsNone(
            test_parsing.is_test_run("pnpm exec helper test-fixture-builder")
        )

    def test_not_bun_build_test_extension_file(self):
        # Free-close reviewer concern: `bun build test.ts` (a build
        # invocation with an input file named test.ts) was satisfying
        # the (?![\w-]) lookahead because '.' is not a word/hyphen char.
        # Tightening to (?![\w.-]) rejects file extensions after `test`.
        self.assertIsNone(test_parsing.is_test_run("bun build test.ts"))

    def test_pnpm_install_test_blind_spot(self):
        # KNOWN LIMITATION: `pnpm install test` (install package "test")
        # currently matches because the 5-token flag-gap can't
        # syntactically distinguish flags (`--filter`) from subcommands
        # (`install`). Tightening would also reject `yarn workspace X
        # test` which IS a valid test invocation. Pinning the false
        # positive so a future "fix" considers the workspace trade-off.
        self.assertEqual(test_parsing.is_test_run("pnpm install test"), "jest")

    def test_not_lerna_run_build(self):
        self.assertIsNone(test_parsing.is_test_run("lerna run build"))

    def test_not_node_run_script(self):
        self.assertIsNone(test_parsing.is_test_run("node script.js"))

    def test_not_deno_run(self):
        self.assertIsNone(test_parsing.is_test_run("deno run app.ts"))

    # --- Bound verification (lazy-quantifier limit) ---

    def test_bun_within_5_tokens_matches(self):
        # 5 intervening tokens is the bound — should still match.
        self.assertEqual(test_parsing.is_test_run("bun a b c d e test"), "bun")

    def test_bun_beyond_5_tokens_no_match(self):
        # 6 intervening tokens exceeds the bound — should NOT match.
        self.assertIsNone(test_parsing.is_test_run("bun a b c d e f test"))


if __name__ == "__main__":
    unittest.main()
