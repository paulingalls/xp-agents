#!/usr/bin/env python3
"""Tests for prepare_review_data.py and the sprint-review preload.

sprint_review_done tests migrated to test_subagent.py::TestSprintReviewerDone
as part of the PostToolUse:Skill replacement plan — the handler now
lives in subagent_stop.py.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))
sys.path.insert(
    0,
    str(
        Path(__file__).parent.parent.parent / "skills" / "xp-sprint-review" / "scripts"
    ),
)

import marker_names
from conftest import (
    _PLUGIN_ROOT,
    _HookTestCase,
    _IntegrationTestCase,
    _s,
    _sprint_json,
)

_SRI = marker_names.SPRINT_REVIEW_INPUT_PREFIX

# ---------------------------------------------------------------------------
# Sprint fixtures
# ---------------------------------------------------------------------------

SPRINT_MIXED = _sprint_json(
    [
        _s("story-001", "User login", "done"),
        _s("story-002", "User registration", "done"),
        _s("story-003", "Password reset", "deferred", dependencies=["story-001"]),
        _s("story-004", "OAuth integration", "ready", dependencies=["story-001"]),
    ],
    sprint_id="sprint-001",
    started="2026-03-15",
    goal="Build auth system",
)

SPRINT_ALL_DONE = _sprint_json(
    [
        _s("story-001", "User login", "done"),
        _s("story-002", "User registration", "done"),
        _s("story-003", "Password reset", "done", dependencies=["story-001"]),
    ],
    sprint_id="sprint-001",
    started="2026-03-15",
    goal="Build auth system",
)

SPRINT_ALL_DEFERRED = _sprint_json(
    [
        _s("story-001", "User login", "deferred"),
        _s("story-002", "User registration", "deferred"),
    ],
    sprint_id="sprint-001",
    started="2026-03-15",
    goal="Build auth system",
)

SPRINT_WITH_MILESTONE = _sprint_json(
    [_s("story-001", "User login", "done")],
    sprint_id="sprint-001",
    started="2026-03-15",
    goal="Build auth system",
    milestone="Milestone 1: Auth Foundation",
)

SPRINT_NO_ID = _sprint_json(
    [_s("story-001", "User login", "done")],
    goal="Build auth system",
)

PRODUCT_SPEC = """\
# Product Spec: Auth System

## Features

### User Registration [planned]
- Users can register with email and password

### JWT Authentication [planned]
- Login returns JWT tokens

### Password Reset [planned]
- Reset password via email link
"""


# ===========================================================================
# prepare_review_data.py
# ===========================================================================


class TestPrepareReviewData(_HookTestCase):
    """M11: prepare_review_data reads sprint + execution_plan, computes velocity."""

    def _run_with(self, sprint_text: str) -> dict:
        """Write sprint.json, run prepare_review_data, return non-None result.

        Centralizes the Optional-narrowing assert that pyright basic mode
        requires after Optional-returning calls — negative tests
        (test_no_sprint_returns_none, test_malformed_sprint_returns_none,
        test_atomic_write_uses_target_path) opt out and call directly.
        """
        import prepare_review_data

        (self.smm_dir / "sprint.json").write_text(sprint_text)
        result = prepare_review_data.run(self.smm_dir, self.smm_dir / f"{_SRI}json")
        assert result is not None
        return result

    def test_basic_velocity(self):
        """2 done, 1 deferred, 1 ready -> planned=4, delivered=2, carried=1."""
        result = self._run_with(SPRINT_MIXED)
        vel = result["velocity"]
        self.assertEqual(vel["stories_planned"], 4)
        self.assertEqual(vel["stories_delivered"], 2)
        self.assertEqual(vel["stories_carried"], 1)

    def test_review_input_structure(self):
        """Output dict has structured keys + paths, not embedded content."""
        result = self._run_with(SPRINT_MIXED)
        expected = (
            "sprint_id",
            "goal",
            "velocity",
            "sprint_path",
            "execution_plan_path",
            "milestone",
        )
        for key in expected:
            self.assertIn(key, result, f"Missing key: {key}")
        # Should NOT have embedded content
        self.assertNotIn("sprint_md", result)
        self.assertNotIn("product_spec_md", result)
        # Should NOT carry the old .md-suffixed key names
        self.assertNotIn("sprint_md_path", result)
        self.assertNotIn("execution_plan_md_path", result)

    def test_no_sprint_returns_none(self):
        """No sprint.json -> None."""
        import prepare_review_data

        result = prepare_review_data.run(self.smm_dir, self.smm_dir / f"{_SRI}json")
        self.assertIsNone(result)

    def test_all_done_velocity(self):
        """3/3 done -> planned=3, delivered=3, carried=0."""
        result = self._run_with(SPRINT_ALL_DONE)
        vel = result["velocity"]
        self.assertEqual(vel["stories_planned"], 3)
        self.assertEqual(vel["stories_delivered"], 3)
        self.assertEqual(vel["stories_carried"], 0)

    def test_all_deferred_velocity(self):
        """0/2 delivered, 2/2 carried."""
        result = self._run_with(SPRINT_ALL_DEFERRED)
        vel = result["velocity"]
        self.assertEqual(vel["stories_planned"], 2)
        self.assertEqual(vel["stories_delivered"], 0)
        self.assertEqual(vel["stories_carried"], 2)

    def test_atomic_write_uses_target_path(self):
        """run() writes to the provided target path, not a fixed name."""
        import prepare_review_data

        (self.smm_dir / "sprint.json").write_text(SPRINT_MIXED)
        target = self.smm_dir / f"{_SRI}test-XYZ123"
        prepare_review_data.run(self.smm_dir, target)
        self.assertTrue(target.exists())

    def test_malformed_sprint_returns_none(self):
        """Sprint without sprint_id -> None."""
        import prepare_review_data

        (self.smm_dir / "sprint.json").write_text(SPRINT_NO_ID)
        result = prepare_review_data.run(self.smm_dir, self.smm_dir / f"{_SRI}json")
        self.assertIsNone(result)

    def test_sprint_id_in_output(self):
        """sprint_id matches what's in sprint.json."""
        result = self._run_with(SPRINT_MIXED)
        self.assertEqual(result["sprint_id"], "sprint-001")

    def test_goal_in_output(self):
        """goal matches sprint heading."""
        result = self._run_with(SPRINT_MIXED)
        self.assertEqual(result["goal"], "Build auth system")

    def test_execution_plan_path_set(self):
        """execution_plan.json exists -> execution_plan_path is non-empty."""
        (self.smm_dir / "execution_plan.json").write_text("{}")
        result = self._run_with(SPRINT_MIXED)
        path = result["execution_plan_path"]
        self.assertTrue(path)
        self.assertTrue(Path(path).is_file())

    def test_missing_execution_plan_empty_path(self):
        """No execution_plan.json -> execution_plan_path=''."""
        result = self._run_with(SPRINT_MIXED)
        self.assertEqual(result["execution_plan_path"], "")

    def test_execution_plan_symlink_empty_path(self):
        """execution_plan.json is symlink -> execution_plan_path=''."""
        target = self.smm_dir / "_fake_target.json"
        target.write_text("{}")
        (self.smm_dir / "execution_plan.json").symlink_to(target)
        result = self._run_with(SPRINT_MIXED)
        self.assertEqual(result["execution_plan_path"], "")

    def test_milestone_populated_from_sprint(self):
        """Sprint with Milestone header -> milestone key populated."""
        result = self._run_with(SPRINT_WITH_MILESTONE)
        self.assertEqual(result["milestone"], "Milestone 1: Auth Foundation")

    def test_milestone_empty_when_not_in_sprint(self):
        """Sprint without Milestone header -> milestone is ''."""
        result = self._run_with(SPRINT_MIXED)
        self.assertEqual(result["milestone"], "")

    def test_execution_plan_path_key_always_present(self):
        """execution_plan_path always present as key in output."""
        result = self._run_with(SPRINT_MIXED)
        self.assertIn("execution_plan_path", result)


