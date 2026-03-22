#!/bin/bash
set -euo pipefail
# Preload diff for security triage classification.
# Show both staged and unstaged — the agent may stage more files
# before committing, especially if a combined git add && git commit
# was blocked before git add executed.
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
