#!/usr/bin/env python3
"""SMM Materializer: events.jsonl → SHARED_MENTAL_MODEL.md

Parses the append-only event log, builds indices, detects structural
conflicts, and renders a human-readable markdown view. Atomic write
via tempfile + os.rename.
"""

import argparse
import contextlib
import fcntl
import hashlib
import json
import os
import signal
import subprocess
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

STALE_THRESHOLD = 50
PRIORITY_RED = "\U0001f534"
_MAX_EVENTS_FILE_SIZE = 10_485_760  # 10 MB


def _validate_smm_dir(smm_dir: Path) -> None:
    """Validate SMM directory exists, is owned by us, not world-writable."""
    if not smm_dir.exists():
        raise ValueError(f"SMM directory does not exist: {smm_dir}")
    st = smm_dir.stat()
    if st.st_uid != os.getuid():
        raise ValueError(f"SMM directory not owned by current user: {smm_dir}")
    if st.st_mode & 0o002:
        raise ValueError(f"SMM directory is world-writable: {smm_dir}")


VALID_TYPES = frozenset(
    {
        "customer_input",
        "status",
        "decision",
        "convention",
        "concern",
        "discovery",
        "question",
        "answer",
        "assumption",
        "pair_guidance",
        "session_end",
        "retrospective",
    }
)


# ---------------------------------------------------------------------------
# SMM path resolution (duplicated for self-containment)
# ---------------------------------------------------------------------------


