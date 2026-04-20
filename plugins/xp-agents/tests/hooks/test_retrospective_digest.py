#!/usr/bin/env python3
"""Tests for retrospective digest structure, resolutions, and try annotation.

Split from test_retrospective.py.
"""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from conftest import _HookTestCase, make_event


class TestRetrospectiveResolvedConcerns(_HookTestCase):
    """Resolved concerns should be rolled up to counts, not included in full."""

    def setUp(self):
        super().setUp()
        (self.smm_dir / "retrospectives").mkdir()

    def test_resolved_concerns_excluded_from_signal_events(self):
        import retrospective

        c1 = make_event("concern", content="Lint error in foo.py: F401")
        c2 = make_event("concern", content="Unresolved real concern")
        resolver = make_event(
            "status",
            content="Fixed",
            working_on=["foo.py"],
            metadata={"resolves": [c1["id"]]},
        )
        events = [c1, c2, resolver, make_event(content="f1"), make_event(content="f2")]
        self._write_events(events)
        retrospective.run(
            {"session_id": "test", "source": "startup"},
            smm_dir=self.smm_dir,
        )
        with open(self.smm_dir / ".retro-input.json") as f:
            data = json.load(f)
        signal_ids = {e["id"] for e in data["digest"]["signal_events"]}
        self.assertNotIn(c1["id"], signal_ids)
        self.assertIn(c2["id"], signal_ids)

    def test_resolved_concerns_counted_in_digest(self):
        import retrospective

        c1 = make_event("concern", content="Lint error")
        c2 = make_event("concern", content="Test failure")
        resolver = make_event(
            "status",
            content="Fixed both",
            working_on=[],
            metadata={"resolves": [c1["id"], c2["id"]]},
        )
        events = [c1, c2, resolver, make_event(content="f1"), make_event(content="f2")]
        self._write_events(events)
        retrospective.run(
            {"session_id": "test", "source": "startup"},
            smm_dir=self.smm_dir,
        )
        with open(self.smm_dir / ".retro-input.json") as f:
            data = json.load(f)
        self.assertEqual(data["digest"]["resolved_concern_count"], 2)

    def test_resolved_concerns_excluded_from_concern_groups(self):
        import retrospective

        c1 = make_event("concern", content="Lint error in foo.py")
        c2 = make_event("concern", content="Lint error in bar.py")
        c3 = make_event("concern", content="Real design concern")
        resolver = make_event(
            "status",
            content="Fixed",
            working_on=[],
            metadata={"resolves": [c1["id"], c2["id"]]},
        )
        events = [
            c1,
            c2,
            c3,
            resolver,
            make_event(content="f1"),
            make_event(content="f2"),
        ]
        self._write_events(events)
        retrospective.run(
            {"session_id": "test", "source": "startup"},
            smm_dir=self.smm_dir,
        )
        with open(self.smm_dir / ".retro-input.json") as f:
            data = json.load(f)
        group_keys = [g["key"] for g in data["digest"]["concern_groups"]]
        self.assertIn("Real design concern", group_keys)
        self.assertNotIn("Lint error in foo.py", group_keys)


