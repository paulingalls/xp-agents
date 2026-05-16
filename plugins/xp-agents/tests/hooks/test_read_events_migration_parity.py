#!/usr/bin/env python3
"""Story-005: parity + call-site enforcement for read_events_raw -> read_delta_full.

Two distinct guards:

- TestParity: byte-equal output between `_common.read_events_raw(smm_dir)`
  and `read_delta.read_delta_full(smm_dir, slug, update_watermark=False)[0]`
  for representative seeded events.jsonl (including a malformed-line case).
  Green at HEAD and forever — regression coverage for the migration claim
  that read_delta_full is a strict semantic superset.

- TestNoReadEventsRawCallers: per-script AST-walk asserting each migrated
  module uses `read_delta.read_delta_full` and does NOT call
  `_common.read_events_raw`. Empty at HEAD (Commit A); each commit B-E
  appends its entry to `_MIGRATED_SITES` atomically with the migration
  so the new test method is born green. Pins the audit-decision rationale
  into executable code — regression-proof against re-introducing
  `read_events_raw` at any migrated site.
"""

import ast
import json
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
    EVENT_TYPE_COMMIT,
    EVENT_TYPE_CONCERN,
    EVENT_TYPE_DECISION,
    EVENT_TYPE_STATUS,
)

_SCRIPTS_DIR = Path(__file__).parent.parent.parent / "scripts"
_SKILLS_DIR = Path(__file__).parent.parent.parent / "skills"

# Per-site call-site enforcement. Tuples: (test name, script path,
# optional function-name scope). Scoping concerns.py separates its two
# call sites so a regression in one is attributed by name.
#
# Sites are added here AS THEY MIGRATE — each migration commit appends
# its entries alongside the code change so the commit is atomically
# green. The roadmap is the 12 audit decisions in events.jsonl with
# topic 'read-events-raw-audit-*'.
_MIGRATED_SITES: list[tuple[str, Path, str | None]] = [
    (
        "load_events_with_resolutions",
        _SCRIPTS_DIR / "_common.py",
        "load_events_with_resolutions",
    ),
    ("session_end_warning", _SCRIPTS_DIR / "session_end_warning.py", None),
    ("sprint_stop_gate", _SCRIPTS_DIR / "sprint_stop_gate.py", None),
    ("lint_resolution", _SCRIPTS_DIR / "lint_resolution.py", None),
    (
        "concerns_has_unresolved",
        _SCRIPTS_DIR / "concerns.py",
        "has_unresolved_concerns",
    ),
    (
        "concerns_resolve",
        _SCRIPTS_DIR / "concerns.py",
        "resolve_concerns",
    ),
    ("subagent_stop", _SCRIPTS_DIR / "subagent_stop.py", None),
    ("teammate_idle", _SCRIPTS_DIR / "teammate_idle.py", None),
    ("tdd_stop_gate", _SCRIPTS_DIR / "tdd_stop_gate.py", None),
    ("task_completed", _SCRIPTS_DIR / "task_completed.py", None),
    ("post_tool_use", _SCRIPTS_DIR / "post_tool_use.py", None),
    (
        "bash_post_tool",
        _SCRIPTS_DIR / "bash_post_tool.py",
        "_prior_commit_was_test_only",
    ),
    (
        "debt_for_files",
        _SKILLS_DIR / "xp-quality-review" / "scripts" / "debt_for_files.py",
        None,
    ),
    (
        "open_plan_concerns",
        _SKILLS_DIR / "xp-quality-review" / "scripts" / "open_plan_concerns.py",
        None,
    ),
    (
        "work_selection_decide",
        _SKILLS_DIR / "xp-work-selection" / "scripts" / "work_selection_decide.py",
        None,
    ),
]


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


