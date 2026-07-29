#!/usr/bin/env python3
"""Pin: conftest re-exports are the single source of truth for shared fixtures.

Resolves prior duplication concerns (split_frontmatter, _MARKERS_PY,
raw sys.path.insert in test files).

Three pins:

(a) Exactly one canonical `_split_frontmatter_body` definition under
    plugins/xp-agents/tests/ (excludes scaffold/_helpers.py whose
    `frontmatter_body()` is a deliberately separate copy because the
    scaffold suite has its own conftest path setup).
(b) Exactly one canonical `_MARKERS_PY = ` definition under
    plugins/xp-agents/tests/.
(c) test_retro_flag_cascade.py does not re-introduce the raw
    `sys.path.insert(... "smm")` line that this story removed in favor
    of the conftest re-export. Pin is scoped to that one file rather
    than the whole tree because most other tests still do their own
    smm sys.path.insert today; promoting them is future work, not
    story-016 scope.

Behavior of the re-exports themselves is covered by the existing
test_retro_flag_cascade.py + test_close_cycle.py + test_markers_cli.py
suites; they continue to pass after the migration. This pin only
enforces the no-duplication invariant so a future contributor can't
silently re-introduce a local copy.
"""

import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from _pin_helpers import files_to_scan

_TESTS_DIR = Path(__file__).parent.parent
_SCAFFOLD_DIR = _TESTS_DIR / "scaffold"

# Every .py file under tests/ (story-001 dropped `files_to_scan`'s
# test_*/_*/conftest.py name filter, so shared test-base modules and
# `__init__.py` are candidates too — strictly more places a duplicate
# definition can hide). scaffold/ excluded: that suite is intentionally
# isolated.
_CANDIDATES: list[Path] = [
    p
    for p in files_to_scan(_TESTS_DIR, Path(__file__))
    if _SCAFFOLD_DIR not in p.parents
]

# Read each file once, share across tests — keeps the pin under 50ms even
# as the test tree grows.
_FILE_TEXTS: dict[Path, str] = {p: p.read_text(encoding="utf-8") for p in _CANDIDATES}


def _files_matching(pattern: str) -> list[Path]:
    rx = re.compile(pattern, re.MULTILINE)
    return [p for p, text in _FILE_TEXTS.items() if rx.search(text)]


