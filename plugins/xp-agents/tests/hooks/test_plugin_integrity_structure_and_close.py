#!/usr/bin/env python3
"""Tests for plugin file structure, milestone files, and plugin integrity.

Split from test_validation.py for file size management, then split again
from test_plugin_integrity.py for the same reason. This file covers the
M7 marketplace.json/hooks.json structural checks, the M-8 worktree-commit
doctrine pins, and the M-2 close-skill step-ordering pins. See
test_plugin_integrity_release_and_content.py for release-artifact sync and
the M6/M6.5 guide, skill, and subagent file checks.
"""

import json
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from _bases import _PLUGIN_ROOT
from _close_fixtures import _assert_text_ordering
from scaffold._helpers import frontmatter_body

# ===========================================================================
# M7: Plugin Integrity
# ===========================================================================


class TestPluginIntegrity(unittest.TestCase):
    """M7: marketplace.json, hooks.json references, and structural checks."""

    def setUp(self):
        self.plugin_root = _PLUGIN_ROOT

    def test_marketplace_json_exists_and_valid(self):
        """marketplace.json has required fields."""
        mp = self.plugin_root / ".claude-plugin" / "marketplace.json"
        self.assertTrue(mp.is_file(), "Missing .claude-plugin/marketplace.json")
        data = json.loads(mp.read_text())
        self.assertIn("name", data)
        self.assertIn("owner", data)
        self.assertIn("name", data["owner"])
        self.assertIn("plugins", data)
        self.assertIsInstance(data["plugins"], list)
        self.assertGreater(len(data["plugins"]), 0)
        for plugin in data["plugins"]:
            self.assertIn("name", plugin)
            self.assertIn("source", plugin)
            self.assertIn("description", plugin)

    def test_plugin_json_exists_and_valid(self):
        """plugin.json has required fields."""
        pj = self.plugin_root / ".claude-plugin" / "plugin.json"
        self.assertTrue(pj.is_file())
        data = json.loads(pj.read_text())
        self.assertIn("name", data)
        self.assertIn("version", data)
        # hooks/hooks.json is auto-discovered; must NOT be in manifest
        self.assertNotIn("hooks", data)

    def _assert_hook_paths_exist(self, hook_type: str, path_key: str):
        """Verify all hooks of given type reference existing files."""
        hooks_file = self.plugin_root / "hooks" / "hooks.json"
        data = json.loads(hooks_file.read_text())
        for event_name, entries in data["hooks"].items():
            for entry in entries:
                for hook in entry.get("hooks", []):
                    if hook.get("type") != hook_type:
                        continue
                    raw = hook[path_key]
                    # Strip interpreter prefix (e.g. "python3 ")
                    marker = "${CLAUDE_PLUGIN_ROOT}"
                    if marker in raw:
                        path_part = raw.split(marker)[-1]
                        resolved = str(self.plugin_root) + path_part
                    else:
                        resolved = raw
                    self.assertTrue(
                        Path(resolved).is_file(),
                        f"Missing {hook_type}: {raw} (event: {event_name})",
                    )

    def test_all_hook_scripts_exist(self):
        """Every command script referenced in hooks.json exists on disk."""
        self._assert_hook_paths_exist("command", "command")

    def test_all_prompt_hooks_exist(self):
        """Every prompt file referenced in hooks.json exists on disk."""
        self._assert_hook_paths_exist("prompt", "prompt")

    def test_kickoff_skill_has_sprint_steps(self):
        """Kickoff SKILL.md must have the redesigned flow steps."""
        skill_file = self.plugin_root / "skills" / "xp-kickoff" / "SKILL.md"
        content = skill_file.read_text()
        self.assertIn("Execution Plan", content)
        self.assertIn("Sprint", content)
        self.assertIn("Work Selection", content)
        self.assertIn("Housekeeping", content)

    def test_kickoff_skill_has_read_tool(self):
        """M8b: kickoff SKILL.md must have Read in allowed-tools."""
        skill_file = self.plugin_root / "skills" / "xp-kickoff" / "SKILL.md"
        content = skill_file.read_text()
        # Extract frontmatter
        match = re.match(r"^---\n(.*?)\n---", content, re.DOTALL)
        assert match is not None
        fm = match.group(1)
        self.assertIn("Read", fm)

    def test_kickoff_skill_no_question_triage_in_sprint_path(self):
        """M8b: sprint-active path should not call /xp-question-triage."""
        skill_file = self.plugin_root / "skills" / "xp-kickoff" / "SKILL.md"
        content = skill_file.read_text()
        # The SPRINT_ACTIVE subsection (between "SPRINT_ACTIVE" and
        # "no SPRINT_ACTIVE") should not mention question-triage
        if "SPRINT_ACTIVE" in content:
            after_sprint = content.split("SPRINT_ACTIVE")[1]
            fallback = after_sprint.find("no SPRINT_ACTIVE")
            sprint_path = after_sprint[:fallback] if fallback > 0 else after_sprint
            self.assertNotIn("xp-question-triage", sprint_path)

    def test_accept_skill_has_story_flow(self):
        """M8c: accept SKILL.md must have acceptance criteria verification."""
        skill_file = self.plugin_root / "skills" / "xp-accept" / "SKILL.md"
        content = skill_file.read_text()
        self.assertIn("acceptance criteria", content.lower())
        self.assertIn("done", content.lower())
        self.assertIn("deferred", content.lower())

    def test_hooks_json_has_sprint_stop_gate(self):
        """hooks.json Stop array must include sprint_stop_gate.py."""
        hooks_path = self.plugin_root / "hooks" / "hooks.json"
        content = hooks_path.read_text()
        self.assertIn("sprint_stop_gate.py", content)

    def test_hooks_json_has_teammate_idle(self):
        """M13: hooks.json TeammateIdle must include teammate_idle.py."""
        hooks_path = self.plugin_root / "hooks" / "hooks.json"
        content = hooks_path.read_text()
        self.assertIn("teammate_idle.py", content)
        self.assertIn("TeammateIdle", content)

    def test_hooks_json_has_task_completed(self):
        """M13: hooks.json TaskCompleted must include task_completed.py."""
        hooks_path = self.plugin_root / "hooks" / "hooks.json"
        content = hooks_path.read_text()
        self.assertIn("task_completed.py", content)
        self.assertIn("TaskCompleted", content)

    def test_no_requirements_or_pyproject(self):
        """No requirements.txt or pyproject.toml with dependencies."""
        for name in ("requirements.txt", "pyproject.toml"):
            path = self.plugin_root / name
            if path.is_file():
                content = path.read_text()
                self.assertNotIn(
                    "install_requires",
                    content,
                    f"{name} should not declare dependencies",
                )
                self.assertNotIn(
                    "dependencies",
                    content,
                    f"{name} should not declare dependencies",
                )

    def test_no_settings_json(self):
        """settings.json should not exist — all config is hardcoded."""
        path = self.plugin_root / "settings.json"
        self.assertFalse(path.is_file())

    def test_guide_files_exist(self):
        """XP_VALUES.md and PROCESS_GUIDE.md exist and are non-trivial."""
        values = self.plugin_root / "XP_VALUES.md"
        process = self.plugin_root / "PROCESS_GUIDE.md"
        self.assertTrue(values.is_file(), "Missing XP_VALUES.md")
        self.assertTrue(process.is_file(), "Missing PROCESS_GUIDE.md")
        combined = values.read_text() + process.read_text()
        self.assertGreater(len(combined), 1000, "Guide files too short combined")


