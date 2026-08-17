#!/usr/bin/env python3
"""Cross-cutting sweep: shipped mentions of /code-review are tool-honest.

story-011. /code-review runs via the Workflow tool, not Skill (fixed for the
close pipeline in v4.14.6; scripts/_close_pipeline_shared.md and
skills/xp-quality-review/SKILL.md already say so correctly). Surrounding
guidance never caught up — some mentions leave the tool unstated, others
still imply /code-review fires on every commit, contradicting the per-commit
cadence (xp-quality-review only; /code-review once at sprint/plan/free-close).

This is the grep-equivalent invariant sweep only: no shipped mention may
suggest launching /code-review with the Skill tool, and none may imply a
per-commit cadence. Individual wordings are pinned where they already live —
tests/hooks/test_post_tool.py, tests/smm/test_seed.py.
"""

import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from _pin_helpers import rel, shipped_files_to_scan

_PLUGIN_ROOT = Path(__file__).parent.parent

# The known-bad shapes found across PROCESS_GUIDE.md, TEAMMATE_GUIDE.md,
# bash_post_tool.py, and seed_smm.py before this story's fix.
_SKILL_CALL_RE = re.compile(r"Skill\([^)]*code-review", re.I)
_NEGATION_RE = re.compile(r"\b(not|cannot|never)\b", re.I)
_PAREN_PAIR = "(/code-review, /xp-quality-review)"
_ARROW_CHAIN_RE = re.compile(r"/code-review\s*(?:→|->)\s*/xp-quality-review")
_AFTER_COMMITS_RE = re.compile(r"/code-review\s+after\s+commits?", re.I)
# "run it on every change" is the same per-commit claim in prose form.
_EVERY_CHANGE_RE = re.compile(r"every (change|commit)", re.I)
_AGENT_NAME_RE = re.compile(r"xp-code-reviewer")

_GUIDE_NAMES = ("PROCESS_GUIDE.md", "TEAMMATE_GUIDE.md")


def _shipped_files() -> list[Path]:
    """Every shipped prose + code surface that can mention /code-review.

    Mirrors the story's end-to-end read-through:
    `grep -rn "code-review" plugins/xp-agents/ | grep -v /tests/`.
    The Python half reuses `_pin_helpers.shipped_files_to_scan` — the same
    shipped-module surface the vocabulary pins scan; this adds the prose.
    """
    files: list[Path] = list(shipped_files_to_scan(_PLUGIN_ROOT))
    files += sorted(_PLUGIN_ROOT.glob("*.md"))
    files += sorted(_PLUGIN_ROOT.glob("agents/*.md"))
    files += sorted(_PLUGIN_ROOT.glob("skills/*/SKILL.md"))
    files += sorted((_PLUGIN_ROOT / "scripts").rglob("*.md"))
    return [f for f in files if f.is_file()]


def _code_review_lines(path: Path) -> list[tuple[int, str, str]]:
    """(lineno, raw line, scannable line) for lines mentioning /code-review.

    The scannable copy blanks out our own `xp-code-reviewer` agent (a
    distinct, unrelated surface) instead of dropping the whole line, so a
    line naming both the agent and the workflow is still swept.
    """
    out = []
    for lineno, line in enumerate(path.read_text().splitlines(), start=1):
        scannable = _AGENT_NAME_RE.sub("", line)
        if "code-review" not in scannable.lower():
            continue
        out.append((lineno, line, scannable))
    return out


