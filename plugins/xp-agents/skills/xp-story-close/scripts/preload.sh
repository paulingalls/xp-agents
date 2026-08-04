#!/bin/bash
set -euo pipefail
# Preload for xp-story-close: surface the five fields the close skill
# orchestrates against. TARGET_BRANCH is the story base (sprint branch
# at stage 2+, primary otherwise) — story-close merges a story branch
# into its sprint base, never directly into a plan/primary branch
# during sprint execution.
# shellcheck source=../../_preload_base.sh
source "$(dirname "$0")/../../_preload_base.sh"
# Sourced directly rather than via _preload_base.sh: only the close skills need
# surface-scoped gate commands, and the base is sourced by every preload.
# shellcheck source=../../_preload_surface.sh
source "$(dirname "$0")/../../_preload_surface.sh"

# Implicit teammate-worktree discovery: when
# /xp-accept dispatches /xp-story-close after promoting a teammate story
# to `closing`, the orchestrator sits on the SPRINT branch — not the story
# branch. Pair the live teammate worktree against sprint.json status
# to discover the worktree of the in-closing story; emit TEAMMATE_CWD
# + override CURRENT_BRANCH from the worktree's HEAD. Empty TEAMMATE_CWD
# means solo flow (orchestrator IS on the story branch).
#
# Multi-match (two `closing` stories with live worktrees) signals broken
# /xp-accept iteration — surface the helper's stderr and propagate the
# non-zero exit (set -e) rather than masking it as solo flow. The
# helper's "fail loud" contract only holds if its callers don't swallow.
#
# CLI emits `<abs-path>\t<branch>`: tab is the unambiguous split
# point — worktree paths can contain spaces on macOS. The shared
# find_closing_teammate_worktree wrapper (in _preload_base.sh) owns the
# CLI command/flags so this and xp-quality-review's preload stay in sync.
CLOSING=$(find_closing_teammate_worktree)
if [ -n "$CLOSING" ]; then
    TEAMMATE_CWD="${CLOSING%$'\t'*}"
    CURRENT_BRANCH="${CLOSING##*$'\t'}"
else
    TEAMMATE_CWD=""
    CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "")
fi
# TARGET_BRANCH is what the close MERGES INTO, so it takes `get-base
# --required`: a silently-degraded primary here merges a story branch straight
# into the release branch. On refusal get-base writes NOTHING to stdout, the
# reason to stderr, and exits 1.
#
# The rc is captured INSIDE a helper that ALWAYS returns 0, and that is
# structural rather than stylistic. This script runs under `set -euo pipefail`
# and the resolve happens BEFORE the first stdout write, so a bare
# `TARGET_BRANCH=$(... --required)` would abort the preload before line 1 and
# hand the skill ZERO BYTES — no SMM_DIR, no STORY_ID, no reason. The old
# `|| echo ""` prevented that only by swallowing the failure whole (empty
# TARGET_BRANCH -> the skill merges into an empty string). Putting the guard
# inside the helper means there is no `|| ...` at the call site for a future
# edit to "clean up", and no way to be loud and truncating at the same time.
#
# NEVER capture with `2>&1`: _common.log_hook_error mirrors to stderr
# unconditionally and can fire on the SUCCESS path (auto-promote against a
# read-only SMM), so folding the streams would splice a warning into the branch
# name we merge into. Streams stay apart; the verdict comes from the exit code.
STORY_BASE_UNRESOLVED="false"
STORY_BASE_REASON=""
resolve_target_branch() {
    local err_file out rc
    err_file=$(mktemp 2>/dev/null) || err_file=""
    out=$(python3 "${PLUGIN_ROOT}/scripts/branching.py" \
        --smm-dir "${SMM_DIR}" get-base --cwd . --required \
        2>"${err_file:-/dev/null}") && rc=0 || rc=$?
    if [ "$rc" -ne 0 ]; then
        STORY_BASE_UNRESOLVED="true"
        out=""
        [ -n "$err_file" ] && STORY_BASE_REASON=$(cat "$err_file")
    fi
    [ -n "$err_file" ] && rm -f "$err_file"
    TARGET_BRANCH="$out"
    return 0
}
resolve_target_branch

