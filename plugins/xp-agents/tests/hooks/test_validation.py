#!/usr/bin/env python3
"""Tests for milestone checks, hooks.json validation, and plugin integrity.

Split from the monolithic test_hooks.py.
"""

import ast
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import _common

# ===========================================================================
# hooks.json M3.4 registration tests
# ===========================================================================


class TestM34HooksConfig(unittest.TestCase):
    def setUp(self):
        hooks_path = Path(__file__).parent.parent.parent / "hooks" / "hooks.json"
        with open(hooks_path) as f:
            self.data = json.load(f)

    def test_hooks_json_has_user_prompt_submit(self):
        self.assertIn("UserPromptSubmit", self.data["hooks"])

    def test_user_prompt_submit_command(self):
        hooks = self.data["hooks"]["UserPromptSubmit"][0]["hooks"]
        cmds = [h["command"] for h in hooks]
        self.assertTrue(any("user_prompt_log.py" in c for c in cmds))

    def test_hooks_json_has_subagent_stop(self):
        self.assertIn("SubagentStop", self.data["hooks"])

    def test_subagent_stop_command(self):
        # Find the catch-all entry (no matcher) that has subagent_stop.py
        for entry in self.data["hooks"]["SubagentStop"]:
            if "matcher" not in entry:
                hooks = entry["hooks"]
                cmds = [h["command"] for h in hooks if "command" in h]
                self.assertTrue(any("subagent_stop.py" in c for c in cmds))
                return
        self.fail("No catch-all SubagentStop entry found")

    def test_subagent_stop_has_timeout(self):
        for entry in self.data["hooks"]["SubagentStop"]:
            if "matcher" not in entry:
                self.assertEqual(entry["hooks"][0]["timeout"], 5000)
                return
        self.fail("No catch-all SubagentStop entry found")


# ===========================================================================
# hooks.json test base class
# ===========================================================================


class _HooksJsonTestCase(unittest.TestCase):
    """Base class for hooks.json registration tests."""

    def setUp(self):
        hooks_path = Path(__file__).parent.parent.parent / "hooks" / "hooks.json"
        with open(hooks_path) as f:
            self.data = json.load(f)

    def _find_matcher_entry(self, hook_event: str, matcher: str) -> dict | None:
        """Find the entry with the given matcher in a hook event list."""
        for entry in self.data["hooks"].get(hook_event, []):
            if entry.get("matcher") == matcher:
                return entry
        return None

    def _find_default_entry(self, hook_event: str) -> dict | None:
        """Find an entry without a matcher (default) in a hook event list."""
        for entry in self.data["hooks"].get(hook_event, []):
            if "matcher" not in entry:
                return entry
        return None


# ===========================================================================
# hooks.json M4 registration tests
# ===========================================================================


_STRUCTURED_OUTPUT_FUNCS = frozenset({"hook_output", "block_output"})
_ASYNC_OUTPUT_OK_MARKER = "async-output-ok"


def _async_hook_scripts(hooks_config: dict) -> list[Path]:
    """Walk hooks.json and return paths of every script with async: true.

    Scans command tokens for the first `.py` argument (rather than just the
    last token) so future hooks with trailing flags
    (e.g. `python3 foo.py --verbose`) still get caught by the integrity check.
    """
    scripts: list[Path] = []
    for entries in hooks_config.values():
        for entry in entries:
            for h in entry.get("hooks", []):
                if not h.get("async"):
                    continue
                cmd = h.get("command", "")
                if not cmd:
                    continue
                py_token = next(
                    (t for t in cmd.split() if t.endswith(".py")),
                    None,
                )
                if py_token is None:
                    continue
                scripts.append(Path(_common.expand_plugin_root(py_token)))
    return scripts


def _has_line_anchored_marker(docstring: str, marker: str) -> bool:
    """True iff `marker` appears as its own (stripped) docstring line."""
    return any(line.strip() == marker for line in docstring.splitlines())


def _calls_any(tree: ast.AST, names: frozenset[str]) -> bool:
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr in names:
            return True
        if isinstance(func, ast.Name) and func.id in names:
            return True
    return False


