#!/usr/bin/env python3
"""Run acceptance_execution commands — per story (--story) or sprint-wide.

Three modes:
- ``--story <id>``: run one story's acceptance_execution commands in order,
  stopping at the first non-zero exit (the /xp-accept gate).
- ``--sprint``: rerun EVERY verify-bearing item across the sprint — each
  object-shaped acceptance_criteria item carrying a command/commands verify
  block PLUS every story-level acceptance_execution. Prints a surface-grouped
  PASS/FAIL matrix and emits a deterministic ``sprint``/``action=verify``
  event carrying verify_status + the failing items (plus the items a blown
  batch budget never started — see ``_DEFAULT_BATCH_TIMEOUT_S``). The signal
  is script-emitted (not reviewer prose) so the close gate reads it
  deterministically.
- ``--query-verify-status``: report the last sprint-verify event's status for
  the current sprint (the reader the sprint-close gate consumes). Exit 0 =
  green/none (no gate), 1 = gated, 2 = error. Gated covers ``red`` (a run
  reported failures or skipped items) AND ``unverified`` (the sprint HAS
  runnable acceptance but no run ever recorded a result — silence is not
  green). ``unverified`` is a reader-side verdict, not a recorded status: the
  event schema accepts only red/green/none, so it is derived here rather than
  written.

Back-compat: a single ``command: str`` is treated as a one-element list.
"""

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import _common
import _subprocess_env
import branch_lifecycle
import sprint_store
from _acceptance_execution import extract_commands
from _append_impl import resolve_smm_dir
from event_schema import (
    EVENT_TYPE_SPRINT,
    SPRINT_ACTION_VERIFY,
    VERIFY_STATUS_GREEN,
    VERIFY_STATUS_RED,
)
from sprint_store import get_story
from verify_acceptance_record import (
    _AGENT_ID,
    VERIFY_REPORT_UNVERIFIED,
    _gather_sprint_items,
    _print_matrix,
    distinct_commands,
    rows_from_results,
    unverified_items,
    verify_report,
)

# Exit codes for --query-verify-status, mirroring verify_paths.py: 1 is a gate
# signal (red), not an error (2).
_EXIT_OK = 0
_EXIT_RED = 1
_EXIT_ERROR = 2

# --story exit for a command that blew its time bound. POSITIVE on purpose:
# _run_commands' return flows through main() into sys.exit(), where the batch
# path's in-process -1 sentinel would surface to the shell as 255. The
# /xp-accept gate compares only against 0, so it would still hold — which is
# precisely why nothing would have caught the nonsense code the operator reads.
_EXIT_TIMEOUT = 3


# Tail of a failing command's output carried in the event so the close gate
# can explain WHY a rerun went red without re-running it.
_OUTPUT_TAIL_CHARS = 500


def _tail_streams(stderr: str, stdout: str) -> str:
    """Each stream tailed independently before the stderr-first join — else a
    chatty stdout evicts the stderr diagnosis out of the kept slice."""
    return branch_lifecycle.combine_streams(
        stderr[-_OUTPUT_TAIL_CHARS:], stdout[-_OUTPUT_TAIL_CHARS:]
    )


# Cap the failing items stored in the event. The whole serialized event —
# metadata included — is checked against MAX_EVENT_BYTES in append_event, and
# append_safe swallows only LockTimeoutError, NOT the ValueError an oversized
# event raises. Each failing item carries a tail of BOTH streams, so up to
# ~1000 chars (~1200 bytes), and a heavily red sprint (>~80 failures) would
# breach the 100 KB budget and crash _run_sprint with an uncaught ValueError —
# blocking close instead of reporting the red. Capping the detail stored keeps
# the event well under budget. 20 is plenty for a red close — failures cluster
# to a few root causes. verify_status + the content's count still reflect the
# TRUE total; only the stored detail is bounded.
_MAX_FAILING_ITEMS = 20

# Per-command timeout shared by BOTH run paths — the attended --story gate and
# the unattended --sprint batch. Its purpose is "never hang forever", not "fail
# fast": a hung acceptance command must convert to an attributable failure
# instead of blocking accept or close indefinitely. Two hours because an
# acceptance suite legitimately runs long — an hour-long one must pass
# comfortably, and a tight bound would turn slow-but-green into red. Operators
# tune per project via VERIFY_CMD_TIMEOUT_S. The bound is PER COMMAND, so a
# story declaring three commands can take 3x it end to end.
_DEFAULT_CMD_TIMEOUT_S = 7200


