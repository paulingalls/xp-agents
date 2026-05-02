#!/usr/bin/env python3
"""M-5 cleanup capstone — zero-reference grep across shipped surfaces.

Pins the M-5 done criterion: zero references to security_review_done,
SECURITY_TRIAGED, xp-security-triage, or xp-security-reviewer in
shipped code/docs. Test files are allowlisted because they assert the
absence of these terms (negative assertions are correct usage);
historical doc paths (docs/ideas/, docs/completed/, docs/handoffs/)
are allowlisted because they record the migration that produced this
state.

A regression-confidence test injects a stub reference into a temp file
and confirms the same predicate trips — without it, a future refactor
that breaks the scan would let resurrections through silently.
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from conftest import _PLUGIN_ROOT

_REPO_ROOT = _PLUGIN_ROOT.parent.parent

_SEARCH_TERMS = (
    "security_review_done",
    "SECURITY_TRIAGED",
    "xp-security-triage",
    "xp-security-reviewer",
)

_SCAN_ROOTS = (
    _PLUGIN_ROOT / "scripts",
    _PLUGIN_ROOT / "smm",
    _PLUGIN_ROOT / "agents",
    _PLUGIN_ROOT / "skills",
    _PLUGIN_ROOT / "hooks",
    _PLUGIN_ROOT / "PROCESS_GUIDE.md",
    _PLUGIN_ROOT / "TEAMMATE_GUIDE.md",
    _PLUGIN_ROOT / "XP_VALUES.md",
    _REPO_ROOT / "README.md",
    _REPO_ROOT / "CLAUDE.md",
    # Scan all of docs/ as a directory (matches M-4 precedent) so newly
    # added design docs / spikes get coverage automatically. Historical
    # subtrees (ideas/, completed/, handoffs/) are filtered by
    # _ALLOWLIST_SUBSTRINGS below.
    _REPO_ROOT / "docs",
)

# Allowlist substrings: paths containing any of these are skipped. Tests
# routinely assert the absence of these terms; historical doc paths
# preserve the migration record. The capstone test file itself names
# the terms as data and must allowlist itself.
_ALLOWLIST_SUBSTRINGS = (
    "/tests/",
    "/docs/ideas/",
    "/docs/completed/",
    "/docs/handoffs/",
)

# File extensions worth scanning for prose / source content.
_SCAN_EXTENSIONS = (".md", ".py", ".sh", ".json")


def _iter_scan_paths():
    for root in _SCAN_ROOTS:
        if root.is_file():
            yield root
        elif root.is_dir():
            for path in root.rglob("*"):
                if path.suffix in _SCAN_EXTENSIONS:
                    yield path


def _scan_for_terms(roots, terms, allowlist=()):
    """Return list of "<path>:<line>: <line text>" hits across `roots`.

    Allowlist suppresses paths whose string contains any allowlisted
    substring. Each term is matched literally; one hit per line is
    enough — `break` short-circuits after the first match so multi-term
    lines don't inflate the offender count.
    """
    offenders = []
    for path in roots:
        if not path.is_file():
            continue
        if any(s in str(path) for s in allowlist):
            continue
        try:
            text = path.read_text()
        except (UnicodeDecodeError, OSError):
            continue
        for line_no, line in enumerate(text.splitlines(), start=1):
            for term in terms:
                if term in line:
                    offenders.append(f"{path}:{line_no}: {line.strip()}")
                    break
    return offenders


class TestM5CutoverZeroReferences(unittest.TestCase):
    """M-5 done criterion executable as a test."""

    def test_zero_references_in_shipped_surfaces(self):
        offenders = _scan_for_terms(
            _iter_scan_paths(), _SEARCH_TERMS, _ALLOWLIST_SUBSTRINGS
        )
        self.assertEqual(
            offenders,
            [],
            "M-5 done criterion violated — these shipped surfaces still "
            "reference removed security-triage names:\n" + "\n".join(offenders),
        )

    def test_regression_guard_catches_injection(self):
        """If the scan ever silently breaks, this fails loud.

        Writes a temp file with a known offender and runs the predicate
        against it directly. Doesn't touch the real scan roots — keeps
        the negative-assertion test above honest without polluting the
        repo.
        """
        with tempfile.TemporaryDirectory() as td:
            offender_path = Path(td) / "stub.md"
            offender_path.write_text(
                "This file mentions xp-security-triage to test the guard.\n"
            )
            offenders = _scan_for_terms([offender_path], _SEARCH_TERMS)
            self.assertEqual(len(offenders), 1, offenders)
            self.assertIn("xp-security-triage", offenders[0])


if __name__ == "__main__":
    unittest.main()
