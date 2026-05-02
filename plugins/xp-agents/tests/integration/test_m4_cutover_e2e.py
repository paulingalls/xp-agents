#!/usr/bin/env python3
"""Story-004 capstone: M-4 cutover end-to-end acceptance.

Renders the milestone done-state into executable assertions:
- Commits clear with `/simplify` + `/xp-quality-review` only.
- Tier 1 deterministic patterns still block on staged secrets.
- Doc set carries zero `security_review_done` references.
- `markers._REVIEW_FLAGS` and `_DEFAULT_REVIEW_CYCLE` no longer
  contain `security_review_done`.
- Below-threshold commits no longer auto-write the security marker
  (absorbs story-001 close-reviewer concern 26d40317ed82 — the
  deleted exemption fallback).
"""

import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import markers
from conftest import _PLUGIN_ROOT, _IntegrationTestCase, _make_bash_input

_REPO_ROOT = _PLUGIN_ROOT.parent.parent

_CLEAN_LINE = 'def hello():\n    return "hi"\n'
_AKIA_LINE = 'aws_key = "AKIAIOSFODNN7EXAMPLE"\n'

# Spread the post-M-4 default so the schema stays in lockstep with markers.py;
# we only flip the two surviving flags.
_REVIEW_DONE = dict(markers._DEFAULT_REVIEW_CYCLE) | {
    "simplify_done": True,
    "quality_review_done": True,
}


