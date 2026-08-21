"""Event factories and SMM fixture builders for tests.

Re-exported from conftest. Import from `conftest` (canonical) or directly
from this module (also fine).
"""

import json
import secrets
import sys
from collections.abc import Sequence
from pathlib import Path

from event_schema import (
    EVENT_TYPE_COMMIT,
    EVENT_TYPE_CONCERN,
    EVENT_TYPE_DISCOVERY,
    EVENT_TYPE_RETROSPECTIVE,
    EVENT_TYPE_SPRINT,
    EVENT_TYPE_STATUS,
    METADATA_KEY_REFUTES,
    SPRINT_ACTION_VERIFY,
    STATUS_ACTION_FILE_WRITE,
    STATUS_ACTION_TEST_RUN_COMPLETE,
)


def verify_events(events: list[dict]) -> list[dict]:
    """Sprint-verify events (type=sprint, metadata.action=verify) in a raw list.

    Single source for the filter previously open-coded across the verify test
    suites. event_helpers.events_of_type filters by type only (it excludes
    chained filters by design), so this two-field filter lives here.
    """
    return [
        e
        for e in events
        if e.get("type") == EVENT_TYPE_SPRINT
        and (e.get("metadata") or {}).get("action") == SPRINT_ACTION_VERIFY
    ]


def write_events(events_file: Path, events: list[dict]) -> None:
    """Write events as JSONL — one event per line, trailing newline.

    Mirrors append.sh's on-disk shape: each line is a complete JSON
    object, terminated by `\n`. No header, no trailing comma.
    """
    events_file.write_text("".join(json.dumps(e) + "\n" for e in events))


def make_event(event_type: str = "customer_input", **kwargs) -> dict:
    """Create a valid event dict with defaults."""
    event = {
        "id": secrets.token_hex(6),
        "ts": "2026-03-12T00:00:00+00:00",
        "type": event_type,
        "agent_id": "main",
        "content": "test content",
        "schema_version": 1,
    }
    match event_type:
        case "status":
            event["working_on"] = kwargs.pop("working_on", ["src/app.ts"])
        case "decision" | "convention":
            event["topic"] = kwargs.pop("topic", "default-topic")
        case "question":
            event["priority"] = kwargs.pop("priority", "\U0001f534")
        case "goal":
            pass  # No extra required fields
        case "debt":
            event["files"] = kwargs.pop("files", ["src/legacy.py"])
        case "customer_intent":
            event["intent_status"] = kwargs.pop("intent_status", "open")
        case "sprint":
            event["metadata"] = kwargs.pop(
                "metadata", {"sprint_id": "sprint-001", "action": "start"}
            )
        case "answer" | "discovery":
            event["references"] = kwargs.pop("references", ["referenced-id"])
    event.update(kwargs)
    return event


def refutes_metadata(assumption: dict) -> dict:
    """The metadata a discovery must carry to DECLARE it refutes *assumption*.

    The contradicted-assumption detector fires on this and nothing else. A bare
    `references` link cannot carry the claim: the schema makes `references`
    mandatory and non-empty on EVERY discovery, so a discovery that CONFIRMS an
    assumption references it identically to one that falsifies it. Firing on the
    reference filed three false high-severity concerns in this project's own log
    — one confirmation, two pairs on unrelated subjects.

    Returned as a dict rather than baked into a factory because several suites
    need to merge it with `supersedes` / `resolves` to prove those suppressions
    still bite once the trigger is armed.
    """
    return {METADATA_KEY_REFUTES: [assumption["id"]]}


def refuting_discovery(assumption: dict, content: str, **kwargs) -> dict:
    """A discovery that declares it refutes *assumption* — the one shape that
    raises a contradiction. Both the reference and the declaration, so a fixture
    cannot be half-written at one site."""
    return make_event(
        EVENT_TYPE_DISCOVERY,
        content=content,
        references=[assumption["id"]],
        metadata=refutes_metadata(assumption),
        **kwargs,
    )


def make_retrospective_with_try(
    try_id: str, try_content: str = "A retro try item"
) -> dict:
    """Build a retrospective event carrying one nested try item with the
    given id. Helper for tests that exercise the
    compute_resolutions/annotate_try_status pipeline."""
    return make_event(
        EVENT_TYPE_RETROSPECTIVE,
        content="Session retrospective",
        **{"try": [{"id": try_id, "content": try_content, "event_refs": []}]},
    )


_WORK_SELECTION_SCRIPTS = (
    Path(__file__).parent.parent / "skills" / "xp-work-selection" / "scripts"
)