class TestConftestConsolidation(unittest.TestCase):
    def test_single_split_frontmatter_body_definition(self):
        hits = _files_matching(r"^def _split_frontmatter_body\b")
        self.assertEqual(
            len(hits),
            1,
            f"_split_frontmatter_body should be defined exactly once "
            f"(in tests/_md_helpers.py); found in: {[str(p) for p in hits]}",
        )
        self.assertEqual(hits[0].name, "_md_helpers.py")

    def test_single_markers_py_constant_definition(self):
        # Home is `_paths.py` (the leaf of the tests/ import graph), not `_bases.py`
        # — `_bases` re-exports it by identity, so every `from _bases import
        # _MARKERS_PY` still resolves. The invariant pinned here is the one that
        # matters: ONE definition, never a copy-paste into a second test module.
        hits = _files_matching(r"^_MARKERS_PY\s*=\s*")
        self.assertEqual(
            len(hits),
            1,
            f"_MARKERS_PY should be defined exactly once (in tests/_paths.py); "
            f"found in: {[str(p) for p in hits]}",
        )
        self.assertEqual(hits[0].name, "_paths.py")

    def test_single_mixin_base_definition(self):
        # Story-020: _MixinBase (TYPE_CHECKING shim that lets pyright see
        # unittest.TestCase while pytest skips collecting empty mixins) was
        # defined inline in 3 sites — _close_fixtures.py, integration/
        # test_preload_markers.py, hooks/test_auto_resolve.py. Promote to
        # tests/_test_typing.py so the pattern lives in one place.
        # Story-002 follow-up: catches the rename gap too — any
        # `<Anything>Base = unittest.TestCase` line under a TYPE_CHECKING
        # branch is the same pattern under a different name and should
        # be replaced by an `import _MixinBase` instead. `\s+` (any
        # leading whitespace, not exactly 4) so a copy-paste under
        # TYPE_CHECKING (4-space), inside a class body (8-space), or
        # under a tab-indented block all trip the pin. A zero-indent
        # top-level `Base = unittest.TestCase` is NOT caught here — but
        # that shape is not the TYPE_CHECKING shim pattern anyway (no
        # if-branch wraps it), so it would be a class alias, not a
        # mixin shim, and out of scope for this pin.
        hits = _files_matching(r"^\s+\w*Base\s*=\s*unittest\.TestCase")
        self.assertEqual(
            len(hits),
            1,
            f"_MixinBase TYPE_CHECKING shim should be defined exactly once "
            f"(in tests/_test_typing.py); a renamed alias of the same shape "
            f"is also a duplicate — import _MixinBase instead. Found in: "
            f"{[str(p) for p in hits]}",
        )
        self.assertEqual(hits[0].name, "_test_typing.py")

    def test_single_pipe_stdin_mixin_definition(self):
        # Story-008: _PipeStdinMixin (os.pipe-backed fake stdin, the only
        # harness the fd-driven output filter can be tested through) was
        # copy-pasted byte-for-byte into a second streaming test file.
        # Promote to tests/_stream_stdin_fixtures.py so the next streaming
        # test imports it instead of pasting a third fd-lifecycle copy —
        # each copy owns real fds and a sys.stdin swap, so a divergent one
        # leaks fds across the whole session.
        hits = _files_matching(r"^class _PipeStdinMixin\b")
        self.assertEqual(
            len(hits),
            1,
            f"_PipeStdinMixin should be defined exactly once "
            f"(in tests/_stream_stdin_fixtures.py); found in: "
            f"{[str(p) for p in hits]}",
        )
        self.assertEqual(hits[0].name, "_stream_stdin_fixtures.py")

    def test_single_lint_tmpdir_mixin_definition(self):
        # Story-020 phase 2: _LintTmpDirMixin (setUp/tearDown that creates a
        # tmpdir with ruff.toml and rmtree's it) was defined inline in
        # tests/hooks/test_auto_resolve.py and has 13 hand-rolled equivalents
        # in tests/hooks/test_lint.py. Promote to tests/_lint_fixtures.py
        # so consumers share the fixture instead of pasting the boilerplate.
        hits = _files_matching(r"^class _LintTmpDirMixin\b")
        self.assertEqual(
            len(hits),
            1,
            f"_LintTmpDirMixin should be defined exactly once "
            f"(in tests/_lint_fixtures.py); found in: {[str(p) for p in hits]}",
        )
        self.assertEqual(hits[0].name, "_lint_fixtures.py")

    def test_single_normalize_path_identity_mixin_definition(self):
        # Free-session debt-burndown: the identity stub
        # `lambda p, _cwd: p` for `worktree.normalize_path` was inlined
        # across many test sites. The setUp-mixin variant lives in
        # tests/_worktree_fixtures.py — scoped `with patch(...)` blocks
        # in test_action_vocabulary_smoke / test_bash_commit_qr_linkage
        # are deliberately out of scope (different shape, mixin doesn't
        # fit). This pin guards the canonical class against re-inlining.
        hits = _files_matching(r"^class _NormalizePathIdentityMixin\b")
        self.assertEqual(
            len(hits),
            1,
            f"_NormalizePathIdentityMixin should be defined exactly once "
            f"(in tests/_worktree_fixtures.py); found in: "
            f"{[str(p) for p in hits]}",
        )
        self.assertEqual(hits[0].name, "_worktree_fixtures.py")

    def test_test_lint_does_not_hand_roll_ruff_toml_tmpdir(self):
        # Acceptance #3 for story-020 phase 2: after migration, the
        # mkdtemp+ruff.toml.touch() pair in test_lint*.py should drop to
        # ≤2 occurrences per file (tolerates genuinely-different shapes
        # like a `tmpdir / "nonexistent"` non-ruff.toml path or a class
        # whose tests intentionally vary which config file is present).
        # Counts the closer-to-source signal directly: it is impossible
        # to have N hand-rolled pairs without N `(... / "ruff.toml").touch()`
        # lines and at least N `tempfile.mkdtemp()` calls in the file —
        # the min of the two upper-bounds the pair count.
        for fname in ("test_lint.py", "test_lint_detection.py"):
            text = _FILE_TEXTS[_TESTS_DIR / "hooks" / fname]
            mkdtemp = text.count("tempfile.mkdtemp()")
            ruff_touch = text.count('"ruff.toml").touch()')
            pairs = min(mkdtemp, ruff_touch)
            self.assertLessEqual(
                pairs,
                2,
                f"{fname} still hand-rolls {pairs} mkdtemp+ruff.toml "
                f"pairs (mkdtemp={mkdtemp}, ruff_touch={ruff_touch}) "
                "— migrate to _LintTmpDirMixin.",
            )

    def test_single_xp_preload_path_constant_definitions(self):
        # Resolves prior duplication: _XP_ACCEPT_PRELOAD and
        # _XP_STORY_CLOSE_PRELOAD path constants were duplicated across 3
        # integration test files. Hoist to
        # tests/integration/conftest.py so a single canonical site owns
        # the path. Pin scoped to integration/ — the constants are
        # integration-suite-only by purpose. One regex with alternation
        # so the file walk happens once, matching sibling pins.
        integration_dir = _TESTS_DIR / "integration"
        const_re = r"^(_XP_ACCEPT_PRELOAD|_XP_STORY_CLOSE_PRELOAD)\s*=\s*"
        hits = [p for p in _files_matching(const_re) if integration_dir in p.parents]
        self.assertEqual(
            len(hits),
            1,
            "_XP_ACCEPT_PRELOAD / _XP_STORY_CLOSE_PRELOAD should be defined "
            f"exactly once under tests/integration/ (in conftest.py); "
            f"found in: {[str(p) for p in hits]}",
        )
        self.assertEqual(hits[0].name, "conftest.py")

    def test_retro_flag_cascade_does_not_reintroduce_smm_sys_path_insert(self):
        # Story-016 removed a raw `sys.path.insert(... "smm")` from
        # test_retro_flag_cascade.py in favor of the conftest re-export.
        # Pin only that file: most other tests in the tree still do their
        # own sys.path.insert for smm/scripts, and broadening this pin
        # would assert an invariant that does not hold today (and would
        # silently pass via a broken regex if scoped tree-wide — see
        # commit history before this fix).
        path = _TESTS_DIR / "integration" / "test_retro_flag_cascade.py"
        text = path.read_text(encoding="utf-8")
        # `.*` (not `[^)]*`) is required: real lines look like
        # `sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))`
        # — `[^)]*` would stop at the first `)` from `Path(__file__)`
        # and never reach the `smm` token, vacuously passing.
        rx = re.compile(r"sys\.path\.insert\b.*\bsmm\b")
        self.assertIsNone(
            rx.search(text),
            f"{path.name}: re-introduced raw sys.path.insert for smm/. "
            "Use the conftest re-export (compute_resolutions, "
            "EVENT_TYPE_CONCERN, etc.) instead.",
        )


if __name__ == "__main__":
    unittest.main()
