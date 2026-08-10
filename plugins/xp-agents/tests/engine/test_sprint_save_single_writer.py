#!/usr/bin/env python3
"""sprint_save is a library with one whole-sprint door, and no entrypoint.

Its module docstring used to argue this in prose: that a second
`python3 sprint_save.py < payload` door would reach run() without the
CLI-layer re-slice preserve and silently re-drop every recorded branch_name.
The argument is history and stays there; the three facts it rests on are
checkable and live here.

LIMITS. The writer scan reads the shipped tree's AST, so it sees a call by the
name it is written under — plain `save_sprint(...)` or `<module>.save_sprint(...)`.
It cannot see a writer reached through a rebinding (`w = save_sprint`), a
`getattr` lookup, or an `exec`. Nothing in the tree does that today; a future
one would pass this pin while breaking the claim, and only the behavioral leg
below would notice, and only if it ran through run().
"""

import ast
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import sprint_save
import sprint_store
from _pin_helpers import rel, shipped_files_by_root
from conftest import _PLUGIN_ROOT, _SMMTestCase, make_sprint_dict, make_story_dict

_REPO_ROOT = _PLUGIN_ROOT.parent.parent
_SPRINT_SAVE = _PLUGIN_ROOT / "smm" / "sprint_save.py"

# Every function in the shipped tree that reaches the whole-sprint atomic write,
# with the reason each is not a second whole-sprint door. A new entry here is a
# claim that must be argued, not a number to bump.
_KNOWN_WRITERS = {
    "sprint_store.set_branch": "writes one field onto the sprint it just loaded",
    "sprint_store.set_story_branch": "writes one field onto a story it just loaded",
    "sprint_store.edit_story": "shallow-merges updates into a story it just loaded",
    "sprint_transitions._write_story_status": "flips one story's status under the lock",
    "sprint_save.save": "the side-effect-free half of run(); no other caller",
}


def _callee_name(node: ast.Call) -> str | None:
    """The final name segment of a call's callee.

    Both spellings must match. `sprint_save.py` calls
    `sprint_store.save_sprint(...)` (an `ast.Attribute`); `sprint_store` and
    `sprint_transitions` import the symbol and call `save_sprint(...)` bare (an
    `ast.Name`), and `sprint_transitions` does that import INSIDE the function,
    where a module-level import scan would not find it either.
    """
    match node.func:
        case ast.Name(id=name):
            return name
        case ast.Attribute(attr=name):
            return name
        case _:
            return None


def _writers_in(path: Path) -> set[str]:
    """`<module>.<function>` for each function in *path* that calls save_sprint."""
    tree = ast.parse(path.read_text(), filename=str(path))
    found = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        for inner in ast.walk(node):
            if isinstance(inner, ast.Call) and _callee_name(inner) == "save_sprint":
                found.add(f"{path.stem}.{node.name}")
    return found


def _all_writers() -> set[str]:
    writers = set()
    for paths in shipped_files_by_root(_PLUGIN_ROOT).values():
        for path in paths:
            writers |= _writers_in(path)
    return writers


def _has_main_block(path: Path) -> bool:
    tree = ast.parse(path.read_text(), filename=str(path))
    return any(
        isinstance(node, ast.If)
        and any(
            isinstance(sub, ast.Name) and sub.id == "__name__"
            for sub in ast.walk(node.test)
        )
        for node in tree.body
    )


def _imports_argparse(path: Path) -> bool:
    tree = ast.parse(path.read_text(), filename=str(path))
    return any(
        (isinstance(n, ast.ImportFrom) and n.module == "argparse")
        or (isinstance(n, ast.Import) and any(a.name == "argparse" for a in n.names))
        for n in ast.walk(tree)
    )


class TestSprintSaveHasNoEntrypointDoor(unittest.TestCase):
    """No `python3 sprint_save.py < payload` door exists to bypass the CLI."""

    def test_no_main_block(self):
        self.assertFalse(
            _has_main_block(_SPRINT_SAVE),
            "sprint_save gained a __main__ block — that is the second door the "
            "module docstring rules out; the re-slice preserve runs above run()",
        )

    def test_does_not_import_argparse(self):
        self.assertFalse(_imports_argparse(_SPRINT_SAVE))

    def test_the_matchers_find_a_door_where_one_exists(self):
        """Both matchers would pass vacuously if they matched nothing at all."""
        sprint_cli = _PLUGIN_ROOT / "smm" / "sprint_cli.py"
        self.assertTrue(_has_main_block(sprint_cli), "matcher found no __main__")
        self.assertTrue(_imports_argparse(sprint_cli), "matcher found no argparse")