def _writer_event(smm_dir: Path, **run_kwargs) -> dict:
    """Append one adopt/defer/drop event by calling the REAL writer, and return
    the event it wrote.

    Every fixture below goes through `work_selection_decide.run` rather than
    hand-rolling the event dict, because a hand-rolled fixture encodes the shape
    its AUTHOR believed the writer produces and then drifts in silence. That is
    not hypothetical: the retro-lane suite was green for months over a broken
    reader because its fixtures built a `decision` carrying `metadata.resolves`
    — a shape no writer has produced since adoption stopped closing its target.
    Sourcing the shape from the writer means the day the writer changes, these
    tests either follow it or go red.
    """
    if str(_WORK_SELECTION_SCRIPTS) not in sys.path:
        sys.path.insert(0, str(_WORK_SELECTION_SCRIPTS))
    import work_selection_decide

    event_id = work_selection_decide.run(smm_dir=smm_dir, **run_kwargs)
    for line in (smm_dir / "events.jsonl").read_text().splitlines():
        if line.strip():
            event = json.loads(line)
            if event.get("id") == event_id:
                return event
    raise AssertionError(f"writer reported {event_id} but wrote no such event")


def _refs_suffix(try_id: str, cites: Sequence[str]) -> str:
    """The `[refs: ...]` suffix the preload renders on a carried Try line.

    `cites` are the debt/concern ids the Try's prose is ABOUT. They ride in the
    same bag as the Try's own id — which is precisely why a reader may not treat
    the bag as a list of adoption targets.
    """
    return f"[refs: {', '.join([try_id, *cites])}]"


def adopt_try_event(
    smm_dir: Path,
    try_id: str,
    *,
    cites: Sequence[str] = (),
    topic: str = "retro-try-fixture",
    content: str = "Adopt the carried Try",
) -> dict:
    """Adoption of a retro Try, as `/xp-work-selection adopt` writes it."""
    return _writer_event(
        smm_dir,
        action="adopt",
        content=f"{content} {_refs_suffix(try_id, cites)}",
        topic=topic,
    )


def defer_try_event(
    smm_dir: Path,
    try_id: str,
    *,
    cites: Sequence[str] = (),
    content: str = "Defer the carried Try",
) -> dict:
    """Deferral of a retro Try, as `/xp-work-selection defer` writes it."""
    return _writer_event(
        smm_dir,
        action="defer",
        content=f"{content} {_refs_suffix(try_id, cites)}",
    )


def drop_try_event(
    smm_dir: Path,
    try_id: str,
    *,
    cites: Sequence[str] = (),
    content: str = "Drop the carried Try",
) -> dict:
    """Drop of a retro Try, as `/xp-work-selection drop` writes it."""
    return _writer_event(
        smm_dir,
        action="drop",
        content=f"{content} {_refs_suffix(try_id, cites)}",
    )


def triage_event(smm_dir: Path, action: str, event_id: str) -> dict:
    """A triage disposition, as `/xp-work-selection triage-{adopt,defer,drop}`
    writes it. `action` is the full subcommand name."""
    return _writer_event(smm_dir, action=action, content="", event_id=event_id)


def make_session_history_entry(
    *,
    ts: str,
    summary: str,
    carry_forward: list[dict] | None = None,
) -> dict:
    """Build a session_history.json entry fixture."""
    return {
        "ts": ts,
        "summary": summary,
        "carry_forward": carry_forward or [],
    }


def file_write_status(path: str, **kwargs) -> dict:
    """Status event matching post_tool_use's file-write emission.

    Action-tagged with metadata.action=file_write + metadata.files=[path].
    Used by retro_metrics / honesty_signals consumer tests.
    """
    return make_event(
        EVENT_TYPE_STATUS,
        content=f"Wrote to {path}",
        working_on=[path],
        metadata={"action": STATUS_ACTION_FILE_WRITE, "files": [path]},
        **kwargs,
    )


