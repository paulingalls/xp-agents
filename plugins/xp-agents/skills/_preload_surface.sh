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
# THE DECISION IS NOT MADE HERE. `scripts/close_gate_commands.py` owns it —
# opt-out first, then the exit-status check, then surface selection — so the
# preload and the gate-time recheck cannot disagree. This function only
# renders. Read that module's docstring for the ordering and why each step
# exists; do not restate the rules here, or the two will drift.
#
# WHAT THIS BLOCK DOES **NOT** GUARANTEE — corrected, because the previous
# wording claimed otherwise and a close review disproved it by RUNNING this
# function. `flat` normalises whitespace; it is NOT sanitisation. It closed the
# unadorned newline and nothing else: `\n;` collapses to `pytest -q ; echo X`,
# one bullet the shell executes as two, and bare `;`/`&`/`|` never went
# through it at all.
#
# What IS guaranteed is narrower and structural: a declared command whose own
# exit status does not reach the shell is REFUSED outright (no block, plus
# GATE_DISABLED_REASON), because such a command reports success when its runner
# failed — and this gate merges without asking. A command that survives that
# check is a single command whose failure the gate will see. It may still be
# compound (`a && b`), and that is fine: `&&` propagates failure.
#
# Each command is line-prefixed with "- ". strip_framing kills the
# newline/CR/tab forgery vectors but does nothing about a value whose SHAPE is
# IDENT=value: printed at line start, `CI=1 pytest tests/` — an ordinary
# command, not only an attack — would forge a preload key. The prefix makes
# that structurally impossible; test_preload_var_hygiene.py pins it.
emit_gate_commands() {
    local base="${1-}" cwd="${2-}" full="${3-}" out scope reason dgst line body

    out=$(python3 "${PLUGIN_ROOT}/scripts/close_gate_commands.py" \
        --smm-dir "${SMM_DIR}" --base "$base" --cwd "${cwd:-.}" \
        --full-command "$full" 2>/dev/null) || out=""

    scope=$(printf '%s\n' "$out" | sed -n 's/^SCOPE=//p' | head -1)
    reason=$(printf '%s\n' "$out" | sed -n 's/^REASON=//p' | head -1)
    dgst=$(printf '%s\n' "$out" | sed -n 's/^DIGEST=//p' | head -1)
    body=$(printf '%s\n' "$out" | sed -n '/^--$/,$p' | tail -n +2)

    # A failed or unparseable resolve is the same as "nothing to run": no
    # block, so the gate cannot run nothing and report green.
    [ -n "$scope" ] || { scope="none"; reason="not-set"; body=""; }

    emit_var GATE_SCOPE "$scope"
    body=$(runnable_lines "$body")
    if [ -z "$body" ]; then
        # Emitted ONLY with no block — it exists to explain an absent one.
        [ -n "$reason" ] && emit_var GATE_DISABLED_REASON "$reason"
        return 0
    fi
    echo ""
    echo "### GATE_COMMANDS"
    # The drift recheck, FIRST and only when the gate actually narrowed.
    #
    # Under GATE_SCOPE=full there is nothing to recheck: the full command is
    # the fallback and the maximum, so a review fix landing after the preload
    # ran cannot make it insufficient. Emitting it there would also change the
    # block every existing project sees, for no safety gained.
    #
    # Under GATE_SCOPE=surface it is load-bearing. The set was frozen from the
    # pre-review diff and both SKILL.md files forbid re-deriving it in prose;
    # this bullet re-derives it in CODE and exits non-zero on drift, so
    # condition 3's "every command exits 0" enforces the freeze. Failure falls
    # through to the human prompt — it can never fail toward auto-merge.
    #
    # Absolute and quoted: the agent runs this in its own shell, where
    # PLUGIN_ROOT and SMM_DIR do not exist, and a worktree path may hold spaces.
    if [ "$scope" = "surface" ] && [ -n "$dgst" ]; then
        printf -- '- python3 %q --smm-dir %q --base %q --cwd %q --full-command %q --expect-digest %q\n' \
            "${PLUGIN_ROOT}/scripts/close_gate_commands.py" \
            "${SMM_DIR}" "$base" "${cwd:-.}" "$full" "$dgst"
    fi
    printf '%s\n' "$body" | while IFS= read -r line || [ -n "$line" ]; do
        [ -n "$line" ] && printf -- '- %s\n' "$(strip_framing "$line")"
    done
}
