#!/usr/bin/env python3
"""Tests for event_schema STATUS_ACTION_* constants."""

import re
import sys
import unittest
from pathlib import Path
from typing import ClassVar

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))
import compact
import event_schema
import materialize

# Explicit `from event_schema import EVENT_TYPE_*` so a future constant rename
# fails at test collection (NameError) instead of silently changing behavior.
from event_schema import EVENT_TYPE_STATUS


class TestStatusActionConstants(unittest.TestCase):
    """Each constant exists with the expected value and the set is unique."""

    M1_EXPECTED: ClassVar[dict[str, str]] = {
        "STATUS_ACTION_SIMPLIFY_COMPLETE": "simplify_complete",
        "STATUS_ACTION_QR_COMPLETE": "qr_complete",
        "STATUS_ACTION_SECURITY_COMPLETE": "security_complete",
        "STATUS_ACTION_PLAN_REVIEWED": "plan_reviewed",
        "STATUS_ACTION_HOUSEKEEPING_COMPLETE": "housekeeping_complete",
    }

    M2_EXPECTED: ClassVar[dict[str, str]] = {
        "STATUS_ACTION_FILE_WRITE": "file_write",
        "STATUS_ACTION_TEST_RUN_COMPLETE": "test_run_complete",
        "STATUS_ACTION_LINT_RESOLVED": "lint_resolved",
        "STATUS_ACTION_BASH_FAILED": "bash_failed",
        "STATUS_ACTION_COMMIT_SUCCESS": "commit_success",
    }

    M3_EXPECTED: ClassVar[dict[str, str]] = {
        "STATUS_ACTION_SUBAGENT_COMPLETE": "subagent_complete",
        "STATUS_ACTION_PLAN_COMPLETED": "plan_completed",
        "STATUS_ACTION_PLAN_AWAITING_REVIEW": "plan_awaiting_review",
        "STATUS_ACTION_PLAN_EXITED": "plan_exited",
    }

    # Step 5c (close skills) — concern classification per finding.
    # Producer is the LLM running story-close + free-close at Step 5c
    # via append.sh; consumer is the Step 6 auto-merge gate's
    # count-classifications subcommand.
    STEP_5C_EXPECTED: ClassVar[dict[str, str]] = {
        "STATUS_ACTION_CONCERN_CLASSIFY": "concern_classify",
    }

    EXPECTED: ClassVar[dict[str, str]] = {
        **M1_EXPECTED,
        **M2_EXPECTED,
        **M3_EXPECTED,
        **STEP_5C_EXPECTED,
    }

    def test_each_constant_exists_with_expected_value(self):
        for name, expected in self.EXPECTED.items():
            with self.subTest(constant=name):
                self.assertTrue(
                    hasattr(event_schema, name),
                    f"event_schema missing constant {name}",
                )
                self.assertEqual(getattr(event_schema, name), expected)

    def test_action_vocabularies_distinct_from_legacy_status_actions(self):
        """M1/M2/M3 vocabularies must not collide with legacy status actions."""
        new_values = {getattr(event_schema, n) for n in self.EXPECTED}
        self.assertNotIn(event_schema.STATUS_ACTION_ITERATION_COMPLETE, new_values)
        self.assertNotIn(event_schema.STATUS_ACTION_SPRINT_RETRO_DONE, new_values)

    def test_m2_set_disjoint_from_m1_review_cycle(self):
        """M2 vocabulary must not collide with the M1 review-cycle vocabulary."""
        m1_values = frozenset(self.M1_EXPECTED.values())
        m2_values = frozenset(self.M2_EXPECTED.values())
        self.assertTrue(
            m1_values.isdisjoint(m2_values),
            f"M1 and M2 action vocabularies overlap: {m1_values & m2_values}",
        )

    def test_m3_set_disjoint_from_m1_m2(self):
        """M3 vocabulary must not collide with M1 or M2 vocabularies."""
        prior_values = frozenset(self.M1_EXPECTED.values()) | frozenset(
            self.M2_EXPECTED.values()
        )
        m3_values = frozenset(self.M3_EXPECTED.values())
        self.assertTrue(
            prior_values.isdisjoint(m3_values),
            f"M3 overlaps with prior vocabularies: {prior_values & m3_values}",
        )

    # Expected producer hook for each M2/M3 constant. The doc blocks in
    # event_schema.py must annotate every constant with its specific hook
    # filename on the same comment line — not just mention all hooks in a
    # shared block (which would let the test pass on mis-attribution).
    EXPECTED_PRODUCER: ClassVar[dict[str, str]] = {
        "STATUS_ACTION_FILE_WRITE": "post_tool_use.py",
        "STATUS_ACTION_TEST_RUN_COMPLETE": "bash_post_tool.py",
        "STATUS_ACTION_LINT_RESOLVED": "lint_resolution.py",
        "STATUS_ACTION_BASH_FAILED": "bash_failure.py",
        "STATUS_ACTION_COMMIT_SUCCESS": "bash_post_tool.py",
        "STATUS_ACTION_SUBAGENT_COMPLETE": "subagent_stop.py",
        "STATUS_ACTION_PLAN_COMPLETED": "subagent_stop.py",
        "STATUS_ACTION_PLAN_AWAITING_REVIEW": "subagent_stop.py",
        "STATUS_ACTION_PLAN_EXITED": "post_tool_exit_plan.py",
    }

    def test_doc_block_names_emitting_hook(self):
        """The producer map names each constant on the same line as its hook.

        Reads both event_schema.py and event_metadata.py (since story-004
        split STATUS_ACTION_* and friends into event_metadata.py via the
        split-shim convention; producer-map comments moved with them).
        """
        import event_metadata

        sources = [event_schema.__file__, event_metadata.__file__]
        text = "\n".join(
            Path(s).read_text(encoding="utf-8") for s in sources if s is not None
        )
        for name, expected_hook in self.EXPECTED_PRODUCER.items():
            with self.subTest(constant=name):
                # Match a comment line that names the constant and its hook
                # together — this is the producer map's load-bearing claim.
                pattern = re.compile(
                    rf"^\s*#.*\b{name}\b.*\b{re.escape(expected_hook)}\b",
                    re.MULTILINE,
                )
                self.assertRegex(
                    text,
                    pattern,
                    f"producer map must annotate {name} with {expected_hook} "
                    f"on a single comment line",
                )


