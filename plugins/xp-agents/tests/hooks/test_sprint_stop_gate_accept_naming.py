#!/usr/bin/env python3
"""Whether the accept message names a story nothing can check.

Sibling to test_sprint_stop_gate_unreadable.py and split out of the cascade
suite for the same reason: the cascade file answers "which cascade step fires",
this one answers "what does the step that fired say", and merging them pushed
that file to 468 of a 500-line cap the Constraints pillar asks us to stay well
clear of.

`conftest._STORY_BASE` carries NO `acceptance_execution`, so every shared
fixture and every bare `_s()` lands on the names-the-gap side. A gap assertion
written on those would pass just as well if the clause were appended
unconditionally — so every has-proof story here is built with an explicit
kwarg, and it is those pins, not the gap pins, that give the pairs meaning.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from conftest import _HookTestCase, _make_stop_input, _s, _sprint_json

_RUNNABLE = {"type": "pytest", "commands": ["pytest tests/ -q"]}
_MANUAL_WITH_STEPS = {"type": "manual", "steps": ["Read the doc against each AC."]}
_MANUAL_EMPTY = {"type": "manual"}


class TestTheGateDoesNotClaimProofItLacks(_HookTestCase):
    def _run(self, story):
        import sprint_stop_gate

        (self.smm_dir / "sprint.json").write_text(_sprint_json([story]))
        result = sprint_stop_gate.run(_make_stop_input(), smm_dir=self.smm_dir)
        return self._assert_not_none(result)

    def test_declared_runnable_proof_leaves_the_message_unchanged(self):
        import sprint_stop_gate

        result = self._run(
            _s("story-1", "t", "reviewing", acceptance_execution=_RUNNABLE)
        )
        self.assertEqual(result, sprint_stop_gate._ACCEPT_MESSAGE)
        self.assertNotIn("story-1", result)

    def test_a_manual_block_with_steps_is_declared_proof(self):
        import sprint_stop_gate

        result = self._run(
            _s("story-1", "t", "reviewing", acceptance_execution=_MANUAL_WITH_STEPS)
        )
        self.assertEqual(result, sprint_stop_gate._ACCEPT_MESSAGE)

    def test_no_acceptance_execution_at_all_is_named(self):
        result = self._run(_s("story-1", "t", "reviewing"))
        self.assertIn("story-1", result)
        self.assertIn("xp-accept", result)

    def test_a_manual_block_with_no_steps_is_named(self):
        """Schema-valid and declares nothing: `type` is the only required key,
        so this shape would read as proof if the check keyed on absence."""
        result = self._run(
            _s("story-1", "t", "reviewing", acceptance_execution=_MANUAL_EMPTY)
        )
        self.assertIn("story-1", result)

    def test_steps_that_declare_nothing_are_not_proof(self):
        """Every shape here is schema-valid — `steps` is validated as a list of
        strings, with no non-empty rule on the list or on any entry — so each
        reaches the predicate, and none gives /xp-accept anything to check."""
        for steps in ([], ["   "], ["", "\n\t"]):
            with self.subTest(steps=steps):
                result = self._run(
                    _s(
                        "story-1",
                        "t",
                        "reviewing",
                        acceptance_execution={"type": "manual", "steps": steps},
                    )
                )
                self.assertIn("story-1", result)

    def test_the_predicate_survives_a_step_the_schema_would_reject(self):
        """Called directly: a non-string step cannot reach here through `run`
        (validation raises first), so the guard that keeps `.strip()` off a
        non-string is only reachable at this level. It stays because an
        exception inside a Stop hook is a silent RELEASE — the failure this
        gate's second change exists to close."""
        import sprint_stop_gate

        self.assertFalse(
            sprint_stop_gate._has_checkable_proof(
                {"acceptance_execution": {"type": "manual", "steps": [None, 7]}}
            )
        )

    def test_only_the_storyless_ones_are_named(self):
        import sprint_stop_gate

        (self.smm_dir / "sprint.json").write_text(
            _sprint_json(
                [
                    _s("story-1", "t", "reviewing", acceptance_execution=_RUNNABLE),
                    _s("story-2", "t", "reviewing"),
                ]
            )
        )
        result = sprint_stop_gate.run(_make_stop_input(), smm_dir=self.smm_dir)
        result = self._assert_not_none(result)
        self.assertIn("story-2", result)
        self.assertNotIn("story-1", result)

    def test_a_done_story_without_proof_is_not_named(self):
        """Only the stories that FIRED the branch are named. A done story has
        left the accept window and is nobody's outstanding proof."""
        import sprint_stop_gate

        (self.smm_dir / "sprint.json").write_text(
            _sprint_json(
                [
                    _s("story-1", "t", "reviewing", acceptance_execution=_RUNNABLE),
                    _s("story-2", "t", "done"),
                ]
            )
        )
        result = sprint_stop_gate.run(_make_stop_input(), smm_dir=self.smm_dir)
        result = self._assert_not_none(result)
        self.assertNotIn("story-2", result)

    def test_the_recorded_false_accept_shape_is_named(self):
        """AC-3: the shape both recorded false accepts ran through — in-progress
        plus the ACCEPT marker plus work, not the under-acceptance branch.
        Varying acceptance_execution alone never reaches this path."""
        import sprint_stop_gate

        (self.smm_dir / "sprint.json").write_text(
            _sprint_json([_s("story-5", "t", "in-progress")])
        )
        (self.smm_dir / ".accept").write_text("done")
        result = sprint_stop_gate.run(_make_stop_input(), smm_dir=self.smm_dir)
        result = self._assert_not_none(result)
        self.assertIn("story-5", result)

    def test_that_same_path_is_unchanged_when_proof_exists(self):
        import sprint_stop_gate

        (self.smm_dir / "sprint.json").write_text(
            _sprint_json(
                [_s("story-5", "t", "in-progress", acceptance_execution=_RUNNABLE)]
            )
        )
        (self.smm_dir / ".accept").write_text("done")
        result = sprint_stop_gate.run(_make_stop_input(), smm_dir=self.smm_dir)
        self.assertEqual(result, sprint_stop_gate._IN_PROGRESS_ACCEPT_MESSAGE)

    def test_a_done_story_is_not_named_by_the_in_progress_branch_either(self):
        """The scope pin for the SECOND branch. Its sibling above pins the
        under-acceptance branch; without this one, widening only the in-progress
        filter to the whole sprint passes the whole suite — every other pin on
        that path carries a single story, where `all stories` and `the firing
        stories` are the same list."""
        import sprint_stop_gate

        (self.smm_dir / "sprint.json").write_text(
            _sprint_json(
                [
                    _s("story-1", "t", "done"),
                    _s("story-2", "t", "in-progress", acceptance_execution=_RUNNABLE),
                ]
            )
        )
        (self.smm_dir / ".accept").write_text("done")
        result = sprint_stop_gate.run(_make_stop_input(), smm_dir=self.smm_dir)
        self.assertEqual(result, sprint_stop_gate._IN_PROGRESS_ACCEPT_MESSAGE)


