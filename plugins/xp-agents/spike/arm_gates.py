#!/usr/bin/env python3
"""Throwaway spike helper: arm a real gate, and PROVE it is armed.

Every negative story-004 records runs through here. A gate that is not actually
armed produces "not blocked" and "did not block" — the same strings no-go
criteria 2 and 3 produce when they genuinely fail. Since those strings are the
verdict, arming may never be *claimed*: it is asserted by running the real gate
and refusing when the gate does not bite.

The condition that makes this more than bookkeeping is cadence. Under `story`
the commit gate never blocks at all — it emits an advisory instead
(`pre_tool_bash_commit_gates.py:172-181`) — and this project's live cadence IS
`story`. A helper that trusted the "commit" default would arm nothing and hand
back a matrix reading as total bypass.

So the shape here is: set what can be set, then run the gate, and on a
non-block DIAGNOSE rather than guess. The assertion is ground truth; the
diagnosis only explains it.
"""

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import code_files
import commits
import coordination
import identity
import markers
import probe_commit_shapes as probe

_PLUGIN_ROOT = Path(__file__).resolve().parent.parent
_APPEND_SH = _PLUGIN_ROOT / "smm" / "append.sh"
_TDD_STOP_GATE = _PLUGIN_ROOT / "scripts" / "tdd_stop_gate.py"

_TIMEOUT_SECONDS = 60

# Matches tdd_check.TEST_CONCERN_RE ("Test failures? detected|run failed|command
# failed"). Spelled out rather than imported so the arming text stays readable
# in the scratch log a later reader inspects.
_FAIL_CONCERN = "Test failures detected: armed by spike/arm_gates.py"

# Same condition, same meaning — a rig whose gate does not bite. Reused rather
# than re-declared so a caller cannot catch one and miss the other.
NotArmedError = probe.RigNotArmedError


def agent_id_for(repo: Path) -> str:
    """The agent id the gate itself will resolve for this cwd.

    Read through `identity.resolve_agent_id` rather than assumed: the
    review-cycle marker is per-agent, so writing one under a different id than
    the gate reads would leave the gate armed while the report says otherwise.
    """
    return identity.resolve_agent_id({"cwd": str(repo)})


def read_cadence(smm_dir: Path) -> str:
    return markers.read_review_cadence(smm_dir)


def write_cadence(smm_dir: Path, cadence: str) -> None:
    markers.write_review_cadence(smm_dir, cadence)


def record_review_done(smm_dir: Path, repo: Path) -> None:
    """Used by the checks to prove arming REFUSES on a released gate."""
    markers.write_review_cycle(
        smm_dir, agent_id_for(repo), {"quality_review_done": True}
    )


def register_other_agent(smm_dir: Path, other_agent_id: str) -> None:
    """Used by the checks: a live sibling releases the TDD Stop gate."""
    coordination.update_coordination(smm_dir, other_agent_id, ["something.py"])


def staged_code_files(repo: Path) -> list[str]:
    staged = commits.get_staged_files(str(repo)) or []
    return [f for f in staged if code_files.is_code_file(f)]


def _diagnose_commit_gate(repo: Path, smm_dir: Path) -> str:
    """Why did the gate not bite? Every known release path, named."""
    agent_id = agent_id_for(repo)
    cycle = markers.read_review_cycle(smm_dir, agent_id)
    code = staged_code_files(repo)
    return (
        f"cadence={read_cadence(smm_dir)!r} "
        f"(story never blocks, it advises); "
        f"staged code files={len(code)} "
        f"(need >= {commits.REVIEW_CYCLE_THRESHOLD}): {code}; "
        f"quality_review_done={cycle.get('quality_review_done')!r} "
        f"for agent_id={agent_id!r}; smm_dir={smm_dir}"
    )