class TestRetireEditReExportCompleteness(unittest.TestCase):
    """STATUS_ACTION_RETIRE_*/EDIT_* must be re-exported from event_schema.

    Regression test for concern c83d08870bf2: event_metadata.py defines
    these ten names, and event_schema.py's docstring/comment above the
    `from event_metadata import (...)` block claims "EVERY public name in
    event_metadata belongs in this list" — but these ten were missing,
    so `from event_schema import STATUS_ACTION_RETIRE_MODULE` raised
    ImportError even though callers reach these names as
    `event_schema.STATUS_ACTION_RETIRE_MODULE`.
    """

    RETIRE_EDIT_NAMES: ClassVar[list[str]] = [
        "STATUS_ACTION_RETIRE_PRINCIPLE",
        "STATUS_ACTION_RETIRE_MODULE",
        "STATUS_ACTION_RETIRE_CONVENTION",
        "STATUS_ACTION_RETIRE_PROJECT_SPECIFIC",
        "STATUS_ACTION_RETIRE_ACCEPTANCE_SURFACE",
        "STATUS_ACTION_EDIT_PRINCIPLE",
        "STATUS_ACTION_EDIT_MODULE",
        "STATUS_ACTION_EDIT_CONVENTION",
        "STATUS_ACTION_EDIT_PROJECT_SPECIFIC",
        "STATUS_ACTION_EDIT_ACCEPTANCE_SURFACE",
    ]

    def test_names_importable_from_event_schema(self):
        for name in self.RETIRE_EDIT_NAMES:
            with self.subTest(constant=name):
                self.assertTrue(
                    hasattr(event_schema, name),
                    f"event_schema missing re-exported constant {name}",
                )

    def test_reexported_names_are_identity_equal_to_event_metadata(self):
        import event_metadata

        for name in self.RETIRE_EDIT_NAMES:
            with self.subTest(constant=name):
                self.assertIs(
                    getattr(event_schema, name),
                    getattr(event_metadata, name),
                    f"event_schema.{name} is not identity-equal to "
                    f"event_metadata.{name} — re-export must be by identity, "
                    f"not a redefinition",
                )


