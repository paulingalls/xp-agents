#!/bin/bash
set -euo pipefail

# Common preload base for XP agent skills.
# Source this from individual preload scripts:
#   source "$(dirname "$0")/../../_preload_base.sh"
#
# After sourcing, PLUGIN_ROOT and SMM_DIR are set.
# Call dump_smm to output the SMM state section.
# Call dump_values to output XP values only.
# Call dump_diff to output git diff stats (or dump_diff full for complete diffs).
# Call get_changed_files to get list of all changed file names.

PLUGIN_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SMM_DIR=$("${PLUGIN_ROOT}/smm/init.sh" 2>/dev/null) || {
    echo "## SMM State: unavailable"
    exit 0
}

# No liveness check here any more (story-009). Reachable only from the injection
# hook, it judged a runtime that was already running — and the handler wrote the
# heartbeat just before the preload read it, so the verdict was inert. The
# reader is deleted; the heartbeat stays for its other two consumers.
#
# Sanitized-emission helpers (flat, emit_var, strip_framing, emit_path_var,
# sanitize_tsv_block) live in a sibling module — extracted when this file
# crossed the 500-line cap. Sourced here so every preload that sources
# _preload_base.sh gets them transitively, with no call-site changes.
# shellcheck source=_preload_emit.sh
source "$(dirname "${BASH_SOURCE[0]}")/_preload_emit.sh"

# Clean up temp files from previous preload runs.
# These are created by smm_render_to_tempfile/sprint_render_to_tempfile and are
# safe to remove once the previous skill has finished — each is consumed by the
# same skill invocation that emitted it.
#
# `.system-context-rendered.*` is NOT swept, and that is the whole point. A
# close emits it at Step 0 and hands the path to the close-reviewer at Step
# 4.5, but Step 4b runs `/xp-quality-review` in between — whose preload sources
# THIS file. Sweeping the pattern here therefore deleted the reviewer's input
# before it was read, every time `RUN_FULL_CODE_REVIEW=true`. It failed
# SILENTLY: the agent gets `SYSTEM_CONTEXT_RENDERED=<dead path>` and reviews
# with no conventions, branching or principles, with no branch for "line
# present, file gone". Observed live in sprint-003's own close.
find "$SMM_DIR" -maxdepth 1 \( -name ".smm-rendered.*" -o -name ".sprint-rendered.*" -o -name ".sprint-review-input.*" \) -exec rm -f {} + 2>/dev/null || true

dump_smm() {
    if [ -f "${SMM_DIR}/shared_mental_model.json" ]; then
        echo "## Current SMM State"
        python3 "${PLUGIN_ROOT}/smm/smm_cli.py" --smm-dir "$SMM_DIR" render 2>/dev/null
    else
        echo "## SMM State: no materialized view"
    fi
}

smm_render_to_tempfile() {
    # Unique tempfile per call — concurrent preloads must not race on a shared path.
    # BSD mktemp (macOS) requires the X's at the end of the template, so no suffix.
    # Agents Read the file via the Read tool, which is extension-agnostic.
    local out
    out=$(mktemp "${SMM_DIR}/.smm-rendered.XXXXXX")
    python3 "${PLUGIN_ROOT}/smm/smm_cli.py" --smm-dir "$SMM_DIR" render > "$out" 2>/dev/null
    echo "$out"
}

sprint_render_to_tempfile() {
    local out
    out=$(mktemp "${SMM_DIR}/.sprint-rendered.XXXXXX")
    python3 "${PLUGIN_ROOT}/smm/sprint_cli.py" --smm-dir "$SMM_DIR" render > "$out" 2>/dev/null
    echo "$out"
}

# Emit `SYSTEM_CONTEXT_RENDERED=<tempfile>` to stdout for the given
# reviewer kind, but only when system_context.json exists. Wraps the
# file-existence guard + render-to-tempfile + KEY= prefix that
# previously copy-pasted across 5 preload call sites. Single source of
# truth for the env-var name plus the file-exists predicate.
emit_system_context_rendered_for() {
    local kind="$1"
    local rendered
    [ -f "${SMM_DIR}/system_context.json" ] || return 0
    # Propagate render failure: $() swallows rc otherwise, leaving an
    # empty `SYSTEM_CONTEXT_RENDERED=` line in preload output that the
    # downstream Read fails loud on. Skipping emission keeps the failure
    # signal at the helper's stderr (already loud) instead of downstream.
    rendered=$(system_context_render_to_tempfile_for "$kind") || return 1
    echo "SYSTEM_CONTEXT_RENDERED=$rendered"
}