echo "SMM_DIR=${SMM_DIR}"
# Route author-influenced values through emit_var. Keep the shell vars
# themselves unflattened — downstream extract-story-id still consumes the raw
# $CURRENT_BRANCH, and $TEAMMATE_CWD feeds --cwd below.
# TEAMMATE_CWD is a filesystem path the close skill feeds to `git -C <path>`
# for the teammate stash+merge; route it through emit_path_var so a worktree
# under a dir with consecutive spaces survives verbatim (emit_var/flat would
# collapse the run and target a non-existent directory), while newline/tab
# forgery vectors are still neutralized.
emit_path_var TEAMMATE_CWD "$TEAMMATE_CWD"
emit_var CURRENT_BRANCH "$CURRENT_BRANCH"
emit_var TARGET_BRANCH "${TARGET_BRANCH}"
# A deterministic key=value flag that disambiguates "the base could not be
# resolved" from "the base happens to be empty" — mirrors
# CLOSE_DIFF_UNAVAILABLE in xp-quality-review's preload. The prose reason goes
# on STDOUT, not stderr, because stderr is not surfaced to the skill: a reason
# the agent cannot read is not a reason. SKILL.md Step 0 halts on the flag.
#
# The reason is AUTHOR-INFLUENCED, so it goes through flat() like every other
# such value here. It interpolates sprint.json's `branch_name` and
# system_context's `integration_branch` — and the latter is only type-checked by
# the schema (never pattern-checked), while the resolver reads it with a raw
# json.loads that skips validation entirely. A newline in it forges a line at
# column 0, and this block prints AFTER the real STORY_BASE_UNRESOLVED /
# TARGET_BRANCH lines, so a forged `STORY_BASE_UNRESOLVED=false` +
# `TARGET_BRANCH=main` pair would shadow them and re-authorize the exact merge
# into the release branch this refusal exists to stop. flat() collapses every
# whitespace run to one space: the reason stays one line, and one line cannot
# forge a second.
echo "STORY_BASE_UNRESOLVED=${STORY_BASE_UNRESOLVED}"
if [ "$STORY_BASE_UNRESOLVED" = "true" ]; then
    echo ""
    echo "## Story base unresolved — do NOT merge"
    echo "TARGET_BRANCH is the branch this close MERGES INTO. It could not be"
    echo "resolved, and the fallback would be the primary/release branch."
    printf '%s\n' "$(flat "${STORY_BASE_REASON}")"
    echo ""
fi
echo "GH_AVAILABLE=$(gh_available)"
echo "WORKTREE_CLEAN=$(worktree_clean)"
HOOK_STATUS=$(pre_commit_hook_present)
echo "PRE_COMMIT_HOOK=${HOOK_STATUS}"
# TEST_COMMAND is customer-set free text (system_context.stack.test_command,
# not a git-constrained ref) — route it through emit_var so a newline in it
# cannot forge a line that shadows the VERIFY_DEFERRED gate emitted below.
#
# Resolved into a variable rather than inlined twice: emit_gate_commands below
# needs the same value, and find_test_command spawns a python3 that re-reads
# system_context.json — a second read that could also disagree with this one if
# the document changed mid-preload.
TEST_COMMAND=$(find_test_command)
emit_var TEST_COMMAND "$TEST_COMMAND"
echo "CLOSE_START_TS=$(now_iso)"
# Assign-then-use, not `echo "$(generate_id)"`: the id has to be reusable by
# the two consumers below, and generating it inside the echo left nothing for
# either of them.
CLOSE_CYCLE_ID=$(generate_id)
echo "CLOSE_CYCLE_ID=${CLOSE_CYCLE_ID}"
# Persist the id where a LATER process can read it. The echo above reaches the
# LLM only, and a concern raised mid-close is appended by a separate process —
# without the marker the merge gate is back to inferring which concerns belong
# to this close from the `files` they happened to record.
#
# write_marker ends in `2>/dev/null || true`, so a failed write is SILENT. That
# degrades safely rather than being guaranteed: no id on disk means no stamp,
# and an unstamped concern is still counted by the gate under the shipped
# files-relevance rule. It is never the reason a close fails to start.
write_marker CLOSE_CYCLE_ID "${CLOSE_CYCLE_ID}"
# Record the cycle in the log too. Story-close is deliberately NOT a
# security-bearing close (no Step 4 /security-review — the enclosing
# sprint-close covers this diff), and it stays outside that family here:
# retro_metrics scopes the security_checks=0 rule on metadata.close_mode, and
# `story` is not one of the modes it counts. Emitting the event is what makes
# the cycle auditable after the marker is swept; it claims nothing about
# security.
emit_close_started_event story "${CLOSE_CYCLE_ID}"