class TestAsyncHookScriptsParser(unittest.TestCase):
    """_async_hook_scripts must catch scripts even when commands have trailing flags."""

    def test_picks_py_token_with_trailing_flags(self):
        """A future hook with `python3 foo.py --verbose` must still be checked."""
        cmd = "python3 ${CLAUDE_PLUGIN_ROOT}/scripts/foo.py --verbose --arg val"
        config = {
            "PostToolUse": [
                {
                    "matcher": "Bash",
                    "hooks": [{"command": cmd, "async": True}],
                }
            ]
        }
        scripts = _async_hook_scripts(config)
        self.assertEqual(len(scripts), 1)
        self.assertTrue(str(scripts[0]).endswith("/scripts/foo.py"))

    def test_skips_when_no_py_token(self):
        """Commands without any .py token are skipped, not errored."""
        cmd = "/usr/bin/some-binary --flag"
        config = {
            "PostToolUse": [
                {"hooks": [{"command": cmd, "async": True}]},
            ]
        }
        self.assertEqual(_async_hook_scripts(config), [])


class TestAsyncHooksHaveNoStructuredReturn(_HooksJsonTestCase):
    """Async hooks have their return value discarded by Claude Code.

    When `async: true`, the hook runs in the background and `hookSpecificOutput`
    is dropped — the agent never sees additionalContext, decision blocks, or
    stderr-via-exit-2 from such a hook. So any async hook script that calls
    `_common.hook_output` or `_common.block_output` is silently leaking work.

    Escape valve: a script may opt out by including the line `async-output-ok`
    on its own line in the module docstring. Use only when the structured
    output is genuinely fire-and-forget (e.g., logged to a sidecar) and
    document why immediately above the marker.
    """

    def test_no_async_hook_calls_structured_output_helpers(self):
        violations: list[str] = []
        for script in _async_hook_scripts(self.data["hooks"]):
            if not script.is_file():
                continue
            tree = ast.parse(script.read_text(encoding="utf-8"))
            doc = ast.get_docstring(tree) or ""
            if _has_line_anchored_marker(doc, _ASYNC_OUTPUT_OK_MARKER):
                continue
            if _calls_any(tree, _STRUCTURED_OUTPUT_FUNCS):
                violations.append(script.name)
        self.assertEqual(
            violations,
            [],
            (
                "async:true hooks must not call hook_output / block_output — "
                f"agent never sees the return. Violations: {violations}"
            ),
        )


class TestHooksJsonM4(_HooksJsonTestCase):
    """Verify hooks.json M4 registrations (agent hooks removed in M6.5)."""

    def test_pretooluse_write_matcher(self):
        entry = self._find_matcher_entry("PreToolUse", "Write|Edit|MultiEdit")
        self.assertIsNotNone(entry, "PreToolUse Write|Edit|MultiEdit entry missing")

    def test_pretooluse_bash_matcher(self):
        entry = self._find_matcher_entry("PreToolUse", "Bash")
        self.assertIsNotNone(entry, "PreToolUse Bash entry missing")

    def test_pretooluse_no_star_matcher(self):
        """Star matcher removed — split into Write|Edit|MultiEdit and Bash."""
        entry = self._find_matcher_entry("PreToolUse", "*")
        self.assertIsNone(entry, "PreToolUse * matcher should be removed")

    def test_posttooluse_no_agent_hooks(self):
        """Quality reviewer agent hook removed in M6.5."""
        entry = self._find_matcher_entry("PostToolUse", "Write|Edit|MultiEdit")
        agents = [h for h in entry["hooks"] if h.get("type") == "agent"]
        self.assertEqual(len(agents), 0, "No agent hooks should remain in PostToolUse")

    def test_subagentstop_no_plan_matcher(self):
        """Plan matcher entry removed in M6.5 (plan review via subagent now)."""
        entry = self._find_matcher_entry("SubagentStop", "Plan")
        self.assertIsNone(entry, "SubagentStop Plan matcher entry should be removed")


# ===========================================================================
# Prompt file tests (Milestone 5)
# ===========================================================================


class TestPromptFilesM5(unittest.TestCase):
    """Verify prompt files state after tdd_check.md replaced by command hook."""

    def setUp(self):
        self.prompts_dir = Path(__file__).parent.parent.parent / "prompts"

    def test_tdd_check_md_deleted(self):
        """tdd_check.md removed — replaced by tdd_stop_gate.py command hook."""
        self.assertFalse((self.prompts_dir / "tdd_check.md").exists())