class TestWholeSprintWritersAreEnumerated(unittest.TestCase):
    """Every function reaching the atomic write is one this pin has judged."""

    def test_no_unjudged_writer(self):
        unjudged = _all_writers() - _KNOWN_WRITERS.keys()
        self.assertEqual(
            unjudged,
            set(),
            f"new whole-sprint write path(s) {sorted(unjudged)} — if one takes a "
            "caller-supplied sprint it is a second door and the claim is false; "
            "if it edits state it loaded, add it to _KNOWN_WRITERS with that reason",
        )

    def test_every_judged_writer_still_exists(self):
        """A stale entry would silently shrink what the check above covers."""
        self.assertEqual(_KNOWN_WRITERS.keys() - _all_writers(), set())

    def test_the_scan_is_not_vacuous(self):
        self.assertGreaterEqual(
            len(_all_writers()),
            5,
            "expected at least the five known write paths — a scan matching "
            "nothing would make the check above certify nothing",
        )

    def test_the_scan_reaches_every_shipped_root(self):
        """The claim is corpus-wide, so a smm-only scan would under-cover it."""
        self.assertEqual(
            set(shipped_files_by_root(_PLUGIN_ROOT)),
            {"scripts", "smm", "skills"},
        )


class TestRunIsTheOnlyCallerSuppliedWriter(_SMMTestCase):
    """The discriminator: whose dict reaches the file.

    `run()` writes the sprint its caller handed it — that is what makes it the
    whole-sprint door. Every other writer merges into state it loaded from disk
    itself, so a caller cannot replace the file through one.
    """

    def _on_disk(self) -> dict:
        return json.loads((self.smm_dir / "sprint.json").read_text())

    def _seed_two_stories(self) -> None:
        sprint = make_sprint_dict(
            stories=[
                make_story_dict(id="story-001", file_domain=["src/a.py — a"]),
                make_story_dict(id="story-002", file_domain=["src/b.py — b"]),
            ]
        )
        sprint_store.save_sprint(self.smm_dir, sprint)

    def test_run_writes_the_callers_sprint_over_what_was_there(self):
        self._seed_two_stories()
        sprint_save.run(
            make_sprint_dict(
                stories=[make_story_dict(id="story-001", file_domain=["src/a.py — a"])]
            ),
            self.smm_dir,
        )
        ids = [s["id"] for s in self._on_disk()["stories"]]
        self.assertEqual(ids, ["story-001"], "run() must write the caller's dict")

    def test_edit_story_keeps_what_the_caller_never_supplied(self):
        self._seed_two_stories()
        sprint_store.edit_story(self.smm_dir, "story-001", {"context": "rewritten"})
        data = self._on_disk()
        ids = [s["id"] for s in data["stories"]]
        self.assertEqual(ids, ["story-001", "story-002"], "not a whole-sprint door")
        self.assertEqual(data["stories"][0]["context"], "rewritten")
        self.assertEqual(data["stories"][0]["title"], "User registration")


class TestKnownWritersTableIsHonest(unittest.TestCase):
    """Each judged writer names a real function, and gives a reason."""

    def test_every_entry_resolves_to_a_shipped_function(self):
        for qualified in _KNOWN_WRITERS:
            module, _, func = qualified.partition(".")
            path = _PLUGIN_ROOT / "smm" / f"{module}.py"
            self.assertTrue(path.is_file(), f"{rel(path, _REPO_ROOT)} is missing")
            tree = ast.parse(path.read_text(), filename=str(path))
            names = {
                n.name
                for n in ast.walk(tree)
                if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)
            }
            self.assertIn(func, names, f"{qualified} names no function")

    def test_every_entry_states_a_reason(self):
        for qualified, reason in _KNOWN_WRITERS.items():
            self.assertTrue(reason.strip(), f"{qualified} has no stated reason")


if __name__ == "__main__":
    unittest.main()
