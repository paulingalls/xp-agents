#!/usr/bin/env python3
"""Shared-pipeline text-content guards: skip-note drop, ordering, genericness.

Split out of `test_close_preloads_emit_shared.py` (which grew past the
500-line cap). See that file for the per-mode preload-stdout assertions
(`_SharedPreloadAssertions`); this sibling covers static text-content
checks that don't run any preload:

- plan/free SKILL.md must have dropped the old "skip MAYBE ADDRESSED"
  note (commit 2b made Step 5b apply uniformly across all 4 skills).
- the shared close-pipeline file's Step 5/5b/5c/6 headings must appear
  in order, exactly once each.
- shipped plugin markdown (skills, agents, the shared close-pipeline
  reference) must not name project-internal SMM event IDs or spike-NNN
  names — the plugin ships to other projects.
"""

import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from _bases import _PLUGIN_ROOT

_SKIP_NOTE_TARGETS = {
    "plan": _PLUGIN_ROOT / "skills" / "xp-plan-close" / "SKILL.md",
    "free": _PLUGIN_ROOT / "skills" / "xp-free-close" / "SKILL.md",
}

_SHARED_CLOSE_PIPELINE = _PLUGIN_ROOT / "scripts" / "_close_pipeline_shared.md"


class TestPlanFreeCloseSkillMDDropsSkipNote(unittest.TestCase):
    """Commit 2b removes the 'skip MAYBE ADDRESSED' notes from
    xp-plan-close + xp-free-close SKILL.md. The shared file's Step 5b
    now applies uniformly across all 4 close skills; leaving the skip
    notes inline would contradict the preload-injected guidance.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.skill_lower = {
            mode: path.read_text().lower() for mode, path in _SKIP_NOTE_TARGETS.items()
        }

    def test_close_skills_drop_skip_maybe_addressed_note(self):
        for mode in _SKIP_NOTE_TARGETS:
            with self.subTest(mode=mode):
                self.assertNotIn(
                    "does not run the maybe addressed",
                    self.skill_lower[mode],
                    f"{mode}-close SKILL.md must drop the 'skip MAYBE "
                    f"ADDRESSED' note in commit 2b — it now contradicts "
                    f"the shared Step 5b",
                )


class TestSharedPipelineCoherence(unittest.TestCase):
    """Per plan-reviewer concern ee1db2bd2f8a: each preceding commit's
    smoke test only checks that commit's marker text. After commits 2,
    3, AND 4 land, the shared file's section ordering should still
    flow: Step 5 → Step 5b → Step 5c → Step 6. A scrambled or
    duplicated heading would break LLM execution but no per-commit
    smoke test would catch it.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.shared_text = _SHARED_CLOSE_PIPELINE.read_text()

    def test_step_headings_appear_in_expected_order(self):
        expected = [
            "### Step 5: Present findings",
            "### Step 5b: Resolve Addressed Concerns",
            "### Step 5c: Classify and act on reviewer findings",
            "### Step 6: Confirm the merge",
        ]
        positions = [self.shared_text.find(heading) for heading in expected]
        for heading, pos in zip(expected, positions, strict=True):
            self.assertNotEqual(
                pos,
                -1,
                f"Shared close-pipeline file missing required heading: {heading}",
            )
        self.assertEqual(
            positions,
            sorted(positions),
            f"Shared close-pipeline headings out of order. "
            f"Expected {expected}; got positions {positions}",
        )

    def test_each_step_heading_appears_exactly_once(self):
        # Duplicate headings would confuse the LLM about which body
        # block to follow. Pin uniqueness alongside ordering.
        for heading in (
            "### Step 5: Present findings",
            "### Step 5b: Resolve Addressed Concerns",
            "### Step 5c: Classify and act on reviewer findings",
            "### Step 6: Confirm the merge",
        ):
            with self.subTest(heading=heading):
                self.assertEqual(
                    self.shared_text.count(heading),
                    1,
                    f"Heading must appear exactly once: {heading}",
                )


