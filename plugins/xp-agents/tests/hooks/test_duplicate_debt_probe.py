#!/usr/bin/env python3
"""Tests for duplicate_debt_probe pure module.

Covers normalization, Jaccard similarity, probe boundary behavior,
and advisory concern building.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import _common
import duplicate_debt_probe as ddp
from conftest import _HookTestCase, make_event


class TestNormalize(unittest.TestCase):
    def test_lowercases(self):
        result = ddp._normalize("Hello World")
        self.assertTrue(all(w == w.lower() for w in result))

    def test_strips_punctuation(self):
        result = ddp._normalize("fix: the bug, now!")
        self.assertNotIn(":", "".join(result))
        self.assertNotIn(",", "".join(result))
        self.assertNotIn("!", "".join(result))

    def test_removes_stopwords(self):
        result = ddp._normalize("the bug is in the code")
        self.assertNotIn("the", result)
        self.assertNotIn("is", result)
        self.assertNotIn("in", result)

    def test_keeps_meaningful_words(self):
        result = ddp._normalize("authentication middleware broken")
        self.assertIn("authentication", result)
        self.assertIn("middleware", result)
        self.assertIn("broken", result)

    def test_returns_set(self):
        result = ddp._normalize("word word word")
        self.assertIsInstance(result, set)
        self.assertEqual(result, {"word"})

    def test_empty_string(self):
        result = ddp._normalize("")
        self.assertEqual(result, set())

    def test_only_stopwords(self):
        result = ddp._normalize("the a an is are")
        self.assertEqual(result, set())


class TestJaccard(unittest.TestCase):
    def test_identical_sets(self):
        s = {"auth", "broken", "middleware"}
        self.assertAlmostEqual(ddp._jaccard(s, s), 1.0)

    def test_disjoint_sets(self):
        a = {"auth", "broken"}
        b = {"deploy", "config"}
        self.assertAlmostEqual(ddp._jaccard(a, b), 0.0)

    def test_partial_overlap(self):
        a = {"auth", "broken", "middleware"}
        b = {"auth", "broken", "login"}
        expected = 2 / 4  # intersection=2, union=4
        self.assertAlmostEqual(ddp._jaccard(a, b), expected)

    def test_both_empty(self):
        self.assertAlmostEqual(ddp._jaccard(set(), set()), 0.0)

    def test_one_empty(self):
        self.assertAlmostEqual(ddp._jaccard({"a"}, set()), 0.0)


class TestProbeDuplicateDebt(_HookTestCase):
    def test_empty_history_returns_empty(self):
        result = ddp.probe_duplicate_debt(self.smm_dir, "some debt content")
        self.assertEqual(result, [])

    def test_no_debt_events_returns_empty(self):
        self._write_events([make_event("status"), make_event("decision")])
        result = ddp.probe_duplicate_debt(self.smm_dir, "some debt content")
        self.assertEqual(result, [])

    def test_below_threshold_returns_empty(self):
        prior = make_event("debt", content="authentication middleware broken")
        self._write_events([prior])
        result = ddp.probe_duplicate_debt(
            self.smm_dir, "deploy pipeline configuration issue"
        )
        self.assertEqual(result, [])

    def test_above_threshold_returns_match(self):
        prior = make_event(
            "debt", id="abc123", content="authentication middleware broken"
        )
        self._write_events([prior])
        result = ddp.probe_duplicate_debt(
            self.smm_dir, "authentication middleware is broken"
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["debt_id"], "abc123")
        self.assertGreater(result[0]["similarity"], 0.8)

    def test_exact_duplicate_returns_similarity_1(self):
        prior = make_event("debt", id="exact1", content="fix the auth bug")
        self._write_events([prior])
        result = ddp.probe_duplicate_debt(self.smm_dir, "fix the auth bug")
        self.assertEqual(len(result), 1)
        self.assertAlmostEqual(result[0]["similarity"], 1.0)

    def test_window_caps_at_20(self):
        events = []
        for i in range(25):
            events.append(
                make_event("debt", id=f"d{i:03}", content=f"unique debt item {i}")
            )
        # Add a duplicate of the first event (index 0, outside window of 20)
        self._write_events(events)
        result = ddp.probe_duplicate_debt(self.smm_dir, "unique debt item 0", window=20)
        # d000 is outside the 20 most recent, so no match
        self.assertEqual(result, [])

    def test_window_includes_recent(self):
        events = []
        for i in range(25):
            events.append(
                make_event("debt", id=f"d{i:03}", content=f"unique debt item {i}")
            )
        self._write_events(events)
        result = ddp.probe_duplicate_debt(
            self.smm_dir, "unique debt item 24", window=20
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["debt_id"], "d024")

    def test_custom_threshold(self):
        prior = make_event("debt", id="t1", content="auth middleware broken")
        self._write_events([prior])
        # With threshold 0.99, high-but-not-perfect overlap should not match
        result = ddp.probe_duplicate_debt(
            self.smm_dir, "auth middleware broken badly", threshold=0.99
        )
        self.assertEqual(result, [])

    def test_multiple_matches(self):
        e1 = make_event("debt", id="m1", content="fix auth middleware bug")
        e2 = make_event("debt", id="m2", content="fix auth middleware issue")
        self._write_events([e1, e2])
        result = ddp.probe_duplicate_debt(self.smm_dir, "fix auth middleware bug")
        self.assertGreaterEqual(len(result), 1)
        ids = {r["debt_id"] for r in result}
        self.assertIn("m1", ids)

    def test_skips_resolved_debts(self):
        resolved = make_event(
            "debt",
            id="r1",
            content="auth middleware broken",
            metadata={"resolved": True},
        )
        self._write_events([resolved])
        result = ddp.probe_duplicate_debt(self.smm_dir, "auth middleware broken")
        self.assertEqual(result, [])

    def test_exclude_id_skips_self(self):
        prior = make_event("debt", id="self1", content="auth middleware broken")
        self._write_events([prior])
        result = ddp.probe_duplicate_debt(
            self.smm_dir, "auth middleware broken", exclude_id="self1"
        )
        self.assertEqual(result, [])

    def test_normalization_handles_punctuation_and_case(self):
        prior = make_event("debt", id="p1", content="Fix: the Auth Middleware, NOW!")
        self._write_events([prior])
        result = ddp.probe_duplicate_debt(self.smm_dir, "fix auth middleware now")
        self.assertEqual(len(result), 1)


class TestBuildAdvisoryConcern(unittest.TestCase):
    def test_builds_valid_concern(self):
        matches = [{"debt_id": "abc123", "similarity": 0.85}]
        result = ddp.build_advisory_concern(matches, "new789", "main")
        self.assertEqual(result["type"], "concern")
        self.assertEqual(result["severity"], "low")
        self.assertEqual(result["agent_id"], "main")
        self.assertIn("abc123", result["content"])
        self.assertIn("duplicate", result["content"].lower())
        self.assertEqual(result["metadata"]["duplicate_of"], "abc123")

    def test_multiple_matches_uses_highest_similarity(self):
        matches = [
            {"debt_id": "a1", "similarity": 0.82},
            {"debt_id": "a2", "similarity": 0.95},
        ]
        result = ddp.build_advisory_concern(matches, "new1", "main")
        self.assertEqual(result["metadata"]["duplicate_of"], "a2")

    def test_has_required_event_fields(self):
        matches = [{"debt_id": "x1", "similarity": 0.9}]
        result = ddp.build_advisory_concern(matches, "new1", "test-agent")
        self.assertIn("id", result)
        self.assertIn("ts", result)
        self.assertIn("schema_version", result)
        self.assertEqual(result["agent_id"], "test-agent")


class TestRunProbeAndAppendExceptionNarrowing(unittest.TestCase):
    """Unexpected exceptions propagate instead of being silently swallowed."""

    def test_attribute_error_propagates(self):
        from unittest.mock import patch

        with (
            patch.object(
                ddp, "probe_duplicate_debt", side_effect=AttributeError("bug")
            ),
            self.assertRaises(AttributeError),
        ):
            ddp.run_probe_and_append(
                Path("/tmp/fake-smm"),
                {"type": "debt", "content": "test", "id": "x", "agent_id": "m"},
            )

    def test_os_error_swallowed(self):
        from unittest.mock import patch

        with patch.object(ddp, "probe_duplicate_debt", side_effect=OSError("disk")):
            ddp.run_probe_and_append(
                Path("/tmp/fake-smm"),
                {"type": "debt", "content": "test", "id": "x", "agent_id": "m"},
            )


class TestDuplicateDebtProbeIntegration(_HookTestCase):
    """Integration: append_safe with debt triggers advisory concern."""

    def test_append_duplicate_debt_creates_advisory(self):
        prior = make_event("debt", id="prior1", content="auth middleware broken")
        self._write_events([prior])
        new_debt = make_event("debt", content="auth middleware broken")
        _common.append_safe(self.smm_dir, new_debt)
        events = self._read_events()
        concerns = [e for e in events if e.get("type") == "concern"]
        advisories = [c for c in concerns if c.get("metadata", {}).get("duplicate_of")]
        self.assertEqual(len(advisories), 1)
        self.assertEqual(advisories[0]["metadata"]["duplicate_of"], "prior1")
        self.assertEqual(advisories[0]["severity"], "low")

    def test_append_unique_debt_no_advisory(self):
        prior = make_event("debt", content="auth middleware broken")
        self._write_events([prior])
        new_debt = make_event("debt", content="deploy pipeline misconfigured")
        _common.append_safe(self.smm_dir, new_debt)
        events = self._read_events()
        concerns = [e for e in events if e.get("type") == "concern"]
        advisories = [c for c in concerns if c.get("metadata", {}).get("duplicate_of")]
        self.assertEqual(len(advisories), 0)

    def test_append_non_debt_no_probe(self):
        _common.append_safe(self.smm_dir, make_event("status"))
        events = self._read_events()
        concerns = [e for e in events if e.get("type") == "concern"]
        self.assertEqual(len(concerns), 0)

    def test_bulk_append_duplicate_debt_creates_advisory(self):
        prior = make_event("debt", id="bulk1", content="auth middleware broken")
        self._write_events([prior])
        new_debt = make_event("debt", content="auth middleware broken")
        _common.bulk_append_safe(self.smm_dir, [new_debt])
        events = self._read_events()
        advisories = [
            e
            for e in events
            if e.get("type") == "concern" and e.get("metadata", {}).get("duplicate_of")
        ]
        self.assertEqual(len(advisories), 1)
        self.assertEqual(advisories[0]["metadata"]["duplicate_of"], "bulk1")


class TestRunDuplicateDebtProbeExceptionNarrowing(unittest.TestCase):
    """_run_duplicate_debt_probe only catches ImportError after narrowing."""

    def test_type_error_propagates(self):
        from unittest.mock import patch

        with (
            patch(
                "duplicate_debt_probe.run_probe_and_append",
                side_effect=TypeError("bug"),
            ),
            self.assertRaises(TypeError),
        ):
            _common._run_duplicate_debt_probe(
                Path("/tmp/fake-smm"),
                {"type": "debt", "content": "test"},
            )

    def test_import_error_swallowed(self):
        from unittest.mock import patch

        with patch.dict("sys.modules", {"duplicate_debt_probe": None}):
            _common._run_duplicate_debt_probe(
                Path("/tmp/fake-smm"),
                {"type": "debt", "content": "test"},
            )


if __name__ == "__main__":
    unittest.main()
