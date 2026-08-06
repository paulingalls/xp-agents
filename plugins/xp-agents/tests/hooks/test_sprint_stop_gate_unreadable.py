#!/usr/bin/env python3
"""run()-level behaviour when sprint.json cannot be read.

Sibling to `TestSprintStopGateEarlyExits` in test_sprint_stop_gate.py, which is
a regression pin for this story and must stay unedited — hence a file of its
own rather than a cascade-suite entry, which would also mix a run()-level
early-exit with cascade-step concerns.

`load_sprint` already separates the two shapes: `None` for a missing file,
`SprintCorruptError` (a ValueError) for undecodable bytes / malformed JSON /
schema failure, and `OSError` for a symlinked path. Keeping missing and
unreadable apart is the whole point — collapsing them either fires the gate on
every project that has never run a sprint, or releases it on state no gate can
evaluate.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from conftest import _HookTestCase, _make_stop_input


class TestAnUnreadableSprintFiresRatherThanReleases(_HookTestCase):
    def _run(self):
        import sprint_stop_gate

        return sprint_stop_gate.run(_make_stop_input(), smm_dir=self.smm_dir)

    def test_malformed_json_fires(self):
        (self.smm_dir / "sprint.json").write_text("{not json at all")
        result = self._assert_not_none(self._run())
        self.assertIn("sprint.json", result)

    def test_schema_invalid_content_fires(self):
        """Parses as JSON, fails validation — the third corrupt shape, and the
        one a hand-edit actually produces."""
        (self.smm_dir / "sprint.json").write_text('{"stories": "not-a-list"}')
        result = self._assert_not_none(self._run())
        self.assertIn("sprint.json", result)

    def test_undecodable_bytes_fire(self):
        (self.smm_dir / "sprint.json").write_bytes(b"\xff\xfe\x00 not utf-8")
        result = self._assert_not_none(self._run())
        self.assertIn("sprint.json", result)

    def test_a_symlinked_sprint_fires(self):
        """`load_sprint` raises OSError, not SprintCorruptError, for this one —
        which is why the precedent in pre_tool_write catches both. Catching only
        the ValueError subclass leaves this shape raising out of the hook, and a
        hook that errors is a hook that released."""
        target = self.smm_dir / "elsewhere.json"
        target.write_text("{}")
        (self.smm_dir / "sprint.json").symlink_to(target)
        result = self._assert_not_none(self._run())
        self.assertIn("sprint.json", result)

    def test_a_missing_sprint_still_releases(self):
        """The mirror direction. Turning absence into a block would fire the
        gate on every project that has never run a sprint."""
        self.assertIsNone(self._run())

    def test_the_block_survives_a_deferral(self):
        """Every other message routes through `_deferred`, so a live teammate or
        a mid-review cycle releases it. Unreadable state is not something a busy
        session gets to stop caring about, so this one bypasses — asserted here
        rather than assumed, because the bypass is invisible from the outside."""
        import sprint_stop_gate

        (self.smm_dir / "sprint.json").write_text("{not json at all")
        original = sprint_stop_gate._deferred
        sprint_stop_gate._deferred = lambda *a, **k: True
        try:
            result = self._assert_not_none(self._run())
        finally:
            sprint_stop_gate._deferred = original
        self.assertIn("sprint.json", result)

    def test_a_deferral_still_suppresses_an_ordinary_block(self):
        """The control: the bypass above is specific to unreadable state, not a
        blanket removal of deferral. Without it, the test above would pass on a
        gate that had simply stopped deferring anything."""
        import sprint_stop_gate
        from conftest import SPRINT_REVIEWING_ONLY

        (self.smm_dir / "sprint.json").write_text(SPRINT_REVIEWING_ONLY)
        original = sprint_stop_gate._deferred
        sprint_stop_gate._deferred = lambda *a, **k: True
        try:
            result = self._run()
        finally:
            sprint_stop_gate._deferred = original
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