# ===========================================================================
# Sprint-062 / M-8: worktree-commit doctrine pins
# ===========================================================================


class TestWorktreeCommitDoctrine(unittest.TestCase):
    """M-8: close skills + TEAMMATE_GUIDE document the `git -C <worktree>`
    pattern (belt-and-suspenders for stories 002 + 003 hook-level
    enforcement) and the verify_acceptance.py before-reviewing timing.
    """

    def setUp(self):
        self.plugin_root = _PLUGIN_ROOT

    def test_close_skills_have_git_dash_C_guidance(self):
        """`git -C` doctrine appears in the three close-related surfaces.

        Pinned: shared close-pipeline template (raw read), xp-accept body
        (frontmatter-stripped — skill .md body and frontmatter are separate
        concerns; doctrine lives in body), and TEAMMATE_GUIDE.md.
        """
        shared = self.plugin_root / "scripts" / "_close_pipeline_shared.md"
        accept = self.plugin_root / "skills" / "xp-accept" / "SKILL.md"
        guide = self.plugin_root / "TEAMMATE_GUIDE.md"

        self.assertIn(
            "git -C",
            shared.read_text(),
            "_close_pipeline_shared.md missing `git -C` worktree-commit guidance",
        )
        _, accept_body = frontmatter_body(accept.read_text())
        self.assertIn(
            "git -C",
            accept_body,
            "xp-accept/SKILL.md body missing `git -C` worktree-commit guidance "
            "(frontmatter stripped before grep)",
        )
        self.assertIn(
            "git -C",
            guide.read_text(),
            "TEAMMATE_GUIDE.md missing `git -C` worktree-commit guidance",
        )

    def test_teammate_guide_mentions_verify_acceptance(self):
        """TEAMMATE_GUIDE.md tells teammates to run verify_acceptance.py
        before flipping a story to `reviewing`.

        Co-located test: the timing phrase ("before flipping … reviewing")
        must appear in the same paragraph/bullet as the CLI mention so a
        future edit can't drop the timing while keeping the reference.
        """
        guide_text = (self.plugin_root / "TEAMMATE_GUIDE.md").read_text()
        self.assertIn(
            "verify_acceptance.py",
            guide_text,
            "TEAMMATE_GUIDE.md missing verify_acceptance.py reference",
        )
        # Find the line/bullet mentioning the CLI; assert the timing
        # phrase ("before flipping ... reviewing") sits within ±2 lines
        # of it so the two facts cannot drift apart.
        lines = guide_text.splitlines()
        cli_idxs = [i for i, ln in enumerate(lines) if "verify_acceptance.py" in ln]
        self.assertTrue(cli_idxs, "expected at least one verify_acceptance.py line")
        timing_re = re.compile(r"before\s+flipping.*reviewing", re.IGNORECASE)
        found_nearby = any(
            timing_re.search(" ".join(lines[max(0, i - 2) : i + 3])) for i in cli_idxs
        )
        self.assertTrue(
            found_nearby,
            "TEAMMATE_GUIDE.md missing 'before flipping … reviewing' timing "
            "near the verify_acceptance.py mention",
        )


