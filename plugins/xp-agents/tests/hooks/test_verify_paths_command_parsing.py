#!/usr/bin/env python3
"""Tests for scripts/verify_paths.py.

The module codifies the harness path-parsing rules that previously lived
only as prose in agents/xp-plan-reviewer.md (§10b). It exposes:
- extract_verify_paths(story): the set of test-file paths a story's per-AC
  verify objects and story-level acceptance_execution point at.
- untouched_verify_paths(paths, cwd, base): the declared paths that no
  commit on base..HEAD touched (log-walk, so touch-then-revert still counts
  as touched).
- a CLI for the story-close preload.

Split from test_verify_paths.py for file size management. This file covers
the low-level command-parsing layer: `_extract_paths_from_command` and
`classify_path_strategy`. See test_verify_paths_extraction_and_git.py for
extract_verify_paths (story-dict extraction), untouched_verify_paths (the
git log-walk), and the CLI.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

import verify_paths

_VERIFY_PATHS = Path(__file__).parent.parent.parent / "scripts" / "verify_paths.py"


class TestExtractPathsFromCommand(unittest.TestCase):
    def test_pytest_strips_selector(self):
        self.assertEqual(
            verify_paths._extract_paths_from_command(
                "pytest tests/hooks/test_x.py::TestC::test_m"
            ),
            {"tests/hooks/test_x.py"},
        )

    def test_python_m_pytest_multiple_paths(self):
        self.assertEqual(
            verify_paths._extract_paths_from_command(
                "python -m pytest tests/a.py tests/b.py"
            ),
            {"tests/a.py", "tests/b.py"},
        )

    def test_pytest_flags_and_flag_args_ignored(self):
        # -x is a bare flag; -k consumes its expr argument — neither is a path.
        self.assertEqual(
            verify_paths._extract_paths_from_command("pytest -x -k expr tests/a.py"),
            {"tests/a.py"},
        )

    def test_unittest_discover_start_and_top_dirs(self):
        self.assertEqual(
            verify_paths._extract_paths_from_command(
                "python -m unittest discover -s tests/smm -t tests"
            ),
            {"tests/smm", "tests"},
        )

    def test_bare_unittest_discover_defaults_to_cwd(self):
        # No -s: unittest discovers from cwd. A recognized runner must not
        # yield an empty (silent-pass) set — map to "." (the whole tree).
        self.assertEqual(
            verify_paths._extract_paths_from_command("python -m unittest discover"),
            {"."},
        )

    def test_direct_python_script(self):
        self.assertEqual(
            verify_paths._extract_paths_from_command("python scripts/foo.py"),
            {"scripts/foo.py"},
        )

    def test_direct_bash_script(self):
        self.assertEqual(
            verify_paths._extract_paths_from_command("bash run.sh"),
            {"run.sh"},
        )

    def test_unrecognized_runner_yields_nothing(self):
        self.assertEqual(verify_paths._extract_paths_from_command("echo hello"), set())

    def test_runner_with_no_path_yields_nothing(self):
        self.assertEqual(verify_paths._extract_paths_from_command("pytest"), set())

    def test_cd_prefix_rebases_pytest_path(self):
        # Monorepo shape: a leading `cd <dir> &&` rebases the cd-relative path
        # to repo-relative so it matches git's repo-relative committed paths.
        self.assertEqual(
            verify_paths._extract_paths_from_command("cd apps/agent && pytest tests/"),
            {"apps/agent/tests/"},
        )

    def test_cd_prefix_strips_selector_then_rebases(self):
        self.assertEqual(
            verify_paths._extract_paths_from_command(
                "cd apps/agent && pytest tests/x.py::T::m"
            ),
            {"apps/agent/tests/x.py"},
        )

    def test_cd_prefix_leaves_whole_tree_sentinel(self):
        # A cd'd bare unittest discover still fails open — sentinel unprefixed.
        self.assertEqual(
            verify_paths._extract_paths_from_command(
                "cd apps/agent && python -m unittest discover"
            ),
            {"."},
        )

    def test_cd_trailing_slash_normalized(self):
        self.assertEqual(
            verify_paths._extract_paths_from_command("cd apps/agent/ && pytest tests/"),
            {"apps/agent/tests/"},
        )

    def test_cd_prefix_normalizes_parent_dir_escape(self):
        # A cross-package AC (`cd apps/agent && pytest ../shared/tests/`) rebases
        # to apps/agent/../shared/tests/ — normpath collapses the `..` to the
        # repo-relative apps/shared/tests/ (up one level from agent, into
        # shared) so it matches git's committed paths instead of failing closed.
        self.assertEqual(
            verify_paths._extract_paths_from_command(
                "cd apps/agent && pytest ../shared/tests/"
            ),
            {"apps/shared/tests/"},
        )


class TestClassifyPathStrategy(unittest.TestCase):
    """Verify-path extraction strategy per command.

    Load-bearing: `is_test_run` returns the same "jest" for `npm run test:e2e`
    (alias, no path) and `npx jest x.test.js` (direct, names a path). The alias
    form must map to "whole_tree" so `test:e2e` is never mis-read as a path;
    the direct form to "positional".

    bun has the same alias/direct split (`bun run test` vs. `bun test
    a.test.ts`), disambiguated differently since `bun` is the literal binary
    token in both forms — see test_verify_paths_bun.py for that cluster.
    `test_bun_run_test_whole_tree` below predates the split and stays
    unchanged here: the assertion was already true before bun grew a
    positional form to disambiguate from.
    """

    def test_npm_run_script_alias_whole_tree(self):
        self.assertEqual(
            verify_paths.classify_path_strategy("npm run test:e2e"), "whole_tree"
        )

    def test_pnpm_test_shorthand_whole_tree(self):
        self.assertEqual(
            verify_paths.classify_path_strategy("pnpm test:unit"), "whole_tree"
        )

    def test_pnpm_filter_test_whole_tree(self):
        self.assertEqual(
            verify_paths.classify_path_strategy("pnpm -F mypkg test"), "whole_tree"
        )

    def test_yarn_workspace_test_whole_tree(self):
        self.assertEqual(
            verify_paths.classify_path_strategy("yarn workspace mypkg test"),
            "whole_tree",
        )

    def test_lerna_run_test_whole_tree(self):
        self.assertEqual(
            verify_paths.classify_path_strategy("lerna run test"), "whole_tree"
        )

    def test_turbo_run_test_whole_tree(self):
        self.assertEqual(
            verify_paths.classify_path_strategy("npx turbo run test"), "whole_tree"
        )

    def test_nx_test_whole_tree(self):
        self.assertEqual(
            verify_paths.classify_path_strategy("nx test mypkg"), "whole_tree"
        )

    def test_bun_run_test_whole_tree(self):
        self.assertEqual(
            verify_paths.classify_path_strategy("bun run test"), "whole_tree"
        )

    def test_go_test_whole_tree(self):
        self.assertEqual(
            verify_paths.classify_path_strategy("go test ./pkg/..."), "whole_tree"
        )

    # --- direct binary invocations name a path on the CLI → positional ---

    def test_direct_npx_jest_positional(self):
        self.assertEqual(
            verify_paths.classify_path_strategy("npx jest x.test.js"), "positional"
        )

    def test_yarn_jest_positional(self):
        # `yarn jest x.test.js` runs the jest binary, not a `test` script.
        self.assertEqual(
            verify_paths.classify_path_strategy("yarn jest x.test.js"), "positional"
        )

    def test_pnpm_exec_playwright_positional(self):
        # `pnpm exec playwright test` resolves to playwright via is_test_run
        # precedence — a direct binary run, not a script alias.
        self.assertEqual(
            verify_paths.classify_path_strategy("pnpm exec playwright test spec.ts"),
            "positional",
        )

    def test_npx_playwright_positional(self):
        self.assertEqual(
            verify_paths.classify_path_strategy("npx playwright test specs/x.spec.mjs"),
            "positional",
        )

    def test_pytest_positional(self):
        self.assertEqual(
            verify_paths.classify_path_strategy("pytest tests/x.py"), "positional"
        )

    def test_unrecognized_none(self):
        self.assertEqual(verify_paths.classify_path_strategy("echo hello"), "none")


class TestExtractPositionalRunners(unittest.TestCase):
    """Non-Python positional-path runners name their proof file on the CLI.

    The generic extractor skips wrapper prefixes (npx/bunx/pnpm exec/yarn),
    the runner binary, and a leading test/run subcommand, then keeps only
    path-shaped positional tokens (containing `/` or `.`) — so a flag value
    like `--project chromium` or `-t renders` is never mis-read as a path.
    """

    def test_npx_playwright_names_spec(self):
        self.assertEqual(
            verify_paths._extract_paths_from_command(
                "npx playwright test specs/login.spec.mjs"
            ),
            {"specs/login.spec.mjs"},
        )

    def test_npx_jest_names_path(self):
        self.assertEqual(
            verify_paths._extract_paths_from_command("npx jest path/x.test.js"),
            {"path/x.test.js"},
        )

    def test_vitest_run_names_path(self):
        self.assertEqual(
            verify_paths._extract_paths_from_command("vitest run src/x.test.ts"),
            {"src/x.test.ts"},
        )

    def test_mocha_names_path(self):
        self.assertEqual(
            verify_paths._extract_paths_from_command("mocha test/x.js"),
            {"test/x.js"},
        )

    def test_node_test_names_path(self):
        self.assertEqual(
            verify_paths._extract_paths_from_command("node --test test/x.js"),
            {"test/x.js"},
        )

    def test_deno_test_names_dir(self):
        # Stored in normal form: extraction normalizes, so the trailing slash
        # is gone. Matching is unchanged — `_is_touched` appends the separator
        # itself when a declared dir lacks one — and this is the same form
        # `extract_verify_paths` already normalizes pins into, so a pin written
        # `src/` now cancels an extracted `src` instead of missing it.
        self.assertEqual(
            verify_paths._extract_paths_from_command("deno test src/"),
            {"src"},
        )

    def test_directory_declaration_still_matches_files_beneath_it(self):
        self.assertTrue(verify_paths._is_touched("src", {"src/a.py"}))
        self.assertTrue(verify_paths._is_touched("src/", {"src/a.py"}))
        self.assertFalse(verify_paths._is_touched("src", {"srcfoo/a.py"}))

    def test_rspec_names_path(self):
        self.assertEqual(
            verify_paths._extract_paths_from_command("rspec spec/x_spec.rb"),
            {"spec/x_spec.rb"},
        )

    def test_phpunit_names_path(self):
        self.assertEqual(
            verify_paths._extract_paths_from_command("phpunit tests/X.php"),
            {"tests/X.php"},
        )

    def test_mix_test_names_path(self):
        self.assertEqual(
            verify_paths._extract_paths_from_command("mix test test/x.exs"),
            {"test/x.exs"},
        )

    def test_jest_title_filter_value_not_a_path(self):
        # `-t renders` is a title filter; `renders` (no `/` or `.`) is not a
        # path and must not be extracted — only the spec is.
        self.assertEqual(
            verify_paths._extract_paths_from_command(
                'npx jest -t "renders" src/x.test.js'
            ),
            {"src/x.test.js"},
        )

    def test_playwright_project_flag_value_not_a_path(self):
        # `--project chromium` (space form): chromium is a value, not a path.
        self.assertEqual(
            verify_paths._extract_paths_from_command(
                "npx playwright test --project chromium specs/x.spec.ts"
            ),
            {"specs/x.spec.ts"},
        )

    def test_space_form_flag_with_path_shaped_value_not_a_path(self):
        # `--config jest.config.js` (space form): jest.config.js is path-shaped
        # but it is the flag's VALUE, not a proof file. Extracting it would
        # report the (untouched) config untouched → spurious gate firing, the
        # worst failure mode. Only the real spec must survive.
        self.assertEqual(
            verify_paths._extract_paths_from_command(
                "npx jest --config jest.config.js tests/x.test.js"
            ),
            {"tests/x.test.js"},
        )

    def test_space_form_reporter_path_value_not_a_path(self):
        self.assertEqual(
            verify_paths._extract_paths_from_command(
                "npx mocha --reporter ./r.js test/x.js"
            ),
            {"test/x.js"},
        )

    def test_attached_flag_value_still_extracts_following_path(self):
        # `--config=jest.config.js` (attached `=` form) consumes its own value,
        # so the following spec is NOT skipped.
        self.assertEqual(
            verify_paths._extract_paths_from_command(
                "npx jest --config=jest.config.js tests/x.test.js"
            ),
            {"tests/x.test.js"},
        )

    def test_pnpm_exec_playwright_wrapper(self):
        self.assertEqual(
            verify_paths._extract_paths_from_command(
                "pnpm exec playwright test specs/x.spec.ts"
            ),
            {"specs/x.spec.ts"},
        )

    def test_positional_runner_no_path_is_whole_tree(self):
        # Bare whole-suite run names no spec → sentinel, never empty (which
        # would silently disable the gate) and never blocking.
        self.assertEqual(
            verify_paths._extract_paths_from_command("npx playwright test"),
            {"."},
        )


class TestWholeTreeRunners(unittest.TestCase):
    """Script aliases / workspace / scheme-or-module runners name no CLI
    path → whole-tree sentinel (recognized, fail-open, never a silent
    no-binding). A script token like `test:e2e` is NOT a path."""

    def test_npm_run_script_alias_is_sentinel(self):
        result = verify_paths._extract_paths_from_command("npm run test:e2e")
        self.assertEqual(result, {"."})
        self.assertNotIn("test:e2e", result)

    def test_pnpm_filter_test_is_sentinel(self):
        self.assertEqual(
            verify_paths._extract_paths_from_command("pnpm -F pkg test"), {"."}
        )

    def test_yarn_workspace_test_is_sentinel(self):
        self.assertEqual(
            verify_paths._extract_paths_from_command("yarn workspace pkg test"), {"."}
        )

    def test_turbo_run_test_is_sentinel(self):
        self.assertEqual(
            verify_paths._extract_paths_from_command("npx turbo run test"), {"."}
        )

    def test_nx_test_is_sentinel(self):
        self.assertEqual(
            verify_paths._extract_paths_from_command("nx test mypkg"), {"."}
        )

    def test_cargo_test_is_sentinel(self):
        self.assertEqual(verify_paths._extract_paths_from_command("cargo test"), {"."})

    def test_maven_module_test_is_sentinel(self):
        self.assertEqual(
            verify_paths._extract_paths_from_command("mvn -pl mod test"), {"."}
        )

    def test_gradle_module_test_is_sentinel(self):
        self.assertEqual(
            verify_paths._extract_paths_from_command("./gradlew :mod:test"), {"."}
        )

    def test_go_test_is_sentinel(self):
        self.assertEqual(
            verify_paths._extract_paths_from_command("go test ./pkg/..."), {"."}
        )

    def test_unrecognized_command_stays_empty(self):
        self.assertEqual(verify_paths._extract_paths_from_command("echo hello"), set())

    def test_non_test_npm_script_stays_empty(self):
        self.assertEqual(
            verify_paths._extract_paths_from_command("npm run build"), set()
        )


class TestPositionalRunnerCdRebase(unittest.TestCase):
    def test_cd_prefix_rebases_playwright_spec(self):
        self.assertEqual(
            verify_paths._extract_paths_from_command(
                "cd apps/web && npx playwright test specs/x.spec.ts"
            ),
            {"apps/web/specs/x.spec.ts"},
        )

    def test_cd_prefix_leaves_sentinel_for_whole_suite(self):
        self.assertEqual(
            verify_paths._extract_paths_from_command(
                "cd apps/web && npx playwright test"
            ),
            {"."},
        )


if __name__ == "__main__":
    unittest.main()
