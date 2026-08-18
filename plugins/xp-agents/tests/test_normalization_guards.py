#!/usr/bin/env python3
"""Pins for guards whose non-match reads as success.

`_WORKTREE_SEGMENT_RE` (`_budget_helpers.py`) and `assert_emitter_under_budgets`'s
missing `normalize_paths` (also `_budget_helpers.py`) were both dead for a whole
release span: a regex written for `/.claude/worktrees/<dir>` stopped matching
once worktrees moved under the data root in v5.0.0, and a normalization helper
never wired in never normalized anything. Neither ever raised — a pattern that
matches nothing and a normalization that normalizes nothing both look exactly
like success. `bff57399` fixed both; this module stops the CLASS from arriving
dead again.

Every specimen here is DERIVED by calling production — `worktree.worktree_path`,
`event_builder.generate_id` — never hand-typed. A hand-typed specimen carries
the same weakness as the guard it pins: when the real shape drifts, the
literal and the pattern go stale TOGETHER and the pin stays green, which is
the exact failure one layer up from the one this module exists to catch (see
the retired `test_measured_len_normalizes_the_real_worktree_layout` in
`test_budget_helpers_shim.py`, folded into `TestWorktreeSegmentGuardIsPinned`).

`_HISTORICAL_ID_RE` is pinned alongside the worktree-segment regex because it
is the same class of defect in a different shape: a DETECTOR whose non-match
reads as "no ids found" — exactly as green as a real absence. `_band_proof.py`'s
`_BAND_LINE` is the third shape: a PARSER that reads a measured value out of an
assertion message, where a wording drift in that message is invisible the same
way.

The per-pattern pins above only prove TODAY's guards are alive. That is
necessary but not the leg that matters going forward: they name patterns that
are already known about. The one guard against the NEXT pattern arriving dead
is `TestRegistryCompleteness`, which AST-scans every module this suite covers
for the pattern-shaped constants it holds and fails when one has no
registered specimen — so a hand-kept list of pattern NAMES can never silently
drift out of date. What is still hand-kept, deliberately, is the small SET of
MODULES covered (`_REGISTRY`'s keys): adding a new guard to an existing module
is a one-line, easy-to-forget change, so that leg has to be automatic; adding
a new module of guards is a visible, new-file-sized event, so naming it
explicitly is the honest scope decision here.
"""

import ast
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import _append_impl
import _band_proof
import _budget_helpers
import event_builder
import worktree
from _repo_fixtures import init_repo

_TESTS_DIR = Path(__file__).resolve().parent

# The set of modules this suite covers — see the module docstring for why this
# level (unlike pattern NAMES within a module) stays hand-kept.
_GUARD_MODULE_PATHS: dict[str, Path] = {
    "_budget_helpers": _TESTS_DIR / "_budget_helpers.py",
    "_band_proof": _TESTS_DIR / "_band_proof.py",
}

# {module: {pattern constant name pinned in this file}}.
_REGISTRY: dict[str, set[str]] = {
    "_budget_helpers": {"_WORKTREE_SEGMENT_RE", "_HISTORICAL_ID_RE"},
    "_band_proof": {"_BAND_LINE"},
}

# ---------------------------------------------------------------------------
# Specimens — each derived by calling the real production code path.
# ---------------------------------------------------------------------------


def _out_of_repo_worktree_specimen(
    name: str = "worktree-story-004",
) -> tuple[str, str]:
    """(plain project dir, worktree dir) for the resolvable-SMM placement:
    `{base}/{project-id}/worktrees/{name}`, obtained by actually calling
    `worktree.worktree_path` with a resolvable `SMM_DIR`."""
    with tempfile.TemporaryDirectory() as base:
        smm = Path(base) / "proj-abc" / "smm"
        smm.mkdir(parents=True)
        worktree._clear_git_root_cache()
        with patch.dict(os.environ, {"SMM_DIR": str(smm)}):
            wt = worktree.worktree_path(name, base)
        plain = smm.resolve().parent
        return str(plain), str(wt)


