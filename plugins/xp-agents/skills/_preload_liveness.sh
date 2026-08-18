# shellcheck shell=bash
# Refuse to hand a skill any context when the hook runtime is not live.
#
# When that runtime stops enforcing, every gate it carries disappears and the
# session looks normal — nothing is blocked and nothing is said.
#
# WHAT THIS STILL DETECTS, and what it no longer can. This fragment used to be
# reached at instruction time, before any hook ran, which let it judge a runtime
# that had not loaded at all. Sprint-007 deleted the `!` lines, so the only
# route here is now `_preload_base.sh` <- `preload_injection.py` — a hook. Two
# states follow, and only the first is ours:
#
#   running, but not heartbeating (hooks loading yet not writing markers, a
#   stale or unreadable heartbeat, a teammate that cannot borrow the lead's) —
#   the preload runs, so the banner still fires. This is the state the whole
#   fragment now exists for, and it is a real one.
#
#   not loaded at all — unreachable from here by construction, because nothing
#   runs this file. story-009 owns that case; do not add a caller to chase it
#   without reading that story's AC3 first, which forbids liveness machinery on
#   the daily path. `tests/skills/test_preload_liveness.py` pins the coupling,
#   so a second caller reddens rather than passing quietly.
#
# A preload CANNOT block. Its only channel is stdout, which becomes context, so
# refusal means starvation plus instruction: emit the banner, suppress the
# preload's normal output, exit. That is as strong as this mechanism gets, and
# the banner must not imply otherwise.
#
# Sourced by _preload_base.sh immediately after the SMM resolves and before any
# other output — and by nothing else, which is the coupling above. Extracted
# rather than inlined because the base is at its size cap and has already been
# split twice (_preload_emit.sh, _preload_diff.sh).
#
# Requires PLUGIN_ROOT and SMM_DIR to be set by the caller.

# Fails CLOSED — the opposite direction from the `cadence_cli || echo commit`
# fail-safe further down the base. `hook_liveness.py status` exits 0 only on a
# positive verdict; every other status refuses, using the CLI's own reason text.
# The CLI already separates determined-not-live from could-not-determine and
# words them differently, so no verdict logic is re-derived here.
if [ "${XP_SKIP_LIVENESS_CHECK:-}" != "1" ]; then
    if ! _liveness_reason=$(python3 "${PLUGIN_ROOT}/scripts/hook_liveness.py" \
        --smm-dir "${SMM_DIR}" status 2>/dev/null); then
        # An empty reason means the check itself did not run (no interpreter, a
        # missing script). Unknown is not live, so it refuses too — but it must
        # not borrow the diagnosis of a verdict that was never reached.
        if [ -z "${_liveness_reason}" ]; then
            _liveness_reason="The hook-liveness check could not run, so whether the hook runtime is live is unknown and must not be assumed."
        fi
        # Distinct from the base's "## SMM State: unavailable": no shared model
        # at all is a different failure, with a different fix, from a shared
        # model whose runtime has stopped.
        echo "## Hook Runtime: not live — skill context withheld"
        echo ""
        echo "${_liveness_reason}"
        echo ""
        echo "The gates this skill relies on are not running, so its steps would go"
        echo "unenforced. Restore the hook runtime, then re-run. To proceed without"
        echo "the gates, set XP_SKIP_LIVENESS_CHECK=1."
        exit 0
    fi
fi
