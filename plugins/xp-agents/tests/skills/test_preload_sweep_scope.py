#!/usr/bin/env python3
"""The preload temp-file sweep must not delete a CROSS-STEP artifact.

`_preload_base.sh` clears stale render tempfiles on every preload run. That is
right for artifacts consumed by the same skill invocation that emitted them,
and wrong for `.system-context-rendered.*`, which a close emits at Step 0 and
hands to the close-reviewer at Step 4.5 — with `/xp-quality-review` running in
between, whose preload sources `_preload_base.sh`.

Sweeping that pattern therefore deleted the reviewer's own input before it was
read, on every close where `RUN_FULL_CODE_REVIEW=true`. It failed SILENTLY:
`xp-close-reviewer.md` branches on the SYSTEM_CONTEXT_RENDERED line being
absent, not on the named file being gone, so the agent reviewed with no
conventions, branching or principles and said nothing.

Observed live in sprint-003's own close, by the reviewer noticing its input was
missing and tracing why.
"""

import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from conftest import _PLUGIN_ROOT

_SWEPT = re.compile(r'-name "(\.[a-z-]+\.\*)"')


class TestPreloadSweepScope(unittest.TestCase):
    def setUp(self):
        self.source = (_PLUGIN_ROOT / "skills" / "_preload_base.sh").read_text()
        sweep = [
            line
            for line in self.source.splitlines()
            if line.startswith("find ") and "-exec rm -f" in line
        ]
        self.assertEqual(
            len(sweep), 1, "expected exactly one temp-file sweep in _preload_base.sh"
        )
        self.patterns = set(_SWEPT.findall(sweep[0]))

    def test_system_context_render_is_not_swept(self):
        """The cross-step artifact must survive an intervening preload."""
        self.assertNotIn(
            ".system-context-rendered.*",
            self.patterns,
            "the close-reviewer's SYSTEM_CONTEXT_RENDERED input is emitted at "
            "Step 0 and read at Step 4.5; a preload sourcing this file runs in "
            "between, so sweeping the pattern hands the reviewer a dead path "
            "and it reviews with no system context, silently",
        )

    def test_the_sweep_still_covers_same_invocation_artifacts(self):
        """Guard the other direction: this must not become a no-op sweep.

        Deleting the whole `find` would also pass the test above, so pin the
        patterns that ARE safe to clear — each is emitted and consumed inside
        one skill invocation.
        """
        self.assertEqual(
            self.patterns,
            {".smm-rendered.*", ".sprint-rendered.*", ".sprint-review-input.*"},
            "sweep scope changed; a pattern added here must be consumed by the "
            "same invocation that emits it, or it repeats the dead-path bug",
        )


if __name__ == "__main__":
    unittest.main()