# Render a reviewer-scoped subset of system_context.json to a tempfile.
# Centralizes the section list so the four close-skill preloads share a
# single source of truth (no inline --sections literals at call sites).
#
# Usage: system_context_render_to_tempfile_for <kind>
#   kind=plan-reviewer  → product/architecture/stack/modules/conventions/
#                         branching/acceptance full + principles and
#                         project_specific topics-only (~1.8K tokens)
#   kind=close-reviewer → stack/conventions/branching full + principles
#                         topics-only (~0.9K tokens)
# Echoes the tempfile path on stdout. Non-zero exit on unknown kind.
#
# Adding a new caller? Update the System Context reader list in
# PROCESS_GUIDE.md in the same commit (the list is user-facing and should
# stay in sync with actual readers).
system_context_render_to_tempfile_for() {
    local kind="$1"
    local out rc sections topics_only empty
    case "$kind" in
        plan-reviewer)
            sections="product,architecture_overview,stack,modules,conventions,branching_strategy,acceptance_surfaces,principles,project_specific"
            topics_only="principles,project_specific"
            ;;
        close-reviewer)
            sections="stack,conventions,branching_strategy,principles"
            topics_only="principles"
            ;;
        *)
            echo "system_context_render_to_tempfile_for: unknown kind '$kind'" >&2
            return 1
            ;;
    esac
    out=$(mktemp "${SMM_DIR}/.system-context-rendered.XXXXXX")
    python3 "${PLUGIN_ROOT}/smm/system_context_cli.py" --smm-dir "$SMM_DIR" \
        render --sections "$sections" --topics-only "$topics_only" \
        > "$out" 2>/dev/null
    rc=$?
    # Catch silent-empty render: a future schema rename that desyncs the
    # --sections literals from the renderer would otherwise produce an
    # empty tempfile with rc=0 (stderr swallowed). Fail loud so callers
    # don't pass a fake-looking path downstream.
    empty=1
    [ -s "$out" ] && empty=0
    if [ "$rc" -ne 0 ] || [ "$empty" -eq 1 ]; then
        echo "system_context_render_to_tempfile_for: render failed (rc=$rc empty=$empty)" >&2
        rm -f "$out"
        return 1
    fi
    echo "$out"
}

dump_values() {
    local values="${PLUGIN_ROOT}/XP_VALUES.md"
    if [ -f "$values" ]; then
        echo ""
        echo "## XP Values"
        cat "$values"
    else
        echo "## XP Values: not found"
    fi
}

# Echo "true" if the working tree has no staged/unstaged changes, else "false".
# Usage: worktree_clean
worktree_clean() {
    if [ -z "$(git status --porcelain 2>/dev/null)" ]; then
        echo "true"
    else
        echo "false"
    fi
}

# Echo "true" if the gh CLI is on PATH, else "false". Uses the POSIX
# command -v builtin instead of `which` (no extra subprocess).
# Usage: gh_available
gh_available() {
    if command -v gh >/dev/null 2>&1; then
        echo "true"
    else
        echo "false"
    fi
}

# Echo "present" or "absent" — does the project run tests via a git
# hook on commit or push? Used by the close-skill preloads to drive
# the hook-absent fallback prose. Falls through to "absent" if the
# helper is missing or python3 is unavailable.
# Usage: pre_commit_hook_present
pre_commit_hook_present() {
    python3 "${PLUGIN_ROOT}/scripts/close_common.py" \
        hook-present --cwd . 2>/dev/null || echo "absent"
}

# Print current UTC time in ISO 8601 format matching events.jsonl's
# `ts` field shape ("YYYY-MM-DDTHH:MM:SS.ffffff+00:00"). Used by
# close-skill preloads to capture CLOSE_START_TS for the Step 6
# auto-merge gate's `count-classifications --since-ts` bound. Python
# (not `date`) for portability — `date -u --iso-8601=seconds` is
# GNU-only; macOS BSD `date` rejects the long flag form.
#
# Mirrors smm/_append_impl.py:now_iso() (the source-of-truth used
# by append.sh when stamping events.jsonl entries). This shell
# variant exists because preload.sh runs before any Python module
# is imported; calling _append_impl directly would force preload to
# set up sys.path. Lexicographic comparison against event ts values
# is safe because both sides use the same fixed-width zero-padded
# fields produced by datetime.isoformat().
#
# Usage: now_iso
now_iso() {
    python3 -c "import datetime; print(datetime.datetime.now(datetime.timezone.utc).isoformat())"
}

