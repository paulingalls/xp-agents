# shellcheck shell=bash
# Surface-scoped gate commands for the close preloads. Function definitions
# only, no top-level code.
#
# Sourced DIRECTLY by the close preloads, not by _preload_base.sh. Two reasons,
# the second being the better one: the base is at 492 lines and was already
# split twice for size (_preload_diff.sh, _preload_emit.sh); and only close
# skills need this, so putting it in the base would make kickoff, plan, accept
# and schedule all carry a helper none of them use.
#
# WHY THE SHELL DECIDES. The alternative is a decision table in SKILL.md that
# the LLM judges. That is the direction the auto-merge conditions were
# converted AWAY from — one of them once "held vacuously" and merged anyway,
# which is why test_close_auto_merge_deterministic.py exists. Condition 3
# guards the same auto-merge, so the choice is resolved here, in shell, where a
# test can assert the invariant instead of trusting prose to honor it:
#
#     a gate must never run nothing and report green.
#
# That invariant is spelled structurally: GATE_SCOPE=none emits NO block, and
# every other scope emits at least one command.

# shellcheck source=_preload_emit.sh
source "$(dirname "${BASH_SOURCE[0]}")/_preload_emit.sh"

# find_surface_commands STORY_ID [CWD] -> newline-joined surface commands, or
# empty. Mirrors find_test_command: delegate to the CLI, swallow failure to
# empty, let the caller decide. story-015's CLI already collapses no-match,
# PARTIAL coverage and cannot-answer into that one empty signal, so empty here
# means exactly "no narrowing available" and never "some of it is covered".
find_surface_commands() {
    [ -n "${1-}" ] || return 0
    python3 "${PLUGIN_ROOT}/smm/system_context_cli.py" \
        --smm-dir "${SMM_DIR}" surface-commands "$1" --cwd "${2:-.}" 2>/dev/null \
        || echo ""
}

# emit_gate_commands STORY_ID FULL_COMMAND [CWD] -> GATE_SCOPE + the block.
#
#   surface commands found -> GATE_SCOPE=surface, block lists them
#   else FULL_COMMAND set   -> GATE_SCOPE=full,    block holds it alone
#   else                    -> GATE_SCOPE=none,    NO block at all
#
# Each command is line-prefixed with "- ". strip_framing kills the
# newline/CR/tab forgery vectors but does nothing about a value whose SHAPE is
# IDENT=value: printed at line start, `CI=1 pytest tests/` — an ordinary
# command, not only an attack — would forge a preload key. The prefix makes
# that structurally impossible; test_preload_var_hygiene.py pins it.
emit_gate_commands() {
    local story="${1-}" full="${2-}" cwd="${3:-.}" resolved scope line
    resolved=$(find_surface_commands "$story" "$cwd")
    if [ -n "$resolved" ]; then
        scope="surface"
    elif [ -n "$full" ]; then
        scope="full"
        resolved="$full"
    else
        scope="none"
        resolved=""
    fi
    emit_var GATE_SCOPE "$scope"
    [ -n "$resolved" ] || return 0
    echo ""
    echo "### GATE_COMMANDS"
    printf '%s\n' "$resolved" | while IFS= read -r line || [ -n "$line" ]; do
        [ -n "$line" ] && printf -- '- %s\n' "$(strip_framing "$line")"
    done
}