class TestMetadataResolvesValidation(unittest.TestCase):
    """metadata.resolves must be list[str] of 12-hex-char event IDs.

    The original bug (decision 311a2af6fce7) emitted resolves as a
    string scalar instead of a list. resolution.py:128 then iterated
    the string char-by-char, finding nothing — STRONG resolution
    silently failed. The schema validator now rejects scalars at
    write time so this class of bug cannot recur.
    """

    _BASE_EVENT: ClassVar[dict] = {
        "id": "abc123def456",
        "ts": "2026-05-04T17:00:00+00:00",
        "type": EVENT_TYPE_STATUS,
        "agent_id": "main",
        "content": "test",
        "schema_version": 1,
        "working_on": [],
    }

    def _event_with_resolves(self, value: object) -> dict:
        return {**self._BASE_EVENT, "metadata": {"resolves": value}}

    def test_list_of_valid_ids_accepted(self):
        event = self._event_with_resolves(["abc123def456", "fedcba654321"])
        self.assertEqual(event_schema.validate_event(event), [])

    def test_metadata_without_resolves_accepted(self):
        event = {**self._BASE_EVENT, "metadata": {"action": "explicit_zero"}}
        self.assertEqual(event_schema.validate_event(event), [])

    def test_no_metadata_at_all_accepted(self):
        self.assertEqual(event_schema.validate_event(self._BASE_EVENT), [])

    def test_string_scalar_rejected(self):
        event = self._event_with_resolves("abc123def456")
        errors = event_schema.validate_event(event)
        self.assertTrue(
            any("resolves" in e and "list" in e for e in errors),
            f"Expected list-shape error; got: {errors}",
        )

    def test_non_list_non_string_rejected(self):
        event = self._event_with_resolves(12345)
        errors = event_schema.validate_event(event)
        self.assertTrue(
            any("resolves" in e and "list" in e for e in errors),
            f"Expected list-shape error; got: {errors}",
        )

    def test_list_with_non_string_item_rejected(self):
        event = self._event_with_resolves(["abc123def456", 42])
        errors = event_schema.validate_event(event)
        self.assertTrue(
            any("resolves" in e for e in errors),
            f"Expected element-type error; got: {errors}",
        )

    def test_list_with_malformed_id_rejected(self):
        event = self._event_with_resolves(["abc123def456", "not-an-id"])
        errors = event_schema.validate_event(event)
        self.assertTrue(
            any("resolves" in e for e in errors),
            f"Expected ID-format error; got: {errors}",
        )

    def test_empty_list_accepted(self):
        event = self._event_with_resolves([])
        self.assertEqual(event_schema.validate_event(event), [])


class TestEventCategoryCompleteness(unittest.TestCase):
    """Every EVENT_TYPE_* in VALID_TYPES maps to exactly one EVENT_CATEGORY.

    Adding a new EVENT_TYPE_* without classifying it must fail loud here
    rather than silently dropping the new type into a default bucket.
    """

    def test_every_valid_type_has_category(self):
        for event_type in event_schema.VALID_TYPES:
            with self.subTest(event_type=event_type):
                category = event_schema.event_category_of(event_type)
                self.assertIsInstance(category, event_schema.EVENT_CATEGORY)

    def test_unknown_event_type_raises(self):
        with self.assertRaises(ValueError):
            event_schema.event_category_of("bogus_type")

    def test_map_keys_match_valid_types(self):
        """No stale entries in _EVENT_CATEGORY_MAP, no missing entries."""
        self.assertEqual(
            set(event_schema._EVENT_CATEGORY_MAP),
            set(event_schema.VALID_TYPES),
        )


class TestEventCategoryDerivation(unittest.TestCase):
    """Byte-equivalence regression pin: derivations in materialize.py and
    compact.py must produce the exact frozenset contents the project relied
    on before EVENT_CATEGORY landed. Snapshot the expected contents here
    as literal sets — if the derivation changes accidentally, this test
    catches it loudly."""

    EXPECTED_BUCKET_ABSENT: ClassVar[frozenset] = frozenset(
        {
            "answer",
            "commit",
            "convention",
            "customer_intent",
            "discovery",
            "goal",
            "session_started",
            "retrospective",
            "session_end",
            "session_summary",
            "sprint",
            "status",
        }
    )

    EXPECTED_COMPACT_ABSENT: ClassVar[frozenset] = frozenset(
        {
            "answer",
            "customer_input",
            "discovery",
            "session_started",
            "session_end",
            "session_summary",
            "status",
        }
    )

    def test_bucket_intentionally_absent_unchanged(self):
        self.assertEqual(
            materialize._BUCKET_INTENTIONALLY_ABSENT,
            self.EXPECTED_BUCKET_ABSENT,
        )

    def test_compact_intentionally_absent_unchanged(self):
        self.assertEqual(
            compact._COMPACT_INTENTIONALLY_ABSENT,
            self.EXPECTED_COMPACT_ABSENT,
        )


class TestSessionStartedRegistration(unittest.TestCase):
    """session_started is the deterministic session-boundary anchor
    (decision f248f4c4e29f, supersedes 9933b0ac1549), registered as a
    SIBLING_ARTIFACT marker mirroring session_end. Inert until Milestone 2
    consumes it for boundary math; this only pins its schema registration."""

    _BASE_EVENT: ClassVar[dict] = {
        "id": "abc123def456",
        "ts": "2026-05-22T18:00:00+00:00",
        "type": "session_started",
        "agent_id": "xp-kickoff",
        "content": "session anchor",
        "schema_version": 1,
    }

    def test_constant_exists_with_expected_value(self):
        self.assertTrue(
            hasattr(event_schema, "EVENT_TYPE_SESSION_STARTED"),
            "event_schema missing constant EVENT_TYPE_SESSION_STARTED",
        )
        self.assertEqual(event_schema.EVENT_TYPE_SESSION_STARTED, "session_started")

    def test_in_valid_types(self):
        self.assertIn("session_started", event_schema.VALID_TYPES)

    def test_category_is_sibling_artifact(self):
        self.assertEqual(
            event_schema.event_category_of("session_started"),
            event_schema.EVENT_CATEGORY.SIBLING_ARTIFACT,
        )

    def test_content_budget_is_50(self):
        self.assertEqual(event_schema.get_required_budget("session_started"), 50)

    def test_well_formed_event_validates(self):
        self.assertEqual(event_schema.validate_event(self._BASE_EVENT), [])

    def test_content_over_budget_rejected(self):
        event = {**self._BASE_EVENT, "content": "x" * 51}
        errors = event_schema.validate_event(event)
        self.assertTrue(
            any("budget" in e for e in errors),
            f"Expected content-budget error; got: {errors}",
        )


