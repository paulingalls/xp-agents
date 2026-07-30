#!/usr/bin/env python3
"""Budgets and trigger retention for the ALWAYS-RESIDENT description surface.

A SKILL.md or agent .md *body* is loaded when that one skill or agent is
actually invoked. Its `description:` frontmatter is different: it is what the
harness lists so the model can pick, so it sits in context on **every session**
and, for agents, on every subagent spawn — whether or not the skill ever fires.
Measured at story-004: 5090 chars across 18 skills plus 1845 across 7 agents.
A character cut here is worth many multiples of the same cut in a body.

Two independent checks, because either alone is unsafe:

* **Budget** bounds the cost. On its own it is satisfied by a description
  trimmed into uselessness — bytes fell, and nothing noticed the skill stopped
  being selectable.
* **Retention** bounds the damage. Each surface declares the trigger vocabulary
  a router needs to reach it; the budget may not be met by deleting those.

Only the budget check carries the red — retention is an INVARIANT that held
before this story and must keep holding, so it passes on both sides of the
trim. Said plainly rather than dressed up as a failing test it never was.

Budget formula, matching the sibling modules: `ratchet(chars, current, 10)` —
`chars * 1.125` rounded to the nearest 10, but never above the number already
on record. A surface keeps ~11% headroom rather than sitting at its cap.

That formula is the **floor**, and `test_no_budget_sits_at_its_cap` enforces
it: an entry BELOW the formula has no room for a clarifying word, which is the
shape that already produced this sprint's PROCESS_GUIDE and close-SKILL debt.
Most entries now sit AT the floor rather than above it, because the ratchet
took each one down to the formula wherever the formula was the lower number.
The two rules meet without conflict: `ratchet` returns `min(formula, current)`
and the floor requires `>= formula`, so the ratchet can only ever land a
description budget exactly on its floor, never under it.

The upper bound fails at 98% of budget, not on breach — a description at its
cap is reported while a trim is still cheap.

Adding a surface: measure the trimmed description, apply the formula, add both
entries below.
"""

import re
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from _band_proof import assert_band_fired, below_band_budget, in_band_budget
from conftest import _PLUGIN_ROOT, band_offender

_SKILLS_DIR = _PLUGIN_ROOT / "skills"
_AGENTS_DIR = _PLUGIN_ROOT / "agents"

# Non-vacuity: a glob that silently stops matching must fail loudly rather than
# report a green scan of nothing (the story-001 lesson).
_EXPECTED_SKILLS = 18
_EXPECTED_AGENTS = 7

SKILL_DESCRIPTION_BUDGETS: dict[str, int] = {
    "xp-accept": 130,
    "xp-assign": 160,
    "xp-end-session": 140,
    "xp-free-close": 130,
    "xp-kickoff": 130,
    "xp-plan": 130,
    "xp-plan-close": 150,
    "xp-quality-review": 130,
    "xp-review-plan": 130,
    "xp-scaffold-acceptance": 180,
    "xp-schedule": 160,
    "xp-sprint-close": 150,
    "xp-sprint-review": 140,
    "xp-sprint-start": 150,
    "xp-stage-migration": 130,
    "xp-story-close": 130,
    "xp-system-context": 140,
    "xp-work-selection": 120,
}

AGENT_DESCRIPTION_BUDGETS: dict[str, int] = {
    "xp-close-reviewer": 160,
    "xp-code-reviewer": 150,
    "xp-housekeeper": 150,
    "xp-plan-reviewer": 150,
    "xp-retrospective": 130,
    "xp-sprint-reviewer": 140,
    "xp-system-analyzer": 130,
}

# The vocabulary a router needs to reach each surface. Matched case-insensitively
# against the description. These are what a trim may NOT spend: a shorter
# description that no longer names what it is for is a regression the body
# cannot repair, because the body is not read until after the pick is made.
SKILL_TRIGGERS: dict[str, tuple[str, ...]] = {
    "xp-accept": ("acceptance criteria", "stories"),
    "xp-assign": ("teammate", "tier"),
    "xp-end-session": ("session", "questions"),
    "xp-free-close": ("free", "merge"),
    "xp-kickoff": ("session start", "retrospective"),
    "xp-plan": ("execution_plan.json", "milestones"),
    "xp-plan-close": ("plan branch", "merge"),
    "xp-quality-review": ("review", "diff"),
    "xp-review-plan": ("plan", "TDD"),
    "xp-scaffold-acceptance": ("scaffold", "acceptance test"),
    "xp-schedule": ("solo", "parallel"),
    "xp-sprint-close": ("sprint branch", "merge"),
    "xp-sprint-review": ("sprint", "shipped"),
    "xp-sprint-start": ("sprint.json", "stories"),
    "xp-stage-migration": ("stage 2", "kickoff"),
    "xp-story-close": ("story", "merge"),
    "xp-system-context": ("system_context.json", "architecture"),
    "xp-work-selection": ("work", "session"),
}