# ===========================================================================
# M5.3 acceptance criteria — prompt content verification
# ===========================================================================


class TestM53AcceptanceCriteria(unittest.TestCase):
    """Verify M5.3 acceptance criteria are met.

    Prompt content checks updated in M6.5 to point to agents/ directory
    (agent hook prompts moved to plugin subagents).
    Testable behaviors verified in their respective test classes:
    - TestPreToolUseEnforcement (ACs 1-2)
    - TestLoadEnforcementMode (AC 3)
    - TestFindDebtForFile (AC 9)
    - TestPreToolUseDebtInjection (AC 10)
    - TestPreToolUseActiveContext (AC 15)
    """

    def setUp(self):
        self.agents_dir = Path(__file__).parent.parent.parent / "agents"

    # AC 4: first session asks for goals (now in xp-work-selection)
    def test_work_selection_has_goal_recording(self):
        skill_dir = Path(__file__).parent.parent.parent / "skills" / "xp-work-selection"
        content = (skill_dir / "SKILL.md").read_text()
        self.assertIn('--type "goal"', content)

    # AC 5-8: question triage + intent reconciliation (now in
    # xp-work-selection for questions, xp-housekeeper for intents)
    def test_work_selection_has_question_triage(self):
        skill_dir = Path(__file__).parent.parent.parent / "skills" / "xp-work-selection"
        content = (skill_dir / "SKILL.md").read_text()
        self.assertIn("Open Questions", content)
        self.assertIn("triage-adopt", content)

    # AC 12: retrospective escalates aging debt
    def test_retrospective_escalates_aging_debt(self):
        content = (self.agents_dir / "xp-retrospective.md").read_text()
        self.assertIn("Escalating aging debt", content)
        self.assertIn("high-priority", content)

    # AC 13: retrospective flags plugin health anomalies
    def test_retrospective_plugin_health(self):
        content = (self.agents_dir / "xp-retrospective.md").read_text()
        self.assertIn("Plugin Health", content)
        self.assertIn("session_stats", content)
        self.assertIn("concern", content)

    # AC 14: cross-session trends
    def test_retrospective_cross_session_trends(self):
        content = (self.agents_dir / "xp-retrospective.md").read_text()
        self.assertIn("previous_retros", content)
        self.assertIn("cross-session", content.lower())


# ===========================================================================
# hooks.json M5 registration tests
# ===========================================================================


class TestHooksJsonM5(_HooksJsonTestCase):
    """Verify hooks.json has all M5 hook registrations."""

    # --- SessionStart: retrospective.py command ---

    def test_session_start_has_retrospective_command(self):
        entry = self._find_matcher_entry("SessionStart", "startup|resume|compact|clear")
        commands = [h for h in entry["hooks"] if h.get("type") == "command"]
        self.assertTrue(
            any("retrospective.py" in h["command"] for h in commands),
            "retrospective.py command hook missing from SessionStart",
        )

    # --- SessionStart: agent hooks removed in M6.5 ---

    def test_session_start_no_agent_hooks(self):
        """Retro analyst and customer proxy agent hooks removed in M6.5."""
        entry = self._find_matcher_entry("SessionStart", "startup|resume|compact|clear")
        agents = [h for h in entry["hooks"] if h.get("type") == "agent"]
        self.assertEqual(len(agents), 0, "No agent hooks should remain in SessionStart")

    # --- SubagentStop: agent hooks removed in M6.5 ---

    def test_subagentstop_no_agent_hooks(self):
        """Subagent reviewer agent hook removed in M6.5."""
        for entry in self.data["hooks"]["SubagentStop"]:
            agents = [h for h in entry["hooks"] if h.get("type") == "agent"]
            self.assertEqual(
                len(agents), 0, "No agent hooks should remain in SubagentStop"
            )

    # --- Stop: tdd_stop_gate command hook ---

    def test_stop_hook_exists(self):
        self.assertIn("Stop", self.data["hooks"], "Stop hook section missing")

    def test_stop_hook_has_tdd_gate_command(self):
        entries = self.data["hooks"]["Stop"]
        all_hooks = []
        for entry in entries:
            all_hooks.extend(entry.get("hooks", []))
        commands = [h for h in all_hooks if h.get("type") == "command"]
        self.assertTrue(
            any("tdd_stop_gate.py" in h["command"] for h in commands),
            "tdd_stop_gate.py command hook missing from Stop",
        )

    def test_stop_hook_no_prompt_hooks(self):
        """Prompt hooks replaced by command hooks — none should remain."""
        entries = self.data["hooks"]["Stop"]
        all_hooks = []
        for entry in entries:
            all_hooks.extend(entry.get("hooks", []))
        prompts = [h for h in all_hooks if h.get("type") == "prompt"]
        self.assertEqual(len(prompts), 0, "No prompt hooks should remain in Stop")