# ===========================================================================
# Sprint-063 / M-2 / story-002: close-cycle step ordering swap
# ===========================================================================


_CLOSE_SKILL_MDS = {
    "free": _PLUGIN_ROOT / "skills" / "xp-free-close" / "SKILL.md",
    "sprint": _PLUGIN_ROOT / "skills" / "xp-sprint-close" / "SKILL.md",
    "plan": _PLUGIN_ROOT / "skills" / "xp-plan-close" / "SKILL.md",
}


class TestCloseSkillStepOrdering(unittest.TestCase):
    """M-2 step-order swap: `/security-review` runs FIRST (Step 4), then
    close-reviewer fork runs LAST (Step 4.5). The reorder solves the
    close-cycle stall — security review's SECURITY_COMPLETE event lands
    while the agent is still gated by the CLOSE_CYCLE_ACTIVE marker, so
    when the close-reviewer's SubagentStop consumes the marker, the
    agent's next attention is on the merge.

    Pins the ordering invariant across the three close-skill SKILL.md
    files (free/sprint/plan) so a future edit can't silently revert to
    the old order. xp-story-close never runs security-review (defers to
    its enclosing sprint-close) and is excluded from this iteration.

    Cross-doc reference: `skills/xp-story-close/SKILL.md` (just before
    the `## Step 4.5: Fork the close-reviewer` heading) names this
    class explicitly when explaining why story-close skips Step 4 yet
    keeps the `4.5` numbering. If this class is renamed, update that
    reference too.
    """

    def test_close_skills_security_before_close_reviewer(self):
        """`## Step 4: ` (Security) precedes `## Step 4.5: ` (Fork
        close-reviewer) in each of the 3 close-skill SKILL.md files.
        Use frontmatter_body() so frontmatter `name:` literals can't
        false-positive on header-substring searches.
        """
        for mode, path in _CLOSE_SKILL_MDS.items():
            with self.subTest(mode=mode):
                _, body = frontmatter_body(path.read_text())
                step4_idx, step4_5_idx = _assert_text_ordering(
                    self,
                    body,
                    "## Step 4: ",
                    "## Step 4.5: ",
                    msg=f"{mode}-close SKILL.md M-2 step-order swap",
                )
                # Pin the content under each header — Step 4 must be the
                # security-review step, Step 4.5 must be the close-reviewer
                # fork. Look only at the heading line itself.
                step4_eol = body.find("\n", step4_idx)
                step4_heading = body[step4_idx:step4_eol]
                self.assertIn(
                    "Security",
                    step4_heading,
                    f"{mode}-close SKILL.md `## Step 4: ` heading must name "
                    f"Security (got: {step4_heading!r})",
                )
                step4_5_eol = body.find("\n", step4_5_idx)
                step4_5_heading = body[step4_5_idx:step4_5_eol]
                # free/sprint/plan use "Fork the close-reviewer"; story-close
                # has the same Fork content under Step 4.5 too.
                fork_or_reviewer = (
                    "Fork" in step4_5_heading or "close-reviewer" in step4_5_heading
                )
                self.assertTrue(
                    fork_or_reviewer,
                    f"{mode}-close SKILL.md `## Step 4.5: ` heading must name "
                    f"Fork or close-reviewer (got: {step4_5_heading!r})",
                )

    # Prose-driven marker-write tests removed in story-002. Behavioral
    # pin moved to tests/integration/test_close_preloads_emit_shared.py
    # (preload arms the marker, not LLM prose).


if __name__ == "__main__":
    unittest.main()
