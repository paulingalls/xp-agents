#!/bin/bash
set -euo pipefail
# Preload for security triage: show diff + write marker + log event.
# Running the skill IS the triage — the agent sees the diff and decides
# if /security-review is also needed. The marker is written unconditionally
# because the skill loading means triage happened.

# shellcheck source=../../_preload_base.sh
source "$(dirname "$0")/../../_preload_base.sh"

echo "SMM_DIR=${SMM_DIR}"
echo ""

# Show both staged and unstaged diffs
STAGED_STAT=$(git diff --cached --stat 2>/dev/null || true)
UNSTAGED_STAT=$(git diff --stat 2>/dev/null || true)

if [ -n "$STAGED_STAT" ]; then
    echo "## Staged Changes"
    echo "$STAGED_STAT"
    echo ""
    echo "## Staged Diff"
    git diff --cached 2>/dev/null || true
fi

if [ -n "$UNSTAGED_STAT" ]; then
    echo ""
    echo "## Unstaged Changes"
    echo "$UNSTAGED_STAT"
    echo ""
    echo "## Unstaged Diff"
    git diff 2>/dev/null || true
fi

if [ -z "$STAGED_STAT" ] && [ -z "$UNSTAGED_STAT" ]; then
    echo "## No Changes"
    echo "(no staged or unstaged changes detected)"
fi

# Write triage marker + log event (merged from mark_triaged.py)
python3 "${PLUGIN_ROOT}/skills/xp-security-triage/scripts/mark_triaged.py" --smm-dir "${SMM_DIR}" 2>/dev/null || true
