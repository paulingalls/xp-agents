#!/usr/bin/env python3
"""Auto-merge condition 2 reads the event log deterministically (story-025).

Spike-016 decided condition 2 ("no Block-severity finding in the close
review") should be a deterministic `count-concerns --severity high` read,
mirroring condition 1's existing `count-classifications` block, instead of
LLM prose over a reviewer summary. This story:

1. Replaces the prose condition 2 in both close SKILLs with that read.
2. Closes the story-close Step 4.5b gap — a blocking finding found by
   `/xp-quality-review` in close context is now recorded as a tagged
   high-severity concern, so condition 2 is real on that path too (it
   previously "held vacuously" — no close-reviewer ran, no Block ever
   existed to check).

These tests pin the prose shape so a future edit can't silently
reintroduce the old non-deterministic check or the vacuous-gap gap.
"""

import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from conftest import _PLUGIN_ROOT, _split_frontmatter_body

_STORY_CLOSE = _PLUGIN_ROOT / "skills/xp-story-close/SKILL.md"
_FREE_CLOSE = _PLUGIN_ROOT / "skills/xp-free-close/SKILL.md"
_QUALITY_REVIEW = _PLUGIN_ROOT / "skills/xp-quality-review/SKILL.md"
_CODE_REVIEWER = _PLUGIN_ROOT / "agents/xp-code-reviewer.md"
_CLOSE_REVIEWER = _PLUGIN_ROOT / "agents/xp-close-reviewer.md"
_SHARED_PIPELINE = _PLUGIN_ROOT / "scripts/_close_pipeline_shared.md"


def _body(path: Path) -> str:
    _, body = _split_frontmatter_body(path.read_text())
    return body


class TestCloseSkillsDeterministicConditionTwo(unittest.TestCase):
    """Both close SKILLs read condition 2 via count-concerns, not prose."""

    @classmethod
    def setUpClass(cls):
        cls.story_close = _body(_STORY_CLOSE)
        cls.free_close = _body(_FREE_CLOSE)

    def test_story_close_condition_two_is_count_concerns_read(self):
        self.assertIn("count-concerns", self.story_close)
        self.assertIn("--severity high", self.story_close)
        self.assertIn("--cycle-id <CLOSE_CYCLE_ID>", self.story_close)
        self.assertIn("--since-ts <CLOSE_START_TS>", self.story_close)

    def test_free_close_condition_two_is_count_concerns_read(self):
        self.assertIn("count-concerns", self.free_close)
        self.assertIn("--severity high", self.free_close)
        self.assertIn("--cycle-id <CLOSE_CYCLE_ID>", self.free_close)
        self.assertIn("--since-ts <CLOSE_START_TS>", self.free_close)

    def test_story_close_no_old_prose_condition(self):
        self.assertNotIn("No Block-severity finding in Step 4.5", self.story_close)
        self.assertNotIn("survived", self.story_close)

    def test_free_close_no_old_prose_condition(self):
        self.assertNotIn("No Block-severity finding", self.free_close)
        self.assertNotIn("survived", self.free_close)

    def test_story_close_no_longer_holds_vacuously(self):
        """The 4.5b gap this story closes: condition 2 used to hold
        vacuously because no close-reviewer ran on that path. Now a
        blocking finding is recorded as a tagged high concern instead."""
        self.assertNotIn("holds vacuously", self.story_close)


