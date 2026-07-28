#!/usr/bin/env python3
"""Prose pins for the sprint-review surfaces: agents/xp-sprint-reviewer.md
and skills/xp-sprint-review/SKILL.md.

Split out of test_sprint_review.py, which tests the *code* (prepare_review_data
and preload.sh). These assert against shipped markdown, share no fixtures with
that module, and grow on a different schedule.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from conftest import _PLUGIN_ROOT

_SPRINT_REVIEWER_AGENT = _PLUGIN_ROOT / "agents" / "xp-sprint-reviewer.md"
_SPRINT_REVIEW_SKILL = _PLUGIN_ROOT / "skills" / "xp-sprint-review" / "SKILL.md"


# ===========================================================================
# PR-creation removal (sprint-032 story-002)
# ===========================================================================


class TestPRCreationRemoved(unittest.TestCase):
    """story-002: PR creation moves to /xp-sprint-close; reviewer is review-only.

    Guards against re-introduction by name-change ("Open Sprint PR"),
    by helper-script substitution (branching.py create-pr), or by
    broader gh allow-listing in the skill.
    """

    @classmethod
    def setUpClass(cls):
        cls.agent_text = _SPRINT_REVIEWER_AGENT.read_text()
        cls.skill_text = _SPRINT_REVIEW_SKILL.read_text()

    def test_agent_no_pr_keywords(self):
        # Catches "Create Sprint PR", "Open Sprint PR", "Sprint PR", etc.
        text = self.agent_text.lower()
        self.assertNotIn("pull request", text)
        self.assertNotIn(" pr ", text)
        self.assertNotIn("sprint pr", text)

    def test_agent_no_gh_invocation(self):
        # Catches `gh pr create`, `gh pr ...`, `which gh`, etc.
        self.assertNotIn("gh pr", self.agent_text)
        self.assertNotIn("which gh", self.agent_text)

    def test_agent_no_branching_invocation(self):
        # Catches a Python-helper substitution for `gh pr create`.
        self.assertNotIn("branching.py", self.agent_text)

    def test_skill_allowed_tools_no_gh_or_branching(self):
        # No `gh` in any Bash() allow-list entry.
        for line in self.skill_text.splitlines():
            stripped = line.strip()
            if stripped.startswith("- Bash("):
                self.assertNotIn("gh", stripped)
                self.assertNotIn("branching.py", stripped)


# ===========================================================================
# story-010: guard against the old .md-suffixed preload key names
# ===========================================================================


class TestNoOldPreloadKeyNamesShip(unittest.TestCase):
    """sprint_md_path / execution_plan_md_path must never reappear on any
    shipped surface — both held .json paths since the four-file migration,
    and the rename to sprint_path / execution_plan_path has no transition
    period.

    Enumerated locally rather than via `_pin_helpers.shipped_files_to_scan`:
    that helper only covers `scripts/`, `smm/`, `skills/*/scripts/` (Python),
    which would skip `agents/xp-sprint-reviewer.md` — the one prose consumer
    this rename touches and the likeliest place for the old key to creep
    back in. Scanning every file (not just `.py`/`.md`) under each shipped
    root also catches `skills/xp-sprint-review/scripts/preload.sh`, the
    producer's own shell sibling.
    """

    _OLD_KEYS = ("sprint_md_path", "execution_plan_md_path")
    _SHIPPED_ROOTS = ("scripts", "smm", "skills", "agents", "hooks")

    @classmethod
    def _shipped_files(cls) -> list[Path]:
        paths: list[Path] = []
        for root_name in cls._SHIPPED_ROOTS:
            root = _PLUGIN_ROOT / root_name
            if not root.is_dir():
                continue
            for p in sorted(root.rglob("*")):
                if p.is_file() and "__pycache__" not in p.parts:
                    paths.append(p)
        paths.extend(sorted(_PLUGIN_ROOT.glob("*.md")))
        return paths

    @classmethod
    def _offending_keys(cls, text: str) -> list[str]:
        return [key for key in cls._OLD_KEYS if key in text]

    def test_pin_scans_a_nonzero_number_of_files(self):
        """A glob that matches nothing reports clean either way — this repo
        has shipped vacuous pins twice."""
        files = self._shipped_files()
        self.assertGreater(len(files), 0, "shipped-surface glob matched nothing")

    def test_pin_scans_the_surfaces_this_rename_touched(self):
        """Non-zero is too weak: a scan set that matched only `smm/*.py`
        would pass it while missing every file the rename actually crossed.
        Name the producer, the prose consumer, and the producer's own
        shell wrapper explicitly."""
        scanned = {
            p.relative_to(_PLUGIN_ROOT).as_posix() for p in self._shipped_files()
        }
        for expected in (
            "agents/xp-sprint-reviewer.md",
            "skills/xp-sprint-review/scripts/prepare_review_data.py",
            "skills/xp-sprint-review/scripts/preload.sh",
        ):
            self.assertIn(expected, scanned)

    def test_pin_detects_the_old_key_names(self):
        """Prove the detector itself flags the exact strings this story
        removed, before trusting it against the real tree."""
        self.assertEqual(
            self._offending_keys("uses sprint_md_path here"), ["sprint_md_path"]
        )
        self.assertEqual(
            self._offending_keys("uses execution_plan_md_path here"),
            ["execution_plan_md_path"],
        )
        self.assertEqual(self._offending_keys("uses sprint_path only"), [])

    def test_no_old_md_path_key_names_in_shipped_surfaces(self):
        offenders: list[str] = []
        for path in self._shipped_files():
            text = path.read_text(encoding="utf-8")
            for old_key in self._offending_keys(text):
                offenders.append(f"{path.relative_to(_PLUGIN_ROOT)}: {old_key}")
        self.assertEqual(
            offenders,
            [],
            "old .md-suffixed preload key name(s) found in shipped surface(s):\n"
            + "\n".join(offenders),
        )


class TestReviewerPromptNamesCurrentPreloadKeys(unittest.TestCase):
    """The old-name pin above is negative-only: it stays green if the keys
    vanish from the reviewer prompt entirely, or get renamed a third time
    on the producer side alone. `test_sprint_review.py::test_review_input_structure`
    pins the producer half of the contract; this pins the consumer half."""

    def test_agent_prompt_names_both_current_keys(self):
        text = _SPRINT_REVIEWER_AGENT.read_text(encoding="utf-8")
        for key in ("sprint_path", "execution_plan_path"):
            self.assertIn(
                key,
                text,
                f"xp-sprint-reviewer.md no longer names the {key!r} preload key "
                "emitted by prepare_review_data.py",
            )


if __name__ == "__main__":
    unittest.main()
