#!/usr/bin/env python3
"""Detector-level tests for `framework_detect._FLAG_GAP`'s token class.

Separate from test_verify_paths_command_parsing.py because this is a claim
about DETECTION (`is_test_run`: which framework, if any, a command line runs),
not about path extraction. The distinction is load-bearing here: `is_test_run`
drives four hook paths that never touch verify paths at all — `bash_post_tool`,
`work_signals`, `test_attribution`, `bash_failure` — so a false positive
mis-attributes a test run that never happened, independently of any gate.

The gap is a bounded run of intervening tokens, admitting the flag-tolerant
forms real projects use (`mvn -pl core test`, `./gradlew :mod:test`). With a
bare `\\S+` a shell separator is just another token, so the run spans it and
one command's runner binds to a LATER command's `test`. Narrowing the class to
exclude `;&|` is what stops that, and it reaches every detector built on the
gap, not only bun's — which is why the ordinary forms are pinned here too.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

import framework_detect


class TestGapDoesNotBindAcrossSeparators(unittest.TestCase):
    def test_bun_build_then_npm_test_is_not_a_bun_run(self):
        """The shape that made the bun extractor demand a build entrypoint."""
        self.assertNotEqual(
            framework_detect.is_test_run("bun build ./src/index.ts && npm test"),
            "bun",
        )

    def test_turbo_build_then_unrelated_test_does_not_bind(self):
        self.assertNotEqual(
            framework_detect.is_test_run("turbo run build && echo test"),
            "turbo",
        )

    def test_maven_package_then_piped_grep_does_not_bind(self):
        self.assertNotEqual(
            framework_detect.is_test_run("mvn package | grep test"),
            "maven",
        )

    def test_gradle_assemble_then_semicolon_does_not_bind(self):
        self.assertNotEqual(
            framework_detect.is_test_run("./gradlew assemble ; echo test"),
            "gradle",
        )


class TestFlagToleranceSurvivesTheNarrowing(unittest.TestCase):
    """The narrowing must not cost the flag tolerance it sits inside."""

    def test_maven_module_flag(self):
        self.assertEqual(framework_detect.is_test_run("mvn -pl core test"), "maven")

    def test_gradle_module_task(self):
        self.assertEqual(framework_detect.is_test_run("./gradlew :mod:test"), "gradle")

    def test_npm_family_alias_is_claimed_by_the_jest_branch(self):
        # "jest", not "npm": that branch deliberately claims the
        # npm/pnpm/yarn/lerna script aliases too, which is why
        # classify_path_strategy needs a literal-`jest`-token check to tell
        # the alias form from the direct one.
        self.assertEqual(framework_detect.is_test_run("pnpm run test:unit"), "jest")

    def test_bun_filter_flag_still_detects(self):
        self.assertEqual(
            framework_detect.is_test_run("bun --filter @legacy/db test"), "bun"
        )

    def test_a_real_chained_test_run_is_still_detected(self):
        """Excluding separators must not blind the detector to a test that
        genuinely runs after one — the later segment matches on its own."""
        self.assertIsNotNone(framework_detect.is_test_run("npm run build && pytest"))


if __name__ == "__main__":
    unittest.main()
