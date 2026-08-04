#!/usr/bin/env python3
"""Throwaway: a failing-first check on the Codex hook registration itself.

A config edit needs a red-then-green check as much as code does, and this one
more than most. This story registers shipped handlers on the second harness for
the FIRST time, and the failure mode of a mistyped path or a handler that dies
on import is `"not blocked"` — the exact string no-go criterion 3 produces when
it genuinely fails. Criterion 3 is the verdict, so a typo would be recorded as a
finding.

So: every command path a hook registers must resolve to a file that exists, the
handlers this story depends on must actually be registered, and the confounding
probe must be gone. Checked offline, before a Codex run is spent.

Deleted with the rest of the rig at sprint close. Run explicitly:
    pytest plugins/xp-agents/spike/test_hook_registration.py
"""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

_PLUGIN_ROOT = Path(__file__).resolve().parent.parent
_HOOKS_CODEX = _PLUGIN_ROOT / "hooks" / "hooks.codex.json"
_PLUGIN_ROOT_VAR = "${CLAUDE_PLUGIN_ROOT}/"


def load_hooks(path: Path = _HOOKS_CODEX) -> dict:
    """The registration file, parsed. Raises rather than returning {} — an empty
    mapping would make every check below pass by finding nothing to object to."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data.get("hooks"), dict):
        raise ValueError(f"{path} has no 'hooks' mapping")
    return data["hooks"]


def registered_commands(hooks: dict) -> list[tuple[str, str, str]]:
    """(event, matcher, command) for every registered hook, in file order."""
    out: list[tuple[str, str, str]] = []
    for event, entries in hooks.items():
        for entry in entries:
            matcher = entry.get("matcher", "")
            for hook in entry.get("hooks", []):
                out.append((event, matcher, hook.get("command", "")))
    return out


def unresolvable_paths(hooks: dict, plugin_root: Path = _PLUGIN_ROOT) -> list[str]:
    """Commands naming a plugin-root-relative script that does not exist.

    The whole point of this module: a `${CLAUDE_PLUGIN_ROOT}` path that does not
    resolve produces a hook that cannot run, and a hook that cannot run is
    indistinguishable from a gate that chose to allow.
    """
    missing = []
    for _event, _matcher, command in registered_commands(hooks):
        if _PLUGIN_ROOT_VAR not in command:
            continue
        rel = command.split(_PLUGIN_ROOT_VAR, 1)[1].split()[0]
        if not (plugin_root / rel).is_file():
            missing.append(command)
    return missing


def commands_for(hooks: dict, event: str) -> list[str]:
    return [c for e, _m, c in registered_commands(hooks) if e == event]


def matchers_for(hooks: dict, event: str) -> list[str]:
    return [entry.get("matcher", "") for entry in hooks.get(event, [])]


class TestPathsResolve(unittest.TestCase):
    def test_every_registered_command_path_exists(self) -> None:
        self.assertEqual(unresolvable_paths(load_hooks()), [])

    def test_a_bad_path_is_actually_caught(self) -> None:
        # Negative control. Without it the check above passes vacuously against
        # a resolver that never resolves anything -- which is precisely the
        # failure it exists to prevent, one level up.
        fake = {
            "PreToolUse": [
                {
                    "matcher": "Bash",
                    "hooks": [
                        {
                            "type": "command",
                            "command": (
                                "python3 ${CLAUDE_PLUGIN_ROOT}/scripts/"
                                "does_not_exist_anywhere.py"
                            ),
                        }
                    ],
                }
            ]
        }
        self.assertEqual(len(unresolvable_paths(fake)), 1)

    def test_an_empty_hooks_mapping_raises(self) -> None:
        # A file that parses but registers nothing would satisfy every
        # "no unresolvable paths" check by having no paths at all.
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            bad = Path(td) / "hooks.json"
            bad.write_text(json.dumps({"name": "x"}), encoding="utf-8")
            with self.assertRaises(ValueError):
                load_hooks(bad)


class TestTheConfoundIsGone(unittest.TestCase):
    def test_skill_inject_is_not_registered(self) -> None:
        # story-010 left `_skill_inject.py` live on PreToolUse:Bash, where it
        # runs a preload (up to 30s) and injects on ANY Bash call naming a skill
        # path. This story measures PreToolUse:Bash, so it is a direct confound.
        commands = [c for _e, _m, c in registered_commands(load_hooks())]
        self.assertEqual([c for c in commands if "_skill_inject" in c], [])


class TestTheHandlersThisStoryNeeds(unittest.TestCase):
    def test_the_commit_gate_is_registered_on_bash(self) -> None:
        # AC-1's whole premise. Nothing shipped has ever run on this harness.
        bash_entries = [
            c
            for e, m, c in registered_commands(load_hooks())
            if e == "PreToolUse" and m == "Bash"
        ]
        self.assertTrue(
            any("scripts/pre_tool_bash.py" in c for c in bash_entries), bash_entries
        )

    def test_a_matcherless_pretooluse_entry_records_every_tool(self) -> None:
        # AC-1's interception enumeration: with no matcher, the recorder sees
        # every tool the model calls, which is how the shell tool's `tool_name`
        # gets QUOTED rather than inferred. The dump currently infers it.
        self.assertIn("", matchers_for(load_hooks(), "PreToolUse"))

    def test_session_start_runs_the_real_handler_for_the_guide(self) -> None:
        # AC-4 measures compliance with TEAMMATE_GUIDE prose, which only ever
        # reaches the model through session_start's teammate branch.
        commands = commands_for(load_hooks(), "SessionStart")
        self.assertTrue(
            any("scripts/session_start.py" in c for c in commands), commands
        )

    def test_probe_resolve_stays_registered(self) -> None:
        # It records `resolved_smm_dir`, the only evidence that a shipped
        # handler wrote the SCRATCH SMM rather than the project's. Dropping it
        # was a live mistake in the first draft of this story's plan.
        commands = commands_for(load_hooks(), "SessionStart")
        self.assertTrue(any("_probe_resolve.py" in c for c in commands), commands)


if __name__ == "__main__":
    unittest.main()
