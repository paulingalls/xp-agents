#!/usr/bin/env python3
"""A skill that SHIPS a preload must INVOKE it.

The preload is wired in exactly one place — a `!`...`` command line in SKILL.md,
run at skill load — and nothing else in the tree reads that line. Every other
suite that touches a preload runs the SCRIPT directly:
`_preload_fixtures`/`test_volume_budgets` execute it to measure bytes, and each
skill's own prose suite executes it to assert the variables it emits. All of
them pass on a preload the shipped skill never runs.

So the failure this pins is silent by construction. A SKILL.md whose steps
branch on `SMM_DIR`, `TEST_COMMAND` or a `### SURFACES` block, with no
invocation line, ships an agent that reads every one of those as unset — and
the budget, fixture and content suites stay green because they never asked who
calls the script.

Found live: `/xp-scaffold-worktree` shipped a preload emitting the seven values
its Steps 0-8 branch on, and no line that ran it.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from conftest import _PLUGIN_ROOT

_SKILLS_DIR = _PLUGIN_ROOT / "skills"

# Non-vacuity: a glob that silently stops matching must fail loudly rather than
# report a green scan of nothing (the same guard the frontmatter suite keeps).
_EXPECTED_PRELOADS = 17


def _preload_scripts() -> list[Path]:
    """Every shell script a skill ships under its own `scripts/`.

    Deliberately NOT filtered to `preload.sh`: the one entry point spelled
    differently today (`xp-kickoff/scripts/check_session_needs.sh`) is proof
    that a name list would have to be maintained, and the failure it would let
    through — a preload under a new name, invoked by nobody — is exactly the one
    this module exists to catch. A shell file here that is genuinely a library
    rather than an entry point does not exist yet; if one is added, it will fire
    this pin and can be moved to the shared `skills/` root, where the other
    sourced-only modules already live.
    """
    return sorted(_SKILLS_DIR.glob("*/scripts/*.sh"))


class TestEveryShippedPreloadIsInvoked(unittest.TestCase):
    def test_the_scan_finds_every_preload(self):
        self.assertEqual(
            len(_preload_scripts()),
            _EXPECTED_PRELOADS,
            "the preload glob drifted — a scan of nothing reads as green",
        )

    def test_each_preload_is_invoked_by_its_skill(self):
        """Matched on the `!`...`` COMMAND line, not on the path appearing
        anywhere: the same path written in a fenced block or a sentence is
        inert, and a substring search cannot tell those apart. The trailing
        backtick is deliberately not required — `/xp-assign` passes an argument
        (`preload.sh --consume-gate`) and is invoked just as much."""
        for script in _preload_scripts():
            skill_md = script.parent.parent / "SKILL.md"
            with self.subTest(skill=script.parent.parent.name):
                lines = skill_md.read_text(encoding="utf-8").splitlines()
                needle = f"${{CLAUDE_SKILL_DIR}}/scripts/{script.name}"
                self.assertTrue(
                    any(line.startswith("!`") and needle in line for line in lines),
                    f"{skill_md.parent.name} ships {script.name} but no `!`...`` "
                    f"line runs it — every variable it emits reads as unset at "
                    f"runtime",
                )


if __name__ == "__main__":
    unittest.main()