# Batch total for the UNATTENDED --sprint run. The bound above is PER COMMAND,
# so N verify-bearing items can legitimately run N x 7200s — ~16h for eight,
# inside sprint close, which the pre-sprint-128 600s cap prevented only by
# accident. Tightening the per-command bound back would false-red any suite over
# ten minutes, so bound the BATCH instead: a slow suite keeps its two hours and
# the run still cannot go overnight. 4h = 2x the per-command bound, so no single
# pathological item can exhaust it alone.
#
# TWO PROPERTIES A READER WILL OTHERWISE ASSUME WRONG. It is not a hard ceiling
# — see the placement comment in _run_sprint. And there is no resume: skipping
# is deterministic in sprint order, so an over-budget batch always skips the
# SAME tail (the newest, least-verified stories) and raising the lever re-pays
# every already-green item. Nothing accumulates across runs. Skipped items gate
# the close as red, so this is a cost, never a false green.
_DEFAULT_BATCH_TIMEOUT_S = 14400

# The batch clock, rebindable so tests can script it. MONOTONIC: a deadline
# built on time.time() moves under an NTP step or a DST change, stopping an
# unattended batch for a reason unrelated to how long it had been running.
_now = time.monotonic


def _batch_budget() -> int | None:
    """Batch-total seconds for --sprint, or None when the budget is off.

    Diverges from `_cmd_timeout`/`_subprocess_env._env_int` on purpose, and the
    divergence IS the opt-out. For a per-command timeout a non-positive value
    is nonsense — `timeout=0` makes the runner raise before the command has run
    at all — so `_env_int` correctly folds zero and negatives into the default.
    For a batch TOTAL, non-positive is the only way to say "do not bound my
    batch": a project whose honest sprint verify runs eight hours needs that
    door, and without it the only escape from a false stop is `--force-close`,
    which bypasses the ENTIRE acceptance gate rather than this one bound.

    Unset is NOT that door — it takes the default. An opt-in budget would leave
    the unbounded batch in place for every project that never set the variable,
    which is every project on upgrade: shipped and inert. Unparseable text is a
    typo, not consent to run unbounded, so it takes the default too.
    """
    raw = os.environ.get("VERIFY_BATCH_TIMEOUT_S")
    if not raw:
        return _DEFAULT_BATCH_TIMEOUT_S
    try:
        seconds = int(raw)
    except ValueError:
        return _DEFAULT_BATCH_TIMEOUT_S
    return seconds if seconds > 0 else None


def _cmd_timeout() -> int:
    """Per-command timeout in seconds; a POSITIVE VERIFY_CMD_TIMEOUT_S overrides.

    Only positive, and that is not input-hygiene fussiness: `timeout=0` makes
    the runner raise TimeoutExpired before the command has run at all, so
    every acceptance command would die "timed out after 0s" having never
    executed. Zero and negatives express no runnable budget, so they are not
    an override; they fall back to the default, exactly as unparseable text
    does.

    Delegates to _subprocess_env._env_int, shared with
    worktree_bootstrap._bootstrap_timeout — kept as a named wrapper (not
    inlined at the call sites) because tests patch/call this name directly.
    """
    return _subprocess_env._env_int("VERIFY_CMD_TIMEOUT_S", _DEFAULT_CMD_TIMEOUT_S)


def _run_commands(commands: list[str], smm_dir: Path) -> int:
    """Run each command in order; return 0 on all-green, else the first failure.

    The failure is the command's own non-zero exit, or _EXIT_TIMEOUT if it
    blew the bound. Output is NOT captured: an operator watches this path
    scroll by during /xp-accept, so the commands stream straight to the
    terminal — the reason the shared runner takes a capture opt-out at all.
    """
    multi = len(commands) > 1
    env = _subprocess_env.smm_child_env(smm_dir)
    timeout = _cmd_timeout()
    # See _run_sprint: the process cwd, explicitly, NOT smm_dir.
    cwd = os.getcwd()
    for i, cmd in enumerate(commands):
        label = f"commands[{i}]" if multi else "command"
        # AC commands are shell strings (test runners, greps, one-liners with
        # pipes/redirects). Stories declare them; the SMM is trusted local
        # state, not external input. Run in a new session so a hung one loses
        # its whole process group rather than orphaning what it backgrounded.
        try:
            result = _subprocess_env.run_in_new_process_group(
                cmd, cwd=cwd, timeout=timeout, env=env, capture=False
            )
        except subprocess.TimeoutExpired:
            print(
                f"verify_acceptance: {label} timed out after {timeout}s: {cmd}",
                file=sys.stderr,
            )
            return _EXIT_TIMEOUT
        if result.returncode != 0:
            print(
                f"verify_acceptance: {label} failed (exit {result.returncode}): {cmd}",
                file=sys.stderr,
            )
            return result.returncode
    return 0


