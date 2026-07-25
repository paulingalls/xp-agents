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

# One hop along a `.migrated-to` pointer, if one is there. Echoes the input
# unchanged otherwise, so this can wrap any resolved path.
#
# spawn_teammate exports SMM_DIR as an ABSOLUTE path and this script honors it
# verbatim, so a process spawned just before a migration keeps resolving the old
# tree for its whole life — its appends would land somewhere nothing reads again.
# One hop only: a chain would mean two migrations raced, which the lock prevents,
# and following one blindly risks a cycle.
follow_migration_pointer() {
    local dir="$1" target
    if [[ -f "${dir}/.migrated-to" ]]; then
        target="$(cat "${dir}/.migrated-to" 2>/dev/null || true)"
        if [[ -n "${target}" ]] && [[ -d "${target}" ]]; then
            printf '%s' "${target}"
            return 0
        fi
    fi
    printf '%s' "${dir}"
}

# Is any teammate live against this SMM? Migration must decline if so.
#
# TWO kinds, and checking only the first is the bug this exists to avoid:
# worktree teammates own a dir under `{project-id}/worktrees/`, while in-place
# teammates run in the MAIN checkout with no worktree dir at all and are tracked
# by `.in-place-active-*` markers inside the SMM. Either way the teammate's
# SMM_DIR was pinned at spawn and cannot be redirected, so relocating out from
# under one splits the event log with no merge path.
teammates_are_live() {
    local legacy_smm="$1" project_dir marker
    project_dir="$(dirname "${legacy_smm}")"
    if [[ -d "${project_dir}/worktrees" ]] &&
        [[ -n "$(ls -A "${project_dir}/worktrees" 2>/dev/null || true)" ]]; then
        return 0
    fi
    for marker in "${legacy_smm}"/.in-place-active-*; do
        if [[ -e "${marker}" ]]; then
            return 0
        fi
    done
    return 1
}

# How long a process that LOSES the migration lock waits for the winner, in
# WALL-CLOCK seconds. Seconds and not ticks, because the loop below sleeps 0.1s
# where fractional `sleep` works and a whole second where it is rejected: a
# fixed tick COUNT therefore meant two different budgets on two platforms, and
# the coarse one was 10x the fine one. At 30 ticks that came to exactly the 30s
# the SessionStart hook gives the whole of init.sh, so on any platform without
# fractional sleep a lock loser timed out with certainty and the session got no
# SMM at all — zero margin, by construction.
#
# Three seconds is the budget that was actually intended (30 x 0.1s), it is long
# enough for a local copy of a normal SMM, and it leaves the other ~27s of the
# caller's budget for the copy THIS process may still have to make plus the
# rest of init.sh. Past it, the legacy tree is returned and the appends made
# there after the winner's last re-sync are the price.
MIGRATE_WAIT_SECONDS=3

# Echo the migrated tree when it is already there, else the legacy one.
#
# Every exit from migrate_legacy_smm that is NOT "this process completed the
# migration" ends here, because a concurrent winner can finish at any point:
# checking only on some of those paths is how a process ends up appending to a
# tree that nothing reads again. Never empty — empty stdout from init.sh
# degrades the whole session to no-SMM.
answer_existing_smm() {
    local legacy="$1" new="$2"
    if [[ -d "${new}" ]]; then printf '%s' "${new}"; else printf '%s' "${legacy}"; fi
}