# Emit a close_started status event naming the close mode. ALL FOUR close
# preloads call this — story-close included, so its cycle stays auditable
# after the marker is swept.
#
# The mode is what carries the security meaning, NOT the presence of the call:
# retro_metrics.security_close_ran counts this event only for the modes that
# run a Step 4 security review (sprint/free/plan), so a story-close-only
# session correctly leaves security_close_ran=False. Adding `story` to that
# set is what would break it. A second consumer scopes on the mode the same
# way — see close_cycle_stop_gate._GATE_ARMING_CLOSE_MODES, whose set answers
# a different question (which closes arm the Stop-gate marker) and happens to
# hold the same three modes.
#
# stdout is suppressed (returned event id is preload noise), but stderr
# is intentionally left visible: this event gates the security-checks=0
# Courage rule, so a silent failure here would disable the very rule
# this helper exists to keep firing. `|| true` keeps preload servo
# continuity, but the user sees the failure mode in stderr.
#
# Usage: emit_close_started_event sprint <CLOSE_CYCLE_ID>
emit_close_started_event() {
    local close_mode="$1"
    local close_cycle_id="$2"
    "${PLUGIN_ROOT}/smm/append.sh" --smm-dir "$SMM_DIR" \
        --type status --agent "xp-${close_mode}-close" \
        --content "Close-cycle started: ${close_mode}" \
        --working-on '[]' \
        --metadata "{\"action\":\"close_started\",\"close_mode\":\"${close_mode}\",\"close_cycle_id\":\"${close_cycle_id}\"}" \
        >/dev/null || true
}

# Generate a 12-char hex ID matching event_builder.generate_id() shape.
# Used by close-skill preloads to capture CLOSE_CYCLE_ID — the strict
# scoper for the Step 6 auto-merge gate's count-classifications query.
# Cycle-id (not just since-ts) prevents concurrent close-cycles in
# other teammate worktrees from leaking concern_classify events into
# this cycle's count.
#
# Usage: generate_id
generate_id() {
    python3 -c "import secrets; print(secrets.token_hex(6))"
}

# Look up the project's test command from system_context.stack.test_command.
# Returns the value (e.g. "pytest -n auto", "npm test", "cargo test")
# or empty string when unset / system_context.json missing.
#
# Used by the story-close + free-close auto-merge override (Step 6) to
# decide whether to fire a deterministic test gate before merging.
# Empty result means "no test command configured" — the override falls
# through to the confirm prompt rather than guessing a project-specific
# command (the plugin ships to repos that may use any test runner or
# none at all).
#
# Wraps `system_context_cli.py get-stack-field test_command`, mirroring
# the `pre_commit_hook_present` pattern of delegating to the
# corresponding CLI rather than inlining Python in shell.
#
# To enable the auto-merge gate in your project, set the field via:
#     printf %s '"<your test command>"' | python3 \
#         "${PLUGIN_ROOT}/smm/system_context_cli.py" --smm-dir "$SMM_DIR" \
#         edit-stack-field test_command
# (or let /xp-system-context's analyzer detect it from your project's
# package.json / pyproject.toml / Cargo.toml / etc. — see Step 3.7
# of agents/xp-system-analyzer.md).
#
# Usage: find_test_command
find_test_command() {
    python3 "${PLUGIN_ROOT}/smm/system_context_cli.py" \
        --smm-dir "${SMM_DIR}" get-stack-field test_command 2>/dev/null \
        || echo ""
}

# Conditionally emit a HOOK_GUIDANCE section when no hook will fire on
# the close skill's merge. Single source of truth — replaces 4 copies
# of identical prose previously inlined in each close skill's SKILL.md.
# Usage: emit_hook_guidance "$(pre_commit_hook_present)"
emit_hook_guidance() {
    if [ "$1" = "absent" ]; then
        echo ""
        echo "### HOOK_GUIDANCE"
        echo "PRE_COMMIT_HOOK=absent — the Step 7 merge fires no project"
        echo "tests. Run the project's test command (its agent instructions"
        echo "file records it) before confirming the merge."
    fi
}

# Emit the two absolute paths Step 4b hands the Workflow tool: the script, and
# the root its finder agents read their angle prose from.
# Resolved HERE because that step's prose is `cat`'d raw and a tool argument has
# no shell to expand a `${CLAUDE_PLUGIN_ROOT}` in — the reasoning in full, and
# the check that the path exists, are in
# tests/integration/_close_preloads_review_helpers.py. PLUGIN_ROOT is
# BASH_SOURCE-derived, so this needs no env var; emit_path_var because an
# install path may hold consecutive spaces flat() would collapse.
# Called only by the modes that RUN Step 4b (free/sprint/plan).
# Usage: emit_workflow_script
emit_workflow_script() {
    emit_path_var WORKFLOW_SCRIPT "${PLUGIN_ROOT}/workflows/code_review.js"
    emit_path_var PLUGIN_ROOT "${PLUGIN_ROOT}"
}