def arm_commit_gate(*, repo: Path, smm_dir: Path) -> dict:
    """Arm the review-cycle commit gate and assert it bites.

    The cadence write is PERSISTENT and is not restored — it must survive into
    the separate process the measured run happens in, so there is no paired
    exit here. Pointed at a real project SMM (`--repo`/`--smm-dir`) it therefore
    changes that project's live cadence for everyone afterwards, which is why
    the previous value is carried into the report and printed.
    """
    previous_cadence = read_cadence(smm_dir)
    write_cadence(smm_dir, "commit")
    try:
        control = probe.assert_armed(repo=repo, smm_dir=smm_dir)
    except NotArmedError as exc:
        raise NotArmedError(
            f"commit gate did not bite after arming.\n{exc}\n"
            f"  diagnosis: {_diagnose_commit_gate(repo, smm_dir)}"
        ) from exc
    return {
        "armed": True,
        "gate": "commit",
        "cadence": read_cadence(smm_dir),
        "previous_cadence": previous_cadence,
        "staged_code_files": staged_code_files(repo),
        "threshold": commits.REVIEW_CYCLE_THRESHOLD,
        "agent_id": agent_id_for(repo),
        "review_recorded": bool(
            markers.read_review_cycle(smm_dir, agent_id_for(repo)).get(
                "quality_review_done"
            )
        ),
        "control_command": probe.CONTROL_COMMAND,
        "control_reason": control["stderr"].strip(),
        "smm_dir": str(smm_dir),
    }


