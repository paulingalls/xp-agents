#!/usr/bin/env python3
"""Pin: the teammate cadence render actually fires in production.

It was dead code: `main` passes `smm_dir=None` for every teammate by design, and
the render was gated on it. Removing the lead's hand-written copy without this
pin would leave a teammate learning its cadence at its FIRST COMMIT (concern
dc47698a5ad9).

Split out of `test_spawn_determinism.py` at 651 lines. The two classes are the
two sides of one contract — where the cadence dir comes from, and that the
production-shaped call renders the cadence and nothing else.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

import session_start
import smm_dir_resolve
from conftest import _HookTestCase, write_smm_fixture


class TestTeammateCadenceRenderActuallyFires(unittest.TestCase):
    """The cadence render was dead code in production: `main` passes
    smm_dir=None for every teammate by design, and the render was gated on it.
    Removing the lead's hand-written copy (phase 4) without this would leave a
    teammate learning its cadence at its FIRST COMMIT (concern dc47698a5ad9).

    Every os.environ patch below is a method-bounded `with` — the shape
    test_env_patch_cleanup_pin.py requires, since patch.dict's exit restores the
    whole mapping and an unbounded one would outlive tearDown.
    """

    def test_cadence_dir_falls_back_to_the_env_var(self):
        """smm_dir=None is the production teammate shape — it must still
        resolve a dir for the cadence read."""
        with (
            tempfile.TemporaryDirectory() as td,
            patch.dict(os.environ, {"SMM_DIR": td}),
        ):
            self.assertEqual(session_start._cadence_dir(None), Path(td))

    def test_cadence_dir_prefers_an_explicit_dir(self):
        with (
            tempfile.TemporaryDirectory() as explicit,
            tempfile.TemporaryDirectory() as from_env,
            patch.dict(os.environ, {"SMM_DIR": from_env}),
        ):
            self.assertEqual(session_start._cadence_dir(Path(explicit)), Path(explicit))

    def test_cadence_dir_is_none_without_the_env_var(self):
        """No dir known — render no cadence rather than deriving one, which
        would create and seed an SMM as a SessionStart side effect."""
        with patch.dict(os.environ):
            os.environ.pop("SMM_DIR", None)
            self.assertIsNone(session_start._cadence_dir(None))

    def test_cadence_dir_follows_a_relocation_pointer(self):
        """The handle is pinned at spawn and the tree can have moved since. A
        raw env read addresses the abandoned copy and renders ITS cadence —
        the split brain smm_dir_resolve.follow_migration_pointer exists to
        prevent, which the env branch must not opt out of."""
        with (
            tempfile.TemporaryDirectory() as old,
            tempfile.TemporaryDirectory() as new,
            patch.dict(os.environ, {"SMM_DIR": old}),
        ):
            (Path(old) / smm_dir_resolve.MIGRATION_POINTER).write_text(new + "\n")
            self.assertEqual(session_start._cadence_dir(None), Path(new))


class TestTeammateRenderIsCadenceOnly(_HookTestCase):
    """The two-sided contract `_cadence_dir` exists to serve, pinned on the
    function production actually calls.

    The dead-code defect survived because every teammate pin passed an explicit
    `smm_dir` — the shape production never uses. `_cadence_dir` unit tests do not
    close that: they cannot catch a re-gating of the render on the wrong
    variable. Both halves belong in ONE pin, because they pull opposite ways —
    the cadence must reach a teammate whose `smm_dir` is None, and the SMM render
    must NOT, since keeping the render out of a teammate's context is exactly why
    `main` passes None.
    """

    _TEAMMATE_CWD = "/home/user/project/.claude/worktrees/worktree-story-001/src"

    def _render(self) -> str:
        import session_start as ss

        data = {"session_id": "test", "source": "startup", "cwd": self._TEAMMATE_CWD}
        with patch.dict(os.environ, {"SMM_DIR": str(self.smm_dir)}):
            result = ss.run(data, smm_dir=None)
        self.assertIsNotNone(result, "teammate SessionStart rendered nothing")
        return result or ""

    def test_production_shape_still_renders_the_cadence(self):
        import markers

        write_smm_fixture(self.smm_dir, intent=[("Ship the widget", "goal")])
        markers.write_review_cadence(self.smm_dir, "story")
        self.assertIn("Review Cadence", self._render())

    def test_production_shape_does_not_leak_the_smm_render(self):
        write_smm_fixture(self.smm_dir, intent=[("Ship the widget", "goal")])
        self.assertNotIn("Ship the widget", self._render())


if __name__ == "__main__":
    unittest.main()


if __name__ == "__main__":
    unittest.main()
