#!/usr/bin/env python3
"""Red proofs for the size gate: each leg, shown to actually go red.

Extracted from `test_file_size_pin.py` at that file's own instruction — its
ceiling note named these four classes as the cohesive group to take out next,
because they share a temp-tree idiom and touch no real-tree state at all. The
pin file crossed the 500-line cap while gaining the JavaScript leg, and taking
the extraction it had already identified is what a cap is FOR: it forced the
split rather than another raise.

Why these proofs exist at all: every leg in the pin file asserts an empty list
against a healthy tree, and an empty list is exactly what a scan that has
collapsed to nothing also returns. A green real-tree leg therefore cannot tell
"nothing is wrong" from "nothing was looked at". Each class below builds a
deliberately broken tree and asserts the corresponding leg NOTICES.
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from _pin_helpers import (
    shipped_files_to_scan,
    shipped_js_to_scan,
    shipped_shell_to_scan,
)
from test_file_size_pin import (
    _SHELL_FLOOR,
    _band_violations,
    _cap_offenders,
    _js_shortfalls,
    _line_count,
    _shell_shortfalls,
    _shipped_root_shortfalls,
)


class TestCapOffenderDetection(unittest.TestCase):
    """A file one line over the cap must be named, with its count."""

    def test_a_501_line_file_is_named_as_an_offender(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            offender = root / "over_cap.py"
            offender.write_text("\n".join(f"x = {i}" for i in range(501)) + "\n")
            self.assertEqual(_line_count(offender), 501)

            offenders = _cap_offenders([offender], root)

        self.assertEqual(len(offenders), 1)
        self.assertIn("over_cap.py", offenders[0])
        self.assertIn("501", offenders[0])

    def test_a_file_at_the_cap_is_not_an_offender(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            at_cap = root / "at_cap.py"
            at_cap.write_text("\n".join(f"x = {i}" for i in range(500)) + "\n")
            self.assertEqual(_line_count(at_cap), 500)

            offenders = _cap_offenders([at_cap], root)

        self.assertEqual(offenders, [])


class TestBandRatchetRedProof(unittest.TestCase):
    """The ratchet itself, proven to go red -- committed, not a manual
    bump-and-restore. `BAND_CEILINGS` is honest against the tree the day it
    is measured, so the real-tree ratchet tests are green by construction and
    say nothing about whether the comparison works."""

    def _write(self, root: Path, lines: int) -> Path:
        path = root / "banded.py"
        path.write_text("\n".join(f"x = {i}" for i in range(lines)) + "\n")
        self.assertEqual(_line_count(path), lines)
        return path

    def test_growth_past_a_recorded_ceiling_is_flagged(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            path = self._write(root, 460)
            violations = _band_violations([path], root, {"banded.py": 459})

        self.assertEqual(len(violations), 1)
        self.assertIn("banded.py", violations[0])
        self.assertIn("460", violations[0])
        self.assertIn("459", violations[0])

    def test_a_file_at_its_recorded_ceiling_is_not_flagged(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            path = self._write(root, 460)
            violations = _band_violations([path], root, {"banded.py": 460})

        self.assertEqual(violations, [])

    def test_crossing_the_floor_with_no_recorded_ceiling_is_flagged(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            path = self._write(root, 451)
            violations = _band_violations([path], root, {})

        self.assertEqual(len(violations), 1)
        self.assertIn("no recorded ceiling", violations[0])

    def test_shrinking_to_the_floor_is_allowed_despite_a_higher_ceiling(self):
        """A file that drops to <=450 passes even while its (now stale) entry
        still records a higher count -- shrinking is never a violation."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            path = self._write(root, 450)
            violations = _band_violations([path], root, {"banded.py": 485})

        self.assertEqual(violations, [])


