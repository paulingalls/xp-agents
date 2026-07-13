#!/usr/bin/env python3
"""Tests for teammate_runner.py's /tmp namespace — the prompt/log path itself.

Split from test_teammate_runner.py, which owns the OTHER half of the module
(subprocess tee + liveness watchdog): the namespace is a pure path-resolution
concern with no subprocess in sight, and keeping both in one file pushed it
past the size cap. Split by feature, as the file-size convention prescribes.

The namespace answers "which file does a teammate's prompt/log live in", and it
is load-bearing for correctness, not just tidiness: the lead WRITES the prompt
to this path and the spawn READS from it, so a path that resolves two different
ways spawns a teammate on an empty — or worse, a stale — prompt.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))


class TestProjectDirSprintToken(unittest.TestCase):
    """_project_dir namespaces teammate files under project AND sprint.

    Story ids repeat across sprints exactly as teammate names repeat across
    projects, so the sprint id extends the same namespace. The token lands in a
    filesystem path, so it is sanitised here — the runner is the single source
    of truth for the namespace, and it must not trust its caller's string.
    """

    def test_sprint_token_extends_the_project_namespace(self):
        import teammate_runner

        without = teammate_runner.project_log_dir("/data/proj-a/smm", sprint_id=None)
        with_sprint = teammate_runner.project_log_dir(
            "/data/proj-a/smm", sprint_id="sprint-117"
        )
        self.assertEqual(with_sprint.parent, without)
        self.assertEqual(with_sprint.name, "sprint-117")

    def test_two_sprints_do_not_share_a_dir(self):
        import teammate_runner

        a = teammate_runner.project_prompt_path(
            "/data/proj-a/smm", "worktree-story-003", sprint_id="sprint-116"
        )
        b = teammate_runner.project_prompt_path(
            "/data/proj-a/smm", "worktree-story-003", sprint_id="sprint-117"
        )
        self.assertNotEqual(a, b)

    def test_traversal_in_the_token_cannot_escape_the_namespace(self):
        """A sprint id is schema-validated free text, not a path. `../..` in it
        would otherwise walk the prompt path out of /tmp/xp-agents-teammates
        and back into a sibling project — or into the SMM tree itself."""
        import teammate_runner

        escaped = teammate_runner.project_log_dir(
            "/data/proj-a/smm", sprint_id="../../etc"
        )
        self.assertIn(
            teammate_runner._LOG_ROOT / "proj-a",
            escaped.parents,
            f"sprint token escaped the per-project namespace: {escaped}",
        )
        self.assertNotIn("..", escaped.parts)

    def test_separators_collapse_to_one_segment(self):
        """Whatever survives sanitation is ONE path component. A token carrying
        any separator (posix, windows, or a NUL that would raise inside Path)
        must not silently deepen the namespace — the prompt would land in a dir
        the spawn never reads."""
        import teammate_runner

        base = teammate_runner.project_log_dir("/data/proj-a/smm", sprint_id=None)
        for junk in ("a/b", "a\\b", "a\0b", "sprint 117"):
            resolved = teammate_runner.project_log_dir(
                "/data/proj-a/smm", sprint_id=junk
            )
            self.assertEqual(
                resolved.parent,
                base,
                f"token {junk!r} deepened the namespace: {resolved}",
            )

    def test_empty_token_collapses_to_the_project_namespace(self):
        """A blank/whitespace token is no token — never a `/tmp/.../ /` dir."""
        import teammate_runner

        base = teammate_runner.project_log_dir("/data/proj-a/smm", sprint_id=None)
        for junk in ("", "   ", "..", "/"):
            self.assertEqual(
                teammate_runner.project_log_dir("/data/proj-a/smm", sprint_id=junk),
                base,
                f"junk token {junk!r} must collapse to the project namespace",
            )


if __name__ == "__main__":
    unittest.main()
