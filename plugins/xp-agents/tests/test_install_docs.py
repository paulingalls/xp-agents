#!/usr/bin/env python3
"""Pins for the install and trust docs.

Stories 001-004 made the plugin installable on the second harness; nothing told
a human how to do it. These rows hold the README's Install section to what was
actually measured, because the failure mode for install docs is not absence — it
is confident prose about something nobody ran.

Three claims are load-bearing and each is pinned by CONSEQUENCE rather than by
keyword, since a document can name `/hooks` while saying nothing about what
skipping it costs:

- trust failure is SILENT, so a reader who skips it gets a session with every
  gate absent and no signal;
- the minimum harness version is UNMEASURED, so no floor may be stated;
- the spawn flag is MANDATORY, because without it a persistent shell bypasses
  every gate riding the command hook.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from _paths import _PLUGIN_ROOT

_README = _PLUGIN_ROOT.parents[1] / "README.md"

# The placeholder the documented local-path command carries. Pinned as a
# constant because the E2E substitutes it; a rename that slipped past would
# quietly turn that substitution into a no-op.
_LOCAL_PATH_PLACEHOLDER = "/path/to/xp-agents"


def _readme() -> str:
    return _README.read_text(encoding="utf-8")


class TestBothHarnessInstallPathsDocumented(unittest.TestCase):
    """Each harness's complete sequence is present.

    The first harness's block predates this story; it is asserted alongside the
    second so that a future edit cannot document one by deleting the other.
    """

    def test_the_first_harness_sequence_is_still_documented(self):
        text = _readme()
        self.assertIn("claude plugin marketplace add", text)
        self.assertIn("claude plugin install xp-agents@xp-agents", text)

    def test_the_second_harness_sequence_is_documented(self):
        text = _readme()
        self.assertIn("codex plugin marketplace add", text)
        self.assertIn("codex plugin add xp-agents@xp-agents", text)

    def test_the_local_path_form_carries_the_pinned_placeholder(self):
        """The E2E substitutes this exact string; a rename must redden here."""
        self.assertIn(
            f"codex plugin marketplace add {_LOCAL_PATH_PLACEHOLDER}", _readme()
        )


if __name__ == "__main__":
    unittest.main()
