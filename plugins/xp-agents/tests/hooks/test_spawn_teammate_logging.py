#!/usr/bin/env python3
"""Tests for spawn_teammate.py forensic-log path scoping.

Teammate forensic logs must be namespaced by project so two xp-agents
sessions in different projects that spawn same-named teammates (e.g.
``worktree-story-001``) don't stomp on each other's ``/tmp`` log. Split
out of test_spawn_teammate.py (feature-cohesive; keeps that file under cap).
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))


class TestProjectScopedLogDir(unittest.TestCase):
    """The project-id is the directory that owns the SMM tree — SMM lives at
    ``${CLAUDE_PLUGIN_DATA}/{project-id}/smm/``, so ``smm_dir.parent.name``
    is the project-id. main() must route run_with_tee's log_dir there.
    """

    def test_helper_scopes_by_project_id(self):
        """project_log_dir embeds the smm-parent (project-id) so distinct
        projects get distinct dirs while a shared teammate name would still
        collide within a single project."""
        import spawn_teammate

        a = spawn_teammate.project_log_dir("/data/8e1f07eb0759/smm")
        b = spawn_teammate.project_log_dir("/data/deadbeefcafe/smm")

        self.assertEqual(a.name, "8e1f07eb0759")
        self.assertEqual(b.name, "deadbeefcafe")
        self.assertNotEqual(a, b, "different projects must not share a log dir")

    def test_helper_handles_trailing_slash_and_relative(self):
        """A trailing slash or relative smm-dir still resolves to the
        project-id, never to '' or '.'."""
        import spawn_teammate

        d = spawn_teammate.project_log_dir("/data/8e1f07eb0759/smm/")
        self.assertEqual(d.name, "8e1f07eb0759")

    def test_main_passes_project_scoped_log_dir(self):
        """main() forwards a project-scoped log_dir to run_with_tee rather
        than letting it default to the shared /tmp."""
        import tempfile
        from unittest.mock import patch

        import spawn_teammate

        captured = {}

        def capture_tee(cmd, *, cwd=None, env=None, stdin=None, name=None, **kw):
            captured["log_dir"] = kw.get("log_dir")

        smm_dir = "/tmp/plugindata/8e1f07eb0759/smm"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("test prompt")
            prompt_path = f.name

        try:
            with (
                patch.object(spawn_teammate, "create_worktree", return_value="/tmp/wt"),
                patch.object(spawn_teammate, "run_with_tee", side_effect=capture_tee),
            ):
                spawn_teammate.main(
                    [
                        "--name",
                        "worktree-story-001",
                        "--smm-dir",
                        smm_dir,
                        "--prompt-file",
                        prompt_path,
                    ]
                )
            self.assertEqual(
                captured.get("log_dir"),
                spawn_teammate.project_log_dir(smm_dir),
                "main() must pass the project-scoped log_dir, not default /tmp",
            )
        finally:
            Path(prompt_path).unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