# Git-diff helpers (_git, get_changed_files, dump_diff, and their committed-
# range variants) live in a sibling module — extracted when this file crossed
# the 500-line cap. Sourced here so every preload that sources _preload_base.sh
# gets them transitively, with no call-site changes.
# shellcheck source=_preload_diff.sh
source "$(dirname "${BASH_SOURCE[0]}")/_preload_diff.sh"

smm_has_section() {
    python3 "${PLUGIN_ROOT}/smm/smm_cli.py" --smm-dir "$SMM_DIR" has-section "$1" 2>/dev/null
}

# Find the latest retrospective JSON file.
# Usage: get_latest_retro "$RETRO_DIR"
# Returns path on stdout, empty string if none found.
get_latest_retro() {
    find "$1" -maxdepth 1 -name "*.json" 2>/dev/null | sort -r | head -1
}

# Extract Try items from a retrospective JSON file.
# Usage: get_try_items "$RETRO_FILE"
# Outputs "- <content> [refs: <id1>, ...]" lines when event_refs present.
#
# Every Try is offered, none are skipped. There used to be a `try_status` skip
# branch here, and it was dormant: `try_status` is computed for the retro AGENT
# and never persisted — save_retrospective writes only timestamp/keep/fix/try/
# analysis_notes — so the file this reads has never carried it. Were it revived
# it would now be actively wrong: `resolved_this_session` means "finished with",
# and an ADOPTED Try is open, in flight, and must stay on offer. Dropping it from
# the list is indistinguishable from it having been done.
get_try_items() {
    python3 -c "
import json, sys
data = json.load(open(sys.argv[1]))
for item in data.get('try', []):
    c = item.get('content', item) if isinstance(item, dict) else item
    refs = list(item.get('event_refs', [])) if isinstance(item, dict) else []
    own_id = item.get('id', '') if isinstance(item, dict) else ''
    if own_id:
        refs.insert(0, own_id)
    if refs:
        print(f'- {c} [refs: {\", \".join(refs)}]')
    else:
        print(f'- {c}')
" "$1" 2>/dev/null || true
}

# Sprint CLI helpers (thin wrappers over sprint_cli.py).
sprint_exists() {
    python3 "${PLUGIN_ROOT}/smm/sprint_cli.py" --smm-dir "$SMM_DIR" exists 2>/dev/null
}

sprint_has_active() {
    python3 "${PLUGIN_ROOT}/smm/sprint_cli.py" --smm-dir "$SMM_DIR" has-active 2>/dev/null
}

# Count stories with a specific status. Returns a single number.
# Usage: sprint_count_status ready
sprint_count_status() {
    python3 "${PLUGIN_ROOT}/smm/sprint_cli.py" --smm-dir "$SMM_DIR" count-status "$1" 2>/dev/null || echo "0"
}

# List stories, optionally filtered by status.
# Usage: sprint_list_stories [--status ready]
sprint_list_stories() {
    python3 "${PLUGIN_ROOT}/smm/sprint_cli.py" --smm-dir "$SMM_DIR" list-stories "$@" 2>/dev/null
}

# Deferred stories to carry into the next sprint. Archive-aware: sprint-close
# MOVES sprint.json, so by sprint-start there is no live file to read. Emits
# `SOURCE: <path>` (where full story definitions live), `WARNING: <reason>`, and
# `STORY: <id>: <title> [<status>]` lines; the command prints its own advisories
# to stdout precisely because this helper discards stderr.
#
# Fail-soft, because under `set -e` a bare command substitution would abort the
# whole preload — but NOT silently: a bare `|| true` would turn any unanticipated
# nonzero exit back into an empty block with no signal, which is the exact bug
# this reader was written to end.
sprint_list_carryover() {
    python3 "${PLUGIN_ROOT}/smm/sprint_cli.py" --smm-dir "$SMM_DIR" list-carryover 2>/dev/null \
        || echo "WARNING: the carry-over reader failed; deferred stories from the previous sprint may be missing."
}

# Next sprint ID (increments current, falls back to sprint-001).
sprint_next_id() {
    python3 "${PLUGIN_ROOT}/smm/sprint_cli.py" --smm-dir "$SMM_DIR" next-id 2>/dev/null || echo "sprint-001"
}