def _load_sprint(smm_dir: Path) -> tuple[dict | None, int]:
    """Load the sprint; on failure print to stderr and return (None, error)."""
    try:
        return sprint_store.load_sprint_required(smm_dir), _EXIT_OK
    except (ValueError, OSError) as exc:
        print(f"verify_acceptance: {exc}", file=sys.stderr)
        return None, _EXIT_ERROR


def _run_one(cmd: str, cwd: str, timeout: int, env: dict) -> dict:
    """Shell one command and report `{returncode, output?}`.

    Run in its own session so the timeout kills the whole process GROUP: a
    plain shell timeout reaps only the shell, leaving alive whatever the
    command backgrounded (a dev server, a stack) to outlive the close it was
    started for. Captured, because the matrix and failure tails read the output.

    The timeout marker is kept OUT of the truncated tail, which keeps the LAST
    `_OUTPUT_TAIL_CHARS`: a hung command that talked a lot before it was killed
    would otherwise evict its own marker, and the row would read as an ordinary
    non-zero exit.
    """
    marker = ""
    try:
        proc = _subprocess_env.run_in_new_process_group(
            cmd, cwd=cwd, timeout=timeout, env=env
        )
        rc = proc.returncode
        err_text, out_text = proc.stderr or "", proc.stdout or ""
    except subprocess.TimeoutExpired as exc:
        rc = -1
        marker = f"timed out after {timeout}s"
        # Whatever the command managed to say before it was killed is usually
        # the only clue to WHY it hung; a bare "timed out after Ns" sends the
        # operator off to reproduce it by hand.
        err_text = getattr(exc, "text_stderr", "").strip()
        out_text = getattr(exc, "text_stdout", "").strip()
    if rc == 0:
        return {"returncode": rc}
    # Carry a tail of the failure so the close gate can explain the red.
    output = ": ".join(p for p in (marker, _tail_streams(err_text, out_text)) if p)
    return {"returncode": rc, "output": output}


def _run_sprint(smm_dir: Path) -> int:
    """Rerun every verify-bearing item, print the matrix, emit the verify event."""
    sprint, code = _load_sprint(smm_dir)
    if sprint is None:
        return code

    items = _gather_sprint_items(sprint)
    if not items:
        print("verify_acceptance: no verify-bearing acceptance to rerun")
        return _EXIT_OK

    timeout = _cmd_timeout()
    env = _subprocess_env.smm_child_env(smm_dir)
    # The process cwd, explicitly — the runner is invoked bare from the main
    # checkout and a declared command's relative paths resolve against it.
    # NOT smm_dir, the nearest Path in scope: that would relocate every
    # declared command and break every relative path it uses.
    cwd = os.getcwd()
    # The batch total, frozen once. None means the project disabled it.
    budget = _batch_budget()
    deadline = None if budget is None else _now() + budget
    # One run per DISTINCT command. Stories share commands — nearly every one
    # declares the whole-suite E2E check — and an unchanging tree cannot answer
    # the same command differently per story, so re-running it only spends the
    # budget that skips later items.
    #
    # PLACEMENT IS THE DESIGN. The batch bound decides which commands START:
    # before the run, since checking after would let one begin on an already
    # exhausted budget. Nothing here kills a RUNNING command — that would blame
    # the batch's exhaustion on whichever was in flight, the misattribution two
    # separate bounds exist to avoid, and it leaves the worst case at budget
    # plus one per-command timeout. `break` is safe only because
    # `rows_from_results` reports every item a result is missing for as
    # skipped; the matrix names what went unrun rather than silently shortening.
    results: dict[str, dict] = {}
    for cmd in distinct_commands(items):
        if deadline is not None and _now() >= deadline:
            break
        results[cmd] = _run_one(cmd, cwd, timeout, env)

    rows = rows_from_results(items, results)
    skipped = [r for r in rows if r.get("skipped")]

    _print_matrix(rows)
    # Skipped rows carry no returncode, so they must drop out BEFORE the
    # comparison — and they are not failures anyway: an item that never ran did
    # not lose.
    failing = [
        r
        for r in rows
        if not r.get("na") and not r.get("skipped") and r["returncode"] != 0
    ]
    # Skipped gates exactly as red does — some items green and the rest unknown
    # is not a verified sprint — and red is the ONLY encoding available: the
    # status set is enforced at append time, so an "incomplete" would be
    # rejected on write and an unknowing reader would pass the close gate.
    status = VERIFY_STATUS_RED if (failing or skipped) else VERIFY_STATUS_GREEN
    summary = f"Sprint verify: {sprint['sprint_id']} {status} ({len(failing)} failing"
    summary += f", {len(skipped)} skipped)" if skipped else ")"
    metadata: dict = {
        "sprint_id": sprint["sprint_id"],
        "action": SPRINT_ACTION_VERIFY,
        "verify_status": status,
        "failing": failing[:_MAX_FAILING_ITEMS],
    }
    if skipped:
        # Added only when it happened, so a batch nowhere near the budget emits
        # exactly the event it always did. Capped for the same reason `failing`
        # is (see that constant); the count stays TRUE, only detail is bounded.
        metadata["skipped"] = skipped[:_MAX_FAILING_ITEMS]
        metadata["skipped_count"] = len(skipped)
        ran = len(rows) - len(skipped) - sum(1 for r in rows if r.get("na"))
        print(
            f"verify_acceptance: batch budget of {budget}s exhausted after "
            f"{ran} item(s); {len(skipped)} not run. Re-running stops at the "
            "same place — raise VERIFY_BATCH_TIMEOUT_S, or set it to 0 to "
            "disable the batch budget.",
            file=sys.stderr,
        )
    event = _common.make_event(EVENT_TYPE_SPRINT, _AGENT_ID, summary, metadata=metadata)
    _common.append_safe(smm_dir, event)
    # append_safe swallows validation errors and lock timeouts; a dropped
    # verify event reads as "none" (green) at the close gate. Confirm the
    # signal landed by reading it back, and fail loud rather than let a red
    # sprint pass undetected.
    landed = _common.read_events_locked(smm_dir, _AGENT_ID)
    if not any(e.get("id") == event["id"] for e in landed):
        print("verify_acceptance: failed to emit sprint-verify event", file=sys.stderr)
        return _EXIT_ERROR
    return _EXIT_OK


