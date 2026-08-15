#!/usr/bin/env python3
"""Deliver a skill's preload state by injecting it, instead of by an expanded line.

Seventeen of nineteen shipped skills get their state from a `!` shell line in
`SKILL.md`, expanded at instruction time. The second harness never expands that
line — only the skill's LOCATOR reaches the model there, never the body — so
every one of those skills runs blind on it. This handler is the one mechanism
that replaces that channel on both harnesses: it runs a skill's own preload and
injects the output as context.

Two triggers, one mechanism. On the first harness a skill invocation is a tool
call, so the identity arrives as `tool_input.skill`. On the second there is no
skill tool call at all; the model reads `SKILL.md` with a shell command, so the
identity arrives inside `tool_input.command` and the trigger is registered only
in the derived variant (see `hooks_emit._VARIANT_ONLY_HOOKS`).

**Every failure in this path is quiet.** Each of the requirements below was found
the hard way, and each fails at exit 0 with no error and an injection that looks
successful:

1. Run the preload in the SESSION's cwd. Run it in the skill directory and it
   resolves a different project's state.
2. Run the command the skill's own line names, via `skill_preload_map`. A
   hardcoded `preload.sh` is right on fourteen skills and WRONG on two — one
   takes an extra flag, one names a different script, and one of the two is the
   most-used skill.
3. Write the heartbeat FIRST. The preload scripts carry their own liveness check
   and emit a refusal banner *instead of state* when no fresh heartbeat exists,
   so skipping this injects a refusal that reads like output. `pre_tool_skill.py`
   refreshes it on the skill trigger, but this is a separate process and the
   second harness's trigger has no refresh at all.
4. A preload that fails, times out, or prints nothing must inject NOTHING.
   Injecting a partial stream or an error as though it were state is this
   milestone's own failure class arriving from inside.

`skill_preload_map` is the SOLE source of the invocation — this module must not
rebuild or second-guess it. That is also what makes an arbitrary-command vector
unreachable: the resolver maps a skill NAME to `skills/<name>/scripts/*.sh` under
the plugin root, so a `SKILL.md` that is a symlink, or a path with a `..`
segment, cannot select what runs. **That property holds only while the resolver
stays the sole path source.** If anything else ever supplies a path here, the
guard is gone and nothing else will say so.
"""

import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import _common
import hook_liveness
import skill_preload_map
import target_routing

# Generous against the slowest measured preload (1.91s for a close preload,
# which computes diffs) and far below the harness's own hook bound. It exists
# so a wedged preload degrades to "no state" rather than hanging the tool call:
# the skill still runs, just without injected context.
_PRELOAD_TIMEOUT_SECONDS = 30


def skill_from_payload(input_data: dict) -> str | None:
    """The bare skill name this invocation names, or None.

    First-harness leg only: the skill tool call carries the name directly.
    `strip_our_namespace` turns `xp-agents:xp-accept` into `xp-accept`; a
    third-party or built-in skill keeps a name the resolver will reject, which
    is the correct outcome — we inject state only for skills we ship.
    """
    skill = input_data.get("tool_input", {}).get("skill", "")
    if not skill:
        return None
    return target_routing.strip_our_namespace(skill) or None


def run_preload(skill: str, cwd: str) -> str | None:
    """That skill's own preload output, or None if it has none or it failed.

    Returns None — never a partial or error stream — on every failure mode:
    an unknown skill name, a skill that ships no preload, a non-zero exit, a
    timeout, or empty output. The caller injects nothing in each case.
    """
    try:
        invocation = skill_preload_map.resolve_preload(skill)
    except ValueError:
        # Names no skill we ship (a third-party or built-in skill). Not an
        # error: most tool calls that reach this handler are not ours.
        return None
    if invocation is None:
        return None

    try:
        completed = subprocess.run(
            invocation.argv,
            env={**os.environ, **invocation.env},
            cwd=cwd or None,
            capture_output=True,
            text=True,
            timeout=_PRELOAD_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None

    if completed.returncode != 0:
        return None
    return completed.stdout or None


def run(input_data: dict, **_kwargs) -> str | None:
    """The injected context for this invocation, or None to inject nothing."""
    if _common.is_xp_agent(input_data):
        return None

    skill = skill_from_payload(input_data)
    if skill is None:
        return None

    _refresh_heartbeat(input_data)
    return run_preload(skill, input_data.get("cwd", ""))


def _refresh_heartbeat(input_data: dict) -> None:
    """Write the liveness heartbeat before the preload reads it.

    Ordering is the whole point: the preload refuses and emits a banner instead
    of state when the heartbeat is stale, so a write placed after the run would
    inject that banner. Never raises — `write_heartbeat` swallows its own
    failures, and a heartbeat that cannot be written must not cost the injection.
    """
    smm_dir = _common.get_validated_smm_dir(None)
    if smm_dir is None:
        return
    hook_liveness.write_heartbeat(
        smm_dir, session_id=hook_liveness.payload_session_id(input_data)
    )


if __name__ == "__main__":
    payload = _common.read_hook_input()
    context = run(payload)
    if context:
        _common.hook_output("PreToolUse", context)
    sys.exit(0)
