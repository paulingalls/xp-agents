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


if __name__ == "__main__":
    unittest.main()
