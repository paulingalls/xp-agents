#!/usr/bin/env python3
"""Tests for pre_tool_bash.py: decision-time nudges (open questions,
same-topic supersession).

Split from test_pre_tool_bash_gates.py -- keeps decision-time nudge tests
separate from the review-cycle/accept and branch-protection gates.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))


import pre_tool_bash
from conftest import (
    _HookTestCase,
    _make_bash_input,
    make_event,
)
from event_schema import EVENT_TYPE_DECISION, EVENT_TYPE_QUESTION

_COMMIT_CMD = "git commit -m 'test'"


class TestPreToolBashDecisionOpenQuestions(_HookTestCase):
    """Decision-time nudge: open-questions context injected when
    `append.sh --type decision` is invoked without metadata.resolves.
    """

    _APPEND = "bash /plugin/smm/append.sh"

    def _decision_cmd(self, *extra: str) -> str:
        return " ".join(
            [
                self._APPEND,
                "--type",
                "decision",
                "--topic",
                "foo",
                "--content",
                "bar",
                *extra,
            ]
        )

    def test_decision_without_resolves_lists_open_questions(self):
        """Decision append without --metadata lists each open question."""
        q_open = make_event(
            EVENT_TYPE_QUESTION,
            id="aaaaaaaaaaaa",
            topic="auth",
            content="Should refresh tokens rotate on every request?",
        )
        q_resolved = make_event(
            EVENT_TYPE_QUESTION,
            id="bbbbbbbbbbbb",
            topic="auth",
            content="Do we need SSO in v1?",
        )
        d_resolver = make_event(
            EVENT_TYPE_DECISION,
            id="cccccccccccc",
            topic="auth",
            content="No SSO in v1",
            metadata={"resolves": ["bbbbbbbbbbbb"]},
        )
        self._write_events([q_open, q_resolved, d_resolver])

        result = pre_tool_bash.run(
            _make_bash_input(command=self._decision_cmd()),
            smm_dir=self.smm_dir,
        )

        result = self._assert_not_none(result)
        self.assertIn("aaaaaaaaaaaa", result)
        self.assertIn("Should refresh tokens rotate", result)
        self.assertNotIn("bbbbbbbbbbbb", result)

    def test_decision_with_resolves_metadata_no_injection(self):
        """Decision append carrying --metadata resolves ... does not nudge."""
        q_open = make_event(
            EVENT_TYPE_QUESTION,
            id="aaaaaaaaaaaa",
            topic="auth",
            content="Should refresh tokens rotate on every request?",
        )
        self._write_events([q_open])

        # Shell-quoted JSON — mirrors how an agent composes the command.
        cmd = self._decision_cmd(
            "--metadata",
            "'" + '{"resolves":["aaaaaaaaaaaa"]}' + "'",
        )
        result = pre_tool_bash.run(
            _make_bash_input(command=cmd),
            smm_dir=self.smm_dir,
        )

        self.assertIsNone(result)

    def test_non_decision_append_no_injection(self):
        """Append of any non-decision type does not trigger the nudge."""
        q_open = make_event(
            EVENT_TYPE_QUESTION,
            id="aaaaaaaaaaaa",
            topic="auth",
            content="Should refresh tokens rotate?",
        )
        self._write_events([q_open])

        cmd = f"{self._APPEND} --type concern --content 'slow build' --severity medium"
        result = pre_tool_bash.run(
            _make_bash_input(command=cmd),
            smm_dir=self.smm_dir,
        )

        self.assertIsNone(result)

    def test_no_open_questions_no_injection(self):
        """Fast-path: zero open questions means no nudge on decision."""
        self._write_events([])
        result = pre_tool_bash.run(
            _make_bash_input(command=self._decision_cmd()),
            smm_dir=self.smm_dir,
        )
        self.assertIsNone(result)

    def test_quoted_decision_text_is_ignored(self):
        """'--type decision' inside a quoted --content must not trigger the nudge."""
        q_open = make_event(
            EVENT_TYPE_QUESTION,
            id="aaaaaaaaaaaa",
            topic="auth",
            content="Should refresh tokens rotate?",
        )
        self._write_events([q_open])

        cmd = (
            f"{self._APPEND} --type concern --content "
            '"discussed append.sh --type decision previously" --severity low'
        )
        result = pre_tool_bash.run(
            _make_bash_input(command=cmd),
            smm_dir=self.smm_dir,
        )

        self.assertIsNone(result)


class TestPreToolBashDecisionSameTopic(_HookTestCase):
    """Decision-time nudge: when emitting on a topic with an existing
    unresolved decision, suggest metadata.supersedes/.resolves. Mirrors
    the same-topic check in concern_conflicts.py's superseded-decision detector
    but fires PRE-write so the agent can declare supersedence inline.
    """

    _APPEND = "bash /plugin/smm/append.sh"

    def _decision_cmd(self, topic: str, *extra: str) -> str:
        return " ".join(
            [
                self._APPEND,
                "--type",
                "decision",
                "--topic",
                topic,
                "--content",
                "bar",
                *extra,
            ]
        )

    def test_unresolved_same_topic_decision_triggers_nudge(self):
        prior = make_event(
            EVENT_TYPE_DECISION,
            id="111111111111",
            topic="naming",
            content="Use camelCase",
        )
        self._write_events([prior])

        result = pre_tool_bash.run(
            _make_bash_input(command=self._decision_cmd("naming")),
            smm_dir=self.smm_dir,
        )

        result = self._assert_not_none(result)
        self.assertIn("111111111111", result)
        self.assertIn("naming", result)
        # Suggestion should mention both metadata keys to give the agent
        # the choice: supersedes (suppresses the flag) vs resolves
        # (also cascade-closes the prior decision).
        self.assertIn("supersedes", result)
        self.assertIn("resolves", result)

    def test_resolved_same_topic_decision_excluded_from_nudge(self):
        prior = make_event(
            EVENT_TYPE_DECISION,
            id="111111111111",
            topic="naming",
            content="camelCase",
        )
        superseder = make_event(
            EVENT_TYPE_DECISION,
            id="222222222222",
            topic="naming",
            content="snake_case",
            metadata={"resolves": ["111111111111"]},
        )
        self._write_events([prior, superseder])

        result = pre_tool_bash.run(
            _make_bash_input(command=self._decision_cmd("naming")),
            smm_dir=self.smm_dir,
        )

        # Prior was explicitly superseded; superseder is the open one.
        result = self._assert_not_none(result)
        self.assertIn("222222222222", result)
        self.assertNotIn("111111111111", result)

    def test_metadata_supersedes_suppresses_nudge(self):
        prior = make_event(
            EVENT_TYPE_DECISION,
            id="111111111111",
            topic="naming",
            content="camelCase",
        )
        self._write_events([prior])

        cmd = self._decision_cmd(
            "naming",
            "--metadata",
            "'" + '{"supersedes":["111111111111"]}' + "'",
        )
        result = pre_tool_bash.run(
            _make_bash_input(command=cmd),
            smm_dir=self.smm_dir,
        )

        self.assertIsNone(result)

    def test_metadata_resolves_suppresses_nudge(self):
        prior = make_event(
            EVENT_TYPE_DECISION,
            id="111111111111",
            topic="naming",
            content="camelCase",
        )
        self._write_events([prior])

        cmd = self._decision_cmd(
            "naming",
            "--metadata",
            "'" + '{"resolves":["111111111111"]}' + "'",
        )
        result = pre_tool_bash.run(
            _make_bash_input(command=cmd),
            smm_dir=self.smm_dir,
        )

        self.assertIsNone(result)

    def test_exempt_topic_no_nudge_even_with_unresolved_prior(self):
        """execution-mode is exempt: never nudge, even with unresolved priors.

        Mirrors concerns.py's SUPERSEDED_DECISION_EXEMPT_TOPICS — multiple
        decisions per session are part of the /xp-assign workflow, not
        silent supersession.
        """
        prior = make_event(
            EVENT_TYPE_DECISION,
            id="111111111111",
            topic="execution-mode",
            content="Solo",
        )
        self._write_events([prior])

        result = pre_tool_bash.run(
            _make_bash_input(command=self._decision_cmd("execution-mode")),
            smm_dir=self.smm_dir,
        )

        self.assertIsNone(result)

    def test_different_topic_no_nudge(self):
        prior = make_event(
            EVENT_TYPE_DECISION,
            id="111111111111",
            topic="auth",
            content="No SSO in v1",
        )
        self._write_events([prior])

        result = pre_tool_bash.run(
            _make_bash_input(command=self._decision_cmd("execution-mode")),
            smm_dir=self.smm_dir,
        )

        self.assertIsNone(result)

    def test_no_topic_arg_no_nudge(self):
        """Decision without --topic can't have same-topic precedent."""
        prior = make_event(
            EVENT_TYPE_DECISION,
            id="111111111111",
            topic="execution-mode",
            content="Solo",
        )
        self._write_events([prior])

        # Decision command without --topic flag.
        cmd = f"{self._APPEND} --type decision --content 'bar'"
        result = pre_tool_bash.run(
            _make_bash_input(command=cmd),
            smm_dir=self.smm_dir,
        )

        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