class TestShippedFilesAreProjectGeneric(unittest.TestCase):
    """Regression guard: shipped plugin files (skills, agents, the
    shared close-pipeline reference) must not name project-internal
    SMM event IDs (12-hex hashes wrapped in `(decision <id>)` or
    `(Constraints \\`<id>\\`)` / `(Wisdom \\`<id>\\`)` patterns) or
    spike-NNN names. Those are meaningful only inside the xp-agents
    repo's own SMM event log; they're noise-or-worse to a plugin user
    in another project.

    Resolves-Event trailers in commit messages are fine (they're git
    trailer syntax, not in shipped runtime instructions). Tests under
    tests/ and docs under docs/ may freely reference internal IDs —
    those don't ship.
    """

    # Walks every markdown file the plugin ships at runtime: SKILL.md
    # bodies (skills/), agent prompts (agents/), and the close-pipeline
    # reference under scripts/. _preload_base.sh is shell, not LLM-
    # facing prose, so excluded.
    #
    # scripts/ is a DIRECTORY root, not a named file. It used to name
    # `_close_pipeline_shared.md` directly, and splitting that reference by
    # close mode moved a third of its prose into a sibling
    # (`_close_pipeline_review.md`) that the named-file form would have
    # silently stopped scanning — the banned patterns are project-internal
    # references, so an unscanned shipped surface is exactly the hole this
    # test exists to close. The glob cannot be outrun by the next split.
    _SHIPPED_MARKDOWN_ROOTS = (
        _PLUGIN_ROOT / "skills",
        _PLUGIN_ROOT / "agents",
        _PLUGIN_ROOT / "scripts",
    )

    # Match the parenthetical patterns that wrap an internal event ID.
    # We deliberately don't ban bare 12-hex strings — git short-hashes
    # and example placeholders use that shape too. The parenthetical
    # framing is what marks the project-internal reference.
    #
    # `M-N` matches project-internal milestone labels (M-1, M-2, …)
    # which only make sense inside this repo's execution_plan.json
    # phasing. Word-boundary anchored so it doesn't false-positive on
    # tokens like "M-Audit" or "M-x".
    _BANNED_PATTERNS = (
        re.compile(r"\(decision\s+[0-9a-f]{12}\b", re.IGNORECASE),
        re.compile(r"\(Constraints\s+`[0-9a-f]{12}`", re.IGNORECASE),
        re.compile(r"\(Wisdom\s+`[0-9a-f]{12}`", re.IGNORECASE),
        re.compile(r"\(Risks\s+`[0-9a-f]{12}`", re.IGNORECASE),
        re.compile(r"\bspike-\d{3}\b", re.IGNORECASE),
        re.compile(r"\bM-\d+\b"),
    )

    @classmethod
    def _shipped_md_files(cls):
        files = []
        for root in cls._SHIPPED_MARKDOWN_ROOTS:
            if root.is_file():
                files.append(root)
            elif root.is_dir():
                files.extend(root.rglob("*.md"))
        return files

    def test_no_internal_smm_id_or_spike_refs_in_shipped_md(self):
        for md_path in self._shipped_md_files():
            text = md_path.read_text()
            for pattern in self._BANNED_PATTERNS:
                with self.subTest(file=str(md_path), pattern=pattern.pattern):
                    match = pattern.search(text)
                    self.assertIsNone(
                        match,
                        f"{md_path.relative_to(_PLUGIN_ROOT)} contains "
                        f"project-internal reference matching "
                        f"{pattern.pattern!r}: {match.group(0) if match else ''!r}. "
                        f"Shipped files must be plugin-generic — no SMM "
                        f"event hex IDs or spike-NNN names. Move the "
                        f"reference to docs/ or replace with a self-"
                        f"contained explanation.",
                    )


if __name__ == "__main__":
    unittest.main()