class TestM4CutoverE2E(_IntegrationTestCase):
    """Integration-level confirmation of the M-4 cutover done-state."""

    def _stage(self, name: str, content: str) -> None:
        (self.tmpdir / name).write_text(content)
        subprocess.run(
            ["git", "add", name],
            cwd=self.tmpdir,
            capture_output=True,
            check=True,
        )

    def _commit_input(self) -> dict:
        return _make_bash_input(command="git commit -m 'wip'", cwd=str(self.tmpdir))

    def test_commit_with_only_simplify_and_quality_passes(self):
        markers.write_review_cycle(self.smm_dir, "main", _REVIEW_DONE)
        self._stage("app.py", _CLEAN_LINE)

        result = self._run_script("pre_tool_bash.py", self._commit_input())

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("xp-security-triage", result.stderr)
        self.assertNotIn("security-review", result.stderr)

    def test_tier1_pattern_still_blocks_after_m4(self):
        markers.write_review_cycle(self.smm_dir, "main", _REVIEW_DONE)
        self._stage("secrets.py", _AKIA_LINE)

        result = self._run_script("pre_tool_bash.py", self._commit_input())

        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("aws-access-key", result.stderr)

    def test_below_threshold_passes_without_marker(self):
        """Absorbs close-reviewer concern 26d40317ed82: below-threshold
        commits pass cleanly without any security gate. The marker
        subsystem itself was removed in M-5 so there is no marker to
        check for absence."""
        self._stage("solo.py", _CLEAN_LINE)

        result = self._run_script("pre_tool_bash.py", self._commit_input())

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_review_flags_no_longer_contain_security(self):
        self.assertNotIn("security_review_done", markers._REVIEW_FLAGS)
        self.assertNotIn("security_review_done", markers._DEFAULT_REVIEW_CYCLE)

    def test_doc_grep_zero_security_review_done_references(self):
        files = [
            _PLUGIN_ROOT / "PROCESS_GUIDE.md",
            _REPO_ROOT / "CLAUDE.md",
            _REPO_ROOT / "docs" / "ARCHITECTURE.md",
            _PLUGIN_ROOT / "agents" / "xp-plan-reviewer.md",
        ]
        # Fail loud if a doc moves — silent skip would let a rename hide
        # surviving references to the retired flag.
        for f in files:
            self.assertTrue(f.exists(), f"M-4 doc-grep target missing: {f}")
        offenders = []
        for f in files:
            for i, line in enumerate(f.read_text().splitlines(), start=1):
                if "security_review_done" in line:
                    offenders.append(f"{f}:{i}: {line.strip()}")
        self.assertEqual(
            offenders,
            [],
            "M-4 doc set must not reference security_review_done; found:\n"
            + "\n".join(offenders),
        )

    def test_no_three_step_cycle_phrase_in_shipped_surfaces(self):
        """Sibling of the named-flag grep above: catches stale prose
        descriptions of the retired three-step review cycle. Per-story
        doc-grep missed runtime nudge strings, seeded wisdom, hook
        tables, and design-doc bullets; this widens the net to every
        shipped script/doc/agent/skill, with active design notes and
        historical records allowlisted.

        Predicate: scans whole-file text (so multi-line Python string
        literals are joined) for any window that mentions simplify,
        quality, AND a security-triage token in close proximity — the
        signature of the retired three-step cycle. Also flags the
        bare-words "security triage before commit" drift form."""
        roots = [
            _PLUGIN_ROOT / "scripts",
            _PLUGIN_ROOT / "smm",
            _PLUGIN_ROOT / "agents",
            _PLUGIN_ROOT / "skills",
            _PLUGIN_ROOT / "PROCESS_GUIDE.md",
            _PLUGIN_ROOT / "TEAMMATE_GUIDE.md",
            _REPO_ROOT / "README.md",
            _REPO_ROOT / "CLAUDE.md",
            _REPO_ROOT / "docs",
        ]
        # Allowlist:
        # - docs/ideas/ — design notes / future-feature exploration
        # - docs/completed/ — archived plans
        # - docs/handoffs/ — timestamped historical records
        # - tests/ — assert against the old behavior we're confirming is gone
        allowlist_substrings = (
            "/docs/ideas/",
            "/docs/completed/",
            "/docs/handoffs/",
            "/tests/",
        )
        # Two drift signatures, both whole-file (not line-by-line) so
        # multi-line string literals can't smuggle the trio past us:
        #   (a) cycle-trio: simplify ... quality ... security-triage
        #       within ~120 chars, AND the trio appears in cycle-listing
        #       context (arrow operator OR the word "cycle" within ~30
        #       chars of the trio). This filters legitimate skill
        #       enumerations (e.g. dispatcher docstrings) from prose
        #       that describes the retired three-step cycle.
        #   (b) bare drift phrase "security triage before commit".
        import re

        # Match the trio with comma/arrow separators in cycle context.
        # Arrow form: simplify → quality → security-triage
        # Comma form: simplify, /xp-quality-review, /xp-security-triage
        # Both require either a "→" arrow somewhere in the window, or
        # the literal word "cycle" within ~80 chars before the match.
        # Char class excludes "." (sentence boundary) but allows
        # newlines and quotes so multi-line Python string literals
        # ("cycle "\n"(/simplify…") still match.
        cycle_trio_arrow = re.compile(
            r"simplify[^.]{1,120}?→[^.]{1,120}?quality"
            r"[^.]{1,120}?→[^.]{1,120}?security[ \-/]?triage",
            re.IGNORECASE,
        )
        cycle_trio_cycle_word = re.compile(
            r"cycle[^.]{0,80}?simplify[^.]{1,120}?quality"
            r"[^.]{1,120}?security[ \-/]?triage",
            re.IGNORECASE,
        )
        bare_drift = re.compile(
            r"security[ \-]triage before commit",
            re.IGNORECASE,
        )
        offenders = []
        for root in roots:
            if root.is_dir():
                paths = (
                    list(root.rglob("*.md"))
                    + list(root.rglob("*.py"))
                    + list(root.rglob("*.sh"))
                )
            else:
                paths = [root]
            for f in paths:
                if not f.is_file():
                    continue
                if any(s in str(f) for s in allowlist_substrings):
                    continue
                try:
                    text = f.read_text()
                except (UnicodeDecodeError, OSError):
                    continue
                for pattern in (cycle_trio_arrow, cycle_trio_cycle_word, bare_drift):
                    for m in pattern.finditer(text):
                        line_no = text.count("\n", 0, m.start()) + 1
                        offenders.append(f"{f}:{line_no}: {m.group(0)!r}")
        self.assertEqual(
            offenders,
            [],
            "Stale three-step review-cycle prose found in shipped "
            "surfaces:\n" + "\n".join(offenders),
        )


if __name__ == "__main__":
    unittest.main()
