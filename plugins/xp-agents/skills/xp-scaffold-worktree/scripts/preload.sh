#!/bin/bash
set -euo pipefail
# Preload for xp-scaffold-worktree: the declared state the skill branches on
# before it measures anything. State-derived — no marker to clear.
#
# Sources the shared base and adds NOTHING to it. That base sits a handful of
# lines under its size cap, and the cap's scanner does not read shell, so a
# helper added there would cross it silently. Everything below is either a base
# helper called as-is or a call this skill alone makes.
# shellcheck source=../../_preload_base.sh
source "$(dirname "$0")/../../_preload_base.sh"

# SMM_DIR only. `PLUGIN_ROOT` is emitted by three older preloads and read by
# none of them — every SKILL.md spells plugin paths `${CLAUDE_PLUGIN_ROOT}`,
# including this one — so a fourth copy would be injected context with no
# reader.
echo "SMM_DIR=${SMM_DIR}"

# The differential's `--cwd` must be the checkout ROOT — it refuses a
# subdirectory, and refuses an empty value outright. Resolved HERE rather than
# in a skill step, because a shell variable assigned in one Bash call does not
# survive into the next one, so the flag would arrive empty on every run.
# `pwd` when this is not a checkout at all: the differential's own refusal is
# the honest report of that, and a dead preload would report nothing.
emit_path_var REPO_ROOT "$(git rev-parse --show-toplevel 2>/dev/null || pwd)"

# Both fields read `none` rather than empty when unset. An empty value cannot be
# branched on: `CURRENT_BOOTSTRAP=` is indistinguishable from a preload that
# died mid-line, and the skill's first step has to tell "nothing declared" from
# "something went wrong" before it runs a command in the customer's checkout.
BOOTSTRAP=$(python3 "${PLUGIN_ROOT}/smm/system_context_cli.py" \
    --smm-dir "${SMM_DIR}" get-stack-field worktree_bootstrap 2>/dev/null || echo "")
emit_var CURRENT_BOOTSTRAP "${BOOTSTRAP:-none}"

TEST_COMMAND=$(find_test_command)
emit_var TEST_COMMAND "${TEST_COMMAND:-none}"
# Emitted explicitly, not implied by the empty var above — a reader that has to
# infer a state from an absent value infers it wrong on the run where the
# absence meant something else.
if [ -z "${TEST_COMMAND}" ]; then
    echo "NONE_DECLARED=true"
fi

# Load-bearing, not informational. The differential creates its worktree leg at
# HEAD while the primary leg runs against the working tree, so a single
# uncommitted tracked edit diverges the two legs on its own — a gap no bootstrap
# could close, reported as one that needs a bootstrap.
echo "WORKTREE_CLEAN=$(worktree_clean)"

# Declared surfaces, for the closing scope report: the bootstrap is verified
# against ONE command, and a surface carrying its own command was not covered by
# that verification. Rendered through the general `render`, deliberately not
# through the surface-command subcommand — that one is being removed.
#
# Each line is `- `-prefixed and framing-stripped before it is printed. A
# surface command may legitimately begin `NAME=value ...`, which at line start
# would stand up as a preload variable and shadow a real one; the prefix is what
# makes that impossible, and strip_framing removes the newline/CR/tab vectors
# that would otherwise forge a line of their own.
SURFACES=$(python3 "${PLUGIN_ROOT}/smm/system_context_cli.py" \
    --smm-dir "${SMM_DIR}" render --sections acceptance_surfaces 2>/dev/null || echo "")
SURFACE_BULLETS=$(printf '%s\n' "${SURFACES}" | grep -E '^[[:space:]]*- ' || true)
if [ -n "${SURFACE_BULLETS}" ]; then
    echo ""
    echo "### SURFACES"
    printf '%s\n' "${SURFACE_BULLETS}" | while IFS= read -r line; do
        printf -- '- %s\n' "$(strip_framing "${line#*- }")"
    done
fi