class TestTheSkillLaunchIsNamedExactlyOnce(unittest.TestCase):
    """AC: the Skill launch is the ONE launch site, and nothing denies it.

    INVERTED, not deleted. This class used to forbid `Skill(... code-review`
    anywhere in shipped prose, because launching that way was believed
    impossible — a belief that came from the same place as
    `pre_tool_skill`'s "cannot be launched with the Skill tool" and that is
    what made close Step 4b unrunnable: the Workflow name it named is not
    registered in the shipped build, so the one broad correctness pass silently
    did not run.

    The mirror image ("every mention must name Skill") would be VACUOUS — most
    mentions name no tool at all, so it would pass against prose that launches
    nothing. The replacement invariant is therefore three specific claims,
    each with its own failure it is there to catch.
    """

    def _mentions(self):
        for f in _shipped_files():
            for lineno, line, scannable in _code_review_lines(f):
                yield f, lineno, line, scannable

    def test_exactly_one_shipped_line_launches_it(self):
        """Two launch sites drift apart; zero means the pass never runs."""
        launches = [
            f"{rel(f, _PLUGIN_ROOT)}:{lineno}: {line.strip()}"
            for f, lineno, line, scannable in self._mentions()
            if _SKILL_CALL_RE.search(scannable)
        ]
        self.assertEqual(
            len(launches),
            1,
            "expected exactly one shipped Skill launch of /code-review, got "
            f"{len(launches)}:\n" + "\n".join(launches),
        )

    def test_the_launch_site_is_the_close_review_reference(self):
        """It belongs beside the cost bound that governs it, not in a guide."""
        for f, _lineno, _line, scannable in self._mentions():
            if _SKILL_CALL_RE.search(scannable):
                self.assertEqual(f.name, "_close_pipeline_review.md")

    def test_no_shipped_line_denies_the_skill_can_launch_it(self):
        """The exact claim that broke Step 4b. A line may still say the
        Workflow tool cannot launch it — that one is true — so the negation
        only counts when `Skill` is the thing being denied."""
        violations = [
            f"{rel(f, _PLUGIN_ROOT)}:{lineno}: {line.strip()}"
            for f, lineno, line, scannable in self._mentions()
            if re.search(r"\bSkill\b", scannable) and _NEGATION_RE.search(scannable)
        ]
        self.assertEqual(
            violations,
            [],
            "shipped mention(s) deny that the Skill tool can launch "
            "/code-review, which is false and is what broke close Step 4b:\n"
            + "\n".join(violations),
        )


class TestNoPerCommitImplication(unittest.TestCase):
    """AC: no path implies /code-review runs on a per-commit cadence."""

    def test_no_shipped_mention_implies_per_commit_cadence(self):
        violations = []
        for f in _shipped_files():
            for lineno, line, scannable in _code_review_lines(f):
                if (
                    _PAREN_PAIR in scannable
                    or _ARROW_CHAIN_RE.search(scannable)
                    or _AFTER_COMMITS_RE.search(scannable)
                    or _EVERY_CHANGE_RE.search(scannable)
                ):
                    loc = f"{rel(f, _PLUGIN_ROOT)}:{lineno}: {line.strip()}"
                    violations.append(loc)
        self.assertEqual(
            violations,
            [],
            "shipped mention(s) imply per-commit /code-review:\n"
            + "\n".join(violations),
        )


class TestGuidesNameTheWorkflowTool(unittest.TestCase):
    """AC: PROCESS_GUIDE and TEAMMATE_GUIDE name the Workflow tool rather
    than leaving /code-review's launch mechanism unstated."""

    def test_broad_review_guides_name_the_workflow_tool(self):
        for name in _GUIDE_NAMES:
            path = _PLUGIN_ROOT / name
            text = path.read_text()
            mentions = list(re.finditer(r"/code-review\b", text))
            self.assertTrue(mentions, f"{name}: no /code-review mention found")
            for m in mentions:
                if "xp-code-reviewer" in text[max(0, m.start() - 30) : m.start()]:
                    continue
                window = text[max(0, m.start() - 200) : m.end() + 200]
                self.assertIn(
                    "Workflow tool",
                    window,
                    f"{name}: /code-review mention not paired with 'Workflow "
                    f"tool' naming: ...{window}...",
                )


if __name__ == "__main__":
    unittest.main()
