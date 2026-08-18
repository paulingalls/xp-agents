#!/usr/bin/env python3
"""Pins for guards whose non-match reads as success.

`_WORKTREE_SEGMENT_RE` and `assert_emitter_under_budgets`'s missing
`normalize_paths` (both `_budget_helpers.py`) were dead for a whole release
span: a regex written for `/.claude/worktrees/<dir>` stopped matching once
worktrees moved under the data root in v5.0.0, and a normalization never wired
in normalized nothing. Neither raised — a pattern matching nothing looks exactly
like success. `bff57399` fixed both; this module stops the CLASS recurring.

Every specimen is DERIVED by calling production (`worktree.worktree_path`,
`event_builder.generate_id`, the failure message `assert_md_under_budgets`
raises), never hand-typed: a literal drifts independently of the pattern it
pins, so both go stale together and the pin stays green — the same defect one
layer up. That is why the retired
`test_measured_len_normalizes_the_real_worktree_layout` in
`test_budget_helpers_shim.py` is folded into `TestWorktreeSegmentGuardIsPinned`.

Those pins only prove TODAY's guards are alive. The leg aimed at the NEXT one is
`TestRegistryCompleteness`: it AST-scans every covered module and fails when a
pattern-shaped constant has no registry entry, so the hand-kept list of pattern
NAMES cannot drift for any shape the scan sees — a module-level name bound to
`re.compile(...)`, or one reaching a `re.compile` pattern argument elsewhere in
the module, annotated or not, whatever expression carries it there. Named rather
than implied, it does NOT see a pattern that binds no module-level name
(compiled inside a function or class body), nor a FRAGMENT reaching
`re.compile` only through another constant — a fragment is not separately
pinnable. And an entry is a promise, not a proof: nothing checks that a
registered NAME has a pin.

Hand-kept deliberately: the SET of modules covered (`_REGISTRY`'s keys). Adding
a guard to an existing module is a one-line, easy-to-forget change, so that leg
has to be automatic; adding a new module of guards is a visible,
new-file-sized event.
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
from _bases import _AssertNotNoneMixin
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
# The path-normalizing regex and the id detector.
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

    def test_stripping_the_segment_collapses_to_the_plain_checkout(self):
        """Folds in `test_budget_helpers_shim.py`'s retired
        `test_measured_len_normalizes_the_real_worktree_layout` — same claim
        (a worktree-inflated measurement must equal the plain one), but the
        worktree path is DERIVED from `worktree.worktree_path` for both
        placements rather than hand-typed. A hand-typed literal drifts from
        the pattern independently, which is how the pattern went dead for a
        whole release span without either side going red.
        """
        for plain, wt in (
            _out_of_repo_worktree_specimen(),
            _legacy_in_repo_worktree_specimen(),
        ):
            with self.subTest(wt=wt):
                inside_worktree = f"SMM_DIR={wt}/smm\n".encode()
                from_plain_checkout = f"SMM_DIR={plain}/smm\n".encode()
                self.assertEqual(
                    _budget_helpers._measured_len(inside_worktree),
                    _budget_helpers._measured_len(from_plain_checkout),
                    "the worktrees segment must be stripped regardless of "
                    "which placement produced it",
                )


class TestHistoricalIdGuardIsPinned(_AssertNotNoneMixin, unittest.TestCase):
    """`_HISTORICAL_ID_RE` is a DETECTOR, not a normalization: a non-match
    reports "no ids found", which reads exactly as green as a real absence.
    Pinned against an id taken from the generator, not typed — a hand-typed
    hex string can drift from whatever `generate_id` actually produces
    without either side noticing.
    """

    def test_matches_a_real_generated_id(self):
        real_id = event_builder.generate_id()
        text = f"See concern {real_id} for background.\n"
        match = self._assert_not_none(
            _budget_helpers._HISTORICAL_ID_RE.search(text),
            f"did not match a real generated id: {real_id!r}",
        )
        self.assertEqual(match.group(0), real_id)


# ---------------------------------------------------------------------------
# Completeness — a new pattern must declare a specimen.
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
    """True when `name` is used as (part of) the PATTERN argument of a
    `re.compile(...)` anywhere in the module — catches a pattern compiled
    lazily and away from its own assignment (`_band_proof._BAND_LINE`, joined
    into a call inside `_band_line_re`), not only the `NAME = re.compile(...)`
    shape.

    The first positional argument only, not every argument: `re.compile(pat,
    _FLAGS)` would otherwise report a flags constant as a pattern, and a
    registry entry for something that is not a guard is noise a reader has to
    disprove.
    """
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not _is_re_compile_call(node):
            continue
        if not node.args:
            continue
        pattern_arg = node.args[0]
        if any(isinstance(n, ast.Name) and n.id == name for n in ast.walk(pattern_arg)):
            return True
    return False


def _assigned_name_and_value(node: ast.stmt) -> tuple[str, ast.expr] | None:
    """(name, value) for a module-level assignment to ONE bare name, whether
    it is annotated or not — else None.

    Both shapes, because `ast.AnnAssign` is a distinct node type and NOT a
    subclass of `ast.Assign`: a scan matching only the latter is blind to
    `_NEW_RE: re.Pattern[str] = re.compile(...)`, which is how this repo
    idiomatically writes a module constant (CLAUDE.md mandates type hints;
    `_spawn_guard._NON_MODEL_SUBCOMMANDS` is the precedent). Blind, and
    SILENTLY so — it would report every pattern registered while seeing none
    of them, which is the failure this whole module exists to stop.

    `AnnAssign.value` is None for a bare declaration (`x: int`), so the
    pattern below requires a value rather than assuming one.
    """
    match node:
        case ast.Assign(targets=[ast.Name(id=name)], value=value):
            return name, value
        case ast.AnnAssign(target=ast.Name(id=name), value=ast.expr() as value):
            return name, value
    return None


def pattern_shaped_constants(path: Path) -> set[str]:
    """Module-level constants that ARE a regex pattern, however they get
    there: bound straight to `re.compile(...)`, or reaching one's pattern
    argument elsewhere in the same module — annotated or not, and whatever
    expression shape carries them there (a bare literal, a join, an f-string).

    Keyed on where the value ENDS UP, not on the node type of the value, since
    the second is what a new guard varies for free: `_A + _B` and `f"{_A}x"`
    are neither of them a `Constant`, and a scan that required one would go
    silently blind the first time a pattern was assembled rather than typed.

    AST, not a name-suffix convention (`_RE`, `_PATTERN`) — `_band_proof.py`'s
    `_BAND_LINE` carries neither suffix and is exactly the constant this shape
    exists to catch. Modelled on the `ast.Call`-on-`ast.Attribute` shape in
    `tests/hooks/test_no_test_can_spawn_a_real_agent.py`.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in tree.body:
        assigned = _assigned_name_and_value(node)
        if assigned is None:
            continue
        name, value = assigned
        if _is_re_compile_call(value) or _name_feeds_a_compile_call(tree, name):
            names.add(name)
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

    def test_the_scan_sees_an_ANNOTATED_pattern_constant(self):
        """The shape that nearly got away, and the one most likely to be used
        NEXT: an annotated assignment.

        `ast.AnnAssign` is a distinct node type, not a subclass of `ast.Assign`
        — a scan that walks only the latter reports "everything registered"
        while seeing nothing. It matters here more than it would elsewhere:
        CLAUDE.md mandates type hints and `_spawn_guard.py` already writes its
        module constants annotated, so the IDIOMATIC way to add a guard was
        the one way to evade the check that exists to catch it. A new guard
        added the normal way would have arrived unregistered with this suite
        green — this module's own failure mode, one level up, inside its fix.
        """
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Path(tmp) / "_annotated_guard.py"
            fixture.write_text(
                "import re\n"
                '_ANNOTATED_RE: re.Pattern[str] = re.compile(r"x")\n'
                '_ANNOTATED_BARE: str = r"y"\n'
                "def _use() -> re.Pattern[str]:\n"
                "    return re.compile(_ANNOTATED_BARE)\n",
                encoding="utf-8",
            )
            found = pattern_shaped_constants(fixture)
        self.assertEqual(
            found,
            {"_ANNOTATED_RE", "_ANNOTATED_BARE"},
            "annotated pattern constants are invisible to the scan",
        )

    def test_the_scan_sees_a_COMPOSED_pattern_constant(self):
        """A pattern assembled rather than written whole still reaches
        `re.compile`, so it is still a guard whose non-match reads as success —
        and `_band_proof` already assembles one (`re.escape(surface) +
        _BAND_LINE`), so this is the shape a second one would copy. Both
        joined-literal and f-string forms have to be visible, because neither
        is a `Constant`: a scan keyed on the VALUE's node type sees them as
        ordinary expressions, and only what reaches the compile call is
        evidence.
        """
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Path(tmp) / "_composed_guard.py"
            fixture.write_text(
                "import re\n"
                '_HEAD = r"/(?:\\.claude/)?"\n'
                '_JOINED = _HEAD + r"worktrees/[^/]+"\n'
                '_INTERPOLATED = f"{_HEAD}data/[^/]+"\n'
                "def _use() -> list[re.Pattern[str]]:\n"
                "    return [re.compile(_JOINED), re.compile(_INTERPOLATED)]\n",
                encoding="utf-8",
            )
            found = pattern_shaped_constants(fixture)
        self.assertEqual(
            found,
            {"_JOINED", "_INTERPOLATED"},
            "a composed pattern constant is invisible to the scan; a FRAGMENT "
            "that reaches re.compile only through another constant (_HEAD) is "
            "deliberately not named — it is not separately pinnable",
        )

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
# The message parser in `_band_proof`.
# ---------------------------------------------------------------------------


