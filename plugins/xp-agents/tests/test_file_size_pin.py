#!/usr/bin/env python3
"""Tree-wide file-size pin. Cap = 500 lines, customer-settled — see the
decision recorded at close.

"Tree-wide" means Python under `scripts/`, `smm/`, `skills/*/scripts/` and
`tests/`, plus every shipped shell script at any depth. It said the same thing
before story-002 while discovering only `.py`, so `skills/_preload_base.sh` sat
at 492 — inside the band, 8 lines from the cap — governed by nothing. A gate
whose stated scope is wider than its real one is the defect class this file now
guards against in others, so the claim is spelled out rather than assumed.
Nothing here is Python-specific: `_line_count` is `splitlines()`, and
`_cap_offenders`/`_band_violations` take paths. Only discovery ever was.

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
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from _pin_ceilings import BAND_CEILINGS
from _pin_helpers import (
    files_to_scan,
    rel,
    scan_shortfalls,
    shipped_files_to_scan,
    shipped_js_to_scan,
    shipped_prose_to_scan,
    shipped_shell_to_scan,
)

_PLUGIN_ROOT = Path(__file__).parent.parent
_REPO_ROOT = _PLUGIN_ROOT.parent.parent

_LINE_CAP = 500
_BAND_FLOOR = 450

# Per-root non-vacuity floors for the shipped leg. Set well below the current
# counts so ordinary growth or shrink never trips this; a whole root going
# missing (a selector typo, a dropped glob) does.
_SHIPPED_ROOT_FLOORS = {
    "scripts": 50,
    "smm": 30,
    "skills/*/scripts": 5,
}

# Non-vacuity floor for the shell surface. No hand-written count: the one that
# was here had already drifted. Set well below the current count: ordinary
# growth or shrink must never trip it, while a scan that collapses to nothing
# -- a broken suffix, an inverted exclusion -- must. One floor, not several,
# because `shipped_shell_to_scan` selects by suffix at any depth: there is no
# per-location glob that could quietly stop matching.
_SHELL_FLOOR = 15

# Non-vacuity floor for the JavaScript surface, same shape and same reasoning as
# the shell one above. One, because there is one shipped `.js` -- the broad-review
# workflow orchestrator -- and the number that matters is the difference between
# one and NONE. A scan that collapses (a broken suffix, an inverted exclusion, a
# moved directory) reports clean over an empty set otherwise, and on this surface
# nothing else would notice: no linter, formatter or type checker in this repo
# reads a `.js`. Raise it when a second one ships.
_JS_FLOOR = 1


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


def _js_shortfalls(paths: list[Path]) -> list[str]:
    """Shortfall when the JavaScript scan has collapsed; empty when healthy."""
    if len(paths) < _JS_FLOOR:
        return [
            f"only {len(paths)} JavaScript file(s) scanned, expected at least "
            f"{_JS_FLOOR}"
        ]
    return []


def _shell_shortfalls(paths: list[Path]) -> list[str]:
    """Shortfall when the shell scan has collapsed; empty when healthy."""
    if len(paths) < _SHELL_FLOOR:
        return [
            f"only {len(paths)} shell file(s) scanned, expected at least {_SHELL_FLOOR}"
        ]
    return []


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

    def test_every_shipped_shell_file_is_at_or_under_the_cap(self):
        offenders = _cap_offenders(shipped_shell_to_scan(_PLUGIN_ROOT), _REPO_ROOT)
        self.assertEqual(offenders, [], msg="; ".join(offenders))

    def test_every_shipped_js_file_is_at_or_under_the_cap(self):
        offenders = _cap_offenders(shipped_js_to_scan(_PLUGIN_ROOT), _REPO_ROOT)
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

    def test_shipped_shell_files_honor_their_recorded_ceiling(self):
        violations = _band_violations(shipped_shell_to_scan(_PLUGIN_ROOT), _REPO_ROOT)
        self.assertEqual(violations, [], msg="; ".join(violations))

    def test_shipped_js_files_honor_their_recorded_ceiling(self):
        violations = _band_violations(shipped_js_to_scan(_PLUGIN_ROOT), _REPO_ROOT)
        self.assertEqual(violations, [], msg="; ".join(violations))


class TestNonVacuity(unittest.TestCase):
    """The scanned count can't quietly go to zero and report clean."""

    def test_shipped_scan_covers_every_root_at_a_floor(self):
        paths = shipped_files_to_scan(_PLUGIN_ROOT)
        shortfalls = _shipped_root_shortfalls(paths, _REPO_ROOT)
        self.assertEqual(shortfalls, [], msg="; ".join(shortfalls))

    def test_shell_scan_clears_its_floor(self):
        shortfalls = _shell_shortfalls(shipped_shell_to_scan(_PLUGIN_ROOT))
        self.assertEqual(shortfalls, [], msg="; ".join(shortfalls))

    def test_js_scan_clears_its_floor(self):
        shortfalls = _js_shortfalls(shipped_js_to_scan(_PLUGIN_ROOT))
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
        surfaces = shipped_files_to_scan(_PLUGIN_ROOT)
        surfaces += shipped_shell_to_scan(_PLUGIN_ROOT)
        for paths in shipped_prose_to_scan(_PLUGIN_ROOT).values():
            surfaces += paths
        return [
            rel(p, _REPO_ROOT)
            for p in surfaces
            if needle in p.read_text(encoding="utf-8")
        ]


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