# ===========================================================================
# hooks.json M5.4 registration tests
# ===========================================================================


class TestHooksJsonM54(_HooksJsonTestCase):
    """Verify hooks.json has M5.4 hook registrations."""

    def test_stop_has_tdd_gate_command(self):
        entries = self.data["hooks"]["Stop"]
        all_hooks = []
        for entry in entries:
            all_hooks.extend(entry.get("hooks", []))
        commands = [h for h in all_hooks if h.get("type") == "command"]
        self.assertTrue(
            any("tdd_stop_gate.py" in h["command"] for h in commands),
            "tdd_stop_gate.py command hook missing from Stop",
        )

    def test_stop_has_five_hooks(self):
        entries = self.data["hooks"]["Stop"]
        all_hooks = []
        for entry in entries:
            all_hooks.extend(entry.get("hooks", []))
        self.assertEqual(
            len(all_hooks),
            5,
            "Expected 5 Stop hooks (TDD + sprint + housekeeping + warning"
            f" + teammate), got {len(all_hooks)}",
        )
        commands = [h["command"] for h in all_hooks if "command" in h]
        self.assertTrue(any("sprint_stop_gate.py" in c for c in commands))
        self.assertTrue(any("housekeeping_stop_gate.py" in c for c in commands))
        self.assertTrue(any("session_end_warning.py" in c for c in commands))
        self.assertTrue(any("teammate_stop_gate.py" in c for c in commands))


# ===========================================================================
# hooks.json gap fixes — PostToolUseFailure + SessionStart clear
# ===========================================================================


class TestHooksJsonGapFixes(_HooksJsonTestCase):
    """Verify hooks.json registrations for PostToolUseFailure and clear matcher."""

    def test_post_tool_use_failure_section_exists(self):
        self.assertIn(
            "PostToolUseFailure",
            self.data["hooks"],
            "PostToolUseFailure section missing from hooks.json",
        )

    def test_post_tool_use_failure_has_bash_matcher(self):
        entries = self.data["hooks"]["PostToolUseFailure"]
        matchers = [e.get("matcher") for e in entries]
        self.assertIn("Bash", matchers)

    def test_post_tool_use_failure_has_bash_failure_command(self):
        entries = self.data["hooks"]["PostToolUseFailure"]
        all_hooks = []
        for entry in entries:
            all_hooks.extend(entry.get("hooks", []))
        commands = [h for h in all_hooks if h.get("type") == "command"]
        self.assertTrue(
            any("bash_failure.py" in h["command"] for h in commands),
            "bash_failure.py missing from PostToolUseFailure",
        )

    def test_post_tool_use_failure_has_ask_user_question_matcher(self):
        entries = self.data["hooks"]["PostToolUseFailure"]
        matchers = [e.get("matcher") for e in entries]
        self.assertIn(
            "AskUserQuestion",
            matchers,
            "AskUserQuestion missing from PostToolUseFailure",
        )

    def test_post_tool_use_failure_ask_user_has_question_answered(self):
        entries = self.data["hooks"]["PostToolUseFailure"]
        ask_entry = next(e for e in entries if e.get("matcher") == "AskUserQuestion")
        commands = [h["command"] for h in ask_entry.get("hooks", [])]
        self.assertTrue(
            any("question_answered.py" in c for c in commands),
            "question_answered.py missing from PostToolUseFailure",
        )

    def test_session_start_includes_clear_matcher(self):
        entry = self._find_matcher_entry("SessionStart", "startup|resume|compact|clear")
        self.assertIsNotNone(entry, "SessionStart matcher should include 'clear'")


# ===========================================================================
# Milestone 6.5: Agent Hook → Plugin Subagent Migration
# ===========================================================================


