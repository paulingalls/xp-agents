"""Event factories and SMM fixture builders for tests.

Re-exported from conftest. Import from `conftest` (canonical) or directly
from this module (also fine).
"""

import json
import secrets
from collections.abc import Sequence
from pathlib import Path

from event_schema import STATUS_ACTION_FILE_WRITE, STATUS_ACTION_TEST_RUN_COMPLETE


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


def make_retrospective_with_try(
    try_id: str, try_content: str = "A retro try item"
) -> dict:
    """Build a retrospective event carrying one nested try item with the
    given id. Helper for tests that exercise the
    compute_resolutions/annotate_try_status pipeline."""
    return make_event(
        "retrospective",
        content="Session retrospective",
        **{"try": [{"id": try_id, "content": try_content, "event_refs": []}]},
    )


def file_write_status(path: str, **kwargs) -> dict:
    """Status event matching post_tool_use's file-write emission.

    Action-tagged with metadata.action=file_write + metadata.files=[path].
    Used by retro_metrics / honesty_signals consumer tests.
    """
    return make_event(
        "status",
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
    **kwargs,
) -> dict:
    """Status event matching bash_post_tool's test_run_complete emission.

    Action-tagged with metadata.action=test_run_complete + structured
    test_passed / test_count / framework. Used by retro_metrics /
    honesty_signals / work_signals consumer tests.

    When parser_status is set (e.g. PARSER_STATUS_FAILED), test_passed
    and test_count are omitted to match bash_post_tool's no-invented-numbers
    contract for parser_failed runs.
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
    return make_event(
        "status",
        content=content,
        working_on=[],
        metadata=metadata,
        **kwargs,
    )


# Canonical test-signal factories shared across integration tests that
# exercise tdd_check.find_last_test_signal. Content strings match
# scripts/concerns.py::TEST_CONCERN_RE and scripts/tdd_check.py::TEST_PASS_RE.
def failing_tests_concern(**kwargs) -> dict:
    """Concern event that find_last_test_signal classifies as 'fail'."""
    return make_event(
        "concern",
        content="Test failures detected: 2 failed (pytest)",
        severity="high",
        **kwargs,
    )


def passing_tests_status(**kwargs) -> dict:
    """Status event that find_last_test_signal classifies as 'pass'."""
    return make_event(
        "status",
        content="Tests: 5 passed, 0 failed (pytest)",
        working_on=[],
        **kwargs,
    )


def commit_event(
    files: list[str],
    ts: str = "2026-04-05T10:00:00+00:00",
    story_id: str | None = None,
    sprint_id: str | None = None,
) -> dict:
    metadata: dict = {"code_commit": True, "commit_hash": "abc123"}
    if story_id:
        metadata["story_id"] = story_id
    if sprint_id:
        metadata["sprint_id"] = sprint_id
    return make_event(
        "commit",
        content="Committed: test change",
        files=files,
        ts=ts,
        metadata=metadata,
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
