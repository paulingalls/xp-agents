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

# Not unused: importing conftest installs the real-agent spawn backstop, which
# every module that touches spawn_teammate must load — pinned by
# test_no_test_can_spawn_a_real_agent. TestTeammateNameCannotEscapeTheNamespace
# drives spawn_teammate.main.
import conftest  # noqa: F401


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


class TestTeammateNameCannotEscapeTheNamespace(unittest.TestCase):
    """The sprint id was guarded against traversal; the NAME beside it was not.

    Both land in the same directory — the sprint id as the dir, the name as the
    filename — and the name is CLI input (`spawn_teammate --name`, authored by
    /xp-assign). It is joined RAW into five paths: the prompt file, the tee log,
    the worktree directory, `.story-assignment-<name>` and the in-place marker.
    The last two live inside the SMM dir, so a `../` in the name escapes the SMM
    tree, not merely the /tmp namespace.

    Refuse, don't sanitize: a silent rewrite resolves to a path the caller did
    not ask for, and the lead (which writes the prompt) and the spawn (which
    reads it) must meet at the SAME file.
    """

    ESCAPES = (
        "../../../etc/passwd",
        "../sibling-project",
        "a/b",
        "..",
        "",
    )

    def test_a_traversing_name_is_refused_by_the_prompt_path(self):
        import teammate_runner

        for name in self.ESCAPES:
            with self.subTest(name=name), self.assertRaises(ValueError):
                teammate_runner.project_prompt_path(
                    "/data/proj-a/smm", name, sprint_id="sprint-117"
                )

    def test_a_traversing_name_is_refused_at_the_spawn_boundary(self):
        """The boundary refusal is what covers the worktree dir and the two
        SMM-dir markers, which no leaf path builder sees. It must fire BEFORE any
        side effect — the same placement argument `load_prompt_for_story` makes.
        """
        import spawn_teammate

        for name in self.ESCAPES:
            with self.subTest(name=name), self.assertRaises(ValueError):
                spawn_teammate.main(["--name", name, "--smm-dir", "/data/proj-a/smm"])

    def test_a_real_teammate_name_is_untouched(self):
        """The control. The names production actually uses must pass through
        verbatim — a guard that rewrote them would break the lead/spawn rendezvous
        on the prompt path."""
        import teammate_runner

        for name in ("worktree-story-001", "worktree-story-042", "solo.teammate_1"):
            with self.subTest(name=name):
                self.assertEqual(teammate_runner.safe_name(name), name)


if __name__ == "__main__":
    unittest.main()