def _legacy_in_repo_worktree_specimen(
    name: str = "worktree-story-004",
) -> tuple[str, str]:
    """(plain git root, worktree dir) for the legacy in-repo placement:
    `{git_root}/.claude/worktrees/{name}`, reached by forcing
    `resolve_smm_dir()` to return None so `worktree_path` falls back."""
    with tempfile.TemporaryDirectory() as repo:
        init_repo(repo)
        worktree._clear_git_root_cache()
        with patch.object(_append_impl, "resolve_smm_dir", return_value=None):
            wt = worktree.worktree_path(name, repo)
        git_root = worktree.resolve_git_root(repo)
        assert git_root is not None
        return git_root, str(wt)


# ---------------------------------------------------------------------------
# Increment 1 — the registry's first two entries.
# ---------------------------------------------------------------------------


class TestWorktreeSegmentGuardIsPinned(unittest.TestCase):
    """`_WORKTREE_SEGMENT_RE` must match BOTH placements `worktree_path` can
    produce. It shipped `.claude/`-only, which matched neither for the whole
    span between the v5.0.0 data-root move and `bff57399` — every emitter
    budget measured longer inside a teammate worktree than in the main
    checkout, purely from path length, and cost two teammates a
    misdiagnosis each in one session.
    """

    def test_matches_the_out_of_repo_placement(self):
        _plain, wt = _out_of_repo_worktree_specimen()
        text = f"cwd={wt}/smm\n"
        self.assertRegex(text, _budget_helpers._WORKTREE_SEGMENT_RE)

    def test_matches_the_legacy_in_repo_placement(self):
        _plain, wt = _legacy_in_repo_worktree_specimen()
        text = f"cwd={wt}/smm\n"
        self.assertRegex(text, _budget_helpers._WORKTREE_SEGMENT_RE)


class TestHistoricalIdGuardIsPinned(unittest.TestCase):
    """`_HISTORICAL_ID_RE` is a DETECTOR, not a normalization: a non-match
    reports "no ids found", which reads exactly as green as a real absence.
    Pinned against an id taken from the generator, not typed — a hand-typed
    hex string can drift from whatever `generate_id` actually produces
    without either side noticing.
    """

    def test_matches_a_real_generated_id(self):
        real_id = event_builder.generate_id()
        text = f"See concern {real_id} for background.\n"
        match = _budget_helpers._HISTORICAL_ID_RE.search(text)
        self.assertIsNotNone(match, f"did not match a real generated id: {real_id!r}")
        assert match is not None
        self.assertEqual(match.group(0), real_id)


# ---------------------------------------------------------------------------
# Increment 2 — completeness: a new pattern must declare a specimen.
# ---------------------------------------------------------------------------


def _is_re_compile_call(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "compile"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "re"
    )


def _name_feeds_a_compile_call(tree: ast.Module, name: str) -> bool:
    """True when `name` is used as (part of) an argument to `re.compile(...)`
    anywhere in the module — catches a pattern compiled lazily and away from
    its own assignment (`_band_proof._BAND_LINE`, joined into a call inside
    `_band_line_re`), not only the `NAME = re.compile(...)` shape.
    """
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and _is_re_compile_call(node)):
            continue
        for arg in node.args:
            if any(isinstance(n, ast.Name) and n.id == name for n in ast.walk(arg)):
                return True
    return False