def _query_verify_status(smm_dir: Path) -> int:
    """Print the current sprint's verify status; exit gate(1)/ok(0)/error(2).

    `unverified` gates exactly as red does — see `verify_report`. Reported under
    its own name rather than folded into red because the two need different
    actions from the operator: red says fix the failures, unverified says the
    rerun never recorded anything, so run it.
    """
    sprint, code = _load_sprint(smm_dir)
    if sprint is None:
        return code

    status, failing, skipped = verify_report(smm_dir, sprint)
    print(status)
    if status == VERIFY_REPORT_UNVERIFIED:
        return _EXIT_RED
    if status == VERIFY_STATUS_RED:
        for line in unverified_items(failing, skipped):
            print(f"  {line}")
        return _EXIT_RED
    return _EXIT_OK


def _run_story(smm_dir: Path, story_id: str) -> int:
    try:
        story = get_story(smm_dir, story_id)
    except (ValueError, OSError) as exc:
        print(f"verify_acceptance: {exc}", file=sys.stderr)
        return 1

    ae = story.get("acceptance_execution")
    if not ae:
        print(
            f"verify_acceptance: story {story_id!r} has no acceptance_execution block",
            file=sys.stderr,
        )
        return 1

    if "command" not in ae and "commands" not in ae:
        # A command-less (manual) block — human/agent steps only, nothing to run.
        print(f"verify_acceptance: story {story_id!r} is N/A (manual, no command)")
        return _EXIT_OK

    return _run_commands(extract_commands(ae), smm_dir)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run acceptance commands per story, sprint-wide, or query status.",
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--story", help="Run one story's acceptance_execution")
    mode.add_argument(
        "--sprint",
        action="store_true",
        help="Rerun every verify-bearing item across the sprint",
    )
    mode.add_argument(
        "--query-verify-status",
        action="store_true",
        help="Report the last sprint-verify status (red=1, green/none=0)",
    )
    parser.add_argument(
        "--smm-dir",
        type=Path,
        default=None,
        help="SMM directory (defaults to $SMM_DIR / init.sh resolution)",
    )
    args = parser.parse_args()

    smm_dir = args.smm_dir or resolve_smm_dir()
    if smm_dir is None:
        print("verify_acceptance: could not resolve SMM directory", file=sys.stderr)
        return _EXIT_ERROR

    if args.sprint:
        return _run_sprint(smm_dir)
    if args.query_verify_status:
        return _query_verify_status(smm_dir)
    return _run_story(smm_dir, args.story)


if __name__ == "__main__":
    sys.exit(main())