def tests_run_status(
    *,
    passed: bool = True,
    count: int = 1,
    framework: str = "pytest",
    parser_status: str | None = None,
    metadata_extra: dict | None = None,
    **kwargs,
) -> dict:
    """Status event matching bash_post_tool's test_run_complete emission.

    Action-tagged with metadata.action=test_run_complete + structured
    test_passed / test_count / framework. Used by retro_metrics /
    honesty_signals / work_signals consumer tests.

    When parser_status is set (e.g. PARSER_STATUS_FAILED), test_passed
    and test_count are omitted to match bash_post_tool's no-invented-numbers
    contract for parser_failed runs.

    `metadata_extra` lets callers add producer-tagged keys (e.g. tdd_red)
    without rebuilding the whole metadata dict.
    """
    metadata: dict = {
        "action": STATUS_ACTION_TEST_RUN_COMPLETE,
        "framework": framework,
    }
    if parser_status is None:
        failed = 0 if passed else 1
        content = f"Tests: {count} passed, {failed} failed ({framework})"
        metadata["test_passed"] = passed
        metadata["test_count"] = count
    else:
        content = f"Tests ran ({framework}) — counts not extracted"
        metadata["parser_status"] = parser_status
    if metadata_extra:
        metadata.update(metadata_extra)
    return make_event(
        EVENT_TYPE_STATUS,
        content=content,
        working_on=[],
        metadata=metadata,
        **kwargs,
    )


# Canonical test-signal factories shared across integration tests that
# exercise tdd_check.find_last_test_signal. Content strings match
# scripts/concerns.py::TEST_CONCERN_RE and scripts/tdd_check.py::TEST_PASS_RE.
SUBAGENT_AUTHOR = "aefef7af4afed4caf"
"""An opaque agent id, the shape `resolve_agent_id` returns from the raw payload
field — which the harness populates only INSIDE a subagent call.

Shared because five suites now need it for the same reason: the TDD gate's
coordination release fires only for an author the tree filter could not place,
and a subagent's is the one such author that occurs in practice. Written once
because five hand-copied literals of a value a resolver produces is the drift
hazard `TEAMMATE_CWD` already documents.
"""


def failing_tests_concern(**kwargs) -> dict:
    """Concern event that find_last_test_signal classifies as 'fail'."""
    return make_event(
        EVENT_TYPE_CONCERN,
        content="Test failures detected: 2 failed (pytest)",
        severity="high",
        **kwargs,
    )


def passing_tests_status(**kwargs) -> dict:
    """Status event that find_last_test_signal classifies as 'pass'."""
    return make_event(
        EVENT_TYPE_STATUS,
        content="Tests: 5 passed, 0 failed (pytest)",
        working_on=[],
        **kwargs,
    )


def commit_event(
    files: list[str],
    ts: str = "2026-04-05T10:00:00+00:00",
    story_id: str | None = None,
    sprint_id: str | None = None,
    is_merge: bool = False,
    is_free_session: bool = False,
    agent_id: str = "main",
) -> dict:
    """A `type=commit` event.

    `agent_id` matters for merges: `story_metrics` treats `is_merge` as evidence
    the story SHIPPED only when the event came from `close_common`, the close-cycle
    emitter. Any other merge is a hand-run one — most often a back-merge keeping a
    branch current — which is neither the story shipping nor the story's own work.
    """
    metadata: dict = {"code_commit": True, "commit_hash": "abc123"}
    if story_id:
        metadata["story_id"] = story_id
    if sprint_id:
        metadata["sprint_id"] = sprint_id
    if is_merge:
        metadata["is_merge"] = True
    if is_free_session:
        metadata["is_free_session"] = True
    return make_event(
        EVENT_TYPE_COMMIT,
        content="Committed: test change",
        files=files,
        ts=ts,
        metadata=metadata,
        agent_id=agent_id,
    )


def write_smm_fixture(
    smm_dir: Path,
    *,
    intent: "Sequence[tuple[str, str]] | None" = None,
    constraints: "Sequence[tuple[str, str]] | None" = None,
    risks: "Sequence[tuple[str, str, str]] | None" = None,
    wisdom: "Sequence[str] | None" = None,
) -> None:
    """Build and save an SMM JSON fixture.

    Args:
        smm_dir: SMM directory path.
        intent: List of (content, type) tuples — type is "goal" or "customer_intent".
        constraints: (content, type) tuples — "decision" or "convention".
        risks: List of (content, type, severity) tuples.
        wisdom: List of content strings.
    """
    import smm_store

    def _make(content: str, **extra: str) -> dict:
        return {
            "id": secrets.token_hex(6),
            "content": content,
            "source": "seed",
            "ts": "2026-01-01T00:00:00+00:00",
            **extra,
        }

    data: dict = {
        "intent": [_make(c, type=t) for c, t in (intent or [])],
        "constraints": [_make(c, type=t) for c, t in (constraints or [])],
        "risks": [_make(c, type=t, severity=s) for c, t, s in (risks or [])],
        "wisdom": [_make(c) for c in (wisdom or [])],
    }
    smm_store.save_smm(smm_dir, data)
