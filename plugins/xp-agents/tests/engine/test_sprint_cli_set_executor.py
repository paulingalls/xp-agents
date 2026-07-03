#!/usr/bin/env python3
"""Tests for sprint_cli.py `set-executor` — the value-or-null executor writer.

set-executor writes executor_model / executor_effort as value-or-null, but ONLY
for the flags that are provided (omitted → field untouched). That is how
/xp-assign Step 0 clears the executor_effort latch (debt c93c9745f5ed) via
`--effort ""` while preserving an executor_model a /xp-schedule pre-seed set.
Split out of test_sprint_cli_mutate.py to keep both files under the 500-line cap.
"""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from conftest import (
    _SMMTestCase,
    run_cli,
)
from conftest import (
    make_sprint_dict as _make_sprint,
)

_CLI = Path(__file__).parent.parent.parent / "smm" / "sprint_cli.py"


class TestSetExecutorCommand(_SMMTestCase):
    """set-executor writes a field only when its flag is PROVIDED (value-or-null:
    a provided-empty flag persists null). An OMITTED flag leaves the field
    untouched — so branch 6 can clear the executor_effort latch (debt
    c93c9745f5ed) via `--effort ""` while preserving an executor_model that
    /xp-schedule deliberately pre-seeded."""

    def _seed(self, **fields):
        sprint = _make_sprint()
        sprint["stories"][0].update(fields)
        (self.smm_dir / "sprint.json").write_text(json.dumps(sprint))

    def _story(self):
        return json.loads((self.smm_dir / "sprint.json").read_text())["stories"][0]

    def test_effort_only_clears_effort_and_preserves_preseeded_model(self):
        """Branch 6: `--effort ""` clears the effort latch; an OMITTED --model
        leaves a /xp-schedule pre-seeded executor_model intact."""
        self._seed(executor_model="haiku", executor_effort="high")
        result = run_cli(
            _CLI, ["set-executor", "story-001", "--effort", ""], self.smm_dir
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self._story()["executor_model"], "haiku")
        self.assertIsNone(self._story()["executor_effort"])

    def test_both_flags_write_value_or_null(self):
        """Branches 4/5: a decided tier plus effort are both persisted; a
        provided-empty --effort clears a stale effort (branch-5 reject)."""
        self._seed(executor_model="opus", executor_effort="high")
        result = run_cli(
            _CLI,
            ["set-executor", "story-001", "--model", "sonnet", "--effort", ""],
            self.smm_dir,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self._story()["executor_model"], "sonnet")
        self.assertIsNone(self._story()["executor_effort"])

    def test_omitted_effort_leaves_effort_untouched(self):
        """An omitted --effort does not touch the field (only provided flags write)."""
        self._seed(executor_effort="high")
        result = run_cli(
            _CLI, ["set-executor", "story-001", "--model", "opus"], self.smm_dir
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self._story()["executor_model"], "opus")
        self.assertEqual(self._story()["executor_effort"], "high")

    def test_provided_empty_model_clears_model(self):
        """A provided-empty --model explicitly clears the field to null."""
        self._seed(executor_model="opus")
        result = run_cli(
            _CLI, ["set-executor", "story-001", "--model", ""], self.smm_dir
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIsNone(self._story()["executor_model"])

    def test_valid_effort_persisted(self):
        """A known effort level is persisted."""
        self._seed()
        result = run_cli(
            _CLI, ["set-executor", "story-001", "--effort", "high"], self.smm_dir
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self._story()["executor_effort"], "high")

    def test_invalid_effort_rejected(self):
        """A non-empty --effort outside the known levels fails loud at write time
        (schema validation), leaving the story unchanged."""
        self._seed(executor_effort="high")
        result = run_cli(
            _CLI, ["set-executor", "story-001", "--effort", "turbo"], self.smm_dir
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self._story()["executor_effort"], "high")


if __name__ == "__main__":
    unittest.main()
