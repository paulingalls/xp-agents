#!/bin/bash
set -euo pipefail

# Validate Python 3.10+
if ! python3 -c "import sys; assert sys.version_info >= (3,10), f'Python 3.10+ required, got {sys.version}'" 2>/dev/null; then
    echo "Error: Python 3.10+ is required" >&2
    exit 1
fi

# If SMM_DIR is already exported (e.g. by a teammate spawner), use it verbatim
# and skip derivation. This is how the lead propagates its SMM to teammates.
if [[ -z "${SMM_DIR:-}" ]]; then
    # Derive project-id from git-common-dir
    # git rev-parse --git-common-dir returns relative path in main worktree (.git)
    # Must resolve to absolute path before hashing for worktree consistency
    GIT_COMMON_DIR=$(git rev-parse --git-common-dir 2>/dev/null) || {
        echo "Error: Not in a git repository" >&2
        exit 1
    }

    # Resolve to absolute path (handles both relative .git and absolute worktree paths)
    if [[ "$GIT_COMMON_DIR" != /* ]]; then
        GIT_COMMON_DIR="$(cd -- "$GIT_COMMON_DIR" && pwd -P)"
    fi

    # Hash to create project-id (first 12 chars of SHA256)
    # Uses Python for portability — shasum (macOS/Perl) and sha256sum (Linux/coreutils)
    # aren't both available on all platforms, but Python 3.10+ is already required.
    PROJECT_ID=$(printf '%s' "$GIT_COMMON_DIR" | python3 -c "import hashlib,sys; print(hashlib.sha256(sys.stdin.read().encode()).hexdigest()[:12])")

    # Use CLAUDE_PLUGIN_DATA if available (standard plugin ecosystem path),
    # fall back to the standard plugin data directory for marketplace installs.
    BASE_DIR="${CLAUDE_PLUGIN_DATA:-${HOME}/.claude/plugins/data/xp-agents-xp-agents}"
    SMM_DIR="${BASE_DIR}/${PROJECT_ID}/smm"

    mkdir -p "${SMM_DIR}/retrospectives"
    # Restrict the ancestor dirs we just created. Only safe inside this branch —
    # if a caller provided SMM_DIR, BASE_DIR may be an unrelated inherited env
    # var we must not touch.
    chmod 700 "${BASE_DIR}" "${BASE_DIR}/${PROJECT_ID}"
else
    mkdir -p "${SMM_DIR}/retrospectives"
fi

chmod 700 "${SMM_DIR}" "${SMM_DIR}/retrospectives"

# Touch event files (touch never truncates, safe to call unconditionally)
touch "${SMM_DIR}/events.jsonl"
chmod 600 "${SMM_DIR}/events.jsonl"
touch "${SMM_DIR}/events.lock"
chmod 600 "${SMM_DIR}/events.lock"

# Seed default SMM for new projects (scans for linter, tests, hooks, CI)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
python3 "${SCRIPT_DIR}/seed_smm.py" "${SMM_DIR}" 2>/dev/null || true

# Output the SMM directory path
echo "${SMM_DIR}"
exit 0
