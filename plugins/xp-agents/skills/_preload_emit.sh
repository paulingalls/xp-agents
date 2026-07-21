# shellcheck shell=bash
# Sanitized preload emission helpers. Extracted from _preload_base.sh when it
# crossed the 500-line cap, alongside _preload_diff.sh. Sourced by
# _preload_base.sh, so every preload that sources the base gets these
# transitively. No top-level code — function definitions only.
#
# Preload stdout is BOTH a machine KEY=value contract AND raw LLM-prompt input.
# A newline/CR/tab in an author-supplied value can forge a second KEY=value line
# and shadow a real gate variable. Emit author-influenced values through these so
# the one-line-per-variable invariant holds by construction. `tr -s '[:space:]'
# ' '` is the exact shell analog of the Python `re.sub(r"\s+", " ", text).strip()`
# rule this replaces (previously inlined in xp-schedule's python3 -c block).

# flat VALUE -> collapse every whitespace run to a single space, trim ends.
flat() {
    local s
    s=$(printf '%s' "${1-}" | tr -s '[:space:]' ' ')
    s="${s# }"
    s="${s% }"
    printf '%s' "$s"
}

# emit_var KEY VALUE -> print exactly one `KEY=<flattened value>` line.
emit_var() {
    printf '%s=%s\n' "$1" "$(flat "${2-}")"
}

# strip_framing VALUE -> replace each newline/CR/tab with a single space so the
# value cannot break TSV row/field framing, WITHOUT collapsing legitimate
# multi-space runs. Unlike flat(), spaces are preserved verbatim: a TSV field is
# not a KEY=value scalar, so only the framing chars (\n \r \t) are injection
# vectors — a worktree path legitimately contains spaces (even consecutive ones),
# and collapsing them would corrupt xp-accept's `--cwd <path>` target.
strip_framing() {
    printf '%s' "${1-}" | tr '\n\r\t' '   '
}

# emit_path_var KEY VALUE -> like emit_var, but PRESERVES consecutive spaces.
# For a path-valued variable (a worktree cwd) whose emitted line a close/review
# skill hands to `git -C <path>` / `--cwd <path>`: a filesystem path may
# legitimately contain a run of spaces (e.g. `/Users/John  Doe/proj`), and
# emit_var's flat() would collapse it, targeting a non-existent directory.
# strip_framing still neutralizes the newline/CR/tab forgery vectors (each -> a
# single space), so the one-line-per-variable invariant holds. Use emit_var for
# every non-path scalar.
emit_path_var() {
    printf '%s=%s\n' "$1" "$(strip_framing "${2-}")"
}

# sanitize_tsv_block (stdin) -> strip framing chars from each TAB field, preserve
# tab field-sep, newline row-sep, and spaces within a field. For xp-accept's
# TEAMMATE_WORKTREES rows (id<TAB>path<TAB>sha<TAB>ref).
# NOTE: operates on the already-serialized block, so it cannot un-break a field that
# already held a raw newline (branching.py emits well-formed rows from real git state,
# out of this domain). AC3's threat is tab/CR/newline inside a field — fully handled;
# benign spaces are preserved so space-bearing paths survive intact.
# `IFS=$'\t' read -ra` treats tab as IFS-whitespace: an empty interior field collapses.
# Harmless here — every snapshot row is id/path/sha/ref, never an empty middle field.
sanitize_tsv_block() {
    local line out i
    local -a fields
    while IFS= read -r line || [ -n "$line" ]; do
        IFS=$'\t' read -ra fields <<< "$line"
        out=""
        for i in "${!fields[@]}"; do
            if [ "$i" -eq 0 ]; then
                out="$(strip_framing "${fields[$i]}")"
            else
                out="${out}"$'\t'"$(strip_framing "${fields[$i]}")"
            fi
        done
        printf '%s\n' "$out"
    done
}
