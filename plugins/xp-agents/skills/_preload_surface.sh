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
# empty, let the caller decide. The CLI collapses no-match, PARTIAL coverage
# and cannot-answer into that one empty signal, so empty here means exactly
# "no narrowing available" and never "some of it is covered".
#
# Input is the CHANGED-PATH set on stdin, not a story id. Story close used to
# pass its id and select on the DECLARED file_domain — but Step 1b tolerates
# drift and continues, so a drifted file never entered the coverage input and
# its tests ran nowhere at an auto-merge. Free close has no story at all. The
# changed set is the one input both modes share and the only one that is true.
find_surface_commands() {
    python3 "${PLUGIN_ROOT}/smm/system_context_cli.py" \
        --smm-dir "${SMM_DIR}" surface-commands --paths-from - 2>/dev/null \
        || echo ""
}

# runnable_lines VALUE -> VALUE minus every blank or whitespace-only line.
#
# The runnability filter the never-run-nothing invariant rests on. Neither
# `stack.test_command` nor a surface `command` is checked for content — the
# schema type-checks and length-checks a string and stops — so `"   "` reaches
# here and is `[ -n ]`-true. Emitted raw that is `GATE_SCOPE=full` plus a
# bullet holding nothing: a scope that claims a command and runs none. Empty
# out here instead, and the caller falls back exactly as it does for a value
# that was never set.
runnable_lines() {
    local line out=""
    while IFS= read -r line || [ -n "$line" ]; do
        [ -n "${line//[[:space:]]/}" ] || continue
        out="${out}${out:+$'\n'}${line}"
    done <<< "${1-}"
    printf '%s' "$out"
}

# emit_gate_commands CHANGED_PATHS FULL_COMMAND -> GATE_SCOPE + the block.
# CHANGED_PATHS is newline-separated (`get_changed_files_range "$BASE"`).
#
#   FULL_COMMAND unrunnable  -> GATE_SCOPE=none,    NO block at all
#   else surface cmds found  -> GATE_SCOPE=surface, block lists them
#   else                     -> GATE_SCOPE=full,    block holds it alone
#
# "runnable"/"found" mean RUNNABLE, not merely non-empty — see runnable_lines.
#
# THE FULL COMMAND IS TESTED FIRST, AND THAT ORDER IS THE CONTRACT, not a
# style choice. PROCESS_GUIDE documents an empty `stack.test_command` as the
# switch that DISABLES the close auto-merge, and both close SKILL.md files
# still print "set stack.test_command ... to enable" when no block is emitted.
# Resolving surfaces first would re-arm unattended merging for a project that
# turned it off on purpose, and the hint it never prints would be a lie.
# It also makes `surface_selection.should_collapse`'s stated assumption — that
# the caller's fallback command covers every surface — checkable rather than
# merely hoped for: there is no narrowing without a fallback to narrow FROM.
#
# `flat` on FULL_COMMAND, not `runnable_lines` alone: FULL_COMMAND is ONE
# command, while the block's contract is one command PER LINE and condition 3
# runs every one of them. A newline in `stack.test_command` would otherwise be
# split into a SECOND EXECUTED command at an unattended merge — an execution
# escalation, not a formatting slip. (The surface leg's per-command flattening
# lives in `surface_selection._declared_command`, so the CLI's one-per-line
# output stays true at its source.)
#
# Each command is line-prefixed with "- ". strip_framing kills the
# newline/CR/tab forgery vectors but does nothing about a value whose SHAPE is
# IDENT=value: printed at line start, `CI=1 pytest tests/` — an ordinary
# command, not only an attack — would forge a preload key. The prefix makes
# that structurally impossible; test_preload_var_hygiene.py pins it.
emit_gate_commands() {
    local changed="${1-}" full="${2-}" fallback resolved scope line
    fallback=$(runnable_lines "$(flat "$full")")
    if [ -z "$fallback" ]; then
        resolved=""
        scope="none"
    else
        resolved=$(runnable_lines "$(printf '%s\n' "$changed" | find_surface_commands)")
        if [ -n "$resolved" ]; then
            scope="surface"
        else
            resolved="$fallback"
            scope="full"
        fi
    fi
    emit_var GATE_SCOPE "$scope"
    [ -n "$resolved" ] || return 0
    echo ""
    echo "### GATE_COMMANDS"
    printf '%s\n' "$resolved" | while IFS= read -r line || [ -n "$line" ]; do
        [ -n "$line" ] && printf -- '- %s\n' "$(strip_framing "$line")"
    done
}