sprint_count() {
    python3 "${PLUGIN_ROOT}/smm/sprint_cli.py" --smm-dir "$SMM_DIR" count 2>/dev/null
}

smm_section() {
    local name="$1"
    python3 "${PLUGIN_ROOT}/smm/smm_cli.py" --smm-dir "$SMM_DIR" section "$name" 2>/dev/null
}

# Canonical filename — single source of truth for shell scripts.
SYSTEM_CONTEXT_FILE="${SMM_DIR}/system_context.json"

# Output SYSTEM_CONTEXT=<path> if system_context.json exists (not a symlink).
check_system_context() {
    local ctx="${SYSTEM_CONTEXT_FILE}"
    if [ -f "$ctx" ] && [ ! -L "$ctx" ]; then
        echo ""
        echo "SYSTEM_CONTEXT=${ctx}"
    fi
}

# Execution plan CLI helpers (thin wrappers over plan_cli.py).
plan_exists() {
    python3 "${PLUGIN_ROOT}/smm/plan_cli.py" --smm-dir "$SMM_DIR" exists 2>/dev/null
}

plan_has_remaining() {
    python3 "${PLUGIN_ROOT}/smm/plan_cli.py" --smm-dir "$SMM_DIR" has-remaining 2>/dev/null
}

plan_count() {
    python3 "${PLUGIN_ROOT}/smm/plan_cli.py" --smm-dir "$SMM_DIR" count 2>/dev/null
}

# Branching CLI helpers (thin wrappers over scripts/branching.py).
# List the user's free branches, excluding HEAD. One branch per line.
# Usage: branching_list_free
branching_list_free() {
    python3 "${PLUGIN_ROOT}/scripts/branching.py" \
        --smm-dir "$SMM_DIR" list-free --cwd . 2>/dev/null
}

# List orphan story branches (story branches not backed by active stories).
# Usage: branching_list_story_orphans
branching_list_story_orphans() {
    python3 "${PLUGIN_ROOT}/scripts/branching.py" \
        --smm-dir "$SMM_DIR" list-story-orphans --cwd . 2>/dev/null
}

# Print the branching stage integer (0 when unset). Auto-promotes 1->2 as a
# side effect, identical to a SKILL.md Step 0 read.
# Usage: branching_stage
branching_stage() {
    python3 "${PLUGIN_ROOT}/scripts/branching.py" \
        --smm-dir "$SMM_DIR" stage 2>/dev/null
}

# Emit the raw `<abs-path>\t<branch>` line for the live teammate worktree
# whose sprint.json story is `closing`, or empty when none matches (solo /
# no teammate mid-close). Callers split the tab themselves:
#   path:   ${closing%$'\t'*}     branch: ${closing##*$'\t'}
# Single source of truth for the CLI command + flags, shared by the
# xp-story-close and xp-quality-review preloads (both route story-close
# work to the same worktree).
#
# Deliberately NO `2>/dev/null`/`|| echo` swallow: multi-match raises in the
# CLI (exit 1) — a broken /xp-accept iteration — and that non-zero MUST
# propagate through the caller's `closing=$(...)` under `set -e` to fail
# loud. The missing-sprint.json case is already graceful (load_sprint→None
# → CLI exit 0, empty stdout). Usage: closing=$(find_closing_teammate_worktree)
find_closing_teammate_worktree() {
    python3 "${PLUGIN_ROOT}/scripts/branching.py" \
        --smm-dir "${SMM_DIR}" find-closing-teammate-worktree --cwd .
}

# Read the session's review cadence ('commit' or 'story') via cadence_cli.py.
# Fail-safes to 'commit' when the marker is unset or python3/cadence_cli is
# unavailable. Both the READ side (quality-review + story-close preloads, here)
# and the WRITE side (xp-kickoff) now route through cadence_cli.py — no inline
# python3 -c markers bootstrap remains.
# Usage: cadence=$(_get_review_cadence)
_get_review_cadence() {
    python3 "${PLUGIN_ROOT}/scripts/cadence_cli.py" --smm-dir "${SMM_DIR}" read 2>/dev/null || echo commit
}

# Marker helpers (consume_marker, write_marker, marker_exists) live in a sibling
# module — extracted when this file crossed the 500-line cap, the same move that
# produced _preload_emit.sh and _preload_diff.sh. Sourced here so every preload
# that sources _preload_base.sh gets them transitively, with no call-site changes.
# shellcheck source=_preload_markers.sh
source "$(dirname "${BASH_SOURCE[0]}")/_preload_markers.sh"
