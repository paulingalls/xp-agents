#!/usr/bin/env python3
"""Doctrinal pin: forbid `patch.dict(os.environ, ...)` cleanup that outlives
`tearDown` under xdist.

Debt eaf94a1afefc. `self.enterContext(patch.dict(os.environ, ...))` and the
`addCleanup`-of-a-detached-patcher shape both register cleanup that unittest
runs AFTER `tearDown` returns. On an xdist worker that reuses the process
across tests, `patch.dict`'s exit restores the *whole* `os.environ` mapping
as it stood at entry -- including `SMM_DIR`, which `tearDown` had already
popped. The next test in that worker then reads a `SMM_DIR` pointing at a
deleted temp directory.

This was fixed once with a prose warning left at the site (see the class
docstring in `test_heartbeat_writers.py`) and reintroduced 35 lines away in
the SAME file within the hour. A prose warning is the wrong guard for a
mechanically detectable AST shape; this pin is the mechanical guard.

THE RULE. A `patch.dict` call whose first argument is `os.environ` is safe
only in a position whose cleanup is bounded by the test method:

    with patch.dict(os.environ, ...):            safe -- exits in the body
    with (patch.dict(os.environ, ...), other()):  safe -- same, multi-item
    @patch.dict(os.environ, ...)                  safe -- scoped to the method
    @patch.dict(os.environ, ...) on a class       safe -- mock's decorate_class
    class T(TestCase):                            wraps each test* method
    def helper():
        return patch.dict(os.environ, ...)        safe -- caller's `with` bounds it
    self._p = patch.dict(os.environ, ...)          safe -- ONLY IF self._p.stop()
    # in setUp, self._p.start()                    is CALLED inside a tearDown
    # in tearDown, self._p.stop()                  in the same class
    anything else                                  FLAGGED

The class-decorator row is per-test-method, not per-class: `decorate_class`
wraps only attributes named `test*`, so `setUp`/`tearDown` do NOT see the
patched values and the restore lands inside each test. The `self._p` row
covers both `self._p = ...` and the annotated `self._p: X = ...` spelling.

THE DISCRIMINATOR for the last safe row: `.stop()` must be *called* inside
`tearDown`, not merely hand off `.stop` to `addCleanup` (`addCleanup` fires
after `tearDown`, which is exactly the bug). Get this precise, or the pin
either misses `enterContext`/`addCleanup` reintroduced under a self-attr
disguise, or flags the legitimate `test_worktree_removal.py`-style pattern
this row exists to allow.

Fail-closed by design: anything not matching an enumerated safe row is
flagged, including shapes nobody has written yet.

HELPER INDIRECTION. A local helper that itself `return`s a safe
`patch.dict(os.environ, ...)` (safe by the `return` row above) can still be
misused by its CALLER: `self.enterContext(helper())` re-introduces the exact
bug through one layer of indirection. Catching this needs a within-module
pass: collect names of functions that `return` an env patcher, then flag any
`self.enterContext(...)`/`self.addCleanup(...)` call whose argument is a
call to one of those names. One real helper in the tree today
(`test_tdd_gate_in_place_teammate.py`'s `_in_place_env`) is consumed safely,
via `with self._in_place_env():`, in the same module -- so within-module
scope is sufficient; nothing here resolves a helper imported from elsewhere.

ALIASED IMPORTS are handled: `_patch_name_aliases` collects every local name
bound to `patch` by an `import from unittest.mock`/`mock`, so
`from unittest.mock import patch as p` then `p.dict(os.environ, ...)` is
matched. The matcher is not keyed on the literal name.

WHERE THE PIECES LIVE. The scanner this runs is `_env_patch_walker`; the proof
that it fires, and the proof that it does not over-fire, are
`test_env_patch_walker_flags.py` and `test_env_patch_walker_allows.py`. This
module is the tree-wide assertion and its anti-vacuity guard, nothing else.

KNOWN GAPS (the remainder of debt 8dffcbf90181): a helper defined in one
module but called from another evades the within-module indirection pass --
still open after the split that was meant to carry it, because detecting it
needs whole-tree state outside any matcher and the split was a pure move.
Plain rebinding (`p = patch`) also
stays invisible: alias collection reads import statements, not assignments.
This pin is a floor, not total coverage. It is also not a total guard on
the safe rows it does bless:
unittest skips `tearDown` when `setUp` raises after `.start()`, so the
setUp-start/tearDown-stop row accepts that one leak window (assumption
37b2549e1a65).
"""

import ast
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

from _env_patch_walker import (
    TESTS_ROOT,
    _files_to_scan,
    _is_env_patch_call,
    _patch_name_aliases,
    _rel,
    _scan_file,
    _scan_root,
)
from _pin_helpers import parse_files, scan_shortfalls

# Files allowlisted from the pin. Each entry's value must justify why the
# unbounded patch.dict is intentional -- auditable via grep on this dict.
# Deliberately empty: the tree passes this pin outright (AC#5). Keying an
# allowlist on whole file path would exempt the entire file the debt's
# reintroduction actually happened in -- exactly the failure mode this pin
# exists to catch. If you're adding an entry here, the rule is wrong; fix
# the rule instead.
ALLOWLIST: dict[str, str] = {}


# ---------------------------------------------------------------------------
# The pin
# ---------------------------------------------------------------------------