def run_stop_gate(*, repo: Path, smm_dir: Path, stop_hook_active: bool = False) -> dict:
    """Run the real TDD Stop gate once and hand back exactly what it emitted.

    The four releasing Stop gates block with `{"decision": "block"}` on stdout
    and exit 0 — NOT stderr plus exit 2, which is the PreToolUse contract. Both
    are returned unreduced because story-004 has to report which mechanism the
    second harness honours, and collapsing them here would erase the
    distinction being measured.
    """
    payload = {
        "hook_event_name": "Stop",
        "session_id": "spike-arm-gates",
        "cwd": str(repo),
        "stop_hook_active": stop_hook_active,
    }
    result = subprocess.run(
        [sys.executable, str(_TDD_STOP_GATE)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=_TIMEOUT_SECONDS,
        env=probe.hook_env(smm_dir),
        cwd=str(repo),
    )
    return {
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


def append_fail_signal(smm_dir: Path, repo: Path) -> None:
    """Record the test-failure concern the TDD gate scans for.

    Written through `append.sh` rather than by touching `events.jsonl`: it is
    the only sanctioned writer, it validates at write time, and a hand-written
    line that fails validation would leave the gate unarmed for a reason no
    diagnosis here would name.

    **Attributed to the agent the READER will scope to**, not to this helper. A
    worktree teammate shares the event log with its lead and siblings, so
    `tdd_check._reader_scope` counts only signals carrying that teammate's own
    agent id; a concern filed under any other name is silently skipped and the
    gate never blocks. `--agent` becomes the event's `agent_id`, so it must be
    the same value `identity.resolve_agent_id` returns for this cwd.
    """
    subprocess.run(
        [
            str(_APPEND_SH),
            "--smm-dir",
            str(smm_dir),
            "--type",
            "concern",
            "--agent",
            agent_id_for(repo),
            "--severity",
            "medium",
            "--content",
            _FAIL_CONCERN,
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=_TIMEOUT_SECONDS,
        cwd=str(repo),
    )


def arm_tdd_stop_gate(*, repo: Path, smm_dir: Path) -> dict:
    """Arm the TDD Stop gate and assert it actually blocks."""
    append_fail_signal(smm_dir, repo)
    result = run_stop_gate(repo=repo, smm_dir=smm_dir)
    decision = None
    if result["stdout"].strip():
        try:
            decision = json.loads(result["stdout"])
        except json.JSONDecodeError:
            decision = None
    if not (decision and decision.get("decision") == "block"):
        # The gate reads `agent_id` off the STOP PAYLOAD, which carries none on
        # either harness — so its self-exclusion never applies and even this
        # rig's OWN coordination entry counts as "another agent". Diagnosing
        # with `agent_id_for(repo)` instead would exclude that entry and report
        # "no other agents" for the release it actually caused.
        payload_agent_id = ""
        raise NotArmedError(
            "TDD Stop gate did not block after arming, so any 'did not block' "
            "observation from Run L would be meaningless.\n"
            f"  exit: {result['returncode']}\n"
            f"  stdout: {result['stdout']!r}\n"
            f"  stderr: {result['stderr']!r}\n"
            f"  diagnosis: other active agents="
            f"{coordination.has_active_teammates(smm_dir, payload_agent_id)} "
            f"(a live sibling releases this gate, since it may own the failing "
            f"tests; Stop carries no agent_id, so ANY coordination entry counts "
            f"— including this rig's own); signal author="
            f"{agent_id_for(repo)!r}; smm_dir={smm_dir}"
        )
    return {
        "armed": True,
        "gate": "tdd-stop",
        "mechanism": "decision-json",
        "returncode": result["returncode"],
        "block_reason": decision.get("reason", ""),
        "agent_id": agent_id_for(repo),
        "fail_signal": _FAIL_CONCERN,
        "smm_dir": str(smm_dir),
    }


def describe(report: dict) -> str:
    """What was ASSERTED, spelled out.

    Refuses an unarmed report: printing a summary for a gate that never bit
    would put the exact reassurance in the log that this module exists to make
    impossible.
    """
    if not report.get("armed"):
        raise ValueError(
            "refusing to describe an unarmed report — arming must raise, not "
            f"be narrated: {report!r}"
        )
    if report["gate"] == "commit":
        code = report["staged_code_files"]
        previous = report.get("previous_cadence")
        restore = (
            ""
            if previous == report["cadence"]
            else f" — OVERWROTE {previous!r}, persistent, restore it afterwards"
        )
        return (
            f"commit gate ARMED in {report['smm_dir']}\n"
            f"  - cadence: {report['cadence']}{restore} "
            f"(story would only advise, never block)\n"
            f"  - staged code files: {len(code)} >= "
            f"{report['threshold']} — {code}\n"
            f"  - review recorded for {report['agent_id']}: "
            f"{report['review_recorded']} (True would release the gate)\n"
            f"  - control `{report['control_command']}` blocked with: "
            f"{report['control_reason']!r}"
        )
    return (
        f"TDD Stop gate ARMED in {report['smm_dir']}\n"
        f"  - mechanism: {report['mechanism']} (exit {report['returncode']}, "
        f"not stderr+exit 2)\n"
        f"  - agent id: {report['agent_id']}\n"
        f"  - blocked with: {report['block_reason']!r}\n"
        f"  - armed by an appended concern: {report['fail_signal']!r}. The log "
        f"is append-only, so nothing here disarms it — resolve that concern, or "
        f"this SMM keeps blocking Stop for every agent scoped to it."
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gate", choices=("commit", "tdd-stop"), default="commit")
    parser.add_argument(
        "--repo", type=Path, help="existing repo to arm; a scratch rig if omitted"
    )
    parser.add_argument("--smm-dir", type=Path, help="SMM dir; scratch if omitted")
    args = parser.parse_args()

    if args.repo and args.smm_dir:
        repo, smm_dir = args.repo, args.smm_dir
        scratch = None
    else:
        scratch = tempfile.mkdtemp(prefix="xp-spike-arm-")
        repo, smm_dir = probe.build_rig(Path(scratch))
        print(f"scratch rig: {scratch}", file=sys.stderr)

    if args.gate == "commit":
        report = arm_commit_gate(repo=repo, smm_dir=smm_dir)
    else:
        report = arm_tdd_stop_gate(repo=repo, smm_dir=smm_dir)
    print(describe(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
