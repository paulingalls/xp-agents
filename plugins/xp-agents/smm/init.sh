#!/bin/bash
set -euo pipefail

# Hash first 12 hex chars of SHA256(stdin). Prefer shasum/sha256sum (native
# binaries, ~2ms) over python3 (~20ms interpreter startup). Fall back to
# python3 if neither is on PATH — seed_smm.py will fail loudly on old Python.
hash12() {
    if command -v shasum >/dev/null 2>&1; then
        shasum -a 256 | cut -c1-12
    elif command -v sha256sum >/dev/null 2>&1; then
        sha256sum | cut -c1-12
    else
        python3 -c "import hashlib,sys; print(hashlib.sha256(sys.stdin.read().encode()).hexdigest()[:12])"
    fi
}

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

    PROJECT_ID=$(printf '%s' "$GIT_COMMON_DIR" | hash12)

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
touch "${SMM_DIR}/events.jsonl" "${SMM_DIR}/events.lock"
chmod 600 "${SMM_DIR}/events.jsonl" "${SMM_DIR}/events.lock"

# Seed default SMM only on first run. The bash-level gate skips Python
# startup (~48ms). Errors surface (no `|| true`) so wrong-Python failures —
# seed_smm.py requires 3.10+ — are visible instead of silently producing an
# unseeded SMM.
if [[ ! -f "${SMM_DIR}/shared_mental_model.json" ]]; then
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    python3 "${SCRIPT_DIR}/seed_smm.py" "${SMM_DIR}"
fi

# Output the SMM directory path
echo "${SMM_DIR}"
exit 0