def _calls_attribute(scope: ast.AST, qualname_options: tuple[str, ...]) -> bool:
    """True if any Call inside `scope` matches one of `qualname_options`.

    Options are dotted paths matched against ast.Attribute chains.
    A bare option name also matches a same-named ast.Name call (covers
    `from _common import read_events_raw` style).
    """
    for node in ast.walk(scope):
        if not isinstance(node, ast.Call):
            continue
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
            if dotted in qualname_options:
                return True
        elif isinstance(func, ast.Name):
            for opt in qualname_options:
                if opt == func.id or opt.endswith("." + func.id):
                    return True
    return False


class TestParity(_SMMTestCase):
    """`read_events_raw` and `read_delta_full[0]` return byte-equal lists."""

    def _seed_representative(self) -> None:
        events = [
            make_event(EVENT_TYPE_CONCERN, content="Bug 1", files=["a.py"]),
            make_event(EVENT_TYPE_DECISION, content="Use REST", topic="t"),
            make_event(EVENT_TYPE_STATUS, content="Working", working_on=["a.py"]),
            make_event(EVENT_TYPE_COMMIT, content="commit msg", files=["a.py"]),
            make_event(
                EVENT_TYPE_CONCERN,
                content="Bug 2",
                files=["b.py"],
                metadata={"resolves": ["bug-1"]},
            ),
        ]
        self._write_events(events)

    def _assert_parity(self, expected_count: int) -> None:
        """Both readers see the same event list with the expected count."""
        unlocked = _common.read_events_raw(self.smm_dir)
        full = read_delta.read_delta_full(
            self.smm_dir, "parity-test", update_watermark=False
        )[0]

        self.assertEqual(unlocked, full)
        self.assertEqual(len(unlocked), expected_count)

    def test_parity_well_formed(self):
        self._seed_representative()
        self._assert_parity(expected_count=5)

    def test_parity_with_malformed_lines(self):
        """parse_jsonl is shared — both readers skip malformed lines identically."""
        good = make_event(EVENT_TYPE_CONCERN, content="good")
        decision = make_event(EVENT_TYPE_DECISION, content="ok", topic="t")
        self._write_raw_lines(
            [
                json.dumps(good),
                "not-json-at-all",
                "",
                '{"partial":',
                "[]",
                json.dumps(decision),
            ]
        )
        self._assert_parity(expected_count=2)

    def test_parity_empty(self):
        self._assert_parity(expected_count=0)


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
    """Per-site enforcement. Methods generated from `_MIGRATED_SITES`."""

    def _assert_site_migrated(self, script_path: Path, scope_name: str | None) -> None:
        source = script_path.read_text()
        tree: ast.AST = ast.parse(source)

        if scope_name is not None:
            found = _function_node(tree, scope_name)
            if found is None:
                self.fail(
                    f"{script_path.name}: scope function {scope_name!r} not found"
                )
            scope: ast.AST = found
        else:
            scope = tree

        uses_old = _calls_attribute(
            scope,
            ("_common.read_events_raw",),
        )
        uses_new = _calls_attribute(
            scope,
            (
                "read_delta.read_delta_full",
                "_common.read_events_locked",
            ),
        )

        scope_desc = f" in function {scope_name!r}" if scope_name else ""
        self.assertFalse(
            uses_old,
            f"{script_path.name}{scope_desc} still calls "
            f"read_events_raw — migrate to read_delta.read_delta_full",
        )
        self.assertTrue(
            uses_new,
            f"{script_path.name}{scope_desc} must call "
            f"read_delta.read_delta_full or _common.read_events_locked",
        )


def _make_method(path: Path, scope: str | None):
    def _test(self):
        self._assert_site_migrated(path, scope)

    return _test


for _name, _path, _scope in _MIGRATED_SITES:
    _method = _make_method(_path, _scope)
    _method.__name__ = f"test_{_name}_uses_read_delta_full"
    setattr(TestNoReadEventsRawCallers, _method.__name__, _method)


if __name__ == "__main__":
    unittest.main()
