#!/usr/bin/env python3
"""Doctrinal pin: shipped code may not branch on a file's extension in silence.

The plugin ships to projects in ANY language — Python, TypeScript, Rust, Go,
Java, Ruby. That is the project's #1 invariant, and until this pin it was
enforced only by prose (CLAUDE.md, a system_context principle, an SMM
convention) plus reviewer vigilance. Sprint-103 leaked it three times against
that prose and was abandoned.

THE DISCRIMINATOR. The plugin is *itself* written in Python, so `.py`,
`python3` and `pytest` appear constantly for legitimate reasons; a naive scan is
useless. What matters is *whose source is being reasoned about*. A
single-language predicate on a USER-supplied path (tool_input file_path, staged
files, hook cwd, a story's file_domain) is where the assumption leaks. The same
predicate on the plugin's OWN `__file__` is fine. So the rule is:

    every file-extension predicate in shipped code must carry an inline
    `# lang-ok: <reason>` marker naming WHY it is agnostic (or is a
    per-language dispatch that degrades gracefully on other languages) —
    unless its operand derives from `__file__`.

The marker convention mirrors `# noqa: secret`, which already ships: a raw-line
match, with the justification AT THE SITE. An allowlist in another file drifts
away from the code it excuses; an inline marker cannot. The reason must be
non-empty, so the next author cannot copy the shape of a legitimate dispatch
without stating why theirs is one too.

WHY AST AND NOT GREP. The shipped tree carries ~140 `#!/usr/bin/env python3`
shebangs, `python3 <script>.py` usage lines inside module docstrings, and prose
mentions of `foo.py` in comments. A grep for `.py` drowns in them and gets
disabled. The AST sees only executable predicates: comments and shebangs never
reach it, and a docstring parses as a bare string Constant that no rule here
matches.

LIMITS — READ THIS BEFORE TRUSTING THE GREEN CHECK. A guardrail that overclaims
its coverage is itself a green check certifying something untrue, which is the
failure this pin exists to kill. So, precisely:

It targets ONE class of leak — the file-extension predicate on a path — and it
does not even close that class. It reads four shapes: `==`/`in` against a
`.suffix` (inline, hoisted one hop, or walrus-bound), `match` on a `.suffix`,
and `.endswith()` with a literal extension. Known shapes it MISSES, verified:
`os.path.splitext(p)[1] == ".py"`; `p.rsplit(".", 1)[-1] == "py"`;
`p.endswith(_PY_SUFFIXES)` where the tuple is a module constant;
`Path(p).match("*.py")` and `fnmatch`/`rglob` glob patterns; and an extension
passed into a helper as a parameter, where the comparison sits a function call
away from the path. Each is a real leak the pin would let through.

It would also have caught NONE of the three leaks this project has actually hit
— not sprint-103's, not the "pytest prints to stdout" plan-reasoning leak (jest
and vitest print to stderr), not a `harness="pytest"` config default. Those live
in prose, in prompts and in defaults, and they stay LLM-reviewed.

This is a floor, not a ceiling. Widen it when a real leak escapes through one of
the named gaps — not preemptively, and never by weakening a marker.

The walker lives in `tests/_lang_leak_scan.py`, and its own unit tests — the
detection and false-positive cases — in `test_lang_leak_scan.py`. This file is
the pin: what the walker finds when it is pointed at the real shipped tree.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from _lang_leak_scan import ENDSWITH_EXTENSION, MARKER, SUFFIX_COMPARE, Site, scan_file
from _pin_helpers import rel as _rel_impl
from _pin_helpers import shipped_files_to_scan

PLUGIN_ROOT = Path(__file__).parent.parent.parent  # plugins/xp-agents/
REPO_ROOT = PLUGIN_ROOT.parent.parent  # repo root for stable rel paths

# Sites the pin must find in today's tree. A guard that silently matches nothing
# passes forever; see the vacuity test.
MIN_KNOWN_SITES = 8


def _rel(path: Path) -> str:
    return _rel_impl(path, REPO_ROOT)


def _scan_shipped() -> dict[str, list[Site]]:
    return {
        _rel(p): sites
        for p in shipped_files_to_scan(PLUGIN_ROOT)
        if (sites := scan_file(p))
    }


# ---------------------------------------------------------------------------
# The pin
# ---------------------------------------------------------------------------


class TestNoLanguageLeak(unittest.TestCase):
    """No shipped module may branch on a file extension without saying why."""

    def test_no_unmarked_extension_predicate(self) -> None:
        """AC1/AC2: every extension predicate in shipped code is marked."""
        unmarked = [
            f"  {path}:{lineno}: {kind} on a user-supplied path with no "
            f"`# {MARKER} <reason>` marker"
            for path, sites in sorted(_scan_shipped().items())
            for lineno, kind, reason in sites
            if reason is None
        ]
        if unmarked:
            self.fail(
                f"{len(unmarked)} unjustified file-extension predicate(s) in "
                f"shipped code. The plugin ships to projects in any language, "
                f"so a single-language predicate on a user's path is a leak. "
                f"If the site is a legitimate multi-language dispatch (or one "
                f"that no-ops elsewhere), say so at the site:\n" + "\n".join(unmarked)
            )

    def test_markers_state_a_reason(self) -> None:
        """AC3: `# lang-ok:` with nothing after it does not count.

        Without this, the next author copies the marker off a legitimate
        dispatch onto a real leak and the pin certifies it.
        """
        empty = [
            f"  {path}:{site[0]}: `{MARKER}` marker with an empty reason"
            for path, sites in sorted(_scan_shipped().items())
            for site in sites
            if site[2] is not None and not site[2].strip()
        ]
        if empty:
            self.fail(
                "Marker present but no reason given — name why the predicate "
                "is language-agnostic:\n" + "\n".join(empty)
            )

    def test_scan_is_not_vacuous(self) -> None:
        """A guard that matches nothing passes forever.

        Pins the known population: if a refactor drops the scan roots or the
        detection shape stops matching, this goes red instead of going quiet.
        """
        total = sum(len(sites) for sites in _scan_shipped().values())
        self.assertGreaterEqual(
            total,
            MIN_KNOWN_SITES,
            msg=(
                f"Only {total} extension predicate(s) found; expected at least "
                f"{MIN_KNOWN_SITES}. The scan has gone blind — check the roots "
                f"in _pin_helpers.shipped_files_to_scan and the detection shape."
            ),
        )

    def test_scan_detects_every_shape_it_claims_to(self) -> None:
        """Each detection shape still finds its known sites in the real tree.

        The count alone is too coarse to notice a shape going blind: 13 of the
        18 known sites are `endswith`, so every `suffix-compare` in the tree
        could stop matching and the population would still clear the floor.
        Pinning per shape is what makes a broken rule go red instead of quiet.
        """
        kinds = {kind for sites in _scan_shipped().values() for _, kind, _ in sites}
        for shape in (SUFFIX_COMPARE, ENDSWITH_EXTENSION):
            self.assertIn(
                shape,
                kinds,
                msg=(
                    f"the `{shape}` rule matched nothing in shipped code — it "
                    f"had known sites, so the rule has gone blind"
                ),
            )

    def test_scan_covers_every_shipped_root(self) -> None:
        """scripts/, smm/ and skills/*/scripts/ all contribute files.

        A typo'd root would silently scan nothing and still pass the pin.
        """
        scanned = shipped_files_to_scan(PLUGIN_ROOT)
        rels = [_rel(p) for p in scanned]
        for root in ("plugins/xp-agents/scripts/", "plugins/xp-agents/smm/"):
            self.assertTrue(
                any(r.startswith(root) for r in rels), msg=f"{root} scanned nothing"
            )
        self.assertTrue(
            any("/skills/" in r and "/scripts/" in r for r in rels),
            msg="skills/*/scripts/ scanned nothing",
        )

    def test_tests_are_not_scanned(self) -> None:
        """Tests never ship, so they are free to be Python-specific — this
        pin's own `rglob("*.py")` would otherwise flag itself."""
        rels = [_rel(p) for p in shipped_files_to_scan(PLUGIN_ROOT)]
        self.assertFalse([r for r in rels if "/tests/" in r])


if __name__ == "__main__":
    unittest.main()
