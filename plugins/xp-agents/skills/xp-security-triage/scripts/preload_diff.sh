#!/bin/bash
set -euo pipefail
# Preload staged diff for security triage classification.
echo "## Staged Changes"
git diff --cached --stat 2>/dev/null || echo "(no staged changes)"
echo ""
echo "## Full Diff"
git diff --cached 2>/dev/null || echo "(no diff available)"