# Verify-touch gate: declared acceptance-test paths no commit on
# base..HEAD touched, plus whether a [verify-deferred] commit defers
# the gate. The close skill refuses on untouched && not-deferred.
# `|| true` keeps the CLI's exit 1 (untouched paths found) from tripping
# `set -e` — we want its stdout regardless of exit code. UNTOUCHED is a
# newline-joined path list; emit_var flattens it to one space-joined line.
STORY_ID=$(python3 "${PLUGIN_ROOT}/scripts/branching.py" \
    --smm-dir "${SMM_DIR}" extract-story-id --branch "${CURRENT_BRANCH}")
UNTOUCHED=""
VERIFY_DEFERRED="false"
# Also gate on a non-empty TARGET_BRANCH, and this guard is load-bearing rather
# than defensive: verify_paths resolves its base as `args.base or
# get_story_base_branch(...)`, and "" is FALSY — so passing `--base ""` does not
# fail, it silently re-enters the DEGRADING resolver and computes the gate
# against the primary/release branch. That is the exact degradation this story
# removed from the merge target, smuggled back in through the gate that guards
# it. (verify_deferred takes the other branch of the same fork: `git log
# ""..HEAD` errors, so it answers "false" — the two CLIs do not even agree.)
# When the base is unresolved the close halts at Step 0, so there is nothing to
# gate: emit no verdict rather than one computed against the wrong base.
if [ -n "$STORY_ID" ] && [ -n "$TARGET_BRANCH" ]; then
    UNTOUCHED=$(python3 "${PLUGIN_ROOT}/scripts/verify_paths.py" \
        --smm-dir "${SMM_DIR}" --cwd "${TEAMMATE_CWD:-.}" \
        --story "$STORY_ID" --base "${TARGET_BRANCH}" 2>/dev/null) || true
    # Single source for the [verify-deferred] marker: verify_deferred reuses
    # parse_verify_deferred (no duplicate bash regex of the marker).
    VERIFY_DEFERRED=$(python3 "${PLUGIN_ROOT}/scripts/verify_deferred.py" \
        has-verify-deferred --cwd "${TEAMMATE_CWD:-.}" --base "${TARGET_BRANCH}" \
        2>/dev/null) || VERIFY_DEFERRED="false"
fi
# emit_var flattens the newline-joined untouched-path list to one space-joined
# line, hardening beyond the old newline-only `tr` (a tab/CR in an acceptance
# path could otherwise survive raw into this KEY=value contract).
emit_var VERIFY_UNTOUCHED "$UNTOUCHED"
echo "VERIFY_DEFERRED=${VERIFY_DEFERRED}"

# Cadence routes Step 4.5: 'story' runs the full review cycle here (the
# per-commit gate deferred it); 'commit'/unset keeps the close-reviewer
# fork. _get_review_cadence fail-safes to 'commit'.
CADENCE=$(_get_review_cadence)
if [ "$CADENCE" = "story" ]; then
    echo "REVIEW_PATH=full-cycle"
else
    echo "REVIEW_PATH=close-reviewer"
fi

emit_system_context_rendered_for close-reviewer
emit_hook_guidance "$HOOK_STATUS"

# Condition 3's command set, RESOLVED here rather than left as prose branches
# for the skill to judge — see _preload_surface.sh.
#
# Selects on the CLOSE DIFF, not the declared file_domain. Step 1b tolerates
# drift and continues, so a file the story drifted onto is absent from the
# declaration — and selecting on the declaration would leave that file's tests
# running nowhere at an auto-merge. `get_changed_files_range` uses _git, which
# is TEAMMATE_CWD-aware, so the range is computed in the right checkout.
#
# Emitted LAST of the preload's own output, so the `### GATE_COMMANDS` block
# is bounded by the shared reference's first heading rather than trailing off
# into unrelated KEY=value lines. The shared file's own `- ` bullets sit under
# their own headings, past that boundary.
emit_gate_commands "$(get_changed_files_range "${TARGET_BRANCH}")" "$TEST_COMMAND"

# Append shared close-pipeline reference (Steps 5, 5b, 6) so the LLM
# sees one consistent set of shared instructions across all four close
# skills instead of four near-duplicate inlined copies.
echo
cat "${PLUGIN_ROOT}/scripts/_close_pipeline_shared.md"
