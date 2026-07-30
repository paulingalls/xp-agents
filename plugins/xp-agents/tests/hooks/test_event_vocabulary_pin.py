#!/usr/bin/env python3
"""Doctrinal pin: forbid bare event-type literals in tests/.

After the M-6a vocabulary sweep, every `make_event(...)` call and every
`{"type": "<bare>"}` dict literal under `plugins/xp-agents/tests/` should
use the `EVENT_TYPE_*` constants from `event_schema`. This pin walks the
test tree via AST and fails on any regression — a future
`make_event("concern", ...)` call fails at test-collection time with a
file:line:value report instead of slipping past grep three sprints later.

Mirrors the `TestEventTypeMatchCompleteness` pattern in
`tests/engine/test_compact.py` (which guards production match-blocks).
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

from _event_vocabulary_walker import (
    TESTS_ROOT,
    _count_event_type_sites_in_tree,
    _files_to_scan,
    _rel,
    _scan_root,
)
from _pin_helpers import parse_files, scan_shortfalls

# Files allowlisted from the pin. Each entry's value must justify why the
# bare literal is intentional — auditable via grep on this dict.
# Justification non-emptiness is enforced by test_allowlist_entries_have_justifications.
ALLOWLIST: dict[str, str] = {
    # test_event_schema.py asserts the literal strings of VALID_TYPES;
    # those tests verify the strings themselves, not behavior built on them.
    "plugins/xp-agents/tests/smm/test_event_schema.py": (
        "VALID_TYPES string assertions intentionally pin the literals"
    ),
    # SMM pillar 'type' field uses smm_schema.VALID_INTENT_TYPES,
    # a vocabulary disjoint from event_schema.VALID_TYPES that happens
    # to share the literal 'goal'. Bare 'goal' values for intent items
    # in this file are smm_schema-domain, not event_schema-domain — the
    # pin should not flag them if they ever appear in a Call/Dict shape.
    "plugins/xp-agents/tests/smm/test_smm_cli.py": (
        "smm_schema.VALID_INTENT_TYPES is a distinct vocabulary from "
        "event_schema.VALID_TYPES; bare 'goal' for SMM pillar 'type' "
        "is intentionally domain-specific"
    ),
    "plugins/xp-agents/tests/smm/test_smm_store.py": (
        "smm_schema.VALID_INTENT_TYPES is a distinct vocabulary from "
        "event_schema.VALID_TYPES; bare 'goal' for SMM pillar 'type' "
        "in test_roundtrip_preserves_all_fields is intentionally domain-specific"
    ),
}


class TestEventVocabularyPin(unittest.TestCase):
    """No test_*.py file under tests/ may contain a bare event-type
    literal in a make_event call or `{"type": ...}` dict literal.

    A future regression fails this test at collection time with a precise
    file:line:value report.
    """

    def test_no_bare_event_type_literals_in_tests(self) -> None:
        violations_by_path, parse_failures = _scan_root(TESTS_ROOT)

        if parse_failures:
            lines = [f"  {_rel(p)}: {err}" for p, err in sorted(parse_failures)]
            self.fail(
                f"{len(parse_failures)} file(s) failed to parse -- the scan "
                f"cannot prove them clean:\n" + "\n".join(lines)
            )

        violations = {
            _rel(p): vs
            for p, vs in violations_by_path.items()
            if _rel(p) not in ALLOWLIST
        }

        if violations:
            lines = [
                f"  {path}:{ln}: bare event-type literal "
                f"'{val}' in {kind}; use EVENT_TYPE_{val.upper()}"
                for path, vs in sorted(violations.items())
                for ln, val, kind in vs
            ]
            self.fail(
                f"{len(violations)} file(s) contain bare event-type "
                f"literals — M-6a sweep regression:\n" + "\n".join(lines)
            )

    def test_allowlist_entries_have_justifications(self) -> None:
        """Every ALLOWLIST entry must have a non-empty justification string —
        prevents `"file.py": ""` slipping in and silently disabling the pin
        for that file. Read at test time so a future bare-empty entry fails
        immediately.
        """
        for path, justification in ALLOWLIST.items():
            self.assertTrue(
                justification.strip(),
                msg=f"ALLOWLIST['{path}'] has empty justification",
            )

    def test_files_to_scan_includes_underscore_helpers(self) -> None:
        """`_*.py` helper modules (e.g., `_event_fixtures.py`) must be
        scanned — they're test-tree code that imports `make_event` and
        was the escape route for pre-sweep regressions in sprint-060.
        """
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "test_a.py").write_text("# test\n")
            (root / "_event_fixtures.py").write_text("# helper\n")
            (root / "_close_fixtures.py").write_text("# helper\n")
            scanned = {p.name for p in _files_to_scan(root)}
            self.assertIn("_event_fixtures.py", scanned)
            self.assertIn("_close_fixtures.py", scanned)
            self.assertIn("test_a.py", scanned)

    def test_files_to_scan_includes_dunder_init(self) -> None:
        """`__init__.py` is now INCLUDED -- story-001 removed the name-shape
        carve-out (name-shape filtering itself is gone; every .py file is
        admitted). Excluding `__init__.py` was a name-shape exemption
        living inside the very change whose point was ending name-shape
        exemptions -- the same hole in miniature. Every real `__init__.py`
        in the tree today is 0 bytes, so including them costs nothing, but
        one with content later is no longer silently exempt.
        """
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "__init__.py").write_text("")
            (root / "_helper.py").write_text("# helper\n")
            scanned = {p.name for p in _files_to_scan(root)}
            self.assertIn("__init__.py", scanned)
            self.assertIn("_helper.py", scanned)

    def test_files_to_scan_includes_non_name_shaped_modules(self) -> None:
        """A module matching none of the legacy test_*/_*/conftest.py
        shapes (e.g. a shared test-base module like
        tests/engine/sister_test_base.py) is scanned -- `files_to_scan`
        admits every .py file now, not just name-shaped ones.
        """
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "shared_test_base.py").write_text("# shared base\n")
            scanned = {p.name for p in _files_to_scan(root)}
            self.assertIn("shared_test_base.py", scanned)

    def test_files_to_scan_includes_conftest_at_any_depth(self) -> None:
        """`conftest.py` files must be included at any depth — pytest
        loads nested conftests (e.g., `tests/hooks/conftest.py`) and a
        future addition there with bare event-type literals must trip
        the pin.
        """
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "conftest.py").write_text("# root conftest\n")
            (root / "test_a.py").write_text("# test\n")
            nested = root / "hooks"
            nested.mkdir()
            (nested / "conftest.py").write_text("# nested conftest\n")
            scanned = {p.relative_to(root).as_posix() for p in _files_to_scan(root)}
            self.assertIn("conftest.py", scanned)
            self.assertIn("hooks/conftest.py", scanned)

    def test_files_to_scan_excludes_pin_file_itself(self) -> None:
        """The pin file is in `tests/hooks/test_*.py` and would otherwise
        match the glob. Excluding it keeps the pin self-isolating —
        the pin asserts other files, not itself.
        """
        scanned = _files_to_scan(TESTS_ROOT)
        scanned_resolved = {p.resolve() for p in scanned}
        self.assertNotIn(Path(__file__).resolve(), scanned_resolved)


class TestPinIsNotVacuous(unittest.TestCase):
    """See test_env_patch_cleanup_pin.py's TestPinIsNotVacuous -- same
    guardrail against a scan that reports clean because it could not look."""

    def test_scan_has_no_shortfalls(self) -> None:
        shortfalls = scan_shortfalls(
            _files_to_scan(TESTS_ROOT),
            TESTS_ROOT,
            min_files=400,
            exclude_self=Path(__file__),
        )
        self.assertEqual(shortfalls, [])

    def test_scan_examines_a_nontrivial_number_of_event_type_sites(self) -> None:
        trees, parse_failures = parse_files(_files_to_scan(TESTS_ROOT))
        self.assertEqual(
            parse_failures,
            [],
            msg=f"{len(parse_failures)} file(s) failed to parse: {parse_failures}",
        )
        total = sum(_count_event_type_sites_in_tree(tree) for _, tree in trees)
        self.assertGreaterEqual(
            total,
            1000,
            msg=(
                f"only {total} event-type sites found -- the "
                f"detection shape may have gone blind"
            ),
        )

    def test_pin_fails_loudly_on_an_unparsable_file(self) -> None:
        """A file the scan cannot parse must be reported as its own
        signal -- neither a violation nor silently clean. Genuinely red
        only because `_scan_root` takes a root parameter."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "test_broken.py").write_text("def broken(:\n")
            violations, parse_failures = _scan_root(root)
            self.assertEqual(violations, {})
            self.assertEqual(len(parse_failures), 1)
            failed_path, _err = parse_failures[0]
            self.assertEqual(failed_path.name, "test_broken.py")


if __name__ == "__main__":
    unittest.main()