# ===========================================================================
# sprint_review_done.py
# ===========================================================================


# ===========================================================================
# preload.sh — Integration tests
# ===========================================================================

_PRELOAD_SCRIPT = (
    Path(__file__).parent.parent.parent
    / "skills"
    / "xp-sprint-review"
    / "scripts"
    / "preload.sh"
)


class TestSprintReviewPreload(_IntegrationTestCase):
    """M11: preload.sh runs prepare_review_data and outputs paths."""

    def test_preload_outputs_smm_dir(self):
        """Preload output includes SMM_DIR= line."""
        (self.smm_dir / "sprint.json").write_text(SPRINT_MIXED)
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("SMM_DIR=", result.stdout)

    def test_preload_outputs_review_input(self):
        """Preload output includes REVIEW_INPUT= line."""
        (self.smm_dir / "sprint.json").write_text(SPRINT_MIXED)
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("REVIEW_INPUT=", result.stdout)

    def test_preload_no_sprint_graceful(self):
        """No sprint.json -> exits 0, no REVIEW_INPUT."""
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("REVIEW_INPUT=", result.stdout)

    def test_preload_no_guide_or_smm(self):
        """Preload is minimal — no guide, no SMM injection."""
        (self.smm_dir / "sprint.json").write_text(SPRINT_MIXED)
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("Extreme Programming", result.stdout)
        self.assertNotIn("Shared Mental Model", result.stdout)

    def test_preload_creates_review_input_file_via_mktemp(self):
        """Preload creates a per-invocation .sprint-review-input.XXXXXX tempfile."""
        (self.smm_dir / "sprint.json").write_text(SPRINT_MIXED)
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        candidates = list(self.smm_dir.glob(f"{_SRI}*"))
        self.assertEqual(len(candidates), 1, candidates)
        self.assertNotEqual(candidates[0].name, f"{_SRI}json")

    def test_preload_review_input_path_is_unique_per_call(self):
        """Two preload calls produce distinct REVIEW_INPUT paths."""
        (self.smm_dir / "sprint.json").write_text(SPRINT_MIXED)
        first = self._run_preload(_PRELOAD_SCRIPT).stdout
        second = self._run_preload(_PRELOAD_SCRIPT).stdout
        # Each REVIEW_INPUT line carries the absolute path; extract the path.
        first_path = first.split("REVIEW_INPUT=", 1)[1].split("\n", 1)[0].strip()
        second_path = second.split("REVIEW_INPUT=", 1)[1].split("\n", 1)[0].strip()
        self.assertNotEqual(first_path, second_path)

    def test_preload_no_sprint_does_not_leave_stale_tempfile(self):
        """When prep returns no data, the mktemp file is removed."""
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(list(self.smm_dir.glob(f"{_SRI}*")), [])


# ===========================================================================
# PR-creation removal (sprint-032 story-002)
# ===========================================================================


_SPRINT_REVIEWER_AGENT = _PLUGIN_ROOT / "agents" / "xp-sprint-reviewer.md"
_SPRINT_REVIEW_SKILL = _PLUGIN_ROOT / "skills" / "xp-sprint-review" / "SKILL.md"


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
    on the producer side alone. `test_review_input_structure` pins the
    producer half of the contract; this pins the consumer half."""

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