class TestRetrospectiveDigestResolutions(_HookTestCase):
    """digest.resolutions exposes all 6 resolution types to the retro analyst."""

    def setUp(self):
        super().setUp()
        (self.smm_dir / "retrospectives").mkdir()

    def _run_and_load(self, events):
        import retrospective

        self._write_events(events)
        retrospective.run(
            {"session_id": "test", "source": "startup"},
            smm_dir=self.smm_dir,
        )
        with open(self.smm_dir / ".retro-input.json") as f:
            return json.load(f)

    def test_digest_includes_debt_resolutions(self):
        debt = make_event("debt", content="Fix the thing later")
        resolver = make_event(
            "status",
            content="Debt closed: fixed it",
            working_on=[],
            metadata={"resolves": [debt["id"]]},
        )
        data = self._run_and_load(
            [debt, resolver] + [make_event(content=f"e{i}") for i in range(4)]
        )
        resolutions = data["digest"]["resolutions"]
        self.assertIn(debt["id"], resolutions)
        entry = resolutions[debt["id"]]
        self.assertEqual(entry["type"], "debt")
        self.assertEqual(entry["resolver_id"], resolver["id"])
        self.assertIn("Debt closed", entry["resolver_content"])

    def test_digest_includes_question_answers(self):
        q = make_event("question", content="What do?")
        resolver = make_event(
            "status",
            content="Answered via resolve",
            working_on=[],
            metadata={"resolves": [q["id"]]},
        )
        data = self._run_and_load(
            [q, resolver] + [make_event(content=f"e{i}") for i in range(4)]
        )
        self.assertIn(q["id"], data["digest"]["resolutions"])
        self.assertEqual(data["digest"]["resolutions"][q["id"]]["type"], "question")

    def test_digest_includes_all_resolution_types(self):
        goal = make_event("goal", content="Ship feature X")
        assumption = make_event("assumption", content="Assuming X works like Y")
        concern = make_event("concern", content="A worry")
        decision = make_event("decision", content="Use X", topic="x-topic")
        resolver = make_event(
            "status",
            content="Everything resolved",
            working_on=[],
            metadata={
                "resolves": [
                    goal["id"],
                    assumption["id"],
                    concern["id"],
                    decision["id"],
                ]
            },
        )
        data = self._run_and_load(
            [goal, assumption, concern, decision, resolver]
            + [make_event(content=f"e{i}") for i in range(4)]
        )
        resolutions = data["digest"]["resolutions"]
        self.assertEqual(resolutions[goal["id"]]["type"], "goal")
        self.assertEqual(resolutions[assumption["id"]]["type"], "assumption")
        self.assertEqual(resolutions[concern["id"]]["type"], "concern")
        self.assertEqual(resolutions[decision["id"]]["type"], "decision")

    def test_resolutions_resolver_content_truncated_to_200(self):
        debt = make_event("debt", content="Thing")
        long_content = "x" * 500
        resolver = make_event(
            "status",
            content=long_content,
            working_on=[],
            metadata={"resolves": [debt["id"]]},
        )
        data = self._run_and_load(
            [debt, resolver] + [make_event(content=f"e{i}") for i in range(4)]
        )
        self.assertEqual(
            len(data["digest"]["resolutions"][debt["id"]]["resolver_content"]),
            200,
        )

    def test_resolutions_use_short_ids(self):
        debt = make_event("debt", content="Thing")
        resolver = make_event(
            "status",
            content="Fixed",
            working_on=[],
            metadata={"resolves": [debt["id"]]},
        )
        data = self._run_and_load(
            [debt, resolver] + [make_event(content=f"e{i}") for i in range(4)]
        )
        for key in data["digest"]["resolutions"]:
            self.assertEqual(len(key), 12, f"key {key!r} is not 12 chars")

    def test_resolutions_single_bucket_invariant(self):
        debt = make_event("debt", content="Thing 1")
        goal = make_event("goal", content="Thing 2")
        resolver = make_event(
            "status",
            content="Both fixed",
            working_on=[],
            metadata={"resolves": [debt["id"], goal["id"]]},
        )
        data = self._run_and_load(
            [debt, goal, resolver] + [make_event(content=f"e{i}") for i in range(4)]
        )
        resolutions = data["digest"]["resolutions"]
        self.assertEqual(len(resolutions), 2)
        self.assertEqual(resolutions[debt["id"]]["type"], "debt")
        self.assertEqual(resolutions[goal["id"]]["type"], "goal")


class TestGatherRetroHistoryTryShape(_HookTestCase):
    """try items in previous_retros preserve {content, event_refs} shape."""

    def setUp(self):
        super().setUp()
        self.retro_dir = self.smm_dir / "retrospectives"
        self.retro_dir.mkdir()

    def test_gather_retro_history_preserves_try_event_refs(self):
        import retro_history

        retro_data = {
            "keep": [{"content": "TDD held", "event_refs": ["aaa11111"]}],
            "fix": [{"content": "no status events"}],
            "try": [
                {
                    "content": "close debt 9cdd4617",
                    "event_refs": ["9cdd4617-aaaa-bbbb-cccc-dddddddddddd"],
                }
            ],
        }
        (self.retro_dir / "2026-03-10T00-00-00.json").write_text(json.dumps(retro_data))
        result = retro_history.gather_retro_history(self.smm_dir)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["keep"], ["TDD held"])
        self.assertEqual(result[0]["fix"], ["no status events"])
        self.assertEqual(len(result[0]["try"]), 1)
        self.assertEqual(result[0]["try"][0]["content"], "close debt 9cdd4617")
        self.assertEqual(
            result[0]["try"][0]["event_refs"],
            ["9cdd4617-aaaa-bbbb-cccc-dddddddddddd"],
        )

    def test_gather_retro_history_handles_legacy_string_try(self):
        import retro_history

        retro_data = {
            "keep": [{"content": "good session"}],
            "fix": [],
            "try": ["be more careful"],
        }
        (self.retro_dir / "2026-03-10T00-00-00.json").write_text(json.dumps(retro_data))
        result = retro_history.gather_retro_history(self.smm_dir)
        self.assertEqual(len(result[0]["try"]), 1)
        self.assertEqual(result[0]["try"][0]["content"], "be more careful")
        self.assertEqual(result[0]["try"][0]["event_refs"], [])