class TestShellScanRedProofs(unittest.TestCase):
    """The shell surface's own discovery, proven to go red.

    Separate proofs, each red for a different reason: the scan collapsing to
    nothing, the tests/ exclusion inverting, and the band and cap legs not
    biting on a shell path. The band one matters most -- the real-tree band
    assertion goes green the moment the ceiling is recorded and stays green
    forever, so `shell path in band -> flagged` is otherwise pinned by nothing.
    """

    def _tree(self, root: Path) -> Path:
        plugin = root / "plugins" / "xp-agents"
        for sub in ("smm", "skills", "skills/xp-thing/scripts", "tests"):
            (plugin / sub).mkdir(parents=True, exist_ok=True)
        return plugin

    def _write_sh(self, path: Path, lines: int) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(f"echo {i}" for i in range(lines)) + "\n")
        self.assertEqual(_line_count(path), lines)
        return path

    def test_a_collapsed_shell_scan_is_flagged(self):
        """No shell anywhere: the floor must fire rather than report clean."""
        with tempfile.TemporaryDirectory() as td:
            plugin = self._tree(Path(td))
            shortfalls = _shell_shortfalls(shipped_shell_to_scan(plugin))

        self.assertEqual(len(shortfalls), 1)
        self.assertIn("0", shortfalls[0])

    def test_a_healthy_shell_tree_reports_no_shortfall(self):
        with tempfile.TemporaryDirectory() as td:
            plugin = self._tree(Path(td))
            for i in range(_SHELL_FLOOR):
                self._write_sh(plugin / "skills" / f"s{i}.sh", 3)
            shortfalls = _shell_shortfalls(shipped_shell_to_scan(plugin))

        self.assertEqual(shortfalls, [])

    def test_shell_under_tests_is_not_scanned(self):
        """tests/ never ships. If this exclusion ever inverts, the pin starts
        governing files the cap was never meant to reach, and the count drifts
        for a reason nobody can see."""
        with tempfile.TemporaryDirectory() as td:
            plugin = self._tree(Path(td))
            shipped = self._write_sh(plugin / "smm" / "init.sh", 3)
            self._write_sh(plugin / "tests" / "fixture.sh", 3)
            scanned = shipped_shell_to_scan(plugin)

        self.assertEqual(scanned, [shipped])

    def test_shell_is_found_in_a_directory_no_glob_anticipated(self):
        """The whole point of scanning by suffix rather than by enumerated
        location: a shell script in a directory nobody listed is still governed.
        An enumerated-glob discovery would report clean here."""
        with tempfile.TemporaryDirectory() as td:
            plugin = self._tree(Path(td))
            surprise = self._write_sh(plugin / "hooks" / "helpers" / "new.sh", 3)
            self.assertIn(surprise, shipped_shell_to_scan(plugin))

    def test_a_banded_shell_file_is_flagged_end_to_end(self):
        """Discovery composed with the band leg -- the assertion the real tree
        can never make again once the ceiling is on record."""
        with tempfile.TemporaryDirectory() as td:
            td_root = Path(td)
            plugin = self._tree(td_root)
            self._write_sh(plugin / "skills" / "big.sh", 460)
            violations = _band_violations(shipped_shell_to_scan(plugin), td_root, {})

        self.assertEqual(len(violations), 1)
        self.assertIn("big.sh", violations[0])
        self.assertIn("460", violations[0])
        self.assertIn("no recorded ceiling", violations[0])

    def test_a_shell_file_over_the_cap_is_named_an_offender(self):
        with tempfile.TemporaryDirectory() as td:
            td_root = Path(td)
            plugin = self._tree(td_root)
            self._write_sh(plugin / "smm" / "huge.sh", 501)
            offenders = _cap_offenders(shipped_shell_to_scan(plugin), td_root)

        self.assertEqual(len(offenders), 1)
        self.assertIn("huge.sh", offenders[0])
        self.assertIn("501", offenders[0])


