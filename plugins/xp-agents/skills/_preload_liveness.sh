# shellcheck shell=bash
# Refuse to hand a skill any context when the hook runtime is not live.
#
# When that runtime fails to load, every gate it enforces disappears and the
# session looks normal — nothing is blocked and nothing is said. The check that
# would report it cannot itself be a hook. A preload is an instruction-time
# load, so it still runs when the thing it tests is broken; that is the whole
# reason this check can exist here and nowhere else.
#
# A preload CANNOT block. Its only channel is stdout, which becomes context, so
# refusal means starvation plus instruction: emit the banner, suppress the
# preload's normal output, exit. That is as strong as this mechanism gets, and
# the banner must not imply otherwise.
#
# Sourced by _preload_base.sh immediately after the SMM resolves and before any
# other output. Extracted rather than inlined because the base is at its size
# cap and has already been split twice (_preload_emit.sh, _preload_diff.sh).
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