class TestAnnotateTryStatus(_HookTestCase):
    """_annotate_try_status flags Try items whose IDs were resolved this session."""

    def setUp(self):
        super().setUp()
        (self.smm_dir / "retrospectives").mkdir()

    def _run_and_load_with_retro(self, retro_data, events):
        import retrospective

        (self.smm_dir / "retrospectives" / "2026-03-10T00-00-00.json").write_text(
            json.dumps(retro_data)
        )
        self._write_events(events)
        retrospective.run(
            {"session_id": "test", "source": "startup"},
            smm_dir=self.smm_dir,
        )
        with open(self.smm_dir / ".retro-input.json") as f:
            return json.load(f)

    def test_annotate_try_with_resolved_debt_id_in_content(self):
        debt = make_event("debt", content="Fix later")
        resolver = make_event(
            "status",
            content="Debt closed",
            working_on=[],
            metadata={"resolves": [debt["id"]]},
        )
        retro_data = {
            "keep": [],
            "fix": [],
            "try": [{"content": f"close debt {debt['id']} in first commit"}],
        }
        data = self._run_and_load_with_retro(
            retro_data,
            [debt, resolver] + [make_event(content=f"e{i}") for i in range(4)],
        )
        try_status = data["previous_retros"][0]["try_status"]
        self.assertEqual(len(try_status), 1)
        self.assertTrue(try_status[0]["resolved_this_session"])
        self.assertEqual(try_status[0]["resolver_id"], resolver["id"])

    def test_annotate_try_with_event_refs_only(self):
        debt = make_event("debt", content="Fix later")
        resolver = make_event(
            "status",
            content="Debt closed",
            working_on=[],
            metadata={"resolves": [debt["id"]]},
        )
        retro_data = {
            "keep": [],
            "fix": [],
            "try": [
                {
                    "content": "be more careful",
                    "event_refs": [debt["id"]],
                }
            ],
        }
        data = self._run_and_load_with_retro(
            retro_data,
            [debt, resolver] + [make_event(content=f"e{i}") for i in range(4)],
        )
        self.assertTrue(
            data["previous_retros"][0]["try_status"][0]["resolved_this_session"]
        )

    def test_annotate_try_with_unresolved_id_not_flagged(self):
        retro_data = {
            "keep": [],
            "fix": [],
            "try": [{"content": "close debt deadbeef12"}],
        }
        data = self._run_and_load_with_retro(
            retro_data, [make_event(content=f"e{i}") for i in range(6)]
        )
        self.assertFalse(
            data["previous_retros"][0]["try_status"][0]["resolved_this_session"]
        )

    def test_annotate_try_with_no_hex_tokens(self):
        retro_data = {
            "keep": [],
            "fix": [],
            "try": [{"content": "be more careful next session"}],
        }
        data = self._run_and_load_with_retro(
            retro_data, [make_event(content=f"e{i}") for i in range(6)]
        )
        self.assertFalse(
            data["previous_retros"][0]["try_status"][0]["resolved_this_session"]
        )

    def test_annotate_only_most_recent_retro(self):
        debt = make_event("debt", content="Fix later")
        resolver = make_event(
            "status",
            content="Debt closed",
            working_on=[],
            metadata={"resolves": [debt["id"]]},
        )
        short = debt["id"]
        old_retro = {
            "keep": [],
            "fix": [],
            "try": [{"content": f"old mention {short}"}],
        }
        new_retro = {
            "keep": [],
            "fix": [],
            "try": [{"content": f"new mention {short}"}],
        }
        (self.smm_dir / "retrospectives" / "2026-03-09T00-00-00.json").write_text(
            json.dumps(old_retro)
        )
        (self.smm_dir / "retrospectives" / "2026-03-10T00-00-00.json").write_text(
            json.dumps(new_retro)
        )
        import retrospective

        self._write_events(
            [debt, resolver] + [make_event(content=f"e{i}") for i in range(4)]
        )
        retrospective.run(
            {"session_id": "test", "source": "startup"},
            smm_dir=self.smm_dir,
        )
        with open(self.smm_dir / ".retro-input.json") as f:
            data = json.load(f)
        self.assertIn("try_status", data["previous_retros"][0])
        self.assertNotIn("try_status", data["previous_retros"][1])

    def test_annotate_empty_previous_retros(self):
        data = self._run_and_load_with_retro(
            {"keep": [], "fix": [], "try": []},
            [make_event(content=f"e{i}") for i in range(6)],
        )
        self.assertEqual(data["previous_retros"][0]["try_status"], [])

    def test_annotate_no_previous_retros(self):
        import retrospective

        self._write_events([make_event(content=f"e{i}") for i in range(6)])
        retrospective.run(
            {"session_id": "test", "source": "startup"},
            smm_dir=self.smm_dir,
        )
        with open(self.smm_dir / ".retro-input.json") as f:
            data = json.load(f)
        self.assertEqual(data["previous_retros"], [])


if __name__ == "__main__":
    unittest.main()