# Copy a legacy SMM to the new root and echo the directory to use.
#
# NEVER moves and never deletes the source: an interrupted or wrong migration
# then loses nothing, and every failure path below can fall back to the legacy
# tree. Every step is guarded rather than allowed to fail the script — `set -e`
# would otherwise abort init.sh, and since this is the single resolver for every
# script and hook, empty stdout degrades the WHOLE session to no-SMM.
migrate_legacy_smm() {
    local legacy="$1" new="$2" project_dir lock tmp holder stale stale_pid
    local tick ticks waited
    project_dir="$(dirname "${new}")"
    lock="${project_dir}/.migrate.lock"

    # umask, not a later chmod: the temp copy of the WHOLE SMM lands in here
    # before the project dir is narrowed at the end of init.sh, and the data
    # root created on this path never reaches that chmod at all (it already
    # exists by the time the mode check runs).
    if ! (umask 077 && mkdir -p "${project_dir}") 2>/dev/null; then
        printf '%s' "${legacy}"
        return 0
    fi

    # Break a lock whose HOLDER IS GONE — liveness, not age. An age bound races
    # a slow copy on a network filesystem: the breaker becomes a second winner
    # and its `mv` lands the temp INSIDE the populated destination, because
    # `mv dirA dirB` moves into dirB when dirB exists.
    #
    # The claim is a SYMLINK whose TARGET IS THE HOLDER'S PID, not a directory
    # with the pid written into it afterwards. Both `mkdir` and `ln -s` fail
    # atomically when the name is taken, but a directory cannot carry its holder
    # at the instant it appears — writing `lock/pid` is a SECOND step, and a
    # racer reading the lock in between sees no holder, concludes the lock is
    # stale and breaks a LIVE one. `ln -s` publishes the name and the holder in
    # one syscall, so that window does not exist. The target is a number rather
    # than a path, so the link is always dangling: `-e` and `-d` are false for
    # it, and `-L` is the only test that sees it.
    #
    # BREAKING one, though, is a read then a delete, and no shell primitive
    # makes that pair indivisible: two processes can read the SAME dead holder,
    # and the second one's delete lands on the FIRST one's fresh claim. (`mv`
    # instead of `rm` does not help — it acts on the NAME, so it takes the live
    # claim just the same.) Both then hold, both copy, and the final rename is
    # a `[[ -d ]]` check one syscall away from the `mv`, so the loser of that
    # buries a whole duplicate tree INSIDE the live SMM.
    #
    # So a run that breaks a lock frees the name and stops there — it does not
    # go on to claim it. A breaker never holds, so two breakers cannot both end
    # up holding, and the next run finds the name free and claims it
    # atomically. The cost is relocating one session later, which this design
    # already accepts wholesale (it declines outright while a teammate is live)
    # — and a dead lock only exists because a previous migration crashed.
    #
    # This NARROWS the window rather than closing it: the `rm` below is still
    # unconditional, so a break can be overtaken (another run frees the name
    # first, a third claims it, and this delete lands on that claim) — two
    # adjacent syscalls wide, where it used to span the whole liveness check.
    # What bounds the damage is everything downstream: the source tree is never
    # deleted, in-flight temps are reaped by liveness and not by ownership, and
    # the rename is guarded by a destination check. A second migrator that gets
    # past all three leaves a stray copy inside the new tree — not a loss.
    if [[ -L "${lock}" ]]; then
        holder="$(readlink "${lock}" 2>/dev/null || true)"
        if [[ ! "${holder}" =~ ^[0-9]+$ ]] || ! kill -0 "${holder}" 2>/dev/null; then
            rm -f "${lock}" 2>/dev/null || true
            answer_existing_smm "${legacy}" "${new}"
            return 0
        fi
    elif [[ -e "${lock}" ]]; then
        # Anything else at that name — including the directory-shaped lock an
        # OLDER version of this script wrote — names no holder we can verify.
        # Reaping beats yielding forever: an unbreakable lock would pin the SMM
        # in the deletable root permanently.
        rm -rf "${lock}" 2>/dev/null || true
        answer_existing_smm "${legacy}" "${new}"
        return 0
    fi

    if ! ln -s "$$" "${lock}" 2>/dev/null; then
        # Another process holds it. Do NOT settle for the legacy tree while that
        # is true: the winner's last whole-tree re-sync happens BEFORE its
        # rename, so anything appended to legacy after that instant never
        # reaches the migrated SMM and is invisible to every later session.
        # Wait for the winner — bounded, because an unbounded wait would hang
        # every hook behind one slow copy, and legacy is still a usable answer.
        # One probe settles BOTH the granularity and the tick count, so the
        # wall-clock budget above holds on either kind of platform: fractional
        # where it is supported, so polling stays fine-grained; whole seconds
        # where it is rejected, with a tenth of the ticks. The probe is itself
        # part of the wait, and this branch was about to wait regardless, so it
        # costs nothing.
        if sleep 0.1 2>/dev/null; then
            tick="0.1"
            ticks=$((MIGRATE_WAIT_SECONDS * 10))
            waited=1 # the probe was a real tick; do not pay for it twice
        else
            tick="1"
            ticks="${MIGRATE_WAIT_SECONDS}"
            waited=0 # a rejected probe waited for nothing
        fi
        while [[ ! -d "${new}" ]] && [[ -L "${lock}" ]] &&
            [[ "${waited}" -lt "${ticks}" ]]; do
            # The sleep may not fail the script — `set -e` would abort init.sh,
            # and empty stdout degrades the WHOLE session to no-SMM — so a
            # system with no usable `sleep` at all just spends the ticks
            # without waiting and falls back to legacy.
            sleep "${tick}" 2>/dev/null || true
            waited=$((waited + 1))
        done
        answer_existing_smm "${legacy}" "${new}"
        return 0
    fi

    # The destination was last seen absent by the CALLER, before this lock was
    # taken. A winner can have completed the whole migration in that window, so
    # yield to it rather than copying a tree we would only have to discard.
    if [[ -d "${new}" ]]; then
        rm -f "${lock}" 2>/dev/null || true
        printf '%s' "${new}"
        return 0
    fi

    # Holding the lock, so any other `.migrating.*` is residue from a crashed
    # run — EXCEPT one whose owner is still running. Reaped by the same liveness
    # rule as the lock: deleting a copy another process is still writing makes
    # it rename a TRUNCATED tree into place, and since completion is marked by
    # the destination existing, every later session reads that truncation as
    # the whole SMM.
    for stale in "${project_dir}"/.migrating.*; do
        [[ -e "${stale}" ]] || continue
        stale_pid="${stale##*.}"
        if [[ "${stale_pid}" =~ ^[0-9]+$ ]] && kill -0 "${stale_pid}" 2>/dev/null; then
            continue
        fi
        rm -rf "${stale}" 2>/dev/null || true
    done
    tmp="${project_dir}/.migrating.$$"

    if ! cp -R "${legacy}" "${tmp}" 2>/dev/null; then
        rm -rf "${tmp}" 2>/dev/null || true
        rm -f "${lock}" 2>/dev/null || true
        printf '%s' "${legacy}"
        return 0
    fi

    # Re-sync the WHOLE tree before the rename, not just events.jsonl: a session
    # start writes sprint.json, execution_plan.json, shared_mental_model.json,
    # session_history.json, .coordination.json and the gate markers too, and any
    # of them can change in the window above.
    if ! cp -R "${legacy}"/. "${tmp}"/ 2>/dev/null; then
        rm -rf "${tmp}" 2>/dev/null || true
        rm -f "${lock}" 2>/dev/null || true
        printf '%s' "${legacy}"
        return 0
    fi

    # Atomic claim — but ONLY while the destination is absent: `mv dirA dirB`
    # moves INTO dirB when dirB exists, which would bury a full duplicate of the
    # SMM inside the live one. The absence check above is not enough on its own,
    # since the copy is not instantaneous, so re-check at the last moment and
    # treat a destination that appeared as exactly what it is — a lost race,
    # handled the same as a failed rename. Completion is marked by `smm/`
    # existing, NOT by the project-id dir — a crash leaving a bare project-id
    # dir must never read as migrated, or the result is an empty SMM and
    # invisible history.
    if [[ -d "${new}" ]] || ! mv "${tmp}" "${new}" 2>/dev/null; then
        rm -rf "${tmp}" 2>/dev/null || true
        rm -f "${lock}" 2>/dev/null || true
        answer_existing_smm "${legacy}" "${new}"
        return 0
    fi

    printf '%s\n' "${new}" >"${legacy}/.migrated-to" 2>/dev/null || true
    rm -f "${lock}" 2>/dev/null || true
    printf '%s' "${new}"
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
        else
            # Found an SMM under a legacy root. Relocate it out of the
            # plugin-managed directory that `claude plugin uninstall` deletes —
            # unless a teammate is live against it, in which case using it in
            # place is the only safe choice.
            #
            # XP_SMM_MIGRATE overrides that default for the two things a
            # session cannot decide for itself. `off` resolves without
            # relocating, so a tool can report the current state without
            # changing it — a dry run that migrates is not a dry run. `force`
            # relocates despite the liveness signal, which is the one case
            # automation must never take on its own: the gate keys on a
            # worktree DIRECTORY, cleanup refuses on an unmerged branch by
            # design, and only a human knows whether that directory belongs to
            # a running teammate or to a story abandoned months ago.
            if [[ "${XP_SMM_MIGRATE:-}" != "off" ]] &&
                { [[ "${XP_SMM_MIGRATE:-}" == "force" ]] ||
                    ! teammates_are_live "${BASE_DIR}/${PROJECT_ID}/smm"; }; then
                SMM_DIR="$(migrate_legacy_smm \
                    "${BASE_DIR}/${PROJECT_ID}/smm" \
                    "${NEW_BASE}/${PROJECT_ID}/smm")"
                # migrate_legacy_smm echoes whichever tree to use — it falls back
                # to legacy on any failure — so re-derive the root from it rather
                # than assuming the copy succeeded.
                BASE_DIR="$(dirname "$(dirname "${SMM_DIR}")")"
            fi
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
    # A caller-provided SMM_DIR is honored verbatim — EXCEPT that a migration
    # may have moved the tree since this value was pinned at spawn. Following
    # the pointer costs one stat and keeps a straggler's appends in the log
    # everything else reads.
    SMM_DIR="$(follow_migration_pointer "${SMM_DIR}")"
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