class TestContentBudgetRaise(unittest.TestCase):
    """concern/debt/decision/discovery budgets raised 400 -> 500 chars so a
    full causal chain (the WHY, not just the conclusion) fits in one event.
    status stays at 200 -- a signal is not an argument."""

    _BASE: ClassVar[dict] = {
        "id": "abc123def456",
        "ts": "2026-07-13T00:00:00+00:00",
        "agent_id": "main",
        "schema_version": 1,
    }

    def _event(self, event_type: str, content: str) -> dict:
        event = {**self._BASE, "type": event_type, "content": content}
        if event_type == EVENT_TYPE_STATUS:
            event["working_on"] = []
        elif event_type in ("decision",):
            event["topic"] = "default-topic"
        return event

    def test_500_char_concern_validates(self):
        event = self._event(event_schema.EVENT_TYPE_CONCERN, "x" * 500)
        self.assertEqual(event_schema.validate_event(event), [])

    def test_501_char_concern_fails(self):
        event = self._event(event_schema.EVENT_TYPE_CONCERN, "x" * 501)
        errors = event_schema.validate_event(event)
        self.assertTrue(
            any("budget" in e for e in errors),
            f"Expected content-budget error; got: {errors}",
        )

    def test_500_char_debt_validates(self):
        event = self._event(event_schema.EVENT_TYPE_DEBT, "x" * 500)
        event["files"] = ["scripts/x.py"]
        self.assertEqual(event_schema.validate_event(event), [])

    def test_500_char_decision_validates(self):
        event = self._event(event_schema.EVENT_TYPE_DECISION, "x" * 500)
        self.assertEqual(event_schema.validate_event(event), [])

    def test_500_char_discovery_validates(self):
        event = self._event(event_schema.EVENT_TYPE_DISCOVERY, "x" * 500)
        event["references"] = ["referenced-id"]
        self.assertEqual(event_schema.validate_event(event), [])

    def test_status_event_at_201_chars_still_fails(self):
        event = self._event(EVENT_TYPE_STATUS, "x" * 201)
        errors = event_schema.validate_event(event)
        self.assertTrue(
            any("budget" in e for e in errors),
            f"Expected content-budget error; got: {errors}",
        )

    def test_status_budget_unchanged_at_200(self):
        self.assertEqual(event_schema.get_required_budget(EVENT_TYPE_STATUS), 200)


class TestUnknownKeyRejection(unittest.TestCase):
    """validate_event rejects unknown top-level keys per type, so field-name
    typos fail at write time instead of round-tripping into events.jsonl."""

    _BASE_STATUS: ClassVar[dict] = {
        "id": "abc123def456",
        "ts": "2026-05-17T00:00:00+00:00",
        "type": EVENT_TYPE_STATUS,
        "agent_id": "main",
        "content": "test",
        "schema_version": 1,
        "working_on": [],
    }

    def test_rejects_unknown_top_level_key(self):
        event = {**self._BASE_STATUS, "naem": "typo-for-future-field"}
        errors = event_schema.validate_event(event)
        self.assertTrue(
            any("naem" in e for e in errors),
            f"Expected unknown-field error naming 'naem'; got: {errors}",
        )

    def test_rejects_unknown_key_on_status_event(self):
        # 'severity' is valid on concern but NOT on status.
        event = {**self._BASE_STATUS, "severity": "high"}
        errors = event_schema.validate_event(event)
        self.assertTrue(
            any("severity" in e for e in errors),
            f"Expected unknown-field error naming 'severity' on status; got: {errors}",
        )

    def test_every_event_type_has_allowed_keys_entry(self):
        missing = set(event_schema.VALID_TYPES) - set(event_schema._TYPE_ALLOWED_KEYS)
        self.assertFalse(
            missing,
            f"Add to _TYPE_ALLOWED_KEYS: {sorted(missing)}",
        )


if __name__ == "__main__":
    unittest.main()
