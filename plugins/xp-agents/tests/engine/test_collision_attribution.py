#!/usr/bin/env python3
"""Attribution tests for the file_domain collision gate (story-009).

`sprint_save.introduced_collisions` decides which of the current collisions are
THIS write's fault so only those block. story-009 replaces the old domain-diff
proxy with a direct baseline-vs-current collision comparison (both sides
sister-expanded), closing two gaps the sprint-115 close /code-review found:

- Gap 1: a dependency edit that makes two shared-path stories concurrent was
  unattributed (no file_domain changed) and passed BOTH run() and edit_story.
- Gap 2: edit_story checked the RAW domain while run() sister-expands first, so a
  sister-test collision run() would block passed edit_story.

Both callers (run(), sprint_store.edit_story) share introduced_collisions, so
these tests drive it through both. A load-bearing regression test
(R6) guards against the false-positive block that naive one-side expansion causes.
"""

import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import sprint_save
import sprint_store
from conftest import _s, _SMMTestCase


def _sprint(stories):
    return {
        "sprint_id": "sprint-001",
        "goal": "t",
        "started": "2026-04-01",
        "milestone": "",
        "stories": stories,
    }


def _story(sid, path, **extra):
    s = _s(sid, sid, "ready")
    s["file_domain"] = [f"{path} — {sid}"]
    s.update(extra)
    return s


def _make_git_project(tmpdir: Path) -> None:
    # _resolve_project_root shells `git rev-parse --show-toplevel`, so a real init
    # is required (a bare .git/ won't satisfy it).
    subprocess.run(["git", "init", "-q", str(tmpdir)], check=True)


class TestDependencyEditConcurrencyAttribution(_SMMTestCase):
    """Gap 1: an edit that removes a dependency, making two shared-path stories
    concurrent, is a real collision this write introduced — caught via run()
    (R1) and via edit_story (R3). A benign dependency edit is not blocked (R5)."""

    def test_run_refuses_dependency_removal_that_creates_concurrency(self):  # R1
        # Baseline: B depends on A, so they are serialized and may share the path.
        sprint_store.save_sprint(
            self.smm_dir,
            _sprint(
                [
                    _story("story-001", "src/shared.py"),
                    _story("story-002", "src/shared.py", dependencies=["story-001"]),
                ]
            ),
        )
        # This write removes B's dependency -> A and B become concurrent -> collision.
        data = _sprint(
            [
                _story("story-001", "src/shared.py"),
                _story("story-002", "src/shared.py", dependencies=[]),
            ]
        )
        with self.assertRaises(ValueError) as ctx:
            sprint_save.run(data, self.smm_dir)
        msg = str(ctx.exception)
        self.assertIn("src/shared.py", msg)
        self.assertIn("story-001", msg)
        self.assertIn("story-002", msg)

    def test_edit_story_refuses_dependency_removal_that_creates_concurrency(self):  # R3
        sprint_store.save_sprint(
            self.smm_dir,
            _sprint(
                [
                    _story("story-001", "src/shared.py"),
                    _story("story-002", "src/shared.py", dependencies=["story-001"]),
                ]
            ),
        )
        # No file_domain in the update: the old gate (`if "file_domain" in updates`)
        # skipped it entirely; the new keyed gate fires on `dependencies`.
        with self.assertRaises(ValueError) as ctx:
            sprint_store.edit_story(self.smm_dir, "story-002", {"dependencies": []})
        msg = str(ctx.exception)
        self.assertIn("src/shared.py", msg)
        self.assertIn("story-001", msg)
        self.assertIn("story-002", msg)

    def test_benign_dependency_edit_without_collision_succeeds(self):  # R5
        # Disjoint domains: the dependency edit fires the gate but introduces no
        # collision, so it must not be falsely blocked.
        sprint_store.save_sprint(
            self.smm_dir,
            _sprint([_story("story-001", "src/a.py"), _story("story-002", "src/b.py")]),
        )
        sprint_store.edit_story(
            self.smm_dir, "story-002", {"dependencies": ["story-001"]}
        )
        story = sprint_store.get_story(self.smm_dir, "story-002")
        self.assertEqual(story["dependencies"], ["story-001"])


class _GitProjectSisterCase(_SMMTestCase):
    """Base for tests needing real sister-test expansion: a git project (so
    `_resolve_project_root` resolves), system_context.test_layout (so
    `_resolve_layout` resolves), and the contested-sister fixture on disk —
    `tests/test_foo_tools.py` matches BOTH `foo.py` and `foo_tools.py` stems, so
    run()'s auto-include injects it into any story owning either source."""

    def setUp(self):
        super().setUp()
        self._tmp = Path(tempfile.mkdtemp(prefix="story-009-"))
        self.addCleanup(lambda: subprocess.run(["rm", "-rf", str(self._tmp)]))
        _make_git_project(self._tmp)
        for rel in ("src/foo.py", "src/foo_tools.py", "tests/test_foo_tools.py"):
            p = self._tmp / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("x = 1")
        self._orig_cwd = Path.cwd()
        os.chdir(self._tmp)
        self.addCleanup(lambda: os.chdir(self._orig_cwd))
        from _system_context_fixtures import valid_doc, write_doc

        write_doc(
            self.smm_dir,
            valid_doc(test_layout={"convention": "python_pytest", "overrides": []}),
        )


class TestSisterExpandedAttribution(_GitProjectSisterCase):
    def test_edit_story_detects_sister_expanded_collision(self):  # R4 (Gap 2)
        # Baseline: A owns foo.py (its contested sister test_foo_tools.py is
        # auto-owned by A alone -> no collision); B owns a disjoint path.
        sprint_store.save_sprint(
            self.smm_dir,
            _sprint(
                [_story("story-001", "src/foo.py"), _story("story-002", "src/other.py")]
            ),
        )
        # Edit B's domain to foo_tools.py. RAW domains stay disjoint (foo.py vs
        # foo_tools.py) so the old raw check permits -- but after sister expansion
        # BOTH claim tests/test_foo_tools.py -> collision.
        with self.assertRaises(ValueError) as ctx:
            sprint_store.edit_story(
                self.smm_dir, "story-002", {"file_domain": ["src/foo_tools.py — b"]}
            )
        self.assertIn("tests/test_foo_tools.py", str(ctx.exception))

    def test_disjoint_add_does_not_falsely_block_on_unexpanded_baseline(self):  # R6
        # Baseline persisted UNEXPANDED (save_sprint bypasses sister discovery):
        # A owns foo.py, B owns foo_tools.py -> after expansion both claim the
        # contested tests/test_foo_tools.py (a pre-existing collision that lived
        # only in the *expanded* view, never on disk).
        sprint_store.save_sprint(
            self.smm_dir,
            _sprint(
                [
                    _story("story-001", "src/foo.py"),
                    _story("story-002", "src/foo_tools.py"),
                ]
            ),
        )
        # Add a disjoint story via run(). The pre-existing A/B contested-sister
        # collision must NOT be attributed to this write: naive one-side expansion
        # (current expanded, baseline raw) would see A "touched" and falsely block;
        # expanding both sides makes the collision present-in-both -> not introduced.
        data = _sprint(
            [
                _story("story-001", "src/foo.py"),
                _story("story-002", "src/foo_tools.py"),
                _story("story-003", "src/unrelated.py"),
            ]
        )
        sprint_save.run(data, self.smm_dir)  # must NOT raise
        self.assertTrue((self.smm_dir / "sprint.json").exists())


if __name__ == "__main__":
    import unittest

    unittest.main()
