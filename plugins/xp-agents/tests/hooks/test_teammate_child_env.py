#!/usr/bin/env python3
"""The environment a spawned teammate's child process actually receives.

Split from `test_spawn_teammate_bootstrap.py` (500 lines). Two things must be
true of the child env, and they pull in opposite directions:

  * SMM_DIR must arrive ABSOLUTE and normalized. The child's cwd is the new
    worktree, so a relative value would resolve against the wrong tree.
  * The lead's session id must NOT arrive. A teammate is its own session and the
    liveness signal is session-keyed, but `os.environ.copy()` carried it.

The second must not become a general env scrub, which is what makes these one
suite rather than two: each is the other's guard.
"""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

# Imported for its SIDE EFFECT as much as any symbol: conftest installs the
# suite-wide backstop that makes launching the real `claude` binary impossible
# (see test_no_test_can_spawn_a_real_agent.py, which PINS this import for every
# module that imports spawn_teammate). The rule is structural — importing the
# module that can spawn is the fact that matters, not how main() is reached.
import conftest  # noqa: F401
import spawn_teammate
from _bootstrap_fixtures import _BootstrapTestCase


class TestChildEnvSmmDirIsResolved(_BootstrapTestCase):
    """The SECOND leg of the same invariant the bootstrap resolves for.

    run_bootstrap resolves SMM_DIR because the child's cwd is the new
    worktree, so a relative/unnormalized value would resolve against it.
    The `claude` teammate spawned moments later runs with that SAME cwd off
    the SAME --smm-dir, so it needs the same resolution — a bootstrap that
    saw an absolute SMM_DIR followed by an agent whose every hook resolved a
    different one is exactly the split-brain the resolve was added to stop.
    """

    def test_teammate_env_smm_dir_is_absolute_and_normalized(self):
        from unittest.mock import patch

        captured: dict[str, dict[str, str]] = {}

        def capture_run(cmd, *args, **kwargs):
            captured["env"] = kwargs["env"]

        # Absolute but UNNORMALIZED: what the child resolves must not depend
        # on its cwd (a relative --smm-dir is the same bug, one os.getcwd()
        # further away).
        unresolved = str(self.smm_dir / ".." / self.smm_dir.name)

        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("test prompt")
            prompt_path = f.name

        try:
            with (
                patch.object(spawn_teammate, "create_worktree", return_value="/tmp/wt"),
                patch.object(spawn_teammate, "run_with_tee", side_effect=capture_run),
            ):
                spawn_teammate.main(
                    [
                        "--name",
                        "worktree-story-bootstrap",
                        "--smm-dir",
                        unresolved,
                        "--prompt-file",
                        prompt_path,
                    ]
                )
        finally:
            Path(prompt_path).unlink(missing_ok=True)

        seen = captured["env"]["SMM_DIR"]
        self.assertEqual(Path(seen), self.smm_dir.resolve())


class TestChildEnvDropsOurSessionId(_BootstrapTestCase):
    """A teammate is its own session and must not inherit the lead's id.

    `os.environ.copy()` carried it, and the liveness signal is session-keyed:
    writers key the marker on the id the harness hands each hook, the preload
    check keys it on these environment variables. A teammate carrying OUR id
    therefore reads a marker its own hooks never write — it either passes on the
    LEAD's heartbeat while its own runtime is broken, or refuses every skill
    preload once the lead goes idle while its hooks are demonstrably running.
    """

    def _child_env(self, *extra_args: str) -> dict[str, str]:
        from unittest.mock import patch

        captured: dict[str, dict[str, str]] = {}

        def capture_run(cmd, *args, **kwargs):
            captured["env"] = kwargs["env"]

        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("test prompt")
            prompt_path = f.name
        try:
            with (
                patch.object(spawn_teammate, "create_worktree", return_value="/tmp/wt"),
                patch.object(spawn_teammate, "run_with_tee", side_effect=capture_run),
            ):
                spawn_teammate.main(
                    [
                        "--name",
                        "worktree-story-bootstrap",
                        "--smm-dir",
                        str(self.smm_dir),
                        "--prompt-file",
                        prompt_path,
                        *extra_args,
                    ]
                )
        finally:
            Path(prompt_path).unlink(missing_ok=True)
        return captured["env"]

    def _dropped_candidates(self, *extra_args: str) -> None:
        import os as _os

        import hook_liveness

        candidates = hook_liveness.SESSION_ID_ENV_CANDIDATES
        leaked = dict.fromkeys(candidates, "the-leads-session")
        with patch.dict(_os.environ, leaked):
            env = self._child_env(*extra_args)
        for var in candidates:
            with self.subTest(var=var):
                self.assertNotIn(var, env)

    def test_every_session_id_candidate_is_dropped(self):
        self._dropped_candidates()

    def test_the_in_place_shape_is_launched_with_the_same_env(self):
        """The other spawn shape, asserted rather than argued from one call site.

        `coordination.has_active_teammates` skips an entry stamped with the
        READER's session id outright, and what makes that safe is that NO
        teammate can carry our id — which holds for the in-place shape only
        because it is launched with this same stripped environment. Today one
        `env` and one launch site make a divergence unexpressible; the day a
        second launch path appears, this row is what says so.
        """
        self._dropped_candidates("--in-place")

    def test_the_teammate_name_and_smm_dir_still_reach_the_child(self):
        """The drop must not become a general env scrub."""
        env = self._child_env()
        self.assertEqual(env["XP_TEAMMATE_NAME"], "worktree-story-bootstrap")
        self.assertEqual(Path(env["SMM_DIR"]), self.smm_dir.resolve())


if __name__ == "__main__":
    unittest.main()
