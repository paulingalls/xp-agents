#!/usr/bin/env python3
"""Tests for system_context_cli.py retire-* subcommands.

Extracted from test_system_context_cli.py to keep that file under the
500-line target. Shares the same fixtures (_system_context_fixtures)
and base class (_SMMTestCase from conftest).
"""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from _system_context_fixtures import read_events, seed_doc, valid_doc, write_doc
from conftest import _SMMTestCase, run_cli
from system_context_schema import SYSTEM_CONTEXT_FILENAME

_CLI = Path(__file__).parent.parent.parent / "smm" / "system_context_cli.py"


class TestRetireCommands(_SMMTestCase):
    """Retire-* CLIs remove an entry from a capped list and emit a status
    event so curation is traceable. Hard delete only — provenance survives
    in the original decision event."""

    # ── retire-principle (by topic) ────────────────────────────

    def test_retire_principle_success(self) -> None:
        write_doc(self.smm_dir, seed_doc("principles", 3))
        result = run_cli(_CLI, ["retire-principle", "t1"], self.smm_dir)
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads((self.smm_dir / SYSTEM_CONTEXT_FILENAME).read_text())
        self.assertEqual(len(data["principles"]), 2)
        self.assertNotIn("t1", [p["topic"] for p in data["principles"]])

    def test_retire_principle_not_found(self) -> None:
        write_doc(self.smm_dir, seed_doc("principles", 3))
        result = run_cli(_CLI, ["retire-principle", "missing"], self.smm_dir)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("missing", result.stderr)
        data = json.loads((self.smm_dir / SYSTEM_CONTEXT_FILENAME).read_text())
        self.assertEqual(len(data["principles"]), 3)

    def test_retire_principle_emits_status_event(self) -> None:
        write_doc(self.smm_dir, seed_doc("principles", 3))
        run_cli(_CLI, ["retire-principle", "t1"], self.smm_dir)
        events = read_events(self.smm_dir)
        retire_events = [
            e
            for e in events
            if e.get("metadata", {}).get("action") == "retire_principle"
        ]
        self.assertEqual(len(retire_events), 1)
        self.assertEqual(retire_events[0]["metadata"]["identifier"], "t1")
        self.assertEqual(retire_events[0]["metadata"]["kind"], "principle")

    # ── retire-module (by name) ────────────────────────────────

    def test_retire_module_success(self) -> None:
        write_doc(self.smm_dir, seed_doc("modules", 3))
        result = run_cli(_CLI, ["retire-module", "m1"], self.smm_dir)
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads((self.smm_dir / SYSTEM_CONTEXT_FILENAME).read_text())
        self.assertEqual(len(data["modules"]), 2)
        self.assertNotIn("m1", [m["name"] for m in data["modules"]])

    def test_retire_module_not_found(self) -> None:
        write_doc(self.smm_dir, seed_doc("modules", 3))
        result = run_cli(_CLI, ["retire-module", "missing"], self.smm_dir)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("missing", result.stderr)

    def test_retire_module_emits_status_event(self) -> None:
        write_doc(self.smm_dir, seed_doc("modules", 3))
        run_cli(_CLI, ["retire-module", "m1"], self.smm_dir)
        events = read_events(self.smm_dir)
        retire_events = [
            e for e in events if e.get("metadata", {}).get("action") == "retire_module"
        ]
        self.assertEqual(len(retire_events), 1)
        self.assertEqual(retire_events[0]["metadata"]["identifier"], "m1")

    # ── retire-project-specific (by name) ──────────────────────

    def test_retire_project_specific_success(self) -> None:
        write_doc(self.smm_dir, seed_doc("project_specific", 3))
        result = run_cli(_CLI, ["retire-project-specific", "ps1"], self.smm_dir)
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads((self.smm_dir / SYSTEM_CONTEXT_FILENAME).read_text())
        self.assertEqual(len(data["project_specific"]), 2)
        self.assertNotIn("ps1", [e["name"] for e in data["project_specific"]])

    def test_retire_project_specific_not_found(self) -> None:
        write_doc(self.smm_dir, seed_doc("project_specific", 3))
        result = run_cli(_CLI, ["retire-project-specific", "missing"], self.smm_dir)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("missing", result.stderr)

    def test_retire_project_specific_emits_status_event(self) -> None:
        write_doc(self.smm_dir, seed_doc("project_specific", 3))
        run_cli(_CLI, ["retire-project-specific", "ps1"], self.smm_dir)
        events = read_events(self.smm_dir)
        retire_events = [
            e
            for e in events
            if e.get("metadata", {}).get("action") == "retire_project_specific"
        ]
        self.assertEqual(len(retire_events), 1)
        self.assertEqual(retire_events[0]["metadata"]["identifier"], "ps1")

    # ── retire-acceptance-surface (by name) ────────────────────

    def test_retire_acceptance_surface_success(self) -> None:
        doc = valid_doc()
        doc["acceptance_surfaces"] = seed_doc("acceptance_surfaces", 3)[
            "acceptance_surfaces"
        ]
        write_doc(self.smm_dir, doc)
        result = run_cli(_CLI, ["retire-acceptance-surface", "s1"], self.smm_dir)
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads((self.smm_dir / SYSTEM_CONTEXT_FILENAME).read_text())
        self.assertEqual(len(data["acceptance_surfaces"]), 2)
        self.assertNotIn("s1", [s["name"] for s in data["acceptance_surfaces"]])

    def test_retire_acceptance_surface_not_found(self) -> None:
        doc = valid_doc()
        doc["acceptance_surfaces"] = seed_doc("acceptance_surfaces", 3)[
            "acceptance_surfaces"
        ]
        write_doc(self.smm_dir, doc)
        result = run_cli(_CLI, ["retire-acceptance-surface", "missing"], self.smm_dir)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("missing", result.stderr)

    def test_retire_acceptance_surface_emits_status_event(self) -> None:
        doc = valid_doc()
        doc["acceptance_surfaces"] = seed_doc("acceptance_surfaces", 3)[
            "acceptance_surfaces"
        ]
        write_doc(self.smm_dir, doc)
        run_cli(_CLI, ["retire-acceptance-surface", "s1"], self.smm_dir)
        events = read_events(self.smm_dir)
        retire_events = [
            e
            for e in events
            if e.get("metadata", {}).get("action") == "retire_acceptance_surface"
        ]
        self.assertEqual(len(retire_events), 1)
        self.assertEqual(retire_events[0]["metadata"]["identifier"], "s1")

    # ── retire-convention (by index or substring) ──────────────

    def test_retire_convention_by_integer_index(self) -> None:
        write_doc(self.smm_dir, seed_doc("conventions", 5))
        result = run_cli(_CLI, ["retire-convention", "2"], self.smm_dir)
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads((self.smm_dir / SYSTEM_CONTEXT_FILENAME).read_text())
        self.assertEqual(len(data["conventions"]), 4)
        self.assertNotIn("c2", data["conventions"])

    def test_retire_convention_integer_index_out_of_range(self) -> None:
        write_doc(self.smm_dir, seed_doc("conventions", 3))
        result = run_cli(_CLI, ["retire-convention", "99"], self.smm_dir)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("out of range", result.stderr)
        data = json.loads((self.smm_dir / SYSTEM_CONTEXT_FILENAME).read_text())
        self.assertEqual(len(data["conventions"]), 3)

    def test_retire_convention_by_substring(self) -> None:
        doc = valid_doc()
        doc["conventions"] = [
            "Use type hints",
            "Prefer pathlib over os.path",
            "Atomic writes via tempfile + rename",
        ]
        write_doc(self.smm_dir, doc)
        result = run_cli(_CLI, ["retire-convention", "pathlib"], self.smm_dir)
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads((self.smm_dir / SYSTEM_CONTEXT_FILENAME).read_text())
        self.assertEqual(len(data["conventions"]), 2)
        self.assertNotIn("Prefer pathlib over os.path", data["conventions"])

    def test_retire_convention_ambiguous_substring_refuses(self) -> None:
        doc = valid_doc()
        doc["conventions"] = [
            "Use type hints",
            "Use pathlib",
            "Use atomic writes",
        ]
        write_doc(self.smm_dir, doc)
        result = run_cli(_CLI, ["retire-convention", "Use"], self.smm_dir)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ambiguous", result.stderr.lower())
        data = json.loads((self.smm_dir / SYSTEM_CONTEXT_FILENAME).read_text())
        self.assertEqual(len(data["conventions"]), 3)

    def test_retire_convention_emits_status_event_with_resolved_text(self) -> None:
        doc = valid_doc()
        doc["conventions"] = [
            "Use type hints",
            "Prefer pathlib over os.path",
            "Atomic writes via tempfile + rename",
        ]
        write_doc(self.smm_dir, doc)
        run_cli(_CLI, ["retire-convention", "pathlib"], self.smm_dir)
        events = read_events(self.smm_dir)
        retire_events = [
            e
            for e in events
            if e.get("metadata", {}).get("action") == "retire_convention"
        ]
        self.assertEqual(len(retire_events), 1)
        self.assertEqual(
            retire_events[0]["metadata"]["identifier"],
            "Prefer pathlib over os.path",
        )


if __name__ == "__main__":
    unittest.main()
