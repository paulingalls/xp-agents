#!/usr/bin/env python3
"""A skill that SHIPS a preload must have something that RUNS it.

The failure is silent by construction, and that has not changed. Every other
suite that touches a preload runs the SCRIPT directly: the budget fixtures
execute it to measure bytes, and each skill's prose suite executes it to assert
the variables it emits. All of them pass on a preload the shipped skill never
runs. A SKILL.md whose steps branch on `SMM_DIR`, `TEST_COMMAND` or a
`### SURFACES` block, with nothing running its preload, ships an agent that
reads every one of those as unset — and those suites stay green, because none
of them asked who calls the script.

Found live that way: `/xp-scaffold-worktree` shipped a preload emitting the
seven values its Steps 0-8 branch on, and no line that ran it.

**What changed is the answer to "who runs it", not the question.** Every
shipped skill is now delivered by hook-side injection: `preload_injection.py`
resolves the skill's own invocation through `skill_preload_map` and injects
the output, so "wired" means the resolver reaches the script AND the handler
is registered on both manifests.

**The forked-skill mechanism this suite once also covered is gone.**
story-013 converted the last three fork holdouts (xp-review-plan,
xp-sprint-review, xp-system-context) to spawn their own subagent instead —
injection was measured not to cross the fork boundary (the parent receives
it, the subagent does not), so each carried an instruction-time `!` line as
its only channel until it converted. That class of test (the `!` line
lookup, the non-vacuity guard for it) is retired rather than left checking an
empty set — see this module's own history for the shape it had while any
skill still needed it.
"""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

import skill_preload_map
from _preload_fixtures import _EXPECTED_PRELOADS
from conftest import _PLUGIN_ROOT

_SKILLS_DIR = _PLUGIN_ROOT / "skills"
_HOOKS_DIR = _PLUGIN_ROOT / "hooks"
_HANDLER = "scripts/preload_injection.py"


def _preload_scripts() -> list[Path]:
    """Every shell script a skill ships under its own `scripts/`.

    Deliberately NOT filtered to `preload.sh`: the one entry point spelled
    differently today (`xp-kickoff/scripts/check_session_needs.sh`) is proof
    that a name list would have to be maintained, and the failure it would let
    through — a preload under a new name, invoked by nobody — is exactly the one
    this module exists to catch.
    """
    return sorted(_SKILLS_DIR.glob("*/scripts/*.sh"))


def _handler_is_registered(manifest: str) -> bool:
    data = json.loads((_HOOKS_DIR / manifest).read_text(encoding="utf-8"))
    return any(
        _HANDLER in hook.get("command", "")
        for entries in data["hooks"].values()
        for entry in entries
        for hook in entry.get("hooks", [])
    )


class TestEveryShippedPreloadIsInvoked(unittest.TestCase):
    def test_the_scan_finds_every_preload(self):
        self.assertEqual(
            len(_preload_scripts()),
            _EXPECTED_PRELOADS,
            "the preload glob drifted — a scan of nothing reads as green",
        )

    def test_each_inline_preload_is_reachable_through_the_resolver(self):
        """Every shipped skill is inline now (story-013): the resolver IS the
        wiring, so a skill it cannot resolve ships a preload nothing can run."""
        for script in _preload_scripts():
            skill = script.parent.parent.name
            with self.subTest(skill=skill):
                invocation = skill_preload_map.resolve_preload(skill)
                self.assertIsNotNone(
                    invocation, f"{skill} ships {script.name} but resolves to nothing"
                )
                assert invocation is not None
                self.assertEqual(Path(invocation.argv[0]).name, script.name)

    def test_the_injection_handler_is_registered_on_both_manifests(self):
        """The other half of inline wiring. A resolver that resolves perfectly
        delivers nothing if no hook runs it, and that failure is invisible to
        every suite that calls the resolver directly."""
        for manifest in ("hooks.json", "hooks.codex.json"):
            with self.subTest(manifest=manifest):
                self.assertTrue(
                    _handler_is_registered(manifest),
                    f"{manifest} registers no {_HANDLER} — every inline skill's "
                    "preload output reads as unset at runtime",
                )

    def test_no_skill_still_carries_an_instruction_time_line(self):
        """Both mechanisms delivering the same state is not belt-and-braces.

        Every skill is inline now (story-013 converted the last three), so
        none may carry the old `!`...`` line alongside injection. Each run of
        a close preload MINTS A NEW CYCLE ID and emits its own `close_started`
        event, so a skill delivered twice arms two cycles: the marker holds
        one, the injected context names the other, and the gate that counts
        by cycle id then counts an empty one.
        """
        offenders = []
        for script in _preload_scripts():
            skill = script.parent.parent.name
            body = (script.parent.parent / "SKILL.md").read_text(encoding="utf-8")
            if any(line.startswith("!`") for line in body.splitlines()):
                offenders.append(skill)
        self.assertEqual(
            offenders,
            [],
            f"delivered by BOTH injection and an instruction-time line: {offenders}",
        )


if __name__ == "__main__":
    unittest.main()