class TestEnvPatchCleanupPin(unittest.TestCase):
    """No unbounded patch.dict(os.environ, ...) cleanup in tests/."""

    def test_no_env_patch_cleanup_leaks_in_tests(self) -> None:
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
                f"  {path}:{ln}: {reason}"
                for path, vs in sorted(violations.items())
                for ln, reason in vs
            ]
            self.fail(
                f"{sum(len(v) for v in violations.values())} unbounded "
                f"patch.dict(os.environ, ...) cleanup site(s) found:\n"
                + "\n".join(lines)
            )

    def test_allowlist_entries_have_justifications(self) -> None:
        for path, justification in ALLOWLIST.items():
            self.assertTrue(
                justification.strip(),
                msg=f"ALLOWLIST['{path}'] has empty justification",
            )


# ---------------------------------------------------------------------------
# Anti-vacuity
# ---------------------------------------------------------------------------


class TestPinIsNotVacuous(unittest.TestCase):
    """A pin over an empty or near-empty population passes forever and
    proves nothing -- see CLAUDE.md's project-agnostic guardrail case study
    and this story's own debt bcbca... reintroduction history."""

    def test_scan_visits_a_nontrivial_number_of_files(self) -> None:
        scanned = _files_to_scan(TESTS_ROOT)
        self.assertGreaterEqual(
            len(scanned),
            400,
            msg=(
                f"only {len(scanned)} files scanned -- check "
                f"_pin_helpers.files_to_scan and TESTS_ROOT"
            ),
        )

    def test_scan_has_no_shortfalls(self) -> None:
        shortfalls = scan_shortfalls(
            _files_to_scan(TESTS_ROOT),
            TESTS_ROOT,
            min_files=400,
            exclude_self=Path(__file__),
        )
        self.assertEqual(shortfalls, [])

    def test_scan_shortfalls_names_a_deliberately_narrowed_scan(self) -> None:
        """Red proof for `scan_shortfalls` itself -- the real tree cannot
        witness this leg post-widening (the legacy set is a subset of the
        widened one by construction), so this hand-narrows the input."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "test_a.py").write_text("# test\n")
            (root / "test_b.py").write_text("# test\n")
            full_scan = [root / "test_a.py", root / "test_b.py"]
            self.assertEqual(scan_shortfalls(full_scan, root, min_files=0), [])

            narrowed = [root / "test_a.py"]
            shortfalls = scan_shortfalls(narrowed, root, min_files=0)
            self.assertEqual(len(shortfalls), 1)
            self.assertIn("test_b.py", shortfalls[0])

    def test_scan_shortfalls_flags_a_low_floor(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "test_a.py").write_text("# test\n")
            scanned = [root / "test_a.py"]
            shortfalls = scan_shortfalls(scanned, root, min_files=5)
            self.assertEqual(len(shortfalls), 1)
            self.assertIn("expected at least 5", shortfalls[0])

    def test_scan_examines_a_nontrivial_number_of_call_sites(self) -> None:
        trees, parse_failures = parse_files(_files_to_scan(TESTS_ROOT))
        self.assertEqual(
            parse_failures,
            [],
            msg=f"{len(parse_failures)} file(s) failed to parse: {parse_failures}",
        )
        total = 0
        for _, tree in trees:
            aliases = _patch_name_aliases(tree)
            total += sum(1 for n in ast.walk(tree) if _is_env_patch_call(n, aliases))
        self.assertGreaterEqual(
            total,
            100,
            msg=(
                f"only {total} patch.dict(os.environ, ...) call sites found "
                f"-- the detection shape may have gone blind"
            ),
        )

    def test_shipped_code_is_not_scanned(self) -> None:
        """The pin scans plugins/xp-agents/tests/ only -- it must never
        reach scripts/, smm/, or skills/*/scripts, which ship to users and
        are covered by a different, language-agnostic pin instead."""
        rels = [_rel(p) for p in _files_to_scan(TESTS_ROOT)]
        self.assertTrue(rels)
        self.assertTrue(all("/tests/" in r for r in rels))

    def test_pin_fails_loudly_on_an_unparsable_file(self) -> None:
        """A file the scan cannot parse must be reported as its own
        signal -- neither a violation nor silently clean. This is a
        genuine red test only because `_scan_root` takes a root
        parameter: the module-constant-only loop this replaces could
        never be pointed at a temp dir to prove it."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "test_broken.py").write_text("def broken(:\n")
            violations, parse_failures = _scan_root(root)
            self.assertEqual(violations, {})
            self.assertEqual(len(parse_failures), 1)
            failed_path, _err = parse_failures[0]
            self.assertEqual(failed_path.name, "test_broken.py")

    def test_pin_can_actually_fail(self) -> None:
        """The main pin test asserts zero violations on the real tree, which
        is indistinguishable from a scanner that never runs. Prove the
        scanner fires by pointing it at the same real-world violation shape
        pinned in TestWalkerDetectsViolations, outside TESTS_ROOT."""
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td) / "test_violation.py"
            tmp.write_text(
                "import os\n"
                "import unittest\n"
                "from unittest.mock import patch\n"
                "class T(unittest.TestCase):\n"
                "    def test_x(self):\n"
                '        self.enterContext(patch.dict(os.environ, {"X": "1"}))\n'
            )
            self.assertNotEqual(_scan_file(tmp), [])


if __name__ == "__main__":
    unittest.main()