def resolve_smm_dir() -> Path:
    """Derive the SMM directory from git-common-dir."""
    try:
        git_common = subprocess.check_output(
            ["git", "rev-parse", "--git-common-dir"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("Error: Not in a git repository", file=sys.stderr)
        sys.exit(1)

    git_common_path = Path(git_common)
    if not git_common_path.is_absolute():
        git_common_path = git_common_path.resolve()

    project_id = hashlib.sha256(str(git_common_path).encode()).hexdigest()[:12]
    return Path.home() / ".claude" / "xp-agents" / project_id / "smm"


# ---------------------------------------------------------------------------
# Locking helpers (duplicated from _append_impl.py per design decision)
# ---------------------------------------------------------------------------


class LockTimeoutError(Exception):
    """Raised when flock cannot be acquired within the timeout."""

    pass


def _on_alarm(signum: int, frame: object) -> None:
    raise LockTimeoutError("Could not acquire lock within 2 seconds")


def _read_with_lock(path: Path) -> str:
    """Read file contents under shared flock with 2-second timeout.

    Raises LockTimeoutError if the lock cannot be acquired.
    Raises OSError if the lock file is a symlink.
    """
    lock_path = path.parent / "events.lock"
    lock_fd = None
    raw_fd = None

    try:
        raw_fd = os.open(
            str(lock_path),
            os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW,
            0o600,
        )
        try:
            lock_fd = os.fdopen(raw_fd, "a")
        except Exception:
            os.close(raw_fd)
            raise
        raw_fd = None

        old_handler = signal.signal(signal.SIGALRM, _on_alarm)
        try:
            signal.alarm(2)
            fcntl.flock(lock_fd, fcntl.LOCK_SH)
            signal.alarm(0)
        finally:
            signal.signal(signal.SIGALRM, old_handler)

        try:
            if path.stat().st_size > _MAX_EVENTS_FILE_SIZE:
                return ""
            return path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return ""

    finally:
        if lock_fd is not None:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            lock_fd.close()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def short_id(event_id: str) -> str:
    """First 8 chars of UUID for readability."""
    return event_id[:8]


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def parse_events(smm_dir: Path) -> tuple[list[dict], int]:
    """Read events.jsonl under shared flock, skip malformed lines."""
    raw = _read_with_lock(smm_dir / "events.jsonl")
    if not raw.strip():
        return [], 0

    events: list[dict] = []
    skipped = 0

    for line_num, line in enumerate(raw.splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
            if not isinstance(event, dict):
                print(
                    f"Warning: Line {line_num} is not a JSON object, skipping",
                    file=sys.stderr,
                )
                skipped += 1
                continue
            if "id" not in event or "type" not in event:
                print(
                    f"Warning: Line {line_num} missing id or type, skipping",
                    file=sys.stderr,
                )
                skipped += 1
                continue
            events.append(event)
        except json.JSONDecodeError:
            print(
                f"Warning: Line {line_num} is malformed JSON, skipping",
                file=sys.stderr,
            )
            skipped += 1

    return events, skipped


# ---------------------------------------------------------------------------
# Index building
# ---------------------------------------------------------------------------


def build_indices(events: list[dict]) -> dict:
    """Single-pass grouping of events into lookup structures."""
    indices: dict = {
        "by_type": defaultdict(list),
        "by_id": {},
        "event_positions": {},
        "latest_status": {},
        "question_answers": {},
        "question_assumptions": {},
        "decisions_by_topic": defaultdict(list),
        "conventions_by_topic": defaultdict(list),
        "assumption_contradictions": {},
        "concern_resolutions": {},
        "agent_ids": set(),
    }

    for i, event in enumerate(events):
        event_type = event.get("type", "")
        event_id = event.get("id", "")

        indices["by_type"][event_type].append(event)
        agent_id = event.get("agent_id", "")
        if agent_id:
            indices["agent_ids"].add(agent_id)
        if event_id:
            indices["by_id"][event_id] = event
            indices["event_positions"][event_id] = i

        match event_type:
            case "status":
                indices["latest_status"][event.get("agent_id", "")] = event

            case "decision":
                topic = event.get("topic", "")
                if topic:
                    indices["decisions_by_topic"][topic].append(event)

            case "convention":
                topic = event.get("topic", "")
                if topic:
                    indices["conventions_by_topic"][topic].append(event)

            case "answer":
                for ref_id in event.get("references", []):
                    ref_event = indices["by_id"].get(ref_id)
                    if ref_event and ref_event.get("type") == "question":
                        indices["question_answers"][ref_id] = event

            case "assumption":
                for ref_id in event.get("references", []):
                    ref_event = indices["by_id"].get(ref_id)
                    if ref_event and ref_event.get("type") == "question":
                        indices["question_assumptions"][ref_id] = event

            case "discovery":
                for ref_id in event.get("references", []):
                    ref_event = indices["by_id"].get(ref_id)
                    if ref_event and ref_event.get("type") == "assumption":
                        indices["assumption_contradictions"][ref_id] = event

        # Any event referencing a concern resolves it
        if event_type != "concern":
            for ref_id in event.get("references", []):
                ref_event = indices["by_id"].get(ref_id)
                if ref_event and ref_event.get("type") == "concern":
                    indices["concern_resolutions"][ref_id] = event

    return indices


# ---------------------------------------------------------------------------
# Conflict detection
# ---------------------------------------------------------------------------


def detect_conflicts(events: list[dict], indices: dict) -> list[str]:
    """Detect 5 structural conflict patterns."""
    conflicts: list[str] = []
    positions = indices["event_positions"]

    # 1. Overlapping working_on
    latest = indices["latest_status"]
    agents = sorted(latest.keys())
    for i, agent_a in enumerate(agents):
        files_a = set(latest[agent_a].get("working_on", []))
        if not files_a:
            continue
        for agent_b in agents[i + 1 :]:
            files_b = set(latest[agent_b].get("working_on", []))
            for f in sorted(files_a & files_b):
                conflicts.append(
                    f"⚠️ working_on overlap: {agent_a} and {agent_b} both claim {f}"
                )

    # 2. Assumption contradicted by discovery
    for assumption_id in sorted(indices["assumption_contradictions"]):
        discovery = indices["assumption_contradictions"][assumption_id]
        conflicts.append(
            f"⚠️ assumption contradicted: {short_id(assumption_id)} "
            f"contradicted by {short_id(discovery['id'])}"
        )

    # 3. Convention violation — decision shares topic but doesn't reference it
    for topic in sorted(indices["decisions_by_topic"]):
        conventions = indices["conventions_by_topic"].get(topic, [])
        if not conventions:
            continue
        convention_ids = {c["id"] for c in conventions}
        for decision in indices["decisions_by_topic"][topic]:
            decision_refs = set(decision.get("references", []))
            if not (decision_refs & convention_ids):
                conv_id = conventions[-1]["id"]
                conflicts.append(
                    f"⚠️ convention violation: decision {short_id(decision['id'])} "
                    f"diverges from convention {short_id(conv_id)}"
                )

    # 4. Stale question — 🔴 with no answer after STALE_THRESHOLD events
    for q in indices["by_type"].get("question", []):
        if q.get("priority") != PRIORITY_RED:
            continue
        q_id = q["id"]
        if q_id in indices["question_answers"]:
            continue
        q_pos = positions.get(q_id, -1)
        if q_pos >= 0:
            events_since = len(events) - q_pos - 1
            if events_since >= STALE_THRESHOLD:
                conflicts.append(
                    f"⚠️ stale question: {short_id(q_id)} has had no answer "
                    f"for {events_since} events"
                )

    # 5. Superseded decision — same topic, no concern referencing either between
    for topic in sorted(indices["decisions_by_topic"]):
        decisions = indices["decisions_by_topic"][topic]
        if len(decisions) < 2:
            continue
        for j in range(len(decisions) - 1):
            d1 = decisions[j]
            d2 = decisions[j + 1]
            d1_id, d2_id = d1["id"], d2["id"]
            d1_pos = positions.get(d1_id, -1)
            d2_pos = positions.get(d2_id, -1)
            if d1_pos < 0 or d2_pos < 0:
                continue
            has_concern_between = False
            for k in range(d1_pos + 1, d2_pos):
                e = events[k]
                if e.get("type") == "concern":
                    refs = set(e.get("references", []))
                    if d1_id in refs or d2_id in refs:
                        has_concern_between = True
                        break
            if not has_concern_between:
                conflicts.append(
                    f"⚠️ superseded decision: {short_id(d2_id)} supersedes "
                    f"{short_id(d1_id)} on topic '{topic}' with no concern raised"
                )

    return conflicts


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def render_markdown(
    events: list[dict],
    indices: dict,
    conflicts: list[str],
    skipped: int,
) -> str:
    """Render the SHARED_MENTAL_MODEL.md content."""
    sections: list[str] = []

    agent_count = len(indices["agent_ids"])

    # Header
    header = (
        f"# Shared Mental Model\n"
        f"*Auto-generated from events.jsonl "
        f"({len(events)} events, {agent_count} agents)*"
    )
    if skipped > 0:
        header += f"\n*⚠️ {skipped} malformed lines skipped*"
    sections.append(header)

    # 1. Architecture Decisions
    decisions = indices["by_type"].get("decision", [])
    if decisions:
        lines = ["## Architecture Decisions"]
        for d in decisions:
            prefix = "(draft) " if d.get("metadata", {}).get("draft") else ""
            refs_str = ""
            if d.get("references"):
                ref_parts = [short_id(r) for r in d["references"]]
                refs_str = f", references {', '.join(ref_parts)}"
            lines.append(
                f"- {prefix}**{d.get('content', '')}** "
                f"[{d.get('agent_id', '')}, {short_id(d.get('id', ''))}{refs_str}]"
            )
        sections.append("\n".join(lines))

    # 2. Conventions
    conventions = indices["by_type"].get("convention", [])
    if conventions:
        lines = ["## Conventions"]
        for c in conventions:
            lines.append(
                f"- {c.get('content', '')} "
                f"[{c.get('agent_id', '')}, {short_id(c.get('id', ''))}]"
            )
        sections.append("\n".join(lines))

    # 3. Questions for Customer
    questions = indices["by_type"].get("question", [])
    if questions:
        lines = ["## Questions for Customer"]
        for q in questions:
            q_id = q["id"]
            if q_id in indices["question_answers"]:
                answer = indices["question_answers"][q_id]
                lines.append(
                    f"- ✅ {q.get('content', '')} "
                    f"[{q.get('agent_id', '')}, {short_id(q_id)}] "
                    f"— answered: {answer.get('content', '')} "
                    f"[{short_id(answer['id'])}]"
                )
            elif q_id in indices["question_assumptions"]:
                assumption = indices["question_assumptions"][q_id]
                lines.append(
                    f"- 🟡 {q.get('content', '')} "
                    f"[{q.get('agent_id', '')}, {short_id(q_id)}] "
                    f"— **assumed: {assumption.get('content', '')}**"
                )
            elif q.get("priority") == PRIORITY_RED:
                lines.append(
                    f"- 🔴 {q.get('content', '')} "
                    f"[{q.get('agent_id', '')}, {short_id(q_id)}] "
                    f"— **blocking, awaiting answer**"
                )
            else:
                lines.append(
                    f"- {q.get('priority', '')} {q.get('content', '')} "
                    f"[{q.get('agent_id', '')}, {short_id(q_id)}]"
                )
        sections.append("\n".join(lines))

    # 4. Customer Input (last 5)
    customer_inputs = indices["by_type"].get("customer_input", [])
    if customer_inputs:
        lines = ["## Customer Input"]
        for ci in customer_inputs[-5:]:
            lines.append(f"- {ci.get('content', '')} [{ci.get('ts', '')}]")
        if len(customer_inputs) > 5:
            lines.append(
                f"*(showing last 5 of {len(customer_inputs)}"
                f" — full history in events.jsonl)*"
            )
        sections.append("\n".join(lines))

    # 5. Discoveries
    discoveries = indices["by_type"].get("discovery", [])
    if discoveries:
        lines = ["## Discoveries"]
        for d in discoveries:
            lines.append(
                f"- ⚠️ {d.get('content', '')} "
                f"[{d.get('agent_id', '')}, {short_id(d.get('id', ''))}]"
            )
        sections.append("\n".join(lines))

    # 6. Assumptions
    assumptions = indices["by_type"].get("assumption", [])
    if assumptions:
        lines = ["## Assumptions"]
        for a in assumptions:
            a_id = a["id"]
            if a_id in indices["assumption_contradictions"]:
                disc = indices["assumption_contradictions"][a_id]
                lines.append(
                    f"- ❌ {a.get('content', '')} "
                    f"[{a.get('agent_id', '')}, {short_id(a_id)}] "
                    f"— contradicted by {short_id(disc['id'])}"
                )
            else:
                lines.append(
                    f"- {a.get('content', '')} "
                    f"[{a.get('agent_id', '')}, {short_id(a_id)}] "
                    f"— unverified"
                )
        sections.append("\n".join(lines))

    # 7. Concerns
    concerns = indices["by_type"].get("concern", [])
    if concerns:
        lines = ["## Concerns"]
        for c in concerns:
            c_id = c["id"]
            if c_id in indices["concern_resolutions"]:
                resolver = indices["concern_resolutions"][c_id]
                lines.append(
                    f"- ✅ {c.get('content', '')} "
                    f"[{c.get('agent_id', '')}, {short_id(c_id)}] "
                    f"— resolved → {short_id(resolver['id'])}"
                )
            else:
                lines.append(
                    f"- ⚠️ {c.get('content', '')} "
                    f"[{c.get('agent_id', '')}, {short_id(c_id)}] "
                    f"— unacknowledged"
                )
        sections.append("\n".join(lines))

    # 8. Agent Status
    latest = indices["latest_status"]
    if latest:
        lines = ["## Agent Status"]
        for agent_id in sorted(latest):
            status = latest[agent_id]
            working_on = status.get("working_on", [])
            content = status.get("content", "")
            if working_on:
                files = ", ".join(working_on)
                lines.append(f"- **{agent_id}**: {content}. Working on: {files}")
            else:
                lines.append(f"- **{agent_id}**: {content}. Idle.")
        sections.append("\n".join(lines))

    # 9. Conflict Alerts
    if conflicts:
        lines = ["## Conflict Alerts"]
        lines.extend(f"- {c}" for c in conflicts)
        sections.append("\n".join(lines))

    # 10. Navigator Guidance (last 3)
    guidance = indices["by_type"].get("pair_guidance", [])
    if guidance:
        lines = ["## Navigator Guidance"]
        for g in guidance[-3:]:
            lines.append(
                f"- {g.get('content', '')} "
                f"[{short_id(g.get('id', ''))}, for {g.get('agent_id', '')}]"
            )
        sections.append("\n".join(lines))

    # 11. Unknown Events
    unknown_types = set(indices["by_type"].keys()) - VALID_TYPES
    if unknown_types:
        lines = ["## Unknown Events"]
        for ut in sorted(unknown_types):
            for e in indices["by_type"][ut]:
                lines.append(
                    f"- [{ut}] {e.get('content', '')} "
                    f"[{e.get('agent_id', '')}, {short_id(e.get('id', ''))}]"
                )
        sections.append("\n".join(lines))

    return "\n\n".join(sections) + "\n"


# ---------------------------------------------------------------------------
# Orchestrators
# ---------------------------------------------------------------------------


def materialize(smm_dir: Path) -> str:
    """Parse events, build indices, detect conflicts, render markdown."""
    events, skipped = parse_events(smm_dir)
    if not events and skipped == 0:
        return ""

    indices = build_indices(events)
    conflicts = detect_conflicts(events, indices)
    return render_markdown(events, indices, conflicts, skipped)


def materialize_to_file(smm_dir: Path) -> Path:
    """Atomic write of SHARED_MENTAL_MODEL.md via tempfile + rename."""
    md = materialize(smm_dir)
    target = smm_dir / "SHARED_MENTAL_MODEL.md"

    fd, tmp = tempfile.mkstemp(dir=smm_dir, suffix=".md.tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(md)
        os.chmod(tmp, 0o600)
        os.rename(tmp, target)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise

    return target


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Materialize events.jsonl into SHARED_MENTAL_MODEL.md"
    )
    parser.add_argument(
        "--smm-dir",
        type=Path,
        help="Override SMM directory (default: auto-detect from git)",
    )
    args = parser.parse_args()

    smm_dir = args.smm_dir if args.smm_dir else resolve_smm_dir()

    try:
        _validate_smm_dir(smm_dir)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    try:
        path = materialize_to_file(smm_dir)
    except LockTimeoutError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    print(f"Materialized to {path}")


if __name__ == "__main__":
    main()
