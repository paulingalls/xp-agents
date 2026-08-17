#!/usr/bin/env python3
"""Deliver a skill's preload state by injecting it, instead of by an expanded line.

Seventeen of nineteen shipped skills carry a preload. Each used to get its
state from a `!` shell line in `SKILL.md`, expanded at instruction time; the
second harness never expands that line — only the skill's LOCATOR reaches the
model there, never the body — so every one of those skills ran blind on it.
This handler is the one mechanism that replaced that channel on both harnesses:
it runs a skill's own preload and injects the output as context. No skill
carries the line any more, so there is no second channel to fall back on.

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
import marker_claim
import markers
import plugin_loader
import shell_commands
import skill_preload_map
import target_routing

# Commands that READ a file's contents. The second harness's identity handle is
# the model reading SKILL.md through the shell, so only a read is an invocation.
#
# A heuristic, and it must be read as one: `wc -c` is the case that was measured
# breaking this, not the only command that could ever mention a skill path. The
# bias is deliberate — a read shape wrongly rejected costs one missed injection
# on that read, while a mention wrongly accepted TAKES THE CLAIM and starves the
# genuine read that follows, which is the failure that hid for a whole session.
_READ_COMMANDS = frozenset({"cat", "head", "tail", "less", "more", "bat", "view", "nl"})

# Short on purpose. The claim exists to collapse the burst of reads that one
# invocation produces, not to remember the invocation: a claim outliving it
# silently starves the next one. A duplicate injection costs context twice; a
# starved one leaves a skill running blind, and only the second is invisible.
_CLAIM_TTL_SECONDS = 10

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


def skill_from_command(command: str) -> str | None:
    """The skill whose body this shell command READS, or None.

    Second-harness leg. Tokenized with `shell_commands.simple_commands` — the
    same tokenization the Bash gates use — rather than searched as raw text. A
    regex over the raw command finds a path inside a commit message and treats
    prose as an argument; to the shell that message is one token, so a tokenizer
    cannot make the mistake. That module's docstring records what the regex
    approach cost twice. Splitting per simple command is what stops a read being
    hidden behind a chain, and unparseable text yields no commands at all, which
    degrades here to no injection.
    """
    for tokens in shell_commands.simple_commands(command):
        if not tokens or Path(tokens[0]).name not in _READ_COMMANDS:
            continue
        for token in tokens[1:]:
            skill = _skill_name_from_path(token)
            if skill is not None:
                return skill
    return None


def _skill_name_from_path(token: str) -> str | None:
    """The skill directory name for a path naming one of OUR skill bodies."""
    path = Path(token)
    if path.name != "SKILL.md":
        return None
    try:
        relative = path.resolve().relative_to(
            (plugin_loader.resolve_plugin_root() / "skills").resolve()
        )
    except (OSError, ValueError, RuntimeError):
        return None
    # Exactly `<skill>/SKILL.md` — not a body nested deeper under a skill.
    return relative.parts[0] if len(relative.parts) == 2 else None


def _claim_for(skill: str) -> markers.MarkerDef:
    """One claim per (session, skill).

    Session-scoped because the SMM dir is shared across worktrees and windows:
    keyed on the skill alone, two teammates invoking the same skill at once
    would leave one of them running blind.
    """
    return markers.MarkerDef(f".preload-claim-{skill}", "text", session_scoped=True)


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
    """The injected context for this invocation, or None to inject nothing.

    The two legs are NOT symmetric, and the asymmetry is deliberate.

    A skill tool call fires once per invocation, so the first-harness leg needs
    no claim — and must not take one. The same entry already carries
    `pre_tool_skill.py`, which can BLOCK the invocation, and hooks on one entry
    run in parallel: this handler cannot know the call was refused. A claim here
    would be taken for an invocation that never happened, starving the user's
    retry after they cleared the gate. The cost of not claiming is one wasted
    preload run whose output goes to a skill that will not run — which starves
    nothing.

    The second-harness leg has no such guarantee: the model may read one
    `SKILL.md` several times for a single invocation, which is the burst the
    claim exists to collapse.
    """
    if _common.is_xp_agent(input_data):
        return None

    skill = skill_from_payload(input_data)
    if skill is None:
        skill = skill_from_command(input_data.get("tool_input", {}).get("command", ""))
        if skill is None or not _take_claim(skill):
            return None

    _refresh_heartbeat(input_data)
    return run_preload(skill, input_data.get("cwd", ""))


def _take_claim(skill: str) -> bool:
    """Claim this skill's preload run, or report that a live claim holds it.

    Fails OPEN when the SMM dir cannot be resolved: without it there is nowhere
    to record a claim, and the choice is then between injecting twice and not
    injecting at all. A duplicate costs context; a miss leaves the skill
    stateless and says nothing, so the tie goes to delivering.
    """
    smm_dir = _common.get_validated_smm_dir(None)
    if smm_dir is None:
        return True
    took = marker_claim.claim(
        smm_dir, _claim_for(skill), ttl_seconds=_CLAIM_TTL_SECONDS
    )
    # One file per (session, skill) would otherwise pile up forever in an SMM
    # dir shared across worktrees and windows. Swept on the TAKING path only: a
    # caller that was refused sits inside someone else's live window and has no
    # business sweeping. The sweep window is far wider than the claim's own, so
    # a claim still doing its job is never a candidate.
    marker_claim.reap_stale(
        smm_dir, ".preload-claim-*", ttl_seconds=_CLAIM_TTL_SECONDS * 60
    )
    return took


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
