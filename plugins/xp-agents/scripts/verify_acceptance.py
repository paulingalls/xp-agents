#!/usr/bin/env python3
"""Run acceptance_execution commands — per story (--story) or sprint-wide.

Three modes:
- ``--story <id>``: run one story's acceptance_execution commands in order,
  stopping at the first non-zero exit (the /xp-accept gate).
- ``--sprint``: rerun EVERY verify-bearing item across the sprint — each
  object-shaped acceptance_criteria item carrying a command/commands verify
  block PLUS every story-level acceptance_execution. Prints a surface-grouped
  PASS/FAIL matrix and emits a deterministic ``sprint``/``action=verify``
  event carrying verify_status + the failing items. The signal is
  script-emitted (not reviewer prose) so the close gate reads it
  deterministically.
- ``--query-verify-status``: report the last sprint-verify event's status for
  the current sprint (the reader the sprint-close gate consumes). Exit 0 =
  green/none (no gate), 1 = red (gate), 2 = error.

Back-compat: a single ``command: str`` is treated as a one-element list.
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import _common
import sprint_store
from _acceptance_execution import extract_commands
from _append_impl import resolve_smm_dir
from event_schema import (
    EVENT_TYPE_SPRINT,
    SPRINT_ACTION_VERIFY,
    VERIFY_STATUS_GREEN,
    VERIFY_STATUS_NONE,
    VERIFY_STATUS_RED,
)
from sprint_store import get_story

# Exit codes for --query-verify-status, mirroring verify_paths.py: 1 is a gate
# signal (red), not an error (2).
_EXIT_OK = 0
_EXIT_RED = 1
_EXIT_ERROR = 2

# Story-level acceptance_execution carries no surface; bucket it here.
_STORY_SURFACE = "(story)"

_AGENT_ID = "verify-acceptance"

# Tail of a failing command's output carried in the event so the close gate
# can explain WHY a rerun went red without re-running it.
_OUTPUT_TAIL_CHARS = 500

# Cap the failing items stored in the event. The whole serialized event —
# metadata included — is checked against MAX_EVENT_BYTES in append_event, and
# append_safe swallows only LockTimeoutError, NOT the ValueError an oversized
# event raises. Each failing item carries a ~500-char output tail (~700 bytes
# total), so a heavily red sprint (>~140 failures) would breach the 100 KB
# budget and crash _run_sprint with an uncaught ValueError — blocking close
# instead of reporting the red. Capping the stored detail keeps the event well
# under budget. 20 is plenty to diagnose a red close — failures usually cluster
# to a few root causes. verify_status + the content's count still reflect the
# TRUE total; only the stored detail is bounded.
_MAX_FAILING_ITEMS = 20

# Per-command timeout for the unattended --sprint batch path: a hung
# acceptance test must convert to an attributable red, never block close
# forever. Generous default (won't false-fail a real suite); operators tune
# via VERIFY_CMD_TIMEOUT_S when a surface legitimately runs longer.
_DEFAULT_CMD_TIMEOUT_S = 600


def _cmd_timeout() -> int:
    """Per-command timeout in seconds; VERIFY_CMD_TIMEOUT_S overrides default."""
    raw = os.environ.get("VERIFY_CMD_TIMEOUT_S")
    if raw:
        try:
            return int(raw)
        except ValueError:
            pass
    return _DEFAULT_CMD_TIMEOUT_S


def _ac_env(smm_dir: Path) -> dict[str, str]:
    """Child env for AC subprocesses — inject SMM_DIR so $SMM_DIR-using ACs work."""
    return {**os.environ, "SMM_DIR": str(smm_dir)}


def _run_commands(commands: list[str], smm_dir: Path) -> int:
    """Run each command in order; return 0 on all-green, else first non-zero exit."""
    multi = len(commands) > 1
    env = _ac_env(smm_dir)
    for i, cmd in enumerate(commands):
        # shell=True: AC commands are shell strings (pytest, grep, bash
        # one-liners with pipes/redirects). Stories declare them; the SMM
        # is trusted local state, not external input.
        result = subprocess.run(cmd, shell=True, check=False, env=env)
        if result.returncode != 0:
            label = f"commands[{i}]" if multi else "command"
            print(
                f"verify_acceptance: {label} failed (exit {result.returncode}): {cmd}",
                file=sys.stderr,
            )
            return result.returncode
    return 0


def _gather_sprint_items(sprint: dict) -> list[tuple[str, int | None, str | None, str]]:
    """Every verify-bearing command across the sprint.

    Each tuple is (story_id, ac_idx, surface, command). Object-shaped
    acceptance_criteria items carrying a command/commands block contribute one
    tuple per command with their declared surface; the story-level
    acceptance_execution contributes with ac_idx=None and surface from the
    block (usually absent → grouped under the story bucket). String ACs and
    stories with no verify commands contribute nothing.
    """
    items: list[tuple[str, int | None, str | None, str]] = []
    for story in sprint.get("stories", []):
        sid = story.get("id", "?")
        for idx, ac in enumerate(story.get("acceptance_criteria", [])):
            if isinstance(ac, dict) and ("command" in ac or "commands" in ac):
                for cmd in extract_commands(ac):
                    items.append((sid, idx, ac.get("surface"), cmd))
        ae = story.get("acceptance_execution")
        if ae:
            for cmd in extract_commands(ae):
                items.append((sid, None, ae.get("surface"), cmd))
    return items


def _print_matrix(rows: list[dict]) -> None:
    """Print the result rows grouped by surface, one PASS/FAIL line each."""
    by_surface: dict[str, list[dict]] = {}
    for r in rows:
        by_surface.setdefault(r["surface"] or _STORY_SURFACE, []).append(r)
    for surface in sorted(by_surface):
        print(f"Surface: {surface}")
        for r in by_surface[surface]:
            rc = r["returncode"]
            mark = "PASS" if rc == 0 else "FAIL"
            ac = f"ac{r['ac_idx']}" if r["ac_idx"] is not None else "ae"
            print(f"  [{mark}] {r['story']} {ac}  {r['command']}  (exit {rc})")


def _load_sprint(smm_dir: Path) -> tuple[dict | None, int]:
    """Load the sprint; on failure print to stderr and return (None, error)."""
    try:
        return sprint_store.load_sprint_required(smm_dir), _EXIT_OK
    except (ValueError, OSError) as exc:
        print(f"verify_acceptance: {exc}", file=sys.stderr)
        return None, _EXIT_ERROR


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
    env = _ac_env(smm_dir)
    rows: list[dict] = []
    for sid, ac_idx, surface, cmd in items:
        # shell=True: AC commands are trusted shell strings declared by the
        # story (see _run_commands). capture_output keeps the matrix clean.
        try:
            proc = subprocess.run(
                cmd,
                shell=True,  # noqa: secret
                capture_output=True,
                text=True,
                timeout=timeout,
                env=env,
            )
            rc = proc.returncode
            output = proc.stderr or proc.stdout or ""
        except subprocess.TimeoutExpired:
            rc = -1
            output = f"timed out after {timeout}s"
        row: dict = {
            "story": sid,
            "ac_idx": ac_idx,
            "surface": surface,
            "command": cmd,
            "returncode": rc,
        }
        if rc != 0:
            # Carry a tail of the failure so the close gate can explain the red.
            row["output"] = output[-_OUTPUT_TAIL_CHARS:]
        rows.append(row)

    _print_matrix(rows)
    failing = [r for r in rows if r["returncode"] != 0]
    status = VERIFY_STATUS_RED if failing else VERIFY_STATUS_GREEN
    event = _common.make_event(
        EVENT_TYPE_SPRINT,
        _AGENT_ID,
        f"Sprint verify: {sprint['sprint_id']} {status} ({len(failing)} failing)",
        metadata={
            "sprint_id": sprint["sprint_id"],
            "action": SPRINT_ACTION_VERIFY,
            "verify_status": status,
            "failing": failing[:_MAX_FAILING_ITEMS],
        },
    )
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


def _last_verify(smm_dir: Path, sprint_id: str) -> tuple[str, list[dict]]:
    """Status + failing items of the last verify event for this sprint.

    Returns ("none", []) when no verify event exists for the sprint — the
    close gate treats that identically to green (nothing was gated).
    """
    events = _common.read_events_locked(smm_dir, _AGENT_ID)
    for e in reversed(events):
        meta = e.get("metadata") or {}
        if (
            e.get("type") == EVENT_TYPE_SPRINT
            and meta.get("action") == SPRINT_ACTION_VERIFY
            and meta.get("sprint_id") == sprint_id
        ):
            return meta.get("verify_status", VERIFY_STATUS_NONE), meta.get(
                "failing", []
            )
    return VERIFY_STATUS_NONE, []


def _query_verify_status(smm_dir: Path) -> int:
    """Print the current sprint's last verify status; exit red(1)/ok(0)/error(2)."""
    sprint, code = _load_sprint(smm_dir)
    if sprint is None:
        return code

    status, failing = _last_verify(smm_dir, sprint["sprint_id"])
    print(status)
    if status == VERIFY_STATUS_RED:
        for r in failing:
            rc = r.get("returncode")
            print(f"  {r.get('story', '?')} {r.get('command', '')} (exit {rc})")
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
