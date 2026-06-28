# shellcheck shell=bash
# Git-diff helpers for preload scripts — working-tree (staged/unstaged/
# untracked) and committed-range (base...HEAD) variants. Extracted from
# _preload_base.sh when it crossed the 500-line cap (debt 57ee2b3b7ea0).
# Sourced by _preload_base.sh, so every preload that sources the base gets
# these transitively. No top-level code — function definitions only.

# Route git through ${TEAMMATE_CWD} so dump_diff / get_changed_files
# capture the teammate worktree's diff during /xp-accept fix-cycles —
# without this, the orchestrator's incidental cwd edits would mask the
# teammate's actual changes in /xp-quality-review.
_git() {
    if [ -n "${TEAMMATE_CWD:-}" ]; then
        git -C "$TEAMMATE_CWD" "$@"
    else
        git "$@"
    fi
}

# List all changed files (staged + unstaged + untracked), one per line.
# Usage: get_changed_files
get_changed_files() {
    { _git diff HEAD --name-only 2>/dev/null
      _git ls-files --others --exclude-standard 2>/dev/null
    } | sort -u
}

# Show uncommitted changes. Default: stat only. Pass "full" for complete diffs.
# Usage: dump_diff        # stat + new file list
#        dump_diff full   # staged/unstaged diffs + new files
dump_diff() {
    local mode="${1:-stat}"
    local staged_stat unstaged_stat untracked

    staged_stat=$(_git diff --cached --stat 2>/dev/null || true)
    unstaged_stat=$(_git diff --stat 2>/dev/null || true)
    untracked=$(_git ls-files --others --exclude-standard 2>/dev/null || true)

    if [ -z "$staged_stat" ] && [ -z "$unstaged_stat" ] && [ -z "$untracked" ]; then
        echo "## No Changes"
        echo "(no staged, unstaged, or untracked changes detected)"
        return
    fi

    if [ "$mode" = "full" ]; then
        if [ -n "$staged_stat" ]; then
            echo "## Staged Changes"
            echo "$staged_stat"
            echo ""
            echo "## Staged Diff"
            _git diff --cached 2>/dev/null || true
        fi
        if [ -n "$unstaged_stat" ]; then
            echo ""
            echo "## Unstaged Changes"
            echo "$unstaged_stat"
            echo ""
            echo "## Unstaged Diff"
            _git diff 2>/dev/null || true
        fi
    else
        echo "## Recent Changes"
        if [ -n "$staged_stat" ]; then
            echo "Staged:"
            echo "$staged_stat"
        fi
        if [ -n "$unstaged_stat" ]; then
            echo "Unstaged:"
            echo "$unstaged_stat"
        fi
    fi

    if [ -n "$untracked" ]; then
        echo ""
        echo "## New Files (untracked)"
        echo "$untracked"
    fi
    echo ""
}

# Cadence-aware variants of get_changed_files / dump_diff that review a
# COMMITTED range (base...HEAD) instead of the working tree. Story cadence
# relocates review to story-close, where the work is already committed — the
# staged-diff helpers above would see nothing. Callers resolve the base (the
# sprint branch via branching.py get-base) and the empty-range fallback; these
# helpers just render the range. Route through the TEAMMATE_CWD-aware _git.

# Usage: get_changed_files_range <base-ref>
get_changed_files_range() {
    _git diff "$1...HEAD" --name-only 2>/dev/null | sort -u
}

# Usage: dump_diff_range <base-ref> [stat|full] [known_files]
# When the caller already resolved `get_changed_files_range "$base"` (e.g.
# to gate the call), pass it as the optional 3rd arg to skip the internal
# repeat — saves one `git diff --name-only` shellout on a hot preload path.
dump_diff_range() {
    local base="$1" mode="${2:-stat}" known_files="${3:-}" stat files
    # Guard on the range's file set (--name-only) — the authoritative
    # "did anything change" signal, symmetric with get_changed_files_range.
    # The --stat is rendered below for the human/LLM view, not used as the
    # presence test.
    if [ -n "$known_files" ]; then
        files="$known_files"
    else
        files=$(_git diff "$base...HEAD" --name-only 2>/dev/null || true)
    fi
    if [ -z "$files" ]; then
        echo "## No Changes"
        echo "(no committed changes since ${base})"
        return
    fi
    stat=$(_git diff "$base...HEAD" --stat 2>/dev/null || true)
    echo "## Story Diff (cumulative since ${base})"
    echo "$stat"
    if [ "$mode" = "full" ]; then
        echo ""
        echo "## Full Diff"
        _git diff "$base...HEAD" 2>/dev/null || true
    fi
    echo ""
}