AGENT_TRIGGERS: dict[str, tuple[str, ...]] = {
    "xp-close-reviewer": ("close", "diff"),
    "xp-code-reviewer": ("code review", "diff"),
    "xp-housekeeper": ("smm", "curat"),
    "xp-plan-reviewer": ("plan", "review"),
    "xp-retrospective": ("retrospective", "keep/fix/try"),
    "xp-sprint-reviewer": ("sprint", "shipped"),
    "xp-system-analyzer": ("system_context.json", "codebase"),
}

_FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---\n", re.S)
_BLOCK_INDICATORS = "|>"


def read_description(path: Path) -> str:
    """The description as the harness renders it: folded to a single line.

    A block scalar joins its lines with spaces, so measuring the raw slice would
    count the YAML indentation the harness never sees. Collapse whitespace and
    measure that — the budget has to bound what actually reaches the context
    window, not the file's layout.

    Every shipped description uses ``>-`` today, but all six block indicators
    (``| > |- >- |+ >+``) are handled: a regex pinned to one spelling would let
    another parse as the two-character indicator itself, which is non-empty and
    trivially under every budget. Same reason the continuation run is read by
    indentation rather than by a trailing newline — `description:` as the last
    frontmatter key has none on its final line.
    """
    frontmatter = _FRONTMATTER_RE.match(path.read_text(encoding="utf-8"))
    if frontmatter is None:
        return ""
    lines = frontmatter.group(1).split("\n")
    for index, line in enumerate(lines):
        if not line.startswith("description:"):
            continue
        value = line[len("description:") :].strip()
        if value and value[0] not in _BLOCK_INDICATORS:
            return " ".join(value.split())
        body = []
        for continuation in lines[index + 1 :]:
            if continuation[:1] not in (" ", "\t"):
                break
            body.append(continuation)
        return " ".join(" ".join(body).split())
    return ""


def _surfaces(directory: Path, pattern: str, name_of) -> dict[str, str]:
    return {name_of(p): read_description(p) for p in sorted(directory.glob(pattern))}


def _skills() -> dict[str, str]:
    return _surfaces(_SKILLS_DIR, "*/SKILL.md", lambda p: p.parent.name)


def _agents() -> dict[str, str]:
    return _surfaces(_AGENTS_DIR, "*.md", lambda p: p.stem)


class TestDescriptionsAreDiscoverable(unittest.TestCase):
    """Every surface has a non-empty description the extractor can read.

    Guards the extractor as much as the content: a regex that silently stopped
    matching would make every budget below pass on an empty string.
    """

    def test_skill_count_and_non_empty(self):
        skills = _skills()
        self.assertEqual(len(skills), _EXPECTED_SKILLS, f"skills: {sorted(skills)}")
        for name, text in skills.items():
            self.assertTrue(text, f"{name}: description did not parse")

    def test_agent_count_and_non_empty(self):
        agents = _agents()
        self.assertEqual(len(agents), _EXPECTED_AGENTS, f"agents: {sorted(agents)}")
        for name, text in agents.items():
            self.assertTrue(text, f"{name}: description did not parse")


class TestReadDescription(unittest.TestCase):
    """The extractor itself, on the YAML shapes a future surface may use."""

    def _read(self, frontmatter: str) -> str:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "SKILL.md"
            path.write_text(f"---\n{frontmatter}\n---\n\n# Body\n", encoding="utf-8")
            return read_description(path)

    def test_folded_block_scalar(self):
        self.assertEqual(
            self._read("name: x\ndescription: >-\n  one two\n  three\nmodel: opus"),
            "one two three",
        )

    def test_literal_block_scalar(self):
        self.assertEqual(self._read("name: x\ndescription: |\n  one two"), "one two")

    def test_block_scalar_as_last_key(self):
        """No trailing newline on the final line — must not be dropped."""
        self.assertEqual(
            self._read("name: x\ndescription: >-\n  one two\n  three"),
            "one two three",
        )

    def test_plain_scalar(self):
        self.assertEqual(self._read("description: one two three"), "one two three")

    def test_missing_description(self):
        self.assertEqual(self._read("name: x\nmodel: opus"), "")


class TestEverySurfaceHasABudget(unittest.TestCase):
    """A new skill or agent must declare its budget, not inherit silence."""

    def test_skill_budget_keys_match(self):
        self.assertEqual(sorted(_skills()), sorted(SKILL_DESCRIPTION_BUDGETS))

    def test_agent_budget_keys_match(self):
        self.assertEqual(sorted(_agents()), sorted(AGENT_DESCRIPTION_BUDGETS))

    def test_skill_trigger_keys_match(self):
        self.assertEqual(sorted(_skills()), sorted(SKILL_TRIGGERS))

    def test_agent_trigger_keys_match(self):
        self.assertEqual(sorted(_agents()), sorted(AGENT_TRIGGERS))


