#!/usr/bin/env python3
"""Tree-wide file-size pin. Cap = 500 lines, customer-settled — see the
decision recorded at close.

Two files are counted differently than a shell `wc -l` would: a file with no
trailing newline undercounts by one under `wc -l` but not under
`str.splitlines()`, so counting is pinned to
`len(path.read_text(encoding="utf-8").splitlines())` everywhere in this file.

The band ratchet is the second half of the recorded constraint ("leave real
headroom below the cap"): a file already above 450 lines may not grow past its
CURRENT count, which becomes its own ceiling. Shrinking below 451 makes an
entry dormant, and an empty table is the success state. The table itself lives
in `_pin_ceilings.py` — it changes on every routine crossing anywhere in the
tree, while this file changes only when the rule does.

Retirement is a MANUAL step and nothing here enforces it: a dormant entry is
not a failure, so a file that shrinks below 451 keeps its old, higher ceiling
and may regrow all the way back to it. Delete the entry when you shrink a
file, or the ratchet quietly hands back the ground you just won.
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from _pin_ceilings import BAND_CEILINGS
from _pin_helpers import (
    files_to_scan,
    rel,
    scan_shortfalls,
    shipped_files_to_scan,
    shipped_prose_to_scan,
)

_PLUGIN_ROOT = Path(__file__).parent.parent
_REPO_ROOT = _PLUGIN_ROOT.parent.parent

_LINE_CAP = 500
_BAND_FLOOR = 450

# Per-root non-vacuity floors for the shipped leg. Set well below the current
# counts (scripts=127, smm=68, skills/*/scripts=13) so ordinary growth or
# shrink never trips this; a whole root going missing (a selector typo, a
# dropped glob) does.
_SHIPPED_ROOT_FLOORS = {
    "scripts": 50,
    "smm": 30,
    "skills/*/scripts": 5,
}


def _line_count(path: Path) -> int:
    return len(path.read_text(encoding="utf-8").splitlines())


def _cap_offenders(
    paths: list[Path], repo_root: Path, cap: int = _LINE_CAP
) -> list[str]:
    """Names + counts of every path over *cap*, repo-relative."""
    offenders = []
    for path in paths:
        count = _line_count(path)
        if count > cap:
            offenders.append(f"{rel(path, repo_root)} ({count} lines)")
    return offenders


def _band_violations(
    paths: list[Path], repo_root: Path, ceilings: dict[str, int] | None = None
) -> list[str]:
    """Files above `_BAND_FLOOR` that either have no recorded ceiling or have
    grown past the one they have.

    *ceilings* defaults to `_pin_ceilings.BAND_CEILINGS`; tests pass their own
    table so the red proof does not depend on which real files happen to be in
    the band.
    """
    ceilings = BAND_CEILINGS if ceilings is None else ceilings
    violations = []
    for path in paths:
        count = _line_count(path)
        if count <= _BAND_FLOOR:
            continue
        key = rel(path, repo_root)
        ceiling = ceilings.get(key)
        if ceiling is None:
            violations.append(
                f"{key} ({count} lines) crossed above {_BAND_FLOOR} with no "
                f"recorded ceiling in _pin_ceilings.BAND_CEILINGS"
            )
        elif count > ceiling:
            violations.append(
                f"{key} grew to {count} lines, above its recorded ceiling of {ceiling}"
            )
    return violations


def _root_of(relpath: str) -> str:
    """The shipped root a scanned path belongs to.

    `shipped_files_to_scan` only ever returns paths under `scripts/`, `smm/`,
    or `skills/*/scripts/` -- every path it yields falls into exactly one.
    """
    if relpath.startswith("plugins/xp-agents/scripts/"):
        return "scripts"
    if relpath.startswith("plugins/xp-agents/smm/"):
        return "smm"
    return "skills/*/scripts"


def _shipped_root_shortfalls(paths: list[Path], repo_root: Path) -> list[str]:
    """Per-root floor check -- a lump floor over the total would still pass
    green after losing an entire root (e.g. all of skills/*/scripts, 13
    files) as long as the remainder clears it. Each root is checked alone."""
    counts: dict[str, int] = {root: 0 for root in _SHIPPED_ROOT_FLOORS}
    for path in paths:
        root = _root_of(rel(path, repo_root))
        counts[root] = counts.get(root, 0) + 1
    shortfalls = []
    for root, floor in _SHIPPED_ROOT_FLOORS.items():
        if counts.get(root, 0) < floor:
            shortfalls.append(
                f"root '{root}' contributed only {counts.get(root, 0)} file(s), "
                f"expected at least {floor}"
            )
    return shortfalls


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


class TestTreeWideCap(unittest.TestCase):
    """The real tree, both legs, at or under the 500-line cap."""

    def test_every_shipped_file_is_at_or_under_the_cap(self):
        paths = shipped_files_to_scan(_PLUGIN_ROOT)
        offenders = _cap_offenders(paths, _REPO_ROOT)
        self.assertEqual(offenders, [], msg="; ".join(offenders))

    def test_every_test_file_is_at_or_under_the_cap(self):
        paths = files_to_scan(_PLUGIN_ROOT / "tests", exclude_self=Path(__file__))
        offenders = _cap_offenders(paths, _REPO_ROOT)
        self.assertEqual(offenders, [], msg="; ".join(offenders))


class TestBandRatchet(unittest.TestCase):
    """Every file above 450 lines is at or under its recorded ceiling."""

    def test_shipped_files_honor_their_recorded_ceiling(self):
        paths = shipped_files_to_scan(_PLUGIN_ROOT)
        violations = _band_violations(paths, _REPO_ROOT)
        self.assertEqual(violations, [], msg="; ".join(violations))

    def test_test_files_honor_their_recorded_ceiling(self):
        paths = files_to_scan(_PLUGIN_ROOT / "tests", exclude_self=Path(__file__))
        violations = _band_violations(paths, _REPO_ROOT)
        self.assertEqual(violations, [], msg="; ".join(violations))


class TestNonVacuity(unittest.TestCase):
    """The scanned count can't quietly go to zero and report clean."""

    def test_shipped_scan_covers_every_root_at_a_floor(self):
        paths = shipped_files_to_scan(_PLUGIN_ROOT)
        shortfalls = _shipped_root_shortfalls(paths, _REPO_ROOT)
        self.assertEqual(shortfalls, [], msg="; ".join(shortfalls))

    def test_test_scan_clears_a_tree_wide_floor(self):
        paths = files_to_scan(_PLUGIN_ROOT / "tests", exclude_self=Path(__file__))
        shortfalls = scan_shortfalls(
            paths, _PLUGIN_ROOT / "tests", min_files=550, exclude_self=Path(__file__)
        )
        self.assertEqual(shortfalls, [], msg="; ".join(shortfalls))


class TestPinDoesNotShip(unittest.TestCase):
    """This pin is repo-internal only -- a shipped surface naming it would
    be exactly the leak this pin's own module docstring warns against: a
    Rust or Go user has no use for a Python line-count rule."""

    def test_module_name_has_no_shipped_hits(self):
        hits = self._search("test_file_size_pin")
        self.assertEqual(hits, [], msg="; ".join(hits))

    def test_line_cap_identifier_has_no_shipped_hits(self):
        hits = self._search("_LINE_CAP")
        self.assertEqual(hits, [], msg="; ".join(hits))

    def _search(self, needle: str) -> list[str]:
        hits = []
        for path in shipped_files_to_scan(_PLUGIN_ROOT):
            if needle in path.read_text(encoding="utf-8"):
                hits.append(rel(path, _REPO_ROOT))
        for _group, paths in shipped_prose_to_scan(_PLUGIN_ROOT).items():
            for path in paths:
                if needle in path.read_text(encoding="utf-8"):
                    hits.append(rel(path, _REPO_ROOT))
        return hits


class TestSelfCoverage(unittest.TestCase):
    """The pin's own file is subject to the cap it enforces on everything
    else -- no self-exemption."""

    def test_this_file_is_under_the_cap(self):
        self.assertLessEqual(_line_count(Path(__file__)), _LINE_CAP)

    def test_this_file_honors_the_band_ratchet_too(self):
        """`exclude_self` keeps this file out of both tree-wide legs, so the
        cap assertion above leaves it the one file in the tree the RATCHET
        cannot see. Crossing 450 here must demand a recorded ceiling like
        anywhere else."""
        violations = _band_violations([Path(__file__)], _REPO_ROOT)
        self.assertEqual(violations, [], msg="; ".join(violations))


if __name__ == "__main__":
    unittest.main()
