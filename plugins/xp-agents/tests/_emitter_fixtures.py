#!/usr/bin/env python3
"""Per-emitter fixture builders for `tests/hooks/test_injection_budgets.py`.

Each builder returns the stdin dict needed to drive the emitter's
representative branch via subprocess. Reuses canonical hook-input
factories from `_hook_inputs.py` where shapes match.

Edge-case branches are validated by per-script unit tests in
`tests/hooks/`; this registry drives the cross-cutting byte-budget test.

`subagent_stop.py` writes a real `.assign-pending` marker when fed an
`xp-plan-reviewer` subagent. The budget runner amortizes one SMM across
all emitters; subagent_stop runs LAST in the sweep so the marker stays
out of any sibling emitter's view (see the order-coupling note in
test_injection_budgets.py).
"""

from collections.abc import Callable

from _hook_inputs import (
    _make_agent_input,
    _make_bash_input,
    _make_skill_input,
    _make_stop_input,
    _make_write_input,
)

FixtureBuilder = Callable[[], dict]


def prompt_nugget() -> dict:
    return {"session_id": "t", "agent_id": "main", "prompt": "what is the next step"}


def user_prompt_log() -> dict:
    return {"session_id": "t", "agent_id": "main", "prompt": "investigate the auth bug"}


def session_start() -> dict:
    return {"session_id": "t", "agent_id": "main", "source": "startup"}


def subagent_start() -> dict:
    return _make_agent_input(subagent_type="general-purpose", tool_input={})


def subagent_stop() -> dict:
    return _make_stop_input(agent_id="xp-plan-reviewer", agent_type="xp-plan-reviewer")


def pre_tool_write() -> dict:
    return _make_write_input(
        tool_input={"file_path": "/tmp/x.py", "content": "def f():\n    pass\n"}
    )


def pre_tool_bash() -> dict:
    return _make_bash_input(command="ls")


def lint_check() -> dict:
    return _make_write_input(
        tool_input={"file_path": "/tmp/x.py", "content": ""},
        tool_response={"success": True},
    )


def review_cycle_done() -> dict:
    return _make_skill_input(skill="simplify", tool_response={"success": True})


def retrospective() -> dict:
    return {"session_id": "t", "agent_id": "main", "source": "startup"}


def session_end_warning() -> dict:
    return {"session_id": "t", "agent_id": "main", "stop_hook_active": False}


def pre_tool_skill() -> dict:
    return _make_skill_input(skill="unrelated-skill")


def post_tool_exit_plan() -> dict:
    # agent_type "xp-*" → is_xp_agent True → no-trigger path (no marker written).
    return {
        "session_id": "t",
        "agent_id": "xp-test",
        "agent_type": "xp-test",
        "tool_name": "ExitPlanMode",
        "tool_input": {},
        "tool_response": {},
    }


def kickoff_gate() -> dict:
    return {
        "session_id": "t",
        "agent_id": "main",
        "prompt": "what is the current sprint status",
    }


def bash_post_tool() -> dict:
    return {
        "session_id": "t",
        "agent_id": "main",
        "tool_name": "Bash",
        "tool_input": {"command": "ls"},
        "tool_response": {"stdout": "", "stderr": "", "exit_code": 0},
    }


EMITTER_FIXTURES: dict[str, FixtureBuilder] = {
    "bash_post_tool.py": bash_post_tool,
    "kickoff_gate.py": kickoff_gate,
    "lint_check.py": lint_check,
    "post_tool_exit_plan.py": post_tool_exit_plan,
    "pre_tool_bash.py": pre_tool_bash,
    "pre_tool_skill.py": pre_tool_skill,
    "pre_tool_write.py": pre_tool_write,
    "prompt_nugget.py": prompt_nugget,
    "retrospective.py": retrospective,
    "review_cycle_done.py": review_cycle_done,
    "session_end_warning.py": session_end_warning,
    "session_start.py": session_start,
    "subagent_start.py": subagent_start,
    "subagent_stop.py": subagent_stop,
    "user_prompt_log.py": user_prompt_log,
}
