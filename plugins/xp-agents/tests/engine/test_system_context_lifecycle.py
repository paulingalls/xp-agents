#!/usr/bin/env python3
"""End-to-end lifecycle: legacy on-disk file -> canonicalized load ->
render -> add (soft/hard cap) -> retire."""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from _system_context_fixtures import read_events, seed_doc, valid_doc, write_doc
from conftest import _SMMTestCase, run_cli
from event_metadata import STATUS_ACTION_RETIRE_PRINCIPLE
from system_context_schema import (
    PRINCIPLES_HARD_CAP,
    PRINCIPLES_SOFT_CAP,
    SYSTEM_CONTEXT_FILENAME,
)
from system_context_store import load_system_context, save_system_context

_CLI = Path(__file__).parent.parent.parent / "smm" / "system_context_cli.py"


def _legacy_doc() -> dict:
    """Pre-M1 on-disk shape: top-level `key_decisions` + `sources`."""
    doc = valid_doc()
    doc["key_decisions"] = doc.pop("principles")
    doc["sources"] = [
        {"label": "Design doc", "location": "docs/design.md", "type": "repo"}
    ]
    return doc


class TestLegacyLoadCanonicalizes(_SMMTestCase):
    def test_load_renames_key_decisions_and_drops_sources(self) -> None:
        legacy = _legacy_doc()
        write_doc(self.smm_dir, legacy)

        data = self._assert_not_none(load_system_context(self.smm_dir))

        self.assertIn("principles", data)
        self.assertNotIn("key_decisions", data)
        self.assertNotIn("sources", data)
        self.assertEqual(data["principles"], legacy["key_decisions"])

    def test_save_after_load_persists_canonical_shape_on_disk(self) -> None:
        write_doc(self.smm_dir, _legacy_doc())

        data = self._assert_not_none(load_system_context(self.smm_dir))
        save_system_context(self.smm_dir, data)

        raw = json.loads((self.smm_dir / SYSTEM_CONTEXT_FILENAME).read_text())
        self.assertIn("principles", raw)
        self.assertNotIn("key_decisions", raw)
        self.assertNotIn("sources", raw)


class TestRenderShowsPrinciples(_SMMTestCase):
    def test_render_against_legacy_file_emits_principles_header(self) -> None:
        write_doc(self.smm_dir, _legacy_doc())

        result = run_cli(_CLI, ["render"], self.smm_dir)

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("## Principles", result.stdout)
        self.assertNotIn("## Key Decisions", result.stdout)
        self.assertNotIn("## Sources", result.stdout)


class TestAddPrincipleSoftCap(_SMMTestCase):
    def test_add_at_soft_cap_threshold_warns_to_stderr(self) -> None:
        write_doc(self.smm_dir, seed_doc("principles", PRINCIPLES_SOFT_CAP - 1))
        new = json.dumps({"topic": "edge", "decision": "land at soft cap"})

        result = run_cli(_CLI, ["add-principle"], self.smm_dir, stdin_data=new)

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn(
            f"principles approaching cap ({PRINCIPLES_SOFT_CAP}/{PRINCIPLES_HARD_CAP})",
            result.stderr,
        )


class TestAddPrincipleHardCap(_SMMTestCase):
    def test_add_at_hard_cap_refuses_nonzero_with_retire_hint(self) -> None:
        write_doc(self.smm_dir, seed_doc("principles", PRINCIPLES_HARD_CAP))
        new = json.dumps({"topic": "overflow", "decision": "should be refused"})

        result = run_cli(_CLI, ["add-principle"], self.smm_dir, stdin_data=new)

        self.assertEqual(result.returncode, 1)
        self.assertIn(
            f"principles hard cap reached "
            f"({PRINCIPLES_HARD_CAP}/{PRINCIPLES_HARD_CAP})",
            result.stderr,
        )
        self.assertIn("run retire-principle first", result.stderr)


class TestRetirePrinciple(_SMMTestCase):
    def test_retire_removes_entry_and_emits_status_event(self) -> None:
        doc = valid_doc()
        doc["principles"] = [
            {"topic": "alpha", "decision": "first"},
            {"topic": "beta", "decision": "second"},
        ]
        write_doc(self.smm_dir, doc)

        result = run_cli(_CLI, ["retire-principle", "alpha"], self.smm_dir)

        self.assertEqual(result.returncode, 0, msg=result.stderr)

        after = json.loads((self.smm_dir / SYSTEM_CONTEXT_FILENAME).read_text())
        topics = [p["topic"] for p in after["principles"]]
        self.assertEqual(topics, ["beta"])
        self.assertNotIn("key_decisions", after)
        self.assertNotIn("sources", after)

        events = read_events(self.smm_dir)
        retire_events = [
            e
            for e in events
            if e.get("metadata", {}).get("action") == STATUS_ACTION_RETIRE_PRINCIPLE
        ]
        self.assertEqual(len(retire_events), 1)
        self.assertEqual(retire_events[0]["metadata"]["identifier"], "alpha")


if __name__ == "__main__":
    unittest.main()
