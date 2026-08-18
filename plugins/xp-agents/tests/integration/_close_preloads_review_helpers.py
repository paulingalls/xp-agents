#!/usr/bin/env python3
"""The Steps 4 / 4b review-reference mixin for the close-preload tests.

Split out of `_close_preloads_helpers.py` when adding this mixin pushed
that module past the 500-line cap. Not `test_`-prefixed, so discovery does
not collect it directly — it is only imported by the
`test_close_preloads_emit_shared*.py` siblings.
"""

from pathlib import Path

from _close_fixtures import _ClosePreloadCommonTests
from conftest import _extract_preload_var


class _ReviewPipelineAssertions(_ClosePreloadCommonTests):
    """Mixin asserting the Steps 4 / 4b review reference appears in stdout.

    Steps 4 (Security Review) and 4b (full code review) live in
    `scripts/_close_pipeline_review.md`, appended only by the modes that RUN
    them. Story-close defers both to its enclosing sprint-close and does not
    mix this in — `TestStoryClosePreloadEmitsShared` carries the inverse pin
    instead, so the two halves cannot both drift the same way.

    Shares `_ClosePreloadCommonTests` as a base with `_SharedPreloadAssertions`
    (for `_PRELOAD` / `_preload`); the MRO collapses the two, so the common
    preload assertions still run once per mode, not twice.

    Subclasses extend this PLUS `_SharedPreloadAssertions` and
    `_IntegrationTestCase`.
    """

    def test_emits_step4_security_review_skill_invocation(self):
        # Security Review is Step 4; the close-reviewer fork is Step 4.5.
        # Pin the heading + the exact Skill-tool invocation shape — args MUST
        # name "cumulative diff" so /security-review scopes correctly.
        result = self._preload()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(
            "### Step 4: Security Review",
            result.stdout,
            "preload must emit the Step 4 (Security Review) heading",
        )
        self.assertNotIn(
            "### Step 4.5: Security Review",
            result.stdout,
            "the review reference must NOT carry a `### Step 4.5: Security "
            "Review` heading — 4.5 is the close-reviewer fork",
        )
        self.assertIn(
            'Skill(skill: "security-review"',
            result.stdout,
            "Step 4 must invoke Skill(skill: 'security-review', args: ...)",
        )
        self.assertIn(
            "cumulative diff",
            result.stdout,
            "Step 4 args must scope to the cumulative diff",
        )

    def test_emits_step4b_full_code_review_heading(self):
        result = self._preload()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(
            "### Step 4b: Full code review (conditional)",
            result.stdout,
            "preload must emit the Step 4b (full code review) heading",
        )

    def test_the_emitted_step4b_carries_a_launch_that_runs(self):
        """The only end-to-end check on Step 4b, and the gap it closes.

        Every other assertion about this step reads the SOURCE file, so all of
        them pass equally against a launch literal that is well-formed and
        wrong — which is exactly what shipped: Step 4b named
        `Workflow({name: "code-review"})` for releases, that name is registered
        nowhere, and the one broad correctness pass silently did not run. No pin
        noticed, because every pin was checking that the string was present
        rather than that it was deliverable.

        This asserts the launch survives `cat` into the preload's own stdout,
        for each close mode that emits it. It still cannot execute the launch —
        but it fails if the reference file stops being emitted at all, which is
        the other way this step goes quiet.
        """
        result = self._preload()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(
            'Skill(skill: "code-review"',
            result.stdout,
            "preload must emit Step 4b's actual launch call, not just its "
            "heading — a heading with no launch is a step that reads as run",
        )
        self.assertNotIn(
            'Workflow({ name: "code-review"',
            result.stdout,
            "the emitted Step 4b must not name a workflow that is registered "
            "nowhere in the shipped build",
        )

    def test_emits_a_workflow_script_path_that_exists_on_disk(self):
        """The one check in the Step 4b wiring that is not a string comparison.

        Step 4b launches the broad review by PATH, and a path is the kind of
        value every other pin here calls green while it is wrong: the reference
        file is `cat`'d RAW into this stdout, so a `${CLAUDE_PLUGIN_ROOT}` in it
        reaches the reader literally — the shell expansions that work in that
        file work because they sit inside a Bash command, and a tool argument
        has no shell. The preload emits the resolved path instead, derived from
        BASH_SOURCE rather than from an env var that may not be set.

        Asserting the file is THERE is what makes this a behavioural check. A
        moved or renamed script leaves every "does the prose contain the
        string" assertion passing and the launch failing at dogfood time, which
        is the failure this whole branch exists to stop happening twice.
        """
        result = self._preload()
        self.assertEqual(result.returncode, 0, result.stderr)
        emitted = _extract_preload_var(result.stdout, "WORKFLOW_SCRIPT")
        self.assertIsNotNone(
            emitted, "a mode that runs Step 4b must emit WORKFLOW_SCRIPT"
        )
        assert emitted is not None
        self.assertNotIn(
            "$",
            emitted,
            "the emitted path must be already-resolved — an unexpanded "
            "variable reaches a tool argument as literal text",
        )
        path = Path(emitted)
        self.assertTrue(
            path.is_absolute(),
            f"WORKFLOW_SCRIPT must not depend on the reader's cwd: {emitted!r}",
        )
        self.assertTrue(
            path.is_file(),
            f"the emitted Workflow script does not exist: {emitted!r}",
        )

    def test_emits_step4_security_concern_metadata_kind(self):
        # Security findings file as concerns with metadata.kind=security
        # so the structural commit-link probe AND any future "filter by
        # source" query can distinguish them from quality blocks.
        result = self._preload()
        self.assertEqual(result.returncode, 0, result.stderr)
        for marker, why in (
            ('"kind":"security"', "metadata.kind=security"),
            (
                '"close_cycle_id":',
                "metadata.close_cycle_id (scopes the Step 6 count to this "
                "close cycle only)",
            ),
            (
                '"close_mode":',
                "metadata.close_mode (free|sprint|plan substituted by each "
                "close skill)",
            ),
        ):
            with self.subTest(marker=marker):
                self.assertIn(
                    marker,
                    result.stdout,
                    f"Step 4 append.sh template must include {why}",
                )

    def test_emits_step4_clean_separation_note(self):
        # Constraint: don't pass security findings to close-reviewer.
        # The template must explicitly tell the close skill not to fold
        # security into the reviewer prompt — security and quality are
        # independent review streams.
        result = self._preload()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(
            "clean separation",
            result.stdout,
            "Step 4 must explicitly call out clean-separation from xp-close-reviewer",
        )

    def test_appends_review_reference_before_the_shared_one(self):
        # Ordering is the whole reason the split is two `cat`s rather than a
        # heading filter: Step 4 must still reach the reader BEFORE Step 5.
        # Pinned on the emitted stdout (the reader's actual view) AND on the
        # source order, because a preload that appended them the other way
        # round would still contain both headings.
        result = self._preload()
        self.assertEqual(result.returncode, 0, result.stderr)
        step4_idx = result.stdout.find("### Step 4: Security Review")
        step5_idx = result.stdout.find("### Step 5: Present findings")
        self.assertGreater(step4_idx, -1, "preload must emit Step 4")
        self.assertGreater(step5_idx, -1, "preload must emit Step 5")
        self.assertLess(
            step4_idx,
            step5_idx,
            "Step 4 must precede Step 5 in the emitted context — append the "
            "review reference BEFORE the shared one",
        )

        source = self._PRELOAD.read_text()
        review_idx = source.find("_close_pipeline_review.md")
        shared_idx = source.find("_close_pipeline_shared.md")
        self.assertGreater(review_idx, -1, "preload must append the review reference")
        self.assertGreater(shared_idx, -1, "preload must append the shared reference")
        self.assertLess(
            review_idx,
            shared_idx,
            "preload must `cat` the review reference before the shared one",
        )