def pattern_shaped_constants(path: Path) -> set[str]:
    """Module-level constants that ARE a regex pattern, however they get
    there: bound straight to `re.compile(...)`, or a bare string literal fed
    into one elsewhere in the same module.

    AST, not a name-suffix convention (`_RE`, `_PATTERN`) — `_band_proof.py`'s
    `_BAND_LINE` carries neither suffix and is exactly the constant this shape
    exists to catch, once that module joins the scan (next increment).
    Modelled on the `ast.Call`-on-`ast.Attribute` shape in
    `tests/hooks/test_no_test_can_spawn_a_real_agent.py`.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name):
            continue
        is_bare_pattern_string = (
            isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
            and _name_feeds_a_compile_call(tree, target.id)
        )
        if _is_re_compile_call(node.value) or is_bare_pattern_string:
            names.add(target.id)
    return names


def _missing_registrations(
    modules: dict[str, Path], registry: dict[str, set[str]]
) -> dict[str, set[str]]:
    """{module: unregistered pattern names}, empty when the registry is
    complete for every module in `modules`."""
    gaps: dict[str, set[str]] = {}
    for name, path in modules.items():
        found = pattern_shaped_constants(path)
        gap = found - registry.get(name, set())
        if gap:
            gaps[name] = gap
    return gaps


class TestRegistryCompleteness(unittest.TestCase):
    """The leg that matters going forward — see the module docstring: the
    pins above prove today's two guards are alive; only this leg stops
    tomorrow's from arriving dead and unregistered.
    """

    def test_every_pattern_shaped_constant_in_the_covered_modules_is_registered(
        self,
    ):
        gaps = _missing_registrations(_GUARD_MODULE_PATHS, _REGISTRY)
        self.assertFalse(
            gaps,
            f"guard pattern(s) with no registered specimen: {gaps} — add a "
            "derived specimen and a _REGISTRY entry for each",
        )

    def test_registry_module_set_matches_the_covered_modules(self):
        """The registry's own keys must be exactly the modules this suite
        scans — a stray key with no scan target, or a scanned module with no
        key, both mean the two have drifted apart from each other."""
        self.assertEqual(set(_REGISTRY), set(_GUARD_MODULE_PATHS))

    def test_the_scan_is_not_vacuous(self):
        """A throwaway pattern in a fixture file the completeness check must
        actually name — proving the AST scan recognizes the shape, rather
        than passing because it scans nothing."""
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Path(tmp) / "_fixture_guard.py"
            fixture.write_text(
                "import re\n_THROWAWAY_RE = re.compile(r'x')\n", encoding="utf-8"
            )
            gaps = _missing_registrations({"_fixture_guard": fixture}, {})
            self.assertIn("_THROWAWAY_RE", gaps.get("_fixture_guard", set()))

    def test_a_registry_scoped_to_budget_helpers_alone_misses_band_line(self):
        """The scope decision, proven rather than argued: narrowing the
        registry to `_budget_helpers` alone — the naive cut, scoped to the
        one file this story is nominally about — leaves `_band_proof.py`'s
        `_BAND_LINE` unregistered even though the real scan target (this
        module's own `_GUARD_MODULE_PATHS`) already covers that file, and
        `_BAND_LINE` is the same class of guard as the other two. This is why
        the registry's module set names BOTH files, not just the one the
        story is nominally about.
        """
        narrow_registry = {"_budget_helpers": _REGISTRY["_budget_helpers"]}
        gaps = _missing_registrations(_GUARD_MODULE_PATHS, narrow_registry)
        self.assertIn("_BAND_LINE", gaps.get("_band_proof", set()))


# ---------------------------------------------------------------------------
# Increment 3 — _band_proof's message parser.
# ---------------------------------------------------------------------------


class _SpyCase(unittest.TestCase):
    """A throwaway TestCase to pass as the `testcase` arg of a budget assert,
    so its failure can be caught and read without polluting the outer test."""

    def runTest(self) -> None:
        pass


class TestBandLineGuardIsPinned(unittest.TestCase):
    """`_BAND_LINE` parses `band_offender`'s failure MESSAGE to recover a
    measured value. If the message's wording drifts, the regex matches
    nothing — the same failure as the other two, one level removed: it reads
    a value out of prose instead of a path or an id.
    """

    def test_matches_a_real_band_offender_message(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            (tmp_path / "SPEC.md").write_text("x" * 99, encoding="utf-8")
            with self.assertRaises(AssertionError) as caught:
                _budget_helpers.assert_md_under_budgets(
                    _SpyCase(), tmp_path, "*.md", {"SPEC": 100}, "test"
                )
        message = str(caught.exception)
        match = _band_proof._band_line_re("SPEC").search(message)
        self.assertIsNotNone(match, f"no band line for SPEC in: {message!r}")


if __name__ == "__main__":
    unittest.main()
