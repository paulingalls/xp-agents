#!/bin/bash
set -euo pipefail

# Validate Python 3.10+
if ! python3 -c "import sys; assert sys.version_info >= (3,10), f'Python 3.10+ required, got {sys.version}'" 2>/dev/null; then
    echo "Error: Python 3.10+ is required" >&2
    exit 1
fi

# Derive project-id from git-common-dir
# git rev-parse --git-common-dir returns relative path in main worktree (.git)
# Must resolve to absolute path before hashing for worktree consistency
GIT_COMMON_DIR=$(git rev-parse --git-common-dir 2>/dev/null) || {
    echo "Error: Not in a git repository" >&2
    exit 1
}

# Resolve to absolute path (handles both relative .git and absolute worktree paths)
if [[ "$GIT_COMMON_DIR" != /* ]]; then
    GIT_COMMON_DIR="$(cd "$GIT_COMMON_DIR" && pwd)"
fi

# Hash to create project-id (first 12 chars of SHA256)
# Uses Python for portability — shasum (macOS/Perl) and sha256sum (Linux/coreutils)
# aren't both available on all platforms, but Python 3.10+ is already required.
PROJECT_ID=$(printf '%s' "$GIT_COMMON_DIR" | python3 -c "import hashlib,sys; print(hashlib.sha256(sys.stdin.read().encode()).hexdigest()[:12])")

SMM_DIR="${HOME}/.claude/xp-agents/${PROJECT_ID}/smm"

# Create directory structure (owner-only permissions)
mkdir -p "${SMM_DIR}/retrospectives"
chmod 700 "${SMM_DIR}"

# Touch event files (touch never truncates, safe to call unconditionally)
touch "${SMM_DIR}/events.jsonl"
chmod 600 "${SMM_DIR}/events.jsonl"
touch "${SMM_DIR}/events.lock"
chmod 600 "${SMM_DIR}/events.lock"

# Output the SMM directory path
echo "${SMM_DIR}"
exit 0