class TestShippedRootFloorRedProof(unittest.TestCase):
    """A narrowed selection (a whole shipped root missing) must trip the
    per-root non-vacuity check -- an automated red proof, not a manual
    mutate-confirm-restore that leaves no regression guard."""

    def test_a_missing_skill_scripts_root_is_flagged(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "plugins" / "xp-agents" / "scripts").mkdir(parents=True)
            (root / "plugins" / "xp-agents" / "smm").mkdir(parents=True)
            for i in range(60):
                (root / "plugins" / "xp-agents" / "scripts" / f"m{i}.py").write_text(
                    "x = 1\n"
                )
            for i in range(35):
                (root / "plugins" / "xp-agents" / "smm" / f"m{i}.py").write_text(
                    "x = 1\n"
                )
            # No skills/*/scripts directory at all -- the root is missing.

            paths = shipped_files_to_scan(root / "plugins" / "xp-agents")
            shortfalls = _shipped_root_shortfalls(paths, root)

        self.assertEqual(len(shortfalls), 1)
        self.assertIn("skills/*/scripts", shortfalls[0])
        self.assertIn("expected at least 5", shortfalls[0])

    def test_a_healthy_tree_reports_no_shortfalls(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            scripts = root / "plugins" / "xp-agents" / "scripts"
            smm = root / "plugins" / "xp-agents" / "smm"
            skill_scripts = (
                root / "plugins" / "xp-agents" / "skills" / "foo" / "scripts"
            )
            for d in (scripts, smm, skill_scripts):
                d.mkdir(parents=True)
            for i in range(60):
                (scripts / f"m{i}.py").write_text("x = 1\n")
            for i in range(35):
                (smm / f"m{i}.py").write_text("x = 1\n")
            for i in range(6):
                (skill_scripts / f"m{i}.py").write_text("x = 1\n")

            paths = shipped_files_to_scan(root / "plugins" / "xp-agents")
            shortfalls = _shipped_root_shortfalls(paths, root)

        self.assertEqual(shortfalls, [])


class TestJsScanRedProofs(unittest.TestCase):
    """The JavaScript surface's discovery, proven to go red.

    The newest surface and the one least able to fail loudly on its own: no
    linter, formatter or type checker in this repo reads a `.js`, and the JS
    behaviour suite runs the shipped script rather than measuring it. If this
    discovery silently returns nothing, a 700-line orchestrator passes every
    check the repo has.

    The `tests/` proof is the one to keep honest. The exclusion is keyed on the
    FIRST path segment, so a `.js` under `tests/` is out and a legitimately
    shipped one at any depth is in — including a depth no glob anticipated,
    which is the case the shell precedent argues is the whole reason to select
    by suffix.
    """

    def _tree(self, root: Path) -> None:
        (root / "workflows").mkdir()
        (root / "tests" / "workflows").mkdir(parents=True)

    def test_a_collapsed_scan_reports_a_shortfall(self):
        with tempfile.TemporaryDirectory() as td:
            plugin = Path(td)
            self._tree(plugin)
            shortfalls = _js_shortfalls(shipped_js_to_scan(plugin))

        self.assertEqual(len(shortfalls), 1)
        self.assertIn("0", shortfalls[0])

    def test_a_healthy_js_tree_reports_no_shortfall(self):
        """The control. Without it the proof above passes against a helper
        that reports a shortfall unconditionally."""
        with tempfile.TemporaryDirectory() as td:
            plugin = Path(td)
            self._tree(plugin)
            (plugin / "workflows" / "code_review.js").write_text("// x\n")
            shortfalls = _js_shortfalls(shipped_js_to_scan(plugin))

        self.assertEqual(shortfalls, [])

    def test_a_js_file_under_tests_is_not_governed_as_shipped(self):
        """The harness and its fixtures are test code and must not count
        toward the shipped floor — otherwise the floor is satisfied by the
        very files that would remain if the shipped scan broke."""
        with tempfile.TemporaryDirectory() as td:
            plugin = Path(td)
            self._tree(plugin)
            (plugin / "tests" / "workflows" / "harness_test.js").write_text("// x\n")
            found = shipped_js_to_scan(plugin)

        self.assertEqual(found, [])

    def test_a_js_file_in_an_unanticipated_directory_is_still_governed(self):
        """Selection is by SUFFIX at any depth. An enumerated glob would miss
        this, and no floor could fire for a location that never existed."""
        with tempfile.TemporaryDirectory() as td:
            plugin = Path(td)
            self._tree(plugin)
            nested = plugin / "somewhere" / "nobody" / "planned"
            nested.mkdir(parents=True)
            (nested / "helper.js").write_text("// x\n")
            found = shipped_js_to_scan(plugin)

        self.assertEqual([p.name for p in found], ["helper.js"])

    def test_the_cap_leg_names_a_js_offender(self):
        """End-to-end on a `.js` path: an over-cap file is named, with its
        count. The real-tree cap leg returns [] whether the tree is clean or
        the scan is empty; this is what tells those apart."""
        with tempfile.TemporaryDirectory() as td:
            plugin = Path(td)
            self._tree(plugin)
            fat = plugin / "workflows" / "code_review.js"
            fat.write_text("// line\n" * 501)
            offenders = _cap_offenders(shipped_js_to_scan(plugin), plugin)

        self.assertEqual(len(offenders), 1)
        self.assertIn("code_review.js", offenders[0])
        self.assertIn("501", offenders[0])

    def test_the_band_leg_bites_on_a_js_path(self):
        """A `.js` above the band floor with no recorded ceiling is a
        violation, exactly as a `.py` or `.sh` would be."""
        with tempfile.TemporaryDirectory() as td:
            plugin = Path(td)
            self._tree(plugin)
            banded = plugin / "workflows" / "code_review.js"
            banded.write_text("// line\n" * 460)
            violations = _band_violations(shipped_js_to_scan(plugin), plugin)

        self.assertEqual(len(violations), 1)
        self.assertIn("code_review.js", violations[0])


if __name__ == "__main__":
    unittest.main()