class TestTheTwoBranchMessagesDiverge(_HookTestCase):
    """The under-acceptance and in-progress branches must say different
    things — a single shared constant would silently reunify them."""

    def test_the_under_acceptance_text_is_pinned_as_a_literal(self):
        """A literal, not a reference to the constant: comparing the result to
        `sprint_stop_gate._ACCEPT_MESSAGE` is self-referential and would still
        pass if the constant were renamed and reworded together."""
        import sprint_stop_gate

        story = _s("story-1", "t", "reviewing", acceptance_execution=_RUNNABLE)
        (self.smm_dir / "sprint.json").write_text(_sprint_json([story]))
        result = sprint_stop_gate.run(_make_stop_input(), smm_dir=self.smm_dir)
        self.assertEqual(
            result,
            "Stories need acceptance. Run /xp-accept to verify "
            "acceptance criteria before stopping.",
        )

    def test_the_two_base_constants_differ_and_the_in_progress_one_drops_the_claim(
        self,
    ):
        import sprint_stop_gate

        self.assertNotEqual(
            sprint_stop_gate._ACCEPT_MESSAGE,
            sprint_stop_gate._IN_PROGRESS_ACCEPT_MESSAGE,
        )
        self.assertNotIn(
            "before stopping", sprint_stop_gate._IN_PROGRESS_ACCEPT_MESSAGE
        )

    def test_the_in_progress_suffix_appends_to_the_in_progress_base(self):
        """The unprovable-story suffix logic is unchanged; prove it appends to
        the in-progress base too, not only to the under-acceptance one."""
        import sprint_stop_gate

        (self.smm_dir / "sprint.json").write_text(
            _sprint_json([_s("story-5", "t", "in-progress")])
        )
        (self.smm_dir / ".accept").write_text("done")
        result = sprint_stop_gate.run(_make_stop_input(), smm_dir=self.smm_dir)
        result = self._assert_not_none(result)
        base = sprint_stop_gate._IN_PROGRESS_ACCEPT_MESSAGE
        self.assertTrue(result.startswith(base))
        self.assertIn("story-5", result)


if __name__ == "__main__":
    unittest.main()
