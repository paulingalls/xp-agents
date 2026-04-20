#!/usr/bin/env python3
"""Tests for F2 customer_input normalization and truncation.

Split from test_curation.py when that file reached the 500-line target.
Also contains the Story-001 E2E test for all three curation fixes.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import materialize
from conftest import _SMMTestCase, make_event


class TestCustomerInputNormalization(_SMMTestCase):
    """Tests for F2: customer_input normalization and truncation."""

    def _auq_content(self, question: str, answer: str) -> str:
        """Build AskUserQuestion-shaped Python repr content."""
        return str(
            {
                "questions": [
                    {
                        "question": question,
                        "header": "Test",
                        "options": [
                            {"label": answer, "description": "test option"},
                        ],
                        "multiSelect": False,
                    }
                ],
                "answers": {question: answer},
            }
        )

    def test_askuserquestion_normalized(self):
        """AskUserQuestion content re-serialized as Q/A pairs."""
        content = self._auq_content("Pick a color?", "Blue")
        events = [make_event("customer_input", content=content)]
        self._write_events(events)
        result = materialize.prepare_curation_data(self.smm_dir)
        ci = result["new_since_last_curation"]["customer_inputs"][0]
        self.assertNotIn("questions", ci["content"])
        self.assertIn("Q:", ci["content"])
        self.assertIn("Blue", ci["content"])

    def test_askuserquestion_multi_answer(self):
        """Multi-question AskUserQuestion properly serialized."""
        content = str(
            {
                "questions": [
                    {
                        "question": "Mode?",
                        "header": "M",
                        "options": [],
                        "multiSelect": False,
                    },
                    {
                        "question": "Speed?",
                        "header": "S",
                        "options": [],
                        "multiSelect": False,
                    },
                ],
                "answers": {"Mode?": "Fast", "Speed?": "Max"},
            }
        )
        events = [make_event("customer_input", content=content)]
        self._write_events(events)
        result = materialize.prepare_curation_data(self.smm_dir)
        ci = result["new_since_last_curation"]["customer_inputs"][0]
        self.assertIn("Mode?", ci["content"])
        self.assertIn("Fast", ci["content"])
        self.assertIn("Speed?", ci["content"])
        self.assertIn("Max", ci["content"])

    def test_long_prompt_truncated(self):
        """Non-AskUserQuestion content >300 chars truncated."""
        long_content = "x" * 400
        events = [make_event("customer_input", content=long_content)]
        self._write_events(events)
        result = materialize.prepare_curation_data(self.smm_dir)
        ci = result["new_since_last_curation"]["customer_inputs"][0]
        self.assertLessEqual(len(ci["content"]), 300)
        self.assertTrue(ci.get("content_truncated", False))

    def test_short_prompt_not_truncated(self):
        """Content <=300 chars remains unchanged, no truncated flag."""
        short_content = "Build an API for users"
        events = [make_event("customer_input", content=short_content)]
        self._write_events(events)
        result = materialize.prepare_curation_data(self.smm_dir)
        ci = result["new_since_last_curation"]["customer_inputs"][0]
        self.assertEqual(ci["content"], short_content)
        self.assertNotIn("content_truncated", ci)


class TestAllThreeFixes(_SMMTestCase):
    """E2E: all three curation structural fixes applied together."""

    def test_e2e_all_three_fixes(self):
        """F1+F2+F3: resolutions list, normalized customer_inputs, capped tries."""
        concern = make_event("concern", content="Old bug")
        resolver = make_event(
            "status",
            content="Fixed",
            working_on=[],
            metadata={"resolves": [concern["id"]]},
        )
        auq_content = str(
            {
                "questions": [
                    {
                        "question": "Continue?",
                        "header": "Q",
                        "options": [],
                        "multiSelect": False,
                    }
                ],
                "answers": {"Continue?": "Yes"},
            }
        )
        auq_event = make_event("customer_input", content=auq_content)
        long_event = make_event("customer_input", content="y" * 400)

        retros = []
        for i in range(4):
            r = make_event(
                "retrospective",
                content=f"Retro {i}",
                ts=f"2026-01-{i + 1:02d}T00:00:00+00:00",
                keep=[{"content": "ok"}],
                fix=[{"content": "unique"}],
            )
            r["try"] = [
                {"content": f"try-{i}-a"},
                {"content": f"try-{i}-b"},
                {"content": f"try-{i}-c"},
                {"content": f"try-{i}-d"},
            ]
            retros.append(r)
        latest_retro = make_event(
            "retrospective",
            content="Latest",
            ts="2026-02-01T00:00:00+00:00",
            keep=[{"content": "ok"}],
            fix=[{"content": "unique"}],
        )
        latest_retro["try"] = [{"content": "latest-try"}]
        retros.append(latest_retro)

        self._write_events([concern, resolver, auq_event, long_event, *retros])
        result = materialize.prepare_curation_data(self.smm_dir)

        # F1: resolutions is a list
        resolutions = result["new_since_last_curation"]["resolutions"]
        self.assertIsInstance(resolutions, list)
        self.assertIn(concern["id"], resolutions)

        # F2: AskUserQuestion normalized
        ci_auq = next(
            c
            for c in result["new_since_last_curation"]["customer_inputs"]
            if "Continue?" in c["content"]
        )
        self.assertIn("Q:", ci_auq["content"])
        self.assertNotIn("questions", ci_auq["content"])

        # F2: long content truncated
        ci_long = next(
            c
            for c in result["new_since_last_curation"]["customer_inputs"]
            if c.get("content_truncated")
        )
        self.assertLessEqual(len(ci_long["content"]), 300)

        # F3: adopted_tries capped at 10
        adopted = result["retro_history"]["adopted_tries"]
        self.assertLessEqual(len(adopted), 10)


if __name__ == "__main__":
    unittest.main()
