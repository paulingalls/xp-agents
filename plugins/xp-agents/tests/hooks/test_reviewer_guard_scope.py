#!/usr/bin/env python3
"""How many agents the reviewer guard covers, and which.

Split from test_pre_tool_bash_reviewer_guard.py, which sat at 499 lines against
a 499 ceiling and a 500 cap — one line of headroom — so this class could not
land beside the behaviour tests it complements.

The scope CLAIM is what lives here: the module argues its allowlist can stay
flat precisely because only the agents with recorded incidents are guarded. The
behaviour tests name specific unguarded agents; none of them notices a third
entry arriving, which is how that argument goes quietly false.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import pre_tool_bash_reviewer_guard as reviewer_guard
import target_routing
from conftest import _HookTestCase


class TestTheGuardedSetStaysAtTwo(_HookTestCase):
    """The scope claim, which nothing checked.

    The module argues its allowlist can stay FLAT precisely because only the
    two agents with recorded incidents are guarded: a subcommand-level
    allowlist cannot pass `branch -a` while refusing `branch -D`, so a third
    agent with different needs would force per-flag rules. The negative tests
    name specific unguarded agents; none of them notices a THIRD entry
    arriving, which is how the scope argument goes quietly false.
    """

    def test_exactly_two_agents_are_guarded(self):
        self.assertEqual(
            len(reviewer_guard.GUARDED_AGENTS),
            2,
            "a third guarded agent breaks the flat-allowlist argument in this "
            "module's docstring — widen the allowlist design, or the prose",
        )

    def test_the_two_are_the_reviewers_with_incidents(self):
        """Non-vacuity: a count alone passes on any two names."""
        self.assertIn("xp-code-reviewer", reviewer_guard.GUARDED_AGENTS)
        self.assertIn(target_routing.CLOSE_REVIEWER_BARE, reviewer_guard.GUARDED_AGENTS)


if __name__ == "__main__":
    import unittest

    unittest.main()