class TestDescriptionBudgets(unittest.TestCase):
    """The red: descriptions are over budget until story-004 trims them."""

    def _assert_under(
        self, surfaces: dict[str, str], budgets: dict[str, int], label: str
    ):
        over = [
            offender
            for name, text in surfaces.items()
            if name in budgets
            and (offender := band_offender(name, len(text), budgets[name]))
        ]
        self.assertFalse(
            over,
            f"{label} description(s) at or inside the 98% band of budget — "
            f"this text sits in EVERY session's context: {over}",
        )

    def test_no_skill_description_exceeds_budget(self):
        self._assert_under(_skills(), SKILL_DESCRIPTION_BUDGETS, "skill")

    def test_no_agent_description_exceeds_budget(self):
        self._assert_under(_agents(), AGENT_DESCRIPTION_BUDGETS, "agent")

    def test_no_budget_sits_at_its_cap(self):
        """A budget under the formula leaves no room for a clarifying word.

        The upper bound above is only half the rule: an entry calibrated flush
        to its current size makes the NEXT true clarification a budget bump
        instead of an edit, which is how PROCESS_GUIDE reached one token of
        headroom and three close SKILL.md files reached 22-28 chars.
        """
        tight = []
        for surfaces, budgets in (
            (_skills(), SKILL_DESCRIPTION_BUDGETS),
            (_agents(), AGENT_DESCRIPTION_BUDGETS),
        ):
            for name, text in surfaces.items():
                floor = round(len(text) * 1.125 / 10) * 10
                if budgets[name] < floor:
                    tight.append(f"{name}: {budgets[name]} < formula floor {floor}")
        self.assertFalse(
            tight, f"description budget(s) below the ~11% headroom floor: {tight}"
        )


class TestDescriptionBandWiring(unittest.TestCase):
    """The band must reach `_assert_under`, not merely live in `band_offender`.

    Every entry above is calibrated ~11% above its surface, so reverting
    `_assert_under` to a bare `actual > budget` breach check leaves all of them
    green and nothing here separates the band from a breach — the same
    unfalsifiable pin the sibling stdout families carried.

    So drive one REAL description into the band with a fabricated budget: at
    or above 98% of it and still under it, which is the only region the band
    reports and a breach check cannot. `xp-scaffold-acceptance` is the surface
    because it is the longest description shipped, keeping the fabricated
    budget clear of the degenerate small numbers.
    """

    _SURFACE = "xp-scaffold-acceptance"

    def setUp(self) -> None:
        self.actual = len(_skills()[self._SURFACE])
        # Non-vacuity: an extractor that silently stopped matching would
        # measure 0, and `band_offender` reports nothing at 0.
        self.assertGreater(
            self.actual, 50, f"{self._SURFACE}: description did not parse"
        )

    def _drive(self, budget: int) -> None:
        """Run the host's own assertion over a one-entry fabricated budget."""
        host = TestDescriptionBudgets("test_no_skill_description_exceeds_budget")
        host._assert_under(_skills(), {self._SURFACE: budget}, "skill")

    def test_description_inside_the_band_is_reported(self) -> None:
        with self.assertRaises(AssertionError) as caught:
            self._drive(in_band_budget(self.actual))
        assert_band_fired(self, caught.exception, self._SURFACE)

    def test_description_below_the_band_passes(self) -> None:
        """The twin that proves the leg above reports the band, not a breach."""
        self._drive(below_band_budget(self.actual))


class TestDescriptionRetainsTriggers(unittest.TestCase):
    """The invariant: a trim may not spend the vocabulary that routes here.

    Holds before and after the trim by design — it exists so a FUTURE trim
    cannot buy its budget by deleting what makes the surface selectable.
    """

    def _assert_retained(
        self, surfaces: dict[str, str], triggers: dict[str, tuple[str, ...]]
    ):
        for name, text in surfaces.items():
            if name not in triggers:
                continue
            lowered = text.lower()
            for token in triggers[name]:
                self.assertIn(
                    token.lower(),
                    lowered,
                    f"{name}: description no longer names {token!r}. The body "
                    "cannot repair this — it is not read until after the pick.",
                )

    def test_skill_descriptions_retain_triggers(self):
        self._assert_retained(_skills(), SKILL_TRIGGERS)

    def test_agent_descriptions_retain_triggers(self):
        self._assert_retained(_agents(), AGENT_TRIGGERS)


if __name__ == "__main__":
    unittest.main()
