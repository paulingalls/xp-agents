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

Budget formula, matching the sibling modules: round(chars * 1.125 / 10) * 10
against the trimmed size, so each surface keeps ~11% headroom rather than
sitting at its cap. Adding a surface: measure the trimmed description, apply
the formula, add both entries below.
"""

import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from conftest import _PLUGIN_ROOT

_SKILLS_DIR = _PLUGIN_ROOT / "skills"
_AGENTS_DIR = _PLUGIN_ROOT / "agents"

# Non-vacuity: a glob that silently stops matching must fail loudly rather than
# report a green scan of nothing (the story-001 lesson).
_EXPECTED_SKILLS = 18
_EXPECTED_AGENTS = 7

SKILL_DESCRIPTION_BUDGETS: dict[str, int] = {
    "xp-accept": 120,
    "xp-assign": 170,
    "xp-end-session": 170,
    "xp-free-close": 180,
    "xp-kickoff": 120,
    "xp-plan": 180,
    "xp-plan-close": 170,
    "xp-quality-review": 180,
    "xp-review-plan": 120,
    "xp-scaffold-acceptance": 200,
    "xp-schedule": 190,
    "xp-sprint-close": 160,
    "xp-sprint-review": 160,
    "xp-sprint-start": 180,
    "xp-stage-migration": 160,
    "xp-story-close": 170,
    "xp-system-context": 180,
    "xp-work-selection": 170,
}

AGENT_DESCRIPTION_BUDGETS: dict[str, int] = {
    "xp-close-reviewer": 200,
    "xp-code-reviewer": 170,
    "xp-housekeeper": 170,
    "xp-plan-reviewer": 160,
    "xp-retrospective": 170,
    "xp-sprint-reviewer": 160,
    "xp-system-analyzer": 170,
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
_DESCRIPTION_RE = re.compile(r"description: >-\n((?:[ \t]+.*\n)+)|description: (.*)")


def read_description(path: Path) -> str:
    """The description as the harness renders it: folded to a single line.

    A folded block scalar (``>-``) joins its lines with spaces, so measuring the
    raw slice would count the YAML indentation the harness never sees. Collapse
    whitespace and measure that — the budget has to bound what actually reaches
    the context window, not the file's layout.
    """
    frontmatter = _FRONTMATTER_RE.match(path.read_text(encoding="utf-8"))
    if frontmatter is None:
        return ""
    match = _DESCRIPTION_RE.search(frontmatter.group(1))
    if match is None:
        return ""
    return " ".join((match.group(1) or match.group(2) or "").split())


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
            f"{name}: {len(text)}/{budgets[name]} (+{len(text) - budgets[name]})"
            for name, text in surfaces.items()
            if name in budgets and len(text) > budgets[name]
        ]
        self.assertFalse(
            over,
            f"{label} description(s) over budget — this text sits in EVERY "
            f"session's context: {over}",
        )

    def test_no_skill_description_exceeds_budget(self):
        self._assert_under(_skills(), SKILL_DESCRIPTION_BUDGETS, "skill")

    def test_no_agent_description_exceeds_budget(self):
        self._assert_under(_agents(), AGENT_DESCRIPTION_BUDGETS, "agent")


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
