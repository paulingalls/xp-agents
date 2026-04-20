"""Event factories and SMM fixture builders for tests.

Re-exported from conftest. Import from `conftest` (canonical) or directly
from this module (also fine).
"""

import secrets
from collections.abc import Sequence
from pathlib import Path


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
    event.update(kwargs)
    return event


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
) -> dict:
    """Commit event with optional story_id for sizing/attribution tests."""
    metadata: dict = {"code_commit": True, "commit_hash": "abc123"}
    if story_id:
        metadata["story_id"] = story_id
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
