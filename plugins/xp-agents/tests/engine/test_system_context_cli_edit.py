#!/usr/bin/env python3
"""Tests for system_context_cli.py edit-* subcommands.

Edit-* CLIs patch one entry in a capped list and emit a status event
for traceability. Patch is a JSON object on stdin merged into the
existing entry (null clears a key); convention edit takes a JSON-
encoded replacement string. Lookup mirrors retire-*.
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


class TestEditModule(_SMMTestCase):
    """edit-module: lookup by name; patch is JSON dict; null clears key."""

    def test_success_patches_only_named_field(self) -> None:
        write_doc(self.smm_dir, seed_doc("modules", 3))
        result = run_cli(
            _CLI, ["edit-module", "m1"], self.smm_dir, stdin_data='{"purpose": "new"}'
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads((self.smm_dir / SYSTEM_CONTEXT_FILENAME).read_text())
        m1 = next(m for m in data["modules"] if m["name"] == "m1")
        self.assertEqual(m1["purpose"], "new")
        self.assertEqual(m1["path"], "src/m1")  # other fields untouched

    def test_not_found(self) -> None:
        write_doc(self.smm_dir, seed_doc("modules", 3))
        result = run_cli(
            _CLI,
            ["edit-module", "missing"],
            self.smm_dir,
            stdin_data='{"purpose": "new"}',
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("missing", result.stderr)

    def test_invalid_json_refuses(self) -> None:
        write_doc(self.smm_dir, seed_doc("modules", 3))
        result = run_cli(
            _CLI, ["edit-module", "m1"], self.smm_dir, stdin_data="{not valid json"
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Invalid JSON", result.stderr)

    def test_non_object_patch_refuses(self) -> None:
        write_doc(self.smm_dir, seed_doc("modules", 3))
        result = run_cli(
            _CLI, ["edit-module", "m1"], self.smm_dir, stdin_data='"just a string"'
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Patch must be a JSON object", result.stderr)

    def test_validation_failure_refuses(self) -> None:
        """Over-budget purpose (>100 chars) gets rejected by whole-doc validate."""
        write_doc(self.smm_dir, seed_doc("modules", 3))
        over_budget = "x" * 200
        result = run_cli(
            _CLI,
            ["edit-module", "m1"],
            self.smm_dir,
            stdin_data=json.dumps({"purpose": over_budget}),
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Validation error", result.stderr)
        # The pre-edit value must survive
        data = json.loads((self.smm_dir / SYSTEM_CONTEXT_FILENAME).read_text())
        m1 = next(m for m in data["modules"] if m["name"] == "m1")
        self.assertEqual(m1["purpose"], "x")

    def test_emits_status_event_with_patched_keys(self) -> None:
        write_doc(self.smm_dir, seed_doc("modules", 3))
        run_cli(
            _CLI,
            ["edit-module", "m1"],
            self.smm_dir,
            stdin_data='{"purpose": "new purpose"}',
        )
        events = read_events(self.smm_dir)
        edit_events = [
            e for e in events if e.get("metadata", {}).get("action") == "edit_module"
        ]
        self.assertEqual(len(edit_events), 1)
        meta = edit_events[0]["metadata"]
        self.assertEqual(meta["identifier"], "m1")
        self.assertEqual(meta["kind"], "module")
        self.assertEqual(meta["patched_keys"], ["purpose"])


class TestEditPrinciple(_SMMTestCase):
    """edit-principle: lookup by topic; patch is JSON dict."""

    def test_success(self) -> None:
        write_doc(self.smm_dir, seed_doc("principles", 3))
        result = run_cli(
            _CLI,
            ["edit-principle", "t1"],
            self.smm_dir,
            stdin_data='{"decision": "new decision"}',
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads((self.smm_dir / SYSTEM_CONTEXT_FILENAME).read_text())
        p1 = next(p for p in data["principles"] if p["topic"] == "t1")
        self.assertEqual(p1["decision"], "new decision")

    def test_not_found(self) -> None:
        write_doc(self.smm_dir, seed_doc("principles", 3))
        result = run_cli(
            _CLI,
            ["edit-principle", "missing"],
            self.smm_dir,
            stdin_data='{"decision": "x"}',
        )
        self.assertNotEqual(result.returncode, 0)


class TestEditProjectSpecific(_SMMTestCase):
    """edit-project-specific: lookup by name; patch is JSON dict."""

    def test_success(self) -> None:
        write_doc(self.smm_dir, seed_doc("project_specific", 3))
        result = run_cli(
            _CLI,
            ["edit-project-specific", "ps1"],
            self.smm_dir,
            stdin_data='{"content": "new content"}',
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads((self.smm_dir / SYSTEM_CONTEXT_FILENAME).read_text())
        ps1 = next(e for e in data["project_specific"] if e["name"] == "ps1")
        self.assertEqual(ps1["content"], "new content")

    def test_content_overflow_refuses(self) -> None:
        """content > PROJECT_SPECIFIC_CONTENT_MAXLENGTH gets rejected."""
        write_doc(self.smm_dir, seed_doc("project_specific", 3))
        over_budget = "x" * 600
        result = run_cli(
            _CLI,
            ["edit-project-specific", "ps1"],
            self.smm_dir,
            stdin_data=json.dumps({"content": over_budget}),
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Validation error", result.stderr)


class TestEditAcceptanceSurface(_SMMTestCase):
    """edit-acceptance-surface (singular): patch one entry by name.
    Distinct from edit-acceptance-surfaces (plural, whole-array)."""

    def test_status_flip(self) -> None:
        doc = valid_doc()
        doc["acceptance_surfaces"] = seed_doc("acceptance_surfaces", 3)[
            "acceptance_surfaces"
        ]
        write_doc(self.smm_dir, doc)
        # Seed entries are "covered"; flip s1 to "gap"
        result = run_cli(
            _CLI,
            ["edit-acceptance-surface", "s1"],
            self.smm_dir,
            stdin_data='{"status": "gap"}',
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads((self.smm_dir / SYSTEM_CONTEXT_FILENAME).read_text())
        s1 = next(s for s in data["acceptance_surfaces"] if s["name"] == "s1")
        self.assertEqual(s1["status"], "gap")

    def test_not_found(self) -> None:
        doc = valid_doc()
        doc["acceptance_surfaces"] = seed_doc("acceptance_surfaces", 3)[
            "acceptance_surfaces"
        ]
        write_doc(self.smm_dir, doc)
        result = run_cli(
            _CLI,
            ["edit-acceptance-surface", "missing"],
            self.smm_dir,
            stdin_data='{"status": "gap"}',
        )
        self.assertNotEqual(result.returncode, 0)


class TestEditConvention(_SMMTestCase):
    """edit-convention: lookup by index OR substring; stdin is JSON-encoded
    replacement string (NOT a dict patch)."""

    def test_by_index(self) -> None:
        write_doc(self.smm_dir, seed_doc("conventions", 5))
        result = run_cli(
            _CLI,
            ["edit-convention", "2"],
            self.smm_dir,
            stdin_data='"replaced text"',
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads((self.smm_dir / SYSTEM_CONTEXT_FILENAME).read_text())
        self.assertEqual(data["conventions"][2], "replaced text")
        self.assertEqual(len(data["conventions"]), 5)  # no insertion/deletion

    def test_by_substring(self) -> None:
        doc = valid_doc()
        doc["conventions"] = [
            "Use type hints",
            "Prefer pathlib over os.path",
            "Atomic writes via tempfile + rename",
        ]
        write_doc(self.smm_dir, doc)
        result = run_cli(
            _CLI,
            ["edit-convention", "pathlib"],
            self.smm_dir,
            stdin_data='"Prefer pathlib for all path manipulation"',
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads((self.smm_dir / SYSTEM_CONTEXT_FILENAME).read_text())
        self.assertIn("Prefer pathlib for all path manipulation", data["conventions"])
        self.assertNotIn("Prefer pathlib over os.path", data["conventions"])

    def test_ambiguous_substring_refuses(self) -> None:
        doc = valid_doc()
        doc["conventions"] = [
            "Use type hints",
            "Use pathlib",
            "Use atomic writes",
        ]
        write_doc(self.smm_dir, doc)
        result = run_cli(
            _CLI, ["edit-convention", "Use"], self.smm_dir, stdin_data='"new"'
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ambiguous", result.stderr.lower())

    def test_non_string_stdin_refuses(self) -> None:
        """Object-shaped stdin to convention edit is rejected with a clear msg."""
        write_doc(self.smm_dir, seed_doc("conventions", 3))
        result = run_cli(
            _CLI,
            ["edit-convention", "0"],
            self.smm_dir,
            stdin_data='{"text": "new"}',
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("must be a JSON string", result.stderr)

    def test_emits_status_event_with_original_text(self) -> None:
        doc = valid_doc()
        doc["conventions"] = [
            "Use type hints",
            "Prefer pathlib over os.path",
        ]
        write_doc(self.smm_dir, doc)
        run_cli(
            _CLI,
            ["edit-convention", "pathlib"],
            self.smm_dir,
            stdin_data='"Prefer pathlib for all path manipulation"',
        )
        events = read_events(self.smm_dir)
        edit_events = [
            e
            for e in events
            if e.get("metadata", {}).get("action") == "edit_convention"
        ]
        self.assertEqual(len(edit_events), 1)
        # identifier is the ORIGINAL text (resolved before replacement)
        self.assertEqual(
            edit_events[0]["metadata"]["identifier"],
            "Prefer pathlib over os.path",
        )


class TestEditNullClearsKey(_SMMTestCase):
    """null in a patch removes the key — mirrors edit-stack-field precedent."""

    def test_null_clears_optional_key(self) -> None:
        """principle.rationale is optional; setting it null removes it."""
        doc = valid_doc()
        doc["principles"] = [
            {"topic": "lang", "decision": "Python", "rationale": "ecosystem fit"}
        ]
        write_doc(self.smm_dir, doc)
        result = run_cli(
            _CLI,
            ["edit-principle", "lang"],
            self.smm_dir,
            stdin_data='{"rationale": null}',
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads((self.smm_dir / SYSTEM_CONTEXT_FILENAME).read_text())
        p = data["principles"][0]
        self.assertNotIn("rationale", p)
        self.assertEqual(p["decision"], "Python")  # other fields preserved


if __name__ == "__main__":
    unittest.main()