class TestBandLineGuardIsPinned(_AssertNotNoneMixin, unittest.TestCase):
    """`_BAND_LINE` parses `band_offender`'s failure MESSAGE to recover a
    measured value. If the message's wording drifts, the regex matches
    nothing — the same failure as the other two, one level removed: it reads
    a value out of prose instead of a path or an id.
    """

    def test_matches_a_real_band_offender_message(self):
        chars, budget = 99, 100
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            (tmp_path / "SPEC.md").write_text("x" * chars, encoding="utf-8")
            with self.assertRaises(AssertionError) as caught:
                _budget_helpers.assert_md_under_budgets(
                    _band_proof.spy_case(), tmp_path, "*.md", {"SPEC": budget}, "test"
                )
        message = str(caught.exception)
        match = self._assert_not_none(
            _band_proof._band_line_re("SPEC").search(message),
            f"no band line for SPEC in: {message!r}",
        )
        # Matching is not enough: every band proof reads these three groups
        # POSITIONALLY, so a reordered or re-grouped pattern still matches
        # while handing `assert_band_fired` the wrong numbers to judge.
        self.assertEqual(
            (int(match[1]), int(match[3])),
            (chars, budget),
            f"chars/budget groups recovered wrongly from: {message!r}",
        )
        self.assertAlmostEqual(
            float(match[2]),
            chars / budget * 100,
            places=1,
            msg=f"percentage group recovered wrongly from: {message!r}",
        )


if __name__ == "__main__":
    unittest.main()
