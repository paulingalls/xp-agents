#!/usr/bin/env python3
"""Tests for scaffold_apply.py — idempotent re-apply / resume.

apply_plan is re-entrant: existing files_to_create targets are backed up
then handled by content — matching content is skipped (resume), divergent
content is overwritten (fresh apply). ApplyResult.resumed reports whether a
prior partial apply was resumed. Reuses `_plan`, `_ApplyTestBase` from the
sibling pipeline file.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

from scaffold_apply import apply_plan, validate_plan
from test_scaffold_apply_pipeline import _ApplyTestBase, _plan


class TestApplyPlanResume(_ApplyTestBase):
    def test_matching_content_skips_write_and_resumes(self) -> None:
        body = "export default 'hi';\n"
        target = self.repo / "tests/a.spec.ts"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")
        before = target.stat().st_mtime_ns
        plan = _plan(
            files_to_create=[
                {"path": "tests/a.spec.ts", "description": "x", "body": body}
            ]
        )
        result = apply_plan(plan, repo_root=self.repo)
        self._track_snapshot(result)
        self.assertTrue(result.ok)
        self.assertTrue(result.resumed)
        # unchanged: no rewrite
        self.assertEqual(target.read_text(encoding="utf-8"), body)
        self.assertEqual(target.stat().st_mtime_ns, before)

    def test_partial_existing_writes_only_missing(self) -> None:
        body_a = "A\n"
        body_b = "B\n"
        body_c = "C\n"
        (self.repo / "a.ts").write_text(body_a, encoding="utf-8")
        (self.repo / "b.ts").write_text(body_b, encoding="utf-8")
        plan = _plan(
            files_to_create=[
                {"path": "a.ts", "description": "a", "body": body_a},
                {"path": "b.ts", "description": "b", "body": body_b},
                {"path": "c.ts", "description": "c", "body": body_c},
            ]
        )
        result = apply_plan(plan, repo_root=self.repo)
        self._track_snapshot(result)
        self.assertTrue(result.ok)
        self.assertTrue(result.resumed)
        self.assertEqual((self.repo / "c.ts").read_text(encoding="utf-8"), body_c)

    def test_divergent_content_overwritten_not_resumed(self) -> None:
        target = self.repo / "a.ts"
        target.write_text("OLD\n", encoding="utf-8")
        plan = _plan(
            files_to_create=[{"path": "a.ts", "description": "a", "body": "NEW\n"}]
        )
        result = apply_plan(plan, repo_root=self.repo)
        self._track_snapshot(result)
        self.assertTrue(result.ok)
        self.assertFalse(result.resumed)
        self.assertEqual(target.read_text(encoding="utf-8"), "NEW\n")

    def test_divergent_create_target_backed_up_and_restored_on_failure(self) -> None:
        target = self.repo / "a.ts"
        target.write_text("ORIGINAL\n", encoding="utf-8")
        plan = _plan(
            files_to_create=[{"path": "a.ts", "description": "a", "body": "NEW\n"}],
            verify_cmd="false",
        )
        result = apply_plan(plan, repo_root=self.repo)
        self._track_snapshot(result)
        self.assertFalse(result.ok)
        self.assertTrue(result.reverted)
        # prior divergent content restored
        self.assertEqual(target.read_text(encoding="utf-8"), "ORIGINAL\n")

    def test_newly_created_file_unlinked_on_failure(self) -> None:
        plan = _plan(
            files_to_create=[{"path": "fresh.ts", "description": "f", "body": "X\n"}],
            verify_cmd="false",
        )
        result = apply_plan(plan, repo_root=self.repo)
        self._track_snapshot(result)
        self.assertFalse(result.ok)
        self.assertTrue(result.reverted)
        self.assertFalse((self.repo / "fresh.ts").exists())

    def test_binary_existing_target_treated_as_divergent(self) -> None:
        # An undecodable (binary) existing create-target must not crash the
        # read-compare; it counts as divergent and gets overwritten.
        target = self.repo / "a.ts"
        target.write_bytes(b"\xff\xfe\x00\x01")
        plan = _plan(
            files_to_create=[{"path": "a.ts", "description": "a", "body": "NEW\n"}]
        )
        result = apply_plan(plan, repo_root=self.repo)
        self._track_snapshot(result)
        self.assertTrue(result.ok)
        self.assertFalse(result.resumed)
        self.assertEqual(target.read_text(encoding="utf-8"), "NEW\n")

    def test_validate_plan_no_longer_refuses_existing_creates(self) -> None:
        (self.repo / "a.ts").write_text("anything\n", encoding="utf-8")
        plan = _plan(
            files_to_create=[{"path": "a.ts", "description": "a", "body": "b\n"}]
        )
        self.assertIsNone(validate_plan(plan, repo_root=self.repo))


if __name__ == "__main__":
    import unittest

    unittest.main()
