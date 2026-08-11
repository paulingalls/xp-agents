#!/usr/bin/env python3
"""Stop command hook: close-cycle gate.

Blocks Stop while a close skill is mid-cycle (CLOSE_CYCLE_ACTIVE marker
present), nudging the agent to invoke xp-close-reviewer next — unless evidence
of a completed reviewer has landed since the close started, in which case this
gate consumes the marker itself. The marker is written by the three closes that
run /security-review — sprint, plan and free — before that review runs, and
normally consumed by subagent_stop.py when xp-close-reviewer completes.

xp-story-close is deliberately OUTSIDE this gate, and the asymmetry is not an
oversight to correct. Two reasons, either sufficient: it skips Step 4 entirely
(the enclosing sprint-close covers its diff, so the block message's
/security-review and /code-review steps do not apply to it), and under story
cadence its review path is the full per-story review cycle, which does not fork
xp-close-reviewer — the only thing that releases this gate. Arming it there
would record a high-severity "close abandoned" concern against a close that ran
exactly the review it was supposed to. `_BYPASS_RECOVERY` naming
/xp-{sprint,plan,free}-close is correct as written for the same reason.

Story-close still has a cycle IDENTITY — every close mode writes its cycle id
to a separate marker, which the appender reads to tag concerns. That marker
arms no gate; the two are deliberately distinct files (see
marker_names.CLOSE_CYCLE_ID).

Defers on ASKING_USER so AskUserQuestion dialogues complete cleanly.
Also defers during the close /code-review's async Step 4b window —
`markers.review_mid_cycle`, under the key `identity.review_cycle_agent_id`
gives every writer of the flag (simplify_done set when the workflow launched,
quality_review_done not yet set when /xp-quality-review consumes its
findings). Pushing xp-close-reviewer there would run Step 4.5 BEFORE the
background /code-review returns; deferring (return None) lets the agent
yield and be re-woken by the workflow-completion notification. Teammates
deferral is intentionally NOT applied — outside Step 4b the close cycle
wants to block mid-cycle by design.

stop_hook_active bypass: Claude Code latches `stop_hook_active=True`
session-wide once any Stop hook returns a `reason` (e.g.,
`session_end_warning`'s nudge) — it does NOT reset per-turn. Once the
flag is True, this gate's block message can no longer reach the agent
reliably. So the bypass allows the Stop and asks
`close_cycle_abandonment.record_abandonment` whether the cycle died; on yes it
records a high-severity concern, emits stderr, and consumes the marker.

This gate does not decide that. The OWNING SESSION does: a close whose session
still heartbeats is running however old its marker is, and one whose session
stopped is abandoned however young. Age survives only as the fallback for an
owner that cannot be named or read. The decision lives in one place because
three detectors face it; see close_cycle_abandonment.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import _common
import close_cycle_abandonment
import event_schema
import identity
import markers
import target_routing

# Two distinct timescales, previously sharing one knob:
#
#   1. DEFER WINDOW — Step 4b is in flight, suppress the close-reviewer
#      nudge. Must EXCEED /code-review high's observed ~10-15 min runtime
#      plus headroom for /xp-quality-review consume + /security-review +
#      concern-triage AskUserQuestion. (Was 600s, which predated the
#      workflow-backed /code-review and expired mid-Step-4b; bumped to 1800s.)
#
#   2. ABANDONMENT TIMEOUT — the bypass-recorded "close abandoned" concern.
#      Must be SUBSTANTIALLY LONGER than the defer window so a slow but
#      legitimate close (security-review prompts, slow agent turns,
#      multi-round concern triage) doesn't trip a false-positive
#      abandonment.
#
# A single shared value forced a compromise that fails both: too long for
# defer (delays surfacing real abandonment) or too short for abandonment
# (false positives). The split keeps each knob honest to its purpose.
_CLOSE_CYCLE_DEFER_WINDOW_SEC = 1800
# The abandonment age is NOT re-declared here. It is owned by
# close_cycle_abandonment, whose recorder this module delegates the whole
# decision to — an alias would be a second name for it with nothing reading it.

_BLOCK_MESSAGE = (
    "Close cycle mid-flight. Run /security-review (Step 4) then "
    "/code-review high via the Workflow tool (Step 4b, if "
    "RUN_FULL_CODE_REVIEW=true) then invoke xp-close-reviewer (Agent tool, "
    "Step 4.5); then continue Steps 5-7."
)

# The concern this gate records is one of three that report the SAME fact, so
# its content and its budget pin live with the other two in
# close_cycle_abandonment. Only the stderr line is this detector's own: it names
# the platform flag that got here, which neither of the others can say.
_BYPASS_RECOVERY = close_cycle_abandonment.RECOVERY
_BYPASS_STDERR = (
    "close-cycle gate bypassed: stop_hook_active=True with "
    f"CLOSE_CYCLE_ACTIVE marker still set — high-severity concern recorded. "
    f"{_BYPASS_RECOVERY}\n"
)


def _marker_age_under(smm_dir: Path, threshold_sec: float) -> bool:
    """True if the CLOSE_CYCLE_ACTIVE marker is younger than ``threshold_sec``.

    Ages through `close_cycle_abandonment.marker_age_seconds` — one reader of
    the marker's mtime, shared with the recorder that applies the abandonment
    threshold to the same number. An unusable age (absent marker, or one that
    raced away) counts as NOT within the window, so the caller falls toward
    surfacing (block) rather than silently latching.
    """
    age = close_cycle_abandonment.marker_age_seconds(smm_dir)
    if age is None:
        return False
    return age < threshold_sec


# The close modes whose preload ARMS this gate — the only ones whose
# close_started can anchor its release. Every close mode emits close_started,
# story-close included, so an unfiltered scan lets the lead's own next
# story-close move the anchor past this cycle's reviewer completion: the
# release then never fires and the aged bypass records a FALSE "reviewer never
# ran" concern. Same three modes retro_metrics scopes its security rule to, for
# a related but distinct reason (that one asks which closes run a security
# review; this one asks which arm a marker), so they are not shared.
_GATE_ARMING_CLOSE_MODES = frozenset({"sprint", "plan", "free"})


def _anchors_this_gate(event: dict) -> bool:
    """Is this a close_started from a close that armed this gate?

    A mode PRESENT and outside the arming set is skipped: by construction its
    preload writes no marker, so it cannot be the cycle being gated. An
    absent/blank mode still anchors — fail closed, because skipping it moves
    the anchor BACKWARD and only makes a release likelier.
    """
    if event_schema.event_action(event) != event_schema.STATUS_ACTION_CLOSE_STARTED:
        return False
    mode = (event.get("metadata") or {}).get(event_schema.METADATA_KEY_CLOSE_MODE)
    if not isinstance(mode, str) or not mode.strip():
        return True
    return mode in _GATE_ARMING_CLOSE_MODES


def reviewer_completed_this_cycle(
    smm_dir: Path, events: list[dict] | None = None
) -> bool:
    """True when xp-close-reviewer emitted a subagent_complete event AFTER the
    latest gate-arming close_started in the log — evidence a reviewer RAN this
    cycle.

    The marker (CLOSE_CYCLE_ACTIVE) is written at close START, so its presence
    proves only that a close started, never that a reviewer ran. This reads the
    real lifecycle fact instead: subagent_stop._handle_close_reviewer_done emits
    the standard subagent_complete event when the close-reviewer stops. Ordering
    is by log/append position (mirroring retro_metrics' close-started scan) — no
    timestamp math; the anchor is the latest close_started from a mode that arms
    this gate (`_anchors_this_gate`).

    Fails CLOSED: a corrupt/failed event read (or any exception) is treated as
    'no evidence' → the caller keeps blocking. Never raises into the Stop hook.
    """
    event_action = event_schema.event_action
    subagent_complete = event_schema.STATUS_ACTION_SUBAGENT_COMPLETE
    try:
        if events is None:
            events, _ = _common.load_events_with_resolutions(smm_dir)
        last_close_started = -1
        for i, event in enumerate(events):
            if _anchors_this_gate(event):
                last_close_started = i
        if last_close_started < 0:
            return False
        for event in events[last_close_started + 1 :]:
            if event_action(event) != subagent_complete:
                continue
            agent_type = (event.get("metadata") or {}).get("agent_type", "")
            if (
                target_routing.strip_our_namespace(agent_type)
                == target_routing.CLOSE_REVIEWER_BARE
            ):
                return True
        return False
    except Exception:
        return False


def _record_bypass(smm_dir: Path, input_data: dict) -> None:
    """Record an abandonment concern and consume the marker — dead cycles only.

    A cycle whose owning session still heartbeats is legitimately in flight
    (e.g. the agent yielded during the async Step 4b `/code-review` wait, with
    `stop_hook_active` already latched session-wide by an unrelated earlier
    hook), however old its marker is. Recording a high-severity "close
    abandoned" concern there is a false positive, so the recorder does nothing:
    no stderr, no concern, no consume; the SessionStart sweep is the backstop.
    Only where the owner cannot be named or read does age decide.

    That decision, the record and the consume all belong to
    close_cycle_abandonment — all three detectors face the same live-vs-dead
    question and would drift apart deciding it separately. What stays here is
    the stderr line, and it is written only when the recorder says a concern
    LANDED: it claims one was recorded, and an operator who cannot find the
    concern it names cannot tell a dropped append from one never attempted.
    """
    if close_cycle_abandonment.record_abandonment(
        smm_dir,
        close_cycle_abandonment.DETECTOR_AGED_STOP,
        identity.resolve_agent_id(input_data),
    ):
        sys.stderr.write(_BYPASS_STDERR)


def run(input_data: dict, smm_dir: Path | None = None) -> str | None:
    """Return block message if close cycle is mid-flight, else None."""
    if _common.is_xp_agent(input_data):
        return None

    smm_dir = _common.get_validated_smm_dir(smm_dir)
    if smm_dir is None:
        return None

    if markers.marker_exists(smm_dir, markers.ASKING_USER):
        return None

    marker_active = markers.marker_exists(smm_dir, markers.CLOSE_CYCLE_ACTIVE)

    # Evidence releases a lingering marker. The block stays marker-triggered,
    # but a reviewer that already ran this cycle (subagent_complete emitted by
    # subagent_stop._handle_close_reviewer_done, after the latest close_started)
    # overrides it. Guard BEFORE the stop_hook_active bypass: Part 1 orders
    # emit-then-consume, so a crash between them can leave evidence + a lingering
    # marker; if that marker ages out and a stop_hook_active Stop fires,
    # _record_bypass would record a FALSE "reviewer never ran" concern despite
    # evidence it did.
    #
    # The consume is what closes that path — allowing the Stop alone would not.
    # The survivor outlives this session, and the SessionStart sweep asks the
    # same recorder about it with no evidence check of its own: it would file
    # the false "close abandoned" concern this branch exists to prevent, and
    # the next close's own abort count reads it. A genuine no-evidence
    # abandonment is untouched — no evidence → no release → the aged bypass and
    # the sweep both still fire. Fails closed (bad read → no evidence → keep
    # blocking).
    if marker_active and reviewer_completed_this_cycle(smm_dir):
        markers.marker_consume(smm_dir, markers.CLOSE_CYCLE_ACTIVE)
        return None

    if input_data.get("stop_hook_active"):
        if marker_active:
            _record_bypass(smm_dir, input_data)
        return None

    if marker_active:
        # Step 4b window: the close /code-review workflow is in flight
        # (review mid-cycle). Defer the close-reviewer nudge until the
        # workflow returns and /xp-quality-review consumes its findings —
        # same predicate sprint_stop_gate uses, under the same key
        # identity.review_cycle_agent_id gives every writer of the flag.
        #
        # Age-bound the defer on its own window (shorter than the abandonment
        # age): defer ONLY while the marker is young (workflow plausibly
        # still running).
        # Once it ages past the threshold the mid-cycle flag is stuck — a
        # /xp-quality-review consume that never set quality_review_done — so
        # an unbounded defer would silently abandon the close forever. Fall
        # through to the block; the next stop_hook_active bypass then consumes
        # the aged marker and records the abandonment concern.
        mid_cycle = markers.review_mid_cycle(
            smm_dir, identity.review_cycle_agent_id(input_data.get("cwd", ""))
        )
        if mid_cycle and _marker_age_under(smm_dir, _CLOSE_CYCLE_DEFER_WINDOW_SEC):
            return None
        return _BLOCK_MESSAGE
    return None


if __name__ == "__main__":
    input_data = _common.read_hook_input()
    result = run(input_data)
    if result:
        _common.block_output(result, "Close cycle gate — close-reviewer pending.")
    sys.exit(0)
