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
    return _make_skill_input(skill="code-review", tool_response={"success": True})


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


def preload_injection() -> dict:
    """Names a skill whose preload is READ-ONLY.

    The fixture's choice of skill is the whole cost of this entry, because this
    emitter injects another script's output verbatim — it contributes no prose
    of its own. `xp-schedule` reads the frontier and writes nothing; a close
    skill would ARM a close cycle by being measured, leaving state behind for
    whatever the harness runs next.
    """
    return {
        "session_id": "t",
        "agent_id": "main",
        "tool_name": "Skill",
        "tool_input": {"skill": "xp-agents:xp-schedule"},
    }


def bash_post_tool() -> dict:
    return {
        "session_id": "t",
        "agent_id": "main",
        "tool_name": "Bash",
        "tool_input": {"command": "ls"},
        "tool_response": {"stdout": "", "stderr": "", "exit_code": 0},
    }


# ceil(measured_chars * 1.125 / 100) * 100, floor at 100 — measured against
# `_budget_helpers._bootstrap_seeded_smm`, so these bound PROSE SHAPE only.
#
# Lives beside the builders rather than in the suite that asserts it:
# `tests/test_volume_budgets.py` needs these as the floor its own measurements
# must clear, and importing a `test_*` module for a constant makes pytest
# execute that file under a second module name.
EMITTER_BUDGETS: dict[str, int] = {
    "bash_post_tool.py": 100,
    "kickoff_gate.py": 100,
    "lint_check.py": 300,
    "post_tool_exit_plan.py": 100,
    "pre_tool_bash.py": 100,
    "pre_tool_skill.py": 100,
    # Measured 355 with the xp-schedule fixture. Unlike every sibling here,
    # these bytes are not this emitter's own prose — it injects another
    # script's output verbatim, so the number tracks that preload rather than
    # anything in preload_injection.py. The primary bound on the payload is
    # the per-skill preload budget in test_preload_budgets.py; this entry
    # exists so the injection surface is not the one emitter with no ceiling
    # at all, and it moves when the chosen fixture's preload moves.
    #
    # Held at 400. A 400 -> 420 bump was made and REVERTED: the 392 that
    # prompted it was not growth in xp-schedule's preload but the teammate
    # worktree's longer checkout path leaking into the measurement. Measured in
    # the main checkout the number had not moved from 355. Both dead guards are
    # fixed in `_budget_helpers` — see the note on `_WORKTREE_SEGMENT_RE`.
    "preload_injection.py": 400,
    "pre_tool_write.py": 100,
    "prompt_nugget.py": 100,
    "retrospective.py": 100,
    "review_cycle_done.py": 200,
    "session_end_warning.py": 100,
    "session_start.py": 1500,
    # Ratcheted 3700 -> 2100 when the unknown-agent-type fallback went lazy:
    # this fixture supplies `subagent_type` inside `tool_input` and the hook
    # reads a TOP-LEVEL `agent_type`, so it lands on that fallback and its
    # measurement fell 3,209 -> 1,815. Left at 3700 the saving would be
    # silently re-spendable, which is the failure mode the band exists to
    # prevent.
    "subagent_start.py": 2100,
    "subagent_stop.py": 300,
    "user_prompt_log.py": 100,
}


# --- Loud variants, for the volume family -----------------------------------
#
# An emitter's cost depends on its INPUT as much as on the SMM, and the
# builders above pick the quiet branch every time. These pick the expensive
# one. Only emitters whose loud branch out-measures their shape budget appear
# here; `test_volume_budgets` classifies the rest and says why.


def session_start_compact() -> dict:
    """`compact` also injects PROCESS_GUIDE, which `startup` does not."""
    return {"session_id": "t", "agent_id": "main", "source": "compact"}


def post_tool_exit_plan_triggered() -> dict:
    """A non-`xp-` agent: writes the marker and returns the review nudge."""
    return {
        "session_id": "t",
        "agent_id": "main",
        "agent_type": "main",
        "tool_name": "ExitPlanMode",
        "tool_input": {},
        "tool_response": {"filePath": "/tmp/p.md"},
    }


def pre_tool_skill_gated() -> dict:
    """A lead-owned lifecycle skill — the branch that emits a gate reason."""
    return _make_skill_input(skill="xp-agents:xp-story-close")


def subagent_start_full_tier() -> dict:
    """A NAMED full-render tier.

    This used to be the shape builder itself: `subagent_start` reads a
    top-level `agent_type`, the shape builder supplies none, and the unknown
    fallback rendered the whole SMM — so the expensive tier was reached by
    accident. The fallback is lazy now, so reaching it has to be deliberate.
    """
    return {
        "session_id": "t",
        "agent_id": "a-1",
        "agent_type": "Plan",
        "tool_name": "Agent",
        "tool_input": {},
    }


def preload_injection_loud() -> dict:
    """The louder branch: a skill whose preload reports triage state.

    The loud dimension for this emitter is WHICH skill it was asked to load,
    because it injects that skill's preload verbatim — so the expensive input
    is a preload with more of the SMM to report, not a bigger payload of its
    own.

    NOT read-only, unlike the quiet fixture: `xp-work-selection`'s preload arms
    NEEDS_HOUSEKEEPING and HOUSEKEEPING_ARMED, so this emitter is registered in
    `_volume_fixture._MARKER_WRITERS` and measured last. No sibling in the
    volume set reads those markers today; the registration is what keeps that
    from being a fact anyone has to re-derive when one starts to.
    """
    return {
        "session_id": "t",
        "agent_id": "main",
        "tool_name": "Skill",
        "tool_input": {"skill": "xp-agents:xp-work-selection"},
    }


EMITTER_LOUD_FIXTURES: dict[str, FixtureBuilder] = {
    "post_tool_exit_plan.py": post_tool_exit_plan_triggered,
    "pre_tool_skill.py": pre_tool_skill_gated,
    "preload_injection.py": preload_injection_loud,
    "prompt_nugget.py": prompt_nugget,
    "retrospective.py": retrospective,
    "session_end_warning.py": session_end_warning,
    "session_start.py": session_start_compact,
    "subagent_start.py": subagent_start_full_tier,
}


EMITTER_FIXTURES: dict[str, FixtureBuilder] = {
    "bash_post_tool.py": bash_post_tool,
    "kickoff_gate.py": kickoff_gate,
    "lint_check.py": lint_check,
    "post_tool_exit_plan.py": post_tool_exit_plan,
    "pre_tool_bash.py": pre_tool_bash,
    "pre_tool_skill.py": pre_tool_skill,
    "preload_injection.py": preload_injection,
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
