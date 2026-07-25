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

    # Where a NEW SMM goes. XP_AGENTS_DATA is ours and nothing else is a
    # write preference: CLAUDE_PLUGIN_DATA resolves to
    # ~/.claude/plugins/data/{id}/, which `claude plugin uninstall` DELETES by
    # default (--keep-data opts out), so an SMM living there is one uninstall
    # away from silent loss. The harness always sets that var, so honoring it as
    # a preference would make this change a no-op for every real user.
    # An explicitly named root is AUTHORITATIVE: when the caller says where the
    # SMM goes, we do not go hunting under legacy roots. Discovery below exists
    # for the UPGRADE path, where this var is unset and a previous version left
    # an SMM under a plugin-data root — searching when a root was named is both
    # wrong (they said where) and unsafe, because the search reaches the real
    # $HOME and would resolve a live SMM from under a caller that had
    # deliberately redirected the root.
    if [[ -n "${XP_AGENTS_DATA:-}" ]]; then
        NEW_BASE="${XP_AGENTS_DATA}"
        DISCOVER_LEGACY=0
    else
        NEW_BASE="${HOME}/.xp-agents/data"
        DISCOVER_LEGACY=1
    fi

    if [[ -d "${NEW_BASE}/${PROJECT_ID}/smm" ]] || [[ "${DISCOVER_LEGACY}" -eq 0 ]]; then
        BASE_DIR="${NEW_BASE}"
    else
        # Where an EXISTING SMM might already be — discovery only, never a write
        # target. A LIST, not one path: CLAUDE_PLUGIN_DATA is absent in some hook
        # processes, and a dev-mode install resolves the plugin id to
        # `xp-agents-inline` where a marketplace install gives
        # `xp-agents-xp-agents`. With a single candidate, a process that cannot
        # see the legacy root creates an EMPTY dir under NEW_BASE that then
        # permanently reads as "already migrated" — stranding the real history.
        # That is the silent loss this change exists to prevent, so the list is
        # load-bearing.
        #
        # Built HERE, not at top level: `nounset` makes an unset $HOME fatal, and
        # reaching this branch already proves $HOME is set (NEW_BASE derived from
        # it above). At top level the same lines made `XP_AGENTS_DATA=... HOME
        # unset` fail on a list that path never even reads.
        LEGACY_CANDIDATES=()
        if [[ -n "${CLAUDE_PLUGIN_DATA:-}" ]]; then
            LEGACY_CANDIDATES+=("${CLAUDE_PLUGIN_DATA}")
        fi
        LEGACY_CANDIDATES+=("${HOME}/.claude/plugins/data/xp-agents-xp-agents")
        LEGACY_CANDIDATES+=("${HOME}/.claude/plugins/data/xp-agents-inline")

        BASE_DIR=""
        for _candidate in "${LEGACY_CANDIDATES[@]}"; do
            if [[ -d "${_candidate}/${PROJECT_ID}/smm" ]]; then
                BASE_DIR="${_candidate}"
                break
            fi
        done
        # No SMM anywhere: a fresh project, which lands at the safe root.
        if [[ -z "${BASE_DIR}" ]]; then
            BASE_DIR="${NEW_BASE}"
        fi
    fi
    SMM_DIR="${BASE_DIR}/${PROJECT_ID}/smm"

    # Was the root already there BEFORE we ran? Decides whether narrowing its
    # mode is ours to do — see the chmod below.
    BASE_PRE_EXISTED=0
    if [[ -d "${BASE_DIR}" ]]; then
        BASE_PRE_EXISTED=1
    fi

    mkdir -p "${SMM_DIR}/retrospectives"

    # Narrow only what WE created. BASE_DIR used to always be the plugin-owned
    # data dir; it is now any path the user names via XP_AGENTS_DATA, and the
    # whole point of the var is that they name one — so `XP_AGENTS_DATA=$HOME`
    # would otherwise chmod 700 their home directory. The project-id dir is
    # always ours, so it is narrowed unconditionally.
    #
    # Intermediates that `mkdir -p` created (`~/a/b` given `~/a/b/c`) keep the
    # default umask; the SMM dir itself is chmodded 700 below regardless, which
    # is what actually protects the contents.
    if [[ "${BASE_PRE_EXISTED}" -eq 0 ]]; then
        chmod 700 "${BASE_DIR}"
    fi
    chmod 700 "${BASE_DIR}/${PROJECT_ID}"
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
