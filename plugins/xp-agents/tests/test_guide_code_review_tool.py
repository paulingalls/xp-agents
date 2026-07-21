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

from _pin_helpers import rel

_PLUGIN_ROOT = Path(__file__).parent.parent

# The known-bad shapes found across PROCESS_GUIDE.md, TEAMMATE_GUIDE.md,
# bash_post_tool.py, and seed_smm.py before this story's fix.
_SKILL_CALL_RE = re.compile(r"Skill\([^)]*code-review", re.I)
_NEGATION_RE = re.compile(r"\b(not|cannot|never)\b", re.I)
_PAREN_PAIR = "(/code-review, /xp-quality-review)"
_ARROW_CHAIN_RE = re.compile(r"/code-review\s*(?:→|->)\s*/xp-quality-review")
_AFTER_COMMITS_RE = re.compile(r"/code-review\s+after\s+commits?", re.I)

_GUIDE_NAMES = ("PROCESS_GUIDE.md", "TEAMMATE_GUIDE.md")


def _shipped_files() -> list[Path]:
    """Every shipped prose + code surface that can mention /code-review.

    Mirrors the story's end-to-end read-through:
    `grep -rn "code-review" plugins/xp-agents/ | grep -v /tests/`.
    """
    files: list[Path] = []
    files += sorted(_PLUGIN_ROOT.glob("*.md"))
    files += sorted(_PLUGIN_ROOT.glob("agents/*.md"))
    files += sorted(_PLUGIN_ROOT.glob("skills/*/SKILL.md"))
    files += sorted((_PLUGIN_ROOT / "scripts").rglob("*.py"))
    files += sorted((_PLUGIN_ROOT / "scripts").rglob("*.md"))
    files += sorted((_PLUGIN_ROOT / "smm").rglob("*.py"))
    files += sorted(_PLUGIN_ROOT.glob("skills/*/scripts/*.py"))
    return [f for f in files if f.is_file()]


def _code_review_lines(path: Path) -> list[tuple[int, str]]:
    """(lineno, line) pairs mentioning /code-review, excluding our own
    xp-code-reviewer agent (a distinct, unrelated surface)."""
    out = []
    for lineno, line in enumerate(path.read_text().splitlines(), start=1):
        if "code-review" not in line.lower():
            continue
        if "xp-code-reviewer" in line:
            continue
        out.append((lineno, line))
    return out


class TestNoSkillLaunchSuggestion(unittest.TestCase):
    """AC: no path suggests launching /code-review with the Skill tool."""

    def test_no_shipped_mention_suggests_skill_launch(self):
        violations = []
        for f in _shipped_files():
            for lineno, line in _code_review_lines(f):
                loc = f"{rel(f, _PLUGIN_ROOT)}:{lineno}: {line.strip()}"
                if _SKILL_CALL_RE.search(line):
                    violations.append(loc)
                    continue
                if re.search(r"\bSkill\b", line) and not _NEGATION_RE.search(line):
                    violations.append(loc)
        self.assertEqual(
            violations,
            [],
            "shipped mention(s) suggest Skill-launching /code-review:\n"
            + "\n".join(violations),
        )


class TestNoPerCommitImplication(unittest.TestCase):
    """AC: no path implies /code-review runs on a per-commit cadence."""

    def test_no_shipped_mention_implies_per_commit_cadence(self):
        violations = []
        for f in _shipped_files():
            for lineno, line in _code_review_lines(f):
                if (
                    _PAREN_PAIR in line
                    or _ARROW_CHAIN_RE.search(line)
                    or _AFTER_COMMITS_RE.search(line)
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