class TestHooksJsonM65(_HooksJsonTestCase):
    """Verify no agent hooks remain in hooks.json after M6.5 migration."""

    def test_no_agent_hooks_anywhere(self):
        """hooks.json should have zero type: agent entries."""
        for event_name, entries in self.data["hooks"].items():
            for entry in entries:
                for hook in entry.get("hooks", []):
                    self.assertNotEqual(
                        hook.get("type"),
                        "agent",
                        f"Found agent hook in {event_name}: {hook}",
                    )

    def test_hooks_json_has_worktree_create(self):
        """WorktreeCreate hook must be registered."""
        self.assertIn("WorktreeCreate", self.data["hooks"])

    def test_worktree_create_command(self):
        """WorktreeCreate must reference worktree_create.py."""
        entry = self._find_default_entry("WorktreeCreate")
        self.assertIsNotNone(entry, "No default WorktreeCreate entry")
        cmds = [h["command"] for h in entry["hooks"]]
        self.assertTrue(any("worktree_create.py" in c for c in cmds))

    def test_only_command_and_prompt_types(self):
        """All hooks should be type: command or type: prompt."""
        valid_types = {"command", "prompt"}
        for event_name, entries in self.data["hooks"].items():
            for entry in entries:
                for hook in entry.get("hooks", []):
                    self.assertIn(
                        hook.get("type"),
                        valid_types,
                        f"Invalid hook type in {event_name}: {hook.get('type')}",
                    )

    def test_no_prompt_hooks_remain(self):
        """All prompt hooks replaced by command hooks — none should remain."""
        prompt_hooks = []
        for event_name, entries in self.data["hooks"].items():
            for entry in entries:
                for hook in entry.get("hooks", []):
                    if hook.get("type") == "prompt":
                        prompt_hooks.append((event_name, hook))
        self.assertEqual(len(prompt_hooks), 0, "No prompt hooks should remain")


# ===========================================================================
# Story-003: Echo-gate hook registration
# ===========================================================================


class TestEchoGateHookRegistration(_HooksJsonTestCase):
    """Verify pre_tool_echo_gate.py is registered on PreToolUse only."""

    def _all_commands(self, event_name: str) -> list[str]:
        commands: list[str] = []
        for entry in self.data["hooks"].get(event_name, []):
            for hook in entry.get("hooks", []):
                cmd = hook.get("command", "")
                if cmd:
                    commands.append(cmd)
        return commands

    def test_echo_gate_registered_for_pretooluse(self):
        """Echo-gate must fire before Agent/Write/Edit/MultiEdit/Bash/Skill."""
        cmds = self._all_commands("PreToolUse")
        self.assertTrue(
            any("pre_tool_echo_gate.py" in c for c in cmds),
            f"pre_tool_echo_gate.py missing from PreToolUse; got: {cmds}",
        )

    def test_echo_gate_pretooluse_matcher_covers_required_tools(self):
        """The entry registering echo-gate must target Agent, Write, Edit,
        MultiEdit, Bash, and Skill so kickoff renders are enforced before
        the next agent invocation, write, edit, bash run, or skill call."""
        required = {"Agent", "Write", "Edit", "MultiEdit", "Bash", "Skill"}
        for entry in self.data["hooks"].get("PreToolUse", []):
            matcher = entry.get("matcher", "")
            hook_cmds = [h.get("command", "") for h in entry.get("hooks", [])]
            if any("pre_tool_echo_gate.py" in c for c in hook_cmds):
                matcher_tokens = set(matcher.split("|"))
                missing = required - matcher_tokens
                self.assertEqual(
                    missing,
                    set(),
                    f"echo-gate PreToolUse matcher '{matcher}' missing {missing}",
                )
                return
        self.fail("No PreToolUse entry registers pre_tool_echo_gate.py")

    def test_echo_gate_not_registered_for_user_prompt_submit(self):
        """Echo-gate enforces agent discipline; blocking the user is the wrong actor."""
        cmds = self._all_commands("UserPromptSubmit")
        self.assertFalse(
            any("pre_tool_echo_gate.py" in c for c in cmds),
            f"pre_tool_echo_gate.py must not appear in UserPromptSubmit; got: {cmds}",
        )


if __name__ == "__main__":
    unittest.main()
