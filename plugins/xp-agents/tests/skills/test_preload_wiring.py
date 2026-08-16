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

**What changed is the answer to "who runs it", not the question.** Two
mechanisms are in force at once, and each skill must be covered by exactly the
one that applies to it:

- **Inline skills** are delivered by hook-side injection. `preload_injection.py`
  resolves the skill's own invocation through `skill_preload_map` and injects
  the output, so "wired" means the resolver reaches the script AND the handler
  is registered on both manifests.
- **Forked skills** keep their instruction-time `!` line. Injection was measured
  not to cross the fork boundary — the parent receives it and the subagent does
  not — so until those three are converted to spawn their own subagent, the line
  is the only channel they have. That interim is time-boxed to the conversion
  story, and this suite is what makes it visible rather than permanent.
"""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

import skill_preload_map
from conftest import _PLUGIN_ROOT

_SKILLS_DIR = _PLUGIN_ROOT / "skills"
_HOOKS_DIR = _PLUGIN_ROOT / "hooks"
_HANDLER = "scripts/preload_injection.py"

# Non-vacuity: a glob that silently stops matching must fail loudly rather than
# report a green scan of nothing (the same guard the frontmatter suite keeps).
_EXPECTED_PRELOADS = 17

# The skill(s) still delivered by the instruction-time line, because
# injection does not cross the fork boundary. Spelled out rather than derived
# from the frontmatter so that CONVERTING one is a visible edit here — derived,
# the list would shrink silently and this suite would never mention it again.
# story-013 converted xp-sprint-review and xp-system-context to the
# inline-spawns-subagent shape; xp-review-plan converts in the same story's
# next commit.
_FORKED_SKILLS = frozenset({"xp-review-plan"})


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

    def test_the_forked_set_is_not_empty_while_it_is_claimed_to_matter(self):
        """Non-vacuity for the split below. An emptied set would silently turn
        the forked branch into a no-op and this suite would assert the injection
        rule over skills that do not have it."""
        self.assertTrue(_FORKED_SKILLS)

    def test_each_inline_preload_is_reachable_through_the_resolver(self):
        """Inline skills: the resolver IS the wiring, so a skill it cannot
        resolve ships a preload nothing can run."""
        for script in _preload_scripts():
            skill = script.parent.parent.name
            if skill in _FORKED_SKILLS:
                continue
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

    def test_each_forked_preload_is_still_invoked_by_its_own_line(self):
        """Forked skills: injection cannot reach them, so the instruction-time
        line is still load-bearing and must still be there.

        Matched on the `!`...`` COMMAND line, not on the path appearing
        anywhere: the same path in a fenced block or a sentence is inert, and a
        substring search cannot tell those apart.
        """
        for script in _preload_scripts():
            skill = script.parent.parent.name
            if skill not in _FORKED_SKILLS:
                continue
            with self.subTest(skill=skill):
                skill_md = script.parent.parent / "SKILL.md"
                lines = skill_md.read_text(encoding="utf-8").splitlines()
                needle = f"${{CLAUDE_SKILL_DIR}}/scripts/{script.name}"
                self.assertTrue(
                    any(line.startswith("!`") and needle in line for line in lines),
                    f"{skill} is forked, so injection cannot reach it, and no "
                    "`!`...`` line runs its preload either — it ships blind",
                )

    def test_no_inline_skill_still_carries_an_instruction_time_line(self):
        """Both mechanisms delivering the same state is not belt-and-braces.

        Each run of a close preload MINTS A NEW CYCLE ID and emits its own
        `close_started` event, so a skill delivered twice arms two cycles: the
        marker holds one, the injected context names the other, and the gate
        that counts by cycle id then counts an empty one.
        """
        offenders = []
        for script in _preload_scripts():
            skill = script.parent.parent.name
            if skill in _FORKED_SKILLS:
                continue
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
