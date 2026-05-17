#!/usr/bin/env python3
"""Sprint-087 M-5: enforcement guards for the retired `read_events_raw`.

Three guards remain after the function's retirement:

- TestReadEventsLocked: contract tests for `_common.read_events_locked`,
  the canonical helper for the `read_delta_full(..., update_watermark=False)[0]`
  pattern. Covers empty/missing/malformed cases at the wrapper boundary.

- TestNoReadEventsRawCallers: negative-space AST guard asserting NO
  caller of `_common.read_events_raw` exists anywhere under
  `plugins/xp-agents/`. The function is gone; this catches any
  re-introduction.

- TestNoInlineCanonicalReadDeltaFull: the canonical locked-read pattern
  (`read_delta_full(..., update_watermark=False)[0]`) may appear only
  inside `_common.read_events_locked` itself. Every other caller must
  route through the helper.
"""

import ast
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import _common
import read_delta
from _bases import _SMMTestCase
from _event_fixtures import make_event
from event_schema import (
    EVENT_TYPE_CONCERN,
    EVENT_TYPE_DECISION,
    EVENT_TYPE_STATUS,
)

_SCRIPTS_DIR = Path(__file__).parent.parent.parent / "scripts"
_SKILLS_DIR = Path(__file__).parent.parent.parent / "skills"
_PLUGIN_ROOT = _SCRIPTS_DIR.parent


def _function_node(
    tree: ast.AST, name: str
) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    """First function-def named `name`. Assumes unique names within the module."""
    for node in ast.walk(tree):
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == name
        ):
            return node
    return None


def _call_matches_qualname(node: ast.Call, qualname_options: tuple[str, ...]) -> bool:
    """True if `node.func` matches one of `qualname_options`.

    Options are dotted paths matched against ast.Attribute chains.
    A bare option name also matches a same-named ast.Name call (covers
    `from <module> import <name>` style).
    """
    func = node.func
    if isinstance(func, ast.Attribute):
        chain = []
        cur: ast.AST = func
        while isinstance(cur, ast.Attribute):
            chain.append(cur.attr)
            cur = cur.value
        if isinstance(cur, ast.Name):
            chain.append(cur.id)
        dotted = ".".join(reversed(chain))
        return dotted in qualname_options
    if isinstance(func, ast.Name):
        for opt in qualname_options:
            if opt == func.id or opt.endswith("." + func.id):
                return True
    return False


def _calls_attribute(scope: ast.AST, qualname_options: tuple[str, ...]) -> bool:
    """True if any Call inside `scope` matches one of `qualname_options`."""
    for node in ast.walk(scope):
        if isinstance(node, ast.Call) and _call_matches_qualname(
            node, qualname_options
        ):
            return True
    return False


_READ_DELTA_FULL_QUALNAMES = ("read_delta.read_delta_full",)


def _has_update_watermark_false(node: ast.Call) -> bool:
    """True if call has an `update_watermark=False` kwarg."""
    for kw in node.keywords:
        if (
            kw.arg == "update_watermark"
            and isinstance(kw.value, ast.Constant)
            and kw.value.value is False
        ):
            return True
    return False


class TestReadEventsLocked(_SMMTestCase):
    """`_common.read_events_locked` is the canonical helper for the
    `read_delta_full(smm_dir, slug, update_watermark=False)[0]` pattern.
    """

    _SLUG = "read-events-locked-test"

    def test_returns_same_list_as_inline_form(self):
        events = [
            make_event(EVENT_TYPE_CONCERN, content="C1", files=["a.py"]),
            make_event(EVENT_TYPE_DECISION, content="D1", topic="t"),
            make_event(EVENT_TYPE_STATUS, content="S1", working_on=["a.py"]),
        ]
        self._write_events(events)

        helper_result = _common.read_events_locked(self.smm_dir, self._SLUG)
        inline_result = read_delta.read_delta_full(
            self.smm_dir, self._SLUG, update_watermark=False
        )[0]

        self.assertEqual(helper_result, inline_result)
        self.assertEqual(len(helper_result), 3)

    def test_returns_empty_list_when_no_events(self):
        self.assertEqual(_common.read_events_locked(self.smm_dir, self._SLUG), [])

    def test_does_not_advance_watermark(self):
        """`update_watermark=False` is wired: watermark file stays absent."""
        events = [make_event(EVENT_TYPE_CONCERN, content="C1", files=["a.py"])]
        self._write_events(events)
        watermark_file = self.smm_dir / f".watermark-{self._SLUG}"
        self.assertFalse(watermark_file.exists())

        _common.read_events_locked(self.smm_dir, self._SLUG)

        self.assertFalse(watermark_file.exists())

    def test_ast_recognizer_accepts_helper_pattern(self):
        """`_calls_attribute` matches both dotted and bare helper call shapes."""
        dotted_src = "import _common\n_common.read_events_locked(p, 'x')\n"
        bare_src = (
            "from _common import read_events_locked\nread_events_locked(p, 'x')\n"
        )

        accepted = ("_common.read_events_locked",)
        self.assertTrue(_calls_attribute(ast.parse(dotted_src), accepted))
        self.assertTrue(_calls_attribute(ast.parse(bare_src), accepted))


class TestNoReadEventsRawCallers(unittest.TestCase):
    """Negative-space guard: `_common.read_events_raw` is retired (sprint-087
    M-5). No caller may exist anywhere under `plugins/xp-agents/`. This test
    catches re-introduction at any new or existing site.
    """

    def test_no_callers_anywhere_under_plugin(self):
        violations: list[str] = []
        for path in _PLUGIN_ROOT.rglob("*.py"):
            tree: ast.AST = ast.parse(path.read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and _call_matches_qualname(
                    node, ("_common.read_events_raw",)
                ):
                    rel = path.relative_to(_PLUGIN_ROOT.parent)
                    violations.append(f"{rel}:{node.lineno}")
        self.assertEqual(
            violations,
            [],
            "_common.read_events_raw is retired — migrate callers to "
            f"_common.read_events_locked: {violations}",
        )


class TestNoInlineCanonicalReadDeltaFull(unittest.TestCase):
    """The canonical `read_delta_full(...update_watermark=False)[0]` pattern
    may only appear inside `_common.read_events_locked`. Every other caller
    must route through the helper. `prompt_nugget.py` is naturally exempt
    because it omits `update_watermark=False` (intentionally advances the
    watermark and uses both tuple elements).
    """

    def test_no_inline_canonical_pattern_in_scripts_and_skills(self):
        helper_path = (_SCRIPTS_DIR / "_common.py").resolve()
        violations: list[str] = []
        for path in list(_SCRIPTS_DIR.rglob("*.py")) + list(_SKILLS_DIR.rglob("*.py")):
            tree: ast.AST = ast.parse(path.read_text())
            skip_lo, skip_hi = 0, 0
            if path.resolve() == helper_path:
                helper_fn = _function_node(tree, "read_events_locked")
                if helper_fn is not None:
                    skip_lo = helper_fn.lineno
                    skip_hi = helper_fn.end_lineno or helper_fn.lineno
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                if skip_lo and skip_lo <= node.lineno <= skip_hi:
                    continue
                if not _call_matches_qualname(node, _READ_DELTA_FULL_QUALNAMES):
                    continue
                if _has_update_watermark_false(node):
                    rel = path.relative_to(_SCRIPTS_DIR.parent)
                    violations.append(f"{rel}:{node.lineno}")
        self.assertEqual(
            violations,
            [],
            f"Inline read_delta_full(...update_watermark=False) outside "
            f"_common.read_events_locked: {violations}",
        )


if __name__ == "__main__":
    unittest.main()
