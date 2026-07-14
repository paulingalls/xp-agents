#!/usr/bin/env python3
"""PreToolUse hook for EnterPlanMode: the schedule plan-mode gate.

Blocks entering plan mode in the schedule trigger window (scheduled stories
exist, no story in motion) so /xp-schedule sets the planning scope first — both
solo and teammate modes plan ONE story per cycle (teammate then loops
plan→review→/xp-assign per story). Without this gate, the agent can plan the
wrong unit before mode is decided.

State-derived (no marker to rm past): the only legitimate exit is /xp-schedule
promoting a frontier scheduled->in-progress, which self-clears the gate. Free
mode / no sprint / a fully-promoted sprint / an in-motion close window never
fire.

The gate's second door. pre_tool_write.py runs the same gate against Write, and
carries the same free-branch exemption — a session that can write on a free
branch but cannot PLAN there has a half-open escape hatch, which is worse than
no exemption at all.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import _common
import branch_names
import identity
import sprint_status


def run(input_data: dict, smm_dir: Path | None = None) -> None:
    """Pure gate: returns None to allow, raises BlockedError to block."""
    if _common.is_xp_agent(input_data):
        return

    smm_dir = _common.get_validated_smm_dir(smm_dir)
    if not smm_dir:
        return

    cwd = input_data.get("cwd", ".")

    # A bad read is not "no sprint". `load_sprint` RAISES on a corrupt / schema-
    # invalid sprint.json, and letting that escape is not a block but an ALLOW:
    # the hook dies with a traceback and exits 1, which PreToolUse treats as a
    # NON-blocking error — the gate is skipped and plan mode opens with every
    # sprint gate blind. The sibling Write door already fails CLOSED here; a door
    # that stops the write but waves the plan through is the same half-open hatch
    # the free-branch exemption below exists to avoid.
    #
    # No SMM exemption to mirror: entering plan mode never repairs sprint.json.
    # The repair paths stay open — Bash (`sprint_cli.py create`) is ungated, and
    # the Write door still exempts writes into the SMM dir.
    try:
        gate_active = sprint_status.schedule_gate_active(smm_dir)
    except (ValueError, OSError) as exc:
        raise _common.BlockedError(
            f"sprint.json cannot be read ({exc}). Every sprint gate is blind "
            "until it is repaired, so planning is blocked rather than silently "
            "un-gated. Repair it (smm/sprint_cli.py create) or restore it from "
            "backup, then retry.",
            "Sprint state unreadable — gates cannot be evaluated.",
        ) from exc

    # Free branches are exempt: there the sprint is not the planning frame, and
    # /xp-free-close is the right path. Keyed on branch SHAPE, never a marker (a
    # marker can be `rm`'d to bypass the gate). No target-file leg — plan-mode
    # entry has no target to place inside or outside the tree, so the branch is
    # the only thing to judge scope by. Fails closed: get_current_branch returns
    # "" on git failure and "HEAD" when detached, and neither is a free branch.
    # The probe is LAST, so it is paid only in the rare gate window.
    #
    # branch_names + identity are imported DIRECTLY rather than reusing
    # pre_tool_write's predicate: importing that module would drag coordination,
    # lead_gates, sprint_state and concerns into every EnterPlanMode process.
    # Two similar lines beat a premature abstraction.
    if gate_active and not branch_names.is_free_branch(
        identity.get_current_branch(cwd)
    ):
        raise _common.BlockedError(
            "Run /xp-schedule to promote the next frontier and pick solo/"
            "teammate before entering plan mode — it sets the planning scope.",
            "Schedule the next frontier before planning.",
        )


if __name__ == "__main__":
    input_data = _common.read_hook_input()

    try:
        run(input_data)
    except _common.BlockedError as e:
        print(str(e), file=sys.stderr)
        sys.exit(2)