class TestConcernCountIsScopedByCloseDiff(unittest.TestCase):
    """Every site that counts concerns for a merge decision must pass the close
    diff, or `--cycle-id` still counts an untagged concern about code this close
    never touched (concern 3542ad2915df — story-003's clean close was pushed to
    abort-recommended by an unrelated open defect in a sibling's domain).

    The engine flag alone changes nothing observable, so this pin is the
    load-bearing half: without it the engine suite would pass equally against
    prose that never passes the flag.
    """

    # Cwd-independent by construction: `<TARGET_BRANCH>...<CURRENT_BRANCH>`, not
    # `...HEAD`. At story-close the orchestrator's HEAD is the sprint branch, not
    # the story branch (same invariant close_common.py's diff-command documents).
    #
    # `--no-renames` (story-003): default rename detection reports only the NEW
    # path, so a concern naming the OLD path of a renamed file is dropped by the
    # very close that renamed it. `-z` (story-003): the only separator that
    # closes every git path-quoting escape (non-ASCII, `"`, `\`), not just the
    # non-ASCII one `core.quotepath=false` alone would close.
    _EXPECTED_DIFF = (
        "git diff --no-renames --name-only -z <TARGET_BRANCH>...<CURRENT_BRANCH>"
    )

    @classmethod
    def setUpClass(cls):
        cls.sites = {
            "story-close": _body(_STORY_CLOSE),
            "free-close": _body(_FREE_CLOSE),
            "shared-pipeline": _SHARED_PIPELINE.read_text(),
        }

    @staticmethod
    def _count_concerns_command(text: str) -> str:
        """The fenced command block(s) that compute HIGH_CONCERN_COUNT.

        Pinning the flag against the whole document would pass on the
        explanatory paragraph alone — every site also NAMES `--diff-paths -` in
        the prose beside its block, so dropping the flag from the command itself
        would leave the substring behind and the pin green.
        """
        blocks = re.findall(r"```bash\n(.*?)```", text, re.DOTALL)
        return "\n".join(b for b in blocks if "count-concerns" in b)

    def test_every_count_concerns_site_passes_diff_paths(self):
        for name, text in self.sites.items():
            with self.subTest(site=name):
                command = self._count_concerns_command(text)
                self.assertTrue(command, "no fenced count-concerns command found")
                self.assertIn("--diff-paths -", command)

    def test_every_site_pipes_the_cumulative_review_diff(self):
        for name, text in self.sites.items():
            with self.subTest(site=name):
                self.assertIn(self._EXPECTED_DIFF, self._count_concerns_command(text))

    def test_no_site_names_head_as_the_diff_head(self):
        """`...HEAD` would silently review the wrong branch at story-close."""
        for name, text in self.sites.items():
            with self.subTest(site=name):
                self.assertNotIn("--name-only <TARGET_BRANCH>...HEAD", text)

    def test_close_reviewer_no_longer_promises_untagged_always_counts(self):
        """The guarantee is now conditional. Agent prose asserting the old
        unconditional version would be a lie the code no longer backs."""
        body = _body(_CLOSE_REVIEWER)
        self.assertNotIn("an untagged concern is counted, never dropped", body)
        self.assertIn("--files", body)


class TestQualityReviewClosesCycleIdThreading(unittest.TestCase):
    """xp-quality-review threads an optional close cycle id into the
    reviewer prompt without changing the single-spawn invariant."""

    @classmethod
    def setUpClass(cls):
        cls.body = _body(_QUALITY_REVIEW)
        start = cls.body.index("## Step 2:")
        end = cls.body.index("## Step 3:")
        cls.step2 = cls.body[start:end]

    def test_step2_threads_close_cycle_id_conditionally(self):
        self.assertIn("## Close Cycle ID", self.step2)
        self.assertRegex(
            self.step2.lower(),
            r"(when|if)[^.]*close cycle id[^.]*(scope|supplied|present)",
            "Step 2 must state the section is added ONLY when a close "
            "cycle id is in scope",
        )

    def test_step2_omits_section_when_absent(self):
        self.assertRegex(
            self.step2.lower(),
            r"(none|absent|no)[^.]*close cycle id[^.]*omit",
            "Step 2 must state the section is omitted for per-commit "
            "review (no close cycle id)",
        )

    def test_single_spawn_invariant_unchanged(self):
        self.assertEqual(
            self.body.count("Agent("),
            1,
            "Threading the close cycle id must not add a second spawn",
        )


class TestCodeReviewerClosesCloseContextRule(unittest.TestCase):
    """xp-code-reviewer.md's close-context rule (mirrors xp-close-reviewer's
    Block recording) keyed on presence of a close cycle id."""

    @classmethod
    def setUpClass(cls):
        cls.body = _body(_CODE_REVIEWER)
        cls.lower = cls.body.lower()

    def test_rule_keys_on_close_cycle_id_section(self):
        self.assertIn("## Close Cycle ID", self.body)

    def test_rule_states_high_severity_and_close_cycle_id_metadata(self):
        self.assertRegex(
            self.lower,
            r"severity high[^.]*close_cycle_id|close_cycle_id[^.]*severity high",
            "The close-context rule must state BOTH the high-severity "
            "floor and the close_cycle_id metadata key",
        )

    def test_rule_states_per_commit_unchanged_when_section_absent(self):
        self.assertRegex(
            self.lower,
            r"absent[^.]*per-commit|per-commit[^.]*(unchanged|does not apply)",
            "The rule must pin the per-commit invariant: absent the "
            "section, recording is unchanged",
        )


if __name__ == "__main__":
    unittest.main()
